# Event ledger shard: worker-codec (resp-tracer sprint)

## worker-codec:1 · 2026-09-02T01:00:00Z · docs-bug
- actor: worker-codec (Claude Code, Sonnet 5)
- based_on: 6bc450d
- refs: targets/resp/tests/test_codec_boundary.py (TestEncode
  .test_bulk_string_binary_safe, TestFeedBasic
  .test_feed_bulk_string_binary_safe), contracts/C1-resp-codec.md
- what bent: implemented `encode`/`feed` per C1's own wire-format table
  (BulkString length is the exact byte count of `.value`) rather than
  matching two frozen tests that hardcode a `$7` length prefix for
  `payload = b"a\r\nb\x00c"`, which is 6 bytes, not 7
  (`len(b"a\r\nb\x00c") == 6`, verified). Result: 30/32 boundary tests
  pass; these 2 fail against a correct implementation.
- why: C1 states "Length is a byte count, not a text length," and lists
  a length that doesn't match the delivered payload boundary as
  ProtocolError-worthy — a lenient codec that papered over the mismatch
  would violate that invariant and would also have to abandon
  length-prefixed (vs. \r\n-scanning) parsing, which is what makes the
  same payload's embedded \r\n binary-safe in the first place. The
  sibling non-binary test (`foobar`, len 6, prefix `$6`) and
  `TestRoundTrip.test_round_trip_each_type` (same payload, passes,
  self-consistent) corroborate: this is a `7`-for-`6` typo in the frozen
  fixture, not an interpretation ambiguity. Did not edit the frozen file
  (owned scope). Added
  `targets/resp/tests/test_codec_impl.py::TestKnownBoundaryTestBug` to
  isolate the bug to the two literal `7`s rather than the
  implementation — it round-trips the identical payload at its true
  length (6) and separately shows the frozen test's literal 12-byte
  stream is genuinely incomplete (never yields a frame) under a
  contract-correct parser.
- rollback: read — n/a. No repo state changed by this finding; the fix
  (recommended: `$7` → `$6` at both call sites) belongs to the lead as
  the frozen file's owner.

## worker-codec:2 · 2026-09-02T01:00:00Z · deviation
- actor: worker-codec (Claude Code, Sonnet 5)
- based_on: 6bc450d
- refs: work-packages/resp-codec.md (Owned scope; Acceptance criteria)
- what bent: created `targets/resp/tests/test_codec_impl.py`, a file
  under `targets/resp/tests/`, which the work package's "Owned scope"
  line names among paths not to edit ("do not edit ... any file under
  `targets/resp/tests/`").
- why: the same work package's Acceptance criteria section explicitly
  names this exact file and calls it "your own scope" ("You may add
  your own additional unit tests in
  `targets/resp/tests/test_codec_impl.py` ... this is your own scope").
  Read the Owned-scope line as aimed at the frozen boundary tests and
  the other packages' files (its own parenthetical cites "the boundary
  tests are frozen"), not as silently revoking the explicit, more
  specific carve-out two sections later; following the letter of the
  broader line over the specific one would make the acceptance
  criteria's own instruction unsatisfiable.
- rollback: delete `targets/resp/tests/test_codec_impl.py` — it is not
  part of the graded gate (`test_codec_boundary.py`) and contains no
  logic the codec depends on.

## worker-codec:3 · 2026-09-02T01:00:00Z · deviation
- actor: worker-codec (Claude Code, Sonnet 5)
- based_on: 6bc450d
- refs: none (no deviations beyond worker-codec:1, worker-codec:2 above)
- no further deviations this package. `targets/resp/codec.py` was
  otherwise hardened per contracts/C1-resp-codec.md and
  work-packages/resp-codec.md without other departures: same class/
  function names and module location kept, no sockets/commands/store
  touched, no other owned-scope files edited.
