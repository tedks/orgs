#!/usr/bin/env bash
# Tests for search-wrapper (installed as ~/.bin/{rg,find,grep}).
# Run: bash skills/_shared/search-guard/tests/test-search-wrapper.sh
#
# Every case runs under `env -i` with a fake HOME, fake "real" binaries that
# just print their argv, and an explicit agent marker or none, so the result
# does not depend on the shell running the test (which is often an agent).
# The scripts below are run by a child shell: their $HOME must not expand here.
# shellcheck disable=SC2016
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/search-wrapper" ] || HERE="$(cd "$HERE/.." && pwd)"
WRAPPER="$HERE/search-wrapper"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BIN="$TMP/bin" REAL="$TMP/real" H="$TMP/home" STATE="$TMP/state"
mkdir -p "$BIN" "$REAL" "$H/Projects/repo" "$STATE"
for n in rg find grep; do
    ln -s "$WRAPPER" "$BIN/$n"
    printf '#!/bin/sh\nif [ "${FAKE_NESTED:-}" = 1 ] && [ "%s" = find ]; then grep -n needle file; exit; fi\necho "REAL %s $*"\nexit ${FAKE_EXIT:-0}\n' "$n" "$n" > "$REAL/$n"
    chmod +x "$REAL/$n"
done
PY="$(command -v python3)"
# A stand-in agent harness. /proc/<pid>/comm of a script is its file name, so
# this looks like Codex to the parent check. It runs `bash -c SCRIPT` as a
# child (the trailing exit stops sh exec'ing bash in its place), and bash in
# turn execs a lone simple command in place: the wrapper's parent is then this
# harness, which is exactly the shape `codex` -> `bash -lc 'find ~'` produces.
mkdir -p "$TMP/harness"
printf '#!/bin/sh\n/bin/bash -c "$1"\nrc=$?\nexit $rc\n' > "$TMP/harness/codex"
chmod +x "$TMP/harness/codex"
HARNESS="$TMP/harness/codex"
SYSPATH="$BIN:$REAL:$(dirname "$PY"):/usr/bin:/bin"

pass=0 fail=0
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $*"; }

# run MARKER CWD SCRIPT [extra env...]: runs SCRIPT the way an agent harness
# does (harness -> bash -c SCRIPT), stdin from /dev/null. Sets OUT, ERR, RC.
run() {
    local marker="$1" cwd="$2" script="$3"
    shift 3
    local -a envs=(HOME="$H" PATH="$SYSPATH" XDG_STATE_HOME="$STATE" PWD="$cwd")
    [ -n "$marker" ] && envs+=("$marker")
    OUT="$(cd "$cwd" && env -i "${envs[@]}" "$@" "$HARNESS" "$script" </dev/null 2>"$TMP/err")"
    RC=$?
    ERR="$(cat "$TMP/err")"
}

expect_real() {
    local label="$1"
    if [ "$RC" -eq 0 ] && [[ "$OUT" == REAL* ]]; then ok; else bad "$label: expected pass-through, rc=$RC out=$OUT err=$ERR"; fi
}
expect_refused() {
    local label="$1"
    if [ "$RC" -eq 2 ] && [ -z "$OUT" ] && [[ "$ERR" == search-guard:* ]]; then ok; else bad "$label: expected refusal, rc=$RC out=$OUT err=$ERR"; fi
}

# 1. No agent marker: untouched, even for the worst shape.
run "" "$H" 'find "$HOME" -name x'
expect_real "no marker"

# Installed compatibility launchers may delegate under a different basename.
ln -s "$WRAPPER" "$H/search-wrapper"
run CODEX_THREAD_ID=abc "$H/Projects/repo"     'SEARCH_GUARD_WRAPPED_NAME=rg "$HOME/search-wrapper" --files "$HOME/Projects"'
expect_refused "delegated rg name"

