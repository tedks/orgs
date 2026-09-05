---
name: orgs-huddle
description: On-demand escalation at the reversibility gate. Any agent convenes a huddle when intent-vs-instruction is unclear or a gated deviation needs a prior decision. It writes a stable issue key so agents at different shas converge on one huddle; attendees are forks carrying their own context; the adjudicator per ownership decides. The decision is a proposal until reconciled against head.
---

# orgs-huddle — escalate at the reversibility gate

Not a step in the sprint — a thing any agent reaches for. The doctrine gate:
huddle **first** only when you can't name your rollback, would change something
across a contract boundary, or would exceed owned scope. Otherwise you deviate
and log (`orgs-ledger`); the huddle is for the genuinely irreversible or
cross-boundary call.

## Convening

- Write an **issue key** — a short, stable slug for the question (e.g.
  `retry-idempotency` on boundary C2). **Reuse it across revisions** so two
  agents who hit the same question at different shas converge on **one** huddle
  rather than opening duplicates.
- **Attendees are forks carrying their own context** (`subagent_type: "fork"` —
  a huddle needs the attendee's context, not a tier change). An attendee may
  **request escalation** but never convenes a further huddle.
- **Fork and keep working while you ask** — the answer arrives stale, and
  speculative work done meanwhile is preserved, not wasted.

## Deciding

- The **chair** facilitates; the **adjudicator per ownership** decides: the
  lowest lead with authority over the thing in conflict; one rung up if that
  lead's own call is what's disputed; a collapsed-hat adjudicator takes a
  **fresh** context.
- The decision is a **proposal** until its accountable owner **reconciles it
  against head** (`based_on` → `applied_at`). Invalidated speculative work is
  preserved and dispositioned by its owner, never auto-discarded.

Committed as `huddle-convened` / `huddle-decided` / `huddle-reconciled` events.
