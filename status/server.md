# Status entry: server

- **State:** ACCEPTABLE-PENDING-REVIEW (implementation complete, self-reviewed,
  all owned tests green; awaiting lead review for ACCEPTED)
- **Current task:** Hardened `targets/resp/server.py` from the M1 tracer-bullet
  stub (one recv(), one frame, one connection) to the full socket lifecycle:
  sequential accept loop, per-connection read/parse/execute/encode/write loop
  serving multiple sequential and pipelined commands, one shared `Engine`
  instance for the process lifetime, clean per-connection teardown on
  `codec.ProtocolError` or a command-shaped precondition violation (see
  deviation below), and `--port`/`$PORT` CLI contract preserved unchanged.
  Authored `targets/resp/tests/test_server_integration.py` (15 tests, own
  scope) covering all four acceptance-criteria bullets plus the edge cases
  called out in the work package (zero-byte disconnect, partial frame then
  disconnect, empty/nil Array command, non-BulkString element, non-Array
  top-level frame). Full suite (`targets/resp/tests/`, 82 tests) green.
- **Last commit:** a012a14 · "server: harden socket loop to full spec
  behavior, add integration tests"
- **Budget burned:** ~60K tokens (reading spec/contracts/work-package/
  existing modules, implementation, test authoring, debugging one flawed
  test fixture, verification runs, status/event-log write-up) of the ~150K
  budget. Well within one discrete turn.
- **Blocked on:** none.
- **Deviations logged:** worker-server:1 (deviation — defensive guard added
  before calling `engine.execute()`; not a contract violation, a precondition
  C2 explicitly assigns to the server). See
  `events/resp-tracer/worker-server.md`.
- **Updated:** 2026-09-02T21:10:00Z

## Acceptance-criteria self-review (work-packages/server.md)

1. **A raw-socket client can open one connection, send two pipelined RESP
   array requests before reading either reply, and receive both correct
   replies in order.** — **Met.** Verified by
   `TestPipelining.test_two_pipelined_requests_both_replies_correct_and_in_order`
   (writes `PING` + `ECHO hi` back-to-back before reading, asserts
   `PONG` then `hi` in order) and
   `TestPipelining.test_pipelined_requests_split_across_recv_boundaries`
   (same, but the two encoded commands are written one byte at a time,
   forcing reassembly across arbitrary `recv()`/`Parser.feed()` chunk
   boundaries — proves the loop doesn't assume one `recv()` == one
   command). Both pass.

2. **A connection serves multiple sequential commands (not just one)
   before the client disconnects.** — **Met.** Verified by
   `TestSequentialCommands.test_multiple_sequential_commands_on_one_connection`
   (SET, GET, SET, GET, DEL — five sequential round-trips on one
   connection, all correct). Passes.

3. **A malformed frame closes that connection without crashing the server
   process (the next new connection still works).** — **Met.** Verified by
   `TestMalformedFrameTeardown.test_malformed_frame_closes_connection_without_crashing_server`
   (bad type sigil `!invalid\r\n`) and
   `test_bad_bulk_string_length_boundary_closes_connection` (length/payload
   boundary mismatch, all bytes present so it's a real `ProtocolError`, not
   an incomplete-frame wait) — both assert the bad connection sees EOF, the
   server process is still alive (`psutil`-free liveness check via
   `proc.poll() is None`), and a fresh connection right after still answers
   `PING`. Passes.

4. **Store state set by one connection (e.g. `SET k v`) is visible from a
   separate, later connection (proves one shared `Engine`, not one per
   connection).** — **Met.** Verified by
   `TestSharedEngineState.test_state_set_on_one_connection_visible_from_another`
   (SET on connection 1, GET on connection 2 sees it) and
   `test_incr_state_accumulates_across_connections` (INCR on connection 1
   then connection 2 accumulates 1 -> 2, which could only happen against one
   shared `Engine`). Both pass.

5. **`python3 targets/resp/server.py --port <N>` and `PORT=<N> python3
   targets/resp/server.py` both work.** — **Met.** Verified by
   `TestCliPortContract.test_dashdash_port_flag` and
   `test_port_env_var` (each launches the server the respective way,
   waits for the port to accept connections, sends `PING`, asserts
   `PONG`). Both pass. CLI wiring in `main()` was not touched — the
   `--port`/`$PORT` fallback logic from the tracer stub is unchanged.

