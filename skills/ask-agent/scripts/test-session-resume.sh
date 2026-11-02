#!/bin/bash
# test-session-resume.sh - tripwire for agent-query.sh's --resume / --session-id-file
#
# Runs the REAL agent-query.sh against stub `claude`, `codex` and `agy`
# executables on PATH. No network, no API calls, no agent state touched.
#
# What it is guarding, in rough order of how badly it would hurt:
#
#   1. A resume that does not resume, silently. agy answers an unknown
#      conversation id by starting a NEW conversation and exiting 0, so the
#      script compares the id agy logged against the one it asked for. If that
#      comparison ever stops firing, a fixpoint council goes cold with no
#      signal at all -- the reviewer just quietly forgets rounds 1..n-1.
#   2. The wrong id in --session-id-file, in either direction. A round that
#      cannot determine an id must leave the file EMPTY -- otherwise the next
#      round chains onto the PREVIOUS round's session and looks perfectly
#      healthy while answering into the wrong thread. But a run that never
#      reached an agent at all must leave the file ALONE, or a typo throws away
#      a warm seat that cost real money to build.
#   3. Argv mapping per agent, including the negative: a plain query must not
#      grow --log-file / --session-id, or every existing caller changes
#      behaviour at once.
#   4. The codex capture path, which is the only path that gave up `exec`, so
#      it is the only one that can drop the reply, lose the exit status, or
#      orphan a child under `timeout`.
#   5. Bookkeeping never outranking the reply. The id is recorded in front of
#      the reply on the agy path, under `set -e`, with the reply's capture file
#      already unlinked -- so a failure there must not be able to abort the
#      script, or the answer is gone for good.
#
# Run after touching option parsing, the per-agent command build, the agy log
# handling, or the tail of the script:
#
#     .claude/skills/ask-agent/scripts/test-session-resume.sh

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/agent-query.sh"
[[ -x "$SRC" ]] || { echo "not executable: $SRC" >&2; exit 2; }

T="$(mktemp -d /tmp/test-session-resume.XXXXXX)"
trap 'rm -r -f -- "$T"' EXIT
BIN="$T/bin"; mkdir -p "$BIN"
printf 'probe prompt\n' > "$T/prompt.txt"

checked=0
fails=0
skipped=0

# Every stub records its full argv, one arg per line, so assertions can look for
# exact adjacent pairs rather than substring-matching a flattened string.
cat > "$BIN/claude" <<'STUB'
#!/bin/bash
printf '%s\n' "$@" > "$STUB_ARGV"
cat > /dev/null            # drain the piped prompt like the real CLI does
printf 'claude reply\n'
exit "${STUB_RC:-0}"
STUB

cat > "$BIN/codex" <<'STUB'
#!/bin/bash
printf '%s\n' "$@" > "$STUB_ARGV"
stub_prompt="$(cat)"
if [[ -n "${STUB_SLOW_BANNER:-}" ]]; then
    # codex exits NOW; the banner reaches tee a second later from a child that
    # kept stderr. Deterministic, no reliance on machine load.
    { sleep 1
      echo "OpenAI Codex v0.0.0-stub"
      echo "--------"
      echo "session id: ${STUB_SID:-11111111-2222-4333-8444-555555555555}"
      echo "--------"
      # exec: so the recorded $! IS the sleep, and killing it cannot leave a
      # foreground child of the subshell running on past the suite.
      exec sleep 2
    } >&2 &
    echo "$!" > "$STUB_ORPHAN_PIDFILE"
    printf 'codex reply\n'
    exit "${STUB_RC:-0}"
fi
# The real codex puts its banner -- AND its echo of the prompt and reply -- on
# stderr, and ONLY the reply on stdout. The stub reproduces both halves of that,
# because the capture path depends on the split AND on the ordering: the banner
# sits between two delimiter lines, the prompt echo comes after the second one.
# Echoing the prompt is not decoration -- without it the "a prompt cannot supply
# its own session id" case below is vacuous.
{
  echo "OpenAI Codex v0.0.0-stub"
  echo "--------"
  [[ -n "${STUB_NO_BANNER:-}" ]] || echo "session id: ${STUB_SID:-11111111-2222-4333-8444-555555555555}"
  echo "--------"
  echo "user"
  printf '%s\n' "$stub_prompt"
  echo "codex"
} >&2
if [[ -n "${STUB_SLEEP:-}" ]]; then
    echo "$$" > "$STUB_PIDFILE"
    # exec, so the pid the test watches IS the sleep. Without it the stub's
    # death leaves the sleep orphaned for its full 30s on every suite run, and
    # the "did the child die?" assertion watches the wrong process.
    exec sleep "$STUB_SLEEP"
