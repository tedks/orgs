# Work package: wp-server

- **State:** READY
- **Owner (role):** implementer, entity `server` · **Model:** haiku
  (tiering ON this run)
- **Base revision:** 33d8591
- **Intent:** serve the spec's socket-lifecycle goal — accept connections,
  read bytes, drive them through the codec and engine contracts, write
  replies, tear down cleanly — and specifically the **pipelining** goal
  ("pipelined sequential requests on one connection"), which is a
  server-entity property, not codec's or engine's alone. When an
  instruction below and this intent conflict, serve correct socket
  lifecycle/pipelining over the letter of any one bullet.
- **Instruction:** harden `targets/resp/server.py` (already a working
  tracer for the PING path — accept loop, read→feed→execute→encode→send,
  sequential one-connection-at-a-time per the spec's concurrency decision)
  and add tests demonstrating pipelining and connection teardown explicitly
  — the frozen exam's hardest assertion drives raw RESP over a socket
  precisely because this can't be proven through `redis-cli` alone; prove
  it yourself the same way.
- **Non-goals:** concurrency beyond one connection at a time; performance
  claims; anything the codec/engine contracts don't require you to
  interpret. **Inline (non-RESP-array) commands are ruled out of scope**
  for this sprint (spec's "Open Questions" item — the tracer already
  proved `redis-cli`'s normal `PING` works over standard RESP-array
  framing without inline support, so the "discovered at M1" condition
  resolved to no; see `events/resp-r4/lead.md` lead:5).
- **Owned scope:** `targets/resp/server.py`, plus
  `targets/resp/tests/test_server_e2e.py`, which you must add: a
  raw-socket pipelining test is a required acceptance criterion below, not
  optional, since it's the one exam assertion `redis-cli` structurally
  cannot exercise. Don't touch `codec.py` or `engine.py` — they're published contracts
  (C1/C2); if what they publish doesn't cover something you need, file an
  interpretation rather than reaching into their source. Your copies of
  those two files in your worktree are the M1 tracer versions (PING-only
  engine) — that's fine, your job doesn't require the full command set to
  be implemented yet, only that you correctly pass whatever `Frame` the
  engine returns back through `encode()` to the client. wp-codec and
  wp-engine are extending their files on separate branches; the lead
  integrates all three.
- **Dependencies:** `contracts/C1-resp-codec.md` v1 (`RespCodec.feed`,
  `encode`, `ProtocolError`) and `contracts/C2-command-engine.md` v1
  (`Engine.execute`). Use them exactly as published; don't assume
  anything C1/C2 mark "intentionally unspecified."
- **Acceptance criteria:**
  - `PING` still answers `PONG` end to end (don't regress the tracer).
  - **Pipelining:** two (or more) requests written to the socket before
    either reply is read are both answered correctly, in order, on one
    connection — matching the frozen exam's raw-`/dev/tcp` assertion
    (`bench/conformance/resp_conformance.sh`, the "pipelined PING;PING"
    check). Demonstrate this with your own raw-socket test, not just by
    reasoning about the code — `redis-cli` cannot exercise this (it
    reads/writes sequentially), which is exactly why the exam doesn't use
    it for this assertion either.
  - **Connection teardown:** the server doesn't crash or hang when a
    client closes its connection mid-stream (including with a partial,
    incomplete frame buffered) or after a clean request/response; it
    returns to accepting new connections either way.
  - **Malformed input:** a `ProtocolError` from `feed()` closes that
    connection without crashing the server process; the accept loop keeps
    serving subsequent connections. (Sending an error reply before closing
    is real Redis's behavior but is not asserted by the frozen exam — your
    call whether to add it; if you do, log it as a one-line deviation
    since it's additive behavior, not a scope change.)
  - `--port <port>` (and reading `$PORT` as the tracer already does) keeps
    working — this is how the exam starts you.
  - Look at how the tracer currently builds a `command: list[bytes]` from
    an `Array` frame's items (it silently drops any item that isn't a
    non-null `BulkString`) and decide, in light of C1/C2, whether that's
    the right behavior for a command array containing something else (e.g.
    a null bulk string as an argument) — fix it if you conclude it's
    wrong, and say why either way in your report.
- **Boundary tests:** none published against server (nothing consumes it —
  it's the top of the boundary diagram); the frozen exam
  (`bench/conformance/resp_conformance.sh`) is the real acceptance gate for
  this entity and you may run it freely (never edit it) under
  `nix develop ./bench --command` against your own worktree's server —
  expect the ECHO/GET/SET/DEL/INCR-specific assertions to still fail on
  your branch alone since your copy of `engine.py` is PING-only; that's
  expected and not your bug to fix. The PING and pipelining assertions
  should pass on your branch alone.
- **Budget:** soft target ~one focused session (rough guide: well under 40
  tool calls / edit-test cycles).
- **Stop conditions:** the same test (yours, or a frozen-exam assertion you
  can legitimately run against PING-only engine) failing three distinct
  ways → reorient once, then escalate to the lead in your final report.
- **Escalation destination:** the lead (report back in your final message).
- **Deviation envelope:** default (doctrine) — log deviations in one line
  in your final report; huddle first only if you'd cross a contract
  boundary or can't name your rollback.
- **Expected artifact:** commits on branch
  `bench-run/r4-orgs-no-crystal-2026-09-03T1148Z-wp-server`, `server.py`
  hardened (and any new test file), reported back to the lead for merge.
