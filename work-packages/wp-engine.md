# Work package: wp-engine

- **State:** READY
- **Owner (role):** implementer, entity `command-engine` · **Model:** haiku
  (tiering ON this run)
- **Base revision:** 33d8591
- **Intent:** serve the spec's command-surface goal — `PING`, `ECHO`, `GET`,
  `SET`, `DEL`, `INCR` with correct RESP2 reply types and correct error
  replies for wrong arity and non-integer `INCR`. When an instruction below
  and this intent conflict, serve command-semantics correctness (what the
  exam actually asserts) over the letter of any one bullet.
- **Instruction:** bring `targets/resp/engine.py` (already a working tracer
  for `PING`) to full contract C2 compliance: implement `ECHO`, `GET`,
  `SET`, `DEL`, `INCR`, and cover it with the boundary tests already
  skeletoned in `targets/resp/tests/test_engine_contract.py`.
- **Non-goals:** expiry, persistence, transactions, pub/sub, `SET` options
  (`EX`/`NX`/...), auth, anything not in the goals list — reply an `Error`
  frame ("unknown command") for anything you don't recognize rather than
  silently accepting it.
- **Owned scope:** `targets/resp/engine.py`,
  `targets/resp/tests/test_engine_contract.py`. Nothing else — `codec.py`
  is a published contract (C1); import its `Frame` types, don't redefine
  or edit them. If C1 as published doesn't give you what you need, file an
  interpretation against `contracts/C1-resp-codec.md` rather than reaching
  into `codec.py`.
- **Dependencies:** `contracts/C1-resp-codec.md` v1 — you consume the
  `Frame` data model (`SimpleString`, `Error`, `Integer`, `BulkString`,
  `Array`) from `codec.py`; `execute(command: list[bytes]) -> Frame` never
  sees a `Frame` on the input side, only raw argument bytes already
  extracted from an `Array(BulkString...)` by the caller (server) — see C2
  for exactly why.
- **Acceptance criteria** (contract: `contracts/C2-command-engine.md`):
  - `PING` (already done in the tracer — don't regress: 0 args → `PONG`,
    1 arg → that arg echoed as a bulk string, 2+ args → arity error).
  - `ECHO <msg>`: exactly 1 arg → `BulkString(msg)`; other arities → an
    `Error` whose text contains "wrong number" (case-insensitive — the
    exam greps for this).
  - `GET <key>`: exactly 1 arg → `BulkString(value)` if present,
    `BulkString(None)` (nil) if absent; other arities → arity error.
  - `SET <key> <value>`: exactly 2 args → store, reply
    `SimpleString("OK")`; other arities (0, 1, or 3+) → arity error.
  - `DEL <key>`: exactly 1 arg → `Integer(1)` if it existed and was
    removed, `Integer(0)` if it didn't exist; other arities → arity error.
  - `INCR <key>`: exactly 1 arg → parse stored value (or treat absent key
    as `0`) as a base-10 signed integer, store `value + 1` as its decimal
    string, reply `Integer(new_value)`; if the stored value isn't
    integer-parseable, reply an `Error` whose text contains "not an
    integer" (case-insensitive); other arities → arity error.
  - Command names match case-insensitively (`ping`/`PING`/`PiNg`).
  - State visibility: one `Engine` instance is read-your-writes across
    sequential `execute()` calls (a `SET` is visible to a later `GET` on
    the same instance) — this is what lets the server share one `Engine`
    across every connection it accepts.
  - Binary safety: `SET`/`GET`/`INCR` treat the value as raw bytes — a
    value containing `\r`, `\n`, `\x00` stored via `SET` comes back
    unchanged via `GET` (don't decode/re-encode through `str` anywhere in
    the value path; `INCR`'s int-parse is the one place you do need
    text/int conversion, and only on the stored value, not on arbitrary
    binary values you're not incrementing).
  - `test_engine_contract.py`'s `TodoTests` class (currently `@skip`ped
    stubs) is filled in and passing — un-skip each as you cover it. Add
    more cases if the stubs don't capture something you find.
- **Boundary tests:** `targets/resp/tests/test_engine_contract.py` (yours
  to extend — this *is* the deliverable test suite for C2).
- **Budget:** soft target ~one focused session (rough guide: well under 40
  tool calls / edit-test cycles).
- **Stop conditions:** the same test failing three distinct ways → reorient
  once (re-read C2 §Behavioral invariants), then escalate to the lead in
  your final report.
- **Escalation destination:** the lead (report back in your final message).
- **Deviation envelope:** default (doctrine) — log deviations in one line
  in your final report; huddle first only if you'd cross a contract
  boundary or can't name your rollback.
- **Expected artifact:** commits on branch
  `bench-run/r4-orgs-no-crystal-2026-09-03T1148Z-wp-engine`, `engine.py`
  and `test_engine_contract.py` updated, all tests in the file green
  (`python3 -m unittest tests.test_engine_contract -v` from
  `targets/resp/`), reported back to the lead for merge.
