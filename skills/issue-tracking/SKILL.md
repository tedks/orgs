---
name: issue-tracking
description: Use when agents create, select, update, comment on, close, or sync ditz issues, especially across worktrees or after uncertain or partial command results. Establish the intended tracker and use the existing CLI safely. Also use when a repo's beads/ditz instructions conflict; resolve the tracker before writing. Does not initialize trackers or migrate beads.
---

# Issue tracking

Make the requested issue change and report what actually happened. Repository
instructions govern the tracker; this skill is a small workflow around the
existing CLI, not a new API or a replacement for project policy.

## Establish the target once per context

Before mutation, identify the intended project/worktree, executable, and store:

1. Check `pwd`, repository instructions, and `git rev-parse --show-toplevel`
   (or `git worktree list` from a bare project root). Use the assigned worktree.
2. Resolve `command -v ditz` and read `ditz --help=plain` plus the relevant
   subcommand's help. Respect Nix/Bazel project tooling rules. Prefer the
   installed executable; if absent, report it and use an explicit project-
   approved install or `nix run github:tedks/ditz -- <cmd>` fallback. Do not
   silently switch binaries after a failure.
3. Inspect relevant `~/.ditz-config` settings and the project's documented
   storage mode. An existing `ditz-metadata` branch takes precedence over
   the configured issue directory; without that branch, the configured
   directory selects the filesystem store. Correlate a known issue or project
   identity with that store before writing. Keep private config contents out
   of reports.

If repo instructions, config, or the observed store disagree, resolve that
specific mismatch before mutation. A missing binary, failed read, or empty
listing is not permission to run `init`, migrate beads, create a fallback
tracker, or declare that no issues exist. Do not apply ditz commands to a
beads project; use its established workflow. Recheck context after changing
project, executable, or config; don't repeat the full preflight per issue.

## Use the current command contract

Read the relevant sections of the canonical
[agent recipes](https://github.com/tedks/ditz/blob/master/docs/agent-recipes.md)
and [JSON/retry contract](https://github.com/tedks/ditz/blob/master/docs/json-contracts.md).
Prefer their local copies in a ditz checkout when available; compare with
installed command help because that binary may predate the docs. Do not invent
flags or a common JSON envelope across commands.

- Capture IDs directly with `add --ids-only`, and retain the exact ID.
  `add --id NAME` creates once; an existing ID returns unchanged, even if new
  creation fields differ. Inspect it before relying on its contents; use `set`
  for an authorized update. This is not an upsert.
- Feed multiline descriptions/comments through the documented stdin flags
  using a quoted here-document or owned file so shell metacharacters stay
  literal. Ditz trims outer stdin whitespace.
- Treat `ready` as a snapshot and `start` as status/history only. Neither
  assigns an owner, grants a lease, nor excludes another agent. Coordinate
  ownership through the project's existing lane records or coordinator.
- Capture exit status, stdout and stderr separately, including on failure.
  Inspect per-item successes and errors before deciding what remains. Retry
  only failed items whose state is known; don't replay successful closes.
- If a mutation's receipt is lost, inspect current fields and `log_events`
  before retrying. Comments and repeated closes append events without retry
  deduplication. If history cannot settle the outcome, report it as unknown
  and resolve the uncertainty before another append.
- Distinguish a local issue change, a metadata commit, and a successful
  `ditz sync`. Source-branch pushes do not prove metadata synchronization.
  Use `sync` within the authorized workflow and check its actual result;
  don't claim remote delivery from local success or an attempted push.

Report the IDs changed, any per-item failures or uncertain outcomes, and the
observed sync state. Avoid dumping complete issue histories or private paths.
