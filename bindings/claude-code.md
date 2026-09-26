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
| Inter-agent messaging | `SendMessage` (deliver) / `ListAgents` (enumerate) same machine; `tmux-message` (installed at `~/.bin/tmux-message`) for interactive instances in tmux. `claude-send.sh` is a legacy transport-only backend. |
| Foreign council seats | `ask-agent` skill (`codex`, `agy`); warm-chain a seat across rounds via its `--resume <id>` + `--session-id-file` options; identity-verify the yielded id every round |
| Council review | `council-review` skill, per its host/provider seating matrix |
| Standup heartbeat | `/loop` (self-paced) or cron; event triggers convene directly |
| Deterministic fan-out (enumerated sprint, fixed task list) | `Workflow` tool — only for the mechanical middle; decomposition and redirection stay with the live lead |
| Team isolation | git worktrees per team/branch (bare-repo layout); packing lists via prompt assembly |
| Handoff and migration | A retirement followed by a spawn. The outgoing agent's handoff shard becomes the successor's brief, and the successor is launched with `agent-spawn.sh` at the new tier or provider. See doctrine, *Quiet coordination and lifecycle*, and [doctrine/ROLES.md](../doctrine/ROLES.md). |
| Harness self-control | **Pending** the harness-control MCP. Until it lands, a session cannot compact itself: it asks with `COMPACT ME`, and a peer sends bare `/compact` over `tmux-message`. |
| Codex seat sessions | `codex exec resume <id> -` (append, single writer) / `codex exec fork <id> -` (non-mutating branch) |
| agy seat sessions | `--conversation <id>` headless; ids via `--log-file` scrape or `~/.gemini/antigravity-cli/conversations/` |

Prompt assembly rule (implements "heavily prompt for Boydian thought and
good engineering"): every role prompt begins with the DOCTRINE.md prompt
block verbatim, then the role's hat ("you are the L5 lead for entity X…"),
then the context manifest contents. The design doc always rides whole.

Bindings: this file and [bindings/codex-cli.md](codex-cli.md). An
Antigravity binding is still deferred.

## Tiers and quota

Tiers are capabilities; the models are today's mapping, dated 2026-09-26.
Record the model actually selected in the roster.

| Tier | Anthropic (Claude Code) | OpenAI (Codex CLI) |
|---|---|---|
| Frontier | Claude Fable 5.1 | gpt-6-astra |
| Lead | Claude Opus 5.5 | gpt-6-sol |
| Implementer | Claude Sonnet 5 | gpt-6-luna |
| Utility | Claude Haiku 4.5 | **Unverified:** gpt-6-luna at `model_reasoning_effort` low, or gpt-5.6-terra (seen in session logs; the OpenAI catalog could not be listed from the CLI) |

Review seats are one per provider: Anthropic through the host's native
subagent, OpenAI through `ask-agent codex`, Google through `ask-agent agy`.
An unavailable foreign seat stays empty and is recorded as empty.

Quota rule (doctrine, *Provider budget*): spend first on the provider whose
weekly window resets soonest, and keep the providers' windows in phase.
Review seats spend before anything else does. Frontier capacity goes to
synthesis, integration and audit, not to routine edits. A quota reset never
revokes a pause.

## Lean operating mode (observed 2026-09-23/24)

When the coordinator's own tokens are the scarce resource, the binding tightens:

- A worker is a Claude Code session in its own tmux window and git worktree, spawned with the capability selected in the roster and briefed from a file; its resume id is recorded so it can be brought back for its own work. Inside it, bounded tactical subagents use tight briefs and concise acceptance reports. Model tiers and concurrency come from the roster, not this historical example.
- Messages to the coordinator take fixed forms and nothing else: `LANDED #<n> <sha>`; `<worker> (<window>): BLOCKED: <one line>`; `<worker> (<window>): NEEDS RULING: <one line>`; `<worker> (<window>): COMPACT ME`; the six-line standup reply; a one-line answer. The origin prefix is used only when the message does not already carry its origin.
- Workers message each other directly for dependencies; nothing routes through the coordinator that needs no judgment.
- Compaction is sent into the worker's window as bare `/compact` after durable state is saved (long focus text may be delivered as an ordinary message, not a slash-command argument). A session cannot run a slash command on itself, so `COMPACT ME` asks a peer to send it over `tmux-message` and confirm the compaction event. This stays until the harness-control MCP lands.
- Readiness is an event-driven table the coordinator keeps from `LANDED`, `BLOCKED` and `NEEDS RULING` messages, so a readiness report is a file read, not a reconstruction.
- A finished lane follows the doctrine's retirement contract and STATES lane
  lifecycle: thank it, verify its handoff shard (one file per session, never
  a shared append) is committed and pushed, then request exit through the
  binding and confirm resource release. Never infer
  retirement from the sender's exit code. New missions start in fresh lanes
  unless exact context continuity is explicitly justified.
- The installed dotfiles `spawn-agent` delivery helper owns typing protection,
  bounded backoff and submission mechanics. Follow its documented outcomes;
  inspect application receipt separately. Before sending, protect human or
  unknown composer input and modals; output generation alone does not prohibit
  pending delivery. Mixed input stops submission. Tmux screen polling cannot
  guarantee atomic exclusion. Do not assume the helper enforces a contract
  until its reviewed version is installed and verified; defer if protection
  or receipt cannot be established. Portable policy is in doctrine, not a
  second sender implementation here.
- Final replies follow controller quiescence, with continuing children named
  accurately. Routine events update records; urgent blockers still surface.

A non-normative example from the chaos launch: seven lanes on Opus 5.5 in a `chaos` tmux session, briefed by file, councils and landings inside the lanes, sixty-six PRs on master in one day at about 0.45 percent of a weekly quota each, the coordinator's own share of spend at two percent.
