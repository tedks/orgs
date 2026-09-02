# Runbook (v0 — manual)

Everything here is performed by hand in v0. Automate a step only after a
sprint shows humans (or agents) repeatedly getting it wrong. Speculative
merge checks and retrospectives are explicitly manual in v0.

## 1. Spec authoring (CEO ↔ CTO)

Instantiate `docs/spec-template.md`. The load-bearing sections are the
firewalled entities, their contracts (one `protocol/templates/contract.md`
each), and the boundary diagram (mermaid: entities as nodes, contracts as
labeled edges). Goals/non-goals are the schwerpunkt — write them so a leaf
worker can adjudicate a deviation against them. Spec merges only after a
council round on it is CLEAN.

## 2. Sizing (hats, not headcount)

Count boundaries; assign hats; instantiate `org/ROSTER.md` from
`protocol/templates/roster.md` — hats, standup heartbeat, blocked threshold, and who
monitors the triggers all get named there. Every artifact type in STATES.md
whose triggering condition fires gets produced, regardless of how few agents
wear the hats — a fired trigger without its artifact is a protocol defect;
an unfired trigger (a sprint with no escalations) owes nothing.

"Fresh context" for the review hat means it never inherits the *context of
the agent whose work it reviews* (decontamination — the reviewer must not
carry the implementer's rationalizations). It does **not** forbid a review
seat from carrying its **own** prior-round review context across rounds:
warm-chaining a seat so it remembers what it already flagged is the intended
practice (LESSONS.md 2026-09-01) and is what lets "the seat that found an
issue re-verify its fix." Fresh vs. the reviewed work; warm vs. its own prior
rounds.

## 3. Decomposition (lead, player-coach)

1. Build the tracer bullet first: a thin executable vertical slice across
   the real boundaries. If the contracts don't compose, fix the spec now —
   file interpretation requests or an amendment before fanning out.
2. Cut work packages from the template. Every package: intent naming the
   spec section, acceptance criteria in prose, boundary tests by path,
   budget, stop conditions, escalation destination.
3. Run the necessity challenge on the decomposition itself (fresh-context
   seat, cheap model): PROCEED / SIMPLIFY / STOP_AND_ESCALATE, in the
   ledger. One decomposition-level PROCEED satisfies the work-package gate
   (STATES: DRAFT→READY) for every package cut from it; re-run only when an
   implementer proposes substantial unplanned machinery not in the
   decomposition.
4. Pack contexts per the manifest template: doctrine prompt block, whole
   design doc, consumed contracts, owned scope, selected lessons. Lean by
   default; the worker reads more on demand.

## 4. Execution (worker loop)

Work in your worktree, on your branch, inside your owned scope. Maintain
your status entry (`status/<package-id>.md` per `protocol/templates/status.md`:
current task, last commit, budget burned, blocked-on — updated on claim,
every push, block/unblock, and each budget quarter).
Log deviations as they happen. Commit granularly. Hit a stop condition →
reorient once, then escalate. Contract silent → file the interpretation
request and keep working on what's unblocked (or fork-huddle if blocked).

## 5. Standup

Convened on triggers (budget tripwire, stop condition, Crystal conflict,
blocked past the roster's threshold, interface change) or on the roster's
heartbeat; each accountable lead monitors the triggers for their entity's
packages (defaults in `protocol/templates/roster.md`). The chair (usually the
convener) facilitates; the adjudicator per ownership decides. Inputs: status
entries, event ledger since last standup, git log, open PRs — compact state,
never transcripts. Outputs, committed as ledger events: decisions,
reassignments, deviation adjudications, redirects, contract-change
proposals. Decisions are proposals until reconciled against head
(`based_on`/`applied_at`); invalidated speculative work is preserved and
dispositioned by its owner, never auto-discarded.

## 5b. Huddle

Convened by any agent (per STATES §Huddle) when intent-vs-instruction is
unclear or a gated deviation needs a prior decision. The convener writes an
**issue key** — a short stable slug for the question (e.g. `retry-idempotency`
on boundary C2), reused across revisions so two agents at different shas
converge on one huddle rather than opening duplicates. Attendees are forks
carrying their own context (they may request escalation, never convene a
further huddle). The chair facilitates; the adjudicator per ownership decides
(the lowest lead with authority over the thing in conflict; one rung up if
that lead's own call is what's disputed; a collapsed-hat adjudicator takes a
fresh context). The decision is a proposal until its accountable owner
reconciles it against head (`based_on`/`applied_at`); invalidated speculative
work is preserved and dispositioned, never auto-discarded. Committed as
`huddle-convened` / `huddle-decided` / `huddle-reconciled` events.

## 6. Review ladder (per PR)

**Freeze the target, quiesce the tree (correct by construction).** A round is
launched against a **named, immutable revision** — a committed sha, normally
a pushed PR head — never the live working tree, and only once the lead has
committed and stopped editing (a quiescent tree). The dispatch prompt names
that revision and every seat reviews exactly it. This is preferred over
having each verdict *report* which state it saw: a frozen target makes "the
seat cleared X" unambiguous by construction, so a live edit can never turn
independent convergence into apparent sequence (LESSONS 2026-09-02). If a
seat cannot be pinned to the named revision (e.g. it reads a working tree),
that round does not count — re-run it against the frozen sha.

1. Implementer self-review against acceptance criteria.
2. Council review at the implementer's tier — use the `council-review`
   skill; provider diversity is the point; findings into the ledger.
3. One-rung-up review by the accountable lead (fresh context: diff + spec +
   criteria + contracts — never the implementer's transcript).
4. One feedback round to the implementer before any takeover. A takeover
   spawns a higher-tier agent packed with the implementer's branch, diff,
   PR thread and status entry (and a transcript excerpt where the reasoning
   matters) — the journey travels via those committed artifacts, because in
   this harness a fork cannot change tier (see the binding). Record a
   `takeover` event.
5. Repeat on the fix delta to fixpoint (CLEAN). Merge only CLEAN + CI green
   (once CI exists). Watch the takeover-rate and churn health signals.

## 7. Speculative merge check (manual v0 Crystal)

At standup cadence: attempt merges of each open branch pair (scratch
worktree, never pushed); on textual conflict or a semantic failure (clean
merge, red boundary tests), record a `crystal-conflict` ledger event with
exact revisions and notify both owners. Ownership of resolution is semantic — contract change:
provider migrates callers; invalid assumption: consumer fixes; disputed:
record semantic-deadlock, lead adjudicates. Whoever merges second cleans up
by default; conflict debt visible at standup so it ages loudly.

## 8. Integration & sprint closure

The **integration owner** merges ACCEPTED packages promptly (integrate
continuously; late integration is the firewalled-teams failure mode) and
keeps main green against all boundary tests. The **lead** then runs the
retro (per the sprint table in STATES.md): adjudicate remaining deviations;
file lessons (provenance, scope, reconsider-when); record the meta:product
ratio; fold expiring interpretations; propose amendments where the
boundary's deviation/docs-bug/interpretation counts say the contract is
wrong.

**meta:product, v0 operational definition:** coordination tokens = the sum
across huddle, standup, review-seat, necessity-challenge, and
ledger-maintenance agent invocations; product tokens = the sum across
implementer work-package invocations (takeovers count as product). Each
invocation's reported token usage is bucketed at the time it runs; where a
harness hides token counts, substitute the word count of the invocation's
output and say so. Both buckets and the ratio are recorded in the
`state-change`→CLOSED ledger entry — where the Sprint table requires
"meta:product recorded" as evidence — (a `lesson` event may cite it); the
number is a soft tripwire, compared sprint-over-sprint, never a gate. (Under
the bench, the same two buckets also populate the run manifest's `cost`
fields; a normal sprint needs only the ledger entry.)

At milestones, run the cold-start audit: fresh agent, different harness,
clean checkout — it must state current state and next authorized action
from committed artifacts alone. Its confusion is a protocol defect; fix the
artifacts, not the auditor.
