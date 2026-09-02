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

## 2026-09-02 — Naming a caught defect class in the next worker's manifest prevents a repeat

- **What happened:** on the resp-tracer pilot sprint (RESP2 server, three
  work packages: resp-codec, command-engine, server), lead review of
  command-engine caught a real crash: a wire-producible RESP nil bulk
  string in the command-name slot (`*1\r\n$-1\r\n`) reached
  `execute()` and raised an uncaught `AttributeError`, which would have
  taken down the whole server process. The server work package's context
  manifest explicitly named this defect class ("this package's own
  review found the command-engine package's real defect... worth the
  server implementer knowing that boundary tests are necessary but not
  sufficient evidence"). The server implementer, unprompted beyond that,
  swept its own integration surface for the analogous shape and found
  three more instances (empty `Array`, nil `Array`, non-`BulkString`
  element — all C1-well-formed, all C2-undefined, all crash `engine.py`
  by inspection) *before submitting*, fixed them, and logged the
  deviation with a full repro. Lead review confirmed all four were real
  and the fix correct, on the first round — no REWORK cycle needed.
- **Evidence:** `events/resp-tracer/lead.md` lead:12 (command-engine
  REWORK finding), lead:18 (server ACCEPTED round 1), lead:27 (lesson
  filed at retro); `events/resp-tracer/worker-server.md` worker-server:1;
  `context-manifests/server.md`.
- **Applies when:** decomposing sequential/dependent work packages within
  one sprint where an earlier package's review surfaces a defect *class*
  (not just a one-off bug) that a later package's integration surface
  could plausibly share. Naming the class explicitly in the later
  package's context manifest — not just fixing the one instance — moved
  the catch from "review ladder, one more round" to "implementer,
  pre-submission, zero extra rounds." Cheaper than relying on review to
  independently rediscover the same shape per package.
- **Reconsider when:** the org has tooling that propagates review
  findings into context manifests automatically (a defect-class registry
  keyed by pattern, not just this sprint's ad hoc lead judgment about
  what to mention).

## 2026-09-02 — Concurrent same-worktree commits need per-worker isolation, not lead discretion

- **What happened:** the resp-tracer sprint's necessity challenge
  confirmed resp-codec and command-engine were fully independent and
  parallelizable, but both workers were instructed (by the sprint's
  launch message) to commit directly onto the shared `pilot-resp`
  working tree with no per-worker worktree. Dispatching both as
  concurrent Agent-tool subagents would have risked git index-lock
  contention or interleaved partial state on concurrent `git commit`
  calls against the same `.git` — a real risk even though the two
  packages touch disjoint files, since the *git operations* (not the
  file contents) are what race. The lead deviated to sequential dispatch
  instead, which cost wall-clock but no token/quality overhead, and
  logged a protocol friction note at dispatch time rather than only
  discovering the tradeoff by hitting it.
- **Evidence:** `events/resp-tracer/lead.md` lead:7 (deviation), lead:24
  (retro adjudication: justified).
- **Applies when:** dispatching two or more work packages the necessity
  challenge (or decomposition) has confirmed are independent, when the
  binding's own guidance (`bindings/claude-code.md`: "Team isolation: git
  worktrees per team/branch") is available but the sprint's launch
  instruction didn't specify per-worker worktrees. RUNBOOK §4 should
  either call for per-worker scratch worktrees (fast-forward-merged by
  the integration owner) whenever packages are dispatched concurrently
  to the *same* branch, or explicitly bless sequential dispatch as the
  v0 default for small (2-3 worker) pilots — right now a lead has to
  rediscover this tradeoff from first principles each time.
- **Reconsider when:** the runbook is amended to pick one of the two
  options above, or the harness's Agent tool gains its own worktree
  isolation flag that removes the git-race risk without lead discretion.

## 2026-09-02 — The v0 meta:product buckets have no home for the lead's own decomposition work

- **What happened:** computing the resp-tracer sprint's meta:product
  ratio at retro (RUNBOOK §8's v0 operational definition) surfaced that
  the bucket list — coordination: huddle, standup, review-seat,
  necessity-challenge, ledger-maintenance; product: implementer
  work-package invocations — has no bucket for the lead's own
  decomposition (contract authoring, work-package cutting, dispatch-
  prompt writing) or tracer-bullet building (RUNBOOK §3's step 1,
  explicitly performed *before* work packages exist, so it can't be an
  "implementer work-package invocation"). That work was the single
  largest continuous chunk of this sprint's lead-session token usage
  (order ~260K tokens across the sprint, by the harness's own running
  budget counter), uncounted in either bucket, versus ~315K measured
  product and ~318K measured coordination from subagent invocations
  alone. Reporting a ratio without surfacing this gap would have looked
  more finished than the definition actually supports.
- **Evidence:** `events/resp-tracer/lead.md` lead:28.
- **Applies when:** any future sprint computes a meta:product ratio under
  the current v0 definition. Either add explicit buckets for
  "decomposition/contract-authoring" and "tracer-bullet-build" (as
  coordination and product respectively, matching their nearest-neighbor
  RUNBOOK phase), or state a rule for splitting a lead's continuous
  session token usage across buckets, so two sprints' ratios are
  actually comparable rather than each lead making an ad hoc call.
- **Reconsider when:** RUNBOOK §8's operational definition is amended to
  close this gap, or tooling attributes token usage per-phase
  automatically rather than per-invocation.

## 2026-09-02 — A frozen fixture bug is exactly the kind of thing self-review should catch, and did

- **What happened:** the lead's own pre-written, frozen boundary-test
  fixture (`test_codec_boundary.py`) had a real bug — a hardcoded RESP
  length prefix (`$7`) one byte off from the actual 6-byte payload it
  was testing — that would have failed a *correct* implementation and
  silently rewarded an incorrect one that special-cased around it. The
  resp-codec implementer (Sonnet) caught it during self-review, did not
  edit the frozen file (correctly out of scope), filed it as a docs-bug
  with a from-first-principles argument (byte-counted the payload,
  cross-checked against a sibling passing test and the round-trip test)
  rather than assuming its own implementation must be wrong, and worked
  around it in its own test file so the two known-bad assertions didn't
  block progress. The lead fixed the fixture and reran to confirm.
- **Evidence:** `events/resp-tracer/lead.md` lead:8, lead:10;
  `events/resp-tracer/worker-codec.md` worker-codec:1.
- **Applies when:** any sprint where the lead pre-writes frozen boundary
  tests before fan-out (RUNBOOK §3.4) — those tests are exactly as
  fallible as any other authored artifact, and this sprint is direct
  evidence the review ladder catches lead-authored defects, not only
  worker-authored ones, *when* implementers are prompted (as this
  sprint's work packages were) to trust the contract's stated invariants
  over a specific test's literal bytes when the two conflict, and to
  file rather than silently work around or silently defer to the test.
- **Reconsider when:** boundary-test fixtures are generated
  mechanically from the contract's own wire-format table (removing the
  hand-transcription step where this kind of typo enters).

## 2026-09-02 — Resuming a discrete-turn worker via SendMessage has no wait primitive

- **What happened:** when command-engine came back REWORK, the runbook's
  "one feedback round to the implementer before any takeover" (RUNBOOK
  §6 step 4) was implemented by `SendMessage`-resuming the same
  Agent-tool subagent (per the binding: "Same-tier continuation of a
  running worker"). Unlike a fresh `Agent` tool call — which blocks and
  returns the full result synchronously in the same turn — the resumed
  subagent's reply arrives asynchronously as a later teammate message,
  with no tool available to block-wait for it (the harness explicitly
  warns against polling `ListAgents` in a loop). The lead had no
  productive path forward on the *blocked* package and used the wait
  productively on independent, unblocked prep (the raw-socket
  conformance substitute) rather than stalling — but this required
  noticing the asymmetry and improvising a workaround, not something the
  runbook told the lead to expect or plan for. This happened **twice**
  this sprint (the command-engine REWORK dispatch, and the round-2
  fix-delta re-review dispatch) — both self-verified and self-resolved
  by the lead's own next tool calls (re-running the repro and boundary
  tests; reading the CLEAN verdict) before any external nudge, not
  rescued by one. **Correction:** a concurrent bench-comparison write-up
  originally characterized this as "the lead stalled idle three times,"
  which this entry repeated uncritically at first filing; that count was
  wrong and has since been corrected at the source
  (`benchcmp` worktree, `docs/bench/resp-v0-comparison.md`,
  reconciled 2026-09-02 after the lead's own turn-by-turn transcript
  showed two cycles, not three) — recorded here as an example of
  provenance pollution (an unverified figure from one artifact silently
  becoming "evidence" in another) as much as of the underlying finding.
- **Evidence:** this session's own SendMessage calls to
  `ae1c424bf87a43ecf` (rework) and `adc6e2c6469f8d1df` (round-2
  re-review) — two, per the lead's own transcript;
  `/home/tedks/Projects/orgs/benchcmp/docs/bench/resp-v0-comparison.md`
  (corrected copy, post-reconciliation).
- **Applies when:** any review round beyond round 1 (feedback rounds,
  warm-chained re-review) that continues a subagent via `SendMessage`
  rather than a fresh `Agent` call. The binding
  (`bindings/claude-code.md`) documents *how* to continue a worker but
  not that doing so changes the call from synchronous to asynchronous —
  a lead following the binding literally has no signal to plan around
  the wait. RUNBOOK or the binding should say explicitly: after the
  first round, expect asynchronous turnaround, and either queue
  independent prep work before sending, or accept idle wall-clock time
  as a normal cost of the review-round-2+ pattern.
- **Reconsider when:** the harness exposes a blocking wait (or
  `notify_when_idle`-equivalent) usable from a non-main teammate session,
  removing the need for a lead to manually improvise parallel prep work
  to avoid stalling.
