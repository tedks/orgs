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
   Scripts prefer a valid active `$TMUX` over file configuration; override with `SPAWN_TMUX_LABEL` or `SPAWN_TMUX_SOCKET`
   when operating from outside the intended server.
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
length, never its contents. Exception: a verified stable command-shaped draft
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
