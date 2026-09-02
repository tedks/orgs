# Event ledger shard: worker-engine (resp-tracer sprint)

## worker-engine:1 · 2026-09-02T20:26:18Z · deviation
- actor: worker-engine (Claude Code, Haiku 4.5)
- based_on: e472628
- refs: work-packages/command-engine.md, contracts/C2-command-engine.md
- no deviations this package (INITIAL ASSESSMENT). `targets/resp/engine.py` was hardened per contracts/C2-command-engine.md and work-packages/command-engine.md without departures: all six goal commands (PING, ECHO, GET, SET, DEL, INCR) implemented per the dispatch table exactly, matching arity rules, error text, and state persistence semantics. Engine class kept with same name and location, `execute()` method name preserved, imports limited to Frame types from codec (no Parser/encode dependencies). All 26 frozen boundary tests pass. No owned-scope files other than engine.py were edited.

## worker-engine:2 · 2026-09-02T20:32:00Z · interpretation-filed
- actor: worker-engine (Claude Code, Haiku 4.5)
- based_on: a6daa5f
- refs: contracts/C2-command-engine.md §"Intentionally unspecified", lead review REWORK finding
- issue: `execute()` crashes with `AttributeError: 'NoneType' object has no attribute 'lower'` when the command-name slot is a RESP nil bulk string (`BulkString(None)`). This is wire-producible: C1 parser happily yields `[Array([BulkString(None)])]` for `*1\r\n$-1\r\n`. C2 contract does not specify behavior for nil command-name. Without a guard, the server process crashes entirely (no try/except around `eng.execute(frame)` in server.py).
- interpretation (lead-provided): treat nil-valued command-name `BulkString` same as any unrecognized command — return `Error` frame, never raise exception. Observable behavior: no exception, `Error("ERR unknown command ''")` reply.
- fix applied: guard `execute()` to check `if name_value is None` before calling `.lower()`, branch into unknown-command error path.
- rollback: none needed; fix applied in place to engine.py.
- verification: repro case `Engine().execute(Array([BulkString(None)]))` now returns `Error` frame, not exception. All 26 boundary tests still pass (verified).
