#!/bin/bash
# claude-send.sh - Send one message to a Claude/Codex agent tmux pane.
#
# Uses tmux screen polling as a conservative guard against composing human text.
# This is not atomic exclusion: a person can type between any two observations.
#
# Usage: claude-send.sh <window> [--submit-delay SEC] [--max-wait SEC]
#        [--render-wait SEC] [--poll-interval SEC] <message|--prompt-file FILE>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"
source "$SCRIPT_DIR/claude-pane-detect.sh"

usage() {
    echo "Usage: claude-send.sh <window> [--submit-delay SEC] [--max-wait SEC] [--render-wait SEC] [--poll-interval SEC] <message>" >&2
    echo "       claude-send.sh <window> [options] --prompt-file FILE" >&2
    echo "  --submit-delay SEC  seconds after paste before submit (integer 0-30; default 8)" >&2
    echo "  --stable-window SEC seconds of unchanged composer (integer 0-30; default submit-delay)" >&2
    echo "  --typed-command    type one validated single-line slash command into an empty composer" >&2
    echo "  --render-wait SEC   initial post-paste render budget (integer 1-30; default 1)" >&2
    echo "  --max-wait SEC      maximum wait for a stable composer (integer 1-600; default 30)" >&2
    echo "  --poll-interval SEC base poll interval (decimal 0.1-2; default 0.5); backoff caps at 8s" >&2
}
if (($# < 2)); then usage; exit 1; fi

window=$1; shift
submit_delay=8
typed_command=0
stable_window=
render_wait=1
max_wait=30
poll_interval=0.5
while (($#)); do
    case "$1" in
        --typed-command) typed_command=1; shift;;
        --stable-window|--submit-delay|--render-wait|--max-wait|--poll-interval)
            (($# >= 2)) || { echo "Error: $1 requires a value" >&2; exit 1; }
            option=$1; value=$2; shift 2
            case "$option" in
                --stable-window|--submit-delay|--render-wait)
                    minimum=0
                    if [[ "$option" == --render-wait ]]; then minimum=1; fi
                    [[ "$value" =~ ^[0-9]+$ && ${#value} -le 2 ]] || { echo "Error: $option requires an integer from $minimum to 30" >&2; exit 1; }
                    if ((10#$value < minimum || 10#$value > 30)); then echo "Error: $option requires an integer from $minimum to 30" >&2; exit 1; fi
                    if [[ "$option" == --stable-window ]]; then
                        stable_window=$((10#$value))
                    elif [[ "$option" == --submit-delay ]]; then
                        submit_delay=$((10#$value))
                    else
                        render_wait=$((10#$value))
                    fi;;
                --max-wait)
                    [[ "$value" =~ ^[0-9]+$ && ${#value} -le 3 ]] || { echo 'Error: --max-wait requires an integer from 1 to 600' >&2; exit 1; }
                    if ((10#$value < 1 || 10#$value > 600)); then echo 'Error: --max-wait requires an integer from 1 to 600' >&2; exit 1; fi
                    max_wait=$((10#$value));;
                --poll-interval)
                    [[ "$value" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ && ${#value} -le 5 ]] || { echo 'Error: --poll-interval requires a decimal from 0.1 to 2' >&2; exit 1; }
                    awk -v n="$value" 'BEGIN { exit !(n >= 0.1 && n <= 2) }' || { echo 'Error: --poll-interval requires a decimal from 0.1 to 2' >&2; exit 1; }
                    poll_interval=$value;;
            esac;;
        --prompt-file|-f)
            break;;
        *) break;;
    esac
done
if (($# < 1)); then echo 'Error: message or --prompt-file is required' >&2; exit 1; fi

stable_window=${stable_window:-$submit_delay}
observe_file=
harness_file=
stable_file=
expected_file=
append_file=
co_submit_fingerprint_file=
draft_harness=
co_submit_claude=0
stale_draft_length=0
clear_attempted=0
cleared_command_draft_length=0
prompt_file=''
cleanup_prompt=0
pending_dir=''
paste_started=0
pending_reported=0
buffer_loaded=0
buf_name="claude-send-$$"
cleanup() {
    if ((buffer_loaded)); then
        "${TMUX_CMD[@]}" delete-buffer -b "$buf_name" 2>/dev/null || true
    fi
    for scratch in "$harness_file" "$observe_file" "$stable_file" "$expected_file" "$append_file" "$co_submit_fingerprint_file"; do
        [[ -z "$scratch" ]] || rm -f -- "$scratch"
    done
    ((cleanup_prompt)) && rm -f -- "$prompt_file"
    [[ -n "$pending_dir" ]] && rmdir -- "$pending_dir" 2>/dev/null || true
}
trap cleanup EXIT
if [[ "$1" == --prompt-file || "$1" == -f ]]; then
    (($# == 2)) || { echo 'Error: --prompt-file requires exactly one path' >&2; exit 1; }
    input_file=$2
    [[ -f "$input_file" && -s "$input_file" ]] || { echo 'Error: prompt file must exist and be nonempty' >&2; exit 1; }
    prompt_file=$(mktemp /tmp/claude-send-prompt.XXXXXX)
    chmod 600 "$prompt_file"
    cleanup_prompt=1
    cp -- "$input_file" "$prompt_file"
else
    message="$*"
    [[ -n "$message" ]] || { echo 'Error: message is empty' >&2; exit 1; }
    prompt_file=$(mktemp /tmp/claude-send-prompt.XXXXXX)
    chmod 600 "$prompt_file"
    cleanup_prompt=1
    printf '%s' "$message" > "$prompt_file"
fi
python3 - "$prompt_file" "$typed_command" "$SCRIPT_DIR" <<'PY'
import importlib.util, pathlib, sys, unicodedata
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("styles", pathlib.Path(sys.argv[3]) / "claude-send-screen.py")
styles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(styles)
try:
    text = pathlib.Path(sys.argv[1]).read_bytes().decode("utf-8")
except (OSError, UnicodeError):
    raise SystemExit("Error: prompt must be UTF-8 text")
if not text.strip() or any(unicodedata.category(ch) == "Cc" and ch != "\n" for ch in text):
    raise SystemExit("Error: prompt must be nonblank text without control characters")
if any(line != line.rstrip(" \t") for line in text.splitlines()):
    raise SystemExit("Error: prompt lines may not end in spaces or tabs")
if sys.argv[2] == "1" and (
    len(text.encode("utf-8")) > 200 or text != text.rstrip() or text.endswith(";")
    or not styles.slash_command_syntax(text)
):
    raise SystemExit("Error: unsupported typed command")
PY

# Preserve the exact outgoing payload privately if delivery is deferred or its
# state becomes ambiguous. The path is reported; the payload is never printed.
preserve_pending() {
    local status=$1 reason=$2 stale_meta=''
    ((stale_draft_length == 0)) || stale_meta=" stale_draft_length=$stale_draft_length"
    ((clear_attempted == 0)) || stale_meta+=" clear_attempted=true"
    ((cleared_command_draft_length == 0)) || stale_meta+=" cleared_command_draft_length=$cleared_command_draft_length"
    pending_reported=1
    if [[ -z "$pending_dir" ]]; then
        state_dir="${XDG_STATE_HOME:-$HOME/.local/state}"
        if ! mkdir -p -- "$state_dir"; then
            cleanup_prompt=0
            printf 'status=%s reason=%s%s pending_file=%s retention=state-directory-failed\n' "$status" "$reason" "$stale_meta" "$prompt_file" >&2
            return 0
        fi
        pending_dir=$(mktemp -d "$state_dir/claude-send-pending.XXXXXX") || {
            cleanup_prompt=0
            printf 'status=%s reason=%s%s pending_file=%s retention=directory-create-failed\n' "$status" "$reason" "$stale_meta" "$prompt_file" >&2
            return 0
        }
        if ! chmod 700 "$pending_dir" || ! cp -- "$prompt_file" "$pending_dir/message" || ! chmod 600 "$pending_dir/message"; then
            rmdir -- "$pending_dir" 2>/dev/null || true
            pending_dir=''
            cleanup_prompt=0
            printf 'status=%s reason=%s%s pending_file=%s retention=copy-failed\n' "$status" "$reason" "$stale_meta" "$prompt_file" >&2
            return 0
        fi
    fi
    printf 'status=%s reason=%s%s pending_file=%s\n' "$status" "$reason" "$stale_meta" "$pending_dir/message" >&2
}
handle_signal() {
    local name=$1 code=$2 status=deferred
    ((paste_started || clear_attempted)) && status=ambiguous
    preserve_pending "$status" "signal-$name"
    exit "$code"
}
handle_exit() {
    local rc=$? status=deferred
    if ((cleanup_prompt && rc != 0 && !pending_reported)); then
        ((paste_started || clear_attempted)) && status=ambiguous
        preserve_pending "$status" "sender-exit-$rc" || true
    fi
    cleanup
    return "$rc"
}
trap handle_exit EXIT
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM
observe_file=$(mktemp /tmp/claude-send-observe.XXXXXX)
harness_file=$(mktemp /tmp/claude-send-harness.XXXXXX)
stable_file=$(mktemp /tmp/claude-send-stable.XXXXXX)
expected_file=$(mktemp /tmp/claude-send-expected.XXXXXX)
append_file=$(mktemp /tmp/claude-send-append.XXXXXX)
co_submit_fingerprint_file=$(mktemp /tmp/claude-send-co-submit.XXXXXX)
cp -- "$prompt_file" "$expected_file"
identity=$("$SCRIPT_DIR/tmux-resolve.sh" "$window") || { echo 'Error: failed to resolve tmux target' >&2; exit 1; }
[[ "$identity" =~ ^[0-9]+:%[0-9]+$ ]] || { echo 'Error: tmux returned an invalid target identity' >&2; exit 1; }
pane_id=${identity#*:}
lock_key=$(printf '%s' "$identity" | sha256sum | cut -d' ' -f1)
# The default must not depend on the caller's XDG environment: desktop, SSH,
# and systemd invocations that resolve to one pane share one lock namespace.
# Tests may supply a private directory, but all cooperating callers must use
# the same override.
lock_dir="${CLAUDE_SEND_LOCK_DIR:-/tmp/claude-send-locks-${UID}}"
umask 077
mkdir -p -- "$(dirname -- "$lock_dir")"
mkdir -m 700 -- "$lock_dir" 2>/dev/null || true
[[ -d "$lock_dir" && ! -L "$lock_dir" && "$(stat -c %u "$lock_dir")" == "$UID" ]] || { echo 'Error: unsafe lock directory' >&2; exit 1; }
chmod 700 "$lock_dir"
exec {lock_fd}>"$lock_dir/$lock_key.lock"
if ! flock -w 90 "$lock_fd"; then
    preserve_pending deferred target-lock-timeout
    exit 2
fi
screen_state() {
    local screen screen_raw cursor cursor_x cursor_y last_nonempty modal_status
    screen_raw=$("${TMUX_CMD[@]}" capture-pane -e -p -t "$pane_id" 2>/dev/null) || return 1
    screen=$(printf '%s' "$screen_raw" | python3 "$SCRIPT_DIR/claude-send-screen.py" --strip-ansi) || return 1
    cursor=$("${TMUX_CMD[@]}" display-message -p -t "$pane_id" '#{cursor_x}:#{cursor_y}' 2>/dev/null) || return 1
    [[ "$cursor" =~ ^([0-9]+):([0-9]+)$ ]] || { printf unknown; return; }
    cursor_x=${BASH_REMATCH[1]}; cursor_y=${BASH_REMATCH[2]}
    # Preserve the narrow pre-routing checks that protected Claude dialogs
    # even when quoted Codex output appears elsewhere in the pane.
    last_nonempty=$(printf '%s\n' "$screen" | awk 'NF { line=$0 } END { print line }')
    if [[ "$screen" == *'Update available!'* && "$last_nonempty" == *'Press enter to continue'* ]] || \
       [[ "$screen" == *'Do you trust the contents of this project?'* ]]; then
        printf modal; return
    fi
    if [[ ( "$screen" == *'Context '* || "$screen" == *'tab to queue message'* || "$screen" == *'  GPT-6-Sol · '* ) && "$screen" == *'› '* ]]; then
        printf codex > "$harness_file"
        printf '%s' "$screen_raw" | python3 "$SCRIPT_DIR/claude-send-screen.py" --observe-file "$observe_file" "$expected_file" "$cursor_x" "$cursor_y"
        return
    fi
    if claude_modal_active "$screen" "$cursor_y"; then
        printf modal; return
    else
        modal_status=$?
        ((modal_status == 1)) || { printf unknown; return; }
    fi
    claude_composer_ready "$screen" "$cursor_y" || { printf unknown; return; }
    printf claude > "$harness_file"
    if ((co_submit_claude)); then
        printf '%s' "$screen_raw" | python3 "$SCRIPT_DIR/claude-send-screen.py" --observe-file "$observe_file" --co-submit-draft-file "$stable_file" "$expected_file" "$cursor_x" "$cursor_y"
    else
        printf '%s' "$screen_raw" | python3 "$SCRIPT_DIR/claude-send-screen.py" --observe-file "$observe_file" "$expected_file" "$cursor_x" "$cursor_y"
    fi
}

# A bounded deadline avoids granting extra time after slow capture calls.
wait_start_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
delay=$poll_interval
previous_state=''
previous_harness=''
stable_start_ns=$wait_start_ns
while :; do
    state=$(screen_state 2>/dev/null || printf unknown)
    current_harness=$(<"$harness_file")
    now_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
    eligible=0
    [[ "$state" == empty || "$state" == command || "$state" == command-home || ( ( "$state" == draft || "$state" == draft-home ) && $typed_command == 0 ) ]] && eligible=1
    if ((eligible)) && [[ "$state" == "$previous_state" && "$current_harness" == "$previous_harness" ]] && cmp -s "$observe_file" "$stable_file"; then
        stable_ns=$((now_ns - stable_start_ns))
    else
        stable_start_ns=$now_ns
        stable_ns=0
    fi
    elapsed=$(awk -v n="$now_ns" -v s="$wait_start_ns" 'BEGIN { print (n-s)/1000000000 }')
    remaining=$(awk -v d="$max_wait" -v e="$elapsed" 'BEGIN { printf "%.3f",d-e }')
    awk -v r="$remaining" 'BEGIN { exit !(r > 0) }' || { preserve_pending deferred "composer-$state"; exit 2; }
    if ((eligible)) && [[ "$previous_state" == "$state" && "$current_harness" == "$previous_harness" ]] && ((stable_ns >= stable_window * 1000000000)) && cmp -s "$observe_file" "$stable_file"; then break; fi
    previous_state=$state
    previous_harness=$current_harness
    cp -- "$observe_file" "$stable_file"
    sleep_for=$(awk -v d="$delay" -v r="$remaining" 'BEGIN { if (d>r) d=r; printf "%.3f",d }')
    if ((eligible && stable_window > 0)); then
        sleep_for=$(awk -v d="$sleep_for" -v ns="$stable_ns" -v w="$stable_window" 'BEGIN { r=w-ns/1000000000; if (d>r) d=r; printf "%.3f",d }')
    fi
    sleep "$sleep_for"
    delay=$(awk -v d="$delay" 'BEGIN { n=d*2; if (n>8) n=8; printf "%.3f",n }')
done

# Recheck exact stable bytes immediately before appending; never overwrite drafts.
state=$(screen_state 2>/dev/null || printf unknown)
elapsed=$(python3 -c 'import time,sys; print((time.monotonic_ns()-int(sys.argv[1]))/1e9)' "$wait_start_ns")
remaining=$(awk -v d="$max_wait" -v e="$elapsed" 'BEGIN { printf "%.3f",d-e }')
awk -v r="$remaining" 'BEGIN { exit !(r > 0) }' || { preserve_pending deferred final-pre-paste-timeout; exit 2; }
if [[ "$state" != "$previous_state" || "$(<"$harness_file")" != "$previous_harness" ]] || ! cmp -s "$observe_file" "$stable_file"; then preserve_pending deferred "pre-paste-$state"; exit 2; fi
if [[ "$state" == draft-home || "$state" == command-home ]]; then
    end_state=${state%-home}
    stable_harness=$(<"$harness_file")
    "${TMUX_CMD[@]}" send-keys -t "$pane_id" End
    while :; do
        state=$(screen_state 2>/dev/null || printf unknown)
        elapsed=$(python3 -c 'import time,sys; print((time.monotonic_ns()-int(sys.argv[1]))/1e9)' "$wait_start_ns")
        remaining=$(awk -v d="$max_wait" -v e="$elapsed" 'BEGIN { printf "%.3f",d-e }')
        awk -v r="$remaining" 'BEGIN { exit !(r > 0) }' || { preserve_pending deferred cursor-navigation-unverified; exit 2; }
        if [[ "$state" == "$end_state" || "$state" == "$end_state-home" ]]; then
            if [[ "$(<"$harness_file")" != "$stable_harness" ]] || ! cmp -s "$observe_file" "$stable_file"; then
                preserve_pending deferred cursor-navigation-unverified
                exit 2
            fi
            [[ "$state" != "$end_state" ]] || break
        elif [[ "$state" != unknown ]]; then
            preserve_pending deferred cursor-navigation-unverified
            exit 2
        fi
        # Unchanged Home/unknown repaint receives no further keys.
        sleep_for=$(awk -v d="$poll_interval" -v r="$remaining" 'BEGIN { if (d>r) d=r; printf "%.3f",d }')
        sleep "$sleep_for"
    done
fi
if [[ "$state" == command ]]; then
    stable_harness=$(<"$harness_file")
    command_length=$(python3 -c 'import pathlib,sys; print(len(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")))' "$stable_file")
    clear_attempted=1
    if ! "${TMUX_CMD[@]}" send-keys -t "$pane_id" C-u; then
        preserve_pending ambiguous command-clear-failed
        exit 3
    fi
    while :; do
        state=$(screen_state 2>/dev/null || printf unknown)
        elapsed=$(python3 -c 'import time,sys; print((time.monotonic_ns()-int(sys.argv[1]))/1e9)' "$wait_start_ns")
        remaining=$(awk -v d="$max_wait" -v e="$elapsed" 'BEGIN { printf "%.3f",d-e }')
        awk -v r="$remaining" 'BEGIN { exit !(r > 0) }' || { preserve_pending ambiguous command-clear-unverified; exit 3; }
        if [[ "$state" == empty && "$(<"$harness_file")" == "$stable_harness" ]]; then
            cleared_command_draft_length=$command_length
            break
        fi
        if [[ "$state" != unknown ]] && { [[ "$state" != command || "$(<"$harness_file")" != "$stable_harness" ]] || ! cmp -s "$observe_file" "$stable_file"; }; then
            preserve_pending ambiguous command-clear-unverified
            exit 3
        fi
        # Incomplete repaint/unchanged command receives no further keys.
        sleep_for=$(awk -v d="$poll_interval" -v r="$remaining" 'BEGIN { if (d>r) d=r; printf "%.3f",d }')
        sleep "$sleep_for"
    done
    state=$(screen_state 2>/dev/null || printf unknown)
    elapsed=$(python3 -c 'import time,sys; print((time.monotonic_ns()-int(sys.argv[1]))/1e9)' "$wait_start_ns")
    if [[ "$state" != empty || "$(<"$harness_file")" != "$stable_harness" ]] || ! awk -v e="$elapsed" -v d="$max_wait" 'BEGIN { exit !(e < d) }'; then
        preserve_pending ambiguous input-changed-after-clear
        exit 3
    fi
fi
if [[ "$state" == draft ]]; then
    stale_draft_length=$(python3 -c 'import pathlib,sys; print(len(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")))' "$stable_file")
    draft_harness=$(<"$harness_file")
    { printf '\n'; cat "$prompt_file"; } > "$append_file"
    { cat "$stable_file"; cat "$append_file"; } > "$expected_file"
else
    draft_harness=$(<"$harness_file")
    cp -- "$prompt_file" "$append_file"
fi
if ((stale_draft_length)) && [[ "$draft_harness" == claude ]]; then
    co_submit_claude=1
fi

if ((typed_command)); then
    paste_started=1
    "${TMUX_CMD[@]}" send-keys -t "$pane_id" -l -- "$(<"$prompt_file")"
else
buffer_loaded=1
"${TMUX_CMD[@]}" load-buffer -b "$buf_name" "$append_file"
paste_started=1
if ! "${TMUX_CMD[@]}" paste-buffer -p -r -d -t "$pane_id" -b "$buf_name"; then
    preserve_pending ambiguous paste-command-failed
    exit 3
fi
buffer_loaded=0
fi

# Require exact visible ownership throughout the delay and again immediately
# before Enter. A changed/unreadable frame is ambiguous; never clear, repaste,
# or press Enter in that case. Agent generation outside the composer is allowed.
delay=$poll_interval
start_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
# Wait without keys for initial empty/unknown render frames. Unknown never
# authorizes Enter; a known mismatch or modal stops immediately. Once ownership
# is observed, every later transition must remain exact.
render_grace_ns=$((render_wait * 1000000000))
own_seen=0
while ((own_seen == 0)); do
    state=$(screen_state 2>/dev/null || printf unknown)
    if [[ "$state" == own ]]; then
        if ((co_submit_claude)); then
            [[ -s "$observe_file" ]] || { preserve_pending ambiguous combined-fingerprint-missing; exit 3; }
            cp -- "$observe_file" "$co_submit_fingerprint_file"
        fi
        elapsed_ns=$(python3 -c 'import time,sys; print(time.monotonic_ns()-int(sys.argv[1]))' "$start_ns")
        ((elapsed_ns < render_grace_ns)) || { preserve_pending ambiguous post-paste-render-timeout; exit 3; }
        own_seen=1
        break
    fi
    if [[ "$state" != empty && "$state" != unknown ]]; then
        preserve_pending ambiguous "post-paste-$state"
        exit 3
    fi
    elapsed_ns=$(python3 -c 'import time,sys; print(time.monotonic_ns()-int(sys.argv[1]))' "$start_ns")
    ((elapsed_ns < render_grace_ns)) || { preserve_pending ambiguous post-paste-render-timeout; exit 3; }
    remaining_ns=$((render_grace_ns - elapsed_ns))
    sleep_for=$(awk -v d="$poll_interval" -v r="$remaining_ns" 'BEGIN { r=r/1000000000; if (d>r) d=r; printf "%.3f",d }')
    sleep "$sleep_for"
done
while :; do
    state=$(screen_state 2>/dev/null || printf unknown)
    [[ "$state" == own ]] || { preserve_pending ambiguous "post-paste-$state"; exit 3; }
    if ((co_submit_claude)) && ! cmp -s "$observe_file" "$co_submit_fingerprint_file"; then
        preserve_pending ambiguous input-changed-after-paste
        exit 3
    fi
    elapsed=$(python3 -c 'import time,sys; print((time.monotonic_ns()-int(sys.argv[1]))/1e9)' "$start_ns")
    remaining=$(awk -v d="$submit_delay" -v e="$elapsed" 'BEGIN { printf "%.3f",d-e }')
    awk -v r="$remaining" 'BEGIN { exit !(r > 0) }' || break
    sleep_for=$(awk -v d="$poll_interval" -v r="$remaining" 'BEGIN { if (d>r) d=r; printf "%.3f",d }')
    sleep "$sleep_for"
done
state=$(screen_state 2>/dev/null || printf unknown)
[[ "$state" == own ]] || { preserve_pending ambiguous "pre-submit-$state"; exit 3; }
if ((co_submit_claude)) && ! cmp -s "$observe_file" "$co_submit_fingerprint_file"; then
    preserve_pending ambiguous input-changed-before-submit
    exit 3
fi
"${TMUX_CMD[@]}" send-keys -t "$pane_id" Enter
# A paste attempt remains irreversible even if reporting fails after Enter.
# Only a normal exit suppresses retention; never classify this phase deferred.
if ((cleared_command_draft_length)); then
    printf 'status=sent receipt=unverified clear_attempted=true cleared_command_draft_length=%s\n' "$cleared_command_draft_length"
elif ((stale_draft_length)); then
    printf 'status=sent receipt=unverified stale_draft_length=%s\n' "$stale_draft_length"
else
    printf 'status=sent receipt=unverified\n'
fi
