#!/bin/bash
# Regression test for capture-session-state.sh.
#
# Drives the real hook end-to-end: feeds it the same PreToolUse JSON Claude
# Code sends on stdin, in an isolated $HOME, and asserts on the state file it
# writes. Claude Code never sets a CLAUDE_SESSION_ID env var -- session_id
# only ever arrives in that stdin JSON -- so this test exists to catch any
# regression back to reading an env var that isn't there, which silently
# turns every run of the hook into a no-op.
#
# Run: bash skills/_shared/hooks/test-capture-session-state.sh   (exits non-zero on failure)

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$HERE/capture-session-state.sh"

if [[ ! -f "$HOOK" ]]; then
  echo "FATAL: hook not found at $HOOK" >&2
  exit 2
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/test-capture-session-state.XXXXXX")"
cleanup() { find "$WORK" -mindepth 1 -delete 2>/dev/null; rmdir "$WORK" 2>/dev/null; }
trap cleanup EXIT

fails=0
ok() { printf 'ok    %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
assert() {
  local description="$1"
  shift
  if "$@"; then ok "$description"; else bad "$description"; fi
}

# Claude Code does not exec a hook directly: it runs `/bin/sh -c <command>`, so
# the real process chain is  claude -> sh -c -> hook  and the hook's $PPID is
# that short-lived sh, NOT claude. A test that ran the hook straight from this
# script would have passed against a hook that keyed its pointer on $PPID, so
# reproduce the real shape with a stand-in "claude" (a script named claude, so
# its comm is "claude") that launches the hook the way Claude Code does.
FAKEBIN="$WORK/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/claude" <<'EOF'
#!/bin/bash
# usage: claude <wrapped|direct|nonshell|nested> <hook> <payload-file>
# Records "<its pid> <its start time>" so the test can check the pointer. The
# start time is computed here with a DIFFERENT parser from the hook's (python,
# rfind(")")) so the two can disagree if either gets awkward comms wrong.
start=$(python3 -c 'import sys; s = open("/proc/%s/stat" % sys.argv[1]).read(); print(s[s.rfind(")") + 2:].split()[19])' "$$")
echo "$$ $start" > "$CLAUDE_PID_FILE"
mode=$1 hook=$2 payload=$3
case "$mode" in
  direct)   "$hook" < "$payload" ;;
  # a non-shell wrapper between sh and the hook (timeout, nix develop, flock...)
  nonshell) sh -c 'timeout 30 "$1"; exit $?' sh "$hook" < "$payload" ;;
  # a wrapper of an arbitrary name that is itself a shell script: hook -> wrap -> sh -> claude
  nested)   sh -c '"$1" "$2"; exit $?' sh "$WRAP" "$hook" < "$payload" ;;
  *)        sh -c '"$1"; exit $?' sh "$hook" < "$payload" ;;
esac
exit $?
EOF
cat > "$FAKEBIN/wrap" <<'EOF'
#!/bin/bash
"$@"
exit $?
EOF
# a claude whose comm has spaces and a ") " in it, to break naive /proc/<pid>/stat parsing
cp "$FAKEBIN/claude" "$FAKEBIN/claude) S 1 2 3"
cat > "$FAKEBIN/orphan-runner" <<'EOF'
#!/bin/bash
# usage: orphan-runner <outer-pid> <HOME> <hook> <payload> <done-file>
# Waits until it has been reparented off <outer-pid> (which exits right after
# launching it), then runs the hook, so the hook's ancestry is off any claude.
outer=$1 home=$2 hook=$3 payload=$4 donefile=$5
for _ in $(seq 1 200); do
  ppid=""
  while read -r k v; do [ "$k" = "PPid:" ] && { ppid=$v; break; }; done < "/proc/$$/status"
  [ "$ppid" != "$outer" ] && break
  sleep 0.05
done
read -r pcomm < "/proc/$ppid/comm"
# If a claude* process adopted us (a child-subreaper claude) the hook would
# legitimately key on it, and this scenario cannot be reproduced here.
case "$pcomm" in claude*) echo skip > "$donefile"; exit 0 ;; esac
HOME="$home" "$hook" < "$payload"
echo ran > "$donefile"
EOF
chmod +x "$FAKEBIN/claude" "$FAKEBIN/claude) S 1 2 3" "$FAKEBIN/wrap" "$FAKEBIN/orphan-runner"

