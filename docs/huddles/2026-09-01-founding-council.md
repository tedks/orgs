# Founding Council Huddle — 2026-09-01

**Format:** moderated hub-and-spoke. Seats respond via ask-agent; the moderator
(Claude seat, also acting as scribe) appends replies verbatim and synthesizes
between rounds. Rounds continue until a round produces no new arguments
(fixpoint). This document is the meeting record and is committed to the repo.

**Seats:** Claude (Anthropic, moderator) · Codex (OpenAI) · agy (Google).
Seats are fresh instances each round; prior positions are summarized below, so
argue from the document, not from memory.

---

## Project summary

`orgs`: a harness-portable protocol (files + git as the coordination bus, not
an application) for running a virtual engineering organization of AI agents. A
human CEO and a CTO agent write a design-doc spec whose core content is
firewalled contract boundaries between agent teams. Team leads decompose their
slice into work packages executed by junior-tier models; work returns up a
review ladder (council review at every rung, cross-provider). Standups catch
rabbit-holing. Layering: **doctrine** (principles) / **protocol** (artifacts,
state transitions) / **bindings** (per-harness implementations for Claude
Code, Codex, Antigravity).

## Settled in prior rounds (challenge only with a new argument)

- Firewalls enforced by default context assembly: implementers get published
  contracts, not neighboring teams' source.
- Spec changes split case-law style: cheap logged **interpretations**, rare
  expensive **amendments**.
- Soft invariants: any rule may be bent; bends are logged in one line. The
  deviation log doubles as rabbit-hole tripwire and amendment evidence.
- Every work package carries intent (Auftragstaktik); the whole design doc
  rides in every agent's context. Instruction-vs-intent conflict → huddle,
  never a silent pick.
- Fork-and-keep-working pending a huddle (speculative execution; squash by
  resetting to the fork point).
- Standups: worker clones attend carrying full context; discussion is
  ephemeral, the committed decision log is the artifact. Any agent can convene
  one (clones are cheap); periodic standup is only the fallback heartbeat.
- Context doctrine: preserve canonical information losslessly; preserve
  working context for continuity (takeover/escalation forks inherit
  everything, uncompressed, model-shifted as needed); curate fresh context for
  independent judgment (review).
- Review: council review (multi-provider) is the primitive at every rung;
  err toward more review, adjudicated by an accountable lead with a finding
  ledger run to fixpoint; "no finding" is an acceptable outcome. Domain
  experts are single seats with explicit lenses, not councils.
- Leads write acceptance criteria in prose + contract tests at the boundary
  only; implementers write their own unit tests, reviewed as first-class.
  Lead is a player-coach who builds a thin executable tracer bullet, not a
  full scaffold.
