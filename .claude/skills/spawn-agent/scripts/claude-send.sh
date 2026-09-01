#!/bin/bash
# claude-send.sh - Send a message to a Claude Code instance in tmux
#
# Usage: claude-send.sh <window> <message>
#        claude-send.sh <window> --prompt-file <file>
#
# Automatically targets the correct tmux server socket when run inside tmux.
# Override with SPAWN_TMUX_SOCKET or SPAWN_TMUX_LABEL env vars.
#
# Uses tmux load-buffer/paste-buffer with a named buffer to avoid ARG_MAX
# limits and race conditions with concurrent sends. The buffer is deleted
# after pasting (-d flag), with a fallback delete-buffer on failure.
# Handles the timing issue where Enter gets swallowed if sent too quickly
# after the text (1.5 second delay).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"

if [[ $# -lt 2 ]]; then
    echo "Usage: claude-send.sh <window> <message>" >&2
    echo "       claude-send.sh <window> --prompt-file <file>" >&2
    echo "  window: tmux window target (e.g., 'chaos:newchan-review')" >&2
    echo "  message: the prompt to send to Claude" >&2
    echo "  --prompt-file: read message from file (avoids ARG_MAX)" >&2
    exit 1
fi

window="$1"
shift

# Get message from --prompt-file or positional args
prompt_file=""
_cleanup_prompt_file=""

# Trap to clean up temp files on exit/interrupt.
# Set before any temp file creation so failure paths don't leak.
cleanup() {
    [[ -n "$_cleanup_prompt_file" ]] && rm -f "$_cleanup_prompt_file"
}
trap cleanup EXIT

if [[ "$1" == "--prompt-file" || "$1" == "-f" ]]; then
    prompt_file="$2"
    if [[ -z "$prompt_file" ]]; then
        echo "Error: --prompt-file requires a file path" >&2
        exit 1
    fi
    if [[ ! -f "$prompt_file" ]]; then
        echo "Error: prompt file not found: $prompt_file" >&2
        exit 1
    fi
    if [[ ! -s "$prompt_file" ]]; then
        echo "Error: prompt file is empty: $prompt_file" >&2
        exit 1
    fi
else
    message="$*"
    if [[ -z "$message" ]]; then
        echo "Error: message is empty" >&2
        exit 1
    fi
    # Write positional args to temp file to avoid ARG_MAX on send-keys
    prompt_file=$(mktemp /tmp/claude-send-prompt.XXXXXX)
    _cleanup_prompt_file="$prompt_file"
    printf '%s' "$message" > "$prompt_file"
fi

# Use tmux load-buffer + paste-buffer with a named buffer. The named
# buffer (keyed by PID) avoids race conditions when multiple claude-send
# instances run concurrently. The -d flag deletes the buffer after paste.
# If paste-buffer fails (e.g., target window gone), delete-buffer ensures
# the prompt doesn't linger in tmux's buffer list.
buf_name="claude-send-$$"
"${TMUX_CMD[@]}" load-buffer -b "$buf_name" "$prompt_file"
if ! "${TMUX_CMD[@]}" paste-buffer -d -t "$window" -b "$buf_name"; then
    "${TMUX_CMD[@]}" delete-buffer -b "$buf_name" 2>/dev/null || true
    echo "Error: failed to paste to $window (window may not exist)" >&2
    exit 1
fi
sleep 1.5
"${TMUX_CMD[@]}" send-keys -t "$window" Enter
