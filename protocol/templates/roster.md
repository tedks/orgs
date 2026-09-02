# Roster: <project / sprint id>

Instantiated at sizing (RUNBOOK §2) as `org/ROSTER.md`, updated whenever
hats move. This is where STATES.md owner references resolve: a cold-started
agent finds *who* is authorized for a transition here, and *what* transition
is next in STATES.md plus the ledger.

## Hats

| Hat | Held by (agent/session) | Notes |
|---|---|---|
| CEO | <human> | rulings; loosening below doctrine defaults |
| CTO / spec doc owner | | spec merges, amendment adjudication |
| Accountable lead — <entity> | | one row per entity; decomposition, reviews, deviation adjudication, retro |
| Integration owner | | merges, keeps main green against boundary tests |
| Escalation owner | | case state, dedup, authority routing |

One agent may hold many hats (hats, not headcount); the review hat always
gets a fresh context regardless.

## Standup parameters

- **Heartbeat:** <default: every 30 minutes of active work, or on any PR /
  escalation / Crystal-conflict event, whichever first>
- **Blocked threshold:** <default: blocked longer than one heartbeat →
  convene>
- **Monitor (who watches the triggers):** <default: each accountable lead
  for their entity's packages>
