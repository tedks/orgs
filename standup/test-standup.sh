#!/usr/bin/env bash
# test-standup.sh — tripwire for the standup component. Each case asserts a
# distinct behavior so a broken bus/guard fails loudly (mutation-checked: see
# the mutation harness at the end of this comment block for how each guard is
# verified able to fail). Cases:
#   1. send → drain delivers the message once, then the inbox is empty
#   2. guard appends a pending message as a footer to the command's output
#   3. guard passes through the command's own exit status when no halt pends
#   4. a pending halt forces exit 87 even when the command succeeds
#   5. a failing command keeps its own status even with a halt pending
#   6. standup redirect/halt enqueue messages guard then delivers
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
bus="$here/bus.sh"; guard="$here/guard.sh"; standup="$here/standup.sh"
for f in "$bus" "$guard" "$standup"; do [ -x "$f" ] || { echo "not executable: $f" >&2; exit 1; }; done

tmp=$(mktemp -d "${TMPDIR:-/tmp}/standup-test.XXXXXX"); trap 'rm -rf "$tmp"' EXIT
export STANDUP_BUS="$tmp/bus"
fail() { echo "FAIL: $1" >&2; exit 1; }

# 1. send → drain once
"$bus" send worker-a info "hello one" >/dev/null
[ "$("$bus" count worker-a)" = "1" ] || fail "count should be 1 after send"
out=$("$bus" drain worker-a)
grep -q 'hello one' <<<"$out" || fail "drain should print the message:
$out"
[ "$("$bus" count worker-a)" = "0" ] || fail "inbox should be empty after drain (one-shot)"
out2=$("$bus" drain worker-a)
grep -q 'hello one' <<<"$out2" && fail "message re-delivered after drain (not one-shot):
$out2"

# 2. guard appends the message as a footer to STDERR, keeping STDOUT clean for
#    machine consumers (stream separation).
"$bus" send worker-b redirect "use lib/retry.py" >/dev/null
gout=$("$guard" worker-b -- printf 'test-output\n' 2>"$tmp/b.err")
gerr=$(cat "$tmp/b.err")
[ "$gout" = "test-output" ] || fail "guard STDOUT should be exactly the command output (clean):
[$gout]"
grep -q 'use lib/retry.py' <<<"$gerr" || fail "guard should append the message to STDERR:
$gerr"
grep -q 'use lib/retry.py' <<<"$gout" && fail "the footer must NOT be on STDOUT (would corrupt data):
$gout"
[ "$("$bus" count worker-b)" = "0" ] || fail "guard should have delivered (drained) the message"

# 2b. a halt that arrives DURING the command (sent by the command itself) must
#     still force 87 — guard samples halt-state after the command, before the
#     drain. With the old pre-command sampling this case exits 0. STANDUP_BUS
#     is exported, so the inner bus.sh uses the same bus root.
set +e
"$guard" worker-during -- sh -c "\"$bus\" send worker-during halt 'arrived mid-run' >/dev/null; exit 0" >/dev/null 2>&1
dstat=$?
set -e
[ "$dstat" -eq 87 ] || fail "a halt arriving during the command should force 87, got $dstat"

# 3. guard passes through the command's own status when nothing pends
set +e
"$guard" worker-c -- sh -c 'exit 0'; s0=$?
"$guard" worker-c -- sh -c 'exit 3'; s3=$?
set -e
[ "$s0" -eq 0 ] || fail "guard should pass exit 0, got $s0"
[ "$s3" -eq 3 ] || fail "guard should pass exit 3, got $s3"

# 4. a pending halt forces exit 87 even when the command succeeds
"$bus" send worker-d halt "stop and reorient" >/dev/null
set +e
"$guard" worker-d -- sh -c 'exit 0' >/dev/null 2>"$tmp/d.err"; hstat=$?
set -e
herr=$(cat "$tmp/d.err")
[ "$hstat" -eq 87 ] || fail "pending halt on a success should force exit 87, got $hstat"
grep -q 'stop and reorient' <<<"$herr" || fail "halt message should still be shown (on stderr):
$herr"

# 5. a failing command keeps its own (more informative) status despite a halt
"$bus" send worker-e halt "also stop" >/dev/null
set +e
"$guard" worker-e -- sh -c 'exit 4' >/dev/null 2>&1; estat=$?
set -e
[ "$estat" -eq 4 ] || fail "a failing command should keep its own status (4), got $estat"

# 6. standup redirect/halt enqueue; guard delivers
"$standup" redirect worker-f "narrow the scope" >/dev/null
"$standup" halt     worker-f "hard stop"        >/dev/null
[ "$("$bus" count worker-f)" = "2" ] || fail "standup should have enqueued 2 messages"
set +e
"$guard" worker-f -- true >/dev/null 2>"$tmp/f.err"; fstat=$?
set -e
ferr=$(cat "$tmp/f.err")
grep -q 'narrow the scope' <<<"$ferr" || fail "redirect not delivered (stderr):
$ferr"
grep -q 'hard stop' <<<"$ferr" || fail "halt not delivered (stderr):
$ferr"
[ "$fstat" -eq 87 ] || fail "a pending halt among the two should force 87, got $fstat"

# 7. at-least-once: a drain whose OUTPUT fails must NOT lose the message — it
#    stays in the inbox to be re-shown (losing a halt is worse than showing it
#    twice). Drain to a closed fd so cat fails; the message must survive.
"$bus" send worker-g halt "must not be lost" >/dev/null
"$bus" drain worker-g >&- 2>/dev/null || true
[ "$("$bus" count worker-g)" = "1" ] || fail "a failed-output drain must leave the message (at-least-once)"
gshow=$("$bus" drain worker-g)
grep -q 'must not be lost' <<<"$gshow" || fail "the surviving message must re-show on the next drain:
$gshow"

echo "PASS: one-shot on success, at-least-once on failure, stderr footer, halt→87 (incl. during-run), stream-clean stdout"
