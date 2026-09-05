---
name: orgs-decompose
description: The lead (player-coach) turns a spec into executable work — a tracer bullet across the real boundaries, work packages with intent and boundary tests, and a necessity challenge — then calls orgs-pack to assemble each worker's context. Produces contracts, work-packages, and packed contexts.
---

# orgs-decompose — spec to executable work

The lead is a player-coach: build the risky seam yourself first, then cut the
rest into packages workers can own. Decomposition is where a good spec becomes
a runnable sprint — or where a bad boundary reveals itself in time to fix
cheaply.

Templates: `protocol/templates/work-package.md`, `protocol/templates/contract.md`.

## The four moves

1. **Tracer bullet first.** Build a thin executable vertical slice across the
   *real* boundaries — a single path that touches every entity. If the
   contracts don't compose, you've found a spec bug: file an interpretation
   request or an amendment **now**, before fanning out. The tracer is the
   cheapest place to learn the boundaries are wrong.
2. **Cut work packages.** Each package names: **intent** (which spec section /
   entity it serves), acceptance criteria in prose, **boundary tests by path**
   (pre-written, first-class artifacts the review evaluates), budget, stop
   conditions, and an escalation destination. One package = one owned scope.
3. **Necessity challenge** on the decomposition itself — a fresh-context,
   cheap-model seat returns **PROCEED / SIMPLIFY / STOP_AND_ESCALATE** into the
   ledger. One decomposition-level PROCEED satisfies the work-package gate
   (STATES: DRAFT→READY) for *every* package cut from it; re-run only when an
   implementer later proposes substantial unplanned machinery not in the
   decomposition. This is where "what fails if we just don't?" gets asked of
   the plan.
4. **Pack contexts** — call `orgs-pack` for each package: doctrine block, whole
   design doc, consumed contracts, owned scope, selected lessons. Lean by
   default.

Record each transition via `orgs-ledger`. Hand the packed packages to
`orgs-implement`. (What else watches the fan-out is the sprint root's wiring,
not this skill's concern.)

## On contracts

Contracts are **authored in `orgs-spec`** — one per boundary, councilled with
the spec before it merges. Decomposition does not originate them; it
**refines** them into concrete boundary tests and instantiates the
work-package references to them. If decomposition finds a contract missing or
wrong, that is a spec bug: file the interpretation request or amendment.
