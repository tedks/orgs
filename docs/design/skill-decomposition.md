# The protocol as a graph of skills — decomposition draft

**Status:** draft for CEO sanity-check before building. Supersedes the
monolithic `run_regime.py` orchestrator approach (see
`docs/bench/CONTAMINATION-VECTORS.md` for why that shape kept springing
leaks).

## The idea in one paragraph

Decompose the protocol into small, independently-usable **skills**. A **root
skill** composes them into "the protocol." An **experimental variety** is just
a root skill that composes a *different subset* — and it runs in its own
isolated Claude config that only has *that subset installed*. So "run the full
protocol," "run an ablation," and "ship the real skillset" are one artifact.
There is no toggle logic anywhere: a variety that lacks standup literally does
not have the standup skill, so nothing can leak it into a prompt.

## Design rules

1. **A skill is one act an agent performs**, with a clear input and a clear
   output artifact. Not a phase label — an invokable unit.
2. **Skills wrap what already exists**; they don't reinvent it. `standup/`,
   `crystal/`, `protocol/templates/`, `council-review`, `ask-agent` become
   the implementations *behind* skills.
3. **Composition is by inclusion, never by flag.** A variety's root skill
   lists the skills it uses; an absent skill is absent. (Rejected: one root
   skill with a "mechanisms on/off" manifest — that reintroduces exactly the
   toggle→prompt leak class that cost a night.)
4. **The evaluator lives outside every variety.** Grading, auditing, and
   measuring are not skills the agent has; the thing being scored must not be
   able to touch its score.

## The sub-skills

| skill | the act | input → output | wraps |
|---|---|---|---|
| `orgs:spec` | CEO+CTO author the contracts-first design doc | intent → `docs/specs/<name>.md` (goals, non-goals, entities, **boundaries/contracts**, milestones, stop conditions) | `docs/spec-template.md` |
| `orgs:decompose` | lead turns a spec into executable work: player-coach **tracer bullet**, published **contracts + boundary tests**, **work packages** with intent, **necessity challenge** | spec → `contracts/*.md`, `work-packages/*.md`, tracer commit | `protocol/RUNBOOK.md` §2–4, templates |
| `orgs:implement` | one worker builds one work package inside its firewalled scope | work package + context pack → commits on its branch + `status/<wp>.md` | `protocol/RUNBOOK.md` §5 |
| `orgs:review` | one-rung-up review to fixpoint on the fix delta (the ladder step; parameterized by rung: lead / CTO) | frozen revision → `review-findings` + verdict, re-run on the delta until CLEAN | RUNBOOK §6, review-findings template |
| `orgs:council` | cross-provider review to fixpoint (own-provider native seat + foreign seats) | frozen revision → per-seat findings + union verdict | `council-review` + `ask-agent` |
| `orgs:standup` | situational awareness: observe the org, redirect or halt a drifting agent, deliver via the bus | cadence/trigger → `redirect`/`halt` messages agents *must* observe | `standup/` (bus, guard, standup.sh) |
| `orgs:crystal` | speculative merge-check across concurrent branches; report semantic conflicts *to the lead* | worker branches → conflict report delivered to the lead (never just a log) | `crystal/crystal-check.sh` |
| `orgs:integrate` | merge accepted packages, run the target's conformance, record the integration | accepted WPs → integration commit + conformance result | RUNBOOK §7 |
| `orgs:huddle` | escalate at the reversibility gate (irreversible / boundary-crossing / out-of-scope) | a gated decision → huddle record + ruling | RUNBOOK §5b |
| `orgs:retro` | close the sprint: lessons, `meta:product`, deviation adjudication | sprint artifacts → `LESSONS.md` entries + closure ledger entry | RUNBOOK §8 |

## Cross-cutting pieces (used *by* skills; not phases)

| piece | role |
|---|---|
| `orgs:pack` | **The firewall.** Assembles a role's context manifest: doctrine block + the role's hat + *only* its scope and the published contracts it may depend on. Used by `decompose` (to pack workers), `review`/`council` (to pack fresh judgment-role reviewers), `implement` (to read its pack). Lean-vs-full packing lives here and *only* here. |
| `orgs:ledger` | Event log + status. Every skill appends its state transitions (`protocol/STATES.md`) and records deviations. Sharded per actor, id `<actor>:<seq>`, causal `refs`. |
| doctrine block | `DOCTRINE.md`'s "Prompt block," prepended verbatim to every role prompt by `pack`. |

## The graph

