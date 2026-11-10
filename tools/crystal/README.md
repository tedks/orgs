# Crystal checker

A small command for previewing integration of **explicitly selected** local branches. It detects textual merge conflicts with `git merge-tree --write-tree`. With `--test-cmd`, it tests each pinned input commit alone, then each clean merged tree. A merged test failure is called a semantic conflict only when both inputs passed the same test alone. The approach is inspired by [Brun, Holmes, Ernst, and Notkin's Crystal](https://homes.cs.washington.edu/~mernst/pubs/vc-conflicts-fse2011-tooldemo.pdf).

## Operator walkthrough

1. Read the sprint's current roster and package statuses. Pick only concurrently active branches owned by this sprint, and a published boundary-test command that works on committed plain files. Confirm authority to inspect those revisions and run that test. Do not point this command at arbitrary live product branches.
2. From that project's repository, run:

       tools/crystal/crystal-check.sh --base master \
         --test-cmd 'bash tests/boundary.sh' package-a package-b

   The same test runs on `master`, `package-a`, `package-b`, and each clean speculative merge. Replace the example command with the project's actual boundary test. Use `--timeout <seconds>` to change the 120-second foreground limit; `--timeout 0` disables it.
3. Read the full commit IDs in the report. Exit `0` means selected checks passed. Exit `1` means at least one textual conflict or a clean merged tree failed after green input baselines. Exit `2` means an input baseline failed, extraction/environment failed, or a selected ref moved and the result is stale. A `stale:` line requires a rerun before acting. A no-argument invocation is a clean no-op; it never scans historical local branches.
4. For a conflict, record the exact pair, test, result, and owner in the sprint ledger; deliver the finding to the accountable lead and both owners. Recheck after either head or the boundary test changes. The skill in `skills/crystal/SKILL.md` gives the cadence and ownership procedure.

Only **local branch names** are accepted, not SHAs or tags. Repeated names and the base name are ignored. The checker pins each name to a full commit ID once, so a concurrent update cannot make the merge and report refer to different commits. It compares the refs again at the end and flags movement. A ref can move immediately after this final comparison; operators should reconcile heads before acting on an older report.

The test command runs with `bash -c` inside a temporary plain-file extraction of the committed tree (`git archive | tar`), without `.git`. Git environment variables and `OLDPWD` are unset and Git upward discovery is limited. This reduces accidental changes to the real repository; it is **not** a security sandbox against hostile commands, absolute paths, or symlink escapes. Use only trusted commands that do not background processes. A command requiring `.git`, clean/smudge filters, or files excluded by `export-ignore` is outside this check's semantic-test support. `git archive` avoids running repository-configured filter code.

Requires Bash 4 or later, Git 2.38 or later, and tar. GNU `timeout` is used when available; otherwise the command warns and runs tests without a time limit. The check creates no Git worktree and updates no ref. It makes `n` base merges and `n(n-1)/2` pair merges for `n` selected branches; keep selection focused on current ownership. Output contains statuses, not the failing test's log, so inspect the affected boundary test separately when diagnosing a red result.

## Fixture tests

Run `nix develop --command bash tools/crystal/test-crystal.sh` from the orgs checkout. It creates disposable Git repositories and checks textual, semantic, clean, baseline-red, no-argument, stale-head, and isolation behavior. The script entrypoints remain stable for the separate build-graph targets.
