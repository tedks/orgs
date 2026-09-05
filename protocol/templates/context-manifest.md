# Context manifest: <work package id>

What was packed into an agent's context at claim time. A packing list, not
a firewall — the agent may read anything; this records what it was *given*,
for reproducibility and the cold-start audit.

- **Pack type:** implementer | reviewer | auditor | takeover | continuation
  - *implementer* packs additionally include **the work package itself**;
  - *takeover* / *continuation* (journey) packs include the prior agent's
    **branch, diff, PR thread, status entry**, and a transcript excerpt where
    the reasoning matters — the journey travels via committed artifacts;
  - *reviewer* packs include the **diff under review, the acceptance
    criteria, and the consumed contracts** — never the context of the agent
    whose work is under review (decontamination). A review *seat* may still
    be warm-chained across rounds so it carries its **own** prior-round
    review context (RUNBOOK §2);
  - *auditor* packs are the clean checkout alone.
- **Doctrine:** DOCTRINE.md @ <sha> (prompt block verbatim in role prompt)
- **Design doc:** <path> @ <sha> (whole document — intent must travel)
- **Contracts:** <each consumed contract + version>
- **Owned scope source:** <paths>
- **Lessons packed:** <LESSONS.md entries relevant to this package, by
  heading — the decomposition step selects these>
- **Prior context:** none (fresh) | inherited via self-fork from <session id>
  (same-tier continuation / huddle attendance only). A **higher-tier
  takeover** does NOT inherit context — it is a fresh pack carrying the prior
  owner's branch, diff, PR thread, status entry (+ transcript excerpt if the
  reasoning matters); record those source ids here.
- **Excluded by default:** neighbor-team source (readable on demand;
  packed lean per context-hygiene doctrine)
