---
name: retire-agent
description: Close out accepted agent work with a private resumable handoff and voluntary verified exit, or transfer the handoff to a fresh successor.
---

# retire-agent

Use this when a controller accepts finished lane work and initiates closeout,
or for an explicitly authorized retirement, waiting handoff, or migration.
Send personal thanks promptly, independently of this skill's success; the
offer and operational recovery are separate. A retained lane needs a named
authorized next mission or review dependency requiring its exact context,
with reason, owner and next event/checkpoint in the existing roster. A pause
does not resume its package.
A saved handoff and an ended agent process are separate receipts. Preserve
human input and leave a session open when either receipt cannot be established.
Read [the shard and recovery contract](references/protocol.md) before invoking
the script. Linux `/proc`, tmux, Git, Python 3.11+ and the installed spawn-agent
skill are required. Native verification loads the canonical sibling readers in
`../_shared/native/`, including the bounded Codex rollout reader; preserve the
installed skills tree layout. Claude requires the
installed `capture-session-state.sh` PreToolUse hook and its per-process pointer.
The sender must defer on an existing draft and guard typed Codex and literal
Claude exits. Configure `off_duty.path`, optional expected `off_duty.remote`, and
`doctrine.roles_path` in the [shared configuration](../_shared/configuration.md).
The generic handoff path is `<projects_root>/agent-handoffs`; the existing
repository must have a verified private `origin` with `master`. No remote is
invented or cloned.

The controller resolves the pinned peer's provider-native session ID before
sending the offer and supplies that ID with the assigned shard path. The agent
uses it in the shard without hunting for helpers or rediscovering identity.
The controller rechecks the binding before asking the sender to submit offer
or exit input.
A missing, changed or conflicting binding blocks input. Do not substitute
home-wide searches, `/nix/store` discovery, cwd, environment UUIDs or newest
rollout.
If the scripted path blocks, the controller keeps ownership of collection:
identify the failed assumption and protected invariant, use a bounded
alternative observation within authority, and record its receipt or blocker.
Retry only with new evidence, a changed hypothesis, or changed conditions.
Never bypass native identity, private recovery, human input, voluntary exit,
or process-end proof to make the procedure finish.

## Modes

- `scripts/retire.sh %PANE --retire`: quote Ted's
  [retirement offer](references/offer.md) verbatim, preserve its handoff,
  verify the private remote copy, then request exit.
- `scripts/retire.sh %PANE --waiting`: the same sequence, with the pending
  human decision and its owner named in the shard.

Offer the waiting-list message to **every** agent, including Utility. An agent
may decline or report DONE without leaving a shard. In either case the caller
writes the same operational shard with `author: "caller"`, a
`caller_authored` marker naming the lead and Ted's resume authority, and an
`exact_resume_command` as its last field. Use `declined: true` for a decline
or `no_agent_shard: true` for a reported DONE with no file. The controller
adds a `Caller-authored` INDEX row and syncs a dotfiles `retirements` issue
with the session ID, resume command, and private shard path before exit.
Honestly name the source and uncertainty.
Do not invent an agent's own-word thanks. Personal thanks are separate from
operational recovery. Off-duty is not authorization to resume product work.

## Migration

Follow the [authority and shard rules](../../doctrine/ROLES.md#handoff-and-migration-any-hat).
A CTO's own migration requires approval from `orgs-cto-self-migration-approver`. Before
any outgoing handoff push or exit, confirm that the requested successor
provider and model are supported, that the live identity can be verified
through the selected launch route, and that the sender supports a fresh
application receipt on that route. Confirm that `doctrine.roles_path`
resolves to the configured, readable `ROLES.md`. The published launcher
supports explicit model selection for Claude and Codex. Shared task
delivery for agy is unsupported. If any prerequisite fails, report the
migration blocker before the outgoing push or exit.

The legacy `retire.sh --handoff` wrapper is unsuitable for an approved
migration because it attaches the shard to the launch prompt before the
controller can verify the live successor. Use the separate
[identity-first launch](../spawn-agent/SKILL.md#named-lane-dispatch) without
a brief. Verify the live successor and fetch the approved private remote
afresh. Record the fetched commit SHA and compare the blob ID at the
assigned shard path in that commit with the shard blob hash recorded at
the outgoing push.

Build a new brief file in a directory accessible only to the controller.
Use this order and separate the three parts with two LF bytes each. Keep
the shard bytes intact.

1. The cold-start instruction below.
2. The shard bytes read directly from the verified fetched commit and
   assigned path using `git cat-file blob "$verified_commit:$shard_path"`.
3. The configured `ROLES.md` from `doctrine.roles_path`.

```text
Cold-start audit before action: Reconstruct state from this shard and committed artifacts alone. File any protocol defect first. Establish your identity and write your first durable record before acting.
```

Keep the brief private and unchanged from construction through delivery.
Pass that exact file to `tmux-message send "$pane_id" --prompt-file "$brief"`
on the pinned socket and verify its fresh receipt. Withhold the brief if
live identity or shard verification fails. Record the new owner before the
successor acts.

## Evidence and limits

Pin the explicit pane and verify its identity before each send. Use the shared
`tmux-message` sender for composer protection and new application receipts.
An ambiguous send never authorizes another paste. The sender observes input
twice eight seconds apart. Existing drafts defer the offer or exit. The
controller preserves the composer and returns to the pending handoff.
After a proven pre-input offer deferral, wait for the draft's owner to
reconcile it. Then resume the same handoff with
`--resume STATE --retry-deferred offer`. Ambiguous input requires observation
and disposition before proceeding.
Claude exit uses the shared `--literal-exit` guard and Codex exit uses
`--typed-command`.
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
After verified process exit, collect verified owned resources and empty
childless shells; distinguish a shell from the agent process and preserve any
active work or unknown child. Record collection receipts in the existing
owner record before marking the lane retired.

The wrapper directly `exec`s Python: pending or usage failure exits nonzero
(2), and only completed retirement exits zero. If piping output through `tail`
or another command, enable shell `pipefail` so the caller retains that status.
Use `--wait 1200` for a 10–20 minute shard; the maximum is 1800 seconds.
The script emits a private state path on failure. `scripts/retire.sh %PANE --resume PATH` continues
observation after a delivered offer, without resending it. After an observed
decline or a reported DONE with no shard, author the assigned shard then use
`scripts/retire.sh %PANE --resume PATH --caller-shard`.
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

`--stale-offer-draft` verifies pre-input offer deferral through the shared
sender. The fixture checks its own draft, clears it, then resumes the same
handoff with `--retry-deferred offer`. `--baseline-script` runs the original history-discovery
failure against real Codex before checking the repaired flow. Observation
continues with `--resume` after a delivered offer exhausts its first minute;
it never resends that offer. Run without Python optimization so assertions
remain enabled. SIGTERM unwinds the owned server cleanup.
