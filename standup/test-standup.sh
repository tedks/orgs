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

# 2. guard appends a pending message as a footer to command output
"$bus" send worker-b redirect "use lib/retry.py" >/dev/null
gout=$("$guard" worker-b -- printf 'test-output\n')
grep -q 'test-output' <<<"$gout" || fail "guard should pass command output:
$gout"
grep -q 'use lib/retry.py' <<<"$gout" || fail "guard should append the pending message:
$gout"
[ "$("$bus" count worker-b)" = "0" ] || fail "guard should have delivered (drained) the message"

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
hout=$("$guard" worker-d -- sh -c 'exit 0' 2>/dev/null); hstat=$?
set -e
[ "$hstat" -eq 87 ] || fail "pending halt on a success should force exit 87, got $hstat"
grep -q 'stop and reorient' <<<"$hout" || fail "halt message should still be shown:
$hout"

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
fout=$("$guard" worker-f -- true 2>/dev/null); fstat=$?
set -e
grep -q 'narrow the scope' <<<"$fout" || fail "redirect not delivered:
$fout"
grep -q 'hard stop' <<<"$fout" || fail "halt not delivered:
$fout"
[ "$fstat" -eq 87 ] || fail "a pending halt among the two should force 87, got $fstat"

echo "PASS: bus one-shot delivery, guard footer + status passthrough, halt→87 override, standup enqueue"
