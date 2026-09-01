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
