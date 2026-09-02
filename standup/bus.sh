#!/usr/bin/env bash
# bus.sh — the situational-awareness message bus (git-native, file-backed).
#
# The bus is a directory of per-agent inboxes. A message is one file; delivery
# is CONSTRUCTED, not trusted to a transport: a message is either in the inbox
# or it is not, and it moves to delivered/ only when it has actually been
# shown to the agent (by guard.sh). This is deliberately not a fire-and-forget
# mailbox — that class of channel dropped verdicts elsewhere in this project.
#
# Concurrency: a message is written to a unique temp file and atomically
# rename()d into the inbox, so a concurrent reader never sees a partial write
# and two senders never collide. A drainer that races another drainer for the
# same file simply skips it (the rename/`mv` is the exclusive claim).
#
# Layout (default root: $STANDUP_BUS or ./.standup/bus):
#   <root>/<agent-id>/inbox/<epoch>-<rand>-<severity>.msg
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
# agent-ids are a single path segment — reject anything that could escape the
# bus root or break the newline-delimited file protocol.
valid_agent() {
    case "$1" in
        ''|*/*|.|..) return 1;;
        *'..'*) return 1;;
        *[[:cntrl:]]*) return 1;;   # newlines / control chars
        *) return 0;;
    esac
}
# Validate on EVERY entry point, not just send, so drain/peek/... cannot be
# handed a traversal id.
req_agent() { valid_agent "$1" || { echo "bus: bad agent-id: $1" >&2; exit 2; }; }

cmd_send() {
    local agent=$1 sev=$2; shift 2
    req_agent "$agent"
    valid_severity "$sev" || { echo "bus: bad severity: $sev" >&2; exit 2; }
    [ $# -ge 1 ] || { echo "bus: empty message" >&2; exit 2; }
    local dir; dir="$(bus_root)/$agent/inbox"; mkdir -p "$dir"
    local name; name="$(date +%s)-$RANDOM$RANDOM-$sev.msg"
    # Atomic publish: write to a unique temp, then rename into place. A reader
    # only ever sees the complete file; two senders never truncate each other.
    local tmp; tmp="$(mktemp "$dir/.tmp.XXXXXX")"
    printf '%s\n' "$*" > "$tmp"
    mv "$tmp" "$dir/$name"
    printf 'queued %s/%s\n' "$agent" "$name"
}

_pending() { # agent -> prints inbox file paths in stable order, or nothing
    local agent=$1 dir; dir="$(bus_root)/$agent/inbox"
    [ -d "$dir" ] || return 0
    # exclude in-flight temp files
    find "$dir" -maxdepth 1 -type f -name '*.msg' ! -name '.tmp.*' | sort
}

cmd_peek()  { req_agent "$1"; local f; while IFS= read -r f; do [ -n "$f" ] && { echo "── ${f##*/}"; cat "$f" || true; }; done < <(_pending "$1"); }
cmd_count() { req_agent "$1"; _pending "$1" | grep -c . || true; }
cmd_haspending() { req_agent "$1"; [ -n "$(_pending "$1")" ]; }

# No grep -q on a pipe here: grep -q exits early on match, upstream `sort`
# takes SIGPIPE, and under pipefail the pipeline would report failure EVEN
# WHEN A HALT MATCHED — a false negative on the safety signal. Iterate instead.
cmd_halting() {
    req_agent "$1"
    local f
    while IFS= read -r f; do
        case "$f" in *-halt.msg) return 0;; esac
    done < <(_pending "$1")
    return 1
}

cmd_drain() { # print each pending message, then move it to delivered/
    req_agent "$1"
    local agent=$1 f base ddir; ddir="$(bus_root)/$agent/delivered"; mkdir -p "$ddir"
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        base=${f##*/}
        # Claim the file first (mv is the exclusive claim); if another drainer
        # already took it, skip rather than crash under set -e.
        mv "$f" "$ddir/$base" 2>/dev/null || continue
        case "$base" in
            *-halt.msg)     echo "━━ SITUATION [HALT] ━━";;
            *-redirect.msg) echo "━━ SITUATION [redirect] ━━";;
            *)              echo "━━ SITUATION ━━";;
        esac
        cat "$ddir/$base" || true
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
