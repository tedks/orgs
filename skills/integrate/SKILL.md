---
name: orgs-integrate
description: The integration owner merges ACCEPTED work packages promptly and keeps the trunk green against all boundary tests. Integrate continuously — late integration is the failure mode of firewalled teams, where individually-green branches turn out incompatible only at the end.
---

# orgs-integrate — continuous integration of accepted work

Firewalled teams fail when integration is deferred: each branch passed its own
tests in isolation and the incompatibilities surface all at once at the end.
The defense is to integrate **continuously**, not to firewall and hope.

## The job

- Merge each package **as it reaches ACCEPTED** (CLEAN review ladder + green
  boundary tests), promptly — do not batch merges to the end.
- Keep the trunk **green against all boundary tests**, not just the merged
  package's own. A merge that reddens another entity's boundary test is a
  semantic conflict — hand it back through `orgs-crystal`'s ownership rules
  (provider migrates / consumer fixes / lead adjudicates a deadlock).
- Record each integration via `orgs-ledger` (a `state-change` into INTEGRATED).

## Handoff

Once every non-abandoned package is INTEGRATED and the trunk is green against
the full boundary-test suite, the sprint is ready for `orgs-retro`. Run the
target's conformance exam at integration so correctness is a fact on the trunk,
not a claim.
