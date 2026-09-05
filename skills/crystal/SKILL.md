---
name: orgs-crystal
description: Speculative merge-checking across concurrent worker branches. At standup cadence, attempt each open branch-pair merge in a scratch worktree and run the boundary tests; a textual conflict or a clean-merge-with-red-tests is a semantic conflict — record it and deliver it to the lead. Detects integration breakage early, before late integration becomes the failure mode.
---

# orgs-crystal — speculative merge check

Firewalled teams fail at integration: two branches each pass their own tests,
merge cleanly, and are semantically incompatible. Crystal finds that early by
*speculatively* merging concurrent branches and running the boundary tests
against the result — behavioral, not just textual, conflict detection (after
Brun & Notkin's Crystal, ESEC/FSE 2011). Prior art on agent branches does only
textual/tree-diff detection; the build-and-test oracle is the unclaimed part.

Tool: `tools/crystal/crystal-check.sh` (git-archive plain-files sandbox; never
touches the real repo or pushes).

## The check (at the cadence the sprint root sets)

For each open branch pair:
1. Attempt the merge in a **scratch worktree, never pushed**.
2. **Textual conflict** → a conflict.
3. **Clean merge, red boundary tests** → a *semantic* conflict (the dangerous
   kind: both branches were individually green).

## On a conflict

- Record a **`crystal-conflict`** event via `orgs-ledger` with the exact
  revisions, and **deliver it to the lead** (and notify both owners) — a
  conflict that only lands in a log is inert; it must reach the org that can
  act on it. The delivery channel is the sprint root's wiring.
- **Resolution ownership is semantic:** contract change → provider migrates
  callers; invalid assumption → consumer fixes; disputed → record
  `semantic-deadlock`, the lead adjudicates.
- Whoever merges second cleans up by default. Open conflict debt is reported
  to the lead on every check so it ages loudly rather than silently.

## Requires parallel branches

Crystal has nothing to do in a variety that builds sequentially (one branch at
a time) — it earns its place only when work fans out in parallel. Pair it with
per-worker worktree isolation.
