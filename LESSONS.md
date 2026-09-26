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

## 2026-09-02 — A verdict must name the state it was rendered against

- **What happened:** during PR #6's review the moderator was editing the
  working tree live. codex reviewed the *committed* `2feaffc` (inline
  pipelining probe) and flagged two defects; the Anthropic seat reviewed
  the *working tree* at the same wall-clock window, which already carried
  the fixes, and cleared it. The moderator then recorded this as "codex
  caught two defects the Anthropic seat missed" — a sequence — when it was
  independent convergence on overlapping states. The working-tree-vs-commit
  distinction is invisible once commits are squashed into history, so the
  wrong record would later misattribute credit and blame with nothing to
  audit against. This is the silence-as-consent failure one level up:
  convergence read as sequence.
- **Evidence:** PR #6 review-correction comment.
- **Applies when:** any review, and acutely when the reviewed artifact can
  change during the review (live editing, parallel commits). **Prefer correct
  by construction over reporting:** launch every round against a named,
  immutable revision (a committed sha / PR head) from a quiescent tree, and
  name it in the dispatch prompt so each seat reviews exactly it (now RUNBOOK
  §6). Reporting the state in the verdict — "a sha, or explicitly 'working
  tree at time T'" — is the weaker fallback for when a frozen target isn't
  available; a CLEAN with no pinned base is ambiguous, and "the seat cleared
  X" is only meaningful once X is pinned.
- **Reconsider when:** the harness makes reviewing a live/unpinned tree
  impossible (review always resolves a named revision), so the freeze is
  enforced by tooling rather than discipline.

## 2026-09-02 — A binding needs a reviewer who can execute its primitives

- **What happened:** the Claude Code binding claimed
  `subagent_type: "fork"` could carry the implementer's context and shift
  model for a takeover. In this harness a fork inherits the *caller's*
  context and *ignores* a `model` override, so the takeover mechanism was
  unexecutable. This Critical survived every foreign council seat because
  no seat's scope was checking a harness-binding document against the
  harness it binds — it was reviewed as prose, and prose review cannot
  catch a false claim about a tool's contract.
- **Evidence:** PR #6 finding #1; `bindings/claude-code.md`.
- **Applies when:** reviewing any document that asserts how a tool, API, or
  primitive behaves (bindings, integration docs, tool mappings). At least
  one reviewer must be able to execute against the named primitives, or
  check the claims against the authoritative tool contract — prose review
  alone cannot verify executable behavior. The v1 review ladder should give
  binding files such a seat explicitly (ditz `binding-executable-review`).
- **Reconsider when:** binding claims are generated from or checked against
  machine-readable tool schemas, so a false capability claim fails
  mechanically rather than needing a human/agent to notice.

## 2026-09-03 — The cross-provider council is the keystone; the hierarchy is optional at small scale

- **What happened:** a 5-regime ablation study on the RESP tracer (raw /
  no-council / no-decomposition / full / no-standup). Both regimes WITHOUT
  cross-provider council-to-fixpoint (raw, no-council) shipped ~6 Critical/High
  crash-or-DoS defects; both regimes WITH it (no-decomposition, full) reached a
  clean shippable bar — and the FLAT build + council reached the same bar as the
  full hierarchy + council. All five pass 12/12 conformance (conformance
  saturates). The hierarchy cost ~10× and its distinctive payoff (defect-class
  propagation) was a partial head-start, not the source of robustness.
- **Evidence:** docs/bench/ablation-study-5regime.md; bench/study/<regime>/.
- **Applies when:** deciding where to invest in an agent-org protocol. The
  load-bearing, low-cost mechanism is cross-provider review-to-fixpoint (same-
  provider review has correlated blind spots — no-council's lead review missed
  the nil class recurring in storage that the council caught). The expensive
  decomposition hierarchy must justify itself on larger, multi-team targets; at
  3-entity scale it did not pay for its ~10× cost in measurable robustness.
- **Reconsider when:** a larger multi-team target, real replication, or a
  standup-triggering scenario (parallel workers / planted rabbit-hole) is run —
  the standup, the most novel bet, was NOT exercised here (no trigger fired).

## 2026-09-24 — Lean command and control: what a week of lanes measured

