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

# Any Claude modal that must stop an automated paste. Deliberately BROAD --
# "No, exit" is shared with the bypass-permissions responsibility dialog, and
# that is correct here: the spawner should refuse on any modal, not just the
# trust one.
#
# Matching is on SHORT fragments. Claude re-flows the dialog to the pane width,
# and tmux sizes a session to its SMALLEST attached client, so a long literal
# silently stops matching on a narrow terminal -- exactly when a paste would be
# most damaging. A false positive only refuses to act; a false negative pastes
# into the dialog. Fail closed.
claude_trust_modal_active() {
    local active_tail
    active_tail=$(printf '%s\n' "$1" | tail -n 25)
    [[ "$active_tail" == *"Quick safety check"* || \
       "$active_tail" == *"Yes, I trust this folder"* || \
       "$active_tail" == *"No, exit"* ]]
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
    local active_tail
    active_tail=$(printf '%s\n' "$1" | tail -n 25)
    # A dialog on screen is never a ready composer, at any width.
    if claude_trust_modal_active "$1"; then
        return 1
    fi
    printf '%s\n' "$active_tail" | grep -q '─' && \
        printf '%s\n' "$active_tail" | grep -q '❯'
}
