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

## Lean operating mode (observed 2026-09-23/24)

When the coordinator's own tokens are the scarce resource, the binding tightens:

- A worker is a Claude Code session in its own tmux window and git worktree, spawned with the strongest model and briefed from a file; its resume id is recorded so it can be brought back for its own work. Inside it, edits and gate runs go to Sonnet-class subagents with tight briefs and twenty-line reports; logs go to Haiku-class readers that return the failing assertion with file and line.
- Messages to the coordinator take fixed forms and nothing else: `LANDED #<n> <sha>`; `<worker> (<window>): BLOCKED: <one line>`; `<worker> (<window>): NEEDS RULING: <one line>`; `<worker> (<window>): COMPACT ME`; the six-line standup reply; a one-line answer. The origin prefix is used only when the message does not already carry its origin.
- Workers message each other directly for dependencies; nothing routes through the coordinator that needs no judgment.
- Compaction is sent into the worker's window as the `/compact <focus>` slash command by the coordinator, via the send helper, because a session cannot run a slash command on itself.
- Readiness is an event-driven table the coordinator keeps from `LANDED`, `BLOCKED` and `NEEDS RULING` messages, so a readiness report is a file read, not a reconstruction.
- A finished worker is thanked and writes its own entry in the off-duty waiting list (session id, working directory, window, role, exact resume command, what it would pick up, one or two things worth keeping), commits it, and exits. New work starts in a fresh worker.

A non-normative example from the chaos launch: seven lanes on Opus 5.5 in a `chaos` tmux session, briefed by file, councils and landings inside the lanes, sixty-six PRs on master in one day at about 0.45 percent of a weekly quota each, the coordinator's own share of spend at two percent.

v0 note: this file is the only binding. Codex CLI and Antigravity bindings
are deferred until the first sprint proves the artifact set (the cold-start
audit may run on them read-only before then).
