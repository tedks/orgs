# Ablation study: which parts of the org protocol earn their cost?

Run autonomously 2026-09-02/03. The question: on a bounded, externally-gradable
target (the RESP2 tracer server), does the full org protocol produce better
software than simpler regimes, and **which mechanisms carry the value?** Five
regimes, same target, same grader, same cross-provider council applied
uniformly.

## Design and how each regime was run

A regime is the full protocol with mechanisms toggled off (the toggle-based
regime configs used at the time are preserved at tag
`archive/runnable-framework`; the project has since moved to composing regimes
from skills rather than toggling a monolith — see
`docs/design/skill-decomposition.md`). Two regimes reuse builds from earlier in
the project (the "before" states); three are new or analytic:

| Regime | = | How produced |
|---|---|---|
| `raw` | one strong agent, no protocol, no review | the null-check build (Sonnet, one pass) |
| `no-council` | decomposition + tiering + lead review, **no cross-provider council** | the pilot build (it skipped council by instruction) |
| `no-decomposition` | one flat build **+ council-to-fixpoint** | the null-check server, then cross-provider council until CLEAN |
| `full` | decomposition + tiering + review **+ council-to-fixpoint** | the pilot server, then cross-provider council until CLEAN |
| `no-standup` | `full` minus the standup | analytic — see below |

**Grading is uniform.** Every server is graded by the real frozen exam
(`resp_conformance.sh`) under the Nix devshell that provides `redis-cli`
(8.10.1), and every server was subjected to the same cross-provider council
(codex + agy) hunting crash/DoS defects. "Escaped defects" = Critical/High the
council found that the regime shipped.

## Results

| Regime | Frozen exam | Escaped crash/DoS defects | Council rounds to CLEAN | Cost (tokens) |
|---|---|---|---|---|
| `raw` | 12/12 | **~6** (INCR-int crash, response-split, OOM, slowloris, nil-coerce, length laxity) | never run in-build | **~80K** |
| `no-council` | 12/12 | **~6** (nil-value crash, INCR-int, recursion, response-split, OOM, slowloris) | never run in-build | **~632K + unbucketed lead work (~10×)** |
| `no-decomposition` | 12/12 | **0 in-scope** (CLEAN) | **5** | ~80K + 5 council rounds |
| `full` | 12/12 | **0 in-scope** (CLEAN) | **2** † | ~632K + 2 council rounds |
| `no-standup` | = `full` | = `full` | = `full` | = `full` (see below) |

† The 2-vs-5 round gap is **partly a confound, not a pure regime effect** —
see Caveats. All four hardened/graded servers pass 12/12 conformance
regardless of regime; conformance saturates and does not discriminate.

## The decisive findings

**1. The cross-provider council is the keystone for robustness.** The two
regimes *without* council-to-fixpoint (`raw`, `no-council`) both shipped ~6
Critical/High crash-or-DoS defects — a nil value or oversized integer or
malformed frame terminates the whole server process. The two regimes *with*
council-to-fixpoint (`no-decomposition`, `full`) both reached a clean, shippable
bar. **Whether a cross-provider council ran is the variable that separates
"crashes on the first bad byte" from "shippable" — not protocol-vs-no-protocol.**

**2. The decomposition hierarchy is largely optional for robustness at this
scale.** `no-decomposition` (one flat file + council) reached the *same* clean
bar as `full` (three firewalled entities + contracts + council). The
hierarchy did not produce robustness the council didn't already produce. Its
distinctive contribution — real, but narrower than its cost — was **defect-class
propagation**: the pilot's own review caught a nil-command crash, promoted it
to a contract clarification, and the next worker pre-hardened its dispatch
path against the class. That gave `full` a head start on ~2 of the ~8 defect
types. But the flat build reached the same endpoint; the propagation shortened
the path, it wasn't necessary for the destination.

**3. Same-provider review is not enough; provider diversity is.** `no-council`
had a *lead review* (same-provider, Claude-reviews-Claude) and still shipped 6
crashes — including the nil class *recurring in the storage path* that the
same review had just caught in the dispatch path. The cross-provider council
caught all of it. Correlated blind spots are real and only cross-provider
review closes them.

**4. The dominant cost is the hierarchy, and it did not buy proportional
value.** `full`/`no-council` cost ~10× `raw`/`no-decomposition` (measured
coordination:product ≈ 1:1 ≈ 632K, *plus* the lead's unbucketed decomposition
work — the largest single slice). The council-to-fixpoint that produced the
actual robustness cost only a handful of review rounds on top of the *cheap*
flat build. So the expensive part (decomposition) and the valuable part
(council) are different parts.

## Conclusion on the "standup is the 80/20" hypothesis

The study confirms the hypothesis in a sharpened form, and extends it:
**the load-bearing, low-cost core is cross-provider review-to-fixpoint** (and,
by the earlier finding + prior-art survey, the standup/forced-observe layer for
keeping running agents on track). The heavy decomposition/contract hierarchy is
the expensive part whose robustness payoff was not visible at 3-entity scale —
it bought a partial head-start (defect-class propagation) and an audit trail at
~10× cost. On this evidence, a lean org — **cheap build + cross-provider
council-to-fixpoint + forced-observe** — captures most of the measurable value
at a fraction of the cost. The full hierarchy must justify itself on a larger,
multi-team target where its coordination structure could plausibly matter.

## Caveats — what this study does NOT establish

- **Single target, single run per regime.** One RESP tracer, no replication.
  This is a shakedown, not a powered study; the numbers are directional.
- **The 2-vs-5 round gap is confounded.** `full` converged in 2 council rounds
  partly because I applied the fix-set *already learned* from `no-decomposition`'s
  5 rounds, and partly because the pilot's defect-class propagation had
  pre-hardened the engine. A clean measurement would run the two council loops
  blind and independently. The safe claim is only that **both reached the same
  clean bar**; the round-count difference is not a clean regime effect.
- **`no-standup` is untested, not equal-by-measurement.** At 3-entity
  sequential scale the standup never *triggered* (no rabbit-hole, no budget
  tripwire, no parallel branches), so `no-standup` produced the identical
  outcome to `full` — a **null result from absence of trigger, not evidence the
  standup lacks value.** Testing it needs a scenario that fires it: parallel
  workers, a planted rabbit-hole, or a longer run. That is the most important
  gap to close next, because the standup is the project's most novel bet.
- **"Escaped defects" is a council-found proxy**, itself bounded by what codex
  + agy caught; a third provider or a fuzzer might find more in every regime.
- **Fixer identity.** The council-to-fixpoint fixes were applied by the
  moderator (a strong model), not a regime-tier implementer. This measures
  whether the council *process* converges to clean and at what review cost, not
  who types the patch.

## Artifacts

Per-regime servers under `bench/study/<regime>/`; each hardened server passes
12/12 and survives the crash-probe battery (oversized INCR / length / count,
deep nesting, nil-value INCR, CRLF command). Regime configs preserved at tag
`archive/runnable-framework`.
