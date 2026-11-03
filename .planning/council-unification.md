# Consolidate council review into one discoverable skill

This ExecPlan is a living document maintained under `.planning/PLANS.md`. It is public-safe: session identities, timing and private evidence belong in the Lead's external status record.

## Purpose / Big Picture

An agent should find one `council-review` skill for both an ordinary exploratory code review and an org's formal merge or spec gate. The skill should say when a review is advisory and when its verdict counts toward acceptance. A repo without org protocol artifacts should still be able to review a worktree, staged diff, branch, PR or file. A protocol sprint should get pinned revisions, clean convergence, and a durable finding record through that same skill. `orgs-review` remains the accountable lead's separate one-rung review.

## Progress

- [x] Read the assigned worktree instructions, doctrine, binding, both existing council skills, plan format and active callers; record assumptions before source edits.
- [x] Consolidate the formal workflow into `skills/council-review/SKILL.md`, retaining its exploratory targets.
- [x] Update active callers and remove the duplicate discovery link; current instruction references have been audited. Historical design and bench descriptions remain records of their original protocol varieties.
- [ ] Validate the skill, links, focused references and required local gates at the final source head. They passed at the substantive source head; rerun after this plan-only correction.
- [ ] Push a draft PR, run a fresh Lead-tier provider council on its frozen head, converge any fixes and record exact evidence. PR #39 is draft and present seats converged at the substantive source head; review this plan-only delta before final receipt.
- [ ] Report the pushed, reviewed head to the CTO for audit; do not merge.

## Surprises & Discoveries

- The org wrapper says a missing required seat needs CEO exception, while the standing rule says an unavailable foreign seat stays empty and present seats can converge. The merged skill will only apply a stricter threshold when a governing policy explicitly declares one.
- `skills/review` is already a separate one-rung accountable-lead procedure. `skills/ledger` means the sprint event log; no current caller requires renaming either.
- The active `protocol/STATES.md` and event-log template still treated a required EMPTY seat as an automatic acceptance block. They must follow Ted's standing present-seat rule unless a governing policy explicitly declares a stricter condition.
- The first council found that a newly available seat must review the full change, and that an org round needs `review-seat-outcome` and `review-clean` ledger events even when it has no findings. The first fix exposed a contradictory package transition row, now qualified.

## Decision Log

- Decision: Keep `council-review` as the sole discoverable council name and remove the `council` source/link after callers move. Rationale: Ted and the CTO chose this entry point, and an alias would preserve the duplicate discovery problem. Date/Author: 2026-11-02, Lead.
- Decision: Mark current worktree/staged/branch/PR/file requests advisory by default; a declared merge or spec gate must name a committed, pushed SHA. Rationale: exploratory behavior must survive without passing off a moving target as a formal clearance. Date/Author: 2026-11-02, Lead.
- Decision: Require org packing and ledger events when the review participates in an org sprint, while leaving ordinary repositories free of org artifacts. Rationale: one reusable skill must work in both contexts. Date/Author: 2026-11-02, Lead.
- Decision: Give a formal gate an explicit `formal <pushed-sha> [base-sha]` invocation and state that a bare PR target is exploratory. Rationale: a caller needs a visible way to request the pinned workflow; dotfiles' older bare-PR merge wording requires coordinated update. Date/Author: 2026-11-02, Lead.
- Decision: Update active state/template rules to present-seat convergence and record each seat outcome plus `review-clean`; record a stricter seat requirement only when a governing policy actually declares it. Rationale: Ted's standing rule resolves the old wrapper conflict, and the ledger must substantiate a zero-finding round. Date/Author: 2026-11-02, Lead.
- Decision: Keep `base-sha` as the original full-review comparison base, distinct from each seat's last-reviewed SHA on a fix round. Rationale: a seat arriving late needs the original change, while warm seats review only their accumulated fix delta. Date/Author: 2026-11-02, Lead.

## Outcomes & Retrospective

The canonical skill and active callers are consolidated. Present council seats converged on the substantive source change, and the local gates passed at that head. A final plan-only correction and its delta review/gates remain before the Lead's READY report. Dotfiles #230 satisfied the installer compatibility condition; global wording is staged in dotfiles #231 for post-orgs merge/deploy. The orgs CTO owns final-head audit and merge.

## Context and Orientation

