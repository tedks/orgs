---
name: orgs-ledger
description: Append to the org's event log and maintain status entries. Every orgs skill records its state transitions, deviations, and decisions here. Sharded per actor, ids <actor>:<seq>, causal ordering by an event chain (not wall-clock). This is the org's memory during a sprint.
---

# orgs-ledger — the event log

The ledger is the sprint's durable memory: what happened, in what causal
order, and why. Every skill appends to it. It is what lets a standup, a
takeover, or a cold-start audit reconstruct state from committed artifacts
alone.

Templates: `protocol/templates/event-log.md`, `protocol/templates/status.md`.
States and transitions: `protocol/STATES.md`.

## Event log

- **Sharded per actor:** `events/<sprint-id>/<actor-id>.md`. Each actor
  appends only to its own shard, so parallel workers never contend.
- **Event id:** `<actor-id>:<local-seq>` (e.g. `worker-engine:2`).
- **Causal order** comes from the event chain: `refs` carries the predecessor
  event id, not a wall-clock time. `based_on` stays a git sha (what the event
  was computed against). Do not order the sprint by timestamps.
- **Event kinds** include: `state-change`, `deviation`, `interpretation-filed`,
  `docs-bug`, `crystal-conflict`, `huddle-convened`/`-decided`/`-reconciled`,
  `takeover`, `lesson`. Use the kind the STATES table names for the transition.

## Status entries

`status/<package-id>.md` per the status template: current task, last commit,
budget burned, blocked-on. Update on claim, every push, block/unblock, and
each budget quarter. Status is the compact live state a standup reads — never
a transcript.

## Deviations

Every bent rule gets a one-line `deviation` event as it happens: what bent,
why, rollback. The deviation log doubles as the rabbit-hole tripwire and as
the evidence base for amendments at retro.

## Reconciliation

Decisions (from standup/huddle) are **proposals** until their accountable owner
reconciles them against head (`based_on` → `applied_at`). Invalidated
speculative work is preserved and dispositioned by its owner, never
auto-discarded.