fi
# A descendant that outlives codex and keeps stderr -- an MCP server, a sandbox
# helper, a command the model backgrounded. It pins tee's pipe open.
if [[ -n "${STUB_ORPHAN:-}" ]]; then
    sleep "$STUB_ORPHAN" &
    echo "$!" > "$STUB_ORPHAN_PIDFILE"
fi
printf 'codex reply\n'
exit "${STUB_RC:-0}"
STUB

cat > "$BIN/agy" <<'STUB'
#!/bin/bash
printf '%s\n' "$@" > "$STUB_ARGV"
dir=""; log=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --add-dir)  dir="$2";  shift 2;;
    --log-file) log="$2";  shift 2;;
    -p)         shift 2;;
    *)          shift;;
  esac
done
if [[ -n "$log" ]]; then
    echo "I0101 00:00:00.000000 1 printmode.go:104] Print mode: starting (promptLength=1, model=\"\", conversationID=\"\")" > "$log"
    [[ -n "${STUB_NO_CONV:-}" ]] || \
      echo "I0101 00:00:00.000001 1 printmode.go:209] Print mode: conversation=${STUB_CONV:-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee}, sending message" >> "$log"
fi
M="$(tail -1 "$dir/prompt.txt")"
# Simulates the sid destination going read-only DURING the run (a full /tmp, a
# remount, a quota): the startup writability proof has already passed, so only
# the final rename fails.
[[ -n "${STUB_LOCKDIR:-}" ]] && chmod 0500 "$STUB_LOCKDIR"
# Replace the scratch file with a directory, so the printf into it fails while
# the destination stays perfectly writable.
if [[ -n "${STUB_DIRIFY_TMP:-}" ]]; then
    for f in "$STUB_DIRIFY_TMP"/.ask-agent-sid.*; do
        [[ -f "$f" ]] || continue
        rm -f "$f" && mkdir -p "$f"
    done
fi
# Turn the DESTINATION into a directory after the -d check has already passed.
[[ -n "${STUB_MKDIR_SID:-}" ]] && mkdir -p "$STUB_MKDIR_SID"
if [[ -n "${STUB_NO_MARKER:-}" ]]; then printf 'agy reply\n'; else printf 'agy reply\n\n%s\n' "$M"; fi
exit "${STUB_RC:-0}"
STUB
chmod +x "$BIN"/claude "$BIN"/codex "$BIN"/agy

ok() { checked=$(( checked + 1 )); printf '    %-42s OK\n' "$1"; }
bad() {
    checked=$(( checked + 1 )); fails=$(( fails + 1 ))
    printf '    %-42s FAIL  %s\n' "$1" "$2" >&2
}
is() { [[ "$2" == "$3" ]] && ok "$1" || bad "$1" "got [$2] want [$3]"; }
has() { [[ "$2" == *"$3"* ]] && ok "$1" || bad "$1" "[$2] lacks [$3]"; }
hasnt() { [[ "$2" != *"$3"* ]] && ok "$1" || bad "$1" "[$2] unexpectedly holds [$3]"; }

# run <agent> [args...]  -> sets rc, out, err, argv (newline-joined stub argv)
run() {
    local agent="$1"; shift
    : > "$T/argv"
    PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
        "$SRC" "$agent" "$@" -f "$T/prompt.txt" > "$T/out" 2> "$T/err"
    rc=$?
    out="$(cat "$T/out")"; err="$(cat "$T/err")"; argv="$(cat "$T/argv")"
}
# adjacent <flag> <value> -- true only if <value> is the line immediately after
# the FIRST <flag> line. Not `grep -A1 | grep`: that searches both lines of the
# window, so a value equal to the flag would match itself.
adjacent() {
    local n
    n="$(grep -n -x -F -e "$1" "$T/argv" 2>/dev/null | head -1 | cut -d: -f1)"
    [[ -n "$n" ]] || return 1
    [[ "$(sed -n "$((n + 1))p" "$T/argv")" == "$2" ]]
}