run_hook() { # $1 = HOME dir, $2 = json payload, $3 = wrapped (default) | direct | nonshell | nested
  local payload_file="$WORK/payload.json"
  printf '%s' "$2" > "$payload_file"
  HOME="$1" WRAP="$FAKEBIN/wrap" CLAUDE_PID_FILE="$WORK/claude.pid" \
    "$FAKEBIN/${CLAUDE_NAME:-claude}" "${3:-wrapped}" "$HOOK" "$payload_file"
}
last_claude_pid() { cut -d' ' -f1 "$WORK/claude.pid"; }
last_claude_start() { cut -d' ' -f2 "$WORK/claude.pid"; }

state_file() { echo "$1/.claude/session-state/$2.json"; }
pointer_file() { echo "$1/.claude/session-state/current.$2"; }
# the pointer's whole content: "<session id> <claude's start time> <boot id>"
BOOT="$(cat /proc/sys/kernel/random/boot_id)"
pointer_value() { cat "$(pointer_file "$1" "$2")" 2>/dev/null; }
has_pointer_file() { compgen -G "$1/.claude/session-state/current.*" >/dev/null; }
pointer_count() { compgen -G "$1/.claude/session-state/current.*" | wc -l; }

echo "case: a real PreToolUse payload writes session state"
HOME1="$WORK/home1"
REPO1="$WORK/repo1"
mkdir -p "$HOME1" "$REPO1"
init_repo() {
  (cd "$1" && git init -q && git config user.email t@example.com \
    && git config user.name test && git commit -q --allow-empty -m init)
}
init_repo "$REPO1"
(cd "$REPO1" && git checkout -q -b feature-x)
SID1="11111111-1111-1111-1111-111111111111"
PAYLOAD1="$(jq -n --arg sid "$SID1" --arg cwd "$REPO1" \
  '{session_id: $sid, cwd: $cwd, hook_event_name: "PreToolUse", tool_name: "Bash", tool_input: {command: "echo hi"}}')"
if run_hook "$HOME1" "$PAYLOAD1"; then ok "hook exits 0"; else bad "hook exits 0"; fi
SF1="$(state_file "$HOME1" "$SID1")"
assert "state file was written" test -f "$SF1"
assert "state file records the session id" \
  test "$(jq -r .session_id "$SF1")" = "$SID1"
assert "state file records the payload's cwd, not the hook's own \$PWD" \
  test "$(jq -r .launch_dir "$SF1")" = "$REPO1"
assert "state file records the git branch of that cwd" \
  test "$(jq -r .git_branch "$SF1")" = "feature-x"
assert "a per-PID pointer file was written" has_pointer_file "$HOME1"
CLAUDE1="$(last_claude_pid)"
assert "the pointer is keyed by the claude process, not the sh wrapper (\$PPID), and carries its start time" \
  test "$(pointer_value "$HOME1" "$CLAUDE1")" = "$SID1 $(last_claude_start) $BOOT"
assert "exactly one pointer was written (nothing keyed on the wrapper's pid)" \
  test "$(pointer_count "$HOME1")" = 1

echo "case: a hook exec'd directly by claude (no sh wrapper) is keyed on claude too"
HOME4="$WORK/home4"
mkdir -p "$HOME4"
SID4="44444444-4444-4444-4444-444444444444"
PAYLOAD4="$(jq -n --arg sid "$SID4" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
if run_hook "$HOME4" "$PAYLOAD4" direct; then ok "direct-exec hook exits 0"; else bad "direct-exec hook exits 0"; fi
assert "direct-exec pointer is keyed by the claude process" \
  test "$(pointer_value "$HOME4" "$(last_claude_pid)")" = "$SID4 $(last_claude_start) $BOOT"

echo "case: wrappers of any kind between claude and the hook are stepped over"
HOME4B="$WORK/home4b"
mkdir -p "$HOME4B"
for mode in nonshell nested; do
  SID4B="4b4b4b4b-4b4b-4b4b-4b4b-4b4b4b4b4b4b"
  PAYLOAD4B="$(jq -n --arg sid "$SID4B" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
  if run_hook "$HOME4B" "$PAYLOAD4B" "$mode"; then ok "$mode-wrapper hook exits 0"; else bad "$mode-wrapper hook exits 0"; fi
  assert "$mode wrapper: pointer is keyed by the claude process" \
    test "$(pointer_value "$HOME4B" "$(last_claude_pid)")" = "$SID4B $(last_claude_start) $BOOT"
