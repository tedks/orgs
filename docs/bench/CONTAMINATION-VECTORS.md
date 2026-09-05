# What contaminates a comparative agent study

Distilled from hardening `bench/harness/run_regime.py` — a single orchestrator
that ran six ablation arms over one shared substrate — through eleven
cross-provider council rounds (Claude + codex + agy). Roughly seventy defects
were found and fixed; these are the ones that would have **silently biased the
comparison** rather than crashing the run.

This file exists because the harness approach was superseded by physical
isolation (a separate Claude config + protocol copy per arm). The list is the
lasting output: it is the specification of **what has to be isolated**, and
the evidence for why policing a shared substrate is the harder road.

Every vector below was verified against real code or a real run, not
theorised. The failure mode they share: **no error, no crash, just a wrong
number in the results table.**

---

## Class 1 — The agent can tell which arm it is in

The sharpest class, and the one physical isolation eliminates by
construction. An agent that knows it is the ablation may behave differently,
and nothing downstream can detect it.

1. **The regime name was in the branch and the working directory.**
   `bench-run/r5-orgs-no-crystal-no-standup-…`, and a worktree path to match.
   Every build prompt states both outright. The agent could read its own arm,
   and which mechanism it was missing, off its own `cwd`.
   *Fixed by an opaque slug — but see 3 and 4.*

2. **Switched-off mechanisms were named in the prompt.** The toggle table
   said "`crystal` | OFF — do not reintroduce it". A precedence warning is
   still the word `crystal` in the prompt of the arm defined by not having
   it. *Fixed: the table lists only what is ON and declares itself
   exhaustive.*

3. **The "opaque" slug was not opaque.** *(found last, unfixed)* It was a
   public deterministic hash of the run id (current minute) and one of six
   known regime names — an agent can enumerate six candidates and recover its
   arm. Blinding by hash requires a secret, not just a hash.

4. **The review worktree still carried the regime name.** *(found last,
   unfixed)* The build tree was moved under a neutral root; the review tree
   stayed under `run_dir`, which contains the regime — and grading executes
   the server from there, so `__file__` reveals the arm to the code under
   test. **An incomplete fix to vector 1, made by the same person who wrote
   vector 1's fix.**

5. **The parent session's environment reached every "fresh" agent.**
   `CLAUDECODE`, session ids, job paths, messaging sockets — inherited whole.
   "Fresh process, no inherited context" was false. *Fixed by an explicit
   scrub with a credential keep-list; scrubbing credentials too would
   silently turn a councilled arm into an un-councilled one.*

## Class 2 — The ablation did not remove the mechanism

6. **Ablations did not ablate the instructions.** The lead received the full
   runbook with "run it in order", so the no-crystal arm was still instructed
   by §7 to run speculative merge checks. For a process ablation the runbook
   is not a shared input — **it is the treatment.** *Fixed by filtering
   sections and scrubbing residual mentions.*

7. **Scrubbing a mechanism name ate a common English word.** Deriving the
   word from the heading `6. review ladder` yielded `review`, replacing every
   occurrence in the document. The fix for vector 6 corrupted the runbook of
   the arm it was protecting. *Fixed: only distinctively-named mechanisms are
   scrubbable; for the rest, removing the section is the whole ablation.*

8. **A mechanism could be ON and inert.** Crystal detected conflicts into a
   log file and told nobody, while the prompt promised the lead they would
   arrive at standup. The crystal arm and the no-crystal arm would have
   differed by one paragraph. *Fixed by delivering over the bus; and a
   mechanism configured on that never functioned is now a recorded failure.*

9. **The standup's stall signal was fabricated.** `standup.sh` greps
   `git log --all --grep=<agent-id>`; in a shared bare repo the id `codec`
   matched twelve pre-existing commits, newest 344 minutes old. Every agent
   read as stalled from the first observe, so the standup arms would have
   been fed a stream of false "you have not committed" redirects the
   standup-off arms never see. *Fixed by run-unique agent ids.*

10. **Worker briefs carried doctrine the lead was denied.** The control arm's
    contamination, one level down.

## Class 3 — The measurement was not measuring what it claimed

11. **An earlier illustrative `[]` could become the recorded result.** The
    findings parser fell back from the required final fenced block to
    *earlier* ones, so a reviewer that showed the format as an example and
    then emitted a malformed real block was recorded as finding nothing. A
    silent clean verdict from a review that failed. **Nine council rounds
    walked past this; a fresh full review caught it immediately** — see
    LESSONS 2026-09-03 on delta-only fixpoint.

12. **A missing seat was a silent zero.** One provider rate-limited meant the
    round still counted, with the surviving seat's opinion wearing a two-seat
    label. *Fixed: `parse_ok` means every seat answered; partial rounds are
    marked and never fill the headline field.*

