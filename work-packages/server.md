# Work package: server

- **State:** CLAIMED — worker-server, Sonnet 5 (Agent tool, general-purpose subagent)
- **Owner (role):** L3 implementer · **Model:** sonnet (integration
  judgment — socket lifecycle, partial-read handling, connection
  persistence across multiple pipelined commands — carries more open
  design surface than the other two packages' fully-enumerated contracts)
- **Base revision:** 3f70fdc (resp-codec and command-engine both ACCEPTED)
- **Intent:** Serves spec §"Firewalled Entities" entity 3 (server) and the
  spec's stated Decisions ("sequential accept loop, one connection served
  at a time" — "pipelined sequential" is the graded behavior). This
  entity is the only one that touches sockets; its whole job is composing
  C1 and C2 correctly without knowing RESP wire format or command
  semantics itself. If achieving real pipelining or clean teardown ever
  requires touching codec.py or engine.py internals, that is a boundary
  violation — huddle first (reversibility gate) rather than reach across.
- **Instruction:** Harden `targets/resp/server.py` from its tracer-bullet
  stub (one command per connection, no partial-read handling, no
  malformed-input teardown) into the real socket loop described in the
  spec: sequential `accept()` loop (one connection served at a time is
  fine — no threading/async needed, matches the spec's Decisions);
  per-connection, read from the socket in a loop, feed bytes to a
  `codec.Parser`, `execute()` each resulting frame against **one shared
  `engine.Engine` instance constructed once for the whole server process**
  (not per-connection — C2's state-visibility invariant), `encode()` and
  write each reply, and keep the connection open for multiple sequential
  and pipelined commands until the client disconnects. On `codec.ProtocolError`,
  close the connection (connection-fatal per C1) rather than crash the
  server process. Must accept `--port <port>` and fall back to `$PORT`
  (already wired in the tracer stub — preserve this CLI contract, the
  conformance exam depends on it exactly as documented in
  `docs/specs/2026-09-02-resp-tracer.md`'s Conformance grading section).
- **Non-goals:** concurrency beyond one connection at a time (explicit
  spec non-goal); authentication; TLS; any RESP parsing or command logic
  of your own (delegate everything to codec/engine — if you find yourself
  writing a `b"PING"` string literal or a `+OK\r\n` byte string in
  server.py, that's very likely scope creep back into C1/C2's territory).
- **Owned scope:** `targets/resp/server.py` only. Read anything else in
  the repo; do not edit `targets/resp/codec.py`, `targets/resp/engine.py`,
  or any file under `targets/resp/tests/`.
- **Dependencies:** C1 (`contracts/C1-resp-codec.md`, `Parser`/`encode`)
  and C2 (`contracts/C2-command-engine.md`, `Engine.execute`) — both at
  v1, **both ACCEPTED** before this package is claimed (sequenced after,
  not parallel with, the other two — server needs the real
  implementations to test its own integration behavior against, not the
  tracer stubs). Ordinary use of both published contracts; not gated.
- **Acceptance criteria:**
  - A raw-socket client can open one connection, send two pipelined RESP
    array requests before reading either reply, and receive both correct
    replies in order (the spec's graded pipelining behavior).
  - A connection serves multiple sequential commands (not just one) before
    the client disconnects.
  - A malformed frame closes that connection without crashing the server
    process (the next new connection still works).
  - Store state set by one connection (e.g. `SET k v`) is visible to a
    later, separate connection (proves one `Engine` instance for the
    server's lifetime, not one per connection).
  - `python3 targets/resp/server.py --port <N>` and `PORT=<N> python3
    targets/resp/server.py` both work.
  - Write these as your own tests (this package has no frozen boundary
    test file — author `targets/resp/tests/test_server_integration.py` in
    your owned scope, since integration behavior needs real codec+engine
    to test against, which is why this package is sequenced last).
- **Boundary tests:** none pre-written (see above — author your own
  integration tests; they become the acceptance evidence, same as any
  boundary test).
- **Budget:** ~150K tokens / one discrete turn.
- **Stop conditions:** the same test failing three distinct ways → stop,
  reorient once, then escalate.
- **Escalation destination:** L6 lead (this session) — leave a `BLOCKED`
  status entry; discrete-turn worker, end your turn rather than loop.
- **Deviation envelope:** default (doctrine) — loose.
- **Expected artifact:** commit(s) on branch `pilot-resp` implementing
  `targets/resp/server.py` and its own integration tests;
  `status/server.md` updated; deviations logged to
  `events/resp-tracer/worker-server.md`.
