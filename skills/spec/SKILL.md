---
name: orgs-spec
description: CEO and CTO author the contracts-first design doc for a sprint. The load-bearing content is the firewalled entities, their contracts, and the boundary diagram. Produces docs/specs/<name>.md; merges only after a clean council round on the spec itself.
---

# orgs-spec — author the design doc

The spec is the sprint's constitution. Its most important content is not the
features — it is the **boundaries**: which entities exist, what each one
publishes, and how they connect. Everything downstream (decomposition,
firewalled context, review) is derived from these.

Template: `docs/spec-template.md`. Outputs: `docs/specs/<name>.md` **and one
`contracts/<boundary>.md` per boundary** (from `protocol/templates/contract.md`)
— the contracts are authored here, as part of the spec, and councilled with
it. Decomposition later refines them into boundary tests; it does not
originate them.

## The load-bearing sections

1. **Firewalled entities** — the components that will be built behind
   boundaries. Each is one team's owned scope.
2. **Contracts** — one `protocol/templates/contract.md` per boundary. The
   published surface an entity's consumers may depend on, and nothing more.
   This is the firewall made concrete.
3. **Boundary diagram** — a mermaid graph: entities as nodes, contracts as
   labeled edges. If you cannot draw it, the boundaries are not yet clear.
4. **Goals / non-goals** — the **schwerpunkt**. Write them so a leaf worker
   can adjudicate a deviation against them on its own: concrete enough that
   "does this serve intent?" has an answer without a meeting.
5. **Milestones and stop conditions.**

## Gate

The spec merges only after a **council round on the spec itself is CLEAN**
(use `orgs-council`). A boundary error caught here is cheap; caught after
fan-out it is an amendment. Record the spec's CLEAN council in `orgs-ledger`.
A spec is **substantive** — it is never the "trivial docs-only" change that
`orgs-council` lets skip a round; this gate is unconditional.

## Changes after merge

Cheap **interpretations** (clarifications promote to the spec immediately;
temporary exceptions expire) vs. rare **amendments** (a real boundary change).
An implementer files an interpretation request against a silent contract
rather than guessing; `orgs-retro` folds the accumulated evidence into
amendments where a boundary's counts say the contract is wrong.
