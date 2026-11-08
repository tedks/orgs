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
# Priority: per-call pin > responding $TMUX > generic override > config > default
source "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../../_shared/config.sh"
_AGENT_SKILLS_TMUX_SOCKET=$(agent_skills_get tmux.socket) || return $?

_tmux_socket_responds() {
    local socket_path="$1"
    [[ -S "$socket_path" ]] || return 1
    python3 - "$socket_path" <<'PY'
import subprocess
import sys

try:
    result = subprocess.run(
        ['tmux', '-S', sys.argv[1], 'display-message', '-p', '#{socket_path}'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, check=False)
except (OSError, subprocess.TimeoutExpired):
    raise SystemExit(1)
raise SystemExit(result.returncode != 0)
PY
}

_resolve_tmux_cmd() {
    local active_rejected=0

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
        if _tmux_socket_responds "$socket_path"; then
            TMUX_CMD=(tmux -S "$socket_path")
            return
        fi
        active_rejected=1
    fi

    # The generic environment override is part of the resolved shared config;
    # it is considered only after an active server.
    if [[ -n "$_AGENT_SKILLS_TMUX_SOCKET" ]]; then
        if [[ "$_AGENT_SKILLS_TMUX_SOCKET" == */* ]]; then
            TMUX_CMD=(tmux -S "$_AGENT_SKILLS_TMUX_SOCKET")
        else
            TMUX_CMD=(tmux -L "$_AGENT_SKILLS_TMUX_SOCKET")
        fi
        return
    fi

    # A rejected $TMUX would still affect bare tmux in Python callers, so use
    # the same explicit default server selector in both implementations.
    if (( active_rejected )); then
        TMUX_CMD=(tmux -L default)
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
