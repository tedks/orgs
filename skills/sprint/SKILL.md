---
name: orgs-sprint
description: The root runbook for a virtual-engineering-org sprint — how the org skills compose into building a spec end to end, and the ONE place cross-skill wiring lives. Invoke to run a sprint; it dispatches the other orgs skills in order. A named variety is this runbook composing a subset.
---

# orgs-sprint — the runbook

A sprint turns a **spec** into shipped, reviewed software by composing the
orgs skills. This file is the *graph*: which skills run, in what order, with
what handoffs. Each skill owns its own procedure and is **unconditional about
its own act**; this file owns how they fit together and does all the
**cross-skill wiring**. It replaces the old inline `protocol/RUNBOOK.md` — the
procedures moved into the skills; the connections stayed here.

Doctrine (`doctrine/DOCTRINE.md`) is ambient: its prompt block is packed into
every role prompt by `orgs-pack`, and its precedence rules govern every
deviation. Assumed everywhere below.

## The graph

```
[spec] ─▶ [decompose] ─▶ ( [implement]×N ∥ [standup] ∥ [crystal] )
       ─▶ [council] ─▶ [review] ─▶ [integrate] ─▶ [retro]
                             ▲
     [huddle] — the escalation floor, always available via doctrine
   · every step appends to [ledger]   · every role prompt is built by [pack]
```

## The sequence

1. **[spec]** — CEO+CTO author the contracts-first design doc, including one
   contract per boundary. Merges only after a council round on the spec is
   CLEAN. → produces the spec + its contracts.
2. **size** — count boundaries, assign hats (not headcount), instantiate
   `org/ROSTER.md`. Every artifact type whose trigger fires gets produced no
   matter how few agents wear the hats; **an unfired trigger (a sprint with no
   escalations) owes nothing.** Sizing is short and lives here.
3. **[decompose]** — the lead builds the tracer bullet, refines the spec's
   contracts into boundary tests, cuts work packages, runs the necessity
   challenge, and calls **[pack]** for each worker. → produces work packages,
   boundary tests, packed contexts.
4. **[implement]×N** — workers build their packages in parallel, each in its
   own worktree/branch, inside firewalled scope, and **self-review** against
   the acceptance criteria before handing off. → produces commits + status.
5. **[standup]** and **[crystal]** run *alongside* the fan-out (see Wiring).
6. **[council]** — cross-provider review to fixpoint on each frozen PR head.
7. **[review]** — the accountable lead's one-rung-up review to fixpoint,
   fresh context. Council CLEAN + lead-review CLEAN → **ACCEPTED**.
8. **[integrate]** — the integration owner merges each package *as it is
   ACCEPTED* (continuously, not batched at the end) and keeps the trunk green
   against all boundary tests. Drawn once in the graph; runs throughout.
9. **[retro]** — the lead closes the sprint: adjudicate deviations, file
   lessons, record meta:product, fold expiring interpretations, propose
   amendments. Milestones get a cold-start audit.

## Wiring (the cross-skill connections — they live HERE, not in the skills)

The leaf skills never say "if X is present." The composer says how they
connect. In the **full** composition:

- **implement ↔ standup:** workers run their dev-loop commands through
  `tools/standup/guard.sh <agent-id> -- <cmd>` so redirects/halts are forced
  into view. (This instruction is issued by this root — `implement` itself is
  unconditional.)
- **crystal → lead:** a `crystal-conflict` is delivered to the lead over the
  standup bus.
- **standup triggers:** budget tripwire, stop condition, `crystal-conflict`,
  blocked past threshold, interface change, or the roster heartbeat.
- **deviations → adjudicator:** `LOGGED → ADJUDICATED` by the next standup's
  adjudicator.
- **review → integrate:** each ACCEPTED package flows to integrate immediately.

A variety that omits a skill **also omits that skill's wiring lines**, and
re-routes anything left dangling (e.g. with no `standup`, crystal delivers
straight to the lead and the **retro's lead adjudicates deviations**; with no
`decompose`, `implement` runs in its whole-spec mode). Write each variety as
its own short root file: the skills it composes, in order, plus its wiring.
Never a flag on this file.

## Composition and varieties

The full graph above is the **canonical runbook**. A named **variety** is this
runbook composing a **subset** — that is the whole mechanism for an ablation.
A variety that lacks a skill does not invoke it and is not installed with it.
Because imperative wiring lives only here, removing a skill removes its
mechanism from every prompt. Two honest boundaries on that claim:

- **Descriptive catalogs are not leaks.** `ledger` lists every event kind,
  `standup` lists every trigger, `retro` sums whichever coordination skills
  ran. A variety simply never emits what it doesn't run.
- **Huddle is the floor, not a step.** The doctrine block (packed into every
  role) tells agents when to huddle, so `huddle` is always *available*; it is
  the escalation gate, not an ablatable mechanism.

Bench varieties (`docs/bench/`): drop `crystal`; drop `crystal`+`standup`;
drop `decompose` (one implementer builds the whole spec; review ladder intact).

## Precedence and escalation (from doctrine)

- Serve the spec's intent (goals/non-goals — the schwerpunkt). When the letter
  of a task defeats its purpose, deviate to serve intent and log the bend in
  one line. Justified is justified; review reads the whole change.
- **Huddle first** only at the reversibility gate: an unnameable rollback, a
  change across a contract boundary (publish a new version / break an existing
  one / depend on an unpublished surface — ordinary use of published contracts
  is never gated), or work beyond owned scope. **Huddle voluntarily** when you
  can't tell what intent requires — fork and keep working while you ask.
- A thrice-failed approach is a signal, not a dare — reorient, then escalate.
- Only the CEO loosens a doctrine default; a lead cannot self-authorize
  skipping a skill the variety includes.

## On automation

The v0 runbook said: automate a step only after a sprint shows it repeatedly
done wrong by hand. The pilot showed exactly that for two steps — manual
Crystal was never run and manual standups never convened — so `crystal` and
`standup` now wrap executables (`tools/`). Everything else remains a
by-hand act.

## Isolation (when run as an experiment)

Each variety runs in its own isolated config (no shared memory/session/
messaging), its own protocol copy, its own repo/worktree pinned to the shared
target sha, with run-unique agent ids. Nothing shared ⇒ nothing to police.
`docs/bench/CONTAMINATION-VECTORS.md` is the checklist. Grading, audit, and
measurement live in the **evaluator, outside every variety** — never a skill
an agent has, so the graded thing cannot write its own grade.
