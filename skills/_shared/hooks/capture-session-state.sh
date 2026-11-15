#!/bin/bash
# Capture Claude session state on first tool use.
#
# PreToolUse hook that writes session ID, launch directory, and metadata
# to ~/.claude/session-state/<session-id>.json. Only writes once per
# session (skips if file already exists).
#
# Linux-only: the process walk reads /proc (as does the MCP server).
#
# Also maintains a 'current.<claude_pid>' pointer, on EVERY call rather than
# only the first, so the MCP server can find the active session without
# CLAUDE_SESSION_ID in its environment. It has to be per call because the
# state file above is per session but the pointer is per PROCESS: a resumed
# session (`claude --resume`, or harness-control's own branch_session) is a
# new claude pid with an old session id and an already-existing state file.
# The pointer is written only once the state file demonstrably exists (from
# this call or an earlier one): otherwise the server could answer with a
# session id that has no launch_dir/project_path/git_branch to go with it.
#

# Claude Code delivers the session id only in the stdin JSON payload (field
# "session_id") -- it never sets a CLAUDE_SESSION_ID env var, so that has to
# be parsed out rather than read from the environment.
input="$(cat)"
session_id="$(jq -r '.session_id // empty' <<< "$input" 2>/dev/null)"
# session_id becomes part of a filesystem path below; require it to be a UUID
# so a malformed or unexpected payload (e.g. "../../.claude") can't make
# STATE_FILE resolve outside STATE_DIR.
[[ "$session_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] || exit 0

# The payload's own "cwd" is the session's launch directory; prefer it over
# $PWD, which reflects this hook subprocess and is not guaranteed to match.
launch_dir="$(jq -r '.cwd // empty' <<< "$input" 2>/dev/null)"
[ -z "$launch_dir" ] && launch_dir="$PWD"

STATE_DIR="$HOME/.claude/session-state"
STATE_FILE="$STATE_DIR/$session_id.json"

# Session identifiers, launch paths and process pointers are private even
# when the calling shell inherited a permissive umask. Tighten an existing
# directory before reading or writing state beneath it.
umask 077
mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR" || exit 0

# Boot id, read once and with a fallback: it goes into the pointer below so a
# stale pointer from before a reboot (same pid, same tick count -- ticks reset
# at boot) is refused. If the file is ever unreadable (a locked-down sandbox),
# "unknown" degrades to "no boot-crossing protection" rather than writing no
# pointer at all, which would otherwise cost every future get_session_info
# call its whole retry window for a condition polling can't fix.
boot_id=""
read -r boot_id 2>/dev/null < /proc/sys/kernel/random/boot_id
[ -z "$boot_id" ] && boot_id="unknown"

# --- Sweep, on EVERY call -----------------------------------------------------
# Whether a process still exists is what decides whether its file is garbage,
# so this can run per call. It must not wait for a brand-new session (most of
# this fleet's sessions are resumes, which never take that path).
#
# Liveness (mostly forkless): catches the common case -- the owning process is
# simply gone -- immediately, for both pointers and temp files. No age check
# alongside it for pointers: a live session idle for days must keep its
# pointer, and the pointer's own start-time+boot-id check (below) already
# makes a stale pointer under a reused pid harmless (the server refuses it,
# it doesn't hand out a wrong session), so an age sweep would only add the
# risk of deleting a live, merely-idle one.
for f in "$STATE_DIR"/current.* "$STATE_DIR"/.current.* "$STATE_DIR"/.state.* "$STATE_DIR"/.log.*; do
    [ -e "$f" ] || continue
    pid=${f##*.}
    if [[ "$pid" =~ ^[0-9]+$ ]] && [ ! -d "/proc/$pid" ]; then rm -f -- "$f"; fi
done
# Age, temp files only: a dead hook's .current.<pid>/.state.<pid> has no
# equivalent of the pointer's own verification, so if its pid is later
# inherited by an unrelated long-lived process (a daemon), liveness alone
# would call it "in flight" forever. This is the backstop for exactly that;
# it costs one `find` per call, which is fine for files this rare. A hook
# writing its own temp file is normally done in milliseconds, so day-old
# temp files are near-certainly abandoned -- but "near-certainly" is not
# "never": a hook truly stuck for over a day (e.g. blocked on a hung network
# mount under STATE_DIR) could in principle lose this race. Accepted: it
# costs that one call its state/pointer, and self-heals on the next one.
find "$STATE_DIR" \( -name '.current.*' -o -name '.state.*' -o -name '.log.*' \) -mtime +1 -delete 2>/dev/null

# --- Find the claude process --------------------------------------------------
# $PPID is NOT claude: Claude Code runs a hook as `/bin/sh -c <command>`, so the
# chain is hook -> sh -> claude, and keying on $PPID would name the short-lived
# sh, which the server can never match. So walk up (bounded, from /proc, no
# forks) to the nearest ancestor whose comm is claude*. That also steps over any
# wrapper -- timeout, nix, flock, zsh -- without having to list them.
#
# If there is NO such ancestor (an orphaned hook reparented to a subreaper,
# /proc unreadable, a claude whose comm is not claude*), write no pointer: a
# missing pointer only makes get_session_info report null, whereas falling back
# to some other ancestor could key it on a process many sessions share
# (systemd --user, tmux, a daemon) and answer one session with another's id. The
# ancestry is logged (bounded below) so that silent null can be diagnosed.
claude_pid=""
chain=""
p=$PPID
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    read -r comm 2>/dev/null < "/proc/$p/comm" || break
    chain="$chain $p:$comm"
    case "$comm" in claude*) claude_pid=$p; break ;; esac
    parent=""
    while read -r key val; do
        if [ "$key" = "PPid:" ]; then parent=$val; break; fi
    done 2>/dev/null < "/proc/$p/status"
    if ! [[ "$parent" =~ ^[0-9]+$ ]] || [ "$parent" -le 1 ]; then break; fi
    p=$parent
done

# The pointer says "<session_id> <claude start time> <boot id>". Pids wrap
# within days on this fleet, so a dead claude's pointer can sit under a pid a
# new claude then reuses; the server accepts a pointer only if the start time
# (field 22 of /proc/<pid>/stat, in ticks since boot) and the boot id both
# match the live process.
pointer_line=""
if [ -n "$claude_pid" ]; then
    if read -r stat 2>/dev/null < "/proc/$claude_pid/stat"; then
        read -ra stat_fields <<< "${stat##*) }"   # fields after "(comm)", from field 3
        starttime=${stat_fields[19]}              # field 22
        if [[ "$starttime" =~ ^[0-9]+$ ]]; then
            pointer_line="$session_id $starttime $boot_id"
        fi
    fi
else
    # Bounded (not just appended): a host stuck on this path -- comm never
    # matching claude*, or a subreaper repeatedly adopting hooks -- would
    # otherwise fire on every tool call and grow this file without limit,
    # which can fill a host disk if repeated indefinitely.
    # Keep the last ~200 lines, checking size first so the common case (no
    # trimming needed) costs one `wc`, not a `tail`+`mv` every call.
    #
    # The trim-then-append has to be one locked section, not two separate
    # steps: without the lock, two hooks hitting this branch at once could
    # both read the same pre-trim content, and whichever's `mv` lands last
    # would silently discard the other's already-appended entry -- exactly
    # the concurrent-clobbering this file's `>>` (instead of `>`) exists to
    # prevent. flock serializes it; it's already a hard dependency of this
    # Linux-only hook's whole approach (same distro family as /proc).
    #
    # The lock file's name deliberately does NOT match .log.* (or any other
    # sweep pattern below): it's long-lived, not a per-call temp file, and
    # the age-based .log.* sweep has no liveness/pid guard the way the
    # liveness loop does -- if it could match this file, going quiet on
    # this branch for a day would let that sweep unlink the lock out from
    # under a held flock (a classic flock+unlink TOCTOU: the next opener
    # gets a fresh inode with its own independent lock, so two "holders"
    # would no longer actually exclude each other), silently reopening the
    # exact race this lock exists to close.
    log="$STATE_DIR/no-claude-ancestor.log"
    lock="$STATE_DIR/.no-claude-ancestor.lock"
    entry="$(date -u +%Y-%m-%dT%H:%M:%SZ) session=$session_id no claude* ancestor; chain:$chain"
    (
        flock -x -w 2 200 || exit 0   # never let a stuck lock block the hook itself
        log_size="$(wc -c < "$log" 2>/dev/null)"
        if [[ "$log_size" =~ ^[0-9]+$ ]] && [ "$log_size" -gt 65536 ]; then
            log_tmp="$STATE_DIR/.log.$$"
            if tail -n 200 "$log" > "$log_tmp" 2>/dev/null; then
                mv "$log_tmp" "$log" 2>/dev/null || rm -f "$log_tmp"
            else
                rm -f "$log_tmp"
            fi
        fi
        echo "$entry" >> "$log" 2>/dev/null
    ) 200>"$lock"
fi

# --- State file: once per session ---------------------------------------------
if [ ! -f "$STATE_FILE" ]; then
    # Capture git branch if in a repo
    git_branch=""
    if git -C "$launch_dir" rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        git_branch=$(git -C "$launch_dir" branch --show-current 2>/dev/null)
    fi

    # Write session state via jq -n rather than interpolating into a JSON
    # template: launch_dir/git_branch come from the filesystem (a directory or
    # branch name containing a quote or backslash would otherwise corrupt the
    # file), so build the object field-by-field instead.
    #
    # Write to a temp file and rename into place rather than writing STATE_FILE
    # directly: the "only write once" check above is presence-based, so a hook
    # killed mid-write would otherwise leave a truncated/invalid JSON file
    # behind forever (the MCP server would then fail to parse it on every
    # future read, and no later run would ever repair it).
    state_tmp="$STATE_DIR/.state.$$"
    if jq -n \
        --arg session_id "$session_id" \
        --arg launch_dir "$launch_dir" \
        --arg git_branch "$git_branch" \
        --arg started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg hostname "$(hostname -s)" \
        '{session_id: $session_id, launch_dir: $launch_dir, project_path: $launch_dir,
          git_branch: $git_branch, started_at: $started_at, hostname: $hostname}' \
        > "$state_tmp"; then
        mv "$state_tmp" "$STATE_FILE" || rm -f "$state_tmp"
    else
        rm -f "$state_tmp"
    fi

    # Age backstop for old state files, only when a new session starts -- but
    # NOT for a session whose pointer is still live: pointers no longer age
    # out at all (above), on purpose, so a long-lived session (tmux keeps
    # these alive for weeks -- see install-tmux-snapshot) would otherwise
    # have its *own* *.json swept by some unrelated session's hook run,
    # while its still-verifying-fine pointer keeps returning its session_id
    # -- the exact "id with no launch_dir" bug this file exists to prevent,
    # reached through the state file's sweep instead of the pointer's.
    # Reproduced directly: a 31-day-old state file with a live pointer
    # survived a naive age-only sweep being deleted by construction; it must
    # be cross-checked against which session ids current live pointers name.
    #
    # This snapshot can still be stale for a session that is ITSELF mid-resume
    # right now: a resumed session's own state file already exists, so ITS
    # hook skips this whole block and doesn't publish its new pointer until
    # the very end of its run (~10ms, measured) -- so a concurrent sweep that
    # lands inside that window won't see it here either, and could delete its
    # 30+-day-old state file, which then makes that resume's own pointer-write
    # gate (state file must exist) refuse to publish. Accepted: this makes
    # that one resume return null instead of full state, self-heals on the
    # very next tool call (a missing state file just looks like a brand-new
    # session), and needs two unrelated sessions' hooks to land within
    # milliseconds of each other -- closing it for good needs a lock around
    # the whole state-file lifecycle, not just this sweep, which is a bigger
    # change than this narrow, self-healing case has earned so far.
    # A pointer counts as naming a live session only if it actually verifies
    # (start time + boot id match the live process at that pid), the same
    # check the server applies before trusting one -- not just "some process
    # currently occupies this pid, and the file happens to name this
    # session." A stale pointer (pid reused by an unrelated process, wrong
    # start time) is harmless to the SERVER, which independently re-verifies
    # before ever trusting it -- but it would otherwise still pin this sweep
    # to keep a dead session's state file forever, silently defeating the
    # 30-day backstop it exists to provide. Reproduced directly: a
    # fabricated stale pointer (right session_id, wrong start time) let a
    # 31-day-old state file survive indefinitely before this check.
    # An array, not a space-separated string: `for x in $unquoted_var` runs
    # both word-splitting AND pathname expansion on it, so a live_sid holding
    # so much as a literal `*` would silently glob-expand against this
    # process's cwd when later iterated below. Every legitimate live_sid here
    # is a UUID (validated before any hook ever writes one), so this can't
    # happen through normal use -- but an array closes it completely rather
    # than trusting that invariant to keep holding, matching how the rest of
    # this file treats untrusted-shaped input (e.g. the UUID check on
    # session_id itself, right at the top).
    live_sessions=()
    for p in "$STATE_DIR"/current.*; do
        [ -e "$p" ] || continue
        pid=${p##*.}
        [[ "$pid" =~ ^[0-9]+$ ]] || continue
        live_sid="" live_start="" live_boot=""
        read -r live_sid live_start live_boot < "$p" 2>/dev/null
        [ -n "$live_sid" ] || continue
        read -r pstat 2>/dev/null < "/proc/$pid/stat" || continue
        read -ra pfields <<< "${pstat##*) }"
        # Require the boot id to match too, UNLESS THIS CALL's own read (just
        # above) failed: falling back to start-time-only there, rather than
        # treating "unknown" as a value that must match, avoids a transient
        # glitch on this one call wrongly sweeping some OTHER, genuinely live
        # session's state file (reproduced directly: a live pointer with a
        # real, correct boot id was excluded from live_sessions purely
        # because THIS call's own read happened to fail).
        #
        # Deliberately NOT symmetric: an earlier version of this also
        # exempted a CANDIDATE whose stored live_boot was "unknown" (from
        # whenever ITS OWN pointer was written), reasoning it was the same
        # kind of glitch. It isn't, and a native council review caught the
        # difference and reproduced it: this call's "unknown" is transient
        # and resolves itself on literally the next call, for everyone --
        # but a candidate's STORED "unknown" persists as long as that
        # session's pointer goes unwritten, which for an idle-for-weeks
        # session (this file's own comments elsewhere note tmux keeps these
        # alive that long) is a real window. Exempting it there would
        # permanently disable exactly the reboot/pid-reuse/coincidental-
        # start-time collision boot_id was added to catch, for that specific
        # pointer, for that whole window -- reproduced directly: a pointer
        # with a real, matching start time and a stored live_boot="unknown"
        # survived indefinitely even though THIS call's own boot_id read
        # succeeded and had a real value to compare against. A candidate
        # whose own write-time read glitched gets a fair, non-exempt check
        # like anyone else; it self-heals the same way -- on ITS OWN next
        # call, not on some other session's sweep giving it a permanent pass.
        boot_ok=false
        if [ "$boot_id" = "unknown" ] || [ "$live_boot" = "$boot_id" ]; then
            boot_ok=true
        fi
        if [ "$live_start" = "${pfields[19]}" ] && [ "$boot_ok" = true ]; then
            live_sessions+=("$live_sid")
        fi
    done
    while IFS= read -r f; do
        sid=${f##*/}; sid=${sid%.json}
        # A `case` pattern is a glob, and $sid comes from a filename -- every
        # writer of a *.json here validates session_id as a UUID first, so
        # this never matters in practice, but a plain string-equality loop
        # costs nothing extra and doesn't rely on that holding forever.
        is_live=false
        for candidate in "${live_sessions[@]}"; do
            if [ "$candidate" = "$sid" ]; then is_live=true; break; fi
        done
        [ "$is_live" = true ] && continue
        rm -f -- "$f"
    done < <(find "$STATE_DIR" -maxdepth 1 -name '*.json' -mtime +30 2>/dev/null)
fi

# --- Pointer: last, and gated on the state file actually being there ---------
# Rewritten on every call, which is what gives a resumed session (new claude
# pid, state file already there) its pointer. Gated on [ -f "$STATE_FILE" ],
# re-checked here rather than assumed from the block above succeeding: if jq
# or the mv failed just now, or fails on every future call (STATE_DIR out of
# space, permissions), publishing a pointer anyway would let the server return
# a session id with no launch_dir/project_path/git_branch -- exactly the
# incomplete answer the state-before-pointer ordering exists to prevent.
if [ -n "$pointer_line" ] && [ -f "$STATE_FILE" ]; then
    tmp="$STATE_DIR/.current.$$"
    if echo "$pointer_line" > "$tmp"; then
        mv "$tmp" "$STATE_DIR/current.$claude_pid" || rm -f "$tmp"
    else
        rm -f "$tmp"
    fi
fi

exit 0
