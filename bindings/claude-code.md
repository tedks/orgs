# Binding: Claude Code

How protocol roles map to Claude Code primitives. Other harnesses get their
own binding file; the protocol artifacts are identical across bindings —
that's the portability claim the cold-start audit tests.

| Protocol concept | Claude Code primitive |
|---|---|
| CTO / lead session | interactive session (or background job) in the project worktree |
| Worker (L3/L4; Implementer or Utility tier) | `Agent` tool subagent; `model` set per work package from the tier table below (Sonnet for Implementer, Haiku for Utility by default, overridable up) |
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
| Handoff and migration | Ordinary retirement follows DONE; an explicitly authorized pause or stop can also end the lane's assignment, leaving unfinished package work paused. A model/provider migration is the only case where an open package's shard can brief a successor. A CTO's own migration waits on `orgs-cto-self-migration-approver`. Before the outgoing lane pushes its shard, the controller records the intended successor provider and model argument and confirms the target differs from the outgoing lane by provider or normalized model argument. The `retire.sh --handoff` workflow launches without the shard, then confirms the live provider and selected model argument match that target. It verifies the shard's exact bytes before briefing. Otherwise the shard is not used as a successor brief; the package remains unassigned and its approving authority decides whether to assign a new owner. No work resumes before that assignment. The outgoing lane's package authority ends at the successful push; the controller records the new owner and assigns a fresh bounded mission before the successor acts. A tier mismatch still goes to the CTO, who decides tier per lane (ROLES.md), before briefing. Nobody fixes it by typing into the successor's pane. `retire.sh --handoff` wraps the published launcher, which accepts `--model` for Claude and Codex. See doctrine, *Quiet coordination and lifecycle*, and [doctrine/ROLES.md](../doctrine/ROLES.md). Same-provider selector and alias rules are in [DOCTRINE.md#quiet-coordination-and-lifecycle](../doctrine/DOCTRINE.md#quiet-coordination-and-lifecycle). |
| Harness self-control | **Pending** the harness-control MCP. Until it lands, a session cannot compact or exit itself: it asks with `COMPACT ME`, and a peer sends bare `/compact` over `tmux-message`; after the shard push, a peer types bare `/exit` only if the agent chooses to leave and asks for it (see Lean operating mode). |
| Codex seat sessions | `codex exec resume <id> -` (append, single writer) / `codex exec fork <id> -` (non-mutating branch) |
| agy seat sessions | `--conversation <id>` headless; ids via `--log-file` scrape or `~/.gemini/antigravity-cli/conversations/` |

Prompt assembly rule (implements "heavily prompt for Boydian thought and
good engineering"): every role prompt begins with the DOCTRINE.md prompt
block verbatim, then the role's hat ("you are the L5 lead for entity X…"; L-levels are the README's org levels, tiers are in ROLES.md),
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
An unavailable foreign seat stays empty and is recorded as empty. Seats run at
the Lead tier: the native seat is spawned with the Lead model explicitly
(Claude: `model: opus`; Codex: gpt-6-sol), foreign seats with `ask-agent
<cli> -m <lead model>`; a host must never let a seat inherit its own
Frontier model (CEO ruling, 2026-10-13).

Quota rule (doctrine, *Provider budget*): spend first on the provider whose
weekly window resets soonest, and keep the providers' windows in phase.
Review seats spend before anything else does. Frontier capacity goes to
synthesis, integration and audit, not to routine edits. A quota reset never
revokes a pause.

## Lean operating mode (observed 2026-09-23/24)

When the coordinator's own tokens are the scarce resource, the binding tightens:

- A worker is a Claude Code session in its own tmux window and git worktree, spawned with the capability selected in the roster and briefed from a file; its resume id is recorded so it can be brought back for its own work. Inside it, bounded tactical subagents use tight briefs and concise acceptance reports. Model tiers and concurrency come from the roster, not this historical example.
- Messages to the coordinator take fixed forms and nothing else: `LANDED #<n> <sha>`; `<worker> (<window>): BLOCKED: <one line>`; `<worker> (<window>): NEEDS RULING: <one line>`; `<worker> (<window>): COMPACT ME`; `DONE` with the remaining gaps named; the six-line standup reply; a one-line answer. The origin prefix is used only when the message does not already carry its origin.
- Workers message each other directly for dependencies; nothing routes through the coordinator that needs no judgment.
- Compaction is sent into the worker's window as bare `/compact` after durable state is saved (long focus text may be delivered as an ordinary message, not a slash-command argument). A session cannot run a slash command on itself, so `COMPACT ME` asks a peer to send it over `tmux-message` and confirm the compaction event. This stays until the harness-control MCP lands.
- Readiness is an event-driven table the coordinator keeps from `LANDED`, `BLOCKED` and `NEEDS RULING` messages, so a readiness report is a file read, not a reconstruction.
- A finished lane follows the doctrine's retirement contract and STATES lane
  lifecycle: complete the mission at DONE, or end the lane's assignment with
  an explicitly authorized pause or stop that leaves unfinished package work
  paused. Write the one-per-session shard, push it to the approved private
  remote. A successful push begins retirement and gives the agent its own
  time; later controller verification and receipt bookkeeping do not delay or
  reverse it. Verify exact bytes before sending a requested exit; this check
  does not hold the agent's off-duty time. Before a migration push, the
  controller records the intended successor provider and model argument and
  confirms the target differs from the outgoing lane by provider or normalized
  model argument.
  After launch, and before the successor receives the shard as a brief or a
  package mission, the controller confirms the live provider and selected
  model argument match the intended target. Otherwise the shard is not used as
  a successor brief; the package
  remains unassigned and its approving authority decides whether to assign a
  new owner. No work resumes before that assignment. A model/provider migration
  is the only case where an open package's shard can brief a successor. Only if
  the agent chooses to leave and asks for exit may a peer type bare `/exit` into
  the lane's empty composer over `tmux-message`, under the same input-protection checks
  as `/compact`. The receipt is the pane's process ending, observed; never a
  kill. Confirm resource release before marking the
  lane RETIRED. Never infer process end from the sender's exit code. This
  stays until the harness-control MCP lands. New missions start in fresh
  lanes unless exact context continuity is explicitly justified.
- Retirement shards and receipts are pushed from a temporary worktree at the freshly fetched remote master commit, never committed in the shared checkout, and verified against a fresh remote fetch.
- The local vendored `spawn-agent` delivery helper owns typing protection,
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
