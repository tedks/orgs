---
name: retire-agent
description: Preserve a private, resumable agent handoff and verify a polite exit, or transfer the handoff to a freshly spawned successor.
---

# retire-agent

Use this for an explicitly authorized retirement, waiting handoff, or migration.
A saved handoff and an ended agent process are separate receipts. Preserve
human input and leave a session open when either receipt cannot be established.
Read [the shard and recovery contract](references/protocol.md) before invoking
the script. Linux `/proc`, tmux, Git, Python 3.11+ and the installed spawn-agent
skill are required. Native verification loads the canonical sibling readers in
`../_shared/native/`, including the bounded Codex rollout reader; preserve the
installed skills tree layout. Claude requires the
installed `capture-session-state.sh` PreToolUse hook and its per-process pointer.
The sender must provide stable ordinary draft co-submission and guarded typed
Codex / literal Claude exits. Configure `off_duty.path`, optional expected `off_duty.remote`, and
`doctrine.roles_path` in the [shared configuration](../_shared/configuration.md).
The generic handoff path is `<projects_root>/agent-handoffs`; the existing
repository must have a verified private `origin` with `master`. No remote is
invented or cloned. Handoff mode requires a configured roles file or `--roles`.

The controller resolves the pinned peer's provider-native session ID before
sending the offer and supplies that ID with the assigned shard path. The agent
uses it in the shard without hunting for helpers or rediscovering identity.
The controller rechecks the binding before asking the sender to submit offer
or exit input.
A missing, changed or conflicting binding blocks input. Do not substitute
home-wide searches, `/nix/store` discovery, cwd, environment UUIDs or newest
rollout.

## Modes

- `scripts/retire.sh %PANE --retire`: thank the agent, preserve its handoff,
  verify the private remote copy, then request exit.
- `scripts/retire.sh %PANE --waiting`: the same sequence, with the pending
  human decision and its owner named in the shard.
- `scripts/retire.sh %PANE --handoff AGENT MODEL`: retire, then spawn a fresh
  successor through spawn-agent's published launcher. Its brief is the shard
  plus the orgs doctrine's ROLES.md. Reconstruct state from artifacts alone
  and write the first durable record before acting.

Offer thanks and off-duty time to **every** agent, including Utility. An agent
may decline; the caller then writes the same operational shard with `author:
"caller"` and `declined: true`, honestly naming the source and uncertainty.
Do not invent an agent's own-word thanks. Personal thanks are separate from
operational recovery. Off-duty is not authorization to resume product work.

The published launcher supports explicit model selection for Claude and
Codex. agy model-specific handoffs fail before retirement because its shared
task delivery is unsupported; do not improvise a second spawn mechanism.

## Evidence and limits

Pin the explicit pane and verify its identity before each send. Use the shared
`tmux-message` sender for composer protection and new application receipts.
An ambiguous send never authorizes another paste. The sender observes input
twice eight seconds apart and co-submits ordinary stable drafts with the offer;
a stable command-shaped draft follows its published clear-and-verify exception.
Claude exit uses the shared `--literal-exit` guard; Codex exit uses
`--typed-command`. Both require an empty composer and defer for ordinary drafts.
Changing input, a modal, missing evidence, or changed process identity defers
retirement.

Shards belong only in a private repository. Preserve one file per session,
serialize publication, and use the shared `offduty-push.sh` helper from a
private event staging directory; it commits from a temporary worktree at
fetched `origin/master`, never from the shared checkout. Verify the shard
on fetched `origin/master` before recording its receipt and requesting exit.
Keep operational recovery separate
from personal thanks. A provider-native resume handle comes last and must not
be required to reconstruct the work.

Record attempts privately without storing pane contents or unfinished human
text. Before offer, bind the selected peer to its native session UUID. Before
exit, match the immutable shard UUID to that offered ID and the pinned process:
Codex uses its unique writable CLI rollout descriptor, which only a session
running in its own process holds (not a client of the app-server daemon); Claude uses its
per-process session pointer with start/boot identity. Missing or conflicting
bindings leave the handoff pending without exit input. Verify all pinned
original processes ended and a fresh native resume notice
names the immutable shard's same session UUID; an exit transport result alone is
insufficient. Never kill a session. Do not stop unrelated services or delete
worktrees, branches, transcripts, or another actor's files.

