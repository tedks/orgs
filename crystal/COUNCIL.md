# Crystal — council record

Reviewed to fixpoint per the org's own review ladder (RUNBOOK §6), on the
fix delta each round. Seats: Codex (OpenAI, warm-chained across rounds via
`codex exec resume` of one session), agy (Google, fresh per round), Claude
(Anthropic, inline as moderator/CTO — the spawned native subagents did not
return actionable findings in time, so the seat is recorded `(inline)` per
the council-review skill's fallback).

| Round | Scope | Codex | agy | Outcome |
|---|---|---|---|---|
| 1 | full | 1 Critical + 5 Important + 4 Minor | 1 Critical + 2 Important + 2 Minor | fixes applied |
| 2 | delta | 1 Critical (deepened) + 4 Important + 1 Minor | (folded) | fixes applied |
| 3 | delta | 1 Critical + 2 Important | (folded) | fixes applied |
| 4 | delta | CLEAN | CLEAN | **fixpoint** |

## What the council changed (most severe first)

- **Critical, resolved across rounds — sandbox isolation.** The original
  materialized the merged tree in a `git worktree`, which shares `.git`, so
  a side-effecting `--test-cmd` could mutate the real repo. Fixed to a
  plain-files extraction (`git archive | tar`, no `.git`), then hardened
  against the inherited-env / `OLDPWD` / `cd -` escapes (unset after `cd`),
  then against git's upward repo discovery when `TMPDIR` nests inside a repo
  (`GIT_CEILING_DIRECTORIES`). Isolation is documented as best-effort
  against accidents, not a security sandbox.
- **Important — extraction fidelity vs. safety.** `git archive` honors
  `export-ignore`; `checkout-index` instead runs clean/smudge filter *code*
  (LFS side effects, network) in the real repo's context. Settled on
  `archive` (no code execution — the safer failure) with export-ignore/LFS
  repos documented out of scope for v0 semantic checks.
- **Important — correctness.** merge-tree captured stdout-only (a stderr
  warning could otherwise be mistaken for the tree OID); branches pinned to
  a SHA once (re-resolution race); local-branch-only validation; ERR trap
  maps unguarded failures to exit 2 rather than leaking git's raw codes.
- **Important — the tripwire.** The semantic assertion was scoped to the
  specific pair's stanza (was a global grep that a spurious base-pair
  failure could satisfy); isolation assertions exercise every escape vector
  the sandbox closes and are mutation-checked (removing a guard makes its
  case go red — per LESSONS.md, a fix's tripwire needs its own mutation
  check).
- **Minor — portability.** `bash >= 4` guarded; GNU-only `sed \t`, cycling
  `paste -d`, and `sed -i`/`\n` in the test all removed.

Full findings and evidence: the round prompts and seat replies are in the
session transcript; this file is the durable summary for the PR record.
