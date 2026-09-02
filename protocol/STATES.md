# Protocol state transitions

One table per artifact type. Every transition names who may perform it and
what evidence it requires. Every state-changing entry in the event ledger
carries `based_on` (the revision the actor reasoned from) and, where it
applies work, `applied_at` (the revision it landed on). All artifacts live in
git; the repo is the office, and any harness must be able to reconstruct
current state from these tables plus the ledger (the cold-start audit tests
exactly this).

## Work package

| From | To | Who | Evidence required |
|---|---|---|---|
| — | DRAFT | lead | intent field naming the spec section served |
| DRAFT | READY | lead | acceptance criteria + boundary tests named; necessity challenge passed (PROCEED or SIMPLIFY applied) |
| READY | CLAIMED | worker (or lead assigns) | worker + model recorded (role and model both stamped) |
| CLAIMED | IN_PROGRESS | worker | context manifest committed |
| IN_PROGRESS | BLOCKED | worker | blocking dependency or filed escalation named |
| BLOCKED | IN_PROGRESS | worker | blocker resolved, entry references resolution |
| IN_PROGRESS | REVIEW | worker | PR open; self-review done; acceptance criteria addressed with evidence |
| REVIEW | REWORK | reviewing lead | findings ledger entries (severity + evidence) |
| REWORK | REVIEW | worker | fix delta referenced; only the delta re-reviewed |
| REVIEW | ACCEPTED | accountable lead | council round CLEAN; findings all dispositioned |
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
| — | CONVENED | any agent (attendance forks are terminal delegates: they may request escalation, never convene) | issue key + base revision; at most one open huddle per (issue, revision) |
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
| RULED (clarification) | PROMOTED | contract owner | spec text updated immediately; narrows no permitted behavior; consumers notified |
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

Invariant (tracer-tested): a harness kill between case creation and decision
commit must, on restart, yield exactly one live case with both observations
preserved.

## Review round

| From | To | Who | Evidence |
|---|---|---|---|
| — | OPENED | accountable lead | scope: full PR (round 1) or fix delta (round N) |
| OPENED | FINDINGS | council seats (fresh or warm-chained; warm seats identity-verified per round) | each finding: severity, claim, evidence |
| FINDINGS | DISPOSITIONED | accountable lead | per finding: fixed / filed with rationale / rejected with reason — never silently dropped |
| DISPOSITIONED | next round | lead | next round reviews the fix delta only |
| any round | CLEAN | all seats | zero new Critical/Important; fixpoint reached |

## Sprint

| From | To | Who | Evidence |
|---|---|---|---|
| — | PLANNED | lead | spec section owned; work packages drafted |
| PLANNED | TRACER | lead (player-coach) | thin executable vertical slice: contracts demonstrably compose |
| TRACER | EXECUTING | lead | packages READY; fan-out begun |
| EXECUTING | INTEGRATING | integration owner | all packages INTEGRATED or ABANDONED |
| INTEGRATING | RETRO | lead | lessons filed with provenance/scope/reconsider-when; meta:product ratio recorded; deviations all adjudicated |
| RETRO | CLOSED | lead | cold-start audit passed if milestone |
