
### Speculative merge check (ON)

While your workers run, the harness speculatively merges every pair of worker
branches (and each against `{{RUN_BRANCH}}`) with `crystal-check.sh` and runs a
boundary-test command on the merged tree. It touches no ref and no worktree.

Two failure shapes get reported to you at standup, and both are yours to
adjudicate:

- **textual conflict** — two branches edited the same lines;
- **semantic conflict** — the merge is clean but the boundary tests go red;
  both branches are green alone and broken together.

Resolution ownership is semantic: contract changed → the provider migrates its
callers; assumption was invalid → the consumer fixes it; genuinely disputed →
you adjudicate. Whoever merges second cleans up.
