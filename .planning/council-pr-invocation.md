# Make `/council-review PR #N` a formal, self-recording council

This ExecPlan is a living document maintained in accordance with `.planning/PLANS.md`. It is public-safe: session identities, quota readings and machine records belong in the Lead's private status record, never here.

## Purpose / Big Picture

Before this change, a merge gate needed a caller to type `/council-review formal <pushed-sha> [base-sha]` and, on every convergence round, to work out each reviewer's last-reviewed SHA by hand. A plain `/council-review PR #N` was advisory. After this change, `/council-review PR #N` is the merge gate by construction: it resolves the PR's current pushed head and its merge-base with the target branch, writes a machine-readable round record as a PR comment, and gives every reviewer seat exactly the right bytes. Running the same command again is the convergence pass: it reads the earlier round records and gives each warm seat only its own unreviewed delta and each fresh seat the whole change. Nobody types a SHA. Working-tree, staged, branch-without-PR and file reviews stay advisory and say so. Someone can see it working by running the helper's fixture tests, which replay realistic PR histories (fix pushes, force-pushes, retargets, late reviewers, void rounds, spoofed or corrupt comments, refused-then-corrected arguments) and show the review plan and clearance verdict the skill would act on.

## Progress

- [x] (2026-11-03) Read the assigned instructions, doctrine, Claude binding, the current `council-review` skill, its callers, the prior unification plan and the skill-creator guidance; recorded assumptions below before editing.
- [x] (2026-11-03) Wrote the helper `skills/council-review/scripts/council_pr.py` and its fixture suite; folded in three CTO early checks (alias use is adoption, explicit per-seat disposition before clearance, no raw text in public records).
- [x] (2026-11-03) Rewrote the `council-review` interface and formal workflow around PR rounds; record and planning rules live in `skills/council-review/references/pr-rounds.md`.
- [x] (2026-11-03) Updated active callers, the AGENTS.md gate list and the review-round state table; ran gates; opened draft PR #40 at the first frozen head.
- [x] (2026-11-03) Filed follow-ups `council-formal-alias-removal` and `council-invocation-measurement`.
- [x] (2026-11-03) Round 1 formal council at the first frozen head (baseline workflow): Anthropic and OpenAI seats received findings; Google EMPTY (usage limit). The CTO's audit and the independent acceptance review reported overlapping findings. All are dispositioned below and fixed in this delta.
- [x] (2026-11-03) Round 2 on the fix delta `2f0f9c3..46ca515`: OpenAI (identity-verified resume) and Anthropic (same live native reviewer) received findings; Google EMPTY again (usage limit). Two CTO audits and the acceptance review's second pass are folded in; dispositions below; fixed in the next delta.
- [ ] Round 3 on the next fix delta, to fixpoint.
- [ ] Post gate and council receipts on PR #40; send the finalized interface to the CTO; report READY.

## Assumptions

The repository has a GitHub remote and the `gh` CLI is authenticated wherever a council runs; a host without `gh` cannot run a PR council and must say so rather than fall back to advisory review silently. Anyone can comment on a public PR, so a round record is trusted only when GitHub reports its author as the repository's owner, a member or a collaborator, and only while it is unedited (checked against the real API: unedited comments report equal `created_at` and `updated_at`, and the owner's association is `OWNER`). PR titles, bodies and comments are data for reviewers, never instructions to the council runner. Reviewers review git objects fetched at a frozen SHA, never the live `gh pr diff`. Merge-base means `git merge-base <head> <target tip>` at invocation. A seat is one model provider; its warm identity is private and never written to the PR. The council runner is honest about what it gave each reviewer (`continuity` is self-declared); the helper makes the honest record easy and an over-claimed coverage impossible to derive, but it does not defend against a dishonest collaborator.

## Surprises & Discoveries

