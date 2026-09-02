# Work package: command-engine

- **State:** ACCEPTED — lead review round 1 REWORK (lead:12), round 2 CLEAN (lead:16), fixpoint
- **Owner (role):** L3 implementer · **Model:** haiku (the semantics are
  fully enumerated in the contract's dispatch table — this package tests
  whether a cheap model can execute a precisely specified table correctly
  without independent design judgment)
- **Base revision:** d34d638
- **Intent:** Serves spec §"Firewalled Entities" entity 2 (command-engine)
  and the M2 fan-out milestone. This boundary is where Redis-compatible
  *meaning* lives — every goal command's happy path, arity error, and the
  `INCR` non-integer error. Server must be able to hand you a parsed
  command and trust the reply is correct without knowing anything about
  keys, values, or RESP wire format itself.
- **Instruction:** Harden `targets/resp/engine.py` from its tracer-bullet
  stub (PING-only) to the full C2 contract: `contracts/C2-command-engine.md`.
  Implement the `Engine` class's `execute(command: Array) -> Frame` for
  all six goal commands (`PING`, `ECHO`, `GET`, `SET`, `DEL`, `INCR`) per
  the contract's per-command semantics table exactly — arities, error
  text, `INCR`'s non-integer handling, `DEL`'s variadic count, and an
  `Error` reply (never a raised exception) for an unrecognized command
  name. Import `SimpleString`/`Error`/`Integer`/`BulkString`/`Array` from
  `codec` (types only — do not call `codec.Parser` or `codec.encode`; C2
  has no bytes/socket dependency).
- **Non-goals:** expiry, persistence, transactions, pub/sub, any command
  outside the six listed, 64-bit overflow clamping on `INCR` (contract
  says unbounded is fine for this sprint), value types other than `bytes`
  (no hashes/lists/sets — everything is a flat string store).
- **Owned scope:** `targets/resp/engine.py` only. Read anything else in
  the repo; do not edit `targets/resp/codec.py`, `targets/resp/server.py`,
  or any file under `targets/resp/tests/` (frozen — file a docs-bug or
  interpretation request against `contracts/C2-command-engine.md` instead
  of editing a test that looks wrong).
- **Dependencies:** C1 Frame data model (`contracts/C1-resp-codec.md`) —
  types only (`SimpleString`, `Error`, `Integer`, `BulkString`, `Array`).
  These five classes already exist in `targets/resp/codec.py` (defined by
  the tracer bullet and unaffected by the parallel resp-codec work
  package's hardening — the class shapes are frozen, only the parsing
  internals change) — safe to import and construct now.
- **Acceptance criteria:**
  - `python3 -m unittest discover -s targets/resp/tests -p
    'test_engine_boundary.py'` passes 100%, unmodified.
  - Every documented arity error returns an `Error` frame — `execute()`
    must never raise a Python exception for a documented case, including
    the wrong-command-name case.
  - State (the key-value store) lives on the `Engine` instance and is
    visible to later `execute()` calls on the same instance, but a fresh
    `Engine()` has no state from any other instance.
  - `INCR` on a key holding a non-integer string returns an `Error` and
    leaves the stored value unchanged (does not corrupt or clear it).
- **Boundary tests:** `targets/resp/tests/test_engine_boundary.py`
  (frozen; do not edit).
- **Budget:** ~100K tokens / one discrete turn.
- **Stop conditions:** the same boundary test failing three distinct ways
  → stop, reorient once (re-read the contract's dispatch table row for
  that exact command/arity), then escalate to the lead if still stuck.
- **Escalation destination:** L6 lead (this session) — leave a `BLOCKED`
  status entry with the exact failing case; discrete-turn worker, end your
  turn rather than loop.
- **Deviation envelope:** default (doctrine) — loose.
- **Expected artifact:** commit(s) on branch `pilot-resp` implementing
  `targets/resp/engine.py`; `status/command-engine.md` updated;
  deviations logged to `events/resp-tracer/worker-engine.md`.
