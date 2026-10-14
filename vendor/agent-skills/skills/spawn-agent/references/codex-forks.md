# Fork one Codex step and hand back a recap

Use this workflow to keep the parent session at executive level while the user
can steer a context-rich child directly:

1. Choose a **new recap marker that has never appeared in the inherited
   conversation**.
2. End the child prompt with a contract requiring its last response to begin
   with that marker and recap decisions, changes, verification, and remaining
   work. State that the user may steer the child in tmux.
3. For a large inherited session, **use step-specific compaction by default**.
   Write a compact prompt that names the durable product decisions and current
   step state to preserve, and repetitive logs or obsolete launch attempts to
   discard. Omit compaction for a short parent or when verbatim history matters.
   The launcher combines this policy with the task automatically, so the
   compactor sees the assignment before it summarizes the inherited context.
4. Spawn `codex` with `--fork-session`, `--rollout-path-file`, and, when
   appropriate, `--compact-prompt-file`. This invokes interactive `codex fork`,
   not headless `codex exec fork`.
5. Report the window and socket immediately so the user can enter it.
6. Block with `codex-jsonl-watch.py recap` from the recorded byte cursor. It
   follows only complete JSONL records and emits only the whole matching final
   message. Do not poll or copy tmux scrollback and do not relay routine child
   messages through the parent.

```bash
set -e
step_dir=$(mktemp -d)
prompt_file="$step_dir/prompt"
compact_file="$step_dir/compact-prompt"
rollout_file="$step_dir/rollout-path"
cursor_file="$step_dir/recap-cursor"
startup_file="$step_dir/startup-cursor"
marker="STEP-1-7f3a DESIGN COMPLETE — EXECUTIVE RECAP"

{
cat <<'PROMPT_DELIM'
Design the requested system. The user may enter this tmux window and steer you.

Your LAST action must be a final response beginning exactly:
PROMPT_DELIM
printf '%s\n\n' "$marker"
cat <<'PROMPT_DELIM'

Include decisions, risks, verification, remaining work, and the recommended
next step. Do not merely point to files or prior messages.
PROMPT_DELIM
} > "$prompt_file"

cat > "$compact_file" <<'COMPACT_DELIM'
Preserve the product gestalt, settled architecture and UX decisions, current
repository/worktree state, active step goal, user steering, and recap contract.
Compress repeated terminal captures, superseded launch attempts, and other
operational noise that is not needed to complete this step.
COMPACT_DELIM

~/.claude/skills/spawn-agent/scripts/agent-spawn.sh \
  ide:design codex ./project \
  --fork-session "$PARENT_SESSION_ID" \
  --model "$CHILD_MODEL" \
  --compact-prompt-file "$compact_file" \
  --rollout-path-file "$rollout_file" \
  --recap-cursor-file "$cursor_file" \
  --startup-cursor-file "$startup_file" \
  --prompt-file "$prompt_file"

IFS= read -r rollout < "$rollout_file"
IFS= read -r recap_after < "$cursor_file"
~/.claude/skills/spawn-agent/scripts/codex-jsonl-watch.py recap \
  "$rollout" "$marker" 7200 --after-byte "$recap_after"
```

The fork is a snapshot taken when it starts. Later parent messages do not flow
into it; steer the child in its tmux window. Do not use `--resume`: resuming
would append to and contend with the parent instead of creating a child.

Set `PARENT_SESSION_ID` to the session you want to fork and `CHILD_MODEL` to
your chosen model (or omit `--model`). Use `--codex-bin` when the desired
installed executable is not the one on PATH.

Codex `/compact` accepts no inline argument. The launcher supplies the
step-specific policy **and task** through a private, process-local
`experimental_compact_prompt_file` config override, submits bare `/compact`,
and waits for a new compaction record (`context_compacted` on older releases,
`compacted` on Codex0.157.1). Both bare `/compact`
and the subsequent exact task go through `tmux-message send` to the stable child
pane. No native queue is used. The launcher verifies the fork's ancestry before
this optional fork workflow continues; ordinary messaging does not discover a
transcript.

A missing compaction event, vanished child, modal, or guarded transport failure
stops without another send. Inspect the existing pane before retrying. Rollout
and cursor files identify this fork and support optional completion watching;
they do not prove receipt. A successful launch reports `receipt unverified`.
Use `tmux-message read` to inspect a new exact user/pending row, then the unique
recap marker to distinguish eventual completion.

For supervised startup, `--startup-cursor-file` writes the existing pre-compaction
offset atomically as decimal bytes plus newline, mode 600. Pass
`"$step_dir/startup-cursor"` for Swarm's supervisor. It is distinct from
`recap-cursor`, which is recorded after compaction and before task delivery.
Use a fresh step directory for each launch; do not invent a receipt afterward
or treat its presence as proof that compaction or the assignment finished.

Fork tasks are snapshotted before launch so the same bytes inform compaction
and later delivery. They must be nonblank UTF-8, without control characters
except newlines, and under 32 KiB. Delivery preserves bytes; wrapped/collapsed
composers can remain unverifiable and stop with retained payloads. No queue
command or queue-version prerequisite applies.

The launcher creates its own mode-600 combined compaction file; the child shell
removes it when the child exits. Original caller files are never edited or
deleted. Keep the rollout/cursor files for your watcher, then remove `step_dir`
when finished. ROOT compaction and child compaction remain separate operations.
