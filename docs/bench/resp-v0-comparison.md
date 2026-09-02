# Bench: RESP v0 — null-check vs. protocol (first stab)

The first real bench run of the project's central question: does the org
protocol produce better software than a single capable agent handed the same
spec, and at what cost? Same target (the RESP tracer spec), same neutral
grader, two regimes built in parallel.

## Grading note

`redis-cli` (the frozen exam's external client) is **not installed** in this
environment, so `bench/conformance/resp_conformance.sh` exits 2 by design.
Both regimes are therefore graded by **`resp_grade_rawsocket.py`** — a neutral
grader authored from the spec's frozen assertion list, driving the server with
hand-built RESP2 frames over one socket (no client library). It is independent
of both builds, so it grades them on identical terms. This is a stand-in for
the real frozen exam, honest about that limitation: it covers the same
assertions (16 checks incl. binary-safe CRLF+NUL and true pipelining) but is
not the frozen artifact run against a real `redis-cli`.

## Regime 1 — null-check (control): one agent, no protocol

- **Model:** Sonnet, single agent, goal-directed, no org ceremony.
- **Result:** 16/16 neutral grader · 23/23 self-authored smoke test.
- **Cost:** ~80K tokens · ~15 tool-call rounds · 15–20 min · one build pass +
  one self-directed adversarial QA pass (no reviewer).
- **Notable:** with no review loop, the agent *still* threw an adversarial
  probe at its own parser after its smoke test was green, and found + fixed a
  real bug (any negative bulk length treated as the `-1` null-bulk sentinel;
  malformed `$-5` swallowed as an empty arg instead of connection-fatal). A
  solo capable agent self-reviews to a degree.
- **Shape:** single flat `server.py`, no codec/engine/server split (the
  protocol's firewall boundaries were deliberately skipped).
- **Honest gaps:** INCR accepts leading-zero integers real Redis rejects;
  inline-command fallback unverified; never run against the real frozen exam.

## Regime 2 — protocol: L6 lead + tiered workers

- **Model mix:** Sonnet lead; workers Sonnet (resp-codec), Haiku (command-
  engine), Sonnet (server); Sonnet lead-review seats.
- **Result:** **16/16 neutral grader** — identical graded conformance to the
  baseline. The protocol did **not** produce a more *conformant* server on
  this task.
- **Cost:** materially higher — conservatively **~5–7× the baseline** across
  all subagents (measured fragments: the command-engine worker alone was
  ~77K tokens and its single lead-review ~87K; times three packages plus the
  lead's own orchestration puts the total in the ~400–600K range vs. ~80K).
  Precise split awaits the pilot's own retro.
- **What the protocol bought that the baseline did NOT get:**
  1. **A real caught bug.** The lead review found a wire-producible nil
     command-name that `AttributeError`s and crashes the whole server
     process; sent it back REWORK; verified the fix to fixpoint. The
     null-check shipped with no reviewer and honest un-graded gaps.
  2. **Firewalled architecture** — three entities (codec/engine/server) with
     published contracts and pre-written boundary tests, vs. one flat file.
  3. **A full audit trail** — roster, per-actor event ledger, deviation log,
     a self-caught docs-bug in a frozen test fixture, review findings.
- **The dominant cost was coordination, not review.** The lead stalled idle
  **three times** waiting on subagent results that had already been
  delivered — a message-delivery gap, not a protocol defect (the protocol
  work completed correctly each time). It only progressed when hand-nudged.

## Correction (after the pilot completed)

The "equal graded correctness" headline is true only of the **16 graded
assertions** — and it undersells the protocol. On the **un-graded adversarial
surface** (malformed wire input) the protocol build is meaningfully more
robust, via a mechanism the baseline structurally cannot have:

- Lead review found a crash class — a wire-producible RESP nil bulk string as
  the command name `AttributeError`s and kills the whole server process (a DoS
  on a network server, not a cosmetic bug) — fixed it to fixpoint over two
  rounds, and **promoted the fix as a contract clarification**.
- The server implementer, handed that defect class in its **context manifest**,
  then independently found and fixed **three more instances of the same shape**
  (nil arrays, non-`BulkString` elements, empty arrays) before ever submitting.

This is **defect-class propagation through the published contract** — a bug
found in one entity becomes a contract clarification that is packed into the
next worker's context, preventing the whole class. It is the firewall/contract
/context-assembly thesis delivering: knowledge flows through the published
surface, not by everyone reading everyone's code. The null-check, single flat
file with no reviewer, shipped with honest un-graded gaps and no mechanism to
catch or propagate any of this — a real network server built that way would
crash on the first malformed frame.

So the honest comparison is: **equal on graded conformance, protocol
materially more robust on the adversarial surface**, at ~5–7× token cost. The
pilot's own tests (82/82) and a 12/12 raw-socket smoke back this up.

## Reading

On a bounded 3-entity task, the full protocol cost ~5–7× the tokens of a
single capable agent for equal *graded* correctness plus materially better
robustness, buying a caught+propagated crash class, firewalled architecture,
and an audit trail. Two things follow, both
bearing on the "standup is the 80/20" hypothesis:

1. **The value the protocol added was concentrated in the review ladder**
   (the caught crash), not in the full contract/decomposition hierarchy — the
   architecture and ledger are nice but did not change the graded outcome
   here.
2. **The cost the protocol added was concentrated in coordination** (the three
   delivery-stall deadlocks), not in the review. The lead spent its overhead
   getting stuck, not reviewing.

Together these are direct evidence for the hypothesis in a sharper form than
expected: the high-value, low-cost core is **review + keeping agents observing
each other** (the standup / forced-observe layer), while the heavy
decomposition/contract hierarchy is the part whose payoff was not visible at
this scale and may only appear on much larger, multi-team work. A larger
target (more entities, real cross-boundary integration, a late amendment) is
needed before the full hierarchy can justify its multiple — which is exactly
what bench v1's paired-scenario runs are for.

## The question this run informs

The null-check set a high bar: ~80K tokens to a correct server, in one pass,
by one mid-tier model, with a spontaneous self-QA that caught its own bug. For
the protocol to justify its ceremony on a task this size it must either (a)
produce a *more correct / more robust* server (e.g. catch the corners the
solo agent cut), or (b) do so at competitive quality-adjusted cost with
cheaper workers. If instead the protocol costs multiples more tokens for the
same or worse correctness on a 3-entity task, that is direct evidence for the
"standup is the 80/20" hypothesis — that the coordination *value* concentrates
in a few lightweight mechanisms (keeping an agent observing, catching
rabbit-holes) rather than the full contract/decomposition/review hierarchy,
which may only pay off at larger scale. Recorded honestly either way.
