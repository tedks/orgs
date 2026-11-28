# Usage tooling migration: dotfiles to Orgs

Status: draft spec, 2026-11-28. Nothing here is merged or enabled on any host.
Authority: requested by the CEO through the dotfiles coordinator. Every step
that changes what a host runs needs the dotfiles owner's go and the CEO's.

## Overview

The usage tooling is the code that counts tokens per agent session, reads
provider quota meters, raises the token tripwire and, once two in-review
changes land, serves the quota snapshot. It lives in the private dotfiles
repository under `scripts/usage/`. Orgs already depends on it: the `usage`
skill, `harness-control`'s `get_usage`, the quota-reset monitor and the
doctrine's task-boundary ritual all read its CLI.

This spec moves the implementation into Orgs and leaves dotfiles as the
install layer, the split the search guard already uses: Orgs owns the code
under `skills/_shared/`, dotfiles keeps the installed entry points and the
installers.

### Assumptions

- Orgs is a public repository and so is the frontend repository that owns
  the quota contract. dotfiles is private. Anything pushed to an Orgs branch
  is published, including a draft pull request's commits, and cannot be
  recalled by deleting the branch.
- Hosts reach Orgs code through the managed skills view at
  `~/.claude/skills`, whose `_shared` entry resolves to the Orgs checkout the
  host's installer validated.
- `~/.bin/token-*` are symlinks to files in the dotfiles checkout. Pulling
  dotfiles therefore changes what those names run with no installer step in
  between.
- `harness-control` runs with `AGENT_SKILLS_ROOT` set to a pinned copy of
  `skills/_shared` from the revision it was built from, not the host's
  checkout.
- The tools are Python 3.11+ standard library only and stay that way.
- The on-disk store and the config file are machine-owned and do not move.
  The store has one format, read and written by both copies during the
  migration.

## Goals and Non-goals

Goals:

1. One implementation of `token-usage`, `token-tripwire` and
   `token-calibrate`, including the quota service, owned and tested in Orgs.
   On a host, every caller runs the same copy.
2. No observable change for any consumer at cutover: same command names on
   `PATH` and in `~/.bin`, same subcommands, flags, output and exit codes,
   same config and state paths, same cron row and unit behaviour.
3. Nothing private is published: no real session, request or rollout ids,
   hostnames, user names, home paths, project or worktree names, pane ids,
   or figures measured on a real host, in any pushed commit.
4. A host can be switched back to the dotfiles copy by one installer run,
   with no store migration in either direction, until the dotfiles copy is
   removed.
5. The in-review quota-service work lands where it is being reviewed and is
   imported at its merged head. It is not restarted or rebased onto this
   move.

Non-goals:

- No behaviour change, refactor, rename or new feature in the moved code,
  except the `paths` subcommand named below, which lands in dotfiles before
  the import.
- No Nix packaging of the tools.
- The Sui usage analyzers (`sui_*`) do not move.
- Installers, the cron row, the systemd unit file, the adapters list, the
  installer's ownership records, the machine config and the state store stay
  in dotfiles.
- The quota contract (`quota-snapshot/1`, `quota-observation/1`) is not
  changed. The frontend repository stays its owner.
- Git history of `scripts/usage` is not carried over.

## Firewalled Entities and Contract Boundaries

| Entity | Repository | Owns |
|---|---|---|
| Usage implementation | Orgs, `skills/_shared/usage/` | `token_usage.py`, `tripwire.py`, `calibrate.py`, `quota_service.py`, the vendored `quota_contract.py`, tests, synthetic fixtures, README |
| Install layer | dotfiles | the three entry-point proxies; the activation step that points `~/.bin/token-*` at them; `install-token-tripwire`, `install-quota-service`, the cron row, the `token-usage-serve` unit; machine config and store |
| Quota contract | frontend repository | the canonical validator, its tests and fixtures for `quota-snapshot/1` and `quota-observation/1` |
| Consumers | Orgs, dotfiles, frontend | `usage` skill, `harness-control` `get_usage`, quota-reset monitor; `npm-ai-update`, the cron row, the unit; the desktop frontends |

Boundaries:

- **`usage-cli`** ([contract](../../contracts/usage-cli.md)): the usage
  implementation provides the command line; every consumer depends on it and
  on nothing else. Consumers never import the modules or read the store.
- **`usage-install-layout`**
  ([contract](../../contracts/usage-install-layout.md)): what the install
  layer may assume about the implementation's files, and what it must
  guarantee about activation.
- **Quota contract** (external, existing): between the quota service inside
  the implementation and the frontends, for both `token-usage snapshot` and
  the `serve` socket. Orgs carries the frontend's validator, its copied tests
  and fixtures unchanged, pinned by digest
  `afac23cacb98c580d15999f314a82ffcb8ef858c649a2296703471a24d1f1e52`. A
  contract change is made in the frontend repository first and re-vendored.

### Decisions

