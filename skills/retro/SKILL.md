---
name: orgs-retro
description: The lead closes the sprint — adjudicate remaining deviations, file lessons, record the meta:product ratio, fold expiring interpretations, and propose amendments where a boundary's deviation/docs-bug/interpretation counts say the contract is wrong. At milestones, run the cold-start audit. Produces LESSONS entries and the CLOSED ledger entry.
---

# orgs-retro — close the sprint

The retro is where the sprint turns experience into durable improvement: what
bent, what the numbers say, and where the contracts were wrong.

## The closing acts

1. **Adjudicate remaining deviations** in the ledger — each bent rule is either
   justified-and-kept or reverted.
2. **File lessons** (`LESSONS.md`): each with **provenance** (what happened),
   **scope** (where it applies), and **reconsider-when** (what would make it
   wrong). Link related lessons.
3. **Record the meta:product ratio** (below) in the `state-change`→CLOSED
   ledger entry — where the Sprint table requires "meta:product recorded."
4. **Fold expiring interpretations** back into the spec or let them lapse.
5. **Propose amendments** where a boundary's accumulated deviation / docs-bug /
   interpretation counts say the contract itself is wrong.

## meta:product (v0 operational definition)

- **Coordination tokens** = the sum across huddle, standup, review-seat,
  necessity-challenge, and ledger-maintenance invocations.
- **Product tokens** = the sum across implementer work-package invocations
  (takeovers count as product).
- Bucket each invocation's reported usage when it runs; where a harness hides
  token counts, substitute the output's word count and say so.
- **Known v0 gap** (pilot retro): there is **no bucket for the lead's own
  decomposition / contract-authoring / tracer work** — often the single
  largest slice. Record it explicitly as an unbucketed line rather than hiding
  it; a cost claim that omits it understates the hierarchy's true cost.
- The ratio is a **soft tripwire**, compared sprint-over-sprint, never a gate.

## Cold-start audit (at milestones)

A fresh agent, different harness, clean checkout must state the current state
and next authorized action **from committed artifacts alone**. Its confusion is
a protocol defect — fix the artifacts, not the auditor. This is the real test
of whether the ledger and status entries are load-bearing.
