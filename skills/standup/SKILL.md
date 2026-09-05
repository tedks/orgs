---
name: orgs-standup
description: Situational awareness — force a running agent to observe outside-world updates at unavoidable chokepoints, and redirect or halt one that has drifted. Convened on triggers or a heartbeat; delivers steering through a bus that workers' dev-loop commands can't skip. The one mechanism prior art has no precedent for.
---

# orgs-standup — forced re-observation

The agent that needs redirecting is the one that stopped observing. So
observation is forced *environmentally*, at chokepoints an agent cannot skip —
never left to a rabbit-holing agent's volition. Prior art (MetaGPT, ChatDev,
AutoGen, Devin, OpenHands, Gas Town, LangGraph) has approval-gates and
stuck-detection, but **nothing that forces a healthy, still-progressing agent
to pause and check what changed.** This is that.

Tool: `tools/standup/` — `bus.sh` (git-native message bus, at-least-once
delivery), `guard.sh` (the forced-observe wrapper), `standup.sh` (observe /
redirect / halt).

## Forced observe

Workers run their dev-loop commands through
`tools/standup/guard.sh <agent-id> -- <cmd>`. The guard runs the command, then
samples the bus for pending steering **after** it, and forces a nonzero exit
(87) on a pending halt even when the command itself succeeded — so a redirect
or halt is pushed into the agent's view at a point it cannot rabbit-hole past.

## Convening

On a **trigger** — budget tripwire, stop condition, `crystal-conflict`, blocked
past the roster's threshold, an interface change — or on the roster's
**heartbeat**. Each accountable lead monitors the triggers for their entity.

## Run the standup

- **Observe:** `standup.sh observe` produces a compact digest — git log +
  status entries + stall detection — **never transcripts**. Inputs are the
  status entries and the event ledger since the last standup.
- **Redirect / halt:** post steering to the bus for the drifting agent; the
  chair facilitates, the adjudicator per ownership decides.
- **Outputs**, committed as `orgs-ledger` events: decisions, reassignments,
  deviation adjudications, redirects, contract-change proposals. Decisions are
  proposals until reconciled against head; invalidated speculative work is
  preserved, never auto-discarded.

## Standalone

This skill needs no org hierarchy — the bus + guard + observe loop run on any
repo. It is the piece a collaborator flagged as possibly "80% of the value at
20% of the effort," and it lifts out whole if that proves true.
