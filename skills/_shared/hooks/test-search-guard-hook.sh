#!/bin/bash
# Tests for the search-guard Claude Code PreToolUse hook.
#
# Feeds the hook the JSON Claude Code sends and asserts on deny/allow, with a
# scratch XDG_STATE_HOME so the real guard log is never touched.
# Do the same for any manual smoke test of the hook or the wrappers: export
# XDG_STATE_HOME=<scratch dir> first, or the refusals land in the live log
# and can trip the token-tripwire's broad-search alert.
# Run: bash skills/_shared/hooks/test-search-guard-hook.sh   (exits non-zero on failure)
# ok() never fails, so A && ok || bad is a safe if/else here; command
# strings are single-quoted on purpose (the hook must see them unexpanded).
# shellcheck disable=SC2015,SC2016
set -u
export HOME=${HOME:-/home/u}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="${HOOK_UNDER_TEST:-$HERE/search-guard.sh}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export XDG_STATE_HOME="$TMP/state"
H="$HOME"

pass=0 fail=0
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $*"; }

# hook TOOL INPUT_JSON CWD -> sets OUT, RC
hook() {
    local tool="$1" input="$2" cwd="$3"
    OUT="$(jq -nc --arg t "$tool" --argjson i "$input" --arg c "$cwd" \
        '{hook_event_name: "PreToolUse", tool_name: $t, tool_input: $i, cwd: $c, session_id: "sess-test"}' |
        PATH="${HOOK_RUNTIME_PATH:-$PATH}" bash "$HOOK")"
    RC=$?
}
bash_cmd() { hook Bash "$(jq -nc --arg c "$1" '{command: $c}')" "${2:-$H/Projects/example}"; }
denied() {
    if [ "$RC" -eq 0 ] && [ "$(jq -r '.hookSpecificOutput.permissionDecision // empty' <<<"$OUT" 2>/dev/null)" = deny ]; then
        ok
    else
        bad "$1: expected deny, rc=$RC out=$OUT"
    fi
}
allowed() {
    if [ "$RC" -eq 0 ] && [ -z "$OUT" ]; then ok; else bad "$1: expected allow, rc=$RC out=$OUT"; fi
}

[ -f "$HOOK" ] && ok || bad "hook missing: $HOOK"

# The measured shapes are denied, with a reason that names the fix.
bash_cmd "rg --files $H/Projects | rg '/ditz/.*md\$' | head"; denied "rg --files Projects"
reason="$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<<"$OUT" 2>/dev/null)"
case "$reason" in *search-guard*worktree*) ok ;; *) bad "reason does not name the fix: $reason" ;; esac
case "$reason" in *Grep*) ok ;; *) bad "reason does not point at the Grep/Glob tools: $reason" ;; esac
bash_cmd 'find ~ -maxdepth 6 -type d -path "*node_modules/@vendor/pkg" 2>/dev/null | head'; denied "find ~ -maxdepth 6"
bash_cmd 'cd ~ && rg foo'; denied "cd ~ && rg"
bash_cmd "ssh remote.example 'find / -name x'"; denied "ssh remote find"
bash_cmd 'rg foo' "$H"; denied "rg with no path from HOME"

# Scoped, bounded, overridden, unrelated: allowed, silently.
bash_cmd 'rg foo scripts'; allowed "scoped rg"
bash_cmd 'find ~ -maxdepth 2 -name x'; allowed "bounded find"
bash_cmd 'SEARCH_UNBOUNDED=1 find ~ -name x'; allowed "override"
bash_cmd 'git status && ls'; allowed "unrelated"
bash_cmd 'cd "$(git rev-parse --show-toplevel)" && rg foo' "$H"; allowed "cd to repo root"

# Grep and Glob tools.
hook Grep '{"pattern":"x","path":"'"$H"'"}' "$H/Projects/example"; denied "Grep over HOME"
hook Grep '{"pattern":"x","path":"'"$H"'","glob":"*.md"}' "$H/Projects/example"; denied "Grep over HOME with a glob"
hook Grep '{"pattern":"x","path":"'"$H"'/Projects/example"}' "$H"; allowed "Grep in a project"
hook Glob '{"pattern":"**/apksigner","path":"'"$H"'"}' "$H/Projects/example"; denied "Glob ** over HOME"
hook Glob '{"pattern":"example/**/*.sh","path":"'"$H"'/Projects"}' "$H"; allowed "Glob scoped by its literal prefix"
hook Read '{"file_path":"/etc/hostname"}' "$H"; allowed "other tools"

# Every refusal is logged once, with the session id from the hook input.
log="$XDG_STATE_HOME/search-guard/log"
n_denied=$(grep -c '"source":"claude-hook"' "$log" 2>/dev/null || echo 0)
[ "$n_denied" -eq 8 ] && ok || bad "expected 8 logged refusals, got $n_denied"
grep -q '"session":"sess-test"' "$log" && ok || bad "session id not logged"

# Fail open for a classification failure; fail CLOSED for a logging failure
# (the decision to refuse must not depend on whether it can be logged).
OUT="$(printf 'not json' | bash "$HOOK")"; RC=$?; allowed "malformed input"
mkdir -p "$TMP/nopy"; for t in cat readlink jq bash; do ln -s "$(command -v $t)" "$TMP/nopy/$t"; done
HOOK_RUNTIME_PATH="$TMP/nopy" bash_cmd 'find ~ -name x'; allowed "no python3"
XDG_STATE_HOME=/proc/nonexistent bash_cmd 'find ~ -name x'; denied "unwritable log still denies"

echo "search-guard hook: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
