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
- **A real coordination friction, correctly scoped (corrected).** An earlier
  version of this doc said the lead "stalled idle three times ... only
  progressed when hand-nudged." That is wrong, per the lead's own transcript,
  and this doc was the source that wrongly propagated the number into the
  pilot's LESSONS.md. The accurate finding: continuing an already-spawned
  worker via `SendMessage` is **asynchronous with no wait primitive**, so the
  lead had to *notice and route around* the wait on **two** occasions (the
  engine REWORK dispatch and the round-2 fix-delta review). It **self-verified
  and self-resolved each** and finished autonomously — the moderator's two
  out-of-band "unblock" messages **crossed in transit** and were redundant,
  not rescues. Every synchronous `Agent`-tool call (necessity challenge, both
  initial builds, all three lead-reviews) returned in-round with no wait. So
  the coordination cost is real but bounded: manual work to route around an
  async-continuation with no join, not a deadlock requiring external help.

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
more robust on the adversarial surface than the baseline**, at ~5–7× token
cost. The pilot's own tests (82/82) and a 12/12 raw-socket smoke back this up.

### But the CEO-requested cross-provider council then found the protocol's own review was insufficient

When the foreign-provider council (codex + agy) reviewed the pilot server —
the review the sprint had *skipped* (a deviation flagged for CEO ruling) — it
found **six Critical/High crash-or-DoS defects the in-org review ladder
missed**, several verified empirically:

- **The nil crash class RECURRED and was missed.** `SET k <nil>` then
  `INCR k` → `None.decode()` → AttributeError → whole-server crash
  (verified). This is the *same class* the sprint caught in the command-name
  slot and propagated to the C2 clarification — it reappeared in the storage
  path, and the same-provider review did not catch the recurrence.
- Uncaught `ValueError` on >4300-digit integers; unbounded recursion on
  nested arrays; unbounded buffer (OOM); O(n²) partial-frame reparse;
  blocking-I/O slowloris; RESP response-splitting via unsanitized command
  bytes.

The lesson is sharp and it cuts both ways: **defect-class propagation through
contracts is real but bounded to the boundary the worker was reasoning about**
(dispatch, not storage), and **same-provider review has correlated blind spots
that only cross-provider review closes.** The pilot's council-skip was
consequential — provider diversity is load-bearing, not optional. So the
protocol is more robust *than the baseline*, but its internal review ladder
alone was **not sufficient** to ship a network server; the cross-provider
council is the part that was.

## Side-by-side: both builds councilled by the same seats (codex + agy)

The null-check had never been reviewed; giving it the *same* council the pilot
got makes the comparison fair — and the result is levelling.

| Dimension | Null-check (solo, no protocol) | Pilot (full protocol) |
|---|---|---|
| Frozen exam, real redis-cli (nix) | **12/12** | **12/12** |
| Neutral raw-socket grader | 16/16 | 16/16 |
| Own tests | 23/23 (self smoke) | 82/82 |
| Architecture | 1 flat file | 3 firewalled entities + 2 contracts |
| Review *during* build | none | same-provider lead review; **cross-provider council SKIPPED** |
| Council (post-hoc) crash/DoS findings | ~6 Critical/High | ~6 Critical/High |
| — shared by BOTH | INCR-int-crash · response-splitting · OOM (unbounded buffer) · slowloris · length-parse laxity | (same) |
| — divergent | nil bulk silently coerced to empty (latent ambiguity, no crash on nil *command name*) | nil **stored value** → INCR crash (verified); but dispatch-path nil/empty/non-BulkString **hardened + tested** via contract propagation |
| Cost (tokens) | ~80K, one pass | ~632K measured subagents + unbucketed lead design work ≈ **~10×** |
| Production-ready? | No | No |

**The finding:** the two servers have **nearly identical vulnerability
profiles.** Both crash on oversized-integer INCR, both split responses, both
OOM on unbounded frames, both slowloris. The protocol's review ladder caught
and hardened *one* class (dispatch-path nil handling, via defect-class
propagation) that the null-check left as a latent coercion bug — a real but
partial win — and it cost ~10×, yet it **did not close the robustness gap**:
both builds ship the same critical set.

Why? **Neither build ran a cross-provider council *during* construction** — the
pilot skipped it, the null-check had none. The differentiating variable for
robustness is therefore *not* protocol-vs-no-protocol; it is **whether a
cross-provider council ran.** When one finally did (post-hoc), it found the
same crash class in both. That is the sharpest form yet of the 80/20
hypothesis: the load-bearing mechanism is **cross-provider review**, not the
decomposition/contract hierarchy — which bought a partial robustness win and
an audit trail at ~10× cost, without reaching a shippable bar on its own.

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
2. **The coordination friction the protocol hit was async worker-continuation**
   (two `SendMessage` cycles with no wait primitive), which the lead handled
   itself — bounded manual overhead, not a deadlock. It is still a real
   argument for the situational-awareness layer (which would surface a landed
   result automatically instead of the lead polling for it), but a milder one
   than a "the pilot couldn't finish without hand-holding" framing would
   suggest — it finished on its own.

Together these are evidence for the hypothesis in a sharper form than
expected: the high-value, low-cost core is **review + defect-class propagation
through contracts** (which demonstrably paid off here), while the heavy
decomposition/necessity-challenge apparatus is the part whose payoff was not
visible at this scale and may only appear on much larger, multi-team work. A larger
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
