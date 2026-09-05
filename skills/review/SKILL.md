---
name: orgs-review
description: One-rung-up review to fixpoint, parameterized by rung (lead, then CTO). Freeze the target at a named immutable revision, review with fresh context (never the implementer's transcript), give one feedback round before any takeover, and repeat on the fix delta until CLEAN. Merge only CLEAN + CI green.
---

# orgs-review — the review ladder

Review refines work upward. This skill is the **one-rung-up** step, run once at
the **lead** tier and again at the **CTO** tier (same act, different rung). The
cross-provider round is its own skill, `orgs-council`; it sits between the
implementer and the lead.

## Freeze the target first (correct by construction)

A round is launched against a **named, immutable revision** — a committed sha,
normally a pushed PR head — **never the live working tree**, and only once the
author has committed and stopped editing (a **quiescent tree**). The dispatch
prompt names that revision; every seat reviews exactly it.

This is preferred over having each verdict *report* which state it saw: a
frozen target makes "the seat cleared X" unambiguous **by construction**, so a
live edit can never turn independent convergence into apparent sequence. If a
seat cannot be pinned to the named revision (e.g. it read a working tree),
**that round does not count** — re-run it against the frozen sha.

## The ladder (per PR)

1. **Implementer self-review** against the acceptance criteria.
2. **Council** at the implementer's tier — `orgs-council`; provider diversity
   is the point.
3. **One-rung-up review** by the accountable lead — **fresh context**: diff +
   spec + criteria + contracts, assembled by `orgs-pack`. **Never the
   implementer's transcript** (decontamination).
4. **One feedback round** to the implementer before any takeover. A takeover
   spawns a **higher-tier** agent packed with the implementer's branch, diff,
   PR thread, and status entry (a fork cannot change tier — see the binding).
   Record a `takeover` event.
5. **Repeat on the fix delta to fixpoint.** Re-review only the delta since the
   last-reviewed sha — that is where fix-introduced regressions hide. A round
   is CLEAN when it produces no new actionable finding. Merge only **CLEAN +
   CI green.**

## Rules that cost us to learn

- **A silent seat is not a CLEAN seat.** Wait for a *received* CLEAN; never
  read idle or dropped output as consent.
- **A verdict must name the state it reviewed** (the frozen sha) — see above.
- Watch the takeover-rate and churn as health signals; escalating churn on a
  fix delta means the fix is fighting the design.
