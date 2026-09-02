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

Count boundaries; assign hats. Every artifact in STATES.md gets produced
regardless of how few agents wear the hats. The review hat always gets a
fresh context, even on a one-agent project.

## 3. Decomposition (lead, player-coach)

1. Build the tracer bullet first: a thin executable vertical slice across
   the real boundaries. If the contracts don't compose, fix the spec now —
   file interpretation requests or an amendment before fanning out.
2. Cut work packages from the template. Every package: intent naming the
   spec section, acceptance criteria in prose, boundary tests by path,
   budget, stop conditions, escalation destination.
3. Run the necessity challenge on the decomposition itself (fresh-context
   seat, cheap model): PROCEED / SIMPLIFY / STOP_AND_ESCALATE, in the
   ledger. Re-run it whenever an implementer proposes substantial unplanned
   machinery.
4. Pack contexts per the manifest template: doctrine prompt block, whole
   design doc, consumed contracts, owned scope, selected lessons. Lean by
   default; the worker reads more on demand.

## 4. Execution (worker loop)

Work in your worktree, on your branch, inside your owned scope. Maintain
your status entry (current task, last commit, budget burned, blocked-on).
Log deviations as they happen. Commit granularly. Hit a stop condition →
reorient once, then escalate. Contract silent → file the interpretation
request and keep working on what's unblocked (or fork-huddle if blocked).

## 5. Standup

Convened on triggers (budget tripwire, stop condition, Crystal conflict,
blocked > threshold, interface change) or heartbeat. The chair (usually the
convener) facilitates; the adjudicator per ownership decides. Inputs: status
entries, event ledger since last standup, git log, open PRs — compact state,
never transcripts. Outputs, committed as ledger events: decisions,
reassignments, deviation adjudications, redirects, contract-change
proposals. Decisions are proposals until reconciled against head
(`based_on`/`applied_at`); invalidated speculative work is preserved and
dispositioned by its owner, never auto-discarded.

## 6. Review ladder (per PR)

1. Implementer self-review against acceptance criteria.
2. Council review at the implementer's tier — use the `council-review`
   skill; provider diversity is the point; findings into the ledger.
3. One-rung-up review by the accountable lead (fresh context: diff + spec +
   criteria + contracts — never the implementer's transcript).
4. One feedback round to the implementer before any takeover; takeover
   inherits the implementer's context (journeys inherit, judgments don't).
5. Repeat on the fix delta to fixpoint (CLEAN). Merge only CLEAN + CI green
   (once CI exists). Watch the takeover-rate and churn health signals.

## 7. Speculative merge check (manual v0 Crystal)

At standup cadence: attempt merges of each open branch pair (scratch
worktree, never pushed); on textual conflict or a semantic failure (clean
merge, red boundary tests), record a ledger event with exact revisions and
notify both owners. Ownership of resolution is semantic — contract change:
provider migrates callers; invalid assumption: consumer fixes; disputed:
record semantic-deadlock, lead adjudicates. Whoever merges second cleans up
by default; conflict debt visible at standup so it ages loudly.

## 8. Integration & sprint closure

Integration owner merges ACCEPTED packages promptly (integrate continuously;
late integration is the firewalled-teams failure mode), keeps main green
against all boundary tests, then runs the retro: adjudicate remaining
deviations; file lessons (provenance, scope, reconsider-when); record
meta:product ratio; fold expiring interpretations; propose amendments where
the boundary's deviation/docs-bug/interpretation counts say the contract is
wrong. At milestones, run the cold-start audit: fresh agent, different
harness, clean checkout — it must state current state and next authorized
action from committed artifacts alone. Its confusion is a protocol defect;
fix the artifacts, not the auditor.