echo "  option validation (nothing should reach an agent):"
for badid in "-m" "a b" "" "x;y" "../etc"; do
    run codex --resume "$badid"
    if (( rc == 1 )) && [[ -z "$argv" ]]; then ok "rejects --resume [$badid]"
    else bad "rejects --resume [$badid]" "rc=$rc argv=[$argv]"; fi
done
run codex --session-id-file "$T/no/such/dir/sid"
if (( rc == 1 )) && [[ -z "$argv" ]]; then ok "rejects unwritable --session-id-file"
else bad "rejects unwritable --session-id-file" "rc=$rc"; fi

echo "  argv mapping:"
run claude
hasnt "claude plain: no --session-id"          "$argv" "--session-id"
hasnt "claude plain: no --resume"              "$argv" "--resume"
run claude --resume 1e5a4dcb-0000-4000-8000-000000000001 --session-id-file "$T/sid"
adjacent --resume 1e5a4dcb-0000-4000-8000-000000000001 \
  && ok "claude resume: --resume <id>" || bad "claude resume: --resume <id>" "$argv"
is "claude resume: sid file echoes the id" "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-000000000001"

run claude --session-id-file "$T/sid"
minted="$(cat "$T/sid")"
if [[ "$minted" =~ ^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$ ]]; then
    ok "claude fresh: mints a real uuid"
else bad "claude fresh: mints a real uuid" "got [$minted]"; fi
adjacent --session-id "$minted" \
  && ok "claude fresh: passes the minted id" || bad "claude fresh: passes the minted id" "$argv"

run codex
is "codex plain: argv is exec -" "$argv" "$(printf 'exec\n-')"
run codex --resume 1e5a4dcb-0000-4000-8000-000000000002 --session-id-file "$T/sid"
is "codex resume: argv is exec resume <id> -" "$argv" \
   "$(printf 'exec\nresume\n1e5a4dcb-0000-4000-8000-000000000002\n-')"
is "codex resume: sid file echoes the id" "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-000000000002"

run agy
hasnt "agy plain: NO --log-file (unchanged path)" "$argv" "--log-file"
hasnt "agy plain: no --conversation"              "$argv" "--conversation"
is    "agy plain: stderr stays empty"             "$err"  ""
run agy --session-id-file "$T/sid"
has "agy + sid file: passes --log-file"           "$argv" "--log-file"
is  "agy + sid file: id read out of the log"      "$(cat "$T/sid")" "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

echo "  the stale-id guard:"
printf 'STALE-ID-FROM-LAST-ROUND\n' > "$T/sid"
STUB_NO_BANNER=1 run codex --session-id-file "$T/sid"
is "no id determinable => file is EMPTY, not stale" "$(cat "$T/sid")" ""
has "no id determinable => says so on stderr"       "$err" "could not read a session id"
is  "no id determinable => reply still delivered"   "$out" "codex reply"

echo "  codex capture path (the one that cannot exec):"
STUB_SID=1e5a4dcb-0000-4000-8000-00000000000c run codex --session-id-file "$T/sid"
is  "captures the id from the banner"  "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-00000000000c"
is  "stdout is the reply and only that" "$out" "codex reply"
has "stderr still passes through live"  "$err" "OpenAI Codex v0.0.0-stub"
STUB_RC=7 run codex --session-id-file "$T/sid"
is "propagates the agent's exit status" "$rc" "7"

