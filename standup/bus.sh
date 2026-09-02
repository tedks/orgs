#!/usr/bin/env bash
# bus.sh — the situational-awareness message bus (git-native, file-backed).
#
# The bus is a directory of per-agent inboxes. A message is one file; delivery
# is CONSTRUCTED, not trusted to a transport: a message is either in the inbox
# or it is not, and it moves to delivered/ only when it has actually been
# shown to the agent (by guard.sh). This is deliberately not a fire-and-forget
# mailbox — that class of channel dropped verdicts elsewhere in this project.
#
# Layout (default root: $STANDUP_BUS or ./.standup/bus):
#   <root>/<agent-id>/inbox/<epoch>-<seq>-<severity>.msg
#   <root>/<agent-id>/delivered/<same-name>
# Severity is one of: info | redirect | halt. `halt` forces guard.sh to a
# nonzero exit so the agent treats it as a stop signal.
set -euo pipefail

bus_root() { printf '%s' "${STANDUP_BUS:-$PWD/.standup/bus}"; }

usage() {
    cat >&2 <<'EOF'
usage:
  bus.sh send   <agent-id> <info|redirect|halt> <message...>
  bus.sh peek   <agent-id>            # list pending (does not deliver)
  bus.sh count  <agent-id>            # number pending
  bus.sh drain  <agent-id>            # print pending + move to delivered (deliver)
  bus.sh haspending <agent-id>        # exit 0 if any pending, 1 if none
  bus.sh halting <agent-id>           # exit 0 if any pending halt, 1 if none
EOF
    exit 2
}

valid_severity() { case "$1" in info|redirect|halt) return 0;; *) return 1;; esac; }
# agent-ids are path segments — keep them from escaping the bus root.
valid_agent() { case "$1" in ''|*/*|.|..|*'..'*) return 1;; *) return 0;; esac; }

cmd_send() {
    local agent=$1 sev=$2; shift 2
    valid_agent "$agent" || { echo "bus: bad agent-id: $agent" >&2; exit 2; }
    valid_severity "$sev" || { echo "bus: bad severity: $sev" >&2; exit 2; }
    [ $# -ge 1 ] || { echo "bus: empty message" >&2; exit 2; }
    local dir; dir="$(bus_root)/$agent/inbox"; mkdir -p "$dir"
    # Monotonic-ish name: epoch + a per-call random seq so concurrent senders
    # (a standup and a Crystal daemon) never collide on a filename.
    local name; name="$(date +%s)-$RANDOM-$sev.msg"
    printf '%s\n' "$*" > "$dir/$name"
    printf 'queued %s/%s\n' "$agent" "$name"
}

_pending() { # agent -> prints inbox file paths in stable order, or nothing
    local agent=$1 dir; dir="$(bus_root)/$agent/inbox"
    [ -d "$dir" ] || return 0
    find "$dir" -maxdepth 1 -type f -name '*.msg' | sort
}

cmd_peek()  { local f; while IFS= read -r f; do [ -n "$f" ] && { echo "── ${f##*/}"; cat "$f"; }; done < <(_pending "$1"); }
cmd_count() { _pending "$1" | grep -c . || true; }
cmd_haspending() { [ -n "$(_pending "$1")" ]; }
cmd_halting() { _pending "$1" | grep -q -- '-halt\.msg$'; }

cmd_drain() { # print each pending message, then move it to delivered/
    local agent=$1 f base ddir; ddir="$(bus_root)/$agent/delivered"; mkdir -p "$ddir"
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        base=${f##*/}
        case "$base" in *-halt.msg) echo "━━ SITUATION [HALT] ━━";; *-redirect.msg) echo "━━ SITUATION [redirect] ━━";; *) echo "━━ SITUATION ━━";; esac
        cat "$f"
        mv "$f" "$ddir/$base"
    done < <(_pending "$agent")
}

[ $# -ge 1 ] || usage
sub=$1; shift
case "$sub" in
    send)       [ $# -ge 3 ] || usage; cmd_send "$@";;
    peek)       [ $# -eq 1 ] || usage; cmd_peek "$1";;
    count)      [ $# -eq 1 ] || usage; cmd_count "$1";;
    drain)      [ $# -eq 1 ] || usage; cmd_drain "$1";;
    haspending) [ $# -eq 1 ] || usage; cmd_haspending "$1";;
    halting)    [ $# -eq 1 ] || usage; cmd_halting "$1";;
    *) usage;;
esac
