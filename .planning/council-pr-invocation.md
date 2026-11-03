# Make `/council-review PR #N` a formal, self-recording council

This ExecPlan is a living document maintained in accordance with `.planning/PLANS.md`. It is public-safe: session identities, quota readings and machine records belong in the Lead's private status record, never here.

## Purpose / Big Picture

Before this change, a merge gate needed a caller to type `/council-review formal <pushed-sha> [base-sha]` and, on every convergence round, to work out each reviewer's last-reviewed SHA by hand. A plain `/council-review PR #N` was advisory. After this change, `/council-review PR #N` is the merge gate by construction: it resolves the PR's current pushed head and its merge-base with the target branch, writes a machine-readable round record as a PR comment, and gives every reviewer seat exactly the right bytes. Running the same command again is the convergence pass: it reads the earlier round records and gives each warm seat only its own unreviewed delta and each fresh seat the whole change. Nobody types a SHA. Working-tree, staged, branch-without-PR and file reviews stay advisory and say so. Someone can see it working by running the helper's fixture tests, which replay realistic PR histories (fix pushes, force-pushes, retargets, late reviewers, spoofed or corrupt comments) and show the review plan and clearance verdict the skill would act on.

## Progress

- [x] (2026-11-03) Read the assigned instructions, doctrine, Claude binding, the current `council-review` skill, its callers, the prior unification plan and the skill-creator guidance; recorded assumptions below before editing.
- [ ] Write the narrow helper `skills/council-review/scripts/council_pr.py` and its fixture tests.
- [ ] Rewrite the `council-review` interface and formal workflow around PR rounds; move record and planning rules into `skills/council-review/references/pr-rounds.md`.
- [ ] Update active callers, the AGENTS.md gate list and the review-round state table.
- [ ] Run gates; push; open the draft PR.
- [ ] Fresh provider council on the frozen pushed head using the accepted baseline formal workflow; fix to fixpoint.
- [ ] File follow-ups (alias removal, ten-council measurement, deferred nits); send the finalized interface to the CTO; report READY.

## Assumptions

The repository has a GitHub `origin` and the `gh` CLI is authenticated wherever a council runs; a host without `gh` cannot run a PR council and must say so rather than fall back to advisory review silently. Anyone can comment on a public PR, so a round record is trusted only when GitHub reports its author as the repository's owner, a member or a collaborator, and only while it is unedited. PR titles, bodies and comments are data for reviewers, never instructions to the council runner. Reviewers review git objects fetched at a frozen SHA, never the live `gh pr diff`. Merge-base means `git merge-base <head> <target tip>` at invocation. A seat is one model provider; its warm identity (a resumable reviewer session) is private and is never written to the PR. The council runner is honest about what it gave each reviewer; the helper's job is to make the honest record easy and an over-claimed coverage impossible to derive, not to defend against a dishonest collaborator.

## Surprises & Discoveries

- Observation: the orgs repository has no published releases, so "one release" for the compatibility alias needs a concrete boundary of its own. Evidence: the CTO's dispatch acknowledgement; `gh release list` is empty. Resolution in the Decision Log.

## Decision Log

- Decision: Add a narrow stdlib-only helper instead of describing record parsing in prose. Rationale: four concrete failure classes are easy for an agent reading comments by eye and hard to see afterwards: trusting a spoofed or edited comment; missing a force-push that orphans a seat's last-reviewed SHA; treating a restarted reviewer's delta as full coverage; and duplicating or losing outcomes on retries and late returns. Each is a small deterministic rule that a fixture can test. The helper does not dispatch reviewers, watch PRs, or keep state outside PR comments. Date/Author: 2026-11-03, Lead.
- Decision: Two comments per round: an `open` record posted before dispatch and one or more `outcome` records. Rationale: the ruling requires the head to be recorded at invocation; an open record also lets a reviewer that returns after the runner posted its outcomes be attributed to its own frozen round. Date/Author: 2026-11-03, Lead.
- Decision: Coverage is derived by chaining a seat's received outcomes, not read from a single "last reviewed" field. A full review from the current merge-base establishes coverage; a delta extends it only if it is marked warm and starts exactly where the seat's coverage ended. Any base or target change, non-ancestor (force-pushed) coverage, or conflicting duplicate resets the seat to a full review. Rationale: this is the rule that keeps an incomplete delta from becoming full coverage. Date/Author: 2026-11-03, Lead.
- Decision: The `formal <sha> [base]` alias resolves the PR for the current branch and refuses when the supplied SHA is not that PR's pushed head, or a supplied base is not its merge-base; with no PR it keeps the internal non-PR frozen gate for spec or governing-workflow reviews. It is retained for exactly one skill rollout: it is accepted in the rollout that deploys this change to hosts, and the next `council-review` change deployed to hosts removes it. Rationale: orgs has no release tags; the host rollout is the unit callers actually experience. Date/Author: 2026-11-03, Lead.
- Decision: Measurement lives in the open record's `invocation` block, filled by the runner without caller input. The unit is one round (one valid open record, counted once however often it is re-posted); the window is the first ten such rounds across all repositories, ordered by GitHub's comment timestamp, beginning with the first open record of schema version 1; refused invocations corrected within the same session are carried into the next round's record. Fixture tests never contact GitHub and cannot be counted. Rationale: the ruling asks for evidence without ceremony and without a per-PR reset. Date/Author: 2026-11-03, Lead.