# Banner printed, THEN a non-zero exit -- an auth error, an unknown model, a
# refused sandbox. The id is real and must survive the failure, so the poll must
# NOT be shortened on a non-zero status: what it waits for is tee's flush, which
# has nothing to do with the agent's exit code.
#
# The banner deliberately arrives LATE, from a descendant that outlives codex.
# The obvious version of this test -- ordinary stub, exit 7 -- cannot fail: the
# stub emits and exits in the same instant, so tee always wins on an idle
# machine and the assertion passes with the guard broken. Measured on this
# shape: a one-shot poll loses the id 4 times out of 4.
: > "$T/orphanpid"
STUB_SLOW_BANNER=1 STUB_RC=7 STUB_SID=1e5a4dcb-0000-4000-8000-000000000007 \
  STUB_ORPHAN_PIDFILE="$T/orphanpid" run codex --session-id-file "$T/sid"
orphan="$(cat "$T/orphanpid" 2>/dev/null || true)"
[[ -n "$orphan" ]] && kill -KILL "$orphan" 2>/dev/null
is "late banner + agent exited 7: id still captured" \
   "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-000000000007"
is "late banner + agent exited 7: status still 7" "$rc" "7"

# `timeout` is how every real caller runs this. Without signal forwarding the
# wrapper would die and leave codex orphaned -- still running, still billing.
: > "$T/argv"
: > "$T/childpid"
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" STUB_SLEEP=30 STUB_PIDFILE="$T/childpid" \
    "$SRC" codex --session-id-file "$T/sid" -f "$T/prompt.txt" >/dev/null 2>&1 &
wrapper=$!
for _ in $(seq 1 100); do [[ -s "$T/childpid" ]] && break; sleep 0.1; done
kill -TERM "$wrapper" 2>/dev/null
wait "$wrapper" 2>/dev/null
child="$(cat "$T/childpid" 2>/dev/null || true)"
for _ in $(seq 1 50); do kill -0 "$child" 2>/dev/null || break; sleep 0.1; done
if [[ -n "$child" ]] && ! kill -0 "$child" 2>/dev/null; then
    ok "TERM is forwarded (no orphaned agent)"
else
    bad "TERM is forwarded (no orphaned agent)" "child [$child] survived"
    [[ -n "$child" ]] && kill -KILL "$child" 2>/dev/null
fi

echo "  agy resume verification (the silent-fork guard):"
STUB_CONV=1e5a4dcb-0000-4000-8000-00000000000a \
  run agy --resume 1e5a4dcb-0000-4000-8000-00000000000a
is "id matches => exit 0" "$rc" "0"
adjacent --conversation 1e5a4dcb-0000-4000-8000-00000000000a \
  && ok "id matches => passed --conversation" || bad "id matches => passed --conversation" "$argv"

STUB_CONV=99999999-9999-4999-8999-999999999999 \
  run agy --resume 1e5a4dcb-0000-4000-8000-00000000000a --session-id-file "$T/sid"
is  "silent fork => exit 4"                  "$rc" "4"
has "silent fork => names both ids"          "$err" "did NOT resume 1e5a4dcb-0000-4000-8000-00000000000a"
has "silent fork => names the one it got"    "$err" "99999999-9999-4999-8999-999999999999"
is  "silent fork => reply still printed"     "$out" "agy reply"
# The stranger's conversation has no history in it, and on the symmetric call
# shape (--resume "$(cat $sid)" --session-id-file "$sid") recording it would
# overwrite the warm id with a cold one -- destroying the only thing needed to
# retry the round the exit-4 warning is telling you to retry.
is  "silent fork => sid file is EMPTY, not the stranger" \
    "$(cat "$T/sid")" ""
has "silent fork => stranger's id still on stderr"  "$err" "99999999-9999-4999-8999-999999999999"

STUB_NO_CONV=1 run agy --resume 1e5a4dcb-0000-4000-8000-00000000000a
is  "unverifiable => exit 4 (fails closed)" "$rc" "4"
has "unverifiable => says why"              "$err" "cannot confirm agy resumed"

# A partial prompt read is the more fundamental problem, so 3 outranks 4.
STUB_NO_MARKER=1 STUB_CONV=99999999-9999-4999-8999-999999999999 \
  run agy --resume 1e5a4dcb-0000-4000-8000-00000000000a
is  "missing sentinel outranks mismatch => 3" "$rc" "3"
has "...but the mismatch is still reported"   "$err" "did NOT resume"

