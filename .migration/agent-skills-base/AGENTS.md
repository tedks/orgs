# Agent Instructions: agent-skills

Shared agent skills, scripts, and project scaffolding for Claude and Codex.

## Scope of this file

Global workflow rules live in `~/.claude/CLAUDE.md` (installed from the
dotfiles repo) and apply to every project: landing the plane (session
completion and mandatory push), branch + draft-PR discipline, granular
commits, stacked PRs, the bare-repo/worktree layout, and Nix/Bazel
environment detection. **Do not restate them here.** This file covers only
what is specific to agent-skills; if a rule belongs to every repo, it
belongs in the global instructions instead.

`AGENTS.md` is the canonical instruction file. Keep `CLAUDE.md` (and
`GEMINI.md`, `COPILOT.md` if present) as symlinks to it unless a specific
agent genuinely needs divergent instructions.

## Project structure

- `skills/` — canonical skill instructions, scripts, fixtures, and templates.
- `.planning/PLANS.md` — implementation-plan format.
- `README.md` — installation and configuration contract.

## Environment

Git, Bash, and Python 3.11 or later. Individual skills document additional
requirements such as tmux and provider CLIs. There is no repository-wide Nix
flake or build system.

## Build and test

Run the tests for each changed skill and the repository configuration checks.
Use temporary HOME/config directories for installer and configuration tests;
do not exercise live messaging, retirement, or deletion as an automated gate.
Always verify that new regression tests fail against the previous behavior.

## Issue tracking (ditz)

This project uses `ditz`; issues live on the `ditz-metadata` branch. Run
commands from the intended worktree and check `~/.ditz-config` before writing:
an existing `ditz-metadata` branch takes precedence; otherwise a configured
issue directory can select the filesystem store. Use the installed
`ditz` binary and its `--help=plain`; do not initialize or migrate an existing
tracker merely because discovery fails.

```bash
ditz ready --json             # readiness snapshot, not an ownership claim
ditz show <id> --json         # inspect the exact issue before changing it
ditz start <id> --json        # record in_progress; coordinate ownership separately
ditz sync                    # explicitly fetch/merge/push metadata
```

Use the canonical [agent recipes](https://github.com/tedks/ditz/blob/master/docs/agent-recipes.md)
for creation, multiline text and partial batch results, and the
[JSON/retry contract](https://github.com/tedks/ditz/blob/master/docs/json-contracts.md)
for command-specific receipts. If available, use the shared `issue-tracking`
skill for context checks and recovery. Keep detailed CLI examples in those
references rather than copying them here.

`add --id <name>` creates once, returning an existing issue unchanged; it is
not an upsert. Use `set` for intentional updates. Preserve exit status, stdout
and stderr: a failed batch can have successful items, and an interrupted
mutation can have taken effect. Inspect state/history before retrying an
uncertain append or close. Local mutations do not prove remote sync; include
`ditz sync` in the session completion workflow and check its result.

If `ditz` is absent, follow the project's environment policy. An explicit
installation is `nix profile install github:tedks/ditz#ditz`; a one-off fallback
is `nix run github:tedks/ditz -- <cmd>`. Do not silently switch binaries after a
failed mutation, and do not mistake Nix startup output for ditz JSON.

## Planning

ExecPlans for non-trivial work follow the format in
[.planning/PLANS.md](.planning/PLANS.md).

## Shared agent skills

The files under `.claude/skills/<name>/SKILL.md` are pointers to shared skills
installed at `~/.claude/skills/<name>/SKILL.md`. Install them through dotfiles;
the implementation lives in the separate agent-skills checkout. Follow the
installed skill's instructions rather than copying its scripts into this repo.

## Repo specifics

Installed entry points are `~/.claude/skills/<name>` and
`~/.codex/skills/<name>`. Keep scripts relocatable and keep machine-specific
values in the external agent-skills configuration. Never commit the
app-managed `skills/synced/` cache.

The repository history was extracted from dotfiles; historical commits can
contain former setup-specific values. Current-tree portability checks are
not a historical privacy audit.
