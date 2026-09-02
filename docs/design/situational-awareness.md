# Design: situational awareness — keeping a running agent's OODA loop open

Status: **design only.** The primary v1 infrastructure blocker before a
multi-provider or long-running-agent sprint. Specify now; build when a real
sprint needs a long-running foreign worker, not before.

## Problem

Two orchestration models exist for driving an org agent:

- **Discrete-turn (outer loop):** every turn is an orchestrator-issued call
  (`codex exec resume <id> <prompt>`, `agy --conversation <id> <prompt>`,
  `claude -p`). The orchestrator owns the prompt, so injecting new
  information is just prepending to it before sending — *mutate before
  transmission*, no agent-side hook, uniform across providers, and with a
  delivery guarantee we construct (the message is in the prompt or it
  isn't). This case is solved.
- **Persistent-interactive (inner loop):** a long-running agent grinding its
  own edit → test → edit dev loop, generating turns without round-tripping
  to the orchestrator. There is no send for us to mutate. **This is the
  blocker** — and it is exactly where a standup needs to reach in and
  redirect a rabbit-holing agent.

The naive fix — instruct the agent to `check_inbox()` at the top of every
turn — fails for one fatal reason:

> **The agent you most need to redirect is definitionally the one that has
> stopped observing.** Rabbit-holing *is* a collapsed OODA loop — the agent
> spins Orient→Act→Act and skips the outward Observe. Asking it to
> voluntarily poll is asking the failed faculty to repair itself.

## Principle

> The agent must not be responsible for *deciding* to observe. The
> environment forces the observe at chokepoints the agent cannot avoid.

Corollary — separate the two things `check_inbox()` wrongly fuses:

- **What Observe returns** (the situation digest): fine as a *pull* — an MCP
  tool, a file read.
- **When Observe is forced** (the trigger): must be *pushed*, into channels
  the agent already cannot not-read.

This is the firewall principle applied to attention instead of dependencies:
physical enforcement over honor system.

## The primitive: `situational_awareness()`, not an inbox

It is the OODA **Observe** — "integrate the current outside world" — so the
digest carries everything that could change the agent's orientation, not just
messages:

- **standup guidance / redirects** (the headline case);
- **contract deltas** — a contract the agent is coding against was amended;
- **Crystal conflicts** — the agent's branch now collides with a peer's HEAD;
- **budget / tempo** — the agent is at 85% of the package's token budget;
- **dependency / peer status** — the thing it was blocked on just landed.

Key unification: **the tripwires already designed *are* forced observes.** The
stop-condition (3 failed tries → reorient), the budget tripwire, the Crystal
alert — each is the environment interrupting the agent with new world-state.
`situational_awareness()` is not new machinery bolted on; it is the *union*
of the tripwires into one "here is what changed, re-orient" injection
delivered at forced chokepoints.

## Chokepoints — how to force the Observe in the inner loop

The inner dev loop is edit → **run a tool** → read result → think. The agent
passes through tool calls constantly and **cannot not-read its own tool
output**. Co-opt the agent's Observe-of-its-own-action. Ranked by reliability:

1. **Tool-result piggyback + exit-code weaponization — strongest for the
   inner loop.** Wrap the tools the agent uses (test runner, build, git,
   shell) so their output carries a situation footer when the bus has
   something:
   ```
   FAILED: 3 tests…
   ━━ SITUATION ━━ Standup redirect: you are reimplementing rate-limiting
      that already exists behind contract C2. Stop; read huddle/…​.
   ```
   The agent ran the test to read the result — it *will* read the footer. On
   a HALT-severity item the wrapper **exits nonzero with the redirect as the
   failure**, weaponizing the agent's own error-handling reflex to force the
   reorient. Provider-agnostic; targets exactly the dev loop.
2. **Git-hook gate — the hard block.** `pre-commit` / `pre-push` run on the
   agent's own actions and can **refuse the commit until the agent
   acknowledges** the standup. The agent *will* commit (it is in the loop);
   the hook is a blocking chokepoint. Provider-agnostic.
3. **Cadence-forced observe — bounds rabbit-hole duration.** The tool wrapper
   counts calls; every Nth call (or M tokens) injects the digest
   unconditionally. Cannot guarantee voluntary observation, but *can*
   guarantee the environment forces one every K actions — capping how long a
   rabbit-hole runs blind. OODA made mechanical.
4. **Preempt-and-resume — the guaranteed one, and needed anyway.** For a
   redirect that must land: the orchestrator SIGINTs the agent and resumes it
   with the redirect **prepended** — collapsing the hard interactive case
   back into the clean mutate-before-send model. The in-flight turn is lost
   (squash/rollback per the speculative-work rules), but the Observe is
   certain. Reuses the **budget-tripwire's** own preempt-and-resume-with-
   context machinery, and *is* the fork-and-huddle endgame (parent works,
   huddle decides, "redirect" preempts).
5. **Harness-native interrupt — type into the running agent.** agy: **tmux
   send-keys** into the TUI (lands as if the user typed it). codex: the
   **`steer`** feature (present in its config — verify it injects a steering
   turn into a running session). Claude: `SendMessage` at the next turn
   boundary (native, but its delivery proved unreliable — see
   LESSONS 2026-09-02 "a silent seat"). tmux send-keys is the universal form;
   weakness is timing (lands between turns or queues).
6. **Voluntary `situational_awareness()` poll — baseline supplement only.**
   Keep it as the cheap happy-path the doctrine encourages, never the
   mechanism a redirect *relies* on.

## Recommended layered design

Layer by reliability, cheapest first:

- **Bus** — git-native addressed digest files (messages + state deltas). The
  shared substrate, provider-agnostic; the same file bus the ledger/status
  already use. Delivery is *constructed* (read → inject → on success mark
  delivered), not trusted to a transport — which fixes the dropped-channel
  class from LESSONS 2026-09-02.
- **Default force** — tool-result piggyback (1) + cadence (3): cheap, covers
  the common redirect, hits the inner loop directly.
- **Hard force** — git-hook gate (2) for HALT-severity redirects.
- **Guaranteed force** — preempt-and-resume (4), reusing the budget-tripwire
  machinery, for redirects that must land.
- **Digest access** — a `situational_awareness()` MCP tool (both codex and
  agy take MCP; so does Claude) so the agent can *also* pull on demand — but
  the trigger is always pushed.

## Provider notes

| Mechanism | Claude Code | codex | agy |
|---|---|---|---|
| Discrete-turn prepend | `claude -p` | `exec resume <id> <prompt>` | `--conversation <id> <prompt>` |
| MCP digest tool | ✅ | ✅ (`codex mcp`) | ✅ (`mcp_config.json`; smoke-test) |
| Native mid-session interrupt | `SendMessage` (unreliable delivery) | `steer` (verify) | tmux send-keys |
| Preempt + resume | Agent tool / stop + fork | SIGINT + `exec resume` | SIGINT + `--conversation` |
| Tool-piggyback / git-hook | provider-agnostic (environmental) | ← | ← |

## Scope and sequencing

Design only. This is the primary v1 blocker for long-running / multi-provider
sprints, alongside `binding-executable-review` and the codex/agy binding
files. Build order when a sprint needs it: the git bus + tool-piggyback
(default force) first, then the git-hook gate, then wire preempt-and-resume
to the existing budget tripwire, then the MCP digest tool last (interactive
pull). Do not build ahead of the first real long-running-agent sprint — but
specify it now so that sprint does not discover the gap mid-flight.
