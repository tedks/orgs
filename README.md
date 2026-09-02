# Crystal

Speculative merge checking for the org, after Brun, Holmes, Ernst, and
Notkin's Crystal (ESEC/FSE 2011): most speculative merges are clean, and the
value is early warning on the rare real conflict — textual, or *semantic*
(both branches green alone, red together).

## Usage

```bash
crystal/crystal-check.sh [--base <branch>] [--test-cmd <cmd>] [branch ...]
```

Checks every named branch against the base and every pair against each
other. Textual detection uses `git merge-tree --write-tree` (git ≥ 2.38) —
no worktree, no index, no ref is touched. With `--test-cmd`, the clean
merged tree is extracted as **plain files** (`git archive | tar`, no `.git`
in the scratch dir) and the command runs there (`bash -c`, cwd = the merged
files); failure is reported as a semantic conflict. Only local branch names
are accepted, each pinned to a commit once up front so a concurrent ref
update cannot desync the report from the tested tree. Exit codes: `0` all
clean · `1` conflicts found · `2` error.

Assumptions and residuals worth knowing:

- The test command should be green on each branch individually — a branch
  that fails alone makes every one of its pairings FAIL, which is noise.
- The sandbox is *plain files, no `.git`*: this is what keeps a
  side-effecting test from mutating the real repo (a git worktree shares the
  object store and refs, and would not). A `--test-cmd` that itself needs a
  git repository is therefore out of scope in v0.
- `--timeout` (default 120s, needs coreutils `timeout`) bounds a wedged
  foreground command but not a process the test *backgrounds*; boundary-test
  commands must not daemonize.

## Org integration (RUNBOOK §7)

- Run at standup cadence, or continuously: `/loop 30m` invoking this script
  with the boundary-test command. Exit 1 is the standup trigger.
- Report stanzas are revision-stamped (`branch@sha × branch@sha`) —
  speculative results go stale; a decision made on a stanza must be
  reconciled if either branch moved.
- Resolution ownership is semantic: contract change → provider migrates
  callers; invalid assumption → consumer fixes; disputed → record a
  semantic-deadlock event, the lead adjudicates. Whoever merges second
  cleans up by default. Conflict debt is visible at standup so it ages
  loudly.

## v0 scope

Invocable script + loop integration only. The commit-hook daemon
(commit → merge → build → test → report at next agent turn-start) is
deferred until the pilot shows the loop cadence is insufficient.

## Tests

`crystal/test-crystal.sh` builds a scratch repo with an engineered textual
conflict, an engineered semantic conflict (clean merge, red tests), and a
compatible pair, and asserts crystal distinguishes all three — so the test
can fail, by construction, if detection breaks in either direction.