- **What happened:** a coordinator (Fable) ran seven implementer lanes (Opus 5.5) toward a hard event date. Three changes cut the coordinator's share of spend from a sixth of the day to two percent and halved the cost per landed PR, from about 1.0 percent of a weekly quota to about 0.45: councils and landings moved into the lanes, with the coordinator reading only fixed-form events; standups became one message out and six lines back, read as a critic; new work went to fresh lanes and finished lanes retired with a written entry. Measurement of the session logs showed cache re-reads (context size times message count) at 85 to 90 percent of spend, and lanes on the 1M-token window costing about twice as much per message as standard ones, which set the next rule: lanes coordinate, Sonnet-class workers edit and run gates, Haiku-class readers digest logs. One relayed error became a landed PR: the coordinator's wrong line about a registry's scope reached one lane through another after a third lane had already corrected it, because the correction went to the corrector only.
- **Evidence:** chaos-speech PRs #893 through #964 on 2026-09-23; the lane protocol's fifteen points and the landing script in that repo's `docs/process/` and `tools/`; the per-lane spend table in the coordinator's session.
- **Applies when:** one coordinator drives several implementer agents and its own context or quota is the binding constraint; when landing can be scripted and gate-enforced; when the review record on the change can stand in for the coordinator's second reading.
- **Reconsider when:** the harness lets a session compact itself or hold tool output out of band, which removes the reason for the coordinator/worker split; when a foreign review seat is reliably available, which removes the quota-scarce ordering; when a landed change shows the record-plus-gates regime missing a class of defect the coordinator's own reading would have caught.

## 2026-09-26 — A status reply is not the end of a mission

- **What happened:** in the Chaos org, lanes B and H went idle after
  answering standups while authorized work remained. In PredictionBook,
  protocol maintenance after milestone M2 displaced the next product
  assignment, and a lane sat without a mission. In both cases a report or
  side question was read as a boundary, and nothing re-entered the mission.
- **Evidence:** `/home/tedks/.local/state/doctrine-notes/20260926/C.md`
  and `P.md` (private CTO notes);
  `/home/tedks/Projects/chaos/controller-tools/cto-noon-transition-2026-09-26.md`.
- **Applies when:** any agent answers a question, a standup or a sitrep
  request mid-mission. It answers and resumes authorized work unless it is
  explicitly paused, blocked or done. At DONE, the controller assigns the
  next bounded mission or records why the lane stays idle. The rule now
  lives in doctrine as "Mission continuation".
- **Reconsider when:** a scheduler or dispatcher reassigns idle lanes
  mechanically, so continuation no longer depends on each agent's discipline.

## 2026-09-26 — A small real smoke test found what fixtures did not

- **What happened:** the shared tmux sender passed its behavior tests and
  its deterministic live-terminal test. A small smoke against a real Codex
  session then accepted a long message but lost its receipt, because the
  session ran in alternate-screen mode and the first rows of the receipt
  never reached tmux scrollback. The rule held: missing evidence is not a
  reason to replay. The fix launches Codex with `--no-alt-screen`.
- **Evidence:** dotfiles PR #145, merge `c3a84d58`, fix commit `df9bbc2`
  ("Preserve tmux scrollback for Codex delivery receipts");
  `/home/tedks/.local/state/doctrine-notes/20260926/T.md`.
- **Applies when:** a tool depends on observing another program's screen or
  output format. Keep one small representative run against the real program
  alongside the fixtures, and treat missing evidence as ambiguity, never as
  a reason to resend. The rule now lives in doctrine under "Verification
  is a waterfall" (Good engineering).
- **Reconsider when:** the harness exposes a structured receipt (a queue API
  or a control channel with typed results), so screen observation is no
  longer the evidence.

## 2026-09-26 — Approval accumulates around bounded repairs

- **What happened:** Goals Android work needed repeated controller rulings
  for setup and test-harness prerequisites. Each ruling was small, but they
  accumulated, consumed controller context, and turned the controller into
  an approval queue for work the package already implied. Chaos saw the
  same pattern around small diagnostic changes.
- **Evidence:** `/home/tedks/.local/state/doctrine-notes/20260926/G.md`;
  `/home/tedks/Projects/goals/controller-tools/results/controller-status.md`.
- **Applies when:** writing a work package whose outcome needs environment,
  setup or prerequisite repairs. Grant bounded repair authority with the
  outcome. Escalate changed intent, changed risk, changed evidence
  requirements or an exhausted attempt budget, not each attempt. The rule
  now lives in each package as "repair authority" (`doctrine/DOCTRINE.md`,
  Standing authority; `doctrine/ROLES.md`).
- **Reconsider when:** a repair turns out to cross a contract boundary or
  cause an irreversible effect often enough that per-attempt review would
  have caught it.

## 2026-09-26 — A reservation grants scope, not capacity

- **What happened:** whole-host reservations serialized independent work in
  Chaos and Goals, hiding real spare capacity; Goals later ran eight
  frontend workers at once. In PureSky, a UI baseline failed under host
  contention even though it held a nominal slot, so the reservation did not
  guarantee the capacity it implied.
- **Evidence:** `/home/tedks/.local/state/doctrine-notes/20260926/S.md`,
  `C.md` and `G.md` (private CTO notes).
- **Applies when:** scheduling heavy gates or workers on shared hosts.
  Reserve measured CPU, memory and time budgets and owned resources, not a
  whole machine by default. Measure before starting, stop only resources
  you own, and let peers coordinate leases directly. The rule now lives in
  doctrine as "Host resources and hygiene".
- **Reconsider when:** hosts enforce resource isolation (cgroups, per-lane
  VMs), so a reservation does guarantee capacity.
