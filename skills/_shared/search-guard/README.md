# Search guard

The classifier refuses agent-issued whole-tree searches of broad roots and
logs refusals under `${XDG_STATE_HOME:-$HOME/.local/state}/search-guard/log`.
It is used by the Claude `PreToolUse` hook and by PATH wrappers for `find`,
`grep`, and `rg`. The operator installs those entry points and supplies any
Codex exec-policy rules, ripgrep defaults, and alert thresholds separately.

The classifier derives the home root from `HOME`; `SEARCH_UNBOUNDED=1`
overrides a refusal. A depth of at most 3 bounds a walk. Runtime logs and
transcripts are private and do not belong in this source tree.

Use `search_guard.py check --cwd DIR` with command text on stdin to inspect a
classification. The `measure` subcommand replays local Claude and Codex logs
when an operator deliberately invokes it; it does not send them anywhere.
The wrapper accepts `SEARCH_GUARD_WRAPPED_NAME=find|grep|rg` when an installed
compatibility entry point delegates to it under another basename.

Tests use synthetic homes and fake tools. The public source contains no fleet
roots, host list, personal search log, or installed settings.
