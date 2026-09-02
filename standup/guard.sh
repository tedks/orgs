#!/usr/bin/env bash
# guard.sh — the forced-observe wrapper. Runs the agent's inner-loop command
# and appends any pending bus messages to STDERR (so structured STDOUT stays
# intact for machine consumers), where the agent — which ran the command to
# read its result — still sees them. A pending `halt` forces a nonzero exit
# even when the command succeeded, weaponizing the agent's own error-handling
# reflex into a reorient.
#
#   guard.sh <agent-id> -- <command...>
#
# Wrap the tools an agent uses in its dev loop (test runner, build, git):
#   alias t='guard.sh worker-a -- pytest'
# The agent never has to remember to check the bus; the environment forces
# the Observe at the tool-call chokepoint it already passes through.
#
# Exit: the command's own status, UNLESS a halt is pending, in which case 87
# (a distinctive "halted by standup" code) after the output and the situation
# footer are emitted. A command that failed on its own keeps its own status.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
bus="$here/bus.sh"

[ $# -ge 3 ] || { echo "usage: guard.sh <agent-id> -- <command...>" >&2; exit 2; }
agent=$1; shift
[ "$1" = "--" ] || { echo "guard: expected -- before the command" >&2; exit 2; }
shift
[ $# -ge 1 ] || { echo "guard: empty command" >&2; exit 2; }

# Run the wrapped command in a SUBSHELL so a wrapped `exec`/`exit`/`set` cannot
# replace this process or bypass the footer. stdout/stderr pass through live.
( "$@" )
status=$?

# Sample halt-state AFTER the command (catches a halt that arrived while it
# ran) and BEFORE the drain that would consume it. The footer goes to stderr,
# leaving the command's stdout uncorrupted for machine consumers.
halt=0
if "$bus" haspending "$agent"; then
    "$bus" halting "$agent" && halt=1 || true
    {
        echo
        "$bus" drain "$agent"
    } >&2
fi

# A pending halt overrides a success: force the reorient. A command that
# already failed keeps its own (more informative) status.
if [ "$halt" -eq 1 ] && [ "$status" -eq 0 ]; then
    echo "standup: HALT pending — stopping to reorient (see situation above)" >&2
    exit 87
fi
exit "$status"
