# Review findings ledger: <PR / work package id>

Round N scope: full PR for round 1; **fix delta only** thereafter. A round
with zero new Critical/Important findings from every seat is CLEAN and
closes the review at fixpoint. "No finding" is an acceptable seat outcome —
no seat is obliged to manufacture work.

| id | round | seat | severity | claim | evidence | disposition |
|---|---|---|---|---|---|---|
| F1 | 1 | codex | Important | <one-sentence defect> | <repro / line / trace> | fixed in <sha> / filed as <issue> with rationale / rejected: <reason> |

Rules:
- Every finding gets a disposition; none are silently dropped.
- A test added to pin a fix is mutation-checked before the fix's round
  closes (see LESSONS.md 2026-09-01).
- Warm-chained seats are identity-verified every round (yielded session id
  compared to requested; mismatch is a failed round, not a review).
- The seat that found an issue re-verifies its fix when possible.
- Operator decisions (design/scope calls) surface to the CEO, not decided
  unilaterally.
