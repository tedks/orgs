# Work package: wp-codec

- **State:** READY
- **Owner (role):** implementer, entity `resp-codec` · **Model:** haiku
  (tiering ON this run)
- **Base revision:** 33d8591
- **Intent:** serve spec goal "correct RESP2 reply types" and the binary-safe
  value requirement — resp-codec is the bytes<->frames boundary (C1) that
  every other command and the exam's binary-safety/pipelining assertions
  depend on. When an instruction below and this intent conflict, serve
  correct, total RESP2 framing over the letter of any one bullet.
- **Instruction:** bring `targets/resp/codec.py` (already a working tracer
  for the PING path — full grammar, all five frame types) to full contract
  C1 compliance and cover it with the boundary tests already skeletoned in
  `targets/resp/tests/test_codec_contract.py`.
- **Non-goals:** RESP3; inline (non-array) command parsing — the spec
  leaves this an open question, decided "not required" unless you discover
  `redis-cli` needs it for a *goal* command's happy path, in which case
  handle it and log why (deviation, not a huddle — it's additive, not a
  contract break).
- **Owned scope:** `targets/resp/codec.py`,
  `targets/resp/tests/test_codec_contract.py`. Nothing else — if you find
  yourself needing to change `engine.py` or `server.py`, that's a contract
  question (file an interpretation against C1), not a scope widening.
- **Dependencies:** none (resp-codec has no socket, no store, no command
  knowledge — stdlib only).
- **Acceptance criteria** (contract: `contracts/C1-resp-codec.md`):
  - Round-trip: `encode(frame)` fed into a fresh `RespCodec().feed()`
    reproduces an equal `Frame`, for all five frame types incl. null bulk
    (`BulkString(None)`) and null array (`Array(None)`).
  - Binary safety: a bulk string payload containing `\r`, `\n`, and `\x00`
    round-trips exactly (the frozen exam asserts this via a hex-dump
    comparison — see `bench/conformance/resp_conformance.sh`'s "binary-safe
    SET/GET" check for the exact byte pattern it drives through the whole
    server, which is what your codec-level test should isolate and prove
    at this boundary).
  - Incremental feed: splitting one frame's wire bytes across two or more
    `feed()` calls at arbitrary byte boundaries (incl. mid-CRLF, mid-length
    header, mid-payload) yields the frame only once it's complete; **two or
    more complete frames delivered in one `feed()` call each appear in the
    returned list, in order** (this is the pipelining foundation the server
    entity relies on — don't regress it).
  - Malformed input (bad type byte, non-integer length/count field,
    negative length other than the `-1` null sentinel, a bulk payload not
    terminated by CRLF) raises `ProtocolError`; incomplete-but-otherwise-valid
    input never raises.
  - `test_codec_contract.py`'s `TodoTests` class (currently `@skip`ped
    stubs) is filled in and passing — un-skip each as you cover it. Add
    more cases if the stubs don't capture something you find.
- **Boundary tests:** `targets/resp/tests/test_codec_contract.py` (yours to
  extend — this *is* the deliverable test suite for C1).
- **Budget:** soft target ~one focused session (rough guide: well under 40
  tool calls / edit-test cycles). Exceeding it is fine if logged in your
  status entry; three distinct failing shapes on the same test is a stop
  condition (below), not a budget one.
- **Stop conditions:** the same test failing three distinct ways → reorient
  once (re-read C1 §Failure semantics and §Behavioral invariants), then
  escalate to the lead in your final report rather than continuing to
  iterate blind.
- **Escalation destination:** the lead (report back in your final message —
  this is a single-lead sprint, there is no other seat to escalate to).
- **Deviation envelope:** default (doctrine) — log deviations in one line in
  your final report; huddle first only if you'd cross a contract boundary
  (change what C1 or C2 publish) or can't name your rollback.
- **Expected artifact:** commits on branch
  `bench-run/r4-orgs-no-crystal-2026-09-03T1148Z-wp-codec`, `codec.py` and
  `test_codec_contract.py` updated, all tests in the file green
  (`python3 -m unittest tests.test_codec_contract -v` from
  `targets/resp/`), reported back to the lead for merge.
