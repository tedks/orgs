# Review findings: <PR / work package id>

A **projection** of the event ledger (see `event-log.md`): every row cites
its ledger seq id; seat outcomes and the closing CLEAN are ledger events
(`review-seat-outcome`, `review-clean`) recorded by the accountable lead as
scribe. Round N scope: full PR for round 1; **fix delta only** thereafter.
A round in which every seat's outcome event shows zero new
Critical/Important findings is CLEAN and closes the review at fixpoint.
"No finding" is an acceptable seat outcome, recorded explicitly as
`no-finding` — no seat is obliged to manufacture work.

| id | ledger seq | round | seat | severity | claim | evidence | disposition |
|---|---|---|---|---|---|---|---|
| F1 | 14 | 1 | codex | Important | <one-sentence defect> | <repro / line / trace> | fixed in <sha> / filed as <issue> with rationale / rejected: <reason> |

Rules:
- Every finding gets a disposition; none are silently dropped.
- A test added to pin a fix is mutation-checked before the fix's round
  closes (see LESSONS.md 2026-09-01).
- Warm-chained seats are identity-verified every round (yielded session id
  compared to requested; mismatch is a failed round, not a review).
- The seat that found an issue re-verifies its fix when possible.
- Operator decisions (design/scope calls) surface to the CEO, not decided
  unilaterally.