The wrapper directly `exec`s Python: pending or usage failure exits nonzero
(2), and only completed retirement exits zero. If piping output through `tail`
or another command, enable shell `pipefail` so the caller retains that status.
Use `--wait 1200` for a 10–20 minute shard; the maximum is 1800 seconds.
The script emits a private state path on failure. `scripts/retire.sh %PANE --resume PATH` continues
observation after a delivered offer, without resending it. After an observed
decline, author the assigned shard then use `scripts/retire.sh %PANE --resume PATH --caller-shard`.
Only a proven pre-paste deferral permits `scripts/retire.sh %PANE --resume PATH --retry-deferred offer`
(or `exit`). An ambiguous offer with a pinned positive paste and Enter can be
observed on `scripts/retire.sh %PANE --resume PATH` without replay: only a final assistant
`RETIRE-DONE` or `RETIRE-DECLINED` for that exact event advances disposition.
The sender result remains ambiguous; absent or unsupported completion stays
pending. Ambiguous exit attempts still require the independent native notice
and original-process end, never another blind command.
There is no automatic manual relay or ambiguous-send override.

Private state records and exact outgoing payloads live under the private
repository's Git common directory, not public session records. Do not copy
them into public issues or PRs. Screens are heuristic: this cannot atomically
exclude human typing, audit the truth of recovery prose, or independently
prove a resource owner's release claim.

## Repair verification

Keep handles for running exec calls until they complete or are deliberately
stopped. A yielded output chunk is not process completion. Before claiming
resource release, identify owned descendants and verify their actual exit or
accepted transfer; parent-shell exit alone is insufficient. Stop only verified
owned processes, and record pending or unknown descendants as blockers.

Run `scripts/test-retire.py` and `scripts/test-mutations.py` for isolated
behavior and guard-removal tests. Set `RETIRE_TEST_SHARED_SCRIPTS` to the
published spawn-agent `scripts` directory to verify a dependency checkout;
the default is this checkout's sibling spawn-agent. The binding readers'
standalone suites live under `../_shared/native/tests/`; run each `test-*.py`
with Python, plus `--mutation-check`. Dotfiles' MCP wiring tests remain in
that repository and require the MCP SDK.
Run `python3 ../_shared/test-offduty-push.py` for the bare-remote push and
non-fast-forward retry contract. The shared-checkout repair procedure is in
[README.md](README.md).

`scripts/test-retire-native.py` is an opt-in model-token test. Pass `--worktree`
naming an exclusively owned, clean disposable Git directory, `--evidence`
naming a new private directory, and `--shared-skill` naming the published
spawn-agent installation. The cwd must be separate from the skill's source
worktree. Use `--preflight-only` for read-only validation without evidence or
model launches. The launcher grants Claude trust only to that exact disposable
cwd. Codex
receives an exact-cwd project trust table through its documented per-process
`-c` option via the launcher's `--codex-bin` wrapper; no global config is written.
The test compares cwd HEAD/status/tracked diff on success and failure, samples
fresh exit notices, checks the actual local bare remote, and releases its owned
server. These checks do not provide an OS sandbox or prove absence of writes
elsewhere: real agents retain normal host access. The rehearsal prompt permits
only assigned identity/shard files and forbids live publication or pane control.
Artifacts are retained for inspection; source/shared heads and dirty state are
recorded separately as fidelity evidence.

`--stale-offer-draft` also exercises ordinary draft co-submission through the
published sender. `--baseline-script` runs the original history-discovery
failure against real Codex before checking the repaired flow. Observation
continues with `--resume` after a delivered offer exhausts its first minute;
it never resends that offer. Run without Python optimization so assertions
remain enabled. SIGTERM unwinds the owned server cleanup.
