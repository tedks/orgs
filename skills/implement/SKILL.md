---
name: orgs-implement
description: A worker builds one work package inside its firewalled scope — its own worktree and branch, granular commits, a maintained status entry, deviations logged as they happen. Escalate on a stop condition; file an interpretation request against a silent contract rather than guessing. Produces commits + a status entry.
---

# orgs-implement — the worker loop

You own one work package. You may read anything, but you **depend only on
published contracts** — if you had to find it in a neighbor's source, file a
docs-bug rather than depending on it. Build inside your scope, on your branch,
and leave a trail others can pick up.

Your pack (from `orgs-pack`) opens with the doctrine block; it governs.

## The loop

- Work in **your own worktree, on your own branch, inside your owned scope.**
  Parallel workers must not share a working tree (it races).
- **Maintain your status entry** (`status/<package-id>.md` via `orgs-ledger`):
  current task, last commit, budget burned, blocked-on — updated on claim,
  every push, block/unblock, and each budget quarter.
- **Commit granularly.** Each commit carries the tracking id from the lead's
  table so the sprint (and its standup) can tell your commits apart.
- **Log deviations as they happen** — one line each, via `orgs-ledger`.
- **Tests must be able to fail:** mutation-check any test that pins a fix
  (demonstrate it can go red) before you claim the fix works.

## When you hit friction

- **Stop condition** (thrice-failed approach, budget tripwire): reorient
  **once**, then escalate to your package's destination. A repeated failure is
  a signal, not a dare.
- **Silent contract:** file the interpretation request and keep working on
  whatever is unblocked; fork-huddle (`orgs-huddle`) only if it blocks you.
- **The reversibility gate** (unnameable rollback / boundary-crossing change /
  beyond owned scope): huddle **first**. Otherwise deviate and log.

## If the variety includes standup

Run your dev-loop commands through the standup guard
(`tools/standup/guard.sh <your-id> -- <cmd>`) so a redirect or halt from the
org is forced into your view — you can't rabbit-hole past a steering message
you never observed.

Your finished package enters the review ladder: `orgs-council`, then
`orgs-review` at the lead and CTO tiers.
