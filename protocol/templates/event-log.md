# Event ledger conventions

Append-only, **sharded per actor**: `events/<sprint-id>/<actor-id>.md`, one
file per agent. Each agent appends only to its own shard, so workers on
separate branches and worktrees never contend for the same file and there is
no global counter to allocate — the pilot's parallel fan-out cannot collide
on the ledger. The **ledger** is the union of all shards for the sprint;
ordering across shards is by the `ISO timestamp` (ties broken by actor-id),
not a sequence number. An entry's stable id is `<actor-id>:<local-seq>`,
where `local-seq` is monotonic **within one shard only** (so it is
collision-free without coordination). Never edited retroactively —
corrections are new events referencing the old by id. Projections
(interpretation register, case state, current-contract view) are derived
views over the union; in v0 they are maintained by hand at standup/retro and
must cite the ledger entries they summarize.

Entry format:

```
## <actor-id>:<local-seq> · <ISO timestamp> · <type>
- actor: <role> (<model>)
- based_on: <sha> [· applied_at: <sha>]
- refs: <work package / contract / huddle / finding ids>
<one-to-few lines of body>
```

Types: `deviation`, `deviation-adjudicated`, `huddle-convened`,
`huddle-decided`, `huddle-reconciled`, `standup`, `escalation`,
`interpretation-filed`, `interpretation-ruled`, `docs-bug`,
`amendment-proposed`, `review-finding`, `review-seat-outcome`,
`review-clean`, `lead-review`, `takeover`, `necessity-challenge`,
`crystal-conflict`, `semantic-deadlock`, `state-change`, `lesson`.

`lead-review` records the one-rung-up lead's fresh-context result for a
package (outcome: approved / findings `<ids>` / no-finding), the evidence the
work-package ACCEPTED gate requires. `crystal-conflict` records a speculative
merge conflict (branches + revisions + textual|semantic); `semantic-deadlock`
records a conflict whose resolution ownership is disputed and awaiting lead
adjudication.

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
