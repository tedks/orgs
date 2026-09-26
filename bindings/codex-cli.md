# Binding: Codex CLI

How protocol roles map to Codex CLI primitives. The protocol artifacts are
identical across bindings; only the primitives differ. Read
[doctrine/ROLES.md](../doctrine/ROLES.md) for the hats and
[bindings/claude-code.md](claude-code.md) for the sibling binding.

Facts below were checked on 2026-09-26 against `codex-cli 0.157.1`,
`~/.codex/config.toml`, and the dotfiles `spawn-agent`, `ask-agent` and
`council-review` skills. A row marked **unverified** was not exercised for
this document.

| Protocol concept | Codex CLI primitive |
|---|---|
| CTO / lead session | Interactive `codex` in its own tmux window and git worktree, launched with `agent-spawn.sh SESSION:WINDOW codex DIR --model MODEL` (or `SPAWN_CODEX_MODEL`). The launcher adds `--no-alt-screen` so tmux scrollback keeps delivery receipts, and suppresses the startup update check for that process. |
| Worker | A native Codex subagent under the `multi_agent` feature (stable and on in 0.157.1), bounded by the `[agents]` table (`max_threads`, `max_depth`); or a spawned session in its own window and worktree when the worker must be steerable or outlive the lead's turn. The roster's worker bound applies either way; `[agents]` is a harness ceiling, not the roster. |
| Huddle attendance (carry your own context) | `codex exec fork <id>`: a headless, non-mutating branch of the attendee's session. The parent stays pristine. For an interactive branch a human can steer, `agent-spawn.sh ... --fork-session <id>` runs `codex fork` (see the skill's `references/codex-forks.md`). |
| Same-tier continuation of a running worker | `codex exec resume <id>` appends in place to the same thread, with a single active writer. Never resume a session another process is driving. For a live interactive worker, send the next task over `tmux-message` instead. |
| Takeover at a **higher tier** | Not a fork and not a resume: both keep the original model's thread. Spawn a fresh session with the higher model via `agent-spawn.sh --model`, packed from the implementer's branch, diff, PR thread, status entry and, where the reasoning matters, a transcript excerpt. The journey travels through committed artifacts. |
| Judgment roles (review, necessity challenge, cold-start audit) | A fresh session or a fresh native subagent with the curated pack. Never a fork or resume of the agent under review. |
| Inter-agent messaging | `tmux-message send TARGET 'text'` and `tmux-message read TARGET` (installed at `~/.bin/tmux-message`; skill entrypoint `spawn-agent/scripts/tmux-message.sh`). Success means a NEW submitted or queued receipt was observed; it is acceptance, not completion. `codex queue --thread` exists in 0.157.1 but the shared sender does not use it. |
| Foreign council seats | `ask-agent claude` and `ask-agent agy`, warm-chained across rounds with `--resume <id>` and `--session-id-file`; verify the yielded id every round. The Codex host fills the OpenAI seat with its own native subagent and never calls `ask-agent codex`. |
| Council review | The `council-review` skill, per its host/provider seating matrix. `codex exec` refuses to start outside a git repo or a trusted directory, so run from the worktree. |
| Standup heartbeat | Event-driven only. No scheduler for Codex lanes exists today, so a standup is a message the coordinator sends when an event or its own cadence calls for one. Do not claim a timer that is not running. |
| Deterministic fan-out | No Codex equivalent of a workflow runner is bound. Enumerated work goes to bounded subagents or spawned sessions briefed from a file. |
| Team isolation | Git worktrees per team or branch (bare-repo layout); packing lists via prompt assembly. |
| Compaction | Bare `/compact` delivered into the pane by a peer over `tmux-message`, after durable state is saved. `/compact` takes no inline argument; step-specific focus goes through the `experimental_compact_prompt_file` config override, as the fork launcher does. Completion is a new compaction record or a visible `Context compacted` event. `remote_compaction = true` is set in config, but 0.157.1 does not list that flag, so its effect is **unverified**. |
| Harness self-control | **Pending** the harness-control MCP (session-targeted compact, status, usage and exit with typed results). Until it lands, a session cannot compact or exit itself; it asks a peer with `COMPACT ME`. |
| Skills | `~/.codex/skills/<name>` symlinks installed by the dotfiles `install-codex-config` script. Shared skills resolve to the same `SKILL.md` Claude Code reads; never copy them. |
| Trust | `[projects."<path>"] trust_level = "trusted"` in `~/.codex/config.toml`. An interactive spawn into an untrusted directory stops at a trust prompt; never answer it with a task's Enter (modal behavior **unverified** for this document; the `codex exec` refusal is documented in `council-review`). |
| Sessions and resume | Rollouts are JSONL under `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl`. Resume interactively with `codex resume <id>`, headless with `codex exec resume <id>`. Record the id in the roster at spawn. |

