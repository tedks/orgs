---
name: orgs-sprint
description: The root runbook for a virtual-engineering-org sprint — how the org skills compose into building a spec end to end. Invoke to run a sprint; it dispatches the other orgs skills in order. A named variety is this runbook with a skill removed.
---

# orgs-sprint — the runbook

A sprint turns a **spec** into shipped, reviewed software by composing the
orgs skills. This file is the *graph*: which skills run, in what order, with
what handoffs. Each skill owns its own procedure; this owns how they fit
together. It replaces the old inline `protocol/RUNBOOK.md` — the procedures
moved into the skills; the connections stayed here.

Doctrine (`doctrine/DOCTRINE.md`) is ambient: its prompt block is packed into
every role prompt by `orgs-pack`, and its precedence rules govern every
deviation. Assumed everywhere below.

## The graph

```
[spec] ─▶ [decompose] ─▶ ( [implement]×N ∥ [standup] ∥ [crystal] )
       ─▶ [council] ─▶ [review:lead] ─▶ [review:cto] ─▶ [integrate] ─▶ [retro]
                                   ▲
              [huddle] fires on demand at the reversibility gate
   · every step appends to [ledger]   · every role prompt is built by [pack]
```

## The sequence

1. **[spec]** — CEO+CTO author the contracts-first design doc. Merges only
   after a clean council round on the spec itself. → produces the spec.
2. **size** — count boundaries, assign hats (not headcount), instantiate
   `org/ROSTER.md`. Every artifact type whose trigger fires gets produced no
   matter how few agents wear the hats. (Sizing is short; it lives here in the
   root rather than as its own skill.)
3. **[decompose]** — the lead builds the tracer bullet, cuts work packages,
   runs the necessity challenge, and calls **[pack]** to assemble each
   worker's context. → produces contracts, work packages, packed contexts.
4. **[implement]×N** — workers build their packages in parallel, each in its
   own worktree/branch, inside firewalled scope. If **[standup]** is in this
   variety, their dev-loop commands run through its guard so they observe
   redirects. → produces commits + status entries.
5. **[standup]** *(if present)* — observes the org on cadence/trigger and
   injects redirects or halts. **[crystal]** *(if present)* — speculative
   merge-checks the parallel branches and reports conflicts to the lead.
6. **[council]** — cross-provider review to fixpoint on each frozen PR head.
   **[review:lead]** then **[review:cto]** — one-rung-up review to fixpoint,
   fresh context. (Which of these run is the variety; see below.)
7. **[integrate]** — the integration owner merges ACCEPTED packages promptly
   and keeps the trunk green against all boundary tests.
8. **[retro]** — the lead closes the sprint: adjudicate deviations, file
   lessons, record meta:product, fold expiring interpretations, propose
   amendments.

**[huddle]** is not a step: any agent convenes it on demand when
intent-vs-instruction is unclear or a gated deviation needs a prior decision
(see the reversibility gate in doctrine).

## Composition and varieties

The full graph above is the **canonical runbook**. A named **variety** is this
runbook with one or more skills removed — that is the whole mechanism for an
ablation. A variety that lacks a skill does not invoke it and is not installed
with it, so the mechanism cannot leak into any prompt. Examples used by the
bench (`docs/bench/`): drop `crystal`; drop `crystal`+`standup`; drop
`decompose` (one implementer builds the whole spec, review ladder intact).
Write each variety as a short root file that names the skills it composes and
in what order — never as a flag on this one.

## Precedence and escalation (from doctrine)

- Serve the spec's intent (goals/non-goals — the schwerpunkt). When the letter
  of a task defeats its purpose, deviate to serve intent and log the bend in
  one line. Justified is justified; review reads the whole change.
- **Huddle first** only at the reversibility gate: an unnameable rollback, a
  change across a contract boundary (publish a new version / break an existing
  one / depend on an unpublished surface — ordinary use of published contracts
  is never gated), or work beyond owned scope. Otherwise deviate and log.
- A thrice-failed approach is a signal, not a dare — reorient, then escalate.
- Only the CEO loosens a doctrine default; a lead cannot self-authorize
  skipping a skill the variety includes.

## Isolation (when run as an experiment)

Each variety runs in its own isolated config (no shared memory/session/
messaging), its own protocol copy, its own repo/worktree pinned to the shared
target sha, with run-unique agent ids. Nothing shared ⇒ nothing to police.
`docs/bench/CONTAMINATION-VECTORS.md` is the checklist. Grading, audit, and
measurement live in the **evaluator, outside every variety** — never a skill
an agent has, so the graded thing cannot write its own grade.