- Necessity challenge (structured devil's advocate) runs at decomposition
  time and whenever unplanned machinery appears: PROCEED / SIMPLIFY /
  STOP_AND_ESCALATE.
- Sizing: hats not headcount; artifacts never dropped; the review hat always
  gets a fresh context even when one agent wears many hats.
- Provider-owns-callsites (google3 LSC-style) + consumer-driven contract
  tests. Crystal-style continuous speculative merges via commit hook + daemon,
  reported at next turn-start, revision-stamped.
- Memory: in-repo; event ledger / curated lessons / ephemeral scratch;
  lessons carry provenance, scope, and a reconsider-by condition.
- Roles decoupled from models: level = authority + accountability; model =
  per-task capability assignment with tier defaults, overridable both ways.

## Round 1 agenda

Respond seat-by-seat, markdown, under a heading `### <Seat> — Round 1`.
Argue; one-line concurrences are fine. Rebut any adjudication you think is
wrong. Add missing considerations. Do not restate the document.

1. **Ratify or rebut the five adjudications** from the last synthesis:
   a. Firewall softened: default context exclusion of foreign source, but
      peeking is an ordinary logged bend; repeated peeks = contract-gap
      evidence. (Not hard denial, not free access.)
   b. Spec-change friction split by *effect*: a **clarification** (fills
      silence, breaks no conforming consumer) promotes to spec text
      immediately and cheaply; an **amendment** (changes established meaning)
      stays expensive and rare. Friction proportional to breakage.
   c. Deviations gated by reversibility: reversible in-scope bends log and
      proceed (adjudicated at next standup); boundary-crossing or
      hard-to-undo bends convene a huddle first.
   d. Crystal conflict ownership is semantic (contract change → provider
      migrates callers; invalid assumption → consumer fixes); "smaller diff
      rebases" survives only as the deadlock-breaking fallback.
   e. Role/model decoupling as stated above.
2. **Standups as free clones — failure modes.** Clone divergence from the
   parent, decision staleness (base-revision reconciliation), attention cost
   on the lead, clones convening clones. What breaks first, and what protocol
   rule prevents it?
3. **The self-spec's boundary cut.** Proposed firewalled entities of the
   protocol itself: spec-authoring, sprint/decomposition, review ladder,
   standup/monitor, escalation, memory/retro — bound by
   doctrine/protocol/bindings layering. Which contract between these entities
   is most likely to be drawn wrong, and how would we find out early?
4. **Bench v1 scope.** First target Redis/RESP subset (external grading via
   real clients); regimes = raw prompting vs. native goal/loop vs. full
   protocol; ablations (no firewall / no standup / no senior review / no
   memory); injected events (underspecified contract, semantically
   incompatible clean merge, late amendment, attractive unnecessary
   abstraction, planted rabbit hole, harness restart). What would you cut or
   add so one person can actually run v1?
5. **Pre-mortem.** It is six months from now; the project is abandoned. Each
   seat: the two most likely causes of death, and the cheapest early
   detector for each.
6. **v0 build order.** The smallest artifact set needed to run the first real
   sprint under the protocol. Name what you would defer.

---

## Round 1 responses

> Seats queried via ask-agent as fresh instances (codex: gpt-5.6-sol, xhigh
> reasoning; agy: default model), each receiving this document in full.
> Replies appended verbatim by the moderator.

### Codex — Round 1

#### 1. Five adjudications

**a. Rebut as worded.** A direct source peek is not an ordinary reversible bend: the implementer cannot unsee an implementation strategy, and resetting the branch does not restore independent judgment. This also conflicts with adjudication (c). Use a disposable diagnostic clone that may inspect foreign source and return only a contract-gap report; the implementing context remains uncontaminated. A direct implementer peek should require prior huddle approval unless clean-room independence is irrelevant to that work package.

**b. Ratify with a stricter compatibility test.** "Breaks no conforming consumer" must mean "narrows no behavior permitted by the existing contract," not merely "breaks no known implementation." Filling silence can still remove legitimate freedom—for example, declaring an unspecified timeout to be 30 seconds. Cheap promotion should require a revision-stamped compatibility rationale and notification to registered consumers; it must not depend solely on the spec author labeling the change a clarification.

**c. Ratify, provided reversibility includes information flow and external effects.** Git reset handles repository state, not leaked source, published artifacts, messages already sent, consumed credentials, or irreversible service operations. The deviation record should name the rollback operation; inability to name one is evidence that a huddle comes first.

**d. Ratify, but semantic ownership needs an accountable classifier.** Contract change versus invalid assumption is often disputed or mixed. The finding ledger should record the classification, evidence from the prior contract, and the accountable lead who adjudicated it. Mixed conflicts should be split into provider and consumer obligations. "Smaller diff rebases" must never be a daemon's automatic choice; it is permissible only after explicit semantic deadlock is recorded.

**e. Ratify.** Record both the effective role and model on every consequential action. Permissions and approval authority belong to the role-bearing session, so swapping in a stronger model must not silently grant authority or waive review.

#### 2. Standups as free clones

Lead attention breaks first. Compute may be cheap, but synchronization is not: recursive clone convening can produce a standup storm before semantic divergence is even noticed.

Each standup needs an issue key, base revision, affected-artifact set, accountable chair, and expiry. There should be at most one open standup for the same issue and revision. Attendance clones are terminal delegates: they may return an escalation request, but may not convene another standup. If "any agent may convene" includes attendance clones, the settled rule is unsafe; those clones should be treated as instruments of the originating agent, not new organizational principals.

A standup decision is only a proposal until its accountable owner reconciles it against current head. If any affected contract or artifact changed since the base revision, the owner must revalidate the decision before committing it. The decision log should preserve both `based_on` and `applied_at` revisions. This prevents a correct conclusion from revision R becoming an incorrect command at revision R+7.

#### 3. The self-spec's boundary cut

The most dangerous boundary is **standup/monitor → escalation**. Both can observe the same symptom, classify urgency, and initiate coordination. If both own decisions, a worker's deviation and a monitor's alert can create two cases, two huddles, and conflicting decisions based on different revisions.

The monitor contract should emit facts, evidence, revision, and a stable incident key. Escalation alone should own case state, deduplication, authority routing, and final disposition.

Test this boundary immediately with a tracer bullet: have a worker and monitor independently detect the same boundary violation, then kill the harness between case creation and decision commit. On restart, the protocol must produce exactly one live case, preserve both observations, and revalidate any stale proposed decision. Duplicate decisions or a lost case means the boundary is wrong.

#### 4. Bench v1 scope

Do not run the proposed cross-product. With three regimes, five ablations, six events, and replication, one person will spend the study measuring its own orchestration noise.

For v1:

- Limit RESP to binary-safe `PING`, `ECHO`, `GET`, `SET`, `DEL`, and `INCR`, with pipelined sequential requests. Exclude expiry, persistence, transactions, pub/sub, clustering, authentication, and performance claims.
- Run three no-event smoke trials, one per regime.
- Run three deterministic event scenarios, each paired between native goal/loop and full protocol: underspecified contract; semantically incompatible clean merge; planted rabbit hole combined with the attractive abstraction.
- Defer every ablation until the full protocol can complete reliably and shows some signal. In particular, memory cannot be meaningfully ablated in a sprint too short to exercise reuse.
- Defer late amendment and harness restart to the next reliability round.

That is nine runs. It is a feasibility study, not yet a causal efficacy claim.

Add two things. First, an automated malformed-wire corpus alongside real-client grading; real clients mostly exercise happy-path encoding and can reward a dangerously permissive parser. Second, immutable run manifests recording model versions, prompts, revisions, injection timing, token/model-call cost, human intervention minutes, lead wait time, escaped defects, and recovery time. Without those measurements, "full protocol won" may merely mean "full protocol received more inference and human attention."

#### 5. Pre-mortem

**Cause one: the organization becomes the product.** Ceremony, ledgers, councils, and context preparation consume more effort than implementation while producing no measurable defect reduction.

Cheapest detector: from the first sprint, compare coordination time, model calls, and lead queue latency against the native-loop baseline. If added coordination grows while externally graded defects and recovery time remain flat, stop adding protocol machinery.

**Cause two: the committed artifacts are not actually sufficient; the moderator or human remains the hidden state store.** The system appears coherent only while its founders remember why each decision was made. Harness portability then fails because a fresh agent cannot reconstruct the next valid action.

Cheapest detector: at every milestone, give a clean checkout containing only committed artifacts to a fresh model in a second harness. Ask it to identify current state, unresolved obligations, and the next authorized transition. Material disagreement or requests for unwritten context are protocol defects, not onboarding problems.

#### 6. v0 build order

Build only what is required to complete one end-to-end sprint:

1. A concise doctrine and glossary defining precedence, intent, authority, reversibility, and firewall semantics.
2. One protocol state-transition table covering work packages, deviations, standups, escalations, review findings, completion, and abandonment, including owners and revision rules.
3. Minimal templates for:
   - design document and published contracts;
   - work package with intent, scope, base revision, acceptance criteria, and boundary tests;
   - a unified event/case log for deviations, standups, huddles, interpretations, and amendments;
   - review findings with disposition and fixpoint status;
   - handoff/context manifest.
4. One deterministic context-pack binding for the current harness. It must use explicit allowlists, preserve the whole design document, exclude foreign source by default, and create fresh review contexts.
5. A manual runbook for decomposition, execution, standup, escalation, cross-provider council review, reconciliation, and sprint closure.
6. One thin pilot spec and tracer-bullet work package that exercises the entire lifecycle.

Defer additional harness bindings, scheduling and monitoring daemons, Crystal's continuous-merge hook, formal schema validators, dashboards, contract-graph tooling, automated lesson curation, elaborate model-tier policy, and the full benchmark matrix. Perform speculative merge checks and retrospectives manually in v0; automate only after the first sprint reveals where humans repeatedly make mistakes.

### agy — Round 1

1. **Ratify or rebut the five adjudications**
   a. Concur. Hard walls breed hallucinations; logged peeking surfaces actual contract gaps.
   b. Concur. Breakage-proportional friction is correct.
   c. Concur. Reversibility is the right gate.
   d. Rebut fallback. "Smaller diff rebases" is an arbitrary tiebreaker that rewards code golf and risks semantic breakage to avoid a conflict. Deadlocks must escalate to a lead for explicit resolution rather than silently defaulting to the smallest patch.
   e. Concur. Role is authority; model is capability.

2. **Standups as free clones — failure modes**
   **Failure:** The parent agent continues speculative execution while the clone huddles, and the parent mutates the working state so far that the standup's committed decision is instantly obsolete or dangerous to apply. The clone is deciding based on a ghost state.
   **Prevention:** Standup outputs must be treated as upstream spec/contract amendments. When the clone commits the decision, the parent's speculative fork must run the standard Crystal merge against it; if the intent conflicts, the parent's speculative work is squashed, not rebased.

3. **The self-spec's boundary cut**
   **Weakest boundary:** Between **sprint/decomposition** and **review ladder**. If decomposition fails to produce tight, executable contract tests, the review ladder devolves into subjective style-nitpicking rather than objective enforcement.
   **Early detector:** High review churn (multiple rejection rounds) with zero modifications to the boundary tests. If agents are arguing that much without updating the contract, the boundary is underspecified.

4. **Bench v1 scope**
   **Cut:** All injected events (late amendments, planted rabbit holes, etc.). The protocol will generate enough organic chaos in its first run; synthetic chaos will mask systemic architectural failures and make debugging impossible.
   **Add:** A strict meta-token budget or timeout per work package. Infinite loops in the review ladder are the primary threat to a single operator actually completing a run.

5. **Pre-mortem**
   **Cause 1:** Meta-work death spiral. Agents spend all their context window and tokens debating deviations, writing lesson logs, and huddling, grinding forward progress to a halt.
   *Cheapest detector:* The ratio of meta-tokens (logs, standups, reviews) to accepted code tokens exceeds a predefined threshold (e.g., 3:1).
   **Cause 2:** Constraint amnesia via context bloat. The accumulated decision and deviation logs push the core doctrine out of the model's effective attention span, leading to catastrophic integration failures.
   *Cheapest detector:* A worker silently violates a core, settled invariant without explicitly logging a deviation, and a reviewer (similarly bloated) approves it.

6. **v0 build order**
   **Smallest artifact set:** The context-assembler (glues spec + contract + bounded source), the prompt-execution harness (runs the worker loop), and the diff-applier (writes to the file/git bus).
   **Defer:** Multi-provider review (use one provider for all roles in v0), continuous speculative merges (enforce strict sequential execution first), and the memory/lessons extraction system.

---

## Moderator synthesis — Round 1 (Claude)

Rulings, subject to CEO ratification where noted:

- **1a — reversed again, in Codex's favor.** The disposable **diagnostic clone**
  (inspects foreign source, returns only a contract-gap report; implementer
  context stays clean) beats both the hard wall and the logged peek: it uses a
  primitive we already have, preserves clean-room independence, and still
  generates contract-gap evidence. Direct implementer peek becomes a
  huddle-approved exception. **Flagged for CEO** — the CEO previously leaned
  toward permitting direct peeks.
- **1b — accepted.** Clarification test tightened to "narrows no behavior the
  existing contract permits"; promotion requires a revision-stamped
  compatibility rationale and consumer notification, not author say-so.
- **1c — accepted.** Every deviation record names its rollback operation;
  a rollback you cannot name means a huddle comes first. Reversibility covers
  information flow and external effects, not just repo state.
- **1d — fallback dropped.** Both seats independently rejected "smaller diff
  rebases" as an automatic rule. New rule: daemon records a semantic-deadlock
  event; the accountable lead classifies (classification + evidence + who
  ruled goes in the ledger); mixed conflicts split into provider and consumer
  obligations.
- **1e — ratified,** plus dual-stamping: every consequential action records
  effective role AND model; a capability swap never changes authority.
- **2 — composite adopted.** Standup registry keyed by (issue, base revision)
  with accountable chair and expiry; at most one open standup per key;
  attendance clones are terminal delegates (may request escalation, may not
  convene). A standup decision is a *proposal* until its accountable owner
  reconciles it against head (`based_on`/`applied_at` both logged);
  reconciliation mechanic is agy's: run the standard speculative merge of the
  decision against the parent's in-flight work — intent conflict squashes the
  speculative work.
- **3 — both weak-boundary candidates recorded** with their detectors:
  monitor→escalation single-live-case invariant (tracer test: kill the harness
  between case creation and decision commit; restart must yield exactly one
  case) and decomposition→review churn metric (repeated rejection rounds with
  zero boundary-test changes ⇒ underspecified contract).
- **4 — sequenced rather than chosen.** agy's objection applies to the *first
  run*, Codex's design to the *first study*: v0.9 is one full-protocol organic
  shakedown, no injected events, with per-work-package token budgets and
  timeouts; v1 is Codex's nine-run design (three smoke runs, three paired
  event scenarios) plus the malformed-wire corpus and immutable run manifests
  with full cost accounting. All ablations deferred.
