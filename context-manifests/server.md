# Context manifest: server

- **Pack type:** implementer
- **Doctrine:** DOCTRINE.md @ a428ac0 (prompt block packed verbatim atop
  the worker's role prompt)
- **Design doc:** `docs/specs/2026-09-02-resp-tracer.md` @ 3f70fdc (whole
  document)
- **Contracts:** `contracts/C1-resp-codec.md` v1 (ACCEPTED, real
  implementation at `targets/resp/codec.py`), `contracts/C2-command-engine.md`
  v1 (ACCEPTED, real implementation at `targets/resp/engine.py`) — both
  ordinary use of published, accepted contracts; not gated.
- **Owned scope source:** `targets/resp/server.py` (tracer-bullet stub,
  commit 4281655, to be hardened in place)
- **Lessons packed:** none directly implementer-facing (see prior
  manifests); this package's own review found the command-engine
  package's real defect (nil-command-name crash) via a case the frozen
  tests didn't probe — worth the server implementer knowing that
  boundary tests are necessary but not sufficient evidence, in case they
  want to think about analogous edge cases in their own integration
  tests (their scope has no frozen boundary tests at all — see work
  package's Acceptance criteria).
- **Prior context:** none (fresh)
- **Excluded by default:** none — server consumes both other entities'
  full public surface by design (it's the integration point).
