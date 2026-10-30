# Consolidate agent tooling into orgs

This ExecPlan follows `.planning/PLANS.md`. It is a living record for the
`consolidation` branch. Current state: Phase 2 is in progress. The public
agent-skills tip has been imported and its files moved into direct orgs paths;
the old vendor snapshot is removed. Draft orgs PR #34 is open at `17994ec`.
The private installer draft PR is open and the tracker histories are merged
at `e92c5f3`. Council review and host cutover remain pending. No live host
links have changed. Tier-drift remains behind its separate ruling.

## Purpose / Big Picture

The operator wants `orgs` to hold the reusable agent workflow and tooling.
After migration, a fresh install should obtain shared skills and
`harness-control` from one public, commit-pinned source. Private machine
configuration remains in `dotfiles`, and private off-duty records remain
private. A scratch-prefix installation and local tests will demonstrate the
new source path before any host cutover.

## Progress

- [x] (2026-10-29) Read the brief, roles, doctrine, and global instructions;
  confirmed the designated worktree on `consolidation` at `480d875`; sent
  `CONSOL-ACK` to the CTO with a submitted receipt.
- [x] (2026-10-29) Inventoried source trees, naming collisions, tracker IDs,
  consumer paths, and in-flight PR dependencies.
- [x] (2026-10-29) Scanned the complete proposed tier-drift source commit and
  its message without publishing its content; publication awaits a ruling.
- [x] (2026-10-29) Sent `CONSOL-CHECKPOINT-1` with pushed plan commit
  `74a4eb6adf6344f3d1964a7f4bbceb5868d69888` and scan evidence.
- [x] (2026-10-29) Imported public agent-skills `f703451` as a subtree parent
  of `f52ac9994f024d7c9d5126c372b8b6f9345b7542`, moved the skill,
  harness-control, flake, and test trees to direct paths in `26f8e7a`, and
  verified the source tip remains an ancestor.
- [x] (2026-10-29) Finished direct skill discovery, obsolete vendor removal,
  source-specific docs, and gates; pushed `17994ec8e6bffb0d29309052e591a21af4c353f1`
  and opened draft orgs PR #34.
- [x] (2026-10-29) Merged public issue tracker histories at
  `e92c5f3420aca22ec5f97f14231ee86b4a0c25a6`, pushed the metadata branch,
  ran `ditz sync`, and verified one source and one existing issue through CLI.
- [x] (2026-10-29) Opened the private dotfiles installer draft PR; its
  fixture tests and scratch skill installation passed.
- [ ] Council review both draft PRs, fix findings, and rerun the exact-head
  gates before requesting readiness.
- [ ] Prepare public `orgs` and private `dotfiles` draft PRs, preserve source
  history, and run local and scratch-prefix gates.
- [ ] Await explicit `CONSOL-CUTOVER-OK` for host changes, final synchronization,
  and archive work.

## Surprises & Discoveries

- GitHub reports `tedks/tier-drift` as private on 2026-10-29, although the
  brief calls its source public. The CTO confirmed that publication requires
  Ted's explicit approval. No tier-drift content may enter public `orgs`
  before `CONSOL-TIERDRIFT-OK`.
- The proposed tier-drift source is `master` at
  `c4f2d2eb4b3b4ac76d68fb0e0788eb651eb6d4d7`, one root commit authored
  by Ted Smith. The scan covered its full message and all 28 tracked files,
  including lockfiles and symlinks. It found zero named fleet hostnames,
  zero IPv4 or IPv6 addresses, and zero UUID-shaped session IDs. Matches for
  council and ask-agent terms are generic collector classification logic,
  design text, and synthetic tests. Matches for SSH are generic collection
  instructions, not host entries or credentials. Numerical matches are
  published model prices, code constants, and synthetic test data; no
  observed host or session usage figures were found. This is a bounded scan,
  not authorization to publish.
- The source `agent-skills` `master` is `f7034513724f012680e2dc707727110739aa736b`
  with 371 reachable commits and 159 tracked files. The existing `orgs`
  snapshot pins the older `5b1919e723a92b1c90f2ae8495f594e651125564`
  and includes only four shared skills and three `_shared` support files.
- The imported `tests/test_setup_leaks.py` originally scanned every tracked
  file. Existing orgs protocol docs already contain paths and public owner
  names outside the portable-tooling scope. The test now scans the imported
  12 skill directories, harness-control, root Nix files, and imported tests,
  with positive assertions that key source files are present. Its forbidden
  fixture check still passes. The initial whole-repo run failed; the scoped
  run passed 2 tests.