done

echo "case: a hook with NO claude ancestor (orphaned, reparented) writes no pointer at all"
# Falling back to some other ancestor could key the pointer on a process many
# sessions share (systemd --user, tmux) and answer one session with another's id.
HOME4C="$WORK/home4c"
mkdir -p "$HOME4C"
SID4C="4c4c4c4c-4c4c-4c4c-4c4c-4c4c4c4c4c4c"
jq -n --arg sid "$SID4C" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}' > "$WORK/payload-orphan.json"
# setsid + a launcher that exits at once: the runner is orphaned and the hook
# runs with no claude anywhere in its ancestry.
# shellcheck disable=SC2016  # the single quotes are deliberate: $0, $$ and $@ expand in the inner bash
setsid bash -c '"$0" $$ "$@" &' "$FAKEBIN/orphan-runner" \
  "$HOME4C" "$HOOK" "$WORK/payload-orphan.json" "$WORK/orphan.done" < /dev/null > /dev/null 2>&1
for _ in $(seq 1 200); do [ -e "$WORK/orphan.done" ] && break; sleep 0.1; done
if [ "$(cat "$WORK/orphan.done" 2>/dev/null)" = skip ]; then
  ok "skipped: orphans are adopted by a claude* subreaper here, so the scenario cannot be produced"
else
  assert "the orphaned hook ran to completion" test "$(cat "$WORK/orphan.done" 2>/dev/null)" = ran
  assert "the orphaned hook wrote no pointer" test "$(pointer_count "$HOME4C")" = 0
  assert "...but still recorded the session state" test -f "$(state_file "$HOME4C" "$SID4C")"
  assert "...and logged the ancestry it saw, so the silent null can be diagnosed" \
    grep -q 'no claude\* ancestor' "$HOME4C/.claude/session-state/no-claude-ancestor.log"
fi

echo "case: the log's lock file itself survives the sweep even when idle for days"
# The age-based .log.* sweep has no liveness/pid guard (unlike the earlier
# liveness loop), so if the lock file matched that pattern, going quiet on
# this branch for a day could let the sweep unlink a currently-held lock --
# a flock+unlink TOCTOU that would silently defeat the mutual exclusion the
# lock exists for. The fix is naming, not logic: the lock file must not
# match .log.* (or .current.*/.state.*) at all.
HOME4D2="$WORK/home4d2"
STATE4D2="$HOME4D2/.claude/session-state"
mkdir -p "$STATE4D2"
LOCK4D2="$STATE4D2/.no-claude-ancestor.lock"
touch "$LOCK4D2"
touch -d '2 days ago' "$LOCK4D2"
SID4D2="4d2d4d2d-4d2d-4d2d-4d2d-4d2d4d2d4d2d"
PAYLOAD4D2="$(jq -n --arg sid "$SID4D2" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME4D2" "$PAYLOAD4D2" >/dev/null
assert "a 2-day-old lock file is not swept (its name matches no sweep pattern)" \
  test -e "$LOCK4D2"

echo "case: no-claude-ancestor.log is bounded, not left to grow without limit"
HOME4E="$WORK/home4e"
STATE4E="$HOME4E/.claude/session-state"
mkdir -p "$STATE4E"
LOG4E="$STATE4E/no-claude-ancestor.log"
yes "pre-existing line that should be trimmed away" | head -c 100000 > "$LOG4E"
CANARY_LINE="canary-line-that-must-survive-trimming"
echo "$CANARY_LINE" >> "$LOG4E"
SID4E="4e4e4e4e-4e4e-4e4e-4e4e-4e4e4e4e4e4e"
jq -n --arg sid "$SID4E" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}' > "$WORK/payload-orphan2.json"
# shellcheck disable=SC2016  # the single quotes are deliberate: $0, $$ and $@ expand in the inner bash
setsid bash -c '"$0" $$ "$@" &' "$FAKEBIN/orphan-runner" \
  "$HOME4E" "$HOOK" "$WORK/payload-orphan2.json" "$WORK/orphan2.done" < /dev/null > /dev/null 2>&1
