# Protocol state transitions

One table per artifact type. Every transition names who may perform it and
what evidence it requires. Role references (accountable lead, integration
owner, escalation owner) resolve through the project's `org/ROSTER.md`
(template: `protocol/templates/roster.md`) — the roster says *who*, these tables say
*what*. Every state-changing entry in the event ledger carries `based_on`
(the revision the actor reasoned from) and, where it applies work,
`applied_at` (the revision it landed on). All artifacts live in git; the
repo is the office, and any harness must be able to reconstruct current
state from these tables plus the ledger and roster (the cold-start audit
tests exactly this).

## Work package

| From | To | Who | Evidence required |
|---|---|---|---|
| — | DRAFT | lead | intent field naming the spec section served |
| DRAFT | READY | lead | acceptance criteria + boundary tests named; necessity challenge passed (PROCEED or SIMPLIFY applied) |
| READY | CLAIMED | worker (or lead assigns) | worker + model recorded (role and model both stamped) |
| CLAIMED/IN_PROGRESS/REVIEW/REWORK | CLAIMED | lead | takeover — resets to CLAIMED under the new (higher-tier) owner with a fresh context pack, re-walking the ladder from there; a `takeover` event records new owner + model + reason, so takeover rate is derivable at retro |
| CLAIMED | IN_PROGRESS | worker | context manifest committed |
| IN_PROGRESS | BLOCKED | worker | blocking dependency, filed escalation, or open huddle named |
| BLOCKED | IN_PROGRESS | worker | blocker resolved, entry references resolution |
| IN_PROGRESS | REVIEW | worker | PR open; self-review done; acceptance criteria addressed with evidence |
| REVIEW | REWORK | reviewing lead | findings ledger entries (severity + evidence) |
| REWORK | REVIEW | worker | fix delta referenced; only the delta re-reviewed |
| REVIEW | ACCEPTED | accountable lead | council round CLEAN; one-rung-up `lead-review` event recorded (fresh context); findings all dispositioned |
| ACCEPTED | INTEGRATED | integration owner | merged; contract tests green at head |
| any | ABANDONED | accountable lead | reason logged; salvageable branch preserved |

Health signals watched at retro: takeover rate (leads rewriting worker
output = decomposition failing), review churn with zero boundary-test
changes (= underspecified contract), budget overruns (normal when logged,
tripwire when not).

## Deviation

| From | To | Who | Evidence |
|---|---|---|---|
| — | LOGGED | any agent | one line: what bent, why, rollback op (or "read — n/a") |
| LOGGED | ADJUDICATED | next standup's adjudicator | justified / unjustified + one line why |
| ADJUDICATED | (spawns) | adjudicator | may open a docs bug, interpretation request, amendment candidate, or work-package re-spec |

Gated deviations (unnameable rollback, boundary-crossing, beyond scope) may
not enter LOGGED without a prior huddle decision reference.

## Huddle

| From | To | Who | Evidence |
|---|---|---|---|
| — | CONVENED | any agent (attendance forks are terminal delegates: they may request escalation, never convene) | issue key (stable across revisions) + base revision; **at most one open huddle per issue key** — agents at different shas converge on it rather than opening duplicates (RUNBOOK §5b) |
| CONVENED | DECIDED | adjudicator per ownership (see RUNBOOK: facilitation ≠ adjudication) | decision text + based_on |
| DECIDED | RECONCILED | the decision's accountable owner | checked against head; applied, revised, or withdrawn; applied_at stamped |

A DECIDED huddle is a proposal. Speculative work it invalidates is
**not integrated** — the working line resets, the branch is preserved, and
the owner disposes: accept / reject / partially salvage / supersede.

## Interpretation

| From | To | Who | Evidence |
|---|---|---|---|
| — | FILED | any agent | contract + version; the question; what was tried |
| FILED | RULED | contract owner (or lead chain if disputed) | ruling classed: clarification / temporary exception / amendment candidate |
| RULED (clarification) | PROMOTED | contract owner | promoted into the contract's interpretation register (which is the boundary's spec text) immediately; narrows no permitted behavior; consumers notified |
| RULED (temporary) | EXPIRED or PROMOTED | contract owner | scope + expiry stated at ruling; folded in or lapsed by expiry |
| RULED (amendment candidate) | → Amendment | both boundary sides + doc owner | full amendment review |

## Amendment

| From | To | Who | Evidence |
|---|---|---|---|
| — | PROPOSED | anyone via lead | accumulated evidence (deviation log, interpretation register, docs-bug counts for the boundary) |
| PROPOSED | REVIEWED | both sides of boundary + spec doc owner | compatibility analysis; migration plan; who fixes callers (provider, LSC-style) |
| REVIEWED | MERGED | spec doc owner | spec PR merged; consumers acknowledged |

## Escalation / case

| From | To | Who | Evidence |
|---|---|---|---|
| — | OPENED | escalation owner (monitors emit facts + incident key only; escalation alone owns case state) | incident key; dedup: one live case per key |
| OPENED | RULED | lowest lead with authority over the implicated thing | disposition + based_on |
| RULED | CLOSED | case owner | applied and reconciled, or handed to CEO |

Invariant: a harness kill between case creation and decision commit must, on
restart, yield exactly one live case with both observations preserved (the
two observations are the independent detections — e.g. a worker's deviation
and a monitor's alert — that the dedup key must collapse into one case). This
is verified under the **bench's `harness_restart` injected event** (v1), not
the RESP pilot, which runs with no synthetic incidents.

## Review round

All review-round ledger events are recorded by the accountable lead as
scribe — external seats have no repo access; their outputs are the evidence,
the lead's `review-seat-outcome` events are the record.

| From | To | Who (records) | Evidence |
|---|---|---|---|
| — | OPENED | accountable lead | names a frozen revision (sha / PR head) and a quiescent tree; scope: full PR (round 1) or fix delta (round N) |
| OPENED | FINDINGS | lead, from council seat outputs (fresh or warm-chained; warm seats identity-verified per round) | one `review-seat-outcome` per seat: findings (severity, claim, evidence) or explicit `no-finding` |
| FINDINGS | DISPOSITIONED | accountable lead | per finding: fixed / filed with rationale / rejected with reason — never silently dropped |
| DISPOSITIONED | OPENED | lead | opens the next round; it reviews the fix delta only |
| any round | CLEAN | lead | `review-clean` citing every seat's outcome event: zero new Critical/Important; fixpoint reached |

## Sprint

Evidence is the completion of the **from** state that licenses the transition
(the convention every table here uses), so a state's own outputs never gate
entry into it.

| From | To | Who | Evidence |
|---|---|---|---|
| — | PLANNED | lead | spec section owned |
| PLANNED | TRACER | lead (player-coach) | ready to build the walking skeleton (player-coach builds the tracer *before* decomposing — RUNBOOK §3) |
| TRACER | EXECUTING | lead | tracer bullet green — contracts demonstrably compose; only *then* are work packages drafted, necessity-challenged, and READY |
| EXECUTING | INTEGRATING | integration owner | every non-abandoned package INTEGRATED (integration is continuous — packages merge as they are ACCEPTED, not batched here) |
| INTEGRATING | RETRO | integration owner | main green on all boundary tests; no open Crystal conflicts |
| RETRO | CLOSED | lead | lessons filed (provenance/scope/reconsider-when); meta:product recorded; deviations all adjudicated; cold-start audit passed if milestone |
