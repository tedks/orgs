# shellcheck shell=bash
# claude-pane-detect.sh - shared Claude Code pane classifiers. SOURCE, don't run.
#
# Lives apart from its callers so agent-spawn.sh (which must never paste into a
# dialog) and claude-trust-dir.sh --verify (which needs to know WHICH dialog is
# up) cannot drift. A tripwire built on a private copy of the thing it polices
# is worth very little.
#
# WARNING: THE DEFAULT BUTTON IS BUILD-SPECIFIC. DO NOT ASSUME EITHER WAY.
#
#   v2.1.261:  ❯ No, exit                    / Yes, I trust this folder
#   v2.1.220:  ❯ 1. Yes, I trust this folder / 2. No, exit
#
# Both were observed on one machine on the same day; an auto-update re-pointed
# the `claude` symlink between them. So a blind Enter into this dialog may
# DECLINE on one build and silently GRANT trust to an unvetted directory on
# another. Never reason about what an accidental keystroke "would only" do --
# the point of these classifiers is that no keystroke is ever sent.
#
# The fragments below appear in BOTH layouts, so detection fails closed on both.
# Note also that --verify cannot catch this class of drift: both layouts present
# as a prompt, so a prediction-vs-observation check compares equal.

# Shared frame-aware classifier also used by tmux-message.py. Known status
# footers cannot become modals merely because they say "esc to cancel".
claude_modal_active() {
    local script_dir result
    script_dir=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)
    if [[ -n ${2:-} ]]; then
        result=$(printf '%s' "$1" | python3 "$script_dir/claude-send-screen.py" --dialog-active "$2") || return 2
    else
        result=$(printf '%s' "$1" | python3 "$script_dir/claude-send-screen.py" --dialog-active) || return 2
    fi
    [[ "$result" == modal ]]
}

# The TRUST dialog specifically, for callers that must distinguish it from the
# bypass-permissions dialog rather than merely refuse to act. Drops the shared
# "No, exit" fragment; keeps only wording unique to the trust prompt. Callers
# must render wide enough that these survive re-flow -- --verify sizes its own
# pane precisely so it can rely on that.
claude_trust_dialog_specific() {
    local active_tail
    active_tail=$(printf '%s\n' "$1" | tail -n 25)
    [[ "$active_tail" == *"Quick safety check"* || \
       "$active_tail" == *"Yes, I trust this folder"* ]]
}

# Claude's composer, established from positive evidence a dialog cannot supply.
# The "❯" glyph alone is NOT evidence: dialogs draw it as a selection cursor, so
# requiring only that (plus the absence of a footer that wraps out of view) let
# a wrapped dialog read as a live composer. Verified against live Claude: a real
# composer draws both box rules at widths 100, 60, 40, 33 and 25.
claude_composer_ready() {
    local modal_status result script_dir
    # A dialog at the cursor is never a ready composer, at any width.
    if claude_modal_active "$1" "${2:-}"; then
        return 1
    else
        # A failed classifier cannot turn a dialog into a ready composer.
        modal_status=$?
        ((modal_status == 1)) || return 1
    fi
    script_dir=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)
    if [[ -n ${2:-} ]]; then
        result=$(printf '%s' "$1" | python3 "$script_dir/claude-send-screen.py" --composer-frame "$2") || return 1
    else
        result=$(printf '%s' "$1" | python3 "$script_dir/claude-send-screen.py" --composer-frame) || return 1
    fi
    [[ "$result" == composer ]]
}