```
orgs:sprint  (root — one file per variety)
├── orgs:spec                (fixed shared input for the study; see §Variants)
├── orgs:decompose ──uses──► orgs:pack
├── orgs:implement ×N        (parallel, one branch each) ──uses──► orgs:pack
│     └── if standup present: dev-loop commands run through guard.sh
├── orgs:standup             (observes ↑, injects redirect/halt onto the bus)
├── orgs:crystal             (watches the N branches, reports to the lead)
├── orgs:council ──uses──► orgs:pack
├── orgs:review  ──uses──► orgs:pack     (rung=lead, then rung=CTO)
├── orgs:integrate
├── orgs:huddle              (on demand, at the reversibility gate)
└── orgs:retro
        every node ──appends──► orgs:ledger
```

## The six experimental varieties as compositions

`spec` is **not** run per variety — the RESP spec is a *fixed shared input*
identical across all six (the identical-target invariant). Each variety starts
from it.

| variety | root skill composes | what it isolates |
|---|---|---|
| **r1** goal → native review | `implement` (whole spec, goal-directed) → `review` (same-provider, fresh) | review at all, same-provider |
| **r2** goal → council | `implement` (whole spec) → `council` | provider-diversity review |
| **r3** orgs-full | `decompose` → `implement`×N ∥ `standup` ∥ `crystal` → `council` → `review`(lead) → `review`(CTO) → `integrate` → `retro` | the whole protocol |
| **r4** − crystal | r3 without `crystal` | crystal's contribution |
| **r5** − crystal − standup | r4 without `standup` (no guard, no bus) | standup's contribution |
| **r6** − crystal − standup − decomp | `implement` (whole spec, single) → `council` → `review`(lead) → `review`(CTO) → `integrate` | the decomposition/firewall hierarchy vs. the review ladder alone |

Each row is a short root-skill file that states *its* protocol in prose:
"here is how you run a sprint: use these skills, in this order, with these
handoffs." No row mentions a skill it doesn't include.

## The isolation model (how varieties can't contaminate each other)

Per variety, one **isolated Claude config** (`CLAUDE_CONFIG_DIR`/fresh HOME —
no shared memory, sessions, or messaging), containing **only that variety's
skills** (physically: the other skills are not installed), one **copy of the
protocol docs it needs**, one **fresh repo/worktree** pinned to the shared
target SHA, and **run-unique agent ids**. Nothing shared ⇒ nothing to police.
The 25 vectors in `CONTAMINATION-VECTORS.md` are the checklist this setup must
satisfy — most become true by construction; the ones that don't are in the
evaluator (below).

Run varieties **sequentially** (shared API/compute would still couple
wall-clock). **Reviews have no timeout.** Standups run on cadence *only* in
varieties that include `standup`, injecting steering through the agents' bus.

## The evaluator (outside every variety — carries the measurement-honesty rules)

Not a skill any agent has. For each variety, identically:
- **Correctness:** the frozen exam (`resp_conformance.sh`) run from a
  *pristine* copy under the nix redis devshell, against the variety's final
  committed server (exported by SHA, never the live tree). Exactly-one result
  line, anchored; the server's own stdout is separated so it can't forge a
  score.
- **Escaped defects:** one byte-identical post-hoc audit council (codex+agy,
  fresh) against every variety's final server.
- **Bugs caught per review step:** read from each variety's `ledger`
  (`review-findings` entries per rung/seat/round) — the primary signal.
- **Tokens / wall-clock:** from the `claude -p` JSON (`modelUsage`, cumulative)
  per skill invocation; ask-agent seats report no usage → flagged *estimated*,
  never mixed into a measured total.

The four rules that survive any design, enforced here: **unparsed ≠ zero; a
missing seat ≠ a clean seat; estimated ≠ measured; the graded cannot write
its grade.**

## Open decisions for the CEO

1. **One root file per variety (recommended) vs. one root + composition
   manifest.** N files duplicate the shared flow but make the ablation honest
   by construction; a manifest is DRY but is toggle logic by another name.
2. **`review` as one skill parameterized by rung** (lead / CTO) vs. two
   skills. I'd keep one — the ladder is the same act at different tiers.
3. **Where the standup observer runs** in the experiment: the evaluator runs
   `standup.sh observe` on cadence from outside and posts to the variety's
   bus (clean, and it's what "steering injected from outside" means), vs. a
   lead-owned heartbeat inside the variety. I lean evaluator-driven.
4. **Granularity check:** is `huddle` a skill the study needs, or does it
   stay in the full protocol only (r3–r5) as an on-demand escalation? I'd
   include it in the orgs varieties and expect it to fire rarely.
5. **Skill packaging target:** Claude Code `skills/` format first (the
   binding we have), with codex/agy bindings as the portability test later.

## What carries over from the orchestrator work

The prompt templates (now the bodies of `implement`/`review`/`council`), the
nix+redis grading path, the manifest schema, the run-unique-id and env-scrub
lessons, and `CONTAMINATION-VECTORS.md`. Discarded: the monolithic toggle
orchestrator and its policing of a shared substrate.