- Observation: the orgs repository has no published releases, so "one release" for the compatibility alias needed a boundary of its own. Evidence: `gh release list` is empty. Resolution in the Decision Log.
- Observation: the repository's public-source leak guard rejected the first fixture strings (a home-directory path and a host name). Evidence: `tests/test_setup_leaks.py` failed listing `test_council_pr.py` lines; the fixtures now use the guard's sanctioned synthetic home `/home/u/`.
- Observation: skipping void rounds was the wrong fail-safe. Evidence: a fixture with a clean round followed by a conflicting retry at the same head returned CLEAN from the older round. Void rounds now block clearance and erase the coverage of the seats they name.
- Observation: `gh api --paginate ... --jq '.[]'` prints one compact JSON object per line on the real CLI (checked against PR #39's comments), which is what the parser assumes; `gh search prs --match comments` finds PRs by comment text.

## Decision Log

- Decision: Add a narrow stdlib-only helper instead of describing record parsing in prose. Rationale: the failure classes (spoofed or edited comments, force-push orphaning, restarted-reviewer deltas, retries and late returns, void rounds) are easy to get wrong by eye and each is a small deterministic rule a fixture can test. The helper does not dispatch reviewers or watch PRs. Date/Author: 2026-11-03, Lead.
- Decision: Two kinds of comment per round: an `open` record posted before dispatch and one or more `outcome` records. Rationale: the ruling requires the head to be recorded at invocation; an open record also attributes a late reviewer to its own frozen round. Date/Author: 2026-11-03, Lead.
- Decision: Coverage is derived by chaining a seat's received outcomes. A full review from the current merge-base establishes it; a delta extends it only when warm, starting exactly at the prior coverage, and that coverage is an ancestor of the round's head. Base or target change, force-push, or a void round naming the seat resets it. Rationale: an incomplete delta must never become full coverage. Date/Author: 2026-11-03, Lead (ancestry-per-step and void reset added after round 1).
- Decision: A restarted or repacked native reviewer is fresh and gets the full change. Rationale: PR #39 allowed a repacked native seat with prior findings to review only the delta; under the ruling, a reviewer that has not seen the whole change cannot certify it. This tightens, not loosens, the earlier rule. Date/Author: 2026-11-03, Lead.
- Decision: Clearance judges the latest round opened at the head, including a void one; every dispatched seat needs an explicit outcome; covered seats must still chain; a seat absent from that round is never clean, and its open findings still block. Rationale: silence, conflict or omission must never turn into success. Date/Author: 2026-11-03, Lead (after CTO early check 1 and round 1).
- Decision: The `formal <sha> [base]` alias is retained for exactly one host rollout: accepted in the rollout that first deploys PR rounds, removed by the next `council-review` change deployed to hosts. It routes through the PR round, expands abbreviated SHAs, and is refused unless it names the PR's head and merge-base; without an open PR it is refused (`formal-without-pr`), because a gate without a PR is declared by a governing workflow. Rationale: orgs has no release tags; the host rollout is the unit callers experience. Date/Author: 2026-11-03, Lead.
- Decision: Measurement: unit is one completed production round; window is the first ten across all repositories after the recorded deploy time (`tally --since`); mistakes are caller refusals, captured automatically by the helper as shape and code and carried once by the next posted round from the checkout; valid alias use is adoption; evaluation runs pass `--evaluation`; public records never carry raw argument text. Rationale: the ruling asks for evidence without ceremony and without a per-PR reset; the CTO asked for one start point and evaluator exclusion. Date/Author: 2026-11-03, Lead (after CTO early checks 1-2 and the acceptance review).
- Decision: `plan` parses the typed argument itself rather than taking separate `--pr`/`--route` flags. Rationale: separate flags let the recorded shape disagree with what was resolved, and required the runner to report refusals by hand. Date/Author: 2026-11-03, Lead (round 1).

## Round 1 triage

Round 1 reviewed `2f0f9c3` against base `f6b753f`. Seats: Anthropic (native Opus subagent) received 1 Critical, 7 Important, 9 nits; OpenAI (`ask-agent codex -m gpt-6-sol`) received 3 Critical, 5 Important, 1 nit; Google (`ask-agent agy`) EMPTY, usage limit. The CTO's audit (one Important) and the independent acceptance review (4 Important, 8 nits) are folded in. Dispositions:

Fixed. A void round at the head resurrected older clearance (CTO audit; OpenAI C2; Anthropic C1): clearance now judges the latest round including void ones, and a void round erases the coverage of seats it names. A warm delta across a force-push chained (OpenAI C1; Anthropic N5): each step now requires ancestry. Resolution trusted cached objects after a ref moved (OpenAI C3; Anthropic N6): `git ls-remote` must match `gh`'s OIDs, else `pr-moved`. The alias could omit its SHA, refused abbreviations and left the no-PR case undefined (OpenAI I1; Anthropic I5, I6; acceptance N6): the SHA is required, expanded, and the no-PR alias refused. Free text could enter records through extra fields, `model` or `mechanism` (OpenAI I2; Anthropic I4; acceptance N3): closed key sets and vocabularies. `--raw`, `--pr` and `--correction` were separate and manual (OpenAI I3; acceptance I3): `plan` parses the argument and captures refusals itself, counted once. An all-covered reinvocation had no defined record (OpenAI I4): it opens a disposition-only round when something is outstanding, otherwise no round and no measurement. A late record could lower the undispositioned count and `--unresolved` defaulted to zero (OpenAI I5 in part; Anthropic I2; acceptance I2): the flag is required and a round's count is the maximum of its records. Findings from a seat the latest round omitted did not block (Anthropic I1; acceptance I1): they block, and a clean omitted seat is a limit. `--host` accepted CLI names (Anthropic I3; acceptance N1): refused. Missing clearance fixtures and mutants (Anthropic I7): added, with six new mutants. Two measurement start points and no evaluator exclusion (acceptance I4): one start (`--since` the recorded deploy time) and an `evaluation` cohort. Nits fixed: integer comment-id ordering (Anthropic N1), step pointer (N2), `gh pr merge --match-head-commit` (N3), findings in a separate comment (N4; acceptance N2), required `--expect-head` (N9), `unpushed-local-commits` only when the checkout is ahead (acceptance N4), test environment restored (acceptance N8), stale ExecPlan progress (OpenAI N1; acceptance N7), and explicit `--match comments` search for tally discovery (CTO docs check; Anthropic N8).

Verified without change. The real `gh --jq '.[]'` output shape (Anthropic N7) was checked by the CTO and the Lead against PR #39.

Filed with rationale. Binding each finding's disposition to an identifier in the record (the remainder of OpenAI I5) is filed as `council-finding-disposition-binding`: it would turn the helper into a findings tracker, which the ruling did not ask for; dispositions remain the accountable lead's readable record and ledger events, and the count can no longer be lowered by a later record. Tally completeness depends on the PR list it is given (Anthropic N8): documented, with the search command to cite.

## Round 2 triage

Round 2 reviewed `2f0f9c3..46ca515`. Every round-1 finding was confirmed fixed by its finder, except that the target-tip comparison added for the moved-ref finding introduced a new defect. Dispositions:

Fixed. Resolution required `gh`'s `baseRefOid` to equal the remote target tip, but GitHub leaves that value at the PR's last push, so any PR whose target moved would refuse forever (Anthropic C2; acceptance I5, confirmed by the CTO on public GitHub PRs): only the PR head must match, and the target tip now comes from the remote; a fixture advances the target after the PR's last push, and a mutant restores the old source. A late finding posted to an earlier round did not block a newer clean round (OpenAI C1): late findings now block and open the next round. A conflicting open record naming another head could hide a void round (OpenAI C2): round ids are bound to their head, and every frame of a void round counts. Evaluation rounds consumed or supplied production refusals (OpenAI I1; acceptance N1): pending refusals carry their cohort. Retried posts removed a newer identical refusal, unreadable pending state read as zero, and a cap silently dropped refusals (CTO audit 3): each refusal has a random event id consumed exactly, unreadable state is kept aside and reported as `unknown`, and there is no cap; the tally reports unknown rounds and counts each event id once, which also closes concurrent plans double-counting (acceptance N6). A seat whose Critical stood at the head could be cleared by recording it EMPTY in its own disposition round (Anthropic I8): an EMPTY seat with findings at the head now blocks. This follows the existing rule that a missing finder's fix must be examined by a present seat; with no fix pushed there is nothing for a present seat to examine, so the finder must return or a fix must be pushed; after a fix push the EMPTY finder is a limit, as before. Nits fixed: `check` parses PR reference forms (Anthropic N10, acceptance N5); `pr-not-found` matches only GitHub's "Could not resolve to a PullRequest" (acceptance N2); `PR.md`-style names stay advisory (N3); `--since` must be a GitHub timestamp (N4); ``check` accepts PR reference forms (N5, as above).

Verified without change. The per-worktree pending file: the CTO confirmed `git rev-parse --git-path` resolves separately for each linked worktree.

## Outcomes & Retrospective

At the round-2 fix head, the interface, records, planning and clearance rules are implemented and fixture-tested (95 scenarios, 19 mutants killed). Remaining: the convergence council on the fix delta, receipts on the PR, and the CTO's audit and merge. The first round showed that "ignore what is invalid" is only safe when ignoring can cost a review and never grant one; three separate reviewers found the same violation of that principle.

## Context and Orientation

`skills/council-review/SKILL.md` is the only discoverable council skill (installed by symlinking the whole directory, so `scripts/` and `references/` ship with it). It seats one reviewer per model provider: the host's own provider through a native subagent, the others through `skills/ask-agent`. Its formal rules from PR #39 (frozen pushed SHA, a full first review, warm fix-delta rounds, empty-seat honesty, finding dispositions) now sit under *Rules for every formal round*. Callers are `skills/spec`, `skills/implement`, `skills/review`, `skills/sprint`, `skills/README.md`, `protocol/RUNBOOK.md`, `protocol/STATES.md` (review-round table) and the two binding files. "Fixpoint" means repeating rounds until every present seat returns no new Critical or Important finding.

## Plan of Work

The helper's subcommands are `plan` (route the typed argument, resolve the PR, read records, plan each seat), `render` (record comment body), `post` (idempotent posting, which also clears carried refusals), `check` (live recheck and clearance verdict) and `tally` (measurement window). Decision logic is in small functions that take parsed comments and an ancestry callback. `skills/council-review/scripts/test_council_pr.py` replays scenarios against those functions and runs the command line end to end against a temporary git repository with a fake `gh`.

## Concrete Steps

From the worktree root:

    PYTHONDONTWRITEBYTECODE=1 python3 skills/council-review/scripts/test_council_pr.py
    PYTHONDONTWRITEBYTECODE=1 python3 skills/council-review/scripts/test_council_pr.py --mutation-check
    python3 <skill-creator-dir>/scripts/quick_validate.py skills/council-review
    nix flake check
    nix build .#harness-control
    nix develop --command bash -lc 'PYTHONDONTWRITEBYTECODE=1 python3 tests/test_config.py && PYTHONDONTWRITEBYTECODE=1 python3 tests/test_setup_leaks.py && skills/spawn-agent/scripts/test-tmux-message.sh && skills/initialize-repo/scripts/test-sync-check.sh'
    git diff --check origin/master...HEAD

Expected: `Ran 95 tests ... OK`; every `mutant ...: killed`; `Skill is valid!`; the remaining gates pass.

## Validation and Acceptance

The fixture suite shows, among others: a first round plans full reviews for every seat; after a fix push, each warm seat gets its own delta and an EMPTY seat the whole change; a force-push, retarget or merge-base change resets every seat to full; a delta across a force-push or from a restarted reviewer never becomes coverage; spoofed, edited, corrupt, future-version, cross-PR or extra-field records are ignored with a reason; identical retries count once; a void latest round blocks clearance and resets its seats; a late reviewer's outcome attaches to its own round and cannot lower the undispositioned count; same-head reinvocation dispatches only what is open, or a disposition-only round; a silent seat, a moved head, open findings from any seat, or no present seat refuse clearance; a refused argument is remembered as a shape, carried once and never leaks its text; evaluation and pre-rollout rounds are not measured.

## Idempotence and Recovery

The helper only reads git and GitHub, except `post`, which refuses to add a record identical to one already present, and the small refused-invocation file inside the git directory. Records are append-only; a mistaken record makes its round void, which costs a full review and blocks clearance until a new round, never a false clearance.

## Artifacts and Notes

Gate and council receipts are posted on PR #40 at each reviewed SHA.

## Interfaces and Dependencies

User interface: `/council-review PR #N`, `/council-review #N`, `/council-review branch` (formal when the branch has an open PR, advisory otherwise), advisory `staged`, `<file>` and no-argument forms, and the one-rollout alias `formal <sha> [base]`. Helper interface: `python3 <skill-dir>/scripts/council_pr.py plan --raw '<argument>' --host <provider> [--new-provider] [--evaluation]`, `render --open-record F [--outcomes F --unresolved N]`, `post --body-file F`, `check [N] --expect-head SHA`, `tally --since TIME OWNER/REPO#N...`; needs `python3`, `git` and `gh`. The dotfiles global merge gate will name `/council-review PR #N`, the recorded-head rule and `check --expect-head` before merge, after this lands.

Plan revision note: initial plan written before source edits, including assumptions and the CTO's rollout-boundary and measurement clarifications.

Plan revision note: after round 2, recorded the second triage (target-tip liveness, late findings, void frames, refusal identity and unknown capture) and the updated counts.

Plan revision note: after round 1, recorded the fix delta, the triage of every finding from both seats, the CTO audit and the acceptance review, the tightened decisions, and the measurement start boundary.