- **5 — pre-mortems converge on two families:** process-overhead death and
  hidden-state death. Two standing rituals adopted: (i) per-sprint
  meta:product token ratio, watched against the native-loop baseline; (ii)
  the **cold-start audit** at every milestone — a fresh model in a second
  harness gets a clean checkout and must reconstruct current state, open
  obligations, and the next authorized transition from committed artifacts
  alone.
- **6 — Codex's v0 list adopted** (doctrine+glossary, state-transition table,
  minimal templates, one deterministic context-pack binding, manual runbook,
  pilot tracer sprint), manual-first, automation only where the first sprint
  shows repeated human error. **Divergence flagged for CEO:** agy would defer
  multi-provider review in v0; standing CEO preference is council review
  everywhere. Moderator keeps the council (ask-agent makes it nearly free to
  invoke) and records single-provider-review as a bench ablation question.

**Open for Round 2:** (a) CEO ruling on 1a (diagnostic clone vs. direct peek);
(b) does Codex's unified event/case log subsume the interpretation log, or do
they stay separate artifacts; (c) who chairs a standup when the convener is an
interested party; (d) CEO ruling on v0 review breadth.

---

## CEO rulings — Round 1

- **Firewall hardness (1a): not ratified as doctrine — promoted to a bench
  question.** Precedent argument: google3 and Amazon both expose source across
  team boundaries; the API remains the contract anyway. Whether clean-room
  isolation (hard wall / diagnostic clone / direct read) actually reduces
  accidental coupling in *agents* is an empirical claim, so it joins the
  ablation list. Interim default: context assembly still excludes foreign
  source for leanness; a direct peek is an ordinary logged bend.
