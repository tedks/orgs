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
#   SPAWN_TMUX_SOCKET=/tmp/example-tmux/server  (full path)
#   SPAWN_TMUX_LABEL=example                   (-L name)
#
# Priority: explicit env > valid $TMUX > shared config fallback > default socket
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../../_shared/config.sh"
_AGENT_SKILLS_TMUX_SOCKET=$(agent_skills_get tmux.socket) || return $?

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

    # Explicit common override selects a label or socket path.
    if [[ -n "${AGENT_SKILLS_TMUX_SOCKET:-}" ]]; then
        if [[ "$_AGENT_SKILLS_TMUX_SOCKET" == */* ]]; then
            TMUX_CMD=(tmux -S "$_AGENT_SKILLS_TMUX_SOCKET")
        else
            TMUX_CMD=(tmux -L "$_AGENT_SKILLS_TMUX_SOCKET")
        fi
        return
    fi

    # Auto-detect from $TMUX env var (format: /path/to/socket,pid,pane)
    if [[ -n "${TMUX:-}" ]]; then
        local socket_path="${TMUX%%,*}"
        if [[ -S "$socket_path" ]]; then
            TMUX_CMD=(tmux -S "$socket_path")
            return
        fi
        echo 'active TMUX socket unavailable; supply an explicit socket override' >&2
        return 2
    fi

    # File configuration is a fallback outside an active tmux server.
    if [[ -n "$_AGENT_SKILLS_TMUX_SOCKET" ]]; then
        if [[ "$_AGENT_SKILLS_TMUX_SOCKET" == */* ]]; then
            TMUX_CMD=(tmux -S "$_AGENT_SKILLS_TMUX_SOCKET")
        else
            TMUX_CMD=(tmux -L "$_AGENT_SKILLS_TMUX_SOCKET")
        fi
        return
    fi

    # Fallback: bare tmux (uses default socket)
    TMUX_CMD=(tmux)
}

_resolve_tmux_cmd

# Child resolvers, delivery, and rollout readers inherit this selection, not a
# later file configuration. A bare default must also suppress later selection.
unset SPAWN_TMUX_SOCKET SPAWN_TMUX_LABEL
export AGENT_SKILLS_TMUX_SOCKET=""
case "${TMUX_CMD[1]:-}" in
    -S) export SPAWN_TMUX_SOCKET="${TMUX_CMD[2]}";;
    -L) export SPAWN_TMUX_LABEL="${TMUX_CMD[2]}";;
    *) unset TMUX;;
esac
