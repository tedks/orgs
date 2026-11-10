# Make Crystal checks follow active work

This ExecPlan is a living document maintained under `.planning/PLANS.md`. It explains the bounded Crystal refresh so a maintainer can repeat it from this checkout.

## Purpose / Big Picture

Crystal warns a sprint lead when two concurrently owned branches cannot be integrated cleanly. A useful warning names the exact commits, proves each side passed the same boundary test alone, and distinguishes a textual merge failure from a clean merge whose combined tests fail. Running across every historical local branch is expensive and misleading. After this change an operator chooses the active branches from the current sprint roster, runs one command, and can act on a revision-stamped report.

## Progress

- [x] (2026-11-10) Read role, doctrine, runbook, checker, tests, and existing issue; run the baseline fixture test.
- [x] (2026-11-10) Change selection and baseline reporting in `tools/crystal/crystal-check.sh`.
- [x] (2026-11-10) Extend `tools/crystal/test-crystal.sh` with negative cases and mutation checks.
- [x] (2026-11-10) Align `skills/crystal/SKILL.md` and `tools/crystal/README.md` with actual behavior and operator delivery.
- [x] (2026-11-10) Run first exact-head gates and push draft PR #45 at `a3e3cde`.
- [ ] Repair first council findings, rerun exact-head gates and a clean convergence round, then mark PR ready and record outcome.

## Surprises & Discoveries

- The checker already extracts merged Git trees with `git archive` into plain files. Its top comment still says `checkout-index`; the skill says scratch worktree. The checked-in fixture suite passes at base `3e180b3`.
- With no arguments, the checker selects every non-base local branch. In a long-lived worktree repository that means historical branches and quadratic pair checks, unrelated to active package ownership.
- The checker tests only merged trees. A red branch alone can therefore be misreported as a semantic conflict.
- The new fixture suite passed under `nix develop`; three private mutation copies, which restored historical selection, disabled the baseline guard, and disabled the stale-head guard respectively, each made the suite fail. The mutations did not touch the source checkout.
- First council round found that a timed-out merged test had been called semantic, and an unrelated red baseline obscured a real pair conflict in the summary. The first timeout fixture condition did not actually trigger; two explicit branch marker files made the combined-only timeout case deterministic. The revised fixture passes.

## Decision Log

- Decision: No-argument invocation is a clean no-op. The operator supplies branch names from current active ownership; no new roster parser or daemon. Rationale: the roster is already the source of truth and explicit input prevents historical sweeps. Date/Author: 2026-11-10, Crystal lead.
- Decision: Run the same boundary test once on each selected pinned revision before pair tests. Mark a baseline failure as an error and skip semantic classification for pairs containing it. Rationale: “semantic conflict” requires individually green sides. Date/Author: 2026-11-10, Crystal lead.
- Decision: Verify selected branch refs again after the run and mark changed refs stale. Rationale: pinning protects internal consistency, while a moved head invalidates a decision made from the report. Date/Author: 2026-11-10, Crystal lead.
- Decision: Keep `git archive` plain-file extraction and existing script/test entrypoints. Rationale: the tool is for trusted boundary tests but should not share the real worktree's Git metadata. Date/Author: 2026-11-10, Crystal lead.
- Decision: Treat GNU timeout statuses 124/125/137 as inconclusive errors and keep exit 2 for mixed error/conflict reports, with a summary that states both. Rationale: a timeout is not an observed test failure, and an unrelated red input must not hide a real conflict. Date/Author: 2026-11-10, Crystal lead.
- Decision: Archive input trees, not commits, for baseline tests. Rationale: commit archives expand `export-subst` while merged tree archives do not; matching extraction avoids a false comparison. Date/Author: 2026-11-10, Crystal lead.

## Outcomes & Retrospective

Draft PR #45 was pushed at `a3e3cde` after local gates. First formal council round recorded two Important findings and an empty Google seat due to quota. Repairs are under test; a new exact-head gate and formal convergence round remain.

## Context and Orientation

`skills/crystal/SKILL.md` is the operator protocol; `tools/crystal/README.md` is the CLI reference; `tools/crystal/crystal-check.sh` computes pair merges with `git merge-tree --write-tree`, extracts clean trees as plain files, and runs a shell boundary-test command; `tools/crystal/test-crystal.sh` creates a disposable Git fixture. `skills/sprint/SKILL.md` supplies cadence and delivery wiring. A baseline is the boundary test on one input commit by itself. A pair is the speculative merge of two pinned commits.

## Plan of Work

In `crystal-check.sh`, remove the implicit all-local-branches discovery. Keep the existing zero-branch success path. Print full commit IDs, check each selected revision's baseline once when `--test-cmd` is supplied, and distinguish baseline failures from pair failures. Do not run pair tests when either input failed baseline. At the end, compare each named branch's current commit with its pinned commit; stale heads make the report non-actionable and exit as an error. Preserve textual merge reporting and plain-file extraction.

In `test-crystal.sh`, retain the existing textual, semantic, compatible, base-only, and isolation cases. Add a historical-branch no-argument case, a red baseline case that cannot be labelled semantic, and a fixture-only branch move case. Each new assertion must fail if its corresponding guard is removed. In the skill and README, give an operator walkthrough: select current active branch owners and exact refs, choose published boundary tests that are green alone, run the checker, deliver conflict findings to the lead and both owners, and recheck after heads move. Record repeated conflict debt in the sprint ledger rather than adding a registry.

## Concrete Steps

From `/home/tedks/Projects/orgs/crystal-refresh-20261110`, edit only the files named above. Run `nix develop --command bash tools/crystal/test-crystal.sh` and expect the final `PASS` line. Run `bash -n tools/crystal/crystal-check.sh tools/crystal/test-crystal.sh` and expect exit 0. The fixture test runs only against disposable repositories; never pass live product branches without owned revisions and test authority.

## Validation and Acceptance

The fixture suite must show a textual conflict, a clean merge with red boundary tests after two green baselines, and a compatible clean pair. No explicit active branches must yield a clean no-op even when historical branches exist. A red baseline must produce an error, not a semantic conflict. A moved branch must make the report stale. The exact pushed commit must pass local gates and formal council review to a clean convergence round. The PR remains for CTO acceptance and merge.

## Idempotence and Recovery

The script creates its own temporary directory and cleans it on exit; it does not update refs. The fixture suite creates and removes only its own test repository. If a command fails, inspect its output, fix the bounded source, and rerun the same gate. Do not replay a test command against a real branch to diagnose a fixture failure.

## Artifacts and Notes

Baseline at `3e180b3`: `tools/crystal/test-crystal.sh` printed `PASS: crystal distinguishes textual/semantic/clean, handles base-only, and sandboxes tests (env, OLDPWD, upward-discovery)`.

## Interfaces and Dependencies

Keep `tools/crystal/crystal-check.sh` and `tools/crystal/test-crystal.sh` executable at their existing paths for the separate Bazel graph onboarding lane. The checker needs Bash 4, Git with `merge-tree --write-tree`, tar, and optionally GNU `timeout`; the project provides its tested environment through Nix. This change adds no build graph files or runtime data assets.

Plan revision 2026-11-10: created from source audit to bound the implementation and preserve published entrypoints.
Plan revision 2026-11-10: marked implemented steps after the fixture suite and three negative mutation checks passed; formal gates and review remain.
Plan revision 2026-11-10: recorded first formal council findings and the bounded timeout, mixed-summary, and archive-fidelity repairs.
