---
name: spawn-agent
description: Spawn AI agents in tmux windows for parallel/interactive work
argument-hint: <session:window> <agent> [directory] [prompt]
allowed-tools: Bash(~/.claude/skills/spawn-agent/scripts/*)
---

<!-- Codex reads this same file through the .codex/skills/<name> symlink, so the
     paths below assume install-claude-config ran. Never copy this file into
     .codex/skills -- see the skills comment in scripts/install/install-codex-config. -->

# spawn-agent

Spawn AI agents in tmux windows for interactive, parallel work. Use this for
fan-out workflows where you want multiple agents working simultaneously.

## Usage

```
/spawn-agent <session:window> <agent> [directory] [prompt]
```

## Arguments

- `<session:window>`: tmux target (e.g., `chaos:review`)
- `<agent>`: The agent to spawn (`claude`, `codex`, `agy`)
- `[directory]`: Working directory (default: current)
- `[prompt]`: Initial prompt for the agent

## Instructions

When this skill is invoked, perform these steps:

### 1. Validate environment

Run: `test -n "$TMUX" && echo "in-tmux" || echo "not-in-tmux"`

If not in tmux, report error and stop:
> Error: Not running inside tmux. This skill requires a tmux session.

### 2. Check tmux context

Run `~/.claude/skills/spawn-agent/scripts/tmux-info.sh` to see the current
socket, sessions, and windows. This ensures you're targeting the right server.

### 3. Spawn the agent

**Always pass the prompt via a temp file** to avoid ARG_MAX errors:

```bash
# 1. Write prompt to a temp file
prompt_file=$(mktemp /tmp/spawn-agent-prompt.XXXXXX)
cat << 'PROMPT_DELIM' > "$prompt_file"
<your prompt here>
PROMPT_DELIM

# 2. Spawn with --prompt-file
~/.claude/skills/spawn-agent/scripts/agent-spawn.sh <session:window> <agent> [directory] --prompt-file "$prompt_file"
# Note: the script cleans up its own temp files; caller-provided files are preserved
rm -f "$prompt_file"
```

For short prompts, inline is also fine:

```bash
~/.claude/skills/spawn-agent/scripts/agent-spawn.sh <session:window> <agent> [directory] [prompt]
```

The script automatically detects the tmux socket from `$TMUX` -- no manual
`-L` or `-S` flags needed.

### 4. Report success

Tell the user:
- The tmux window name and session
- Which tmux socket/server is being used
- How to switch to it: `Ctrl-b <window-number>` or `tmux select-window -t <name>`

## tmux Socket Awareness

All scripts automatically detect the current tmux server socket from `$TMUX`.
If you're in `tmux -L personal`, spawned agents will be in the same server.

**How it works:**
- `$TMUX` contains `/path/to/socket,pid,pane` when inside tmux
- Scripts extract the socket path and use `tmux -S <path>` for all commands
- Falls back to the default socket when not inside tmux

**Override manually** (rarely needed):
```bash
# By socket path
SPAWN_TMUX_SOCKET=/tmp/tmux-1000/personal ~/.claude/skills/spawn-agent/scripts/agent-spawn.sh ...

# By -L label
SPAWN_TMUX_LABEL=personal ~/.claude/skills/spawn-agent/scripts/agent-spawn.sh ...
```

**Quick diagnostic:**
```bash
~/.claude/skills/spawn-agent/scripts/tmux-info.sh
```
This prints the current socket, server PID, all sessions, and all windows.

## Examples

```bash
# Spawn Claude to review code
/spawn-agent chaos:review claude ./project "Review the auth module"

# Spawn Codex for a different perspective
/spawn-agent chaos:codex-review codex ./project "Help refactor this"

# Spawn agy (Antigravity CLI)
/spawn-agent chaos:agy-review agy ./project "Check this design"

# Spawn without initial prompt (interactive from start)
/spawn-agent chaos:helper claude .
```

## Helper Scripts

All scripts source `tmux-ctx.sh` for automatic socket detection.

### tmux-info.sh

Show current tmux context -- socket, sessions, windows:
```bash
~/.claude/skills/spawn-agent/scripts/tmux-info.sh
```

### agent-spawn.sh

Spawn any supported agent:
```bash
~/.claude/skills/spawn-agent/scripts/agent-spawn.sh <session:window> <agent> [directory] [prompt]
~/.claude/skills/spawn-agent/scripts/agent-spawn.sh <session:window> <agent> [directory] --prompt-file <file>
```

### claude-spawn.sh

Claude-specific spawner with additional options:
```bash
~/.claude/skills/spawn-agent/scripts/claude-spawn.sh <session:window-name> [directory] [claude-args...]

# Examples:
~/.claude/skills/spawn-agent/scripts/claude-spawn.sh chaos:review . --resume abc123  # Resume session
```

### claude-send.sh

Send a message to a running Claude instance:
```bash
~/.claude/skills/spawn-agent/scripts/claude-send.sh <window> <message>
~/.claude/skills/spawn-agent/scripts/claude-send.sh <window> --prompt-file <file>

# Example:
~/.claude/skills/spawn-agent/scripts/claude-send.sh chaos:review "run the tests"
```

Uses tmux load-buffer/paste-buffer for the message body (avoids ARG_MAX),
then sends Enter with a 1.5 second delay to avoid the swallowed-Enter issue.

## Detecting Idle State

Claude Code has an `idle_prompt` notification hook that fires after 60+ seconds
of waiting for user input. To detect when agents are ready:

1. Configure an `idle_prompt` hook in `.claude/settings.json`:
   ```json
   {
     "hooks": {
       "idle_prompt": [{
         "matcher": "",
         "hooks": [{
           "type": "command",
           "command": "touch /tmp/claude-ready-$CLAUDE_SESSION_ID"
         }]
       }]
     }
   }
   ```

2. Check for ready files: `ls /tmp/claude-ready-* 2>/dev/null`

3. Clear after sending: `rm -f /tmp/claude-ready-$session_id`

## Notes

- Agents run interactively in tmux windows
- Use `tmux-info.sh` to see all sessions and windows on the current server
- Use claude-send.sh to send messages to running agents
- Socket detection is automatic -- you don't need to think about `-L` or `-S`
- Prompts are passed via temp files to avoid ARG_MAX limits

## agy and the workspace trust prompt

The **first** interactive `agy` in a directory it has not been trusted with
opens a modal before the composer exists:

```
Do you trust the contents of this project?

Antigravity CLI requires permission to read, edit, and execute files here.

> Yes, I trust this folder
  No, exit

  ↑/↓ Navigate · enter Confirm
```

The default button is *Yes* and the footer is *enter Confirm*, so a blind
`Enter` grants trust — and answering it writes the directory into
`trustedWorkspaces` in `~/.gemini/antigravity-cli/settings.json`, permanently.

**The spawner never answers it.** When that modal is on screen the spawn fails
immediately, having sent no keystroke at all, and tells you to answer it
yourself. Granting a coding agent read/edit/execute over a directory is an
operator decision, not something a script should make on your behalf while you
are looking elsewhere.

So: attach to the session, answer the prompt, then re-run the spawn.

This is also why the readiness check waits for the composer *specifically* — its
rule line **and** its `? for shortcuts` hint — rather than for any box-drawing
character. The banner draws rules before the input box is live, and the modal
draws none at all; matching on rules alone pasted into whatever happened to be
on screen.
