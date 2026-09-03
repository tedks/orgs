# Contract: resp-codec v1

- **Owner:** lead (accountable lead — resp-codec) · **Consumers (ack list):**
  server (worker `server`)
- **Inputs / outputs:**
  - A `Frame` is one of: `SimpleString(str)`, `Error(str)`, `Integer(int)`,
    `BulkString(bytes | None)` (`None` = RESP2 null bulk string, `$-1\r\n`),
    `Array(list[Frame] | None)` (`None` = RESP2 null array, `*-1\r\n`; not
    exercised by this sprint's goals but part of the data model so the
    codec is total over RESP2 framing).
  - `feed(data: bytes) -> list[Frame]` — incremental parse. Accepts any
    number of bytes (may be a partial frame, may contain several complete
    frames, may span prior partial state). Returns the list of frames that
    became *complete* as a result of this call, in the order their
    terminating byte arrived. Bytes that do not yet complete a frame are
    retained internally and combined with the next `feed` call. Calling
    `feed(b"")` is legal and returns `[]`.
  - `encode(frame: Frame) -> bytes` — serialize one frame to its RESP2
    wire form. Pure function, no internal state.
- **Behavioral invariants:**
  - One codec instance holds parse state for exactly one connection's
    inbound byte stream. Multiple `feed` calls against the same instance
    behave identically to one `feed` call with the concatenated bytes
    (incremental parsing is observably transparent).
  - `encode(frame)` output, fed byte-for-byte into a fresh codec's `feed`,
    reproduces an equal `Frame` (round-trip).
  - Binary safety: bulk string payloads may contain any byte value
    including `\r`, `\n`, and `\x00`; the codec must not treat them as
    delimiters inside a bulk string's declared-length payload.
- **Failure semantics:** malformed input (a type byte that isn't one of
  `+-:$*`, a non-integer where an integer is required, a declared bulk
  length that is negative and not exactly `-1`, or bytes that don't resolve
  to a valid frame by any continuation) raises `ProtocolError` from `feed`.
  `ProtocolError` is connection-fatal: the caller (server) must close the
  connection and must not call `feed` again on that instance. `feed` never
  raises for merely-incomplete input — that is the normal partial-frame
  case, not an error.
- **Intentionally unspecified:** which frame types the command layer
  actually emits/consumes (that's C2); whether `feed` batches multiple
  complete frames into one list or the caller must loop (it batches — see
  invariant above, this line exists so a consumer doesn't assume one frame
  per call); inline-command (non-RESP-array) parsing is out of scope unless
  amended.
- **Versioning / compatibility policy:** breaking change = any change to
  the `Frame` variants, `feed`/`encode` signatures, or the round-trip /
  binary-safety invariants above. Provider (resp-codec) fixes all call
  sites on a breaking change. Additive frame variants or new pure helper
  functions are non-breaking.
- **Boundary tests:** `targets/resp/tests/test_codec_contract.py` (consumer
  `server`'s boundary tests against this contract — round-trip, partial-feed
  reassembly, binary-safe CRLF/NUL payload, malformed input raises
  `ProtocolError`).
- **Interpretation register:** none yet. File against this document.