13. **A failed seat's partial output was parsed.** A timed-out reply yields a
    plausible, smaller number indistinguishable from a real one.

14. **The arm that built nothing scored the best robustness result.** The
    audit had no no-server guard, so both seats correctly answered `[]` and
    the arm banked zero escaped defects. *Fixed: null, not zero, and the
    guard keys on what the seats can actually SEE, not on the file existing.*

15. **Cost mixed measured with estimated.** `claude -p` reports usage;
    `ask-agent` reports none, so foreign seats are estimated at chars/4. The
    native-review arm and the council arm are **not comparable on cost** —
    part of the gap is an artefact of counting. *Not fixable here (accepted
    limitation, CTO 2026-09-03): both halves are reported and the bucket is
    flagged incomparable. No precision is faked.*

16. **A budget verdict depended on the mechanism under test.** Failing an
    estimated total against an exact budget meant a council arm could fail a
    budget a native arm passed on identical real spend.

17. **Fix-introduced regressions were invisible.** The metric compared pass
    *counts*, so a fix repairing one assertion and breaking another reported
    zero — the exact case it exists to find. *Fixed by comparing failing
    assertion names.*

18. **Findings were summed across rounds**, so an arm configured for more
    rounds accumulated more. *Fixed: `first_round` is the comparable figure.*

19. **The graded bytes were not the named revision.** The diff came from
    `base..head` while grading and source-inlining read the live working
    tree; uncommitted work was graded under a sha that did not contain it.

20. **The score was forgeable by the thing being scored.** The exam
    backgrounds the server, so its stdout interleaves; an unanchored search
    would scrape a `conformance: 16 passed, 0 failed` the *server* printed.
    *Fixed: exactly one anchored line on stdout, cross-checked against the
    exit status the server cannot forge.*

## Class 4 — Runs leaked into each other

21. **A clean exit did not mean nothing survived.** The process group was
    swept only on timeout, so a backgrounded server or leftover agent child
    outlived its arm — holding a port, billing tokens, mutating a worktree
    into the next arm.

22. **The watchdog censored the treatment.** A single wall-clock bound across
    arms is not neutral: computed from their own timeouts, the review-heavy
    arms need 8.7h and the baseline 4.7h, so one 5h watchdog would have
    killed exactly the arms with more review — turning "more review" into
    "failed arm" in the results. *Fixed: each arm reports its own ceiling.*

23. **SIGTERM terminated without raising**, so the watchdog added to bound an
    arm would have orphaned the agent it was bounding. The robustness fix
    contained the robustness bug.

24. **Inputs were recorded but not enforced.** Each arm independently
    resolved `master` and re-read the spec/exam; a commit between arms gave
    later ones a different target with nothing looking wrong afterwards.
    *Fixed by a preflight pin — which still does not cover the prompt
    fragments (unfixed, found last): `load_template` re-reads them per arm.*

25. **A stale worktree registration broke the next run.** Cleanup named the
    pre-slug worker path, so registrations survived and a later
    `worktree add` at the same path failed.

---

## What this says about the design

Vectors 1–5 and 21–25 are **not really about the harness**. They are about
six arms sharing one repository, one process environment, one filesystem
namespace and one set of refs, with the orchestrator responsible for keeping
them apart at every point of contact. Every fix above is the harness
policing a substrate it does not own — and three of them (3, 4, 7, 23) are
fixes that introduced the next defect.

Under per-arm physical isolation most of this class stops being enforceable
work and becomes true by construction: there is no shared ref namespace to
bleed a stall signal across, no sibling arm's directory to name, no inherited
session, no cross-run worktree registration. What remains genuinely hard —
and does **not** go away — is Class 3: measurement honesty. Unparsed is not
zero, a missing seat is not a clean seat, estimated is not measured, and the
thing being scored must not be able to write its own score. Those need the
same care in any design.

## Unfixed at hand-off

Six findings from the final council round, verified but not repaired because
the approach was redirected. Recorded so nothing is lost:

| # | Severity | Finding |
|---|---|---|
| 3 | Critical | the slug is a public hash of low-entropy inputs; six candidates are enumerable |
| 4 | Critical | the review worktree still names the regime, and grading executes the server from it |
| 24 | Critical | the study pin does not cover `bench/harness/prompts/*.md` |
| — | Critical | `worst_case_runtime_s` omits git-bounded overhead, so the margin may still be short |
| — | Critical | signal handling is main-thread only; a signal during a council join orphans seat subprocesses |
| 20 | Important | an untrusted grade still populates the headline `grading` counts without the trust flag |

Full text: the council transcripts under this session's job directory, and
the commit messages from `03e7ad7` to `5a665be` on `runnable-framework`.