- **Standup registry: suspected overengineering.** v0 keeps only the minimal
  core — at most one open standup per issue, and decisions reconciled against
  head before they apply. Chair/expiry/affected-artifact formality is deferred
  until a standup storm is actually observed.
- **meta:product token ratio: adopted as a soft constraint** (tripwire and
  retro signal, not a hard gate), consistent with the soft-invariant doctrine.
  **Cold-start audit: adopted** as a standing milestone ritual.
- **v0 review rung: build directly on the existing council-review skill**
  rather than new review machinery. Council review stays in v0 (agy's
  deferral not taken); single-provider review is recorded as a bench
  ablation question instead.
- **Warm-seat rounds: approved and dispatched.** ask-agent gains a
  `--resume <id>` option (dotfiles ditz `ask-agent-session-resume`;
  implementation in flight in tmux `orgs:ask-resume`, Claude Opus). Once it
  lands, fixpoint rounds chain each seat's yielded session instead of
  re-feeding transcripts to fresh instances.

---

## Round 2 agenda

Scope: **the delta only** — the moderator synthesis and CEO rulings above. Do
not re-litigate Round 1 positions the rulings already addressed unless you
have a genuinely new argument. If you find nothing Critical or Important, say
**CLEAN** explicitly.

1. Objections to the CEO rulings as they stand? Notably: firewall hardness
   demoted from doctrine to a bench question (interim: default context
   exclusion, direct peek = ordinary logged bend). If you hold that some
   minimum isolation is non-negotiable rather than empirical, argue it now.
