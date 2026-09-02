# Contract: C1 resp-codec v1

- **Owner:** resp-codec work package (accountable lead: L6 lead, collapsed
  hat) · **Consumers (ack list):** server (C2's command-engine consumes
  only the Frame data model below, not `feed`/`encode` — see C2's
  Dependencies).
- **Location:** `targets/resp/codec.py`. The tracer bullet (M1, commit
  `4281655`) already defines the module shape below in crude/stub form;
  the resp-codec work package hardens it in place — same names, same
  file, real implementations.

## Inputs / outputs

**Frame data model** — five frame types, each a class with one `.value`
attribute (already stubbed in the tracer; `Error` and `Integer` are new):

| Type | `.value` | RESP2 wire form |
|---|---|---|
| `SimpleString` | `str` (no embedded `\r` or `\n`) | `+<value>\r\n` |
| `Error` | `str` (no embedded `\r` or `\n`) | `-<value>\r\n` |
| `Integer` | `int` | `:<value>\r\n` |
| `BulkString` | `bytes`, or `None` for RESP nil | `$<len>\r\n<bytes>\r\n`, or `$-1\r\n` for `None` |
| `Array` | `list[Frame]`, or `None` for RESP nil array | `*<len>\r\n<elements>`, or `*-1\r\n` for `None` |

`BulkString.value` is **binary-safe**: arbitrary bytes, including embedded
`\r`, `\n`, and NUL. Length is a byte count, not a text length.

**`Parser` class**, instantiated once per connection:
- `Parser().feed(data: bytes) -> list[Frame]` — incremental. Feed any
  chunk boundary (a single byte at a time must work); returns the list of
  frames that became complete as a result of this call (zero, one, or
  many), and retains any incomplete trailing bytes internally for the
  next `feed()` call. A `Parser` instance is single-connection, stateful,
  not thread-safe, not reusable after a `ProtocolError`.
- Only top-level `Array` frames need to be parsed from client input for
  this sprint's goal (commands arrive as `Array[BulkString]`), but the
  parser must recognize all five types generally — the boundary tests
  exercise decoding each type, not just Array/BulkString, because C1 has
  no other consumer to narrow the promise to "requests only."

**`encode(frame: Frame) -> bytes`** — free function, the inverse of
`feed`: serializes exactly one frame per call, all five types.

## Behavioral invariants

- **Incremental / chunk-boundary independence:** `feed()` called with a
  frame split across arbitrarily many chunks (including one byte per
  call) yields the frame only once all its bytes have arrived, and yields
  it exactly once.
- **Multi-frame per call:** if one `feed()` call's data completes more
  than one frame (e.g. a client sent two pipelined requests back to
  back), all completed frames are returned, in wire order.
- **Round-trip:** for every representable frame `f`, `Parser().feed(encode(f)) == [f]`.
- **Determinism:** `encode` has no side effects and is a pure function of
  its argument.

## Failure semantics

- Malformed input (bad type sigil, non-numeric length/value where a
  number is required, a length that doesn't match the delivered payload
  boundary, an `Array`/`BulkString` declared with a negative length other
  than the `-1` nil sentinel, trailing bytes that don't form a valid
  frame) → `feed()` raises `ProtocolError` (defined in `codec.py`).
- `ProtocolError` is **connection-fatal**: the contract makes no promise
  about parser state after it's raised, and no promise about how much of
  the malformed input was consumed. The caller (server) must not call
  `feed()` again on the same `Parser` instance after catching one — it
  must tear down the connection. (This is a C1 promise about the codec's
  own state, not an instruction to the server implementer, who owns that
  teardown behavior under C2/server scope.)
- `encode()` never raises for any well-formed `Frame` instance of the
  five types above (including a `SimpleString`/`Error` whose `.value` the
  caller has itself kept free of `\r`/`\n` — the codec does not validate
  that on encode; see Intentionally unspecified).

## Intentionally unspecified

- `encode()` does **not** validate that `SimpleString`/`Error` `.value`
  is free of `\r`/`\n` — a caller that puts protocol-breaking bytes into
  a simple string gets a corrupt wire frame, not an exception. Consumers
  (server, engine) must not construct `SimpleString`/`Error` from
  untrusted bytes; boundary tests do not assert `encode()` rejects this.
- Exact `ProtocolError` message text — assert only that it's raised, not
  its `str()`.
- How much of a malformed frame's bytes `feed()` consumes from its
  internal buffer before raising — a caller may not resume the same
  parser and must not depend on any particular partial-consumption
  behavior.
- RESP3 types (out of spec scope — non-goal).
- Inline commands (`PING\r\n` with no `*`/`$` framing) — open question in
  the spec; not part of this contract unless promoted.

## Versioning / compatibility policy

v1. Adding a new method or frame type is additive/non-breaking. Changing
`feed`/`encode` signatures, renaming/removing a Frame type, or changing
nil/binary-safety semantics is breaking — codec (provider) fixes all call
sites (server, engine) on a breaking change.

## Boundary tests

`targets/resp/tests/test_codec_boundary.py` — pre-written by the lead at
decomposition; consumer-driven (encodes what server needs from codec).
Run against the codec provider: `python3 -m unittest
targets.resp.tests.test_codec_boundary -v` from the repo root, or
`python3 -m unittest discover -s targets/resp/tests`.

## Interpretation register

None yet. File against this contract in `contracts/` per protocol
(RUNBOOK §5b/STATES §Interpretation); clarifications promote into this
document immediately.