- An ordinary `git pull --rebase` tried to replay the imported source's
  history and conflicted in three root files. The rebase was aborted; the
  tested `17994ec` head and source merge parent were verified intact. The
  remote feature branch was fetched explicitly and was 374 commits behind
  the local branch with zero remote-only commits before the normal push.

## Decision Log

- Decision: inventory tier-drift metadata and dependencies only until the
  privacy conflict is resolved.
  Rationale: moving even apparently sanitized content from a private remote
  to a public repository crosses the brief's explicit stop condition.
  Date/Author: 2026-10-29, orgs-consolidation lane.
- Decision: merge reusable skills directly under `orgs/skills/` beside the
  existing protocol skills. The current source directory names have no
  collisions. Keep the process skill names and reusable skill names intact.
  Rationale: one installed `skills/` root satisfies the existing installer
  contract and preserves direct `~/.claude/skills` and per-skill Codex links.
  Date/Author: 2026-10-29, orgs-consolidation lane.
- Decision: retain the existing `agent-skills` configuration file, environment
  variable, and installed user paths as compatibility interfaces during the
  installer move; repoint their source checkout to `orgs`.
  Rationale: the file schema already validates URL, branch, and checkout,
  and changing user-facing paths would add an unrelated migration.
  Date/Author: 2026-10-29, orgs-consolidation lane.
- Decision: scope the imported setup-leak test to the imported tooling paths.
  Rationale: the original repository-wide assumption does not hold for orgs,
  while the imported content still needs the full guard.
  Date/Author: 2026-10-29, orgs-consolidation lane.
- Decision: abort the default rebase and compare the fetched feature branch
  before pushing the preserved merge topology. Use `--rebase-merges` only if
  a future remote divergence actually requires a rebase.
  Rationale: flattening the public source merge would discard its explicit
  ancestry and create artificial conflicts. The remote had no new commits.
  Date/Author: 2026-10-29, orgs-consolidation lane; doctrine bend logged.

## Outcomes & Retrospective

Phase 1 mapped the move and isolated the private tier-drift publication gate.
The public source import is in draft PR #34, with its history and full
Nix/package checks. The private installer draft passed fixture tests and
scratch skill installation. The tracker merge is delivered. Council review,
source final sync, and host cutover remain pending.

## Context and Orientation

The `orgs` checkout already has 13 process skills under `skills/`: `council`,
`crystal`, `decompose`, `huddle`, `implement`, `integrate`, `ledger`, `pack`,
`retro`, `review`, `spec`, `sprint`, and `standup`. Its local `.claude/skills/`
links currently expose four entries from a pinned, verbatim snapshot in
`vendor/agent-skills/`, and `.agents/skills` aliases that discovery directory.

The separate public `agent-skills` source has 12 reusable skill directories:
`_shared`, `ask-agent`, `council-review`, `host-hygiene`, `initialize-repo`,
`issue-tracking`, `lean-automation`, `retire-agent`, `spawn-agent`,
`stacked-prs`, `usage`, and `where`. Its root `harness-control/`,
`flake.nix`, `flake.lock`, and `tests/` form the Nix package and checks. The
`_shared/native` helpers are imported by harness-control; moving only the
skill instructions would break the package. The source `README.md` and
`AGENTS.md` describe the old independent checkout and must be reconciled
into the corresponding orgs documents rather than replacing them.

`dotfiles` is private and remains the host configuration repo. It currently
installs the public source by reference and holds machine-owned configuration,
the token-usage collector and tripwire under `scripts/usage`, search guards,
wrapper scripts, and host-specific docs. The private tier-drift companion
work and the separate private archive stay outside public `orgs`.

### Source and destination map

Import `agent-skills/skills/*` into `orgs/skills/*`, preserving their
directory names. Import `agent-skills/harness-control/` to
`orgs/harness-control/`, its root Nix flake and tests to the same root paths,
and retain the AGPL license already used by both repositories. Add
`skills/synced/` to the orgs ignore list because the resolver migrates the
app-managed cache there. Reconcile `skills/README.md`, root `README.md`, and
`AGENTS.md`; replace the four project-local links so they resolve to
`skills/<name>`, and expose the other reusable skills through the same local
discovery directory. Update `tools/vendor-skills/`, its lock, the vendor tree,
and their documentation in a separately reviewed removal after the direct
source is usable. Inventory exact entries before the deletion sweep.