2. Open item (b): does the unified event/case log subsume the interpretation
   log, or do interpretations stay a distinct artifact (contract-adjacent in
   a way deviations are not)?
3. Open item (c): who chairs a standup when the convener is an interested
   party?
4. Fix-introduced regressions only: anything in the rulings themselves that
   creates a new defect.

Seat provenance, Round 2: **Codex = the CEO's original interactive design
conversation, resumed warm as a fork** (the live session continues
independently); **agy = fresh instance on this document**; **Claude =
moderator (native)**.

## Round 2 responses

> Codex seat resumed warm via `codex fork` of the CEO's original conversation
> (fork id `01a05fae`, forked_from `01a05df2` at ordinal 123; the live parent
> session was never touched — codex enforces a single active writer per
> thread, hence fork-then-resume). agy seat fresh on this document.

### agy — Round 2

1. **CLEAN** on the firewall ruling. Testing isolation empirically as a bench question is the correct path. The interim baseline (default exclusion, logged peeks allowed) provides enough flexibility for v0 without over-constraining the initial run.
2. **Interpretations stay distinct.** The unified event/case log is an append-only operational history (deviations, standup minutes, escalations). Interpretations are normative case law bound directly to the contract. An agent consuming a contract must read its interpretations to understand current semantics, but forcing them to read the entire operational ledger to find those semantics would guarantee context bloat and constraint amnesia.
3. **Standup chair:** The accountable lead for that specific contract boundary must chair. A convening worker cannot chair their own standup because they cannot unilaterally waive or redefine a boundary they are bound by; they are proposing a deviation, and the lead must reconcile and accept it.
4. **CLEAN** on fix-introduced regressions.