for _ in $(seq 1 200); do [ -e "$WORK/orphan2.done" ] && break; sleep 0.1; done
if [ "$(cat "$WORK/orphan2.done" 2>/dev/null)" = skip ]; then
  ok "skipped: orphans are adopted by a claude* subreaper here, so the scenario cannot be produced"
else
  assert "the log was actually trimmed to roughly the intended ~200 lines, not merely shrunk" \
    test "$(wc -c < "$LOG4E")" -lt 20000
  assert "the line right before the new entries survived the trim" \
    grep -qF "$CANARY_LINE" "$LOG4E"
  assert "this call's own entry is present" grep -q "session=$SID4E" "$LOG4E"
fi

echo "case: a claude whose comm contains \") \" and spaces still yields the right start time"
HOME4D="$WORK/home4d"
mkdir -p "$HOME4D"
SID4D="4d4d4d4d-4d4d-4d4d-4d4d-4d4d4d4d4d4d"
PAYLOAD4D="$(jq -n --arg sid "$SID4D" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
CLAUDE_NAME='claude) S 1 2 3' run_hook "$HOME4D" "$PAYLOAD4D" >/dev/null
assert "awkward-comm claude: pointer start time matches an independent (python rfind) parse" \
  test "$(pointer_value "$HOME4D" "$(last_claude_pid)")" = "$SID4D $(last_claude_start) $BOOT"

echo "case: a RESUMED session (new claude pid, same session id, state file exists) gets a pointer"
HOME5="$WORK/home5"
mkdir -p "$HOME5"
SID5="55555555-5555-5555-5555-555555555555"
PAYLOAD5="$(jq -n --arg sid "$SID5" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME5" "$PAYLOAD5" >/dev/null
FIRST5="$(last_claude_pid)"
SF5="$(state_file "$HOME5" "$SID5")"
state5_before="$(sha256sum "$SF5")"
run_hook "$HOME5" "$PAYLOAD5" >/dev/null   # the "claude --resume" process
RESUMED5="$(last_claude_pid)"; RESUMED5_START="$(last_claude_start)"
assert "the resumed run really is a different claude process" test "$FIRST5" != "$RESUMED5"
assert "the resumed process has its own pointer to the same session" \
  test "$(pointer_value "$HOME5" "$RESUMED5")" = "$SID5 $RESUMED5_START $BOOT"
assert "the original process is gone, so its pointer was swept (only the resumed one remains)" \
  test ! -e "$(pointer_file "$HOME5" "$FIRST5")" -a "$(pointer_count "$HOME5")" = 1
assert "the resumed run does not rewrite the state file" \
  test "$state5_before" = "$(sha256sum "$SF5")"

echo "case: every call -- a resumed session's too -- sweeps by process liveness, never by age"
HOME6="$WORK/home6"
STATE6="$HOME6/.claude/session-state"
mkdir -p "$STATE6"
SID6="88888888-8888-8888-8888-888888888888"
PAYLOAD6="$(jq -n --arg sid "$SID6" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME6" "$PAYLOAD6" >/dev/null      # creates the state file: what follows is a RESUME
( : ) & DEAD6=$!; wait "$DEAD6"               # a pid that certainly no longer exists
echo "x 1 y" > "$STATE6/current.$$";     touch -d '3 days ago' "$STATE6/current.$$"   # live but idle 3 days
echo "x 1 y" > "$STATE6/current.$DEAD6"       # its process is gone
echo "orphan" > "$STATE6/.current.$DEAD6"     # temp files of hooks that died before their mv
echo "orphan" > "$STATE6/.state.$DEAD6"
echo "inflight" > "$STATE6/.current.$$"       # temp file of a hook that is still running (this script)
run_hook "$HOME6" "$PAYLOAD6" >/dev/null      # the resumed call
assert "a live process's pointer survives 3 idle days" test -e "$STATE6/current.$$"
assert "a dead process's pointer is removed" test ! -e "$STATE6/current.$DEAD6"
assert "a dead hook's .current temp file is swept" test ! -e "$STATE6/.current.$DEAD6"
assert "a dead hook's .state temp file is swept" test ! -e "$STATE6/.state.$DEAD6"
assert "positive control: a running hook's temp file is left alone" test -e "$STATE6/.current.$$"

