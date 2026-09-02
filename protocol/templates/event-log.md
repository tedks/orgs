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

Types: `deviation`, `deviation-adjudicated`, `huddle-convened`,
`huddle-decided`, `huddle-reconciled`, `standup`, `escalation`,
`interpretation-filed`, `interpretation-ruled`, `docs-bug`,
`amendment-proposed`, `review-finding`, `review-seat-outcome`,
`review-clean`, `necessity-challenge`, `state-change`, `lesson`.

`state-change` is generic across every STATES.md artifact type — body reads
`<artifact-type>:<id> <FROM>→<TO>` plus the required evidence — so any
lifecycle (work package, sprint, review round, escalation, amendment) can be
reconstructed from the ledger alone, which is what the cold-start audit
requires.

Deviation entries additionally carry: what bent · why · rollback operation
(or `read — n/a`). Adjudication is a separate `deviation-adjudicated` event
referencing the deviation's seq: justified / unjustified · one line why.

`review-seat-outcome` records one seat's result for one round (seat · round
· `findings: <ids>` or `no-finding`), written by the accountable lead as
scribe — external seats have no repo access. `review-clean` closes a review
at fixpoint, citing the seat-outcome events it rests on.

The per-PR findings file (`protocol/templates/review-findings.md`) is a
**projection** of this ledger: every row cites its `review-finding` /
`review-seat-outcome` seq ids; the ledger is the source of truth.