- **Location.** `skills/_shared/usage/`. The `usage` skill stays a CLI
  consumer and does not import from it.
- **Pulling dotfiles activates nothing.** The cutover change adds the
  proxies at new paths in dotfiles and leaves the existing `.bin/token-*`
  entries untouched. A host switches only when its installer runs the
  activation step. How dotfiles lays this out is the install layer's design;
  the invariant is in the layout contract.
- **Activation is validated, ordered and reversible.** Before switching, the
  installer checks the host's Orgs checkout: the three entry points are
  executable, their program files are byte-identical to the dotfiles copy,
  and `paths` answers with the expected schema. It then stops the serve unit
  if enabled, repoints the three `~/.bin` names, restarts the unit and checks
  the result. The same step with the source set to dotfiles switches back.
- **One copy per host.** The proxies resolve
  `${TOKEN_USAGE_IMPL:-$HOME/.claude/skills/_shared/usage}`. They do not use
  `AGENT_SKILLS_ROOT`, so `harness-control` runs the host's copy rather than
  its own pinned one.
- **Fail closed.** A proxy whose target is missing prints one line naming the
  path and the remedy and exits 127. No fallback implementation. The serve
  unit must not restart-loop on that status, and a caller that tests only for
  the command's existence must also check its exit status; both are install
  layer changes in the cutover.
- **`token-usage paths`.** `install-token-tripwire` and
  `install-quota-service` import `token_usage` to learn the state directory.
  A read-only subcommand replaces those imports. It lands in dotfiles before
  the import, so both copies have it, the installers' tests keep running
  against the dotfiles copy, and the two copies stay byte-identical.
- **Program files are byte-identical; everything else is audited.** The five
  program files are copied unchanged if the publication audit finds nothing
  private in them. If it finds something, the fix lands in dotfiles first and
  the import is taken from the later commit. The vendored contract validator,
  its copied tests and its fixtures are also unchanged. README, the other
  tests and all other fixtures are rewritten or rebuilt for publication.
- **Publication audit, a named gate (M2a).** Described under Milestones.
- **Both copies are frozen** from the import commit until the dotfiles copy
  is removed. A fix lands in dotfiles, is ported to Orgs unchanged, and the
  pairing is recorded. Activation refuses a host whose copies differ.
- **Gates.** The unit suites and the quota suites become Bazel targets under
  `skills/_shared/usage/` and join `//:portable_tools_test`. The mutation
  checks `tests/mutate_tripwire.py` and `tests/mutate_calibrate.py` are
  separate targets; each must report every mutant killed at the import
  commit and whenever a guard changes.

## Boundary Diagram

```mermaid
graph LR
  subgraph Orgs
    IMPL["usage implementation<br/>skills/_shared/usage"]
    SK["usage skill"]
    HC["harness-control get_usage"]
    QR["quota-reset monitor"]
  end
  subgraph dotfiles
    PX["proxies + activation"]
    INST["installers"]
    CRON["cron row"]
    UNIT["serve unit"]
    NPM["npm-ai-update"]
  end
  subgraph frontend
    CT["quota contract (canonical)"]
    FE["desktop frontends"]
  end
  STORE[("machine config and store")]
  IMPL -- "usage-cli" --> SK
  IMPL -- "usage-cli" --> HC
  IMPL -- "usage-cli" --> QR
  IMPL -- "usage-cli" --> NPM
  IMPL -- "usage-cli" --> CRON
  IMPL -- "usage-cli" --> UNIT
  IMPL -- "usage-cli (paths)" --> INST
  IMPL -- "quota contract: snapshot, serve socket" --> FE
  CT -- "vendored, digest-pinned" --> IMPL
  IMPL -- "usage-install-layout" --> PX
  PX -. "route: ~/.bin names" .-> IMPL
  IMPL --- STORE
```

Solid edges point from provider to consumer and are labelled with the
contract. The dotted edge is the invocation route: every consumer reaches the
implementation through the `~/.bin` names or `PATH`, which the install layer
points at the proxies.

## Interpretations Log

None yet.

## Milestones

Owners are named. "Go" means the dotfiles owner's and the CEO's explicit
approval. Only M3 activation and M5 change what a host runs.

- **M0. Spec.** This document and its contracts, CLEAN at a formal council
  round. Owner: Orgs.
- **M1. Quota service lands in dotfiles.** The two in-review pull requests,
  both merged. Owner: dotfiles. If either is abandoned or changed in scope,
  the migration stops here and returns to the dotfiles owner and the CEO; no
  partial baseline is imported.
- **M1b. `paths` lands in dotfiles.** `token-usage paths` as the CLI
  contract defines it, with tests; `install-token-tripwire` and
  `install-quota-service` call it instead of importing. Owner: dotfiles,
  drafted by Orgs on request. Acceptance: installer tests pass; `paths`
  output equals what the import returned on the same environment for each
  config-precedence case; no other output changes.