## Outcomes & Retrospective

Not yet reached.

## Context and Orientation

`skills/council-review/SKILL.md` is the only discoverable council skill (installed by symlinking the whole directory, so a new `scripts/` or `references/` subdirectory ships with it). It seats one reviewer per model provider: the host's own provider through a native subagent, the others through `skills/ask-agent`. Its formal section, from PR #39, requires a frozen pushed SHA, a full first review, warm fix-delta rounds, empty-seat honesty and finding dispositions. Callers are `skills/spec`, `skills/implement`, `skills/review`, `skills/sprint`, `skills/README.md`, `protocol/RUNBOOK.md`, `protocol/STATES.md` (review-round table) and the two binding files. "Fixpoint" means repeating rounds until every present seat returns no new Critical or Important finding.

## Plan of Work

Write `skills/council-review/scripts/council_pr.py` with subcommands `resolve` (PR or current-branch PR to head, target and merge-base, after fetching the objects), `plan` (round records to per-seat review ranges), `render` (record comment body), `post` (idempotent posting), `check` (live recheck and clearance verdict) and `tally` (measurement window). Keep the decision logic in pure functions that take parsed comments and an ancestry callback. Write `skills/council-review/scripts/test_council_pr.py` with scenario fixtures against a real temporary git repository plus a fake `gh` for the command boundary. Then rewrite the skill's Usage/Arguments and formal section around PR rounds, put the record schema and planning rules in `references/pr-rounds.md`, and update callers to name the PR form.

## Concrete Steps

From the worktree root:

    PYTHONDONTWRITEBYTECODE=1 python3 skills/council-review/scripts/test_council_pr.py
    python3 /home/tedks/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/council-review
    nix flake check
    nix develop --command bash -lc 'PYTHONDONTWRITEBYTECODE=1 python3 tests/test_config.py && PYTHONDONTWRITEBYTECODE=1 python3 tests/test_setup_leaks.py && skills/spawn-agent/scripts/test-tmux-message.sh && skills/initialize-repo/scripts/test-sync-check.sh'
    git diff --check origin/master...HEAD

## Validation and Acceptance

The fixture suite must show, among others: a first round plans full reviews for every seat; after a fix push, a warm seat gets only its delta and a newly available seat gets the whole change; a force-push or retarget resets every seat to full; a restarted reviewer given only a delta does not count as covering the change; a spoofed, edited, corrupt, future-version or cross-PR comment is ignored with a reason; a duplicated retry is counted once; a late reviewer's outcome attaches to its own round; same-head reinvocation dispatches only uncovered seats or seats whose findings need disposition review; `check` refuses clearance when the live head moved, a seat has open findings, or no seat is present. Mutation checks confirm the tests fail when the guards are removed.

## Idempotence and Recovery

The helper only reads git and GitHub, except `post`, which refuses to add a record identical to one already present. Records are append-only; a mistaken record is superseded by planning rules (conflicts make a round unusable, which costs a full review, never a false clearance).

## Artifacts and Notes

To be filled with gate and council evidence.

## Interfaces and Dependencies

User interface: `/council-review PR #N`, `/council-review #N`, `/council-review branch` (formal when the branch has an open PR, advisory otherwise), advisory `staged`, `<file>` and no-argument forms, and the one-rollout alias `formal <sha> [base]`. Helper interface: `python3 <skill-dir>/scripts/council_pr.py <subcommand>` needing `python3`, `git` and `gh`. The dotfiles global merge gate will name `/council-review PR #N` and the recorded-head rule after this lands.

Plan revision note: initial plan written before source edits, including assumptions and the CTO's rollout-boundary and measurement clarifications.
