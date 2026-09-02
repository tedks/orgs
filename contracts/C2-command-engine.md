# Contract: C2 command-engine v1

- **Owner:** command-engine work package (accountable lead: L6 lead,
  collapsed hat) · **Consumers (ack list):** server.
- **Location:** `targets/resp/engine.py`. The tracer bullet (M1, commit
  `4281655`) already defines the module shape below in crude/stub form
  (PING only); the command-engine work package hardens it in place —
  same names, same file, real implementations.
- **Dependencies:** C1's Frame data model (`SimpleString`, `Error`,
  `Integer`, `BulkString`, `Array` classes from `targets/resp/codec.py`)
  — **types only**. command-engine imports these five classes to build
  and read frames; it does not call, and has no dependency on,
  `Parser.feed` or `encode` (per spec: "No bytes, no sockets").

## Inputs / outputs

**`Engine` class**, instantiated once per server process (see State
visibility below):
- `Engine().execute(command: Array) -> Frame` — `command` is always an
  `Array` frame whose `.value` is a non-empty `list[BulkString]` (the
  server guarantees non-empty and all-BulkString before calling; an
  empty or non-BulkString-containing Array is a server-side contract
  violation, not a case `execute` must handle — see Intentionally
  unspecified). `command.value[0].value` (bytes) is the command name,
  matched **case-insensitively** (`b"ping"`, `b"PING"`, `b"PiNg"` all
  dispatch identically); `command.value[1:]` are the arguments.
- Returns exactly one reply `Frame`: `SimpleString`, `Error`, `Integer`,
  or `BulkString` (never `Array` — none of this sprint's goal commands
  reply with an array).

## Per-command semantics (the six goal commands)

| Command | Arity (excl. name) | Behavior | Reply |
|---|---|---|---|
| `PING` | 0 | — | `SimpleString("PONG")` |
| `PING` | 1 | — | `BulkString(arg)` (echoes the argument, matching real Redis `PING <msg>`) |
| `PING` | 2+ | — | `Error("ERR wrong number of arguments for 'ping' command")` |
| `ECHO` | 1 | — | `BulkString(arg)` |
| `ECHO` | 0 or 2+ | — | `Error("ERR wrong number of arguments for 'echo' command")` |
| `GET` | 1 (key) | key present | `BulkString(store[key])` |
| `GET` | 1 (key) | key absent | `BulkString(None)` (RESP nil) |
| `GET` | 0 or 2+ | — | `Error("ERR wrong number of arguments for 'get' command")` |
| `SET` | 2 (key, value) | — | `store[key] = value`; `SimpleString("OK")` |
| `SET` | not 2 | — | `Error("ERR wrong number of arguments for 'set' command")` |
| `DEL` | 1+ (keys...) | — | delete each present key; `Integer(count deleted)` |
| `DEL` | 0 | — | `Error("ERR wrong number of arguments for 'del' command")` |
| `INCR` | 1 (key) | key absent | store key = `b"1"`; `Integer(1)` |
| `INCR` | 1 (key) | key present, parses as base-10 int | store key = new value as ASCII bytes; `Integer(new)` |
| `INCR` | 1 (key) | key present, does not parse as base-10 int | `Error("ERR value is not an integer or out of range")`, store unchanged |
| `INCR` | 0 or 2+ | — | `Error("ERR wrong number of arguments for 'incr' command")` |
| *(anything else)* | — | unrecognized command name | `Error("ERR unknown command '<name>'")` — included for robustness (a garbage command must not crash the engine), not itself a goal-command assertion in the frozen exam |
| *(nil command name)* | — | `command.value[0].value is None` (a RESP nil `BulkString` in the name slot — legal per C1, wire-producible via `*1\r\n$-1\r\n`) | `Error("ERR unknown command ''")` — same path as an unrecognized command name, never raises |

- `SET` takes **no options** (no `EX`/`PX`/`NX`/`XX` — expiry is a spec
  non-goal). Any arg count other than exactly 2 is a wrong-arity error;
  this is a deliberate simplification of real Redis's richer `SET`
  grammar, made because expiry/conditional-set are explicitly out of
  spec scope. Logged here rather than silently — flag an interpretation
  request if this reads as too narrow once real usage is seen.
