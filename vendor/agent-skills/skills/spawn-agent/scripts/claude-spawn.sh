#!/bin/bash
# claude-spawn.sh - Create a new tmux window with a Claude Code instance
#
# Usage: claude-spawn.sh <session:window-name> [directory] [claude-args...]
#
# Automatically targets the correct tmux server socket when run inside tmux.
# Override with SPAWN_TMUX_SOCKET or SPAWN_TMUX_LABEL env vars.
#
# Examples:
#   claude-spawn.sh chaos:review           # New window in cwd
#   claude-spawn.sh chaos:review ./project # New window in ./project
#   claude-spawn.sh chaos:review . --resume abc123  # Resume session

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"

if [[ $# -lt 1 ]]; then
    echo "Usage: claude-spawn.sh <session:window-name> [directory] [claude-args...]" >&2
    echo "  session:window-name: tmux target (e.g., 'chaos:newchan-review')" >&2
    echo "  directory: working directory (default: current directory)" >&2
    echo "  claude-args: additional arguments passed to claude" >&2
    exit 1
fi

target="$1"
shift

# Parse session and window from target
session="${target%%:*}"
window="${target#*:}"

# Get directory (default to current)
directory="${1:-.}"
if [[ -n "$1" ]]; then
    shift
fi

# Remaining args go to claude
claude_args="$*"

# Ensure session exists
if ! "${TMUX_CMD[@]}" has-session -t "$session" 2>/dev/null; then
    echo "Creating tmux session: $session" >&2
    "${TMUX_CMD[@]}" new-session -d -s "$session"
fi

# Create the window
"${TMUX_CMD[@]}" new-window -t "$session" -n "$window" -c "$directory" "claude $claude_args"
echo "Created window $target in $directory"
