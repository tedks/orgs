# Context manifest: <work package id>

What was packed into the worker's context at claim time. A packing list, not
a firewall — the worker may read anything; this records what it was *given*,
for reproducibility and the cold-start audit.

- **Doctrine:** DOCTRINE.md @ <sha> (prompt block verbatim in role prompt)
- **Design doc:** <path> @ <sha> (whole document — intent must travel)
- **Contracts:** <each consumed contract + version>
- **Owned scope source:** <paths>
- **Lessons packed:** <LESSONS.md entries relevant to this package, by
  heading — the decomposition step selects these>
- **Prior context:** none (fresh) | inherited from <session/fork id>
  (continuation/takeover — journeys inherit; judgments get fresh packs)
- **Excluded by default:** neighbor-team source (readable on demand;
  packed lean per context-hygiene doctrine)