- **M2a. Publication audit.** Owner: Orgs, with the dotfiles owner's
  sign-off. Done on a local staging tree before anything is pushed to Orgs.
  1. An export inventory lists every file at the import commit with one of:
     copy unchanged, rewrite, rebuild, exclude. The dotfiles owner approves
     it.
  2. Text files marked rewrite are rewritten; the two count fixtures are
     rebuilt from synthetic transcripts with generated ids, synthetic home
     paths and neutral project names, and tests that assert their totals are
     updated. The generator that reads a host's real transcripts is excluded.
  3. A guard scans every file of the staged tree, decompressing compressed
     files, for: UUIDs and request and rollout ids not on a list of
     synthetic ids; `/home/` paths other than the listed synthetic ones;
     hostnames, user names, project and worktree names from a deny list that
     is kept outside Orgs and supplied at run time; pane ids. It runs on
     every commit of the import branch, locally, before the first push.
  4. A fresh reviewer at the Lead tier, with access to both trees, reads the
     staged tree and the guard's output and returns a verdict on publication
     alone. The foreign council seats cannot see the private tree and do not
     substitute for this reviewer.
  5. The audit record (inventory, guard output, reviewer verdict, the
     dotfiles owner's sign-off) is kept privately; the pull request states
     only that the gate passed and at which staged commit.
  Acceptance: zero guard hits, reviewer CLEAN, sign-off recorded. A hit in a
  program file is fixed in dotfiles and the audit restarts from the new
  commit.
- **M2. Import into Orgs.** The audited tree becomes one Orgs pull request.
  Owner: Orgs. Acceptance: the M2a record names the pushed commits; program
  files and the vendored contract files compare equal to the import commit,
  shown by a comparison script's output; all suites and both mutation checks
  pass; a consumer-driven test feeds the real `posture --no-scan --json` and
  `meters --check --json` output on the synthetic store through
  `harness-control`'s validator and the quota-reset monitor's parser; each
  entry point runs by absolute path through a symlinked directory from an
  unrelated working directory. No host changes. Revert is safe only while no
  host is activated.
- **M3. Cutover.** Owner: dotfiles; Orgs drafts on request. One dotfiles
  pull request: the proxies at new paths, the activation step, the unit and
  `npm-ai-update` changes named under Decisions, the installer tests.
  Merging it changes no host. Then, per host and only with the go:
  1. Update the host's Orgs checkout to a revision containing M2; rebuild
     `harness-control` if the host has it.
  2. Run the activation step. It refuses, changing nothing, unless the
     validation under Decisions passes.
  3. Evidence, recorded per host in the dotfiles owner's host inventory:
     the three `~/.bin` names resolve to the proxies; `token-usage paths`,
     `snapshot --no-scan` and `token-tripwire status` exit 0 through them;
     the next cron tick exits 0, shown by the store's state advancing and no
     new error line in the cron log; where enabled, the unit is active after
     its restart with its restart count unchanged afterwards and answers a
     snapshot request with a valid object; `get_usage` returns a posture.
  Switching back is the same step with the source set to dotfiles, followed
  by the same evidence. A partial failure leaves the activation step's
  record of which names it switched; rerunning it in either direction
  completes or undoes them.
- **M4. Documents.** No behaviour. Orgs owner: `skills/usage/SKILL.md`, the
  role checklist's wording, the planning note that says the scripts stay in
  dotfiles. Frontend owner: the "where the code lives" section of its spec.
  dotfiles owner: its agent instructions' pointer to the usage README.
  Acceptance: each names the shipped layout.
- **M5. Remove the dotfiles copy.** Owner: dotfiles, with the go. Requires:
  the host inventory shows every host, including ones that were offline,
  activated with M3 evidence and at least one weekly quota window since with
  no switch back; the dotfiles commit that still holds the copy is recorded
  as the recovery revision; restoring from it and switching one host back
  has been rehearsed. Removes the program files, their tests, the Bazel
  exports of them and the installer tests' dependence on them, and the
  activation step's comparison. Does not remove the proxies, installers, the
  unit file or anything an enabled host links.

**The two-copy window (M2 to M5).** The dotfiles owner approves any fix; the
Orgs owner ports it in the same change set; the Orgs tracker issue for this
migration records each pair of commits. Changes to the installers, the unit
or the vendored contract in that window are checked against both copies
before they merge. The activation step's comparison enforces the pairing on
every host at every run.

Stop conditions: a consumer-visible difference at any milestone; a guard hit
or reviewer finding that cannot be fixed in dotfiles; private data found in a
pushed Orgs commit (stop all pushes, report to the CEO at once; the remedy is
removal of the commits and the pull request's refs by the hosting provider,
and the data is treated as disclosed); the go withheld.

## Open Questions

1. **Which hosts activate, in what order, and when.** Decides: dotfiles
   owner with the CEO. Blocks: M3 activation only.
2. **Soak length before M5.** This spec says one weekly quota window.
   Decides: dotfiles owner. Blocks: M5 only.
