#!/bin/bash
# tmux-info.sh - Show current tmux context for debugging
#
# Usage: tmux-info.sh
#
# Prints: socket path, server PID, current session, all sessions/windows.
# Useful for figuring out which tmux server you're in before spawning agents.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"

echo "=== tmux context ==="

if [[ -n "${TMUX:-}" ]]; then
    socket_path="${TMUX%%,*}"
    server_pid="$(echo "$TMUX" | cut -d, -f2)"
    echo "Socket:  $socket_path"
    echo "PID:     $server_pid"
    echo "In tmux: yes"
else
    echo "In tmux: no (using default socket)"
fi

if [[ -n "${SPAWN_TMUX_SOCKET:-}" ]]; then
    echo "Override: SPAWN_TMUX_SOCKET=$SPAWN_TMUX_SOCKET"
elif [[ -n "${SPAWN_TMUX_LABEL:-}" ]]; then
    echo "Override: SPAWN_TMUX_LABEL=$SPAWN_TMUX_LABEL"
fi

echo ""
echo "=== sessions ==="
"${TMUX_CMD[@]}" list-sessions -F "#{session_name} (#{session_windows} windows, created #{session_created_string})" 2>/dev/null || echo "(no server running)"

echo ""
echo "=== windows ==="
"${TMUX_CMD[@]}" list-windows -a -F "#{session_name}:#{window_name}  [#{window_index}]  #{pane_current_command}  #{pane_current_path}" 2>/dev/null || echo "(none)"
