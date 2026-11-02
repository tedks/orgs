#!/bin/bash
# agent-spawn.sh - Spawn an AI agent in a tmux window (interactive mode)
#
# Usage: agent-spawn.sh <session:window> <agent> [directory] [prompt]
#        agent-spawn.sh <session:window> <agent> [directory] --prompt-file <file>
#
# Agents: claude, codex, agy (Antigravity CLI)
#
# Options:
#   -f, --prompt-file <file>          Read prompt from file (avoids ARG_MAX)
#   -F, --fork-session <uuid>         Fork this Codex session interactively
#       --compact-prompt-file <file>  Compact inherited history before the task
#       --compact-timeout <seconds>   Compaction timeout (default: 600)
#       --rollout-path-file <file>    Record the child Codex rollout path
#       --recap-cursor-file <file>    Record where recap watching should begin
#       --startup-cursor-file <file> Record the cursor before fork compaction
#       --codex-bin <executable>     Codex executable (default: codex on PATH)
#       --model <model>              Claude or Codex model (default: harness configuration)
#
# Automatically targets the correct tmux server socket when run inside tmux.
# Override with SPAWN_TMUX_SOCKET or SPAWN_TMUX_LABEL env vars.
#
# All task and /compact input goes through tmux-message. Fork metadata and
# optional completion watchers are separate from message transport.
#
# Examples:
#   agent-spawn.sh chaos:review claude ./project "Review auth module"
#   agent-spawn.sh chaos:codex-help codex . "Help me refactor this"
#   agent-spawn.sh chaos:review claude ./project --prompt-file /tmp/prompt.txt
#   agent-spawn.sh chaos:design codex ./project --fork-session UUID --prompt-file /tmp/prompt.txt

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tmux-ctx.sh"

usage() {
    echo "Usage: agent-spawn.sh <session:window> <agent> [directory] [prompt]" >&2
    echo "       agent-spawn.sh <session:window> <agent> [directory] --prompt-file <file>" >&2
    echo "  session:window: tmux target (e.g., 'chaos:review')" >&2
    echo "  agent: claude, codex, agy" >&2
    echo "  directory: working directory (default: current)" >&2
    echo "  prompt: initial prompt for the agent" >&2
    echo "  --prompt-file: read prompt from file (avoids ARG_MAX)" >&2
    echo "  --trust: pre-grant Claude Code workspace trust for <directory> (claude only)" >&2
    echo "  --fork-session: interactively fork a Codex session UUID" >&2
    echo "  --compact-prompt-file: compact inherited history with this prompt before the task" >&2
    echo "  --compact-timeout: seconds to wait for compaction receipt and structured completion" >&2
    echo "  --rollout-path-file: atomically write the child Codex rollout path" >&2
    echo "  --recap-cursor-file: atomically write the safe JSONL recap start offset" >&2
    echo "  --startup-cursor-file: atomically write the pre-compaction JSONL offset" >&2
    echo "  --codex-bin: executable path/name (or SPAWN_CODEX_BIN; default codex)" >&2
    echo "  --model: Claude or Codex model (SPAWN_CODEX_MODEL defaults Codex only)" >&2
    exit 1
}

