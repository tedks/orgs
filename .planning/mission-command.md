# Carry mission command through evidence, delivery and retirement

This living ExecPlan follows `.planning/PLANS.md`. It describes a documentation-only change in the `chaos-coordination` worktree; no executable transport changes belong here.

## Purpose / Big Picture

A lead can delegate bounded work, verify what actually passed, deliver control messages without submitting human input, and retire a lane without losing its resumable state. Readers can follow the existing sprint skills and state tables without adopting project-specific model names or a new orchestration platform.

## Progress

- [x] (2026-09-25) Read the assignment, PR #19, current doctrine/skills/state tables and source-session practices; claimed ditz `mission-command-quiet-delivery`.
- [x] (2026-09-25) Published early draft PR #20 with the plan.
- [x] (2026-09-25) Updated doctrine, existing skills/templates/state tables and binding caveats.
- [ ] Validate links, whitespace and scenario walkthroughs; review frozen head with native Terra and foreign agy.
- [ ] Push evidence, sync ditz and send final audit packet to CTO before merge.

## Surprises & Discoveries

PR #19 already added standing authority, lane-owned councils and silence on healthy standups. At initial inspection the roster said 30 minutes and review required hypothetical CI; both are now corrected. The remote exists despite the stale AGENTS note. Lane-10's measured worker costs contradict a universal claim that coordinator re-reads dominate cost. Transport exit success left the first peer message in the composer; receipt inspection identified it and permitted only an exact-payload Enter retry.

## Decision Log

Decision: extend existing protocol artifacts in one coherent PR. Rationale: authority, evidence and quiet lifecycle are one control-flow contract; transport code remains P's separate dotfiles PR. Date/author: 2026-09-25, Q.

Decision: retain full fresh-context lead review; executive audit is additional when delegated, not a replacement. Rationale: selective spot-checks cannot satisfy a promised whole-diff review. Date/author: 2026-09-25, Q.

## Outcomes & Retrospective

Implementation is pushed in draft PR #20. The first Terra review found three protocol gaps (same-SHA approved lead evidence, EMPTY outcome schema, packed delivery procedure); all are being corrected and delta-reviewed. Agy's mission-policy objection to the explicitly Claude-specific binding was rejected with rationale; its initial-state wording nit is fixed. Merge requires the CTO's final evidence audit. Keep the issue in progress until landing; follow-ups must be filed rather than silently dropped.

## Context and Orientation

`doctrine/DOCTRINE.md` supplies ambient principles and a packed prompt block. `skills/sprint/SKILL.md` owns cross-skill wiring; leaf skills own procedures. `protocol/STATES.md` owns transitions, while templates instantiate work packages, roster and ledger evidence. `bindings/claude-code.md` names harness primitives and must defer concrete sender behavior to the installed dotfiles helper. A lane is a coordinator accountable for a delegated work package, possibly with tactical workers.

## Plan of Work

Extend standing authority with explicit stop conditions and exact-head executive audit; make bounded workers and task-boundary review configurable. Put typing protection, truthful receipts, controller quiescence and safe resumable retirement in portable doctrine, with sprint wiring and ledger/state evidence where appropriate. Update work-package and roster templates with authority, acceptance evidence, worker budget, direct resource coordination and cadence. Reconcile review/integration gates and the quota exception wording without copying dated quota rulings. Correct binding portability hazards and point to P's implementation ownership.

## Concrete Steps

From `/home/tedks/Projects/orgs/orgs-chaos-coordination`, commit this plan, push `chaos-coordination`, and create `gh pr create --draft --base master`. Edit only Markdown. Run `git diff --check`, inspect the full diff, and check relative links in changed Markdown. Push the frozen head, assemble its diff and acceptance text for native Terra and foreign agy, fix findings and review only fix deltas until clean. Record exact head and outcomes in the PR. Run `git pull --rebase`, `ditz sync`, `git push` and `git status`; if head changes, invalidate affected review evidence and revalidate. Deliver evidence to CTO and await the audit; do not merge beforehand.

## Validation and Acceptance

No executable tools change, so no documentation-mirroring tests are added. Walk through: a bounded lane completes a task and reviews its diff before rebriefing; stale-head gate output cannot clear a new head; an empty reviewer seat cannot be CLEAN without a scoped authorized exception; unknown human input defers delivery while output with an empty composer permits it; mixed input stops submission; exit0 alone never proves receipt; dispatch completion permits a quiet final reply only after control receipts settle, with children still active explicitly named; retirement requires a privately committed append-only handoff and receipt before exit. Confirm these cases have one consistent answer across doctrine, skills and states.

## Idempotence and Recovery

Ditz uses the deterministic issue id above. Keep edits in the assigned worktree, never push master. Preserve review records and resumable private state. Do not alter shared retirement text by whole-file replacement; reconcile concurrent appends or use per-actor shards. Reuse of an existing lane requires explicit context-continuity justification.

## Artifacts and Notes

Public artifacts contain generalized practices only, no session transcripts, identities, private retirement paths or source-session product rulings. The draft PR, reviewed SHA and CTO audit receipt are the final handoff artifacts.

## Interfaces and Dependencies

No new library or executable interface. Existing doctrine prompt packing, sprint wiring, ledger actor ids and state tables remain canonical. P owns dotfiles sender flags, bounded polling, receipt inspection and installed global instructions; orgs defines the behavior those bindings must provide.

Revision note: initial plan records scope, source evidence and acceptance before implementation.

Revision note: implementation now reconciles gate evidence, authorized empty-seat exceptions and a separate lane retirement lifecycle; frozen-head review is next.

Revision note: first review corrections tighten exact-SHA approval, represent EMPTY honestly and deliver operational safety rules in the packed doctrine block; convergence pending.