Config flags named in older notes, as seen by 0.157.1: `multi_agent` is
stable and on; `steer` is listed as removed; `child_agents_md` and
`remote_compaction` are set in config but not listed. Treat the unlisted and
removed flags as no-ops until a release documents them.

Prompt assembly is the same as every binding: the DOCTRINE.md prompt block
verbatim, then the role's hat from ROLES.md, then the context manifest.

## Tiers and quota

Tiers are capabilities; the models are today's mapping, dated 2026-09-26.

| Tier | Anthropic (Claude Code) | OpenAI (Codex CLI) |
|---|---|---|
| Frontier | Claude Fable 5.1 | gpt-6-astra |
| Lead | Claude Opus 5.5 | gpt-6-sol |
| Implementer | Claude Sonnet 5 | gpt-6-luna |
| Utility | Claude Haiku 4.5 | **Unverified:** gpt-6-luna at `model_reasoning_effort` low, or gpt-5.6-terra (seen in session logs; the OpenAI catalog could not be listed from the CLI) |

Review seats are one per provider: Anthropic through `ask-agent claude`,
OpenAI through the host's native subagent, Google through `ask-agent agy`. An
unavailable foreign seat stays empty and is recorded as empty.

Quota rule (doctrine, *Provider budget*): spend first on the provider whose
weekly window resets soonest, and keep the providers' windows in phase.
Review seats spend before anything else does. Frontier capacity goes to
synthesis, integration and audit, not to routine edits. A quota reset never
revokes a pause.

## Lean operating mode

When the coordinator's own tokens are the scarce resource:

- A worker is a Codex session in its own tmux window and worktree, spawned
  with the roster's tier and briefed from a file. Its session id is recorded
  so it can be brought back for its own work.
- Messages to the coordinator take fixed forms and nothing else:
  `LANDED #<n> <sha>`; `<worker> (<window>): BLOCKED: <one line>`;
  `<worker> (<window>): NEEDS RULING: <one line>`;
  `<worker> (<window>): COMPACT ME`; the six-line standup reply; a one-line
  answer. The origin prefix is used only when the message does not already
  carry its origin.
- Workers message each other directly for dependencies. Nothing routes
  through the coordinator that needs no judgment.
- Compaction: the worker saves durable state, then sends `COMPACT ME`. A peer
  delivers bare `/compact` into its pane over `tmux-message` and confirms the
  compaction event. That bare `/compact` is the only harness command a peer
  types; an ordinary message asking the worker to compact runs nothing. This
  stays until the harness-control MCP lands.
- A finished lane follows the doctrine's retirement contract: thank it,
  verify its handoff shard (one file per session, never a shared append) is
  committed and pushed, request exit, and confirm exit and resource release.
  Migration to another model or provider is the same shard used as the
  successor's brief, spawned with `agent-spawn.sh` (`--model` sets the
  model for a Codex successor only; see the Claude Code binding for a
  Claude successor). New missions
  start in fresh lanes unless exact context continuity is justified.
