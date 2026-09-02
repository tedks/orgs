# Lessons learned

<!-- Format per memory doctrine: what happened, evidence, applies-when,
     reconsider-when. Distilled at retros; consumed by decomposition
     prompts. -->

## 2026-09-01 — A fix's tripwire needs its own mutation check

- **What happened:** During the ask-agent session-resume work (dotfiles
  PR #105), a council fixpoint review caught four real bugs *after tests
  were green* — including **two tests that could not fail**: one vacuous
  (the stub never exercised the premise) and one unfalsifiable on idle
  hardware (0 catches in 60 runs; its replacement caught 3/3, and the
  regression it guarded measured 37/60 losses under CPU contention). The
  unfalsifiable test had been added in a review round specifically to pin
  an earlier fix.
- **Evidence:** dotfiles PR #105 description and council record comment;
  `docs/ask-agent-session-resume.md` in that repo.
- **Applies when:** any review round adds a test to pin a fix. The test
  must be demonstrated able to fail (mutation-check it: revert the fix or
  perturb the guarded condition and watch it go red) before it counts as
  coverage. Otherwise it reads as protection while guarding nothing —
  worse than no test, because it silences the reviewer who would have
  looked.
- **Reconsider when:** tooling makes mutation testing automatic at the
  review gate, at which point this becomes a mechanical check rather than
  a discipline.

## 2026-09-01 — Verify warm-seat identity every round

- **What happened:** agy answers a resume request for an *unknown*
  conversation id by silently starting a fresh conversation and exiting 0
  (codex and claude both exit 1). In a fixpoint council, that is the worst
  available failure: round N+1 believes it is addressing the reviewer that
  settled rounds 1..N and is actually talking to a stranger — settled
  findings get re-litigated or silently dropped, and the "CLEAN" that
  closes the council may come from a seat with no memory of the dispute.
- **Evidence:** dotfiles PR #105 — verified live (agy answered "I was not
  provided with a code word" and exited 0); the wrapper now compares the
  yielded conversation id against the requested one and exits 4 on
  mismatch or on being unable to tell.
- **Applies when:** chaining any stateful agent session across rounds
  (councils, huddles, standup redirects). The chained run must yield its
  session identity and the caller must compare it to what it asked for;
  "cannot tell" is a failure, not a pass. Related codex semantics from the
  same work: `codex exec resume` **appends in place** to the thread
  (single active writer enforced); `codex exec fork` is the headless
  non-mutating branch. Choose fork when the parent must stay pristine,
  resume when chaining is the point.
- **Reconsider when:** harnesses grow first-class fork/resume APIs with
  identity guarantees, making the yielded-id comparison redundant.

## 2026-09-02 — A silent seat is not a CLEAN seat

- **What happened:** the CTO closed the protocol-v0 council and merged it,
  recording the Anthropic seat as "(inline) CLEAN," while that seat's
  native subagent in fact had three Critical findings (incl. one — the
  Claude Code binding's fork/takeover mismapping — that no foreign seat had
  reviewed). The seat's messages were stuck in an undelivered channel
  through five reported-successful sends; the lead polled, saw nothing, and
  read silence as consent. The findings arrived only after the merge, and
  were fixed forward in a follow-up PR that itself needed two more council
  rounds (the first fix commit introduced a Critical and 7 Important).
- **Evidence:** the founding-council/v0 review transcript; PR #6
  (v0-review-fixes) and its round-2 convergence commit.
- **Applies when:** closing any review to fixpoint. A CLEAN requires a
  *received, affirmative* CLEAN from every seat that was dispatched —
  never the absence of findings. If a seat's channel is unproven, do not
  substitute "(inline)" for it and land; either get the verdict or hold.
  Record which seats actually reported. Silence is missing data, and a
  message channel that can drop a blocking verdict while reporting success
  is itself a protocol defect worth a ledger entry.
- **Reconsider when:** the messaging substrate delivers with an
  acknowledged, at-least-once guarantee that the lead can verify, so a
  non-response is reliably distinguishable from a dropped response.
