# Publish off-duty handoffs without committing in a shared checkout

This ExecPlan is a living document maintained under `.planning/PLANS.md`.

Current state (2026-10-19 03:27Z): implementation is pushed to draft agent-skills PR #12 and the one-sentence public rule is in draft orgs PR #31. OpenAI and Anthropic council seats reached CLEAN on the final code delta; the Google seat was unavailable at quota. All changed-skill, native-reader, configuration, and Nix gates passed on the final code. `tests/test_setup_leaks.py` still fails on older tracked planning files under existing issue `setup-leaks-existing-plans`. The CTO owns the ruling for ready/merge and the post-merge installed Nix snapshot.

## Purpose / Big Picture

Retirement can leave a shard on one machine while another process advances the private remote. A local file check can then claim handoff success even though the remote lacks the shard. After this change, callers publish named shard and receipt files from their own private staging directory through a disposable worktree based on fetched `origin/master`. A fetch and byte comparison establish the remote handoff before exit.

## Progress

- [x] (2026-10-19 02:20Z) Confirm assigned branch, read the issue, and deliver the lead acknowledgement.
- [x] (2026-10-19 02:24Z) Add offline helper tests, observe them fail before implementation, and implement bounded publication retry in draft PR #12.
- [x] (2026-10-19 02:28Z) Add a remote-presence regression test, observe its false positive, and require fetched remote commit and bytes.
- [x] (2026-10-19 02:31Z) Move retire-agent's publication files into per-event private state and add an index builder that runs on every retry.
- [x] (2026-10-19 02:33Z) Open draft orgs PR #31 with the retirement rule.
- [x] (2026-10-19 03:05Z) Fix council's stale-ref finding across helper, retirement, and checkpoint evidence; confirm a prior-version red regression and current green offline checks.
- [x] (2026-10-19 03:15Z) Converge council review through four rounds. The final fix stores requested files as unfiltered Git blobs, preserving exact source bytes under committed and dirty attributes. OpenAI native and Anthropic Opus seats are CLEAN; Google was unavailable at quota.
- [x] (2026-10-19 03:18Z) Bring retirement (165 tests), helper (12 tests), and the complete retirement mutation sweep to green.
- [x] (2026-10-19 03:27Z) Run harness-control (115), configuration (21 and 6), native-reader suites and mutations, and `nix flake check`; complete council review to fixpoint. The pre-existing setup-leak failure is tracked separately.
- [ ] Record final draft PR heads and issue status, then publish the private lead shard through this helper.

## Surprises & Discoveries

The current shared sender requires a measured Claude composer with a nonbreaking space after its prompt glyph. The retire-agent fixture used an ordinary space, so Claude fixture tests failed even against the previous retire-agent implementation. The fixture now renders the measured prompt shape.

The old retirement tests also expected canonical files and the generated index to appear in the shared checkout. Those expectations moved to the private staging directory or fetched remote. The shared checkout's dirty files became negative assertions: they stay unchanged.

Council round one found that `git fetch origin master` can succeed without updating `origin/master` under a custom fetch refspec. The old helper could return a stale commit on its no-op path, and retirement could authorize exit after a remote shard was removed. The helper and verification paths now fetch into unique refs, use the resulting commit ID, and delete only their own temporary refs. A new helper test failed against commit `c5765f4` with the stale-ref false positive and passes on this branch. Later convergence rounds found an `unknown` caller-session collision and a source-byte mismatch under Git attributes; both have red-before-green regressions and are fixed.

## Decision Log

- Decision: Keep each existing receipt state and publish each transition. Rationale: downstream readers already consume these states, and retaining them avoids a receipt contract change. Date/Author: 2026-10-19, off-duty write-path lead.
- Decision: Build the index and recheck session identity inside each fresh temporary worktree after copying the event files. Rationale: a static index copied from an older checkout could erase a row added by a concurrent writer during a non-fast-forward retry, or accept a same-session shard from another host. Date/Author: 2026-10-19, off-duty write-path lead.
- Decision: Keep private event staging files in the Git common directory for resume. Rationale: a failed publication must not strand a receipt in the shared checkout or lose the source bytes needed for an exact retry. Date/Author: 2026-10-19, off-duty write-path lead.
- Decision: Stage each named file as an unfiltered Git blob. Rationale: verification promises the exact caller-owned bytes even if remote or shared checkout attributes request conversion. Date/Author: 2026-10-19, off-duty write-path lead.

## Outcomes & Retrospective