if [[ $# -lt 2 ]]; then
    usage
fi

target="$1"
agent="$2"
shift 2

# Parse remaining args: [directory] [prompt] or --prompt-file <file>
# --prompt-file can appear anywhere in the remaining args.
prompt_file=""
prompt=""
directory="."
trust_directory=0
fork_session=""
compact_prompt_file=""
compact_timeout=600
compact_timeout_set=""
rollout_path_file=""
recap_cursor_file=""
startup_cursor_file=""
codex_bin="${SPAWN_CODEX_BIN:-$(agent_skills_get harness.codex_bin)}"
codex_model="${SPAWN_CODEX_MODEL:-}"
codex_bin_set=""
model=""
_cleanup_prompt_file=""
_cleanup_rollout_output=""
_cleanup_cursor_output=""
_cleanup_startup_output=""
_cleanup_compact_file=""
_cleanup_fork_task=""

# Trap to clean up temp files on exit/interrupt (only files we created).
# Set early so failure paths during parsing don't leak temp files.
# An EXIT trap's status BECOMES the script's, so cleanup must be unable to
# fail. Without `return 0` every no-prompt spawn -- where the guard is simply
# false -- reported failure after succeeding; without `|| true` a failing rm
# would kill the trap under `set -e` before it got there.
cleanup() {
    if [[ -n "$_cleanup_prompt_file" ]]; then rm -f "$_cleanup_prompt_file" || true; fi
    if [[ -n "$_cleanup_rollout_output" ]]; then rm -f "$_cleanup_rollout_output" || true; fi
    if [[ -n "$_cleanup_cursor_output" ]]; then rm -f "$_cleanup_cursor_output" || true; fi
    if [[ -n "$_cleanup_startup_output" ]]; then rm -f "$_cleanup_startup_output" || true; fi
    if [[ -n "$_cleanup_compact_file" ]]; then rm -f "$_cleanup_compact_file" || true; fi
    if [[ -n "$_cleanup_fork_task" ]]; then rm -f "$_cleanup_fork_task" || true; fi
    return 0
}
trap cleanup EXIT

positional=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --codex-bin|--model)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "Error: $1 requires a value" >&2
                exit 1
            fi
            if [[ "$1" == --codex-bin ]]; then
                codex_bin="$2"
                codex_bin_set=1
            else
                model="$2"
            fi
            shift 2
            ;;
        --trust)
            trust_directory=1
            shift
            ;;
        --prompt-file|-f)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "Error: --prompt-file requires a file path" >&2
                exit 1
            fi
            prompt_file="$2"
            if [[ ! -f "$prompt_file" ]]; then
                echo "Error: prompt file not found: $prompt_file" >&2
                exit 1
            fi
            if [[ ! -s "$prompt_file" ]]; then
                echo "Error: prompt file is empty: $prompt_file" >&2
                exit 1
            fi
            shift 2
            ;;
        --fork-session|-F)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "Error: --fork-session requires a Codex session UUID" >&2
                exit 1
            fi
            fork_session="$2"
            shift 2
            ;;
        --compact-prompt-file)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "Error: --compact-prompt-file requires a file path" >&2
                exit 1
            fi
            compact_prompt_file="$2"
            if [[ ! -f "$compact_prompt_file" ]]; then
                echo "Error: compaction prompt file not found: $compact_prompt_file" >&2
                exit 1
            fi
            shift 2
            ;;
        --compact-timeout)
            if [[ $# -lt 2 || ! "$2" =~ ^[0-9]+$ || "$2" -eq 0 ]]; then
                echo "Error: --compact-timeout requires a positive integer" >&2
                exit 1
            fi
            compact_timeout="$2"
            compact_timeout_set=1
            shift 2
            ;;
        --rollout-path-file)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "Error: --rollout-path-file requires a file path" >&2
                exit 1
            fi
            rollout_path_file="$2"
            shift 2
            ;;
        --recap-cursor-file)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "Error: --recap-cursor-file requires a file path" >&2
                exit 1
            fi
            recap_cursor_file="$2"
            shift 2
            ;;
        --startup-cursor-file)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "Error: --startup-cursor-file requires a file path" >&2
                exit 1
            fi
            startup_cursor_file="$2"
            shift 2
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done