# A resume must not be able to widen the --add-dir grant: the granted directory
# holds the prompt and nothing else, and in particular not the CLI log.
STUB_CONV=1e5a4dcb-0000-4000-8000-00000000000a \
  run agy --resume 1e5a4dcb-0000-4000-8000-00000000000a --session-id-file "$T/sid"
granted="$(grep -A1 -x -F -e '--add-dir' "$T/argv" | tail -1)"
logpath="$(grep -A1 -x -F -e '--log-file' "$T/argv" | tail -1)"
if [[ -n "$granted" && "$logpath" != "$granted"/* ]]; then
    ok "CLI log lives OUTSIDE the --add-dir grant"
else
    bad "CLI log lives OUTSIDE the --add-dir grant" "granted=$granted log=$logpath"
fi

echo "  the reply outranks the bookkeeping:"
# Under set -e an unguarded write in record_session_id would abort the script
# before the reply is printed -- and on the agy path the capture file is already
# unlinked, so the answer would be unrecoverable. Closed stderr is the cheapest
# way to make every write in that function fail at once.
: > "$T/argv"
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" agy --session-id-file "$T/sid" -f "$T/prompt.txt" > "$T/out" 2>&-
rc=$?
is "closed stderr + sid file: reply survives" "$(cat "$T/out")" "agy reply"
is "closed stderr + sid file: exit 0"         "$rc" "0"

: > "$T/argv"
STUB_CONV=1e5a4dcb-0000-4000-8000-00000000000a \
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" agy --resume 1e5a4dcb-0000-4000-8000-00000000000a -f "$T/prompt.txt" > "$T/out" 2>&-
is "closed stderr + resume: reply survives" "$(cat "$T/out")" "agy reply"

# The destination going read-only mid-run (full disk, remount, quota): startup
# proved it writable, the final rename is what fails.
lockdir="$T/lockme"; mkdir -p "$lockdir"
: > "$T/argv"
STUB_LOCKDIR="$lockdir" \
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" agy --session-id-file "$lockdir/sid" -f "$T/prompt.txt" > "$T/out" 2> "$T/err"
rc=$?
chmod 0700 "$lockdir"
is  "unwritable destination: reply survives" "$(cat "$T/out")" "agy reply"
has "unwritable destination: warns"          "$(cat "$T/err")" "could not write --session-id-file"
# Exit 5, not 0. A caller that only checks the status would otherwise read the
# destination and get whatever was there before -- see the stale case next.
is  "unwritable destination: exit 5"         "$rc" "5"

# The stale-id case that makes 5 necessary: the destination already holds the
# PREVIOUS round's id, and it survives a failed write. The status is the only
# thing that distinguishes it from a fresh one.
lock2="$T/lock2"; mkdir -p "$lock2"
printf 'STALE-PREVIOUS-ROUND\n' > "$lock2/sid"
: > "$T/argv"
STUB_LOCKDIR="$lock2" \
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" agy --session-id-file "$lock2/sid" -f "$T/prompt.txt" > "$T/out" 2>/dev/null
rc=$?
chmod 0700 "$lock2"
is "stale id survives a failed write..."  "$(cat "$lock2/sid")" "STALE-PREVIOUS-ROUND"
is "...so the status must say so (5)"     "$rc" "5"

# The scratch file replaced by a directory: the printf fails, the destination
# is fine. Different branch, same contract.
# In its own directory: this sabotage leaves a DIRECTORY named like a scratch
# file, which cleanup's `rm -f` cannot remove, and the leak assertion further
# down is about the ordinary paths rather than about this.
dirify="$T/dirify"; mkdir -p "$dirify"
: > "$T/argv"
STUB_DIRIFY_TMP="$dirify" \
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" agy --session-id-file "$dirify/sid2" -f "$T/prompt.txt" > "$T/out" 2>/dev/null
rc=$?
is "unwritable scratch file: reply survives" "$(cat "$T/out")" "agy reply"
is "unwritable scratch file: exit 5"         "$rc" "5"

# The -d check happens at startup; the destination can still become a directory
# before the rename. `mv -T` must refuse rather than move the file inside it.
: > "$T/argv"
STUB_MKDIR_SID="$T/sid3" \
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" agy --session-id-file "$T/sid3" -f "$T/prompt.txt" > "$T/out" 2>/dev/null
rc=$?
is "destination turned into a dir: reply survives" "$(cat "$T/out")" "agy reply"
if [[ -d "$T/sid3" ]] && [[ -z "$(find "$T/sid3" -type f)" ]] && (( rc == 5 )); then
    ok "destination turned into a dir: refused, not moved inside"
else
    bad "destination turned into a dir: refused, not moved inside" \
        "rc=$rc contents=[$(find "$T/sid3" -type f 2>/dev/null)]"
fi

# The empty-id write specifically, under POSIX mode. `:` is a POSIX special
# builtin, so `: > file` with a failing redirect exits the shell BEFORE its `||`
# guard -- and bash takes that path whenever POSIXLY_CORRECT is in the
# environment, even empty. That branch is reached exactly on the agy rounds that
# already have a real reply in hand.
dirify2="$T/dirify2"; mkdir -p "$dirify2"
: > "$T/argv"
POSIXLY_CORRECT=1 STUB_DIRIFY_TMP="$dirify2" STUB_NO_CONV=1 \
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" agy --resume 1e5a4dcb-0000-4000-8000-00000000000a \
    --session-id-file "$dirify2/sid" -f "$T/prompt.txt" > "$T/out" 2>/dev/null
rc=$?
is "POSIX mode + failed empty write: reply survives" "$(cat "$T/out")" "agy reply"
is "POSIX mode + failed empty write: exit 4"         "$rc" "4"

echo "  a run that never reached an agent must not clobber the id:"
printf '1e5a4dcb-0000-4000-8000-00000000000a\n' > "$T/sid"
: > "$T/argv"
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" "$SRC" cldaue --session-id-file "$T/sid" \
    -f "$T/prompt.txt" >/dev/null 2>&1
is "typo'd agent name leaves the id intact" \
   "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-00000000000a"
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" "$SRC" claude -d "$T/nope" --session-id-file "$T/sid" \
    -f "$T/prompt.txt" >/dev/null 2>&1
is "nonexistent --dir leaves the id intact" \
   "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-00000000000a"
run codex --resume "not a valid id" --session-id-file "$T/sid"
is "rejected --resume leaves the id intact" \
   "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-00000000000a"
# No stray scratch files left beside it either.
leftovers="$(find "$T" -maxdepth 1 -name '.ask-agent-sid.*' | wc -l)"
is "no scratch files left behind" "$leftovers" "0"

echo "  destinations that are not a plain writable file:"
mkdir -p "$T/sid-as-dir"
run codex --session-id-file "$T/sid-as-dir"
if (( rc == 1 )) && [[ -z "$argv" ]]; then ok "rejects a directory as --session-id-file"
else bad "rejects a directory as --session-id-file" "rc=$rc"; fi
run codex --session-id-file "$T/prompt.txt"
if (( rc == 1 )) && [[ -z "$argv" ]]; then ok "rejects sid file == prompt file"
else bad "rejects sid file == prompt file" "rc=$rc"; fi
is "...and the prompt file is not truncated" "$(cat "$T/prompt.txt")" "probe prompt"
for opt in --resume --session-id-file; do
    : > "$T/argv"
    PATH="$BIN:$PATH" STUB_ARGV="$T/argv" "$SRC" codex "$opt" > "$T/out" 2> "$T/err"
    rc=$?
    if (( rc == 1 )) && [[ "$(cat "$T/err")" == *"requires a"* ]]; then
        ok "missing operand for $opt is reported"
    else bad "missing operand for $opt is reported" "rc=$rc err=$(cat "$T/err")"; fi
done

echo "  a descendant holding stderr must not park the wrapper:"
# codex exits immediately but leaves a child on the tee pipe. An unbounded wait
# on tee would block until that child died -- reporting a good round as a
# timeout, and losing an id that was already parsed and ready.
: > "$T/argv"; : > "$T/orphanpid"
start=$SECONDS
STUB_ORPHAN=25 STUB_ORPHAN_PIDFILE="$T/orphanpid" STUB_SID=1e5a4dcb-0000-4000-8000-00000000000f \
    run codex --session-id-file "$T/sid"
elapsed=$(( SECONDS - start ))
orphan="$(cat "$T/orphanpid" 2>/dev/null || true)"
[[ -n "$orphan" ]] && kill -KILL "$orphan" 2>/dev/null
if (( elapsed < 10 )); then ok "returns promptly (${elapsed}s), does not wait on tee"
else bad "returns promptly, does not wait on tee" "took ${elapsed}s"; fi
is "...and still captured the id" "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-00000000000f"
is "...and still delivered the reply" "$out" "codex reply"

echo "  a prompt must not be able to choose the session id:"
# codex echoes the PROMPT to its stderr, and a prompt quoting this repo's own
# docs carries literal "session id: <uuid>" lines at column 0 -- the council
# review of this very PR sent some. The parser reads the block between the
# banner's two delimiters, and the echo lands after the second one.
printf 'see docs\nsession id: 12345678-1234-4234-8234-123456789abc\nend\n' > "$T/evil.txt"
: > "$T/argv"
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" STUB_NO_BANNER=1 \
    "$SRC" codex --session-id-file "$T/sid" -f "$T/evil.txt" >/dev/null 2>&1
is "no banner: the prompt's id is NOT taken" "$(cat "$T/sid")" ""
# And with a real banner present, the banner wins over the prompt's decoy.
: > "$T/argv"
STUB_SID=1e5a4dcb-0000-4000-8000-00000000000b \
PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
    "$SRC" codex --session-id-file "$T/sid" -f "$T/evil.txt" >/dev/null 2>&1
is "banner beats the prompt's decoy id" "$(cat "$T/sid")" "1e5a4dcb-0000-4000-8000-00000000000b"

echo "  guards that were previously unpinned:"
# The locale hardening: a non-ASCII id must be rejected under a UTF-8 locale,
# where an `=~` bracket RANGE would have accepted it by collation.
# Only en_US.UTF-8 discriminates here: it is the collation that makes an accented
# letter fall INSIDE an `=~` [A-Za-z] range. Under C/C.UTF-8 the old code
# rejected it too, so running there would pass vacuously -- reported as skipped
# rather than counted as a pass.
if locale -a 2>/dev/null | grep -qix 'en_US\.utf-*8'; then
    LC_ALL=en_US.UTF-8 run codex --resume "ab$(printf '\xc3\xa9')cd"
    if (( rc == 1 )) && [[ -z "$argv" ]]; then ok "non-ASCII id rejected under en_US.UTF-8"
    else bad "non-ASCII id rejected under en_US.UTF-8" "rc=$rc argv=[$argv]"; fi
else
    skipped=$(( skipped + 1 ))
    printf '    %-42s SKIP  (en_US.UTF-8 not generated)\n' "non-ASCII id rejected under en_US.UTF-8"
fi
run codex --session-id-file ""
if (( rc == 1 )) && [[ -z "$argv" ]]; then ok "rejects an empty --session-id-file path"
else bad "rejects an empty --session-id-file path" "rc=$rc"; fi

echo "  a closed stderr must not cost the reply on ANY agy branch:"
# record_session_id is guarded, but so must be every diagnostic printed before
# the reply -- these are the branches that print one and then still owe an answer.
for case in no_conv:STUB_NO_CONV=1 mismatch:STUB_CONV=99999999-9999-4999-8999-999999999999; do
    name="${case%%:*}"; envset="${case#*:}"
    : > "$T/argv"
    env "$envset" PATH="$BIN:$PATH" STUB_ARGV="$T/argv" \
        "$SRC" agy --resume 1e5a4dcb-0000-4000-8000-00000000000a --session-id-file "$T/sid" \
        -f "$T/prompt.txt" > "$T/out" 2>&-
    rc=$?
    is "closed stderr, $name branch: reply survives" "$(cat "$T/out")" "agy reply"
    is "closed stderr, $name branch: still exit 4"   "$rc" "4"
done

echo
note=""
(( skipped > 0 )) && note=" ($skipped skipped)"
if (( fails == 0 )); then
    echo "PASS  $checked assertions$note"
    exit 0
fi
echo "FAIL  $fails of $checked assertions$note" >&2
exit 1
