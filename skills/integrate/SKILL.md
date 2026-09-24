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

### Delegated landing

The integration owner may be the worker that made the change, when landing is a scripted act rather than a judgment: merge the trunk into a detached copy of the change; run the gates on that union, only those the union changes; push the union to the branch; merge with a normal merge; verify the trunk's tree equals the union; only then close the tracker items and post the record. The script stops at its first failure and says why, and a lock keeps two landings from racing. Smokes that need artifacts a scratch checkout lacks run in the worker's own checkout on the union head and are recorded by note. The coordinator's standing authority covers the merge; the script is the integration owner's judgment written down.

## Handoff

Once every non-abandoned package is INTEGRATED and the trunk is green against
the full boundary-test suite, the sprint is ready for `orgs-retro`.

Integration verifies against the **boundary tests** the org owns. It does
**not** run the external graded conformance exam — grading belongs to the
evaluator, outside every variety, so the thing being scored never touches its
own score.
