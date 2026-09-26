---
name: orgs-review
description: The accountable lead's one-rung-up review to fixpoint. Freeze the target at a named immutable revision, review with fresh context (never the implementer's transcript), give one feedback round before any takeover, and repeat on the fix delta until CLEAN. Council CLEAN + this review CLEAN = ACCEPTED; merge only CLEAN + applicable local gates on the exact head.
---

# orgs-review — the lead's one-rung-up review

Review refines work upward. The ladder per package is: the implementer's
**self-review** (inside `orgs-implement`) → **`orgs-council`** (cross-provider)
→ **this skill**, the accountable lead's one-rung-up review. Council CLEAN plus
this review CLEAN moves the package to **ACCEPTED** (`STATES.md`, event
`lead-review`). There is one lead rung, not a hierarchy of them — the council
supplies the diversity that catches what a same-provider rung cannot.

## Freeze the target first (correct by construction)

A round is launched against a **named, immutable revision** — a committed sha,
normally a pushed PR head — **never the live working tree**, and only once the
author has committed and stopped editing (a **quiescent tree**). The dispatch
prompt names that revision; the reviewer reviews exactly it.

This is preferred over having a verdict *report* which state it saw: a frozen
target makes "the seat cleared X" unambiguous **by construction**, so a live
edit can never turn independent convergence into apparent sequence. If the
review cannot be pinned to the named revision (e.g. it read a working tree),
**that round does not count** — re-run it against the frozen sha.

## The review

1. **Fresh context**, assembled by `orgs-pack` as a judgment pack: diff + spec
   + acceptance criteria + contracts + the boundary tests. **Never the
   implementer's transcript** (decontamination — you must not carry their
   rationalizations). The review evaluates the tests as a first-class artifact,
   not just the code.
2. Findings by severity into the ledger as `review-finding` events; the
   `review-findings.md` file is a projection of them.
3. **One feedback round** to the implementer before any takeover. A takeover
   spawns a **higher-tier** agent packed with the implementer's branch, diff,
   PR thread, status entry, and a transcript excerpt where the reasoning
   matters (a fork cannot change tier — see the binding). Record a `takeover`
   event.
4. **Repeat on the fix delta to fixpoint.** Re-review only the delta since the
   last-reviewed sha — that is where fix-introduced regressions hide. A round
   is CLEAN when it produces no new actionable finding.
5. Acceptance requires **CLEAN + applicable local gates on the exact head**.
   Match each acceptance sentence to source/head-specific evidence and note
   untested cases. A changed head invalidates affected evidence; rerun affected
   gates and review the delta. An authorized exception must name its issuer,
   criterion, scope and expiry; never promote it to blanket readiness.

When authority requires an executive audit, send the final acceptance map,
pushed head, gate commands/results, council record, exceptions and unresolved
items before merge. The executive selectively spot-checks and resolves holes;
this does not replace this skill's fresh-context whole-diff lead review.

## Rules that cost us to learn

- **A silent seat is not a CLEAN seat.** Wait for a *received* CLEAN; never
  read idle or dropped output as consent.
- **A verdict must name the state it reviewed** (the frozen sha).
- Watch the takeover-rate and churn as health signals; escalating churn on a
  fix delta means the fix is fighting the design.