echo "case: a pointer's own start-time check, not age, is what makes a reused pid harmless"
# No age backstop for current.* itself: it would risk deleting a live,
# merely-idle session's pointer. A pointer under a pid a live-but-unrelated
# process has since inherited just fails start-time verification -- it is
# left on disk (harmless: never matches), not swept.
sleep 300 & LIVE_OLD=$!
echo "x 1 y" > "$STATE6/current.$LIVE_OLD"; touch -d '40 days ago' "$STATE6/current.$LIVE_OLD"
SID6B="99999999-9999-9999-9999-999999999999"
run_hook "$HOME6" "$(jq -n --arg sid "$SID6B" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')" >/dev/null
assert "the 40-day-old pointer under a live-but-unrelated pid is left alone (its process exists)" \
  test -e "$STATE6/current.$LIVE_OLD"
assert "...and the 3-day-old live pointer is still there too" test -e "$STATE6/current.$$"

echo "case: a TEMP file under a pid a live unrelated process has since inherited is aged out"
# Temp files have no start-time check (they're never read by the server), so
# unlike pointers they DO need an age backstop for this case -- liveness alone
# would call them "still in flight" forever.
sleep 300 & LIVE_OLD2=$!
echo "orphan-current" > "$STATE6/.current.$LIVE_OLD2"
echo "orphan-state" > "$STATE6/.state.$LIVE_OLD2"
touch -d '2 days ago' "$STATE6/.current.$LIVE_OLD2" "$STATE6/.state.$LIVE_OLD2"
SID6C="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
run_hook "$HOME6" "$(jq -n --arg sid "$SID6C" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')" >/dev/null
assert "a 2-day-old .current temp file under a now-live pid is removed by the age backstop" \
  test ! -e "$STATE6/.current.$LIVE_OLD2"
assert "...and the .state one too" test ! -e "$STATE6/.state.$LIVE_OLD2"
kill "$LIVE_OLD" "$LIVE_OLD2" 2>/dev/null; wait "$LIVE_OLD" "$LIVE_OLD2" 2>/dev/null

echo "case: if jq fails to build the state file, no pointer is published either"
# The state-before-pointer ordering only protects against the async retry
# reading a pointer a few ms early; it says nothing about jq or the mv
# actually FAILING. The pointer write must be gated on the state file really
# existing, not just placed after the attempt to create it.
HOME7="$WORK/home7"
mkdir -p "$HOME7"
FAILJQ="$WORK/failjq-bin"
mkdir -p "$FAILJQ"
cat > "$FAILJQ/jq" <<EOF
#!/bin/bash
# Real jq for everything except the state-building call (jq -n ...), which
# always fails -- reproducing e.g. a disk-full ENOSPC on that write.
if [ "\$1" = "-n" ]; then exit 1; fi
exec "$(command -v jq)" "\$@"
EOF
chmod +x "$FAILJQ/jq"
SID7="77777777-7777-7777-7777-777777777777"
PAYLOAD7="$(jq -n --arg sid "$SID7" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
if PATH="$FAILJQ:$PATH" run_hook "$HOME7" "$PAYLOAD7"; then
  ok "hook still exits 0 even when state-file creation fails"
else
  bad "hook still exits 0 even when state-file creation fails"
fi
assert "no state file was created" test ! -f "$(state_file "$HOME7" "$SID7")"
assert "no pointer was published either (would otherwise answer with no launch_dir)" \
  test "$(pointer_count "$HOME7")" = 0

echo "case: a launch_dir containing a quote and backslash does not corrupt the JSON"
HOME1b="$WORK/home1b"
REPO1B="$WORK/repo with \"quote\" and \\backslash"
mkdir -p "$HOME1b" "$REPO1B"
SID1B="33333333-3333-3333-3333-333333333333"
PAYLOAD1B="$(jq -n --arg sid "$SID1B" --arg cwd "$REPO1B" \
  '{session_id: $sid, cwd: $cwd, hook_event_name: "PreToolUse", tool_name: "Bash"}')"
if run_hook "$HOME1b" "$PAYLOAD1B"; then ok "quoted-path payload exits 0"; else bad "quoted-path payload exits 0"; fi
SF1B="$(state_file "$HOME1b" "$SID1B")"
assert "state file is valid JSON despite the quote/backslash" \
  jq -e . "$SF1B" >/dev/null
assert "state file's launch_dir round-trips exactly" \
  test "$(jq -r .launch_dir "$SF1B")" = "$REPO1B"

