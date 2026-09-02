#!/usr/bin/env bash
# run-bench.sh — orchestrate one bench run and write its immutable manifest.
#
# v0 scope: this sets up the run directory, seeds a manifest from the schema,
# and (when a built target + conformance exam exist) runs the exam and records
# grading. It does NOT itself drive the agent org — a `protocol` run is
# performed by launching the org per bindings/claude-code.md; this harness is
# the measurement wrapper around it, so cost is recorded on the same footing
# for every regime. The agent-driving glue is deferred until v0.9 has a
# server to grade (see README "v0 scope").
#
# Usage:
#   run-bench.sh --regime <raw|native|protocol> --target <name> \
#                [--event <kind>] [--ablation <name>] [--server <cmd...>]
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
bench_root=$(cd "$here/.." && pwd)

regime="" target="" event="" ablation="" server_cmd=()
while [ $# -gt 0 ]; do
    case "$1" in
        --regime)   regime=$2; shift 2 ;;
        --target)   target=$2; shift 2 ;;
        --event)    event=$2; shift 2 ;;
        --ablation) ablation=$2; shift 2 ;;
        --server)   shift; server_cmd=("$@"); break ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
[ -n "$regime" ] && [ -n "$target" ] || { echo "usage: run-bench.sh --regime <r> --target <t> [--event k] [--ablation a] [--server cmd...]" >&2; exit 2; }
case "$regime" in raw|native|protocol) ;; *) echo "bad regime: $regime" >&2; exit 2 ;; esac

git_rev=$(git -C "$bench_root" rev-parse --short HEAD 2>/dev/null || echo unknown)
run_id="$(date -u +%Y-%m-%dT%H%MZ)-${regime}-${target}-$$"
run_dir="$bench_root/runs/$run_id"
mkdir -p "$run_dir"

manifest="$run_dir/manifest.json"
# Build the optional JSON fragments explicitly (a single ${x:+..}${x:-..}
# expansion cannot express if/else — when x is set, :- still yields its
# value, which corrupts the JSON).
if [ -n "$event" ]; then
    event_json="{\"kind\": \"$event\", \"injected_at\": \"TODO\"}"
else
    event_json="null"
fi
if [ -n "$ablation" ]; then ablation_json="\"$ablation\""; else ablation_json="null"; fi

# Seed the manifest. Cost/grading fields are filled by the run and the exam;
# an unfinished run leaves them at their zero/null defaults — visibly partial,
# never silently absent.
cat > "$manifest" <<JSON
{
  "run_id": "$run_id",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "ended_at": null,
  "regime": "$regime",
  "target": "$target",
  "git_revision": "$git_rev",
  "injected_event": $event_json,
  "ablation": $ablation_json,
  "models": {},
  "cost": {
    "coordination_tokens": 0, "product_tokens": 0, "model_calls": 0,
    "wall_clock_seconds": 0, "human_intervention_minutes": 0, "lead_wait_seconds": null
  },
  "grading": {
    "conformance_total": 0, "conformance_passed": 0,
    "malformed_total": null, "malformed_passed": null,
    "escaped_defects": null, "fix_introduced_regressions": null,
    "recovery_seconds_after_restart": null
  },
  "meta_product_ratio": null,
  "artifacts": {},
  "notes": "seeded by run-bench.sh; agent-driving glue is deferred (v0 scaffold)"
}
JSON

echo "run dir:  $run_dir"
echo "manifest: $manifest"

# If a server command was given and the target's conformance exam exists, grade.
exam="$bench_root/conformance/${target}_conformance.sh"
if [ "${#server_cmd[@]}" -gt 0 ] && [ -x "$exam" ]; then
    echo "grading via $exam ..."
    start=$(date +%s)
    if "$exam" "${server_cmd[@]}" > "$run_dir/conformance.log" 2>&1; then
        grade_ok=1; else grade_ok=0; fi
    dur=$(( $(date +%s) - start ))
    line=$(grep -E 'conformance: [0-9]+ passed' "$run_dir/conformance.log" | tail -1 || true)
    passed=$(sed -n 's/.*conformance: \([0-9]*\) passed.*/\1/p' <<<"$line"); passed=${passed:-0}
    failed=$(sed -n 's/.*passed, \([0-9]*\) failed.*/\1/p' <<<"$line"); failed=${failed:-0}
    total=$(( passed + failed ))
    echo "graded: $passed/$total passed (ok=$grade_ok) in ${dur}s — see conformance.log"
    echo "  (record these in $manifest under grading; automated write-back is v1)"
else
    echo "no --server or no exam at $exam; manifest seeded only (scaffold)."
fi
