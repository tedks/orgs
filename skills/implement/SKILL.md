---
name: orgs-implement
description: A worker builds one work package inside its firewalled scope — its own worktree and branch, granular commits, a maintained status entry, deviations logged as they happen, a self-review before handoff. In a variety with no decomposition, runs in whole-spec mode (the whole target as one implicit package). Escalate on a stop condition; file an interpretation request against a silent contract rather than guessing.
---

# orgs-implement — the worker loop

You own one work package. You may read anything, but you **depend only on
published contracts** — if you had to find it in a neighbor's source, file a
docs-bug rather than depending on it. Build inside your scope, on your branch,
and leave a trail others can pick up.

Your pack (from `orgs-pack`) opens with the doctrine block; it governs. Any
tooling you must run your commands through is stated in your pack by the
sprint's root — this skill does not assume any.

## The loop

- Work in **your own worktree, on your own branch, inside your owned scope.**
  Parallel workers must not share a working tree (it races).
- **Maintain your status entry** (`status/<package-id>.md` via `orgs-ledger`):
  current task, last commit, budget burned, blocked-on — updated on claim,
  every push, block/unblock, and each budget quarter.
- **Commit granularly.** Put your **work-package id** (from the work-package
  template) in each commit message so the sprint can tell your commits apart
  from everyone else's.
- **Log deviations as they happen** — one line each, via `orgs-ledger`.
- **Tests must be able to fail:** mutation-check any test that pins a fix
  (demonstrate it can go red) before you claim the fix works.

## Self-review, then hand off

Before handing off, **self-review against the acceptance criteria** — this is
the first rung of the review ladder and it is yours. Then push a committed,
quiescent head; the review ladder (`orgs-council`, then the lead's
`orgs-review`) runs against that frozen sha.

## When you hit friction

- **Stop condition** (thrice-failed approach, budget tripwire): reorient
  **once**, then escalate to your package's destination. A repeated failure is
  a signal, not a dare.
- **Silent contract:** file the interpretation request and keep working on
  whatever is unblocked; fork-huddle (`orgs-huddle`) only if it blocks you.
- **The reversibility gate** (unnameable rollback / boundary-crossing change /
  beyond owned scope): huddle **first**. Otherwise deviate and log.

## Whole-spec mode (varieties with no decomposition)

When the sprint has no `orgs-decompose`, there is no cut package — you build the
**whole spec as one implicit package**: owned scope is the whole target,
acceptance criteria are the spec's goals plus the boundary tests it names, and
you keep a single status entry for it. You may run the spec's tests to check
yourself; the **official grade is the evaluator's, never yours.** Everything else in this skill
applies unchanged. State your assumptions before you build; the spec is your
only contract.