### Codex (warm, CEO-conversation fork) — Round 2

#### 1. CEO rulings

The firewall ruling restores the position Ted and I had actually reached: the non-negotiable boundary is **dependency isolation**, not epistemic isolation. Looking at foreign source is not itself a contract violation; depending on unpublished behavior is. Default exclusion remains sensible for context leanness, while clean-room implementation, diagnostic clones, and direct inspection become modes the bench can compare.

One Important inconsistency must be resolved: Round 1 accepted that every deviation must name a rollback operation and that irreversible information flow requires a prior huddle. Direct source inspection is irreversible information flow, yet the CEO ruling makes it an ordinary logged bend. The clean resolution is to exempt read-only information access from the general reversibility gate and govern it through the firewall policy:

- Direct inspection is logged with the question that motivated it and any resulting contract gap.
- Publishing, depending upon, or acting across a boundary remains subject to reversibility and authority rules.
- Clean-room independence can be required by a particular work package when it is actually an acceptance condition.

Otherwise the two adopted rules contradict each other.

I concur with the reduced v0 standup machinery, council review in v0, the soft meta:product tripwire, and the cold-start audit.

#### 2. Unified event log versus interpretation log

The unified event ledger should subsume **storage and chronology**, but not the interpretation log's semantic interface.

Interpretations need a distinct contract-adjacent projection or register because agents must be able to ask, "Are there unresolved questions about this contract?" without searching deviations, standups, and operational incidents. Each interpretation record should identify:

- Contract and version.
- The question or ambiguity.
- Whether the ruling is an entailed clarification, temporary exception, or amendment candidate.
- Compatibility rationale and affected consumers.
- The spec revision that canonicalized it, or its expiration.

This must not become a second normative specification. The criterion Ted and I established remains:

> Could a fresh implementer act correctly from the current canonical specification without reading the interpretation history?

If not, a binding interpretation must already have been promoted into the spec or amendment. The register is an inbox, audit trail, and unresolved-work view—not case law that consumers must continually consult.

A useful implementation model is therefore:

```text
append-only event ledger
        ↓
case-state projection
interpretation-register projection
current-contract projection
```

One historical source, multiple purpose-specific views.

#### 3. Standup chair

An interested convener may chair by default. Almost every useful convener is interested; requiring an independent chair for routine coordination would recreate the recursive meeting problem.

The important separation is between **facilitation and decision authority**:

