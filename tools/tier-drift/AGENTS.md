# Agent Instructions: tier-drift

Agent-usage telemetry that tracks how the model tier your work needs drifts
downward as capabilities improve, and recommends dispatch changes: models you
are ignoring, work you could move to a cheaper tier, context-heavy workloads
running on a flagship, and same-price successors you have not switched to.

## Scope of this file

Global workflow rules live in `~/.claude/CLAUDE.md` (installed from the
dotfiles repo) and apply to every project: landing the plane (session
completion and mandatory push), branch + draft-PR discipline, granular
commits, stacked PRs, the bare-repo/worktree layout, and Nix/Bazel
environment detection. This file covers what is specific to tier-drift:
the Worktrees and Fanout sections apply those global rules to this repo's
layout and seams rather than redefining them. If a rule belongs to every
repo, it belongs in the global instructions instead.

`AGENTS.md` is the canonical instruction file. Keep `CLAUDE.md` (and
`GEMINI.md`, `COPILOT.md` if present) as symlinks to it unless a specific
agent genuinely needs divergent instructions.

## Project structure

- `src/tier_drift/` — the package (import name uses an underscore; the project is `tier-drift`)
- `catalog/` — the hand-edited model catalog: the one input you change when a new model ships
- `page/` — HTML/CSS/JS for the rendered report
- `tests/` — pytest suite; `tests/pytest_main.py` is the Bazel test entry point
- `docs/DESIGN.md` — purpose, architecture, principles, and the roadmap
- `.planning/` — ExecPlans
- `MODULE.bazel`, `BUILD.bazel`, `requirements.lock` — Bazel build

## Environment

This repo uses a Nix flake. Run project tooling through it:

```bash
nix develop --command <cmd>
```

If using direnv, `.envrc` is `use flake`.

## Build and test

Bazel is the build and test gate:

```bash
nix develop --command bazel test //...
```

`BUILD.bazel` lists sources and test modules explicitly rather than by glob,
so a new module must be added there, or it is not built or not run. Lint and
the fast inner loop run through uv:

```bash
nix develop --command uv run pytest
nix develop --command uv run ruff check .
nix develop --command uv run ruff format --check .
```

`requirements.lock` pins the test-only PyPI deps Bazel uses. Regenerate it
with `uv pip compile requirements.txt -o requirements.lock` after changing
`requirements.txt`.

## Issue tracking (ditz)

Issues live as plain-text YAML on the `ditz-metadata` git branch, one
file per issue; the `ditz` CLI reads and writes them. Nothing appears in
the working tree, and no per-worktree setup is needed — any worktree of
this repo can run `ditz`. Install via Nix:
`nix run github:tedks/ditz -- <cmd>` (or install `github:tedks/ditz#ditz`).

```bash
ditz add "title"              # file a new issue (-t bugfix|feature|task, -c <component>)
ditz ready                    # find available work (unblocked, ranked)
ditz show <id>                # view issue details (add --json for machine output)
ditz start <id>               # claim work (marks in_progress)
ditz close <id> --reason "…"  # complete work (or --wontfix / --reorg)
ditz comment <id> "message"   # add a progress note
ditz sync                     # fetch/merge/push the ditz-metadata branch
```

Include `ditz sync` in the end-of-session push workflow:

```bash
git pull --rebase
ditz sync
git push
```

Use `ditz` commands rather than hand-editing the `ditz-metadata` branch.
Ditz has no priority / label / assignee fields: grouping is by component
(`-c <component>`), sequencing is by the dependency graph
(`ditz blocks <a> <b>`), and urgency is derived. Use a deterministic id
with `--id <name>` when you need an idempotent add — re-creating with the
same id is a no-op, which is what makes `ditz add` safe to call from
unattended jobs.

## Worktrees

This is a bare repo with one worktree per branch:

```
~/Projects/tier-drift/
├── .git/            bare repo, no working tree
├── create-worktree  helper: ./create-worktree <branch> [base]
├── master/
└── <branch>/        one directory per feature branch
```

Work in the worktree for your branch and never on `master`. Start new work
with `./create-worktree <branch>` from the project root. A stacked branch
takes the branch below it as its base, and only the bottom PR targets
`master`. Never run
bare `git stash`, because the stash is shared by every worktree; prefer a WIP
commit. Remove a worktree once its branch has merged, and delete no branch
of a stack until the whole stack has merged.

## Design

[docs/DESIGN.md](docs/DESIGN.md) is the source of truth for what tier-drift
is for and how it is built. Read it before changing the collector's
counting rules or the insight rules. Keep it current: a change to the
pipeline, a counting rule, or the roadmap updates it in the same PR.

Two design rules are load-bearing and easy to break by "simplifying":

- The collector (`src/tier_drift/collector.py`) runs on Python 3.6 with the
  stdlib only, and emits aggregates, never prompt text. Its docstring lists
  each counting rule with the measurement behind it; do not remove one
  without re-measuring on real logs.
- Capability comparisons are only as good as their sources. Any benchmark
  score added to the catalog names its source, and insight confidence is
  derived from whether compared scores share one.

## Fanout

Independent work fans out to parallel agents, one worktree each:

- **Native subagents** for bounded research or review inside a session.
- **Long-running agents** (e.g. in tmux windows) for independent streams of
  work. Give each its own branch and worktree, so no two agents share a
  working tree.
- **A second model from a different provider** for design questions and
  review. Correlated blind spots are the risk a same-provider reviewer
  shares.
- **A multi-provider review to fixpoint** as the merge gate for any
  non-trivial PR: re-review the fix delta until a round finds nothing new,
  because fixes are where new bugs come from.

Natural fanout seams here are the collector's sources (Claude, Codex,
Antigravity, Gemini CLI) and the insight rules, which are independent
functions over the same inputs. Split along them, not across a counting
rule, whose dedup logic has to be read as a whole.

## Planning

ExecPlans for non-trivial work follow the format in
[.planning/PLANS.md](.planning/PLANS.md).

## Repo specifics

- **License.** AGPL-3.0-only (see `LICENSE`). Other licenses are available
  for purchase from the copyright holder. Do not add code under an
  incompatible license.
- **Output is the operator's private data.** Collected aggregates name hosts,
  models and usage volumes. They go to `out/`, which is gitignored. Never
  commit collected data, and never commit a rendered report.
