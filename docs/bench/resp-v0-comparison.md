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

*(pending — the pilot build is still running; graded the same way when it
lands. To record: neutral-grader score, token/round cost split into
coordination vs. product, wall-clock, whether the protocol was followable,
where it helped vs. was pure overhead, and the lead's meta:product impression
on a 3-entity sprint.)*

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