- The convener facilitates and frames the issue.
- Existing ownership determines who adjudicates: ordinarily the affected work-package owner, contract owner, or lowest common accountable lead.
- If that owner's own conduct or ruling is what is being challenged, adjudication moves one authority rung upward.
- If hats have collapsed onto one agent, the adjudication hat receives a fresh context/council review; unresolved authority conflicts reach the CEO.

This can remain a runbook rule in v0 rather than requiring a chair registry.

#### 4. Fix-introduced regressions

**Important — automatic squashing is a new defect.** The moderator adopted agy's mechanic that an intent conflict "squashes the speculative work." That contradicts the earlier conclusion Ted and I reached: speculative commits remain recoverable, and a misprediction does not imply destructive rollback. It also conflicts with the project's recoverability discipline.

A Crystal merge can provide reconciliation evidence, but it cannot adjudicate semantic intent. On return from a standup:

1. Reconcile the proposal against current head.
2. Identify which speculative changes conflict with the decision.
3. Let the accountable owner accept, reject, partially salvage, or supersede them.
4. Preserve the speculative branch/commits for audit and recovery.

"Squash" may mean "do not integrate this line of work," but must not normatively mean resetting the branch to the fork point or discarding all post-fork work.

**Important — the firewall experiment currently has no scheduled resolution.** The CEO correctly promoted isolation hardness to a bench question, while the adopted v1 plan defers all ablations. That can leave the project indefinitely operating under an empirical interim rule without ever testing the disputed claim. No experiment is needed before v0, but the plan should name a checkpoint: after the organic shakedown demonstrates basic protocol reliability, run a matched direct-peek versus diagnostic-clone/clean-room trial before declaring any permanent firewall doctrine.

Those two issues prevent a CLEAN finding.

---

## Moderator synthesis — Round 2 (Claude)

Round 2 is **NOT CLEAN**: one Important inconsistency and one Important
fix-introduced regression, both accepted. Resolutions:

1. **Read-only access exempted from the reversibility gate.** The
   reversibility/rollback rules govern *actions* (publishing, depending,
   acting across a boundary); *reads* are governed by firewall policy —
   logged with the motivating question and any resulting contract gap. A
   work package may require clean-room independence explicitly when it is an
   acceptance condition. This resolves the Round 1 contradiction.
2. **Squash semantics corrected (fix-introduced regression, caught on the
   delta — the fixpoint convention doing its job).** A standup decision that
   invalidates speculative work means *non-integration*, never destruction:
   the worker's line resets, but the speculative branch and commits are
   preserved for audit and salvage, and the accountable owner disposes
   (accept / reject / partially salvage / supersede). Consistent with the
   repo-wide never-delete-branches-until-merged discipline.
3. **Ledger + projections.** Both seats converged with different halves:
   storage unifies (append-only event ledger), semantics stay distinct
   (interpretation register as a contract-adjacent projection, alongside
   case-state and current-contract views). The canonicality criterion
   governs promotion: a fresh implementer must be able to act correctly from
   the canonical spec alone.
