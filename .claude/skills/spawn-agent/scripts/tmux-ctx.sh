#!/bin/bash
# tmux-ctx.sh - Shared tmux context helper for spawn-agent scripts
#
# Source this file to get a TMUX_CMD array that automatically targets
# the correct tmux server socket.
#
# Usage (in other scripts):
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/tmux-ctx.sh"
#   "${TMUX_CMD[@]}" list-windows
#
# Override with:
#   SPAWN_TMUX_SOCKET=/tmp/tmux-1000/personal  (full path)
#   SPAWN_TMUX_LABEL=personal                   (-L name)
#
# Priority: explicit env var > $TMUX auto-detection > bare tmux (default socket)

_resolve_tmux_cmd() {
    # Explicit socket path takes highest priority
    if [[ -n "${SPAWN_TMUX_SOCKET:-}" ]]; then
        TMUX_CMD=(tmux -S "$SPAWN_TMUX_SOCKET")
        return
    fi

    # Explicit -L label
    if [[ -n "${SPAWN_TMUX_LABEL:-}" ]]; then
        TMUX_CMD=(tmux -L "$SPAWN_TMUX_LABEL")
        return
    fi

    # Auto-detect from $TMUX env var (format: /path/to/socket,pid,pane)
    if [[ -n "${TMUX:-}" ]]; then
        local socket_path="${TMUX%%,*}"
        if [[ -S "$socket_path" ]]; then
            TMUX_CMD=(tmux -S "$socket_path")
            return
        fi
    fi

    # Fallback: bare tmux (uses default socket)
    TMUX_CMD=(tmux)
}

_resolve_tmux_cmd
