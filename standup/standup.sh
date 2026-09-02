#!/usr/bin/env bash
# standup.sh — the Observe step, run for a lead (or a human) over a set of
# working agents. It reads what the world already records — git history and
# each agent's status file — summarizes progress, flags likely rabbit-holes,
# and (optionally) sends a redirect that the agents' guard-wrapped tools will
# force them to observe. It needs NO org hierarchy: point it at a repo and a
# list of agents and it works. That is the whole standalone bet — the standup
# may be most of the value with little of the machinery.
#
#   standup.sh observe                          # digest for every agent with a bus
#   standup.sh observe <agent-id>               # digest for one agent
#   standup.sh redirect <agent-id> <message>    # queue a redirect (guard delivers it)
#   standup.sh halt <agent-id> <message>        # queue a halt (forces a reorient)
#
# Config via env: STANDUP_BUS (bus root), STANDUP_STALL_MIN (minutes without a
# commit before an agent is flagged, default 15). Agents surface in the digest
# by (a) having a bus inbox and (b) referencing their agent-id in their commit
# messages and/or a status/<agent>.md file.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
bus="$here/bus.sh"
stall_min="${STANDUP_STALL_MIN:-15}"

agents_with_bus() {
    local root="${STANDUP_BUS:-$PWD/.standup/bus}" d
    [ -d "$root" ] || return 0
    for d in "$root"/*/; do [ -d "$d" ] && basename "$d"; done
}

# last_commit_epoch_for <agent> — epoch of the newest commit whose message
# mentions the agent id (literal match, not a regex); empty if none.
last_commit_epoch_for() {
    local agent=$1
    git log --all --fixed-strings --grep="$agent" --pretty=%ct -1 2>/dev/null \
        || true
}

observe_one() {
    local agent=$1
    echo "## $agent"
    # pending situation the agent has NOT yet observed (still in inbox)
    local pending; pending=$("$bus" count "$agent" 2>/dev/null || echo 0)
    echo "- unobserved bus messages: $pending"
    # recent activity from git (best-effort: commits mentioning the agent id)
    local last; last=$(last_commit_epoch_for "$agent")
    if [ -n "$last" ]; then
        local age=$(( ( $(date +%s) - last ) / 60 ))
        echo "- last commit mentioning it: ${age} min ago"
        if [ "$age" -ge "$stall_min" ]; then
            echo "- ⚠ STALL: no commit in ${age} min (threshold ${stall_min}) — candidate rabbit-hole"
        fi
    else
        echo "- no commits mention this agent yet"
    fi
    # its status file, if it keeps one
    local sf; for sf in status/"$agent".md status/*"$agent"*.md; do
        [ -f "$sf" ] && { echo "- status ($sf):"; sed 's/^/    /' "$sf"; break; }
    done
    echo
}

cmd_observe() {
    echo "# Standup — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# repo: $(git rev-parse --show-toplevel 2>/dev/null || echo '(not a git repo)') @ $(git rev-parse --short HEAD 2>/dev/null || echo '-')"
    echo
    if [ $# -ge 1 ]; then
        observe_one "$1"
    else
        local any=0 a
        while IFS= read -r a; do [ -n "$a" ] && { any=1; observe_one "$a"; }; done < <(agents_with_bus)
        [ "$any" -eq 1 ] || echo "(no agents have a bus yet — none to observe)"
    fi
}

[ $# -ge 1 ] || { echo "usage: standup.sh observe [agent] | redirect <agent> <msg> | halt <agent> <msg>" >&2; exit 2; }
sub=$1; shift
case "$sub" in
    observe)  cmd_observe "$@";;
    redirect) [ $# -ge 2 ] || { echo "usage: standup.sh redirect <agent> <msg>" >&2; exit 2; }; a=$1; shift; "$bus" send "$a" redirect "$*";;
    halt)     [ $# -ge 2 ] || { echo "usage: standup.sh halt <agent> <msg>" >&2; exit 2; }; a=$1; shift; "$bus" send "$a" halt "$*";;
    *) echo "unknown: $sub" >&2; exit 2;;
esac
