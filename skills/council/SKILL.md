---
name: orgs-council
description: Cross-provider code review to fixpoint. Fill your OWN provider's seat with your native subagent and every FOREIGN provider's seat via ask-agent; review a frozen revision with a fresh pack; fix every Critical/Important; re-council the fix delta until a round is CLEAN from all seats. Provider diversity is the point — it is the mechanism that closes correlated blind spots.
---

# orgs-council — cross-provider review to fixpoint

The bench found this to be the **keystone for robustness**: whether a
cross-provider council ran is the variable that separated "crashes on the first
bad byte" from "shippable" — not protocol-vs-no-protocol. Same-provider review
has **correlated blind spots**; only a different provider closes them. This
skill is not optional decoration in any variety that claims a review bar.

Uses the `council-review` skill's provider-aware seating matrix and `ask-agent`
for foreign seats.

## Freeze the target

Council a **named, immutable revision** — a committed, pushed sha, never a live
working tree — dispatched only after the author has stopped editing. Every
seat's prompt names that sha and every seat reviews exactly it; a seat that
cannot be pinned to it does not count. (The same rule as `orgs-review`; stated
here because council runs first.)

## Seating (provider-relative, whatever host you are)

Identity is the **model provider**, not the CLI name. Let `me` = my provider:
- **My own provider's seat is my native subagent** — never `ask-agent` my own
  provider (that is another instance of my model family: correlated blind
  spots, none of my context). If the native subagent cannot run, review inline
  and record the seat as `(inline)`.
- **Every other provider's seat via `ask-agent`** (Anthropic→`claude`,
  OpenAI→`codex`, Google→`agy`). Keep the foreign seats foreign — provider
  diversity is the entire point. A host from a fourth provider adds its own
  native seat and still fills all three of those.
- **A missing foreign seat is a noted empty seat, never a substitution.** Do
  not backfill it with a second same-provider reviewer; say which seat is
  missing and continue with the rest.
- Warm-chain a seat across rounds (`ask-agent --resume`, identity-verified each
  round) so the seat that found an issue re-verifies its own fix.

## Each seat gets a fresh pack

Assemble every seat's prompt with `orgs-pack` as a **judgment pack**: the frozen
diff + spec + acceptance criteria + contracts + boundary tests — never the
implementer's transcript. Foreign seats can't read your files; inline the
material in the prompt.

## To fixpoint

1. Council the frozen head. Each seat returns findings by severity; record them
   as `review-finding` events via `orgs-ledger` (the `review-findings.md` file
   is a projection).
2. Fix every Critical/Important. For nits/perf/scope-creep: fix, or file a
   follow-up with rationale — never silently drop a finding. A genuine operator
   decision goes to the CEO, not decided unilaterally.
3. **Re-council the fix delta only** (`<last-reviewed-sha>..HEAD`) — that is
   where fix-introduced regressions hide.
4. Repeat until a round returns **CLEAN from every seat that is present** —
   zero new Critical/Important, with any empty seat recorded as empty (an
   empty seat is not CLEAN and does not count toward the fixpoint; if a
   required provider stays unavailable, escalate to the CEO rather than
   declaring convergence). That is the fixpoint.

## Non-negotiables (each cost a night or a lesson)

- **A silent or dropped seat is not a CLEAN seat.** Require a *received* verdict
  from each seat; never treat idle/timeout as clean.
- **Every round names the frozen sha it reviewed.**
- Scale to the change: substantive content gets the full fixpoint loop; a pure
  rename / stray-file removal / typo gets one light pass or a one-line
  "trivial; skipping council" note. **A spec is substantive** — the spec's
  own council gate (`orgs-spec`) is never waived under this rule.
