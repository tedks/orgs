# Event ledger shard: worker-server (resp-tracer sprint)

## worker-server:1 · 2026-09-02T21:10:00Z · deviation
- actor: worker-server (Claude Code, Sonnet 5)
- based_on: 4b21cc7
- refs: work-packages/server.md, contracts/C2-command-engine.md
  §"Inputs / outputs", §"Intentionally unspecified"
- what bent: added a precondition guard (`_is_command()`) in
  `targets/resp/server.py` that runs on every frame the codec parser
  yields, *before* it is handed to `eng.execute()`. A frame is only
  dispatched if it is an `Array` (not the RESP nil array), non-empty, and
  every element is a `BulkString`. Anything else is treated the same as
  a `codec.ProtocolError`: this connection is torn down cleanly, the
  server process keeps running, no reply is sent.
- why: C2 explicitly leaves `execute()`'s behavior undefined for an empty
  or nil `Array`, or one containing a non-`BulkString` element, and
  assigns the precondition to the caller: "the server is responsible for
  only calling execute() with such input" / "The server never constructs
  such a call (its own boundary tests cover that it doesn't)." Without
  this guard the precondition can be violated by wire input the codec
  happily parses as well-formed RESP2 — `*0\r\n` (empty array), `*-1\r\n`
  (nil array), and `*1\r\n:5\r\n` (non-BulkString element) are all legal
  frames per C1, not `ProtocolError`s, so nothing upstream of `execute()`
  stops them from reaching it. Confirmed by direct repro against the
  ACCEPTED `engine.py` (not a hypothetical):
  `Engine().execute(Array([]))` -> `IndexError: list index out of
  range`; `Engine().execute(Array(None))` -> `TypeError: 'NoneType'
  object is not subscriptable`; `Engine().execute(Array([Integer(5)]))`
  -> `AttributeError: 'int' object has no attribute 'lower'`. Any of
  these reaching `eng.execute()` uncaught inside `_handle_connection`
  would propagate out of the per-connection handler (nothing in the
  M1-stub server caught non-`ProtocolError` exceptions) and crash the
  whole accept loop — directly violating the acceptance criterion "a
  malformed frame closes that connection without crashing the server
  process." This is the same shape of gap as the nil command-name crash
  command-engine's lead review caught (worker-engine:2) — found here
  during my own pre-submission edge-case sweep per the work package's
  explicit prompt to think about it, not by an external reviewer.
- is this scope creep into C1/C2 territory: no — it does not implement
  any command semantics, construct any command-specific reply, or
  duplicate any parsing C1 already does. It only checks the generic
  Array/BulkString-list shape that C2's own contract text says is the
  server's job to enforce before calling `execute()`. No RESP wire byte
  literal or command-name/reply-text literal was introduced.
- rollback: revert `_is_command()` and the `if not _is_command(frame):
  return` branch in `_handle_connection()` (targets/resp/server.py); the
  rest of the connection loop is unaffected and continues to work for
  well-formed commands.
- verification: added four dedicated tests in
  `targets/resp/tests/test_server_integration.py`
  (`test_empty_array_command_closes_connection_without_crashing_server`,
  `test_nil_array_command_closes_connection_without_crashing_server`,
  `test_non_bulkstring_array_element_closes_connection`,
  `test_non_array_top_level_frame_closes_connection`) — each sends the
  offending wire bytes on one connection, asserts the connection gets
  EOF, asserts the server process is still alive
  (`ServerProcess.is_alive()`), and asserts a fresh connection right
  after still answers `PING`. All four pass; full suite
  (`targets/resp/tests/`, 82 tests) green.