- The store holds one value type: `bytes`. `INCR`'s integer parsing reads
  the stored bytes as ASCII and requires the *entire* value to be a valid
  base-10 integer literal (`int(value.decode('ascii'))`, no surrounding
  whitespace) — decode or parse failure is the non-integer error case.
  No 64-bit range clamp (Python ints are unbounded) — a deliberate
  divergence from real Redis's overflow error, undocumented in the spec
  because `INCR` overflow isn't a graded goal-command case; flag as an
  interpretation candidate if it matters later.

## Behavioral invariants

- **Deterministic:** the same command sequence against a fresh `Engine`
  produces the same sequence of replies, every time.
- **State visibility:** the store lives on the `Engine` instance. One
  `Engine` instance is constructed once per server process lifetime (not
  per connection) — its state must be visible to every `execute()` call
  made against it regardless of which connection produced the command
  (real Redis persists data across client reconnects within the
  process's lifetime). Constructing a fresh `Engine` per connection would
  violate this and is a server-side contract violation, not a
  command-engine defect.
- **No I/O:** `execute()` never touches a socket or the filesystem
  (persistence is a non-goal).

## Failure semantics

- Wrong arity and `INCR` non-integer are **not exceptions** — they are
  ordinary `Error` frame replies (RESP2 has no concept of a fatal error
  from a well-formed command; the connection stays open). `execute()`
  raising a Python exception for any of the documented cases above is
  itself a defect.
- `execute()` may assume `command` is a well-formed `Array[BulkString]`
  with at least one element (see Intentionally unspecified) — the server
  is responsible for only calling `execute()` with such input.

## Intentionally unspecified

- Behavior when `command.value` is empty, is `None` (nil `Array`), or
  contains a non-`BulkString` element — not a case the boundary tests
  exercise; `execute()` may raise or behave arbitrarily. The server is
  the enforcement point for this precondition (see
  `targets/resp/server.py`'s `_is_command()` guard, added by the server
  work package specifically because these shapes are C1-well-formed and
  therefore wire-reachable) — it must not let such a frame reach
  `execute()`. This carve-out is deliberately narrower than it was at v1
  authoring: a *nil command-name* (`BulkString(None)` as element 0 of an
  otherwise well-formed `Array[BulkString]`) is **not** in this
  unspecified set — see the per-command table's "(nil command name)"
  row, added 2026-09-02 as a clarification (STATES.md Interpretation:
  fills silence, narrows no previously-promised behavior — nothing could
  have relied on "arbitrary" before this). Provenance: found by lead
  review on the command-engine work package (a wire-producible input the
  frozen boundary tests didn't probe, causing an uncaught `AttributeError`
  that would have crashed the whole server process); ruled by the lead as
  contract owner; implemented in `engine.py` and independently
  defended-in-depth by the server's own `_is_command()` guard.
- Case handling of argument *values* (e.g. key names) — always treated as
  opaque bytes, case-sensitive; only the **command name** is
  case-folded.
- Whether the store is a `dict` or something else internally — only
  `execute()`'s observable behavior is contractual.

## Versioning / compatibility policy

v1. Adding a new command is additive/non-breaking. Changing an existing
command's reply shape, arity rule, or error text convention is breaking —
command-engine (provider) fixes all call sites (server) on a breaking
change. (Exact error text is not asserted by the frozen conformance exam,
which greps loosely — see `bench/conformance/resp_conformance.sh` — but
boundary tests here do assert the documented text as a contract, so
changing it still requires updating those tests as part of the breaking
change.)

## Boundary tests

`targets/resp/tests/test_engine_boundary.py` — pre-written by the lead at
decomposition; consumer-driven (encodes what server needs from engine —
every goal command's happy path, every documented arity/error case,
state persisting across `execute()` calls on one instance). Run:
`python3 -m unittest discover -s targets/resp/tests`.

## Interpretation register

- **2026-09-02 · clarification · PROMOTED.** Nil command-name
  (`BulkString(None)` as `command.value[0]`) is defined behavior, not
  unspecified: `Error("ERR unknown command ''")`, never a raised
  exception. Filed as `worker-engine:2`
  (`events/resp-tracer/worker-engine.md`), ruled by the lead
  (`events/resp-tracer/lead.md` lead:12/lead:18), promoted here
  immediately per protocol. See per-command table and "Intentionally
  unspecified" above.