4. **Standup chair: facilitation ≠ adjudication.** The convener may chair
   (facilitate); decision authority follows existing ownership (agy's rule
   is the common case: the boundary's accountable lead adjudicates);
   challenges to the adjudicator move one rung up; collapsed hats get a
   fresh-context adjudication. Runbook rule in v0, no registry.
5. **Firewall experiment gets a scheduled checkpoint:** after the organic
   shakedown demonstrates protocol reliability and before any permanent
   firewall doctrine, run a matched direct-peek vs. diagnostic-clone trial.
   The interim rule may not quietly become doctrine by default.

## Round 3 agenda (fix delta only)

Review resolutions 1–5 above. Anything Critical/Important they introduce?
If not, say **CLEAN** — that closes the founding council at fixpoint.

## Round 3 responses

### Codex (warm) — Round 3

CLEAN

### agy — Round 3

**CLEAN**

---

## Closure

**Fixpoint reached 2026-09-01: Round 3 returned CLEAN from every seat.**
The founding council is closed.

Seats over the council's life: Claude/Anthropic (moderator + scribe, native);
Codex/OpenAI (Round 1 fresh; Rounds 2–3 warm via fork `01a05fae` of the CEO's
original design conversation, thread chained across rounds); agy/Google
(fresh instance each round). The CEO ruled between rounds.

Net result: the settled-decisions list above, as amended by the Round 1 CEO
rulings and the Round 2 resolutions, is the design baseline for the self-spec.
The warm seat's Round 2 catch — a fix-introduced regression in squash
semantics — is the founding example of why review rounds run to fixpoint on
the delta.

## Post-closure CEO ruling — 2026-09-02

**"Read firewall" is retired as a concept.** There is no rule about reading,
no peek-logging requirement, and no permission regime on source. What remains:

- **Context assembly is a packing list, not a firewall.** The default work
  package packs the design doc, the relevant contracts, and the owned scope —
  because anything more is noise, not because more is forbidden. A worker may
  read anything in the repo at will.
- **Isolation is enforced at the dependency level, google3-style.** The
  mechanism that actually keeps boundaries honest in a monorepo is build
  visibility, contract tests, and review — not restricted reads. Where the
  build system supports visibility rules, use them; elsewhere, review checks
  that cross-boundary use sticks to published contracts.
- **A peek is a symptom; the filable defect is the unmet information need**
  (CEO refinement, 2026-09-02). Reads themselves are never logged. When a
  worker had to find an answer in a neighbor's source, that is a bug in the
  published surface, and it forks into two inbox types: a **docs bug** — the
  information should live on the published surface; the owning team fixes it
  unilaterally, cheap, no ruling — or an **interpretation request** — the
  contract is genuinely silent or ambiguous about behavior; needs a ruling,
  may promote to spec text. Working rule: *if you had to find it in the
  source, it belongs in the docs.* This matters more for agents than humans:
  the packing-list default means the published surface is what future
  implementers get in context, so an answer that lives only in source is a
  recurring tax on every future work package. Both filing types accumulate
  per boundary as contract-quality and amendment evidence.
- The scheduled bench trial narrows accordingly: it no longer compares
  permission regimes, but **context-packing defaults** (lean pack vs.
  neighbor-source-included) for junior-tier implementers — a context-hygiene
  question, not a security one.

## Post-closure CEO ruling — 2026-09-02: deviation empowerment restored

The CEO caught a doctrinal inconsistency between two settled lines:
"instruction-vs-intent conflict → huddle, never a silent pick" contradicts
the ratified deviation rule "reversible in-scope bends log and proceed." The
second line governs; the first is amended. Corrected doctrine:

- **The Boydian default stands: those on the ground are empowered to deviate
  from instruction to serve intent, on their own judgment — logged, not
  asked.** "Never a silent pick" narrows to "never an *unlogged* pick."
- The huddle is **mandatory** only where the reversibility gate already
  requires it (irreversible effects, boundary-crossing, beyond owned scope),
  and **voluntary** whenever the worker is uncertain what intent requires.
- Fork-and-continue makes the voluntary huddle *cheaper* than human
  consultation — the worker never stops — but **not free, and not
  epistemically privileged** (CEO correction, 2026-09-02). Consultation has
  real latency and real plumbing failure modes (observed in practice:
  writer-lock conflicts, silent wrong-session resumes, minutes-long seat
  round-trips), and — basic Boyd — the adjudicator rules on a transmitted
  snapshot of a world that has moved: the clone carries a compressed, stale
  picture, and the worker's ground truth does not fit through the huddle.
  The `based_on`/`applied_at` reconciliation machinery exists precisely
  because of this. Forward-vested judgment is therefore justified on
  epistemic grounds, not merely permitted by cheap asking.
- **Deviations surface structurally regardless of the log.** Every deviation
  appears in the diff at code review — and agent review is total, not
  sampled; there is no skimming — and in the delta at standup. The review
  ladder is what makes forward-vested authority safe: human mission command
  ran on trust because verification at tempo was impossible; this org keeps
  forward authority AND total verification, a combination human orgs never
  had. The one-line deviation log is an accelerator, not the safety
  mechanism — it converts "anomaly to investigate" into "decision to
  evaluate" for the reviewer.
- Deviations are adjudicated retroactively at the next standup (the manager
  model: justified is justified). A lead may explicitly *tighten* the
  deviation envelope for a specific work package as a stated acceptance
  condition; the doctrine's default stays loose.