echo "case: a path-traversal-shaped session_id is rejected, not turned into a path"
HOME1C="$WORK/home1c"
mkdir -p "$HOME1C/.claude"
CANARY="$HOME1C/.claude.json"
printf '{"canary": true}' > "$CANARY"
PAYLOAD1C='{"session_id": "../../.claude", "cwd": "/tmp", "hook_event_name": "PreToolUse", "tool_name": "Bash"}'
if run_hook "$HOME1C" "$PAYLOAD1C"; then ok "traversal-shaped session_id exits 0"; else bad "traversal-shaped session_id exits 0"; fi
assert "traversal-shaped session_id does not write outside session-state/" \
  test "$(cat "$CANARY")" = '{"canary": true}'
assert "traversal-shaped session_id writes no state at all" \
  test ! -d "$HOME1C/.claude/session-state"

echo "case: a payload with no session_id (matches no CLAUDE_SESSION_ID env var) is a no-op"
HOME2="$WORK/home2"
mkdir -p "$HOME2"
PAYLOAD2='{"cwd": "/tmp", "hook_event_name": "PreToolUse", "tool_name": "Bash"}'
if run_hook "$HOME2" "$PAYLOAD2"; then ok "no-session_id payload exits 0"; else bad "no-session_id payload exits 0"; fi
assert "no state dir is created" test ! -d "$HOME2/.claude/session-state"

echo "case: a second tool call in the same session does not overwrite the state file"
SID3="22222222-2222-2222-2222-222222222222"
REPO3="$WORK/repo3"
mkdir -p "$REPO3"
init_repo "$REPO3"
(cd "$REPO3" && git checkout -q -b first-branch)
PAYLOAD3a="$(jq -n --arg sid "$SID3" --arg cwd "$REPO3" '{session_id: $sid, cwd: $cwd, hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME1" "$PAYLOAD3a" >/dev/null
SF3="$(state_file "$HOME1" "$SID3")"
before="$(sha256sum "$SF3")"
(cd "$REPO3" && git checkout -q -b second-branch 2>/dev/null)
PAYLOAD3b="$(jq -n --arg sid "$SID3" --arg cwd "$REPO3" '{session_id: $sid, cwd: $cwd, hook_event_name: "PreToolUse", tool_name: "Read"}')"
run_hook "$HOME1" "$PAYLOAD3b" >/dev/null
after="$(sha256sum "$SF3")"
assert "state file is written once per session, not on every tool call" test "$before" = "$after"

echo "case: an OLD state file survives if a LIVE pointer still names its session"
# Pointers no longer age out at all -- deliberately, so a long-lived session
# (tmux keeps these alive for weeks) keeps working. If the state-file age
# sweep didn't check that, an unrelated session's hook run would delete a
# still-live session's *.json out from under it while its pointer keeps
# verifying fine -- session_id with no launch_dir, the exact bug this file
# exists to prevent, reached through a different sweep than the pointer's.
HOME8="$WORK/home8"
STATE8="$HOME8/.claude/session-state"
mkdir -p "$STATE8"
SID_LIVE="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
echo "{\"session_id\":\"$SID_LIVE\"}" > "$STATE8/$SID_LIVE.json"
touch -d '31 days ago' "$STATE8/$SID_LIVE.json"
read -r self_stat < "/proc/$$/stat"; read -ra self_fields <<< "${self_stat##*) }"
printf '%s %s %s\n' "$SID_LIVE" "${self_fields[19]}" "$BOOT" > "$STATE8/current.$$"
SID_UNRELATED="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
PAYLOAD_UNRELATED="$(jq -n --arg sid "$SID_UNRELATED" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME8" "$PAYLOAD_UNRELATED" >/dev/null
assert "the live session's 31-day-old state file survives an unrelated session's hook run" \
  test -f "$STATE8/$SID_LIVE.json"

echo "case: an OLD state file with NO live pointer is still cleaned up"
HOME9="$WORK/home9"
STATE9="$HOME9/.claude/session-state"
mkdir -p "$STATE9"
SID_DEAD="cccccccc-cccc-cccc-cccc-cccccccccccc"
echo "{\"session_id\":\"$SID_DEAD\"}" > "$STATE9/$SID_DEAD.json"
touch -d '31 days ago' "$STATE9/$SID_DEAD.json"
SID_UNRELATED2="ffffffff-ffff-ffff-ffff-ffffffffffff"
PAYLOAD_UNRELATED2="$(jq -n --arg sid "$SID_UNRELATED2" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME9" "$PAYLOAD_UNRELATED2" >/dev/null
assert "a 31-day-old state file with no live pointer is still swept" \
  test ! -f "$STATE9/$SID_DEAD.json"

