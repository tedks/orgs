#!/usr/bin/env bash
# run_study.sh — drive the six-regime ablation study SEQUENTIALLY (fairness:
# parallel runs contend for API/compute and corrupt the wall-clock metric).
# One background job; its completion re-invokes the CTO to collect results.
# Each regime is fully isolated by run_regime.py (fresh worktree + process).
#
# A failing regime is logged and the study CONTINUES — a partial study beats a
# stalled one — but the driver's own exit status remembers it. An unattended
# run whose every arm crashed used to exit 0 and look successful to whatever
# scheduled it.
#
# The FIRST arm pins the study: its base sha and input hashes are passed to
# every later arm, which refuses to run if they have moved. Six arms are only
# comparable if they were built from the same commit against the same spec,
# exam, runbook and doctrine, and nothing about a drifted arm's manifest would
# look wrong afterwards.
set -uo pipefail

cd /home/tedks/Projects/orgs/framework || exit 2
logdir=bench-runs/study-logs
mkdir -p "$logdir"
started=$(date -u +%FT%TZ)
echo "STUDY START $started" | tee "$logdir/_study.log"

# Per-arm watchdog, sized from EACH ARM'S OWN configured bounds (see the
# per-arm computation in the loop below).
#
# One fixed bound across arms is not neutral. An arm with more review steps
# and more rounds has a longer LEGITIMATE ceiling — r3 needs 8.7h where r1
# needs 4.7h — so a single 5h watchdog would have killed exactly the
# review-heavy arms and spared the others, censoring the treatment under study
# and making "more review" look like "failed arm". Each arm asks
# run_regime.py what its own ceiling is and gets that plus a margin.
WATCHDOG_MARGIN=${WATCHDOG_MARGIN:-1800}       # 30 min over the arm's own bound

regimes=(
  r1-goal-native-review
  r2-goal-council
  r3-orgs-full
  r4-orgs-no-crystal
  r5-orgs-no-crystal-no-standup
  r6-orgs-no-decomp
)

# Pin the study to the base commit and the inputs as they stand right now.
base_sha=$(git rev-parse refs/heads/master) || exit 2
hashes=$(python3 - <<'PY'
import hashlib, json, pathlib
paths = {"spec": "docs/specs/2026-09-02-resp-tracer.md",
         "exam": "bench/conformance/resp_conformance.sh",
         "runbook": "protocol/RUNBOOK.md",
         "doctrine": "doctrine/DOCTRINE.md"}
print(json.dumps({k: hashlib.sha256(pathlib.Path(v).read_bytes()).hexdigest()
                  for k, v in paths.items()}))
PY
) || exit 2
printf '%s\n' "$hashes" > "$logdir/_study-pin.json"
echo "STUDY PIN base=$base_sha inputs=$logdir/_study-pin.json" \
    | tee -a "$logdir/_study.log"

failed=()
for cfg in "${regimes[@]}"; do
    # The arm's own worst case, from its own timeouts, plus a margin.
    arm_max=$(python3 bench/harness/run_regime.py \
                  --config "bench/regimes/configs/$cfg.json" \
                  --print-max-runtime 2>/dev/null) || arm_max=""
    case "$arm_max" in ''|*[!0-9]*) arm_max=32400 ;; esac   # 9h fallback
    arm_timeout=$(( arm_max + WATCHDOG_MARGIN ))
    echo "=== $(date -u +%FT%TZ) START $cfg (watchdog ${arm_timeout}s) ===" \
        | tee -a "$logdir/_study.log"
    timeout --kill-after=120 "$arm_timeout" \
        python3 bench/harness/run_regime.py \
            --config "bench/regimes/configs/$cfg.json" \
            --expect-base-sha "$base_sha" \
            --expect-input-hashes "@$logdir/_study-pin.json" \
        > "$logdir/$cfg.log" 2>&1
    rc=$?
    [ "$rc" -ne 0 ] && failed+=("$cfg(exit $rc)")
    [ "$rc" -eq 124 ] && echo "  !! $cfg hit its ${arm_timeout}s watchdog" \
        | tee -a "$logdir/_study.log"
    echo "=== $(date -u +%FT%TZ) END   $cfg (exit $rc) ===" \
        | tee -a "$logdir/_study.log"
done

echo "STUDY COMPLETE $(date -u +%FT%TZ) (began $started)" \
    | tee -a "$logdir/_study.log"
if [ ${#failed[@]} -gt 0 ]; then
    echo "STUDY: ${#failed[@]} of ${#regimes[@]} arm(s) did not exit 0: ${failed[*]}" \
        | tee -a "$logdir/_study.log"
    echo "  (exit 1 does NOT mean no data — read each arm's manifest.json;" \
        | tee -a "$logdir/_study.log"
    echo "   run_regime.py exits 1 when a run finished but recorded failures.)" \
        | tee -a "$logdir/_study.log"
    exit 1
fi
echo "STUDY: all ${#regimes[@]} arms exited 0" | tee -a "$logdir/_study.log"
