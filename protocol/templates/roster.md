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

- **Heartbeat:** <default: every 45 minutes of active work; material events trigger
  immediate attention, task reports trigger immediate diff review>
- **Blocked threshold:** <default: blocked longer than one heartbeat →
  convene>
- **Monitor (who watches the triggers):** <default: each accountable lead
  for their entity's packages>

## Lane authority and resources

Record each lane's mission/package, session and worktree, authority envelope,
stop conditions and escalation destination; selected capability/model/provider;
maximum concurrent tactical workers (default two); review-seat budget;
acceptance evidence and PR/audit links; latest event id and next standup due.
Track file/host leases by exact scope, holder and resource/run id, with peer
agreement before acquisition and an explicit release receipt. A request or
silence does not transfer a lease. Resumption reconciles stale leases with
the holder before reuse. Retired lanes leave the active cadence roster;
private resumable handoffs are referenced only by sanitized receipts.