# Positional args: [directory] [prompt]
if [[ ${#positional[@]} -ge 1 ]]; then
    directory="${positional[0]}"
fi
if [[ ${#positional[@]} -ge 2 ]]; then
    prompt="${positional[1]}"
fi

requested_directory="$directory"
if ! directory=$(CDPATH='' cd -- "$requested_directory" 2>/dev/null && pwd); then
    echo "Error: working directory does not exist or is not accessible: $requested_directory" >&2
    exit 1
fi

# Parse session and window from target
session="${target%%:*}"
window="${target#*:}"

# Validate agent
case "$agent" in
    claude|codex|agy) ;;
    *)
        echo "Unknown agent: $agent" >&2
        echo "Supported agents: claude, codex, agy" >&2
        exit 1
        ;;
esac

if [[ "$agent" == agy && ( -n "$prompt_file" || -n "$prompt" ) ]]; then
    echo "Error: agy task delivery is not yet supported by the shared tmux guard; launch without a prompt." >&2
    exit 1
fi

if [[ -n "$codex_bin_set" && "$agent" != codex ]]; then
    echo "Error: --codex-bin applies to codex only" >&2
    exit 1
fi
if [[ -n "$model" && "$agent" == agy ]]; then
    echo "Error: --model supports claude and codex only" >&2
    exit 1
fi
if [[ "$agent" == codex && -n "$model" ]]; then codex_model="$model"; fi
if [[ "$agent" == codex ]]; then
    codex_bin=$(command -v -- "$codex_bin") || {
        echo "Error: Codex executable not found" >&2
        exit 1
    }
    if [[ ! -f "$codex_bin" || ! -x "$codex_bin" ]]; then
        echo "Error: --codex-bin must resolve to an executable file" >&2
        exit 1
    fi
    codex_bin="$(CDPATH='' cd -- "$(dirname -- "$codex_bin")" && pwd)/$(basename -- "$codex_bin")"
fi

if [[ "$trust_directory" -eq 1 && "$agent" != "claude" ]]; then
    echo "Error: --trust applies to claude only; agy and codex keep their own trust stores." >&2
    exit 1
fi

if [[ -n "$fork_session" ]]; then
    if [[ "$agent" != "codex" ]]; then
        echo "Error: --fork-session is currently supported only for codex" >&2
        exit 1
    fi
    if [[ ! "$fork_session" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]]; then
        echo "Error: --fork-session requires a UUID, got: $fork_session" >&2
        exit 1
    fi
fi

if [[ -n "$compact_prompt_file" ]]; then
    if [[ "$agent" != "codex" || -z "$fork_session" ]]; then
        echo "Error: --compact-prompt-file requires a Codex --fork-session launch" >&2
        exit 1
    fi
    if [[ ! -s "$compact_prompt_file" ]]; then
        echo "Error: compaction prompt file is empty: $compact_prompt_file" >&2
        exit 1
    fi
    if [[ -z "$prompt_file" && -z "$prompt" ]]; then
        echo "Error: launch-time compaction requires a task prompt to deliver afterward" >&2
        exit 1
    fi
fi

if [[ -n "$rollout_path_file" && ( "$agent" != "codex" || -z "$fork_session" ) ]]; then
    echo "Error: --rollout-path-file requires a Codex --fork-session launch" >&2
    exit 1
fi
if [[ -n "$rollout_path_file" && -z "$prompt_file" && -z "$prompt" ]]; then
    echo "Error: --rollout-path-file requires a task prompt in the fork workflow" >&2
    exit 1
fi
if [[ -n "$recap_cursor_file" && -z "$rollout_path_file" ]]; then
    echo "Error: --recap-cursor-file requires --rollout-path-file" >&2
    exit 1
fi
if [[ -n "$compact_timeout_set" && -z "$compact_prompt_file" ]]; then
    echo "Error: --compact-timeout requires --compact-prompt-file" >&2
    exit 1
fi
if [[ -n "$startup_cursor_file" && ( -z "$compact_prompt_file" || -z "$rollout_path_file" ) ]]; then
    echo "Error: --startup-cursor-file requires --compact-prompt-file and --rollout-path-file" >&2
    exit 1
fi

# Normalize prompt to a file if provided as positional arg
if [[ -n "$prompt" && -z "$prompt_file" ]]; then
    prompt_file=$(mktemp /tmp/spawn-agent-prompt.XXXXXX)
    _cleanup_prompt_file="$prompt_file"
    printf '%s' "$prompt" > "$prompt_file"
fi

# Canonicalize prompt_file to absolute path
if [[ -n "$prompt_file" ]]; then
    prompt_file="$(CDPATH='' cd -- "$(dirname -- "$prompt_file")" && pwd)/$(basename -- "$prompt_file")"
fi

if [[ -n "$fork_session" && -n "$prompt_file" ]]; then
    # Keep compaction and later delivery on the same assignment even if the
    # caller edits their task file while this child is starting.
    _cleanup_fork_task=$(mktemp /tmp/spawn-agent-fork-task.XXXXXX)
    cp -- "$prompt_file" "$_cleanup_fork_task"
    prompt_file="$_cleanup_fork_task"
    python3 "$SCRIPT_DIR/codex-fork-task.py" preflight "$prompt_file"
fi

if [[ -n "$compact_prompt_file" ]]; then
    compact_dir=$(CDPATH='' cd -- "$(dirname -- "$compact_prompt_file")" && pwd) || {
        echo "Error: compaction prompt directory does not exist: $(dirname -- "$compact_prompt_file")" >&2
        exit 1
    }
    compact_prompt_file="$compact_dir/$(basename -- "$compact_prompt_file")"
    if [[ "$compact_prompt_file" =~ [[:cntrl:]] ]]; then
        echo "Error: compaction prompt path cannot contain control characters" >&2
        exit 1
    fi
    # Snapshot the policy + task before the child starts. Its shell owns this
    # private file for the child's entire lifetime, including later compactions.
    _cleanup_compact_file=$(mktemp /tmp/spawn-agent-compact.XXXXXX)
    python3 "$SCRIPT_DIR/codex-fork-task.py" compact \
        "$compact_prompt_file" "$prompt_file" "$_cleanup_compact_file"
    compact_prompt_file="$_cleanup_compact_file"
fi

if [[ -n "$rollout_path_file" ]]; then
    rollout_dir=$(CDPATH='' cd -- "$(dirname -- "$rollout_path_file")" && pwd) || {
        echo "Error: rollout path directory does not exist: $(dirname -- "$rollout_path_file")" >&2
        exit 1
    }
    rollout_path_file="$rollout_dir/$(basename -- "$rollout_path_file")"
fi

if [[ -n "$recap_cursor_file" ]]; then
    cursor_dir=$(CDPATH='' cd -- "$(dirname -- "$recap_cursor_file")" && pwd) || {
        echo "Error: recap cursor directory does not exist: $(dirname -- "$recap_cursor_file")" >&2
        exit 1
    }
    recap_cursor_file="$cursor_dir/$(basename -- "$recap_cursor_file")"
fi

if [[ -n "$startup_cursor_file" ]]; then
    startup_dir=$(CDPATH='' cd -- "$(dirname -- "$startup_cursor_file")" && pwd) || {
        echo "Error: startup cursor directory does not exist" >&2
        exit 1
    }
    startup_cursor_file="$startup_dir/$(basename -- "$startup_cursor_file")"
    if [[ -d "$startup_cursor_file" || "$startup_cursor_file" == "$rollout_path_file" || \
          "$startup_cursor_file" == "$recap_cursor_file" ]]; then
        echo "Error: startup cursor must be a separate receipt file" >&2
        exit 1
    fi
fi

# Build one shell-escaped command string for tmux. A bare `codex fork` is the
# interactive transcript-preserving command; `codex exec fork` is headless and
# therefore intentionally does not belong here. Explicit -C avoids Codex's
# current-vs-saved-directory chooser, which is another modal where an automated
# Enter would be unsafe.
# --no-daemon keeps a Codex session in its own process: a client of the shared
# app-server daemon holds no rollout, so retirement could never bind it. Pass
# it only when this binary's own help for the subcommand lists it; older CLIs
# (0.146 has none) reject unknown flags. Without it the launch proceeds as
# before. That is not shown to be in-process: such a CLI that attaches to a
# daemon leaves the lane unbindable, and retirement then stays pending.
codex_has_no_daemon() {
    local help bound=()
    # macOS has no coreutils timeout; clap's --help returns at once anyway.
    if command -v timeout >/dev/null; then bound=(timeout 20); fi
    help=$("${bound[@]}" "$codex_bin" "$@" --help 2>/dev/null) || return 1
    # An option line, optionally after a clap short alias (`-n, --no-daemon`);
    # a description sentence that mentions the flag never matches.
    grep -qE '^[[:space:]]*(-[[:alnum:]],[[:space:]]+)?--no-daemon([[:space:],=<[]|$)' <<<"$help"
}
agent_command=("$agent")
if [[ "$agent" == claude && -n "$model" ]]; then agent_command+=(--model "$model"); fi
if [[ "$agent" == "codex" && -z "$fork_session" ]]; then
    # Managed agent windows must not stop at an update chooser. Keep this a
    # process-local override: ordinary Codex launches still perform their
    # normal update check, and no global configuration is changed.
    # Preserve tmux scrollback so long submitted messages remain observable.
    no_daemon=(); if codex_has_no_daemon; then no_daemon=(--no-daemon); fi
    agent_command=("$codex_bin" "${no_daemon[@]}" --no-alt-screen -c check_for_update_on_startup=false)
    if [[ -n "$codex_model" ]]; then agent_command+=(-m "$codex_model"); fi
fi
if [[ -n "$fork_session" ]]; then
    no_daemon=(); if codex_has_no_daemon fork; then no_daemon=(--no-daemon); fi
    agent_command=("$codex_bin" fork "${no_daemon[@]}" --no-alt-screen -c check_for_update_on_startup=false)
    if [[ -n "$codex_model" ]]; then agent_command+=(-m "$codex_model"); fi
    if [[ -n "$compact_prompt_file" ]]; then
        # Pass only the path in argv, never the prompt body. TOML basic-string
        # escaping handles spaces, quotes, and backslashes without touching
        # the user's global Codex configuration.
        toml_compact_path=${compact_prompt_file//\\/\\\\}
        toml_compact_path=${toml_compact_path//\"/\\\"}
        agent_command+=(-c "experimental_compact_prompt_file=\"$toml_compact_path\"")
    fi
    agent_command+=(-C "$directory" "$fork_session")
fi
printf -v agent_shell_command '%q ' "${agent_command[@]}"
if [[ -n "$_cleanup_compact_file" ]]; then
    printf -v compact_cleanup 'rm -f -- %q' "$_cleanup_compact_file"
    printf -v compact_trap 'trap %q EXIT; ' "$compact_cleanup"
    agent_shell_command="$compact_trap$agent_shell_command"
fi

# Granting workspace trust happens here, before launch, and only because the
# caller asked for it -- never by answering a modal after the fact.
if [[ "$trust_directory" -eq 1 ]]; then
    if ! "$SCRIPT_DIR/claude-trust-dir.sh" "$directory"; then
        echo "Error: could not grant workspace trust for $directory; not launching." >&2
        exit 1
    fi
fi

# Start only after options and fork task validation.
if ! "${TMUX_CMD[@]}" has-session -t "$session" 2>/dev/null; then
    echo "Creating tmux session: $session" >&2
    "${TMUX_CMD[@]}" new-session -d -s "$session"
fi
pane_id=$("${TMUX_CMD[@]}" new-window -P -F '#{pane_id}' -t "$session" -n "$window" -c "$directory" "$agent_shell_command")
[[ "$pane_id" =~ ^%[0-9]+$ ]] || { echo "Error: invalid spawned pane identity" >&2; exit 1; }
_cleanup_compact_file="" # child shell now owns cleanup, including failed delivery

if [[ -n "$prompt_file" ]]; then
    if [[ "$agent" == "codex" && -n "$fork_session" ]]; then
        rollout_path=$("$SCRIPT_DIR/codex-rollout-path.sh" \
            --exclude-session "$fork_session" "$pane_id") || {
            echo "Error: could not resolve the child rollout; task prompt not sent." >&2
            echo "  The child remains running and un-tasked in $target." >&2
            exit 1
        }
        python3 "$SCRIPT_DIR/codex-fork-task.py" child "$rollout_path" "$fork_session" >/dev/null
        if [[ -n "$rollout_path_file" ]]; then
            _cleanup_rollout_output=$(mktemp "$rollout_dir/.codex-rollout.XXXXXX")
            chmod 600 "$_cleanup_rollout_output"
            printf '%s\n' "$rollout_path" > "$_cleanup_rollout_output"
            mv -f -- "$_cleanup_rollout_output" "$rollout_path_file"
            _cleanup_rollout_output=""
        fi
    fi

    if [[ -n "$compact_prompt_file" ]]; then
        compact_after=$("$SCRIPT_DIR/codex-jsonl-watch.py" cursor "$rollout_path")
        if [[ -n "$startup_cursor_file" ]]; then
            _cleanup_startup_output=$(mktemp "$startup_dir/.codex-startup.XXXXXX")
            chmod 600 "$_cleanup_startup_output"
            printf '%s\n' "$compact_after" > "$_cleanup_startup_output"
            mv -f -- "$_cleanup_startup_output" "$startup_cursor_file"
            _cleanup_startup_output=""
        fi
        if "$SCRIPT_DIR/tmux-message.sh" send "$pane_id" --max-wait 30 --receipt-wait "$compact_timeout" '/compact'; then
            :
        else
            status=$?
            echo "Error: /compact delivery unconfirmed; task not sent. Inspect $target before retrying." >&2
            exit "$status"
        fi
        echo "Waiting for Codex to finish the requested history compaction..." >&2
        if ! "$SCRIPT_DIR/codex-jsonl-watch.py" compaction \
            "$rollout_path" "$compact_after" "$compact_timeout"; then
            echo "Error: Codex did not report completed compaction; task prompt not sent." >&2
            echo "  The child remains running and un-tasked in $target; inspect or close it." >&2
            echo "  If Codex was upgraded, verify its compaction config/event compatibility." >&2
            exit 1
        fi
    fi

    if [[ -n "$recap_cursor_file" ]]; then
        recap_after=$("$SCRIPT_DIR/codex-jsonl-watch.py" cursor "$rollout_path")
        _cleanup_cursor_output=$(mktemp "$cursor_dir/.codex-cursor.XXXXXX")
        chmod 600 "$_cleanup_cursor_output"
        printf '%s\n' "$recap_after" > "$_cleanup_cursor_output"
        mv -f -- "$_cleanup_cursor_output" "$recap_cursor_file"
        _cleanup_cursor_output=""
    fi

    if "$SCRIPT_DIR/tmux-message.sh" send "$pane_id" --max-wait 30 --prompt-file "$prompt_file"; then
        echo "Spawned $agent in $target ($pane_id, dir: $directory); task delivery confirmed"
        exit 0
    else
        status=$?
        echo "Error: task transport failed; child remains in $target ($pane_id). Inspect before retrying." >&2
        exit "$status"
    fi
fi

echo "Spawned $agent in $target (dir: $directory)"