echo "case: a STALE pointer (right session_id, wrong start time) does not pin a state file forever"
# A pid reused by an unrelated process produces exactly this shape: the
# pointer's session_id field is still whatever the dead session wrote, but
# the start time no longer matches the live occupant of that pid. The
# server independently re-verifies and would refuse this pointer -- but the
# hook's own liveness-for-sweep-purposes check must not be fooled by it,
# or the 30-day backstop becomes permanently defeated for that session.
HOME10="$WORK/home10"
STATE10="$HOME10/.claude/session-state"
mkdir -p "$STATE10"
SID_STALE="99990000-0000-0000-0000-000000000001"
echo "{\"session_id\":\"$SID_STALE\"}" > "$STATE10/$SID_STALE.json"
touch -d '31 days ago' "$STATE10/$SID_STALE.json"
printf '%s 999999999 %s\n' "$SID_STALE" "$BOOT" > "$STATE10/current.$$"
SID_UNRELATED3="88880000-0000-0000-0000-000000000002"
PAYLOAD_UNRELATED3="$(jq -n --arg sid "$SID_UNRELATED3" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME10" "$PAYLOAD_UNRELATED3" >/dev/null
assert "a 31-day-old state file behind only a stale pointer is still swept" \
  test ! -f "$STATE10/$SID_STALE.json"

echo "case: THIS call's own boot_id read glitching does not sweep an unrelated live session"
# /proc/sys/kernel/random/boot_id is read via a bash builtin redirect from a
# hardcoded path, so a real forced failure can't be injected through PATH or
# the environment the way the jq-failure case above does. Same technique as
# that case in spirit (substitute a controlled failure for a real dependency
# this suite can't otherwise force to fail) applied to a builtin instead of
# an external command: run a copy of the hook with just that one read
# replaced by a hardcoded "this call's read failed" simulation.
GLITCH_HOOK="$WORK/glitch-hook.sh"
sed "s|read -r boot_id 2>/dev/null < /proc/sys/kernel/random/boot_id|boot_id=''|" "$HOOK" > "$GLITCH_HOOK"
chmod +x "$GLITCH_HOOK"
# If a future edit to that line ever stops matching this sed pattern, the
# substitution silently does nothing and GLITCH_HOOK becomes byte-identical
# to the real hook -- the test below would then pass for the wrong reason
# (a real, successful boot_id read) instead of testing the fallback at all.
assert "the boot_id glitch was actually injected into GLITCH_HOOK" \
  grep -qF "boot_id=''" "$GLITCH_HOOK"
HOME12="$WORK/home12"
STATE12="$HOME12/.claude/session-state"
mkdir -p "$STATE12"
SID_LIVE12="77770000-0000-0000-0000-000000000001"
echo "{\"session_id\":\"$SID_LIVE12\"}" > "$STATE12/$SID_LIVE12.json"
touch -d '31 days ago' "$STATE12/$SID_LIVE12.json"
read -r self12_stat < "/proc/$$/stat"; read -ra self12_fields <<< "${self12_stat##*) }"
# A genuinely correct, currently-valid pointer -- real pid ($$), real start
# time, real boot id -- for an unrelated session that must NOT be swept.
printf '%s %s %s\n' "$SID_LIVE12" "${self12_fields[19]}" "$BOOT" > "$STATE12/current.$$"
SID_UNRELATED5="66660000-0000-0000-0000-000000000002"
PAYLOAD_UNRELATED5="$(jq -n --arg sid "$SID_UNRELATED5" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
HOME="$HOME12" bash "$GLITCH_HOOK" <<< "$PAYLOAD_UNRELATED5" >/dev/null
assert "a live session's state file survives another call's own boot_id read glitching" \
  test -f "$STATE12/$SID_LIVE12.json"

