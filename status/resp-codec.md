# Status entry: resp-codec

- **State:** ACCEPTABLE-PENDING-REVIEW (implementation complete,
  self-reviewed; awaiting lead review per RUNBOOK §6 review ladder — not
  ACCEPTED until that evidence exists)
- **Current task:** Done for this turn. `targets/resp/codec.py` hardened
  to the full C1 contract; self-review complete; deviations logged.
  Ending turn per discrete-turn worker instructions.
- **Last commit:** 7794bd7 · "resp-codec: harden codec.py to full C1
  contract"
- **Budget burned:** ~55K tokens (reading spec/contract/work-package/
  stub/frozen tests/templates, implementing, running tests three ways,
  writing supplementary tests, deviation/status writeup) of the ~150K
  soft budget. One discrete turn, not exceeded.
- **Blocked on:** none. Not a STOP-CONDITION case — the 2 frozen-test
  failures share one root cause (a single `7`-for-`6` length typo in the
  fixture, hit twice: once in the encode-direction test, once in the
  feed-direction test), not three genuinely distinct failure modes of
  the same test. See deviations below and events/resp-tracer/
  worker-codec.md:1 for the full analysis; recommend the lead apply a
  two-character fix (`$7` → `$6`) to
  targets/resp/tests/test_codec_boundary.py at both call sites when
  amending the frozen suite (I did not edit it — out of owned scope).
- **Deviations logged:** worker-codec:1 (docs-bug: frozen boundary test
  has an incorrect hardcoded BulkString length for a binary-safe
  payload), worker-codec:2 (owned-scope tension between the work
  package's "don't edit files under targets/resp/tests/" line and its
  own acceptance criteria's explicit test_codec_impl.py carve-out;
  followed the more specific instruction), worker-codec:3 (closing note:
  no further deviations). All in
  events/resp-tracer/worker-codec.md.
- **Updated:** 2026-09-02T01:00:00Z

## Acceptance-criteria self-review (work-packages/resp-codec.md)

1. **`test_codec_boundary.py` passes 100%, unmodified.** — **Not fully
   met, and not fixable from within owned scope.** 30/32 pass. The 2
   failures (`TestEncode.test_bulk_string_binary_safe`,
   `TestFeedBasic.test_feed_bulk_string_binary_safe`) are caused by a bug
   in the frozen fixture, not the implementation: both hardcode a `$7`
   RESP length prefix for `payload = b"a\r\nb\x00c"`, which is verified
   to be 6 bytes (`len(payload) == 6`), not 7. C1's wire-format table
   requires the declared length to be the exact byte count of `.value`
   ("Length is a byte count, not a text length"), and lists a mismatched
   length as ProtocolError-worthy — so a codec that accepted `$7` for a
   6-byte payload would be non-conformant, not merely test-passing. I
   verified this three ways: (a) the sibling non-binary test uses the
   same-length `"foobar"` payload with a correct `$6`; (b)
   `TestRoundTrip.test_round_trip_each_type`, which exercises the
   identical embedded-NUL/CRLF payload and passes, is self-consistent
   regardless of the absolute length used, so it doesn't catch this;
   (c) `test_codec_impl.py::TestKnownBoundaryTestBug` shows the codec
   round-trips this exact payload correctly at its true length (6), and
   that the frozen test's literal 12-byte wire stream is genuinely
   incomplete under a correct length-prefixed parser (never yields a
   frame — consistent with what a real Redis client would also see).
   Filed as `worker-codec:1` (docs-bug) rather than edited (frozen,
   out of owned scope) or silently special-cased (would require
   abandoning length-prefixed parsing, breaking binary-safety for this
   very payload).
2. **`feed()` is genuinely incremental (one byte at a time).** — **Met.**
   `Parser` buffers internally (`self._buf`) and re-attempts a full parse
   from the buffer start on every `feed()` call, propagating a
   NeedMoreData-only-internal exception when a prefix is incomplete.
   Verified by the frozen `test_split_one_byte_at_a_time` (passes) and my
   own `test_nested_array_split_byte_at_a_time` (nested arrays,
   byte-at-a-time, passes) — this isn't special-cased against the test;
   every `feed()` call runs the same code path regardless of chunk size.
3. **Malformed input raises `ProtocolError`; parser not expected to be
   reusable afterward.** — **Met.** All 5 frozen `TestMalformed` cases
   pass (bad sigil, non-numeric length, non-numeric integer, negative
   array length other than -1, negative bulk-string length other than
   -1). Added 2 more of my own (wrong terminator bytes after a
   length-matched payload; malformed frame nested inside an Array
   propagates the error) — both pass. No reuse-after-error guarantee is
   implemented or claimed, per C1's Intentionally Unspecified section.
4. **`BulkString` values round-trip arbitrary bytes, including embedded
   NUL and CRLF.** — **Met** for the parser/encoder itself (the frozen
   `TestRoundTrip.test_round_trip_each_type` case with the embedded
   NUL/CRLF payload passes; my own test confirms the same payload at its
   correct declared length in both encode and feed directions). The two
   *frozen-test-literal* failures above are a fixture-length bug, not a
   round-trip or binary-safety defect in the codec.
5. **May add own tests in `test_codec_impl.py`.** — **Done.** 9
   additional tests (nested/mixed-type arrays incl. byte-at-a-time,
   2 extra malformed-input cases, encode() purity, and 2 tests isolating
   the frozen-fixture bug from this implementation), all passing.

## Test output

```
$ python3 -m unittest targets.resp.tests.test_codec_boundary -v   # frozen, from repo root (pilot-resp/)
...
Ran 32 tests in 0.001s
FAILED (failures=2)   # see self-review item 1 / worker-codec:1

$ python3 -m unittest discover -s targets/resp/tests -p 'test_codec_impl.py' -v   # own scope
...
Ran 9 tests in 0.000s
OK
```

Full `discover -s targets/resp/tests` (no `-p` filter) also picks up
`test_engine_boundary.py`, which is command-engine's package (not mine,
still unhardened at the time of this run) — its failures are out of
scope for this status entry.
