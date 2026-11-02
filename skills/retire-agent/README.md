# Recover a drifted shared off-duty checkout

Only the repository steward should repair the shared checkout. First stop new
writers and record its path. Do not run `pull --rebase`, `stash`, `reset`, or
`clean` before the evidence below has been inspected and preserved.

1. Fetch `origin/master`. Record `git status --porcelain=v1`,
   `git rev-list --reverse origin/master..HEAD`, and
   `git ls-files --others --exclude-standard` in a private incident directory.
   Review each ahead commit with `git show --stat --format=fuller COMMIT`, then
   compare every changed blob against `origin/master:PATH` with `git show` or
   `git diff`. A different commit hash may contain the same bytes as a file
   already on the remote.
2. For **each** modified or untracked file, compare its bytes with
   `git show origin/master:PATH` (treat a missing remote path as new). Record
   which copy is newer by the content and receipt state, not merely the file
   timestamp. Keep a reviewed manifest of exact paths and dispositions.
3. Copy newer shard and receipt states into a private scratch source tree at
   their repository relative paths. Publish that reviewed set through
   `skills/_shared/offduty-push.sh --repo SHARED --source-root SCRATCH FILE... -m MESSAGE`.
   Before calling the helper directly, confirm both origin fetch and push URLs
   equal the configured `off_duty.remote`, and verify that repository is private
   (for GitHub, `gh repo view URL --json isPrivate --jq .isPrivate` must print
   `true`). The retirement controller performs these checks itself.
   Fetch again and compare the remote bytes. If two copies differ and neither
   should replace the other, preserve the alternate on a private salvage
   branch and record its commit. Never silently choose one.
4. Only after every ahead commit and local file has a recorded remote match,
   pushed replacement, or private salvage commit, make a second inventory of
   the shared checkout. Confirm no writer resumed. Then reset its branch with
   `git reset --hard origin/master`. Remove only the reviewed untracked paths
   from the manifest, one exact entry at a time. Verify `git status --short`
   is empty and `HEAD` equals `origin/master`. If Git attributes normalize
   `waiting/` or `receipts/`, an exact-byte shard can appear modified after
   checkout; reconcile that attribute rule before treating a dirty status as
   an unpublished shard.

The 2026-10-18 repair followed this sequence: a redundant ahead shard commit
was byte identical to remote content; newer receipt states were published to
master; a differing shard copy was kept on a salvage branch; the shared
checkout was reset only after those dispositions were verified.
