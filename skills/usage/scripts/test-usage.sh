#!/usr/bin/env bash
# usage.sh against stub CLIs in a private HOME and PATH.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
export HOME="$WORK/home"
mkdir -p "$HOME/.bin" "$WORK/bin"
LOG="$WORK/calls"
export SNAPSHOT_JSON='{"schema":"quota-snapshot/1","store":{"age_seconds":179,"extra":true},"errors":{"meters.openai":"unavailable","storekeeper":"unavailable"},"extra":true}'
for name in token-usage token-tripwire; do
  cat > "$WORK/bin/$name" <<STUB
#!/bin/sh
echo "$name \$*" >> "$LOG"
if [ "$name" = token-usage ] && [ "\$1" = snapshot ]; then
  printf '%s\n' "\$SNAPSHOT_JSON"
  if [ -n "\${SNAPSHOT_STDERR:-}" ]; then printf '%s\n' "\$SNAPSHOT_STDERR" >&2; fi
  exit "\${SNAPSHOT_STATUS:-0}"
fi
case " \$* " in *" --json "*) echo '{"stub": "$name"}' ;; *) echo "$name output" ;; esac
STUB
  chmod +x "$WORK/bin/$name"
done
fail=0
check() { local what="$1"; shift; if "$@"; then echo "ok   $what"; else echo "FAIL $what"; fail=1; fi; }
BASEPATH="/usr/bin:/bin"

PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --project chaos > "$WORK/out"
check "fresh age is shown in whole minutes" grep -Fxq '(store scanned 2 min ago)' "$WORK/out"
check "fresh age has no warning" test "$(sed -n '/^!! /p' "$WORK/out")" = ""
check "project view uses exactly the read-only CLI calls" diff -u - "$LOG" <<'CALLS'
token-usage snapshot --no-scan
token-usage sessions --no-scan --project chaos
token-usage totals --no-scan --by project
token-usage totals --no-scan --by model
token-usage meters --no-scan
token-tripwire status
CALLS

: > "$LOG"
PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --fresh --day 2026-10-14 > /dev/null
check "--fresh scans once, before the read-only calls, and passes --day to totals" diff -u - "$LOG" <<'CALLS'
token-usage scan
token-usage snapshot --no-scan
token-usage sessions --no-scan
token-usage totals --no-scan --day 2026-10-14 --by project
token-usage totals --no-scan --day 2026-10-14 --by model
token-usage meters --no-scan
token-tripwire status
CALLS

PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --json > "$WORK/json" 2> "$WORK/err"
check "json combines all five, with the fresh store age" python3 -c '
import json, sys
with open(sys.argv[1]) as stream:
    doc = json.load(stream)
assert set(doc) == {"sessions", "totals_project", "totals_model", "meters", "incidents",
                    "store_age_minutes", "stale_note"}, doc
assert doc["store_age_minutes"] == 2 and doc["stale_note"] is None, doc
' "$WORK/json"
check "fresh json has no stderr warning" test ! -s "$WORK/err"

SNAPSHOT_JSON='{"schema":"quota-snapshot/1","store":{"age_seconds":1260},"errors":{}}' \
  PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" > "$WORK/out"
check "age over 20 minutes warns in the text view" grep -Fq '!! store last scanned 21 min ago' "$WORK/out"

SNAPSHOT_JSON='{"schema":"quota-snapshot/1","store":{"age_seconds":null},"errors":{}}' \
  PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" > "$WORK/out"
check "unknown age warns in the text view" grep -Fq '!! store age unknown' "$WORK/out"

UNKNOWN_NOTE='store age unknown (never scanned on this host, or unreadable)'
check_unknown() {
  local description="$1" snapshot="$2" note="${3:-$UNKNOWN_NOTE}"
  SNAPSHOT_JSON="$snapshot" PATH="$WORK/bin:$BASEPATH" "$HERE/usage.sh" --json > "$WORK/json" 2> "$WORK/err"
  check "$description yields unknown age in json" python3 -c '
import json, sys
with open(sys.argv[1]) as stream:
    doc = json.load(stream)
assert doc["store_age_minutes"] is None, doc
assert sys.argv[2] in doc["stale_note"], doc
' "$WORK/json" "$note"
  check "$description warns on stderr" grep -Fq "$note" "$WORK/err"
}
check_unknown "null age" '{"schema":"quota-snapshot/1","store":{"age_seconds":null},"errors":{}}'
check_unknown "missing store" '{"schema":"quota-snapshot/1","errors":{}}'
check_unknown "mistyped store" '{"schema":"quota-snapshot/1","store":[],"errors":{}}'
check_unknown "missing age" '{"schema":"quota-snapshot/1","store":{},"errors":{}}'
check_unknown "string age" '{"schema":"quota-snapshot/1","store":{"age_seconds":"125"},"errors":{}}'
check_unknown "fractional age" '{"schema":"quota-snapshot/1","store":{"age_seconds":125.5},"errors":{}}'
check_unknown "boolean age" '{"schema":"quota-snapshot/1","store":{"age_seconds":true},"errors":{}}'
check_unknown "negative age" '{"schema":"quota-snapshot/1","store":{"age_seconds":-1},"errors":{}}'
check_unknown "unknown schema name" '{"schema":"other-snapshot/1","store":{"age_seconds":125},"errors":{}}'
check_unknown "unknown schema major" '{"schema":"quota-snapshot/2","store":{"age_seconds":125},"errors":{}}'
check_unknown "non-JSON output" 'snapshot failed'
check_unknown "non-JSON constant" '{"schema":"quota-snapshot/1","store":{"age_seconds":125},"errors":{},"extra":NaN}'
check_unknown "JSON array" '[]'
check_unknown "missing errors" '{"schema":"quota-snapshot/1","store":{"age_seconds":125}}'
check_unknown "mistyped errors" '{"schema":"quota-snapshot/1","store":{"age_seconds":125},"errors":[]}'
check_unknown "store error" '{"schema":"quota-snapshot/1","store":{"age_seconds":125},"errors":{"store":"failed"}}'
check_unknown "store detail error" '{"schema":"quota-snapshot/1","store":{"age_seconds":125},"errors":{"store.read":"failed"}}'
SNAPSHOT_STATUS=1 SNAPSHOT_STDERR='token-usage: snapshot: unreadable config' \
  check_unknown "nonzero exit with valid JSON" "$SNAPSHOT_JSON"
SNAPSHOT_STATUS=2 SNAPSHOT_STDERR="token-usage: error: argument cmd: invalid choice: 'snapshot' (choose from 'scan', 'sessions', 'totals', 'meters', 'incidents', 'posture')" \
  check_unknown "missing snapshot subcommand" '' 'store age unknown (token-usage lacks snapshot): update token-usage'

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
