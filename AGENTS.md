# Agent Instructions: orgs

A harness-portable set of AI agent skills and protocols for running a
"virtual engineering organization" — see [README.md](README.md) for the
concept overview (currently a draft; design is still in flux).

## Scope of this file

Global workflow rules live in `~/.claude/CLAUDE.md` (installed from the
dotfiles repo) and apply to every project: landing the plane (session
completion and mandatory push), branch + draft-PR discipline, granular
commits, stacked PRs, the bare-repo/worktree layout, and Nix/Bazel
environment detection. **Do not restate them here.** This file covers only
what is specific to orgs; if a rule belongs to every repo, it belongs in
the global instructions instead.

`AGENTS.md` is the canonical instruction file. Keep `CLAUDE.md` (and
`GEMINI.md`, `COPILOT.md` if present) as symlinks to it unless a specific
agent genuinely needs divergent instructions.

## Project structure

- `README.md` — concept pitch (draft)
- `skills/` — **the protocol, as a graph of composable skills.** `skills/sprint`
  is the root runbook; the rest are the acts. See `skills/README.md`.
- `protocol/` — `STATES.md` (transition tables the skills cite),
  `templates/` (artifact templates), and `RUNBOOK.md` (now a pointer into the
  skills, absorbed by `skills/sprint`)
- `tools/` — the executables skills wrap: `tools/crystal/` (speculative merge
  detector), `tools/standup/` (forced-observe bus + guard)
- `doctrine/DOCTRINE.md` — the ambient how-we-work doc; its prompt block is
  packed into every role prompt by `skills/pack`
- `bindings/claude-code.md` — how roles map to Claude Code primitives
- `bench/` — the evaluator (frozen exam, grader, nix devshell); `docs/bench/`
  holds the ablation study and the contamination-vectors checklist
- `docs/spec-template.md`, `docs/amendments/` — spec authoring and amendments
- `LESSONS.md` — lessons-learned memory
- `.planning/PLANS.md` — ExecPlan format guide for non-trivial work

## Environment

No special environment. This is a `bare`-type repo (no language runtime,
no Nix flake) — it's a skill/protocol structure, not a standalone
application.

## Build and test

<!-- TODO: nothing to build yet. Fill in once skills/ has real content
     and there's something to lint or test (e.g. skill-doctor checks). -->

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

Note: this repo has no `origin` remote yet (local-only until a repo
name/visibility is chosen), so `ditz sync`'s push step will fail until
one is added — that's expected for now.

## Planning

ExecPlans for non-trivial work follow the format in
[.planning/PLANS.md](.planning/PLANS.md).

## Repo specifics

<!-- TODO: this whole project is pre-spec. The most load-bearing content
     will eventually be the firewalled contract boundaries between agent
     teams, defined via docs/spec-template.md. Nothing else is settled
     yet — do not invent structure beyond what's already here. -->
