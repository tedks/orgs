# Contract: command-engine v1

- **Owner:** lead (accountable lead — command-engine) · **Consumers (ack
  list):** server (worker `server`)
- **Inputs / outputs:**
  - `execute(command: list[bytes]) -> Frame` — `command` is a non-empty list
    of raw argument bytes already decoded from an `Array(BulkString...)`
    frame by the caller (the engine never sees `Frame` objects, only
    `list[bytes]`; it has no dependency on the codec's types). The command
    name (`command[0]`) is matched case-insensitively per Redis convention
    (`ping`, `PING`, `PiNg` all match). Returns exactly one `Frame` (from
    the same `Frame` data model published by C1) — the reply for that
    command.
  - `Frame` here means the same variants as C1 (`SimpleString`, `Error`,
    `Integer`, `BulkString`, `Array`); the engine module imports C1's Frame
    type rather than redefining it, so the two contracts share one data
    model.
- **Behavioral invariants (per-command semantics):**
  - `PING` (0 args): reply `SimpleString("PONG")`. `PING <msg>` (1 arg):
    reply `BulkString(msg)`. More than 1 arg: arity error.
  - `ECHO <msg>` (exactly 1 arg): reply `BulkString(msg)`. Wrong arity: arity
    error.
  - `GET <key>` (exactly 1 arg): reply `BulkString(value)` if the key holds
    a string value; `BulkString(None)` (nil) if the key does not exist.
    Wrong arity: arity error.
  - `SET <key> <value>` (exactly 2 args): store `value` (bytes, may contain
    any byte incl. NUL/CRLF) under `key`, overwriting any prior value;
    reply `SimpleString("OK")`. Wrong arity: arity error. (Options like
    `EX`/`NX` are a non-goal per spec; extra args beyond key+value are an
    arity error, not silently ignored.)
  - `DEL <key>` (exactly 1 arg): remove `key` if present; reply
    `Integer(1)` if it existed, `Integer(0)` if it did not. Wrong arity:
    arity error.
  - `INCR <key>` (exactly 1 arg): parse the stored value (or `0` if the key
    is absent) as a base-10 signed integer, add 1, store the result as its
    decimal string, reply `Integer(new_value)`. If the stored value is not
    parseable as an integer, reply an `Error` frame whose text contains
    "not an integer" (case-insensitive substring match — the exam's grader
    greps for `not an integer|error` case-insensitively). Wrong arity:
    arity error.
  - Unknown command: reply an `Error` frame (text containing "unknown
    command" or similar — no exam assertion pins the exact text, only the
    known-command error texts above are pinned).
  - Arity errors: reply an `Error` frame whose text contains "wrong number
    of arguments" (the exam greps case-insensitively for `wrong number|
    error`).
  - State visibility: `execute` calls against one engine instance are
    strictly sequential (the spec's concurrency model is one connection at
    a time; the engine is not required to be thread-safe) and
    read-your-writes within that instance — a `SET` is visible to every
    later `GET`/`INCR`/`DEL` on the same instance. One engine instance is
    the whole server's key-value store (not per-connection) — that's what
    makes state persist across separate connections within one server
    process. This sprint has no goal requiring cross-process persistence.
- **Failure semantics:** `execute` never raises for a well-formed
  `list[bytes]` command (including empty list — treat as a no-op arity
  error, since it has no command name to dispatch on); all command-level
  failures (arity, non-integer INCR, unknown command) are `Error` *frames*,
  not exceptions. `execute` may assume `command` is non-empty is **false**:
  the caller (server) must not assume the engine validates non-emptiness
  itself beyond returning an `Error` frame — this line exists so the
  distinction doesn't get lost: malformed *framing* is a codec-level
  `ProtocolError` (C1); an empty or semantically-invalid *command* is
  always an `Error` frame from the engine, never an exception.
- **Intentionally unspecified:** key/value size limits; eviction; any
  command not in the goals list (expiry, persistence, transactions,
  pub/sub — explicit non-goals) — the engine may reply `Error` (unknown
  command) for anything not listed above.
- **Versioning / compatibility policy:** breaking change = altering a
  pinned reply value/type for an existing command, or the `execute`
  signature. Adding a new command is non-breaking. Provider fixes all call
  sites on a breaking change.
- **Boundary tests:** `targets/resp/tests/test_engine_contract.py`
  (consumer `server`'s boundary tests: each command's happy path, arity
  errors, non-integer INCR, missing-key GET, cross-call state visibility).
- **Interpretation register:** none yet. File against this document.
