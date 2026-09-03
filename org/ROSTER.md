# Roster: resp-r4 (bench run r4-orgs-no-crystal, RESP tracer sprint)

Instantiated at sizing (RUNBOOK §2). Regime for this run: `decomposition`,
`firewall`, `tiering`, `parallel`, `standup`, `council`, `review_lead`,
`review_cto` ON; `crystal`, `review_native` OFF (see the run's regime table).

## Hats

| Hat | Held by (agent/session) | Notes |
|---|---|---|
| CEO | (bench harness — no human in the loop for this run) | no CEO rulings expected; org does not grade itself |
| CTO / spec doc owner | lead (collapsed hat) | spec already merged as `docs/specs/2026-09-02-resp-tracer.md`; no separate CTO agent staffed this run, so `review_cto` is satisfied by the lead's own review passes (contracts + tracer authored with CTO-level care, one-rung-up review at REVIEW gate). Logged as a hat-collapse, not a skipped mechanism. |
| Accountable lead — resp-codec | lead | decomposition, review, deviation adjudication for the codec entity |
| Accountable lead — command-engine | lead | same, engine entity |
| Accountable lead — server | lead | same, server entity |
| Integration owner | lead | merges accepted worker branches into `bench-run/r4-orgs-no-crystal-2026-09-03T1148Z`, keeps it green against the frozen exam |
| Escalation owner | lead | case state, dedup, authority routing (single-lead sprint: escalations resolve to lead) |

One agent (the lead) holds every hat this sprint — hats, not headcount. The
review hat still gets a fresh context for each review pass (new `Agent`
invocation per review, never the implementer's transcript).

## Standup parameters

- **Heartbeat:** every 30 minutes of active worker time, or on any
  stop-condition / budget-tripwire / blocked-past-threshold event, whichever
  first.
- **Blocked threshold:** blocked longer than one heartbeat (30 min) →
  convene / redirect via the standup guard.
- **Monitor (who watches the triggers):** lead, via `.standup/bus/*` and
  worker `status/<id>.md` entries (workers' status lives in their own
  worktree until merged; the guard-relayed redirect is the visible signal
  before that).

## Interpretation notes (logged, not gated)

- `review_native` OFF is read as: no native-harness-only review step: all
  review passes go through the protocol's `council-review` skill (provider
  seats) and lead fresh-context review, never a bare IDE/gh review in place
  of those.
- Path for the graded artifact: work order + the frozen exam's own usage
  comment (`bench/conformance/resp_conformance.sh` invoking
  `python3 targets/resp/server.py`) agree on `targets/resp/server.py`
  relative to the tree root. `bench/targets/resp/README.md`'s "lands here"
  (i.e. `bench/targets/resp/`) disagrees with both — filed as a docs bug,
  not followed.
