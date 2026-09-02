# Binding: Claude Code

How protocol roles map to Claude Code primitives. Other harnesses get their
own binding file; the protocol artifacts are identical across bindings —
that's the portability claim the cold-start audit tests.

| Protocol concept | Claude Code primitive |
|---|---|
| CTO / lead session | interactive session (or background job) in the project worktree |
| Worker (L3/L4) | `Agent` tool subagent; `model` set per work package (haiku/sonnet default, overridable up) |
| Huddle attendance (carry your own context) | the attending agent forks **itself** — `subagent_type: "fork"` inherits the forker's full context (and runs on the forker's model; a `model` override is ignored). Correct here: a huddle needs the attendee's context, not a tier change. |
| Same-tier continuation of a running worker | `SendMessage` to the live subagent (keeps its context and model), or a self-`fork` to branch it |
| Takeover at a **higher tier** | **not** a fork — a fork runs on the forker's model, so it cannot raise tier, and it inherits the *lead's* context, not the implementer's. Spawn a fresh higher-tier `Agent` packed with the implementer's branch, diff, PR thread, and status entry (and, where the reasoning matters, an excerpt of its transcript). The implementer's *journey* travels via those committed artifacts, not via context inheritance. |
| Judgment roles (review, necessity challenge, cold-start audit) | fresh subagent with the curated pack from the context manifest — never a fork of the agent under review. A review *seat* may still be warm-chained across rounds so it carries its own prior-round context: a foreign seat via `ask-agent --resume` (Foreign council seats row); a native Claude seat by `SendMessage` to the same still-live review subagent, or a fresh subagent re-packed with its prior findings. |
| Inter-agent messaging | `SendMessage` (deliver) / `ListAgents` (enumerate) same machine; tmux `claude-send.sh` for interactive instances |
| Foreign council seats | `ask-agent` skill (`codex`, `agy`); warm-chain a seat across rounds via its `--resume <id>` + `--session-id-file` options; identity-verify the yielded id every round |
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