# A separate installed proxy must be skipped as a PATH candidate without
# marking the command classified; otherwise it loops or silently allows it.
cat > "$TMP/proxy" <<'SH'
#!/bin/sh
SEARCH_GUARD_WRAPPED_NAME=${0##*/}
SEARCH_GUARD_PROXY_SEEN=${SEARCH_GUARD_PROXY_SEEN:-}:$0
export SEARCH_GUARD_WRAPPED_NAME SEARCH_GUARD_PROXY_SEEN
exec "$SHARED_SEARCH_WRAPPER" "$@"
SH
chmod +x "$TMP/proxy"
for n in rg find grep; do ln -sf "$TMP/proxy" "$BIN/$n"; done
run "" "$H/Projects/repo" 'find --version' SHARED_SEARCH_WRAPPER="$WRAPPER"
expect_real "installed proxy reaches real find"
run CODEX_THREAD_ID=abc "$H/Projects/repo" 'find "$HOME" -name x' SHARED_SEARCH_WRAPPER="$WRAPPER"
expect_refused "installed proxy still classifies broad find"
for n in rg find grep; do ln -sf "$WRAPPER" "$BIN/$n"; done
run "" "$H/Projects/repo" 'SEARCH_GUARD_WRAPPED_NAME=find "$HOME/search-wrapper" . -name x' FAKE_NESTED=1
if [ "$RC" -eq 0 ] && [[ "$OUT" == 'REAL grep -n needle file' ]]; then ok; else bad "nested grep retains its own tool name: rc=$RC out=$OUT err=$ERR"; fi

# 2. Each marker turns the guard on.
for m in CLAUDECODE=1 CODEX_THREAD_ID=abc CODEX_SESSION_ID=abc GEMINI_CLI=1 OPENCODE=1; do
    run "$m" "$H/Projects/repo" 'find "$HOME" -name x'
    expect_refused "marker $m"
done

# 2b. Both parent shapes: a lone command (bash execs it; parent = harness) and
#     a compound one (parent = the bash -c shell).
run CLAUDECODE=1 "$H/Projects/repo" 'true; find "$HOME" -name x'
expect_refused "compound -c string"
run CLAUDECODE=1 "$H/Projects/repo" 'find "$HOME" -name x | head -1; exit ${PIPESTATUS[0]}'
expect_refused "pipeline"

# 3. The refusal is logged with what the tripwire needs.
rm -f "$STATE/search-guard/log"
run CLAUDECODE=1 "$H/Projects/repo" 'rg --files "$HOME/Projects"' CLAUDE_CODE_SESSION_ID=sess-1 TMUX_PANE=%9
expect_refused "rg --files Projects"
if "$PY" - "$STATE/search-guard/log" "$H" <<'EOF'
import json, sys
recs = [json.loads(l) for l in open(sys.argv[1])]
assert len(recs) == 1, recs
r = recs[0]
assert r["tool"] == "rg" and r["root"] == sys.argv[2] + "/Projects", r
assert r["session"] == "sess-1" and r["harness"] == "claude" and r["pane"] == "%9", r
assert r["source"] == "wrapper" and r["argv"][:2] == ["rg", "--files"], r
EOF
then ok; else bad "log record"; fi

# 4. Scoped, bounded, overridden: all pass.
run CLAUDECODE=1 "$H" 'find "$HOME/Projects/repo" -name x'
expect_real "scoped find"
run CLAUDECODE=1 "$H/Projects/repo" 'find "$HOME" -maxdepth 2 -name x'
expect_real "bounded find"
run CLAUDECODE=1 "$H/Projects/repo" 'rg --max-depth 2 foo "$HOME/Projects"'
expect_real "rg with --max-depth 2"
run CLAUDECODE=1 "$H/Projects/repo" 'rg -g "*.md" foo "$HOME/Projects"'
expect_refused "rg with a glob still walks"
run CLAUDECODE=1 "$H/Projects/repo" 'grep -rn foo .'
expect_real "grep -r in a repo"
run CLAUDECODE=1 "$H/Projects/repo" 'SEARCH_UNBOUNDED=1 find "$HOME" -name x'
expect_real "override"

# 5. The cwd counts when no path is given; a piped stdin is what rg searches.
run CLAUDECODE=1 "$H" 'rg foo'
expect_refused "rg from HOME with no path"
run CLAUDECODE=1 "$H" 'echo hi | rg foo'
expect_real "rg reading a pipe"
run CLAUDECODE=1 "$H/Projects/repo" 'find .. -name x'
expect_refused "find .. from a project"
run CLAUDECODE=1 "$H/Projects/repo" 'grep -r foo /'
expect_refused "grep -r /"

# 5b. Short-option bundles still count as recursive; a plain grep never walks.
run CLAUDECODE=1 "$H" 'grep -nRi foo'
expect_refused "grep -nRi from HOME"
run CLAUDECODE=1 "$H" 'grep -n foo "$HOME/x"'
expect_real "plain grep from HOME"

# 6. A script the agent runs is not the agent's command line.
printf 'find "$HOME" -name x\n' > "$TMP/script.sh"
run CLAUDECODE=1 "$H/Projects/repo" "bash $TMP/script.sh"
expect_real "nested script"

# 7. Every broad root the classifier knows is caught by the shell prefilter.
#    (A root missing from the prefilter would silently pass through.)
roots="$(HOME="$H" "$PY" -c "import sys; sys.path.insert(0, '$HERE'); import search_guard as g; print('\n'.join(sorted(g.broad_roots('$H'))))")"
while IFS= read -r r; do
    run CLAUDECODE=1 "$H/Projects/repo" "find '$r' -name x"
    expect_refused "prefilter root $r"
done <<< "$roots"

# 8. Fail open: a python3 that fails, and one that is missing.
mkdir -p "$TMP/badpy"
printf '#!/bin/sh\nexit 1\n' > "$TMP/badpy/python3"; chmod +x "$TMP/badpy/python3"
OUT="$(cd "$H" && env -i HOME="$H" PATH="$BIN:$REAL:$TMP/badpy:/usr/bin:/bin" CLAUDECODE=1 "$HARNESS" 'find "$HOME" -name x' </dev/null 2>/dev/null)"; RC=$?
expect_real "broken python3"
# Only readlink on PATH, so the wrapper gets as far as looking for python3.
mkdir -p "$TMP/nopy"; ln -s "$(command -v readlink)" "$TMP/nopy/readlink"
OUT="$(cd "$H" && env -i HOME="$H" PATH="$BIN:$REAL:$TMP/nopy" CLAUDECODE=1 "$HARNESS" 'find "$HOME" -name x' </dev/null 2>/dev/null)"; RC=$?
expect_real "no python3 on PATH"

# 9. The real binary's exit status comes through, and a missing one is 127.
run "" "$H" 'grep foo bar' FAKE_EXIT=3
if [ "$RC" -eq 3 ]; then ok; else bad "exit status propagation: rc=$RC"; fi
OUT="$(env -i HOME="$H" PATH="$BIN" /bin/sh -c 'rg foo' </dev/null 2>"$TMP/err")"; RC=$?
if [ "$RC" -eq 127 ] && grep -q 'no rg on PATH' "$TMP/err"; then ok; else bad "missing real binary: rc=$RC"; fi

# 10. The wrapper on PATH twice (or via another link) never finds itself.
mkdir -p "$TMP/bin2"; ln -s "$BIN/rg" "$TMP/bin2/rg"
OUT="$(env -i HOME="$H" PATH="$TMP/bin2:$BIN:$REAL:/usr/bin:/bin" /bin/sh -c 'rg foo x' </dev/null)"; RC=$?
expect_real "self-skip through a second link"

# 11. A human at a terminal is never stopped, marker or not.
if command -v script >/dev/null; then
    OUT="$(cd "$H" && env -i HOME="$H" PATH="$SYSPATH" CLAUDECODE=1 TERM=dumb \
        script -qec 'find "$HOME" -name x' /dev/null </dev/null | tr -d '\r')"; RC=$?
    # script(1) gives the command a pty for stdin and stdout.
    if [[ "$OUT" == REAL* ]]; then ok; else bad "tty pass-through: $OUT"; fi
else
    echo "SKIP: tty pass-through (no script(1))"
fi

# 12. Two COPIES of the wrapper on PATH (a feature worktree's .bin ahead of
#     ~/.bin) must not exec each other forever -- for any caller.
mkdir -p "$TMP/copyA" "$TMP/copyB"
cp "$WRAPPER" "$TMP/copyA/grep"; cp "$WRAPPER" "$TMP/copyB/grep"
cp "$HERE/search_guard.py" "$TMP/copyA/"; cp "$HERE/search_guard.py" "$TMP/copyB/"
OUT="$(env -i HOME="$H" PATH="$TMP/copyA:$TMP/copyB:$REAL:/usr/bin:/bin" timeout 5 /bin/sh -c 'grep foo bar' </dev/null)"; RC=$?
expect_real "two wrapper copies, no marker"
OUT="$(cd "$H" && env -i HOME="$H" PATH="$TMP/copyA:$TMP/copyB:$REAL:/usr/bin:/bin" CLAUDECODE=1 timeout 5 "$HARNESS" 'grep -r foo "$HOME"' </dev/null 2>"$TMP/err")"; RC=$?; ERR="$(cat "$TMP/err")"
expect_refused "two wrapper copies, agent"

# 13. A wrapper whose search_guard.py is missing: python exits 2 for "can't
#     open file", which must not read as a refusal.
mkdir -p "$TMP/lone"; cp "$WRAPPER" "$TMP/lone/find"
OUT="$(cd "$H" && env -i HOME="$H" PATH="$TMP/lone:$REAL:/usr/bin:/bin" CLAUDECODE=1 "$HARNESS" 'find "$HOME" -name x' </dev/null 2>/dev/null)"; RC=$?
expect_real "search_guard.py missing"

# 14. Non-canonical spellings of a broad root still reach the classifier.
for spelling in '//' '/.' '/tmp/.' '/tmp//' '$HOME/.' '$HOME//' '$HOME/Projects/.' '/nix/store/.'; do
    run CLAUDECODE=1 "$H/Projects/repo" "find $spelling -name x"
    expect_refused "spelling $spelling"
done

# 15. A program between the agent's shell and the search: it passes.
run CLAUDECODE=1 "$H/Projects/repo" "python3 -c 'import subprocess,sys; sys.exit(subprocess.run(\"find \$HOME -name x\", shell=True).returncode)'"
expect_real "python shell=True"
run CLAUDECODE=1 "$H/Projects/repo" 'echo "$HOME" | xargs -I{} sh -c "find {} -name x"'
expect_real "xargs sh -c"

# 16. No python3 at all: silent, and the search runs.
OUT="$(cd "$H" && env -i HOME="$H" PATH="$BIN:$REAL:$TMP/nopy" CLAUDECODE=1 "$HARNESS" 'find "$HOME" -name x' </dev/null 2>"$TMP/err")"; RC=$?
if [ ! -s "$TMP/err" ]; then ok; else bad "no python3 is not silent: $(cat "$TMP/err")"; fi

# 17. The guard log cannot be written (a full disk): the refusal still
#     happens, with the actionable hint AND an extra line on stderr saying
#     the log was skipped. expect_refused only checks that $ERR starts with
#     "search-guard:", which the skipped-log line alone would satisfy, so
#     check for the hint by name too.
run CLAUDECODE=1 "$H/Projects/repo" 'find "$HOME" -name x' XDG_STATE_HOME=/proc/nonexistent
expect_refused "unwritable log still refuses"
if [[ "$ERR" == *"search-guard: refused"* ]]; then ok; else bad "no refusal hint: $ERR"; fi
if [[ "$ERR" == *"could not write the log"* ]]; then ok; else bad "no note about the skipped log: $ERR"; fi

echo "search-wrapper: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
