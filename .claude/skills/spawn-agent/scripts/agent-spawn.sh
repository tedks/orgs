#!/bin/bash
# agent-spawn.sh - Spawn an AI agent in a tmux window (interactive mode)
#
# Usage: agent-spawn.sh <session:window> <agent> [directory] [prompt]
#        agent-spawn.sh <session:window> <agent> [directory] --prompt-file <file>
#
# Agents: claude, codex, agy (Antigravity CLI)
#
# Options:
#   -f, --prompt-file <file>   Read prompt from file (avoids ARG_MAX)
#
# Automatically targets the correct tmux server socket when run inside tmux.
# Override with SPAWN_TMUX_SOCKET or SPAWN_TMUX_LABEL env vars.
#
# The prompt is delivered via tmux load-buffer/paste-buffer after the agent
# starts, so it never appears in any execve(2) argument list.
#
# Examples:
#   agent-spawn.sh chaos:review claude ./project "Review auth module"
#   agent-spawn.sh chaos:codex-help codex . "Help me refactor this"
#   agent-spawn.sh chaos:review claude ./project --prompt-file /tmp/prompt.txt
#   agent-spawn.sh chaos:review claude --prompt-file /tmp/prompt.txt

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"

usage() {
    echo "Usage: agent-spawn.sh <session:window> <agent> [directory] [prompt]" >&2
    echo "       agent-spawn.sh <session:window> <agent> [directory] --prompt-file <file>" >&2
    echo "  session:window: tmux target (e.g., 'chaos:review')" >&2
    echo "  agent: claude, codex, agy" >&2
    echo "  directory: working directory (default: current)" >&2
    echo "  prompt: initial prompt for the agent" >&2
    echo "  --prompt-file: read prompt from file (avoids ARG_MAX)" >&2
    exit 1
}