Only after `CONSOL-TIERDRIFT-OK`, import the single sanitized commit at
`c4f2d2eb4b3b4ac76d68fb0e0788eb651eb6d4d7` under
`orgs/tools/tier-drift/`. Keep its build metadata and tests together;
exercise Bazel from that nested project directory. The private archive and
private dotfiles companion work are excluded, including their history.

### Tracker merge

The public `orgs` `ditz-metadata` head was
`2484ef2426d58ca91c29ecd125c8cfb52b9c28b2`; the public
`agent-skills` tracker head was
`449fc7a19cbe4c0b3e86b80e584c34675bbef2d3`. They hold 23 and 34
issue YAML files respectively. Their 57 issue IDs and filenames are
disjoint. Only `.ditz/project.yaml` collides; retain the orgs project
identity and merge the issue records while preserving source branch history.
Recheck collisions against freshly fetched tracker heads immediately before
the merge, use the established ditz store, and verify all IDs with `ditz`.

### Consumers and cutover surface

The live user interfaces are `~/.claude/skills -> <checkout>/skills`, 13
per-skill `~/.codex/skills/<name>` symlinks (with `.system` retained), the
dotfiles-owned `~/.bin/tmux-message` wrapper, and the stable
`~/.local/bin/harness-control` executable and MCP registrations. The current
links still resolve to the independent source; Phase 2 must not change them.

In private `dotfiles`, `.agent-skills.ref` provides the source URL, branch,
and bare-repo worktree path. `scripts/install/resolve-agent-skills` validates
that checkout's origin, clean state, tracking state, config validator, and
`skills/synced` migration. `install-claude-config` links the whole skills
directory; `install-codex-config` links each skill; `install-harness-control`
builds `#harness-control` from the validated checkout's exact Git revision,
installs a dedicated Nix profile, and publishes the stable executable.
`install-claude-introspect`, `install-all`, and the Codex registration flow
call those installers. The `.bin/tmux-message` wrapper and
`harness-control-smoke` consume installed paths. Their associated
`test-install-*` tests must be updated and rerun.

Private documentation that names the old repository or checkout includes
`docs/agent-skills-install.md`, `docs/harness-control.md`,
`docs/tmux-messaging.md`, `docs/ask-agent-session-resume.md`, and the global
`CLAUDE.md`. The usage skill invokes the installed `token-usage` CLI from
private `scripts/usage`; the `where` skill's examples use the stable installed
`~/.claude/skills` path. Preserve those interfaces. The private
`.config/agent-skills/config.toml.template`, usage scripts, search guards,
private host docs, and tier-drift companion work stay in dotfiles.

The orgs `vendor/agent-skills/` snapshot, lock, updater, README, and current
project-local links are additional consumers. Their old pin must stop being
the source of truth when direct skills land. No host link changes occur until
Phase 3.

The two required agent-skills PRs are #13 (Codex idle composer recognition)
and #14 (harness-control usage posture). Both were open on 2026-10-29 and
must land in source before final synchronization. #11 and #15 were also open
drafts; check their state at final sync and coordinate any necessary inclusion
without silently broadening this migration.

## Assumptions and failure modes

- The source repositories may advance during this task; record source SHAs
  and make a final sync before cutover.
- The installed user skill links and harness-control registration remain live
  until the authorized cutover. Changing them early would break active lanes.
- Public `orgs` receives only content independently verified as public or
  explicitly approved for publication. A private remote's history cannot be
  assumed safe from a clean-looking tip.
- The tracker merge must preserve existing issue IDs and detect ID collisions
  before writing the destination branch.

## Plan of Work

Phase 1 records the map above and sends a checkpoint. Phase 2 imports the
public agent-skills history using a temporary subtree prefix, then moves
the mapped files to their intended orgs paths in reviewable commits. The
merge commit must retain the source tip as an ancestor; `git log` must show
its history. Importing via a temporary prefix avoids trying to add a
subtree directly into the existing `skills/` directory. On final source
sync, import the new source tip under a fresh temporary prefix, apply the
delta to the direct paths, and verify the mapped trees. Remove the temporary
prefix only from the working tree after the commits preserve ancestry.

Prepare a private dotfiles draft PR that re-points `.agent-skills.ref` to
the public orgs checkout while retaining its three-field validation and
exact-revision build. Update the installer tests and docs to name the new
source. Rehearse both links and harness-control under an owned scratch home
and profile. Keep all live user links and registration untouched.

