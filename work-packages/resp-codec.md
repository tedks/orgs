# Work package: resp-codec

- **State:** READY (necessity challenge PROCEED, `events/resp-tracer/lead.md` lead:5)
- **Owner (role):** L3 implementer · **Model:** sonnet (state-machine
  parsing correctness matters more than the mechanical dispatch work in
  command-engine — see roster/necessity-challenge rationale)
- **Base revision:** d34d638
- **Intent:** Serves spec §"Firewalled Entities" entity 1 (resp-codec) and
  the M2 fan-out milestone. This boundary protects every other entity from
  ever touching raw RESP wire bytes — server and command-engine must be
  able to trust `feed`/`encode` completely. Deviate toward *that* isolation
  if instruction and intent ever pull apart.
- **Instruction:** Hardn `targets/resp/codec.py` from its tracer-bullet
  stub (PING-only, one-frame-per-call, no error handling) to the full C1
  contract: `contracts/C1-resp-codec.md`. Implement `ProtocolError`,
  `SimpleString`, `Error`, `Integer`, `BulkString`, `Array`, a real
  incremental `Parser.feed(bytes) -> list[Frame]`, and a complete
  `encode(Frame) -> bytes`. Keep the same class/function names and module
  location — you are hardening in place, not redesigning the shape.
- **Non-goals:** RESP3 types; inline commands (`PING\r\n` with no `*`/`$`
  framing — that's an open spec question, out of this package); validating
  that `SimpleString`/`Error` values are free of `\r`/`\n` on encode (see
  contract's Intentionally Unspecified); anything about sockets, commands,
  or the key-value store (that's command-engine's and server's scope).
- **Owned scope:** `targets/resp/codec.py` only. Read anything else in the
  repo; do not edit `targets/resp/engine.py`, `targets/resp/server.py`, or
  any file under `targets/resp/tests/` (the boundary tests are frozen —
  if one looks wrong, file a docs-bug/interpretation request against
  `contracts/C1-resp-codec.md` instead of editing the test).
- **Dependencies:** none (resp-codec has no dependencies on the other two
  entities — it is the base of the boundary diagram).
- **Acceptance criteria:**
  - `python3 -m unittest targets.resp.tests.test_codec_boundary -v` (or
    `python3 -m unittest discover -s targets/resp/tests -p
    'test_codec_boundary.py'`) passes 100%, unmodified.
  - `feed()` is genuinely incremental: a frame fed one byte at a time
    still parses correctly (this is asserted by the boundary tests —
    don't special-case around the test, make the parser actually
    buffer).
  - Malformed input raises `ProtocolError`; the parser is not expected to
    be reusable afterward.
  - `BulkString` values round-trip arbitrary bytes, including embedded
    NUL and CRLF.
  - You may add your own additional unit tests in
    `targets/resp/tests/test_codec_impl.py` (a new file — this is your
    own scope) for anything the boundary tests don't cover, but the
    graded acceptance gate is the boundary tests above passing unedited.
- **Boundary tests:** `targets/resp/tests/test_codec_boundary.py` (frozen;
  do not edit).
- **Budget:** ~150K tokens / one discrete turn. Soft — exceeding it is
  normal if logged in your status file; going silent about it is the
  tripwire.
- **Stop conditions:** the same boundary test failing three distinct ways
  → stop, reorient once (re-read the contract's exact wire-format table),
  then escalate to the lead if still stuck rather than attempt a fourth
  variant.
- **Escalation destination:** L6 lead (this session) — `SendMessage` to
  the lead, or leave a `BLOCKED` status entry; this is a discrete-turn
  worker, so in practice: finish what you can, leave status/deviation
  entries stating exactly what's blocking you, and end your turn rather
  than looping.
- **Deviation envelope:** default (doctrine) — loose. Log any bend in one
  line per DOCTRINE.md; you are not asking permission.
- **Expected artifact:** commit(s) on branch `pilot-resp` implementing
  `targets/resp/codec.py`; `status/resp-codec.md` updated per
  `protocol/templates/status.md`; any deviations logged to
  `events/resp-tracer/worker-codec.md` (your own shard).