6. **Own integration tests, no frozen boundary-test file for this
   package.** — **Met.** `targets/resp/tests/test_server_integration.py`,
   15 tests, launches the server as a real subprocess on an OS-assigned
   ephemeral port and drives it with a raw-socket RESP2 client
   independent of `codec.py` (per instruction: don't import server.py's
   internals or depend on the codec module being correct to validate
   itself). Covers the four bullets above plus additional edge cases (see
   deviation below and Test output).

## Test output

```
$ python3 -m unittest discover -s targets/resp/tests -v
... (82 tests total: 26 codec boundary/impl + 26 engine boundary + 15 server
     integration + a handful of codec_impl extras)
----------------------------------------------------------------------
Ran 82 tests in ~1.2s

OK
```

Full `-v` transcript for the server package specifically:

```
$ python3 -m unittest targets.resp.tests.test_server_integration -v
test_dashdash_port_flag (TestCliPortContract) ... ok
test_port_env_var (TestCliPortContract) ... ok
test_bad_bulk_string_length_boundary_closes_connection (TestMalformedFrameTeardown) ... ok
test_client_disconnect_with_zero_bytes_does_not_crash_server (TestMalformedFrameTeardown) ... ok
test_empty_array_command_closes_connection_without_crashing_server (TestMalformedFrameTeardown) ... ok
test_malformed_frame_closes_connection_without_crashing_server (TestMalformedFrameTeardown) ... ok
test_nil_array_command_closes_connection_without_crashing_server (TestMalformedFrameTeardown) ... ok
test_non_array_top_level_frame_closes_connection (TestMalformedFrameTeardown) ... ok
test_non_bulkstring_array_element_closes_connection (TestMalformedFrameTeardown) ... ok
test_partial_frame_then_disconnect_does_not_crash_server (TestMalformedFrameTeardown) ... ok
test_pipelined_requests_split_across_recv_boundaries (TestPipelining) ... ok
test_two_pipelined_requests_both_replies_correct_and_in_order (TestPipelining) ... ok
test_multiple_sequential_commands_on_one_connection (TestSequentialCommands) ... ok
test_incr_state_accumulates_across_connections (TestSharedEngineState) ... ok
test_state_set_on_one_connection_visible_from_another (TestSharedEngineState) ... ok

----------------------------------------------------------------------
Ran 15 tests in 1.198s

OK
```

Also ran `bench/conformance/resp_smoke_rawsocket.py` (the raw-socket
substitute for the frozen exam, since `redis-cli` is unavailable in this
sandbox) against the hardened server: `12 passed, 0 failed`. This is
weaker evidence than the real frozen `resp_conformance.sh` exam (see that
script's own docstring) but it's an additional, independently-written
cross-check of goal-command behavior end-to-end through the real socket
process, and it was green.

## Implementation summary

**File:** `targets/resp/server.py`

- `serve(port)`: unchanged shape — binds, listens, sequential `accept()`
  loop, one shared `engine.Engine()` constructed once before the loop
  starts.
- `_handle_connection(conn, eng)`: new — owns one connection's whole
  lifetime. Loops `conn.recv(65536)`, feeds bytes to a per-connection
  `codec.Parser`, and for each completed frame: validates it's a
  dispatchable command shape (see deviation), calls `eng.execute()`,
  `codec.encode()`s the reply, writes it back. Returns (closing the
  connection via the caller's `with conn:`) on: `data == b""` (client
  EOF, including immediate zero-byte disconnect), `codec.ProtocolError`
  (never calls `feed()` again on that parser afterward, per C1), a
  non-command-shaped frame, or `OSError` from `recv()`/`sendall()`
  (client reset/broken pipe). No exception escapes `_handle_connection`,
  so the top-level accept loop always keeps running.
- `_is_command(frame)`: new — the precondition guard described in the
  deviation below.
- `main()` / CLI `--port`/`$PORT` handling: byte-for-byte unchanged.

No edits to `codec.py`, `engine.py`, or any file under
`targets/resp/tests/` other than the new `test_server_integration.py`.
No RESP wire literals or command-semantics literals were introduced in
`server.py` — the only content server.py "knows" about a command's shape
is the generic Array/BulkString-list precondition from C2's own contract
text, not any specific command's name or reply text.
