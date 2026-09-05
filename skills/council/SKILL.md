---
name: orgs-council
description: Cross-provider code review to fixpoint. Fill your own provider's seat with a native subagent and every foreign seat via ask-agent (codex, agy); review a frozen revision; fix every Critical/Important; re-council the fix delta until a round is CLEAN from all seats. Provider diversity is the point — it is the mechanism that closes correlated blind spots.
---

# orgs-council — cross-provider review to fixpoint

The bench found this to be the **keystone for robustness**: whether a
cross-provider council ran is the variable that separated "crashes on the first
bad byte" from "shippable" — not protocol-vs-no-protocol. Same-provider review
has **correlated blind spots**; only a different provider closes them. This
skill is not optional decoration in any variety that claims a review bar.

Uses the `council-review` skill's seating matrix and `ask-agent` for foreign
seats. Review a **frozen revision** (see `orgs-review` — freeze first).

## Seating (provider-aware)

- **Your own provider's seat is your native subagent** (the `Agent` tool for
  Claude). Never `ask-agent` your own provider — that is another instance of
  your own model family: correlated blind spots, none of your context.
- **Every foreign seat via `ask-agent`** (`codex`, `agy`). Keep the foreign
  seats foreign — provider diversity is the entire point.
- **A missing foreign seat is a noted empty seat, never a substitution.** Do
  not backfill it with a second same-provider reviewer; say which seat is
  missing and continue.
- Warm-chain a seat across rounds (`ask-agent --resume`, identity-verified each
  round) so the seat that found an issue re-verifies its own fix.

## To fixpoint

1. Council the frozen head. Each seat returns findings by severity into the
   ledger (`review-findings`).
2. Fix every Critical/Important. For nits/perf/scope-creep: fix, or file a
   follow-up with rationale — never silently drop a finding. A genuine operator
   decision goes to the CEO, not decided unilaterally.
3. **Re-council the fix delta only** (`<last-reviewed-sha>..HEAD`) — that is
   where fix-introduced regressions hide.
4. Repeat until a round returns **CLEAN from every seat** — zero new
   Critical/Important. That is the fixpoint.

## Non-negotiables (each cost a night or a lesson)

- **A silent or dropped seat is not a CLEAN seat.** Require a *received* verdict
  from each seat; never treat idle/timeout as clean.
- **Every round names the frozen sha it reviewed.**
- Scale to the PR: substantive logic gets the full fixpoint loop; a
  docs-only/rename/stray-file change gets one light pass or a one-line
  "trivial; skipping council" note.