The helper tests exercise a dirty and ahead shared checkout, path rejection, idempotence, failure cleanup, a stale tracking ref, exact blobs under attributes, and remote races that add another index entry or a duplicate session. The full retirement suite passed 165 tests and every active retirement mutation was caught. Harness-control passed 115 tests; repository configuration passed 21 and 6 tests; native readers passed 10, 12, and 63 tests and their mutation checks. `nix flake check` passed its transport, package, and unit checks, including the harness-control mutation gate. The separate setup-leak test has an unrelated known failure in existing `.planning/harness-compact-*.md` files (`setup-leaks-existing-plans`).

## Context and Orientation

`skills/_shared/offduty-push.sh` is the publication entry point. Its `--repo` argument names an existing private Git working tree, `--source-root` names a caller-owned tree containing repository-relative files, and each positional file path is copied from that tree. By default it accepts only `waiting/`, `receipts/`, `lane-notes/`, and `writing/`; `--allow-path` is an explicit exception. The helper fetches master into a unique private ref, creates a detached worktree under XDG, TMPDIR, XDG cache, or `/tmp` scratch, commits only the requested files, and pushes `HEAD:master`. On a remote advance it removes that worktree and tries again, at most three times.

`skills/retire-agent/scripts/retire.py` controls the lifecycle. It stores mutable private state under the repository Git common directory. It now stages each event's shard and receipt under `<event>.publication/` there and calls the helper. `skills/retire-agent/scripts/build-index.py` regenerates the bounded section of `waiting/INDEX.md` in the temporary worktree on each attempt, preserving the steward's surrounding text.

`harness-control/harness_control.py` checks checkpoint evidence. A pushed-remote attestation now fetches master into a unique ref and verifies that the named commit is on that fetched tip and that the remote shard bytes match the recorded SHA-256 digest. `skills/retire-agent/README.md` documents repair of an already drifted shared checkout. The orgs rule is a separate public documentation PR.

## Plan of Work

Maintain the helper's source and destination path guards and test each one against a throwaway bare repository. Keep all publication content outside the shared checkout and preserve it after a failed push. Verify a successful push by fetching and comparing Git blob IDs. Update retirement fixture assertions to distinguish private staging, the remote, and unrelated local shared content. Re-run focused tests after each adjustment, then run the complete skill, harness-control, and repository configuration gates. Review the exact final diff and repeat council review on any fix delta until clean.

## Concrete Steps

From this worktree, run `python3 skills/_shared/test-offduty-push.py`, `python3 skills/retire-agent/scripts/test-retire.py`, `python3 skills/retire-agent/scripts/test-mutations.py`, and the harness-control tests under `harness-control/`. Run `python3 tests/test_config.py` and `python3 tests/test_setup_leaks.py` for configuration. Use `bash -n skills/_shared/offduty-push.sh` and `git diff --check` before committing. The tests use temporary bare repositories and private tmux fixtures; they do not publish to the real off-duty remote.

## Validation and Acceptance

The helper test must show one pushed commit whose shard bytes match its source while the shared checkout's HEAD, dirty tracked file, staged local commit, and untracked file remain unchanged. A forced concurrent push must produce a remote history containing both writers' files and both generated index rows. The retirement test must show a shard and final receipt on the bare remote and no new `waiting/` or `receipts/` files in the shared checkout. A local-only checkpoint commit must be rejected; pushing it to the bare remote must make the same evidence verifiable.

## Idempotence and Recovery

The helper prints the existing remote commit when requested bytes are already present. A failed push keeps the caller's staging files and removes only the temporary worktree it created. Retirement resumes from its pinned private event state and verifies remote evidence before any exit send. The shared checkout recovery procedure requires a reviewed per-file disposition before a steward resets it.

## Artifacts and Notes

The first helper test run failed because the helper did not exist. The first checkpoint regression run failed because `verify_checkpoint` accepted a local-only commit. Both are explicit red-before-green evidence. The draft PRs are agent-skills #12 and orgs #31.

## Interfaces and Dependencies

The helper uses Bash, Git, and a private scratch directory. It accepts `--repo REPO --source-root ROOT FILE... -m MESSAGE`, with optional `--allow-path` and the retire-agent-owned `--build-index EXECUTABLE` hook. It prints one commit hash on stdout. The index builder accepts the temporary worktree path and optional session/event identifiers for retry-time duplicate detection. Python 3.11 or later is required by retire-agent and its tests. No real network or private remote is needed for the local gates.

Plan update 2026-10-19: recorded the implemented architecture and the fixture compatibility finding so the current suite reconciliation can resume from this file alone.
