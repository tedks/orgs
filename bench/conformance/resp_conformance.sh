#!/usr/bin/env bash
# resp_conformance.sh — the frozen RESP exam. The org does NOT grade itself:
# this drives the built server exclusively through a real `redis-cli` and
# asserts protocol-correct replies. Implementers may run it but never edit it
# (changes are spec amendments).
#
# Usage: resp_conformance.sh <server-cmd...>
#   <server-cmd...> starts the server; it MUST accept `--port <port>` (or read
#   $PORT) and listen on that TCP port. Example:
#       resp_conformance.sh python3 targets/resp/server.py
#
# Exit: 0 all assertions pass · 1 an assertion failed · 2 harness/setup error.
#
# Status in v0: SKELETON. The assertion list below is the frozen spec of what
# "conformant" means for the RESP tracer goals (PING ECHO GET SET DEL INCR,
# binary-safe, wrong-arity errors, non-integer INCR, missing-key GET,
# pipelining). It is wired to run once a server binary exists; until then it
# exits 2 with a clear "no server" message rather than pretending to pass.
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: resp_conformance.sh <server-cmd...>" >&2; exit 2; }
command -v redis-cli >/dev/null 2>&1 || { echo "conformance: redis-cli not found (the external grader)" >&2; exit 2; }

port=$(( (RANDOM % 20000) + 20000 ))
srv_pids=()
cleanup() { for p in "${srv_pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

# Start the server with the chosen port exposed both ways.
PORT="$port" "$@" --port "$port" &
srv_pids+=($!)

# Wait up to 5s for the port to accept connections.
ready=0
for _ in $(seq 1 50); do
    if redis-cli -p "$port" PING >/dev/null 2>&1; then ready=1; break; fi
    sleep 0.1
done
[ "$ready" -eq 1 ] || { echo "conformance: server did not become ready on port $port" >&2; exit 2; }

pass=0 fail=0
cli() { redis-cli -p "$port" "$@"; }
check() { # <description> <expected> <actual>
    if [ "$2" = "$3" ]; then pass=$((pass+1));
    else fail=$((fail+1)); echo "FAIL: $1 — expected [$2] got [$3]" >&2; fi
}

# --- Frozen assertion list (the exam) ---------------------------------------
check "PING"                 "PONG"  "$(cli PING)"
check "ECHO hello"           "hello" "$(cli ECHO hello)"
check "SET k v"              "OK"    "$(cli SET k v)"
check "GET k"                "v"     "$(cli GET k)"
check "GET missing (nil)"    ""      "$(cli GET nope)"
check "DEL k"                "1"     "$(cli DEL k)"
check "DEL missing"          "0"     "$(cli DEL nope)"
check "SET n 10 / INCR"      "11"    "$(cli SET n 10 >/dev/null; cli INCR n)"
# binary-safe value with embedded CR LF and a NUL byte. A NUL cannot survive
# an argv, so the value is written via `redis-cli -x` (value read from stdin).
# Read back with `--raw` (NOT --no-raw, which escapes NUL/CR/LF to literal
# text like \x00) and hex-dump before the shell can strip the NUL. redis-cli
# --raw appends a newline as its output delimiter, so tolerate one trailing
# 0a on the readback.
printf 'a\r\nb\x00c' | cli -x SET bin >/dev/null
want=$(printf 'a\r\nb\x00c' | od -An -tx1 | tr -d ' \n')
# `|| got=...`: a plain assignment lets pipefail's nonzero status (e.g. the
# server dying mid-run) trip errexit and abort with no FAIL line; the OR list
# suppresses that so `check` reports a real failure instead.
got=$(cli --raw GET bin | od -An -tx1 | tr -d ' \n') || got="<no reply>"; got=${got%0a}
check "binary-safe SET/GET (CRLF+NUL)" "$want" "$got"
# error replies (redis-cli prints the error text)
check "INCR non-integer errs" "1" "$(cli SET s abc >/dev/null; cli INCR s 2>&1 | grep -c -i 'not an integer\|error')"
check "SET wrong arity errs"  "1" "$(cli SET onlykey 2>&1 | grep -c -i 'wrong number\|error')"
# True pipelining on one connection: BOTH requests are written before either
# reply is read. redis-cli cannot assert this — feeding it two lines sends
# them sequentially (write/read/write/read), and `--pipe` reports only
# transfer statistics, not the replies — so a redis-cli-only check would pass
# a server that cannot pipeline at all. We drive raw RESP over one socket via
# bash's /dev/tcp. The two requests are proper RESP arrays (`*1\r\n$4\r\nPING\r\n`,
# not the inline form, which the contracts do not require and the spec leaves
# open), and the read is bounded by `timeout` so a server that answers once
# and stalls fails the assertion instead of hanging the exam. Hex-compared so
# CR bytes survive the shell.
pl_want=$(printf '+PONG\r\n+PONG\r\n' | od -An -tx1 | tr -d ' \n')
pl_got=$(timeout 5 bash -c '
    exec 3<>"/dev/tcp/127.0.0.1/'"$port"'" || exit 1
    printf "*1\r\n\$4\r\nPING\r\n*1\r\n\$4\r\nPING\r\n" >&3
    head -c 14 <&3
    exec 3>&- 3<&-' 2>/dev/null | od -An -tx1 | tr -d ' \n') || pl_got="<no reply / timeout>"
check "pipelined PING;PING (raw RESP arrays, one conn)" "$pl_want" "$pl_got"
# ----------------------------------------------------------------------------

echo "conformance: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