echo "case: a CANDIDATE's stored boot_id=unknown is not a permanent exemption from verification"
# THIS call's own read glitching (above) is transient and resolves itself on
# literally the next call, for every session equally. A candidate pointer's
# STORED "unknown" is different: it persists as long as that session's own
# pointer goes unwritten, which for a session idle for weeks (this file's
# own comments elsewhere: tmux keeps these alive that long) is a real
# window -- and a native council review found that exempting it there
# permanently disables exactly the reboot/pid-reuse/coincidental-start-time
# collision boot_id was added to catch, for that one pointer, for that whole
# window. So: THIS call's own boot_id read succeeds normally here (real
# value), while the CANDIDATE's stored one says "unknown" -- and it must
# get a fair, non-exempt check like anyone else.
HOME13="$WORK/home13"
STATE13="$HOME13/.claude/session-state"
mkdir -p "$STATE13"
SID_STORED_UNKNOWN="55550000-0000-0000-0000-000000000009"
echo "{\"session_id\":\"$SID_STORED_UNKNOWN\"}" > "$STATE13/$SID_STORED_UNKNOWN.json"
touch -d '31 days ago' "$STATE13/$SID_STORED_UNKNOWN.json"
read -r self13_stat < "/proc/$$/stat"; read -ra self13_fields <<< "${self13_stat##*) }"
# Real pid, real matching start time -- but the stored boot id is "unknown".
printf '%s %s unknown\n' "$SID_STORED_UNKNOWN" "${self13_fields[19]}" > "$STATE13/current.$$"
SID_UNRELATED6="33330000-0000-0000-0000-000000000007"
PAYLOAD_UNRELATED6="$(jq -n --arg sid "$SID_UNRELATED6" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
run_hook "$HOME13" "$PAYLOAD_UNRELATED6" >/dev/null
assert "a candidate's stored boot_id=unknown does not exempt it forever; its state is still swept" \
  test ! -f "$STATE13/$SID_STORED_UNKNOWN.json"

echo "case: a live_sid field is not word-split/glob-expanded against the hook's cwd"
# for x in \$unquoted_list runs both word-splitting and pathname expansion.
# If live_sessions were ever a plain string instead of an array, a malformed
# pointer's session_id field of literally "*" would expand, at iteration
# time, to whatever files exist in the hook's OWN cwd -- and if one of those
# happened to share a name with some OTHER session's *.json stem, that
# unrelated, genuinely-dead session's state file would be wrongly preserved
# (an observable, not just theoretical, divergence). Every real session_id
# is UUID-validated before any hook ever writes one, so this needs a
# malformed current.* file to trigger at all -- still worth closing outright.
HOME11="$WORK/home11"
STATE11="$HOME11/.claude/session-state"
mkdir -p "$STATE11"
DECOY_DIR="$WORK/decoy-cwd11"
mkdir -p "$DECOY_DIR"
SID_COINCIDENCE="dddddddd-dddd-dddd-dddd-dddddddddddd"
touch "$DECOY_DIR/$SID_COINCIDENCE"   # a file that just happens to share its name with a session id
echo "{\"session_id\":\"$SID_COINCIDENCE\"}" > "$STATE11/$SID_COINCIDENCE.json"
touch -d '31 days ago' "$STATE11/$SID_COINCIDENCE.json"
# A malformed pointer (session_id field is a bare glob char) but otherwise
# genuinely verifiable -- pid $$ (this test script, alive) with the REAL
# matching start time + boot id -- so it survives the start-time/boot-id
# check that an earlier round's fix added, and reaches the vulnerable line.
read -r self11_stat < "/proc/$$/stat"; read -ra self11_fields <<< "${self11_stat##*) }"
printf '* %s %s\n' "${self11_fields[19]}" "$BOOT" > "$STATE11/current.$$"
SID_UNRELATED4="eeee0000-0000-0000-0000-000000000003"
PAYLOAD_UNRELATED4="$(jq -n --arg sid "$SID_UNRELATED4" '{session_id: $sid, cwd: "/tmp", hook_event_name: "PreToolUse", tool_name: "Bash"}')"
( cd "$DECOY_DIR" && run_hook "$HOME11" "$PAYLOAD_UNRELATED4" >/dev/null )
assert "the coincidentally-named cwd file did not fool the sweep into keeping this dead session's state" \
  test ! -f "$STATE11/$SID_COINCIDENCE.json"

echo
if (( fails )); then
  echo "$fails test(s) FAILED"
  exit 1
fi
echo "all tests passed"
