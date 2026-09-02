# Context manifest: command-engine

- **Pack type:** implementer
- **Doctrine:** DOCTRINE.md @ a428ac0 (prompt block packed verbatim atop
  the worker's role prompt)
- **Design doc:** `docs/specs/2026-09-02-resp-tracer.md` @ d92cef6 (whole
  document)
- **Contracts:** `contracts/C2-command-engine.md` v1 (own contract),
  `contracts/C1-resp-codec.md` v1 (Dependencies — types only:
  SimpleString/Error/Integer/BulkString/Array)
- **Owned scope source:** `targets/resp/engine.py` (tracer-bullet stub,
  commit 4281655, to be hardened in place)
- **Lessons packed:** none — see resp-codec manifest; same rationale.
- **Prior context:** none (fresh)
- **Excluded by default:** `targets/resp/server.py` — readable on demand,
  not packed. `targets/resp/codec.py`'s *internals* (Parser/encode) are
  out of scope by contract (types only); the file itself is packed
  implicitly since the Frame classes live there.
