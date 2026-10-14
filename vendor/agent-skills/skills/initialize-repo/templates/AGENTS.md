# Agent Instructions: {{PROJECT_NAME}}

{{PROJECT_DESCRIPTION}}

## Scope of this file

Global workflow rules live in `~/.claude/CLAUDE.md` (installed from the
dotfiles repo) and apply to every project: landing the plane (session
completion and mandatory push), branch + draft-PR discipline, granular
commits, stacked PRs, the bare-repo/worktree layout, and Nix/Bazel
environment detection. **Do not restate them here.** This file covers only
what is specific to {{PROJECT_NAME}}; if a rule belongs to every repo, it
belongs in the global instructions instead.

`AGENTS.md` is the canonical instruction file. Keep `CLAUDE.md` (and
`GEMINI.md`, `COPILOT.md` if present) as symlinks to it unless a specific
agent genuinely needs divergent instructions.

## Project structure

<!-- TODO: directory layout, one line per top-level entry -->

## Environment

<!-- TODO: delete this paragraph (and .envrc note) if the project has no flake -->
This repo uses a Nix flake. Run project tooling through it:

```bash
nix develop --command <cmd>
```

If using direnv, `.envrc` is `use flake`.

<!-- TODO: note anything beyond the flake (submodules, secrets, services) -->

## Build and test

<!-- TODO: exact build/test/lint commands, e.g.:
nix develop --command <build>
nix develop --command <test>
-->

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

<!-- TODO: anything an agent must know that is unique to this repo:
domain constraints, legal/licensing notes, safety gates, deploy targets -->
