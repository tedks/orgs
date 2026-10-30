#!/usr/bin/env bash
# Lane usage from the installed token-usage / token-tripwire CLIs. Counts only.
set -euo pipefail

usage() {
  echo "Usage: usage.sh [--project NAME] [--day YYYY-MM-DD] [--fresh] [--json]" >&2
  exit "${1:-2}"
}
value() {  # an option's value must exist and must not be another option
  if [ $# -lt 2 ] || [ -z "$2" ] || [[ "$2" == -* ]]; then
    echo "usage.sh: $1 needs a value" >&2
    usage
  fi
}

project="" day="" fresh=false json=false
while [ $# -gt 0 ]; do
  case "$1" in
    --project) value "$@"; project="$2"; shift 2 ;;
    --day) value "$@"; day="$2"; shift 2 ;;
    --fresh) fresh=true; shift ;;
    --json) json=true; shift ;;
    -h|--help) usage 0 ;;
    *) usage ;;
  esac
done
if [ -n "$day" ] && ! [[ "$day" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "usage.sh: --day must be YYYY-MM-DD" >&2
  exit 2
fi

find_cli() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then command -v "$name"; return 0; fi
  if [ -x "$HOME/.bin/$name" ]; then echo "$HOME/.bin/$name"; return 0; fi
  return 1
}
if ! TU="$(find_cli token-usage)"; then
  echo "usage.sh: token-usage is not installed on this host (dotfiles scripts/usage)" >&2
  exit 3
fi
TW="$(find_cli token-tripwire || true)"

# How old is the store? Without a scan (and without the cron row) it can be
# hours stale, and an empty view would read as "no lanes running".
age_minutes() {
  python3 - "$TU" <<'PY' 2>/dev/null || echo unknown
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.realpath(sys.argv[1])))
import token_usage as tu
path = tu.Store(tu.load_config()).state_path
print(int((time.time() - os.stat(path).st_mtime) // 60))
PY
}
if $fresh; then "$TU" scan > /dev/null; fi
age="$(age_minutes)"
if [ "$age" = unknown ]; then
  stale_note="store age unknown (never scanned on this host, or unreadable): run with --fresh (and enable the cron row)"
elif [ "$age" -gt 20 ]; then
  stale_note="store last scanned ${age} min ago: numbers are that old; run with --fresh, and check the token-tripwire cron row (install-token-tripwire --enable)"
else
  stale_note=""
fi
scan=(--no-scan)  # --fresh scanned once, just above
sessions=("$TU" sessions "${scan[@]}")
[ -n "$project" ] && sessions+=(--project "$project")
totals=("$TU" totals --no-scan)
[ -n "$day" ] && totals+=(--day "$day")

if $json; then
  # Each view goes through a private file: outputs can exceed an argument's size limit.
  dir="$(mktemp -d)"
  trap 'rm -rf -- "$dir"' EXIT
  "${sessions[@]}" --json > "$dir/sessions"
  "${totals[@]}" --by project --json > "$dir/totals_project"
  "${totals[@]}" --by model --json > "$dir/totals_model"
  "$TU" meters --no-scan --json > "$dir/meters"
  if [ -n "$TW" ]; then "$TW" status --json > "$dir/incidents"; else echo null > "$dir/incidents"; fi
  python3 -c 'import json, os, sys
names = ("sessions", "totals_project", "totals_model", "meters", "incidents")
out = {}
for name in names:
    with open(os.path.join(sys.argv[1], name)) as stream:
        out[name] = json.load(stream)
age = sys.argv[2]
out["store_age_minutes"] = None if age == "unknown" else int(age)
out["stale_note"] = sys.argv[3] or None
print(json.dumps(out, indent=1))' "$dir" "$age" "$stale_note"
  [ -n "$stale_note" ] && echo "usage.sh: $stale_note" >&2
  exit 0
fi

if [ -n "$stale_note" ]; then
  echo "!! $stale_note"
  echo
else
  echo "(store scanned ${age} min ago)"
fi
echo "== Sessions, last 60 min${project:+ (project $project)} =="
"${sessions[@]}"
echo
echo "== Totals by project${day:+ ($day)} =="
"${totals[@]}" --by project
echo
echo "== Totals by model${day:+ ($day)} =="
"${totals[@]}" --by model
echo
echo "== Quota meters (account-wide; note the observed time) =="
"$TU" meters --no-scan
echo
if [ -n "$TW" ]; then
  echo "== Tripwire incidents =="
  "$TW" status
else
  echo "(token-tripwire not installed: no incident state)"
fi
