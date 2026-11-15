#!/bin/sh
# search-guard — Claude Code PreToolUse hook for Bash, Grep and Glob.
#
# Denies a whole-tree search of a broad root (~, ~/Projects, /, /home, /nix,
# /tmp) with a reason that says how to scope it, and logs the refusal to
# ~/.local/state/search-guard/log for the tripwire. The rules live in
# skills/_shared/search-guard/search_guard.py; this file finds it and fails open.
#
# Claude's Bash snapshot defines find and grep as shell functions, so the
# ~/.bin wrappers never see those; this hook sees the command text first.
# A failure to classify is an allow: no python3, no module, malformed input.
# A failure to log a refusal already decided is not one of these -- the deny
# still happens; see search_guard.py.

input=$(cat)
# Cheap prefilter: nothing that could be a search, nothing to decide.
case "$input" in
    *find*|*rg*|*grep*|*'"Grep"'*|*'"Glob"'*) ;;
    *) exit 0 ;;
esac

self=$(readlink -f "$0" 2>/dev/null) || exit 0
module="${self%/hooks/*}/search-guard/search_guard.py"
[ -f "$module" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
printf '%s' "$input" | python3 "$module" hook 2>/dev/null
exit 0