The source checkout is the `council-unification` worktree of the orgs repository. At the starting revision, `skills/council-review/SKILL.md` supplied reusable exploratory targets and provider-relative seats, while `skills/council/SKILL.md` supplied the org gate: freeze, judgment pack, finding disposition, ledger record and fix-delta convergence. The two source paths each had a local discovery link. This change combines their procedures in `skills/council-review/SKILL.md` and removes `skills/council` and its link; `.agents/skills` still points to `.claude/skills`. The active sprint graph is `skills/sprint/SKILL.md`, summarized in `skills/README.md` and `protocol/RUNBOOK.md`. `skills/spec`, `skills/implement` and `skills/review` invoke the council. A “seat” is one model provider's reviewer; “CLEAN” means a received verdict with no new Critical or Important finding for the reviewed bytes. A “judgment pack” is review material assembled without the author's transcript.

## Plan of Work

First amend `skills/council-review/SKILL.md` to route advisory targets and formal gates, preserving the existing seat matrix, Lead model pins, foreign `ask-agent` transport and parallel launch. Formal rounds will use the existing target collection as source material but pin every seat to a pushed SHA and, in org context, assemble the pack through `orgs-pack`; the fixpoint loop will log and dispose findings through `orgs-ledger`. Then replace active `orgs-council` invocations with `council-review`, clarify that `orgs-review` and `orgs-ledger` are different acts, and remove the duplicate source and its local discovery symlink. Keep historical design, bench and log descriptions as records of their time.

## Concrete Steps

Run from the assigned `council-unification` worktree. Read the full old skill files before editing. Check `git diff --check` and `git diff --stat` after each coherent edit. Stage only this worktree's files. Commit the skill consolidation separately from caller/link cleanup, then push only the feature branch after checking `gh repo view --json visibility`. Open a draft PR with the cross-repo installer sequencing stated. Freeze the PR head and give every review seat the same material. After any fix, commit, push and send only the last-reviewed SHA to new SHA delta for the convergence round. Rerun affected gates at the final SHA.

## Validation and Acceptance

Run the skill creator's `quick_validate.py skills/council-review`, then verify all local discovery links resolve and search active source for `orgs-council` or `skills/council` paths. The expected result is no current caller of the removed source. Inspect retained historical mentions to ensure they are records, not instructions. Run `nix develop --command` for project tooling and `nix flake check`, the source config/leak tests, the tmux transport test and sync installer test required by `AGENTS.md`. Since no runtime code is intended to change, cached packaged checks are acceptable, but a failed gate must be reported and investigated. The fresh council must return received verdicts for present seats on the pinned head; missing foreign seats remain recorded as empty. The final PR comment names the reviewed SHA and local gate commands/results.

## Idempotence and Recovery

The source edits are normal git changes. If an edit fails midway, inspect `git diff` before reapplying it. Never replace a reviewer verdict with silence. If a seat fails, record it as empty and continue with present seats under the standing rule; a documented stricter governing policy would be surfaced to its named authority. The CTO owns dotfiles and merge sequencing. Its #230 installer change is deployed, so the compatibility condition is satisfied; #231 global wording follows the orgs merge. No other worktree is changed here.

## Artifacts and Notes

The plan, final source diff and PR are public. Operational identities, session receipts, timing and private evidence remain outside the repository. The issue `skills-council-vs-council-review-dedupe` is already in progress; its tracker status is not an ownership lease.

## Interfaces and Dependencies

`council-review` is the user-facing invocation. `ask-agent` supplies foreign provider seats, a native subagent supplies the host provider seat, `orgs-pack` builds org judgment packs, and `orgs-ledger` writes org review-round events. `orgs-review` remains a later accountable-lead verdict. The dotfiles CTO owns the installer allowlist and global merge-gate wording; #230 has satisfied the source compatibility requirement and #231 follows this merge.

Plan revision note: initial plan written before source edits to make the cross-skill contract and verification sequence explicit.

Plan revision note: after the first edit, marked the canonical skill and caller migration complete; validation, review and final evidence remain open.

Plan revision note: after first-round council findings, added explicit formal invocation, late-seat handling, full org review-round ledger events and aligned active state/template policy. The first-round SHA remains recorded; only the fix delta will be reviewed by warm seats.

Plan revision note: after the first fix-delta round, qualified the remaining package transition row for first-time seats and clarified the original base SHA and accountable lead's scribe role. Removed quota outcome details from this public plan; operational receipts remain in the external status record.

Plan revision note: corrected Context and Orientation to describe the starting state after the old source was removed, and recorded the current Lead outcome and dotfiles sequencing before the final plan-only delta review.
