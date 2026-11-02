---
name: where
description: Use before any find, rg, grep or Glob over a repo or a directory you do not already have an exact path for. Prints a small map of the current project (root, worktrees, depth-2 tree with sizes, the repo's own "Project structure" notes) so you search the worktree you own with a path instead of enumerating ~, ~/Projects, /, /nix or /tmp.
---

# Where

Agents burn time and quota by launching very broad `find` and `rg` calls to
locate things. Ask `where` first, then search with a narrow root.

## Run

```bash
~/.claude/skills/where/scripts/where [--refresh] [--max-age MIN] [PATH]
```

PATH defaults to the current directory. The output is at most about 120
lines and says what it truncated:

- the project root and, for a bare-repo + worktrees layout, `git worktree list`;
- a depth-2 tree of the current worktree's tracked files with sizes;
- the body of the worktree's structure section in `AGENTS.md` (or
  `CLAUDE.md` when AGENTS.md has none): a `##` heading matching, case
  insensitively, `[Project |Repository |Directory ]Structure|Layout`, or a
  one-line note that it is missing. A symlink that leaves the project is not
  read.

The tree lists tracked files only (untracked directories are not shown) and
every top-level directory appears (up to about 90 lines); top-level files
are shown while space remains and the rest collapse into one counted line.
When space runs out, the notice names the command that shows the rest
(`git ls-files <dir>`, `git worktree list`). Past `WHERE_MAX_STAT` sizes
are skipped (shown as `?`) and the tree is the index unfiltered, so files
deleted from disk may be listed (the output says so).
Needs git 2.31 or later. `WHERE_GIT_TIMEOUT` (seconds, default 30) and
`WHERE_MAX_STAT` (tracked-file count past which sizes are skipped, default
20000) bound the work; a failure prints one line and exits 1.

The map is cached under `${XDG_CACHE_HOME:-~/.cache}/where/` and reused for
10 minutes while HEAD, the worktree list and the git directory are unchanged (uncommitted edits are not noticed; use
`--refresh`). It reads git metadata and the tracked-file list only and never
walks outside the project root. It exits 2 with a hint when pointed at a
broad root (`~`, `~/Projects`, `/`, `/tmp`, and similar) or at a directory
that is not in a git project.

## Rules for searching

1. Before searching, run `where`. Use its tree and Project structure notes to
   pick the directory that holds what you want.
2. Search inside the worktree you own, always with an explicit path:
   `rg PATTERN <worktree>/src`, not `rg PATTERN` from a parent.
3. Never enumerate `~/Projects`, `~`, `/`, `/nix` or `/tmp`. If the thing
   lives in another project, `where <that project's path>` and search there.
4. With the Grep and Glob tools, set `path` to the worktree (or a
   subdirectory). A glob pattern or type filter does not shorten the walk;
   only the root and an explicit depth limit of 3 or less do
   (`find DIR -maxdepth 3 ...`).
5. If the project has no "Project structure" section, say so in your
   handoff; the repo's `AGENTS.md` should carry one (see the
   `initialize-repo` skill's template).

## Test

```bash
~/.claude/skills/where/scripts/test-where.sh
```
