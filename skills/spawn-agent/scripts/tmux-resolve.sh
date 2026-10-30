#!/usr/bin/env bash
# Resolve an exact target without display-message's missing-target fallback.
# Output SERVER_PID:PANE_ID; all later operations must use that stable pane ID.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"
fail() { echo 'Error: tmux target is missing, ambiguous, or unsupported.' >&2; exit 2; }
(($# == 1)) || fail
target=$1
[[ -n "$target" && "$target" != *[[:cntrl:]]* ]] || fail
pane_requested=''
name=''
case "$target" in
    %*) [[ "$target" =~ ^%[0-9]+$ ]] || fail; pane_requested=$target; window=$target;;
    @*) [[ "$target" =~ ^@[0-9]+$ ]] || fail; window=$target;;
    *:*)
        session=${target%%:*}
        name=${target#*:}
        [[ -n "$session" && -n "$name" && "$session" != -* ]] || fail
        # Enumerate exact window names: no prefixes, globs, relative selectors,
        # index/name guessing or active-window fallback. Dots are literal names.
        windows=$("${TMUX_CMD[@]}" list-windows -t "=$session" -F $'#{window_id}\t#{window_name}') || fail
        window=''
        while IFS=$'\t' read -r id candidate; do
            [[ "$id" =~ ^@[0-9]+$ ]] || fail
            if [[ "$candidate" == "$name" ]]; then
                [[ -z "$window" ]] || fail
                window=$id
            fi
        done <<< "$windows"
        [[ -n "$window" ]] || fail;;
    *) fail;;
esac
rows=$("${TMUX_CMD[@]}" list-panes -t "$window" -F '#{pid}:#{pane_id}:#{pane_active}:#{window_name}') || fail
identity=''
while IFS= read -r row; do
    [[ "$row" =~ ^([0-9]+):(%[0-9]+):([01]):(.*)$ ]] || fail
    server=${BASH_REMATCH[1]}; pane=${BASH_REMATCH[2]}; active=${BASH_REMATCH[3]}
    actual_name=${BASH_REMATCH[4]}
    [[ -z "$name" || "$actual_name" == "$name" ]] || fail
    if [[ -n "$pane_requested" ]]; then
        [[ "$pane" == "$pane_requested" ]] || continue
    else
        [[ "$active" == 1 ]] || continue
    fi
    [[ -z "$identity" ]] || fail
    identity="$server:$pane"
done <<< "$rows"
[[ -n "$identity" ]] || fail
printf '%s\n' "$identity"
