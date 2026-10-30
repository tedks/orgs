#!/bin/bash
# Resolve the Codex rollout held open by the process in a tmux pane.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"

exclude_session=""
if [[ $# -eq 3 && "$1" == "--exclude-session" ]]; then
    exclude_session="${2,,}"
    target="$3"
elif [[ $# -eq 1 ]]; then
    target="$1"
else
    echo "Usage: $0 [--exclude-session <uuid>] <session:window>" >&2
    exit 2
fi

proc_root="${SPAWN_PROC_ROOT:-/proc}"

if ! pane_pid=$("${TMUX_CMD[@]}" display-message -p -t "$target" '#{pane_pid}' 2>/dev/null) || \
   [[ ! "$pane_pid" =~ ^[0-9]+$ ]]; then
    echo "Error: cannot resolve the pane process for $target" >&2
    exit 1
fi

for _ in $(seq 1 40); do
    pids=("$pane_pid")
    pid_index=0
    while (( pid_index < ${#pids[@]} )); do
        pid="${pids[pid_index]}"
        children_file="$proc_root/$pid/task/$pid/children"
        if [[ -r "$children_file" ]]; then
            children=()
            read -r -a children < "$children_file" || true
            pids+=("${children[@]}")
        fi
        pid_index=$((pid_index + 1))
    done

    rollouts=()
    for pid in "${pids[@]}"; do
        for descriptor in "$proc_root/$pid/fd"/*; do
            [[ -e "$descriptor" || -L "$descriptor" ]] || continue
            path=$(readlink "$descriptor" 2>/dev/null || true)
            if [[ "$path" == */sessions/*/rollout-*.jsonl ]]; then
                if [[ -n "$exclude_session" && "$path" == *-"$exclude_session".jsonl ]]; then
                    continue
                fi
                rollouts+=("$path")
            fi
        done
    done

    if (( ${#rollouts[@]} > 0 )); then
        mapfile -t unique_rollouts < <(printf '%s\n' "${rollouts[@]}" | sort -u)
        if (( ${#unique_rollouts[@]} == 1 )); then
            printf '%s\n' "${unique_rollouts[0]}"
            exit 0
        fi
        echo "Error: multiple Codex rollouts are open below $target:" >&2
        printf '  %s\n' "${unique_rollouts[@]}" >&2
        exit 1
    fi
    sleep 0.25
done

echo "Error: no Codex rollout appeared below $target within 10s" >&2
exit 1
