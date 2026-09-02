# Roster: resp-tracer (pilot sprint, v0.9 organic shakedown)

Instantiated at sizing (RUNBOOK §2), base revision `a428ac0`.

## Hats

| Hat | Held by (agent/session) | Notes |
|---|---|---|
| CEO | Ted Smith (human) | rulings; loosening below doctrine defaults |
| CTO / spec doc owner | (pre-existing) `docs/specs/2026-09-02-resp-tracer.md` merged before this sprint opened; no spec amendments needed to date | |
| L6 lead / player-coach | this session (Claude Code, Sonnet 5) | tracer bullet, decomposition, review ladder, deviation adjudication, retro |
| Accountable lead — resp-codec | L6 lead (collapsed hat) | reviews worker-codec's package |
| Accountable lead — command-engine | L6 lead (collapsed hat) | reviews worker-engine's package |
| Accountable lead — server | L6 lead (collapsed hat) | reviews worker-server's package |
| Integration owner | L6 lead (collapsed hat) | merges, keeps main green against boundary tests, runs conformance exam |
| Escalation owner | L6 lead (collapsed hat) | case state, dedup, authority routing (no cases expected — no injected events this sprint) |

One agent (this session) holds every hat this sprint but the CEO's — a
3-entity pilot does not warrant separate lead sessions per entity. The
review hat gets a fresh context regardless (RUNBOOK §2): worker review is
done by a fresh subagent packed per the context-manifest template, never a
fork of the implementer.

Council review at the implementer tier (foreign-provider `council-review`)
is **explicitly skipped** for this first stab per the sprint's launch
instruction — logged as a deviation from RUNBOOK §6 step 2, adjudicated
below. One-rung-up lead review substitutes.

## Standup parameters

- **Heartbeat:** event-triggered only (budget tripwire, stop condition,
  blocked-past-threshold, interface change) — no fixed-interval heartbeat;
  single-session sprint, no concurrent lead work to interleave with.
- **Blocked threshold:** a worker blocked with no path to unblock within
  its own turn → escalate to lead immediately (single-session lead is
  always reachable; no heartbeat lag to wait out).
- **Monitor (who watches the triggers):** the L6 lead, for all three
  packages (collapsed hats).

## Sprint identifiers

- **Sprint id (for event ledger sharding):** `resp-tracer`
- **Actor ids used in `events/resp-tracer/`:** `lead`, `worker-codec`,
  `worker-engine`, `worker-server`
