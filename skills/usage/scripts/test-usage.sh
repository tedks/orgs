#!/usr/bin/env bash
# usage.sh against stub CLIs in a private HOME and PATH.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
export HOME="$WORK/home"
mkdir -p "$HOME/.bin" "$WORK/bin"
LOG="$WORK/calls"
for name in token-usage token-tripwire; do
  cat > "$WORK/bin/$name" <<STUB
#!/bin/sh
echo "$name \$*" >> "$LOG"
case " \$* " in *" --json "*) echo '{"stub": "$name"}' ;; *) echo "$name output" ;; esac
STUB
  chmod +x "$WORK/bin/$name"
done
fail=0
check() { local what="$1"; shift; if "$@"; then echo "ok   $what"; else echo "FAIL $what"; fail=1; fi; }
BASEPATH="/usr/bin:/bin"

PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --project chaos > "$WORK/out"
check "an unknown store age is called out, not hidden" grep -q 'store age unknown' "$WORK/out"
check "sessions read without scanning, for the project" grep -qx 'token-usage sessions --no-scan --project chaos' "$LOG"
check "totals by project and model" grep -qx 'token-usage totals --no-scan --by model' "$LOG"
check "meters read" grep -qx 'token-usage meters --no-scan' "$LOG"
check "incidents read" grep -qx 'token-tripwire status' "$LOG"

: > "$LOG"
PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --fresh --day 2026-10-14 > /dev/null
check "--fresh scans" grep -qx 'token-usage scan' "$LOG"
check "--day passed to totals" grep -qx 'token-usage totals --no-scan --day 2026-10-14 --by project' "$LOG"

PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --json > "$WORK/json"
check "json combines all five, with the store age" python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert set(d) == {"sessions","totals_project","totals_model","meters","incidents","store_age_minutes","stale_note"} and d["stale_note"]' "$WORK/json"

: > "$LOG"
mv "$WORK/bin/token-usage" "$HOME/.bin/token-usage"
PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" > /dev/null
check "falls back to ~/.bin" grep -qx 'token-usage meters --no-scan' "$LOG"
rm "$HOME/.bin/token-usage"
if PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" 2>/dev/null; then rc=0; else rc=$?; fi
check "missing token-usage exits 3" [ "$rc" -eq 3 ]
if PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --day 14-10-2026 2>/dev/null; then rc=0; else rc=$?; fi
check "bad --day refused" [ "$rc" -eq 2 ]
if PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --project 2>/dev/null; then rc=0; else rc=$?; fi
check "--project without a value refused" [ "$rc" -eq 2 ]
if PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --project --json 2>/dev/null; then rc=0; else rc=$?; fi
check "an option is not taken as --project's value" [ "$rc" -eq 2 ]
if PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --help 2>/dev/null; then rc=0; else rc=$?; fi
check "--help exits 0" [ "$rc" -eq 0 ]
exit "$fail"