if [[ $# -lt 2 ]]; then
    usage
fi

target="$1"
agent="$2"
shift 2

# Parse remaining args: [directory] [prompt] or --prompt-file <file>
# --prompt-file can appear anywhere in the remaining args.
prompt_file=""
prompt=""
directory="."
_cleanup_prompt_file=""

# Trap to clean up temp files on exit/interrupt (only files we created).
# Set early so failure paths during parsing don't leak temp files.
# An EXIT trap's status BECOMES the script's, so cleanup must be unable to
# fail. Without `return 0` every no-prompt spawn -- where the guard is simply
# false -- reported failure after succeeding; without `|| true` a failing rm
# would kill the trap under `set -e` before it got there.
cleanup() {
    if [[ -n "$_cleanup_prompt_file" ]]; then rm -f "$_cleanup_prompt_file" || true; fi
    return 0
}
trap cleanup EXIT

positional=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt-file|-f)
            prompt_file="$2"
            if [[ -z "$prompt_file" ]]; then
                echo "Error: --prompt-file requires a file path" >&2
                exit 1
            fi
            if [[ ! -f "$prompt_file" ]]; then
                echo "Error: prompt file not found: $prompt_file" >&2
                exit 1
            fi
            shift 2
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

# Positional args: [directory] [prompt]
if [[ ${#positional[@]} -ge 1 ]]; then
    directory="${positional[0]}"
fi
if [[ ${#positional[@]} -ge 2 ]]; then
    prompt="${positional[1]}"
fi

# Parse session and window from target
session="${target%%:*}"
window="${target#*:}"

# Validate agent
case "$agent" in
    claude|codex|agy) ;;
    *)
        echo "Unknown agent: $agent" >&2
        echo "Supported agents: claude, codex, agy" >&2
        exit 1
        ;;
esac

# Ensure session exists
if ! "${TMUX_CMD[@]}" has-session -t "$session" 2>/dev/null; then
    echo "Creating tmux session: $session" >&2
    "${TMUX_CMD[@]}" new-session -d -s "$session"
fi

# Normalize prompt to a file if provided as positional arg
if [[ -n "$prompt" && -z "$prompt_file" ]]; then
    prompt_file=$(mktemp /tmp/spawn-agent-prompt.XXXXXX)
    _cleanup_prompt_file="$prompt_file"
    printf '%s' "$prompt" > "$prompt_file"
fi

# Canonicalize prompt_file to absolute path
if [[ -n "$prompt_file" ]]; then
    prompt_file="$(cd -- "$(dirname -- "$prompt_file")" && pwd)/$(basename -- "$prompt_file")"
fi

# Start the agent in a new tmux window, then deliver the prompt via
# load-buffer/paste-buffer. This avoids ARG_MAX at every boundary:
# the tmux command, the shell inside tmux, and the agent's execve.
"${TMUX_CMD[@]}" new-window -t "$session" -n "$window" -c "$directory" "$agent"

if [[ -n "$prompt_file" ]]; then
    # Wait for the agent to initialize before sending the prompt
    if [[ "$agent" == "agy" ]]; then
        # agy paints a full-screen TUI and discards anything delivered before it
        # is listening, so a flat `sleep 2` races it -- on a cold start the
        # prompt vanishes and the spawn still reports success.
        #
        # Worse, agy's FIRST run in an untrusted directory opens a modal asking
        # whether to trust it, whose default button is "Yes, I trust this
        # folder" and whose footer is "enter Confirm". Pasting into that does
        # nothing and the Enter that follows GRANTS TRUST. That is how
        # /tmp/pr64-test ended up in agy's trustedWorkspaces during testing.
        # Never send keys until the composer specifically is on screen.
        agy_ready=""
        agy_gone=0
        for _ in $(seq 1 120); do
            # A window that disappeared is not a slow window: say so, rather
            # than burning 30s and then claiming the agent is waiting for input.
            if pane="$("${TMUX_CMD[@]}" capture-pane -p -t "$session:$window" 2>/dev/null)"; then
                agy_gone=0
            else
                agy_gone=$(( agy_gone + 1 ))
                if (( agy_gone >= 3 )); then
                    echo "Error: $session:$window is gone -- $agent exited before the prompt could be sent." >&2
                    echo "  Nothing was pasted." >&2
                    exit 1
                fi
                sleep 0.25
                continue
            fi

            if [[ "$pane" == *"Do you trust the contents of this project?"* ]]; then
                echo "Error: agy is asking whether to trust this directory before it will run:" >&2
                echo "    $directory" >&2
                echo "  Nothing was pasted, and no key was sent -- answering that prompt is a" >&2
                echo "  permission decision this tooling will not make for you." >&2
                echo "  Answer it yourself, then re-run:  tmux attach -t $session" >&2
                exit 1
            fi

            # The composer specifically: its rule AND the shortcuts hint. The
            # rule alone is not enough -- a banner can draw box characters
            # before the input box is live, which would paste even earlier than
            # the flat sleep did. The trust modal has neither.
            if [[ "$pane" == *"? for shortcuts"* && "$pane" == *"─"* ]]; then
                agy_ready=1
                break
            fi
            sleep 0.25
        done
        if [[ -z "$agy_ready" ]]; then
            echo "Error: agy's input box did not appear within 30s; prompt not sent." >&2
            echo "  $agent is running in $session:$window -- attach and type it by hand." >&2
            exit 1
        fi
        # The box is painted a beat before input is accepted.
        sleep 1
    else
        sleep 2
    fi
    buf_name="spawn-agent-$$"
    "${TMUX_CMD[@]}" load-buffer -b "$buf_name" "$prompt_file"
    if ! "${TMUX_CMD[@]}" paste-buffer -d -t "$session:$window" -b "$buf_name"; then
        "${TMUX_CMD[@]}" delete-buffer -b "$buf_name" 2>/dev/null || true
        echo "Error: failed to paste prompt to $session:$window" >&2
        exit 1
    fi
    sleep 1.5
    "${TMUX_CMD[@]}" send-keys -t "$session:$window" Enter
fi

echo "Spawned $agent in $target (dir: $directory)"
