---
name: spawn-agent
description: Spawn AI agents in steerable tmux windows for parallel or long-running work, including transcript-preserving Codex session forks with step-scoped compaction and structured final-recap handoffs. Use to spawn interactive agents, steer running tmux agents, or fork a Codex session for a separate step.
allowed-tools: Bash(~/.claude/skills/spawn-agent/scripts/*)
---

# spawn-agent

Launch interactive agents and send live messages through the shared tmux
interface. Use actual message text; files may carry large prompts or optional
supporting reports. Agents can receive steering between tool calls without
waiting for their turn to finish.

## Launch

1. Run `scripts/tmux-info.sh` from this skill to confirm the socket and targets.
   Read the [shared configuration](../_shared/configuration.md) for tmux and Codex defaults.
   Scripts prefer `$TMUX` only when its socket exists and the server answers a
   short probe; an unresponsive server falls through to the generic override
   and shared configuration. Per-call `SPAWN_TMUX_LABEL` or
   `SPAWN_TMUX_SOCKET` pins take precedence over the active server.
2. Use `scripts/agent-spawn.sh SESSION:WINDOW AGENT DIRECTORY [PROMPT]`.
   `AGENT` is `claude`, `codex`, or `agy`. For larger prompts pass
   `--prompt-file FILE`; the launcher preserves caller files.
3. Report the window, pane and socket. A successful task send confirms a new
   application receipt. If delivery fails, the child remains running: inspect
   the reported pane and reason before retrying; never blindly spawn again.

```bash
~/.claude/skills/spawn-agent/scripts/agent-spawn.sh \
  chaos:review codex ./project 'Review the auth module.'
~/.claude/skills/spawn-agent/scripts/agent-spawn.sh \
  chaos:review claude ./project --prompt-file /tmp/review-prompt
# Interactive start without a task is supported for every harness.
~/.claude/skills/spawn-agent/scripts/agent-spawn.sh chaos:helper agy ./project
```

Claude and Codex accept `--model MODEL` for an explicit model.
Codex also accepts `--codex-bin EXECUTABLE`, or environment
`SPAWN_CODEX_MODEL` / `SPAWN_CODEX_BIN`. Its startup update check is suppressed
for that process only. Codex launches use `--no-alt-screen` to preserve tmux
scrollback for receipts longer than the visible pane. Existing alternate-screen
sessions can accept a message yet hide its receipt; ambiguity never permits replay.
Claude `--trust` grants directory trust before launch;
read [Claude trust](references/claude-trust.md) when using it or diagnosing a
trust modal. Never answer a modal with a task's Enter.

### Named lane dispatch

Give each named operational lead, implementer or expressly requested audit
lane a named, interactive tmux window of its own. Use `scripts/tmux-info.sh`
to identify the project session. For ordinary dispatch, use its existing
session name in `SESSION:WINDOW` and choose a new window name. Create a tmux
session only when the request explicitly calls for a separate session or
the project has no existing session.

For example, with the `project` session already running, launch a new
`api-impl` window with the assigned worktree, requested model and brief.

```bash
scripts/agent-spawn.sh project:api-impl codex ./api-impl --model MODEL \
  --prompt-file /path/to/brief
```

Check that the reported live pane is in the chosen session and new window
on the reported socket. A different session or window is an identity
mismatch. Match the live provider, selected model and worktree to the
assignment. Track that identity evidence separately from the task's
existing transport receipt.

- For ordinary lanes, supply the brief in the combined launch as prompt text
  or with `--prompt-file` when you can establish both identity and delivery.
  Confirm the live identity and a fresh submitted or queued receipt before
  reporting successful dispatch. If identity is unverified or mismatched,
  report the assignment as unfulfilled and state the observed delivery
  outcome separately, even if the task has a receipt. Preserve the child
  and alert the accountable lead promptly to decide whether to steer or
  stop it.
- For migrations and explicit identity-first requests, launch without the
  brief, verify the live identity, then send the brief with `tmux-message`
  and verify its fresh receipt. Withhold the brief and alert the
  accountable lead if identity is unverified or mismatched. Record the
  brief as withheld.

If the requested launch is blocked, report the blocker. If a child exists
and a brief attempt has no fresh receipt, report the child with delivery
unconfirmed. Preserve and inspect any existing child in its window before
further action. Keep the original attempt for inspection without replaying
the task or launching a duplicate. Use the receipt from the actual brief.
Keep the window available for independent inspection and steering.

The same-provider council seat follows its native council route. The
assigning lead or operator can explicitly authorize a bounded internal helper
whose result attests only to its assigned task. Use the interactive route
above for named lanes and package ownership.

## Send and read

Use `tmux-message` for running-agent messages and pane reads. The installed
alias is `~/.bin/tmux-message`; the skill-local entrypoint is
`~/.claude/skills/spawn-agent/scripts/tmux-message.sh`.

```bash
tmux-message send chaos:review --typed-command /compact
tmux-message read chaos:review
tmux-message send chaos:review 'MSG-unique Please prioritize the failing test.'
# A file is a way to pass the actual task bytes, not a filename-only message.
tmux-message send chaos:review --prompt-file /tmp/task-prompt
```

`send` blocks until it observes a NEW submitted message or pending queue entry.
It compares the input before and after one paste, allows wrapped text and
collapsed paste markers, and makes at most one Enter-only recovery. Receipt is
acceptance, not completion of the task. Busy agent output can continue.

Observe the composer twice, one `--stable-window` apart (default: the
`--submit-delay`, normally eight seconds). Changing text or cursor returns
`human-typing`; use `--backoff --max-wait 60` for bounded waiting. An unchanged
draft is preserved: append a newline and the outgoing message, verify the
combined input, then submit both. Results record only the co-submitted draft
length, never its contents. A Claude composer containing `[Image #N]`, even
when the marker wraps across rows, defers as `image-placeholder`; the image is
opaque and must never be co-submitted. This check precedes command-draft
handling. Exception to co-submission: a verified stable command-shaped draft
is cleared without execution, then the outgoing message is sent only after
empty input is verified. Its context may pre-empt the command. Results include
`cleared_command_draft_length` after empty input is verified, and
`clear_attempted` whenever clearing was attempted, never draft contents.
Changing input, replay residue, modals and unsupported layouts still defer.
Claude Code status footers such as usage limits, auto-update errors, and
feedback-draft counts do not by themselves return `modal`. Delivery requires
the measured Claude composer frame at the cursor. Known dialogs return `modal`,
and unfamiliar Claude choice layouts defer as unknown input without paste or Enter.
For ordinary co-submission, the public sender supports measured Codex and
Claude append shapes: Codex's unchanged draft prefix plus one fresh Content
marker whose count covers the appended newline and payload; Claude's exact
draft prefix plus one fresh `[Pasted text #N +K lines]` marker whose K equals
one plus the payload newline count. Claude's transient `paste again to expand`
hint is ignored. Both require the same harness and verified end cursor. Claude
stable-draft co-submissions send Enter at most once and require a new receipt.
Other unsupported combined layouts remain closed.
Claude prompt suggestions are disabled fleet-wide; an ambiguous suggestion
frame retains the conservative probe. One pane lock serializes cooperating
senders; it cannot lock out human typing.

Use `--typed-command` for slash commands such as `/compact`, `/exit`, and
`/status`: these are literal keys,
with the same draft preservation and receipt checks. Claude may treat a pasted
slash command as ordinary text. This option accepts one single-line slash command and optional arguments; it
rejects control characters, newlines, leading whitespace, and ordinary prose.
Typed commands require an empty composer: appending them to a draft would
turn the command into ordinary message text. Ordinary stable drafts therefore defer
for command delivery; eligible command drafts are cleared first.

Results are JSON: exit 0 is `status=delivered` with a `submitted`, `queued`, or
`command` receipt. Exit 2 is deferred before paste; exit 3 is ambiguous after
paste may have occurred. Failure reports include `reason`, `pending_file`,
`pane` when resolved, and `needs_review`. The private file holds the actual
outgoing message; it is never automatically replayed.
For a future attempt explicitly selected for structural diagnosis, `send` accepts
`--diagnostic-file ABSOLUTE_NEW_PATH`. It records bounded, redacted composer
structure from that invocation's existing samples only. The parent directory
must exist, be owned by the caller, have mode 0700, and contain no symlink in
its path; the new file is mode 0600. The option is off by default and never
changes paste, Enter, receipt, or recovery behavior. The artifact is private
layout metadata, not an anonymous transcript; the caller owns its retention.
Do not treat a diagnostic from a later send as evidence of an earlier ambiguous
attempt. See [transport details](references/tmux-messaging.md) for fields and
failure behavior.
On a changed-footer Codex pane, a bold `›` row followed by a blank row and
indented text may be an archived unsent composer. It is not a delivery receipt.
`receipt-timeout` after an attempted paste means the message may have been
submitted; inspect the pane and do not repaste the pending file.
Claude can display a queued user row as a flush-left `❯` message followed by
`ctrl+x ctrl+s to send now`, above a busy spinner and its live composer. A
screen capture alone cannot establish that this row came from Claude rather
than a transcript copy. The sender therefore leaves this shape ambiguous.
The empty-composer hint `Press up to edit queued messages` and background-task
rows alone do not prove receipt. This measured frame can return
`mixed-input-after-paste` after one Enter. Inspect promptly: Claude may redraw
with little scrollback. Mark `delivered` only with independent new receipt
evidence, such as a later submitted `❯` row without the send-now hint or a
recognized `Messages to be submitted` block. An agent response attributable
to the exact message supports `acknowledged (transport ambiguous)`, and may
show task completion, but does not verify the sender's transport result. If
neither exists, leave delivery unconfirmed and preserve the pending payload.
Do not send another message just to obtain proof or replay the payload.

The scoped parser suite runs with
`nix develop --command bazel test //skills/spawn-agent:tmux_message_test`.

For `needs_review=true`, read the pane and inspect the reported stage. If a new
receipt is visible, record acceptance. If this attempt's paste is still in the
input, the operator permits deliberate Enter-only recovery based on sufficient evidence
including its collapsed paste marker. Preserve unrelated/mixed drafts and
modals. Do not repaste an ambiguous attempt. Return to other useful work when
human typing is the blocker; a model call is unnecessary for that case.

`read` shows 200 history rows plus the visible pane. No agent implementation,
transcript, native queue API, process registry or daemon is needed. Agy task
submission remains unsupported; interactive launch is available.
Read [transport details](references/tmux-messaging.md) for options, evidence
limits and extending screen recognition. The old `claude-send.sh` entrypoint
retains its legacy transport-only behavior; use `tmux-message` for confirmation.

## Fork and completion

For `codex --fork-session UUID`, read [Codex forks](references/codex-forks.md).
It preserves inherited context and optionally compacts it for one step. The
launcher sends both `/compact` and the assignment through `tmux-message`.
Fork ancestry and optional structured completion watching remain Codex-specific
helpers; they are not prerequisites for sending live messages.

Use a unique final-recap marker to distinguish completion from acceptance.
`codex-jsonl-watch.py recap` is an optional structured completion watcher for a
known Codex fork. Live steering and receipt checks use tmux. Do not wait for an
idle hook or final response before delivering a message to an empty composer.

## Other helpers

- `tmux-info.sh`: socket and target inventory.
- `claude-spawn.sh`: interactive Claude launch with resume/CLI arguments;
  use `tmux-message` afterward to send a task.
- `claude-trust-dir.sh`: inspect/grant workspace trust and verify trust behavior.
- `codex-rollout-path.sh`: optional fork preparation and completion metadata.
- [Reusable tools](references/reusable-tools.md): surrounding orchestration.

Claude retirement exits use `tmux-message send %PANE --literal-exit /exit` only
after a private handoff receipt. This types the slash command literally and
permits one Enter, then verifies a fresh shell resume notice. Process exit
remains a separate lifecycle receipt. Read the messaging reference for limits.
