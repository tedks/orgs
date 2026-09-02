# Binding: Claude Code

How protocol roles map to Claude Code primitives. Other harnesses get their
own binding file; the protocol artifacts are identical across bindings —
that's the portability claim the cold-start audit tests.

| Protocol concept | Claude Code primitive |
|---|---|
| CTO / lead session | interactive session (or background job) in the project worktree |
| Worker (L3/L4) | `Agent` tool subagent; `model` set per work package (haiku/sonnet default, overridable up) |
| Continuation / takeover / huddle attendance | `subagent_type: "fork"` — inherits full context; model override for takeovers via fork + model shift |
| Judgment roles (review, necessity challenge, cold-start audit) | fresh subagent with the curated pack from the context manifest — never a fork |
| Inter-agent messaging | `SendMessage` / `ListAgents` (same machine); tmux `claude-send.sh` for interactive instances |
| Foreign council seats | `ask-agent` skill (`codex`, `agy`); warm chaining via `--resume <id>` + `--session-id-file` (dotfiles PR #105); identity-verify every round |
| Council review | `council-review` skill, per its host/provider seating matrix |
| Standup heartbeat | `/loop` (self-paced) or cron; event triggers convene directly |
| Deterministic fan-out (enumerated sprint, fixed task list) | `Workflow` tool — only for the mechanical middle; decomposition and redirection stay with the live lead |
| Team isolation | git worktrees per team/branch (bare-repo layout); packing lists via prompt assembly |
| Codex seat sessions | `codex exec resume <id> -` (append, single writer) / `codex exec fork <id> -` (non-mutating branch) |
| agy seat sessions | `--conversation <id>` headless; ids via `--log-file` scrape or `~/.gemini/antigravity-cli/conversations/` |

Prompt assembly rule (implements "heavily prompt for Boydian thought and
good engineering"): every role prompt begins with the DOCTRINE.md prompt
block verbatim, then the role's hat ("you are the L5 lead for entity X…"),
then the context manifest contents. The design doc always rides whole.

v0 note: this file is the only binding. Codex CLI and Antigravity bindings
are deferred until the first sprint proves the artifact set (the cold-start
audit may run on them read-only before then).
