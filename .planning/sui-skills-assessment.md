# Assess Sui development skills against fleet usage

This ExecPlan is a living document maintained under `.planning/PLANS.md`.

## Current state

At 2026-10-18 06:20 UTC, the lead is Codex gpt-6-sol, session `01a14da8-e1f5-7660-b803-fd548235abd2`, pane `%749`, in `/home/tedks/Projects/orgs/sui-skills-assessment` on `sui-skills-assessment` at `9ba2f2e`. The parent is dotfiles CTO `%321`. Ditz issue `sui-skills-assessment` is in progress and synced. The acknowledgement was pasted into the CTO pane and visibly queued; the sender returned an ambiguous receipt, so it must not be repasted. Deliverable 1 is under way with two bounded native workers: `usage_parser` owns `tools/sui-usage/` and `corpus_inventory` owns `docs/assessments/sui-usage-corpus-inventory.md`. No scratch worktree has been created.

## Purpose / Big Picture

The CTO needs a decision grounded in observed Sui, Move and Walrus agent work. The result will be a private report that shows where agents spend turns, a reproducible measurement script, a survey of candidate skills and a shortlist with evidence for each recommendation. Running the script against fixture logs must reproduce the reported classification behavior without exposing transcript text or secrets.

## Progress

- [x] (2026-10-18 06:19 UTC) Read brief, role, doctrine, binding and project instructions; verified the assigned worktree and branch.
- [x] (2026-10-18 06:19 UTC) Opened the lane issue in orgs ditz.
- [x] (2026-10-18 06:20 UTC) Synced the lane issue and briefed two bounded workers with distinct artifact ownership.
- [ ] Build and verify the Deliverable 1 corpus inventory and measurement script, then publish its report section and push a checkpoint.
- [ ] Survey external and local candidates, record their provenance and load/behavior costs, perform bounded offline spot-checks, and push a checkpoint.
- [ ] Build the gap matrix and shortlist, file product questions, run local gates and council to fixpoint, and submit the reviewable draft PR.
- [ ] Write and privately push the retirement shard after the CTO receives `SUISKILLS-DONE`.

## Surprises & Discoveries

- The orgs checkout has a configured `origin`, despite a stale repo note saying otherwise. The branch starts at `origin/master` `9ba2f2e`.
- The shared sender reported `mixed-input-after-paste` for the acknowledgement while the CTO was busy. A pane read showed this exact message above an empty composer as queued input. Treat delivery as pending independent verification, never a reason to paste again.

## Decision Log

- Decision: Use session as the counting unit and report host, project, provider, model tier and week separately. Rationale: multiple retries inside one session and repeated fetches across sessions have different meanings. Date/Author: 2026-10-18, lead.
- Decision: Keep the fleet corpus read-only and keep raw transcript lines, addresses, keys, mnemonics and human text out of artifacts. Rationale: only aggregates and sanitized command/error shapes are needed for the adoption decision. Date/Author: 2026-10-18, lead.
- Decision: Treat unknown model identity, command classification and error type as unknown, rather than infer a favorable outcome. Rationale: the ranking must expose thin evidence. Date/Author: 2026-10-18, lead.

## Outcomes & Retrospective

Pending each deliverable.

## Context and Orientation

The canonical mission brief is `/home/tedks/.local/state/org-briefs/20261018/sui-skills-assessment.md`. The assigned repository is a bare git project with this feature worktree. The private report belongs at `docs/assessments/sui-skills-2026-10.md`; the reusable log reader, fixtures and tests belong under `tools/sui-usage/`. Claude transcript files are JSONL under `~/.claude/projects/<cwd-slug>/`; Codex rollouts are JSONL under `~/.codex/sessions/YYYY/MM/DD/`. Remote hosts `tower0.local` and `splinter1.local` are read-only. Sui project identity must be confirmed from manifests, not the brief's project list. The known live Chaos testnet launch must not be disturbed.

## Plan of Work

First enumerate targeted projects and log directories, using `where` before repository searches. In fixtures, encode representative Claude and Codex event shapes, including malformed lines, repeated compiler errors, document fetches, source-tree searches and keytool calls. Run tests red before implementation, then parse streaming JSONL and emit only aggregate JSON. Compare results to a bounded manual sample, audit privacy, and place measured tables and caveats in the report.

Then inspect official and community candidate sources, record source and version evidence, and shortlist candidates for three offline pain-point spot-checks. Use only `sui move build/test` or a local sui-devstack network. The final report compares observed pain to coverage and deployment cost and recommends no more than five candidates. The CTO decides integration; Ted decides third-party vendoring and project adoption.

## Concrete Steps

From this worktree, run `python3 -m unittest discover -s tools/sui-usage/tests -v` and expect fixtures to fail before the parser is implemented, then pass after implementation. Run the measurement CLI with explicit, scoped roots and time range; store only summarized JSON. Inspect `git diff` at each boundary, commit, `git pull --rebase`, `ditz sync`, push and verify status. Build a draft PR early, then perform council review to fixpoint before requesting acceptance.

## Validation and Acceptance

Deliverable 1 is accepted for checkpoint when fixture tests pass, the script emits reproducible per-project/provider/tier counts for the requested categories, a manual sample has been cross-checked, and privacy inspection shows no raw transcript text, key material or wallet addresses. The report must describe log coverage, classification rules and uncertainty. Deliverable 2 requires candidate source links, maintainer/license/date/version/load/behavior/coverage fields and three bounded paired spot-checks. Deliverable 3 requires the pain matrix, shortlist and open product questions in ditz. The exact pushed commit and gate output accompany each checkpoint.

## Idempotence and Recovery

The measurement CLI only reads explicitly named roots and writes a selected output file under this worktree. Rerunning it should replace the summary deterministically without modifying logs. The issue ID is deterministic; `ditz add --id` must not be used as an update. If a message receipt is ambiguous, inspect the target and never repaste unless exact unsent input is proven. Scratch worktrees are removed only after an enumerated review of owned paths and running processes.

## Artifacts and Notes

Initial source head: `9ba2f2e`. Lane issue: `sui-skills-assessment`. No quality gate has run yet.

## Interfaces and Dependencies

Use Python standard library only for the measurement CLI and tests; no dependency installation is authorized. Input is Claude and Codex JSONL files selected by the caller, and output is an aggregate JSON document plus a human-readable report section. Repo manifest reads and public source research inform classification but are not mutated.

Change note: initial plan created at mission start to make the acceptance evidence and privacy constraints explicit before implementation.
