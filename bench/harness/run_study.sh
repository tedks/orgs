#!/usr/bin/env bash
# run_study.sh — drive the six-regime ablation study SEQUENTIALLY (fairness:
# parallel runs contend for API/compute and corrupt the wall-clock metric).
# One background job; its completion re-invokes the CTO to collect results.
# Each regime is fully isolated by run_regime.py (fresh worktree + process).
# A failing regime is logged and the study CONTINUES (partial > stalled).
set -uo pipefail

cd /home/tedks/Projects/orgs/framework
logdir=bench-runs/study-logs
mkdir -p "$logdir"
started=$(date -u +%FT%TZ)
echo "STUDY START $started" | tee "$logdir/_study.log"

regimes=(
  r1-goal-native-review
  r2-goal-council
  r3-orgs-full
  r4-orgs-no-crystal
  r5-orgs-no-crystal-no-standup
  r6-orgs-no-decomp
)

for cfg in "${regimes[@]}"; do
  echo "=== $(date -u +%FT%TZ) START $cfg ===" | tee -a "$logdir/_study.log"
  python3 bench/harness/run_regime.py --config "bench/regimes/configs/$cfg.json" \
      > "$logdir/$cfg.log" 2>&1
  rc=$?
  echo "=== $(date -u +%FT%TZ) END   $cfg (exit $rc) ===" | tee -a "$logdir/_study.log"
done

echo "STUDY COMPLETE $(date -u +%FT%TZ) (began $started)" | tee -a "$logdir/_study.log"