Phase 3 waits for the CTO's `CONSOL-CUTOVER-OK`. After the required source
PRs land, synchronize the final source tip, re-run the gates, and hand the
ready PR heads to the CTO for merge. A separate
`CONSOL-TIERDRIFT-OK` is necessary before any tier-drift import. Only the
cutover approval permits fleet installation and source-repository archive.

## Concrete Steps

In the orgs worktree, verify both source tips and the public destination
before importing. Fetch the public source into an explicit remote-tracking
ref, add it with `git subtree add --prefix=<temporary-prefix> <source-sha>`,
move mapped files into root locations, and inspect `git log` and the complete
diff. Use `git diff --check`, the orgs vendor checks while the snapshot
remains, and `nix flake check` after the harness-control flake moves. The
source flake currently expects its package at `./harness-control` and helpers
under `./skills/_shared`, so preserve those relationships.

In the orgs tracker worktree, fetch both public `ditz-metadata` heads, merge
with the orgs `.ditz/project.yaml` identity retained, then inspect all 57
IDs with the established `ditz` CLI and synchronize the metadata branch.
Do not hand-edit issue content.

In a new private dotfiles feature worktree, re-point the source reference,
adjust installer source messages and docs, run its local installer tests,
then exercise the installer with a scratch `HOME` and XDG/profile paths.
Check the resolved Claude and Codex skill links and the Nix store output
without modifying a live host.

## Validation and Acceptance

Phase 1: a reader can account for every source tree, collision, tracker ID,
and consumer path from this plan, and the private-public boundary is
explicit. Phase 2: the complete source history is reachable through the
orgs branch, all 57 existing issue IDs resolve, local Nix and script gates
pass on the exact draft PR heads, and a scratch-prefix install resolves
the expected skill links and harness-control store path. Phase 3: the CTO
authorizes cutover before any host link or archive action. Tier-drift's
separate publication approval precedes its first public commit.

## Idempotence and Recovery

The plan is additive. Each source import uses a pinned SHA and records a
merge parent, so `git merge-base --is-ancestor <source-sha> HEAD` detects an
already imported tip. A failed or interrupted import must be inspected and
reverted before retry; never replay it blindly. Tracker IDs are checked
before and after the branch merge. Host installation is rehearsed under a
scratch prefix; failure leaves active host links unchanged.

## Artifacts and Notes

The CTO received `CONSOL-ACK` and `CONSOL-NEEDS-RULING` with submitted
receipts. The latter was resolved to a distinct approval gate for
tier-drift publication. `CONSOL-CHECKPOINT-1` also has a submitted receipt.
The initial `nix flake check` on the unchanged moved source tree passed; a
second run on `17994ec` passed as well, including the package, unit, and
transport checks. `nix build --no-link --print-out-paths .#harness-control`
returned `/nix/store/a6akf7q8ryzqmcwig0z781r34n6lv04h-harness-control`.
The configuration test passed 21 cases, tmux-message and scaffold sync tests
passed, and the scoped setup-leak test passed 2 cases.
The scratch install cloned the imported orgs branch into an owned temporary
home, linked 25 Codex skills plus Claude's skills directory, preserved
Codex's `.system`, and installed without touching live host links.
The metadata merge `e92c5f3` has parents `2484ef2` and `449fc7a`. Its tree
contains 57 issue YAML files with 57 distinct IDs and the existing orgs
project identity; `ditz sync` succeeded and representative issues from both
sources resolved through `ditz show`.

## Interfaces and Dependencies

`orgs` and `agent-skills` are public; `dotfiles`, off-duty, tier-drift, and
the tier-drift archive are private as of this inventory. Public `orgs`
contains reusable code and process; private dotfiles owns installation and
machine-specific state. Installed skill paths, the config file schema,
`AGENT_SKILLS_ROOT`, and the stable MCP executable path remain interfaces.

Revision note (2026-10-29): opened the Phase 1 record, then completed the
source/consumer inventory and incorporated the CTO's tier-drift ruling.
Revision note (2026-10-29): recorded the Phase 2 source import, direct path
transition, and test-scope adjustment after the first gate runs.
Revision note (2026-10-29): recorded exact gate and PR evidence, plus recovery
from the unsafe default rebase attempt without changing the tested tree.
Revision note (2026-10-29): recorded the delivered tracker merge and private
installer draft before the review gate.
