# Context manifest: resp-codec

- **Pack type:** implementer
- **Doctrine:** DOCTRINE.md @ a428ac0 (prompt block packed verbatim atop
  the worker's role prompt)
- **Design doc:** `docs/specs/2026-09-02-resp-tracer.md` @ d92cef6 (whole
  document)
- **Contracts:** `contracts/C1-resp-codec.md` v1 (own contract — the one
  being implemented)
- **Owned scope source:** `targets/resp/codec.py` (tracer-bullet stub,
  commit 4281655, to be hardened in place)
- **Lessons packed:** none — all four LESSONS.md entries (as of d92cef6)
  concern review/council process (mutation-checking pinned tests, warm-
  seat identity, verdict-state pinning, binding-executable review), not
  implementer scope. Not excluded on purpose, just none apply.
- **Prior context:** none (fresh)
- **Excluded by default:** `targets/resp/engine.py`,
  `targets/resp/server.py` — readable on demand, not packed (neighbor
  scope, context-hygiene doctrine).
