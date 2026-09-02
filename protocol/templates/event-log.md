# Event ledger conventions

Append-only, one file per sprint: `events/<sprint-id>.md`. One entry per
event, newest last. Never edited retroactively — corrections are new events
referencing the old. Projections (interpretation register, case state,
current-contract view) are derived views; in v0 they are maintained by hand
at standup/retro and must cite the ledger entries they summarize.

Entry format:

```
## <seq> · <ISO timestamp> · <type>
- actor: <role> (<model>)
- based_on: <sha> [· applied_at: <sha>]
- refs: <work package / contract / huddle / finding ids>
<one-to-few lines of body>
```

Types: `deviation`, `huddle-convened`, `huddle-decided`, `huddle-reconciled`,
`standup`, `escalation`, `interpretation-filed`, `interpretation-ruled`,
`docs-bug`, `amendment-proposed`, `review-finding`, `necessity-challenge`,
`state-change` (work package transitions), `lesson`.

Deviation entries additionally carry: what bent · why · rollback operation
(or `read — n/a`) · adjudication (appended by standup as a new event).
