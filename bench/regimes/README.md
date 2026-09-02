# Regimes and ablations — one configurable runner

The bench answers "does the protocol earn its cost, and which parts?" by
running the **same target** under different **regimes**, where a regime is a
set of protocol mechanisms turned on or off. "Run the full protocol" and "run
an ablation" are the same code path with a different config — so making the
framework *runnable* (item 2) and *ablatable* (item 3) is one build.

## The toggle surface

Each mechanism is an independent boolean (or small enum) in a regime config
(`regimes/<name>.json`). The runner reads it and includes/omits that mechanism.

| Toggle | on | off | isolates |
|---|---|---|---|
| `decomposition` | CTO/lead cuts contracts + work packages; player-coach tracer | one agent builds the whole target monolithically | the firewall/contract hierarchy |
| `firewall` | workers get lean packs (own scope + published contracts only) | workers get the whole tree | context-assembly isolation |
| `tiering` | junior models (Haiku/Sonnet) implement, senior reviews | one strong model does everything | model-tier economics |
| `review` | one-rung-up lead review to fixpoint | no review | review at all |
| `council` | cross-provider council (codex+agy) to fixpoint on each PR | no council | **provider-diversity review** (the hypothesized keystone) |
| `standup` | workers' tools wrapped in guard.sh; standup convenes on triggers | no forced-observe | situational-awareness |
| `crystal` | speculative merge-check across parallel branches | none | early-conflict detection |
| `parallel` | workers run concurrently in isolated worktrees | sequential | whether parallelism (and thus crystal/standup) is even exercised |

## Named regimes (the study)

- `raw` — everything off: one strong agent, spec + goal. (= the null-check.)
- `native` — `tiering` only: a lead spawns workers, no protocol artifacts.
- `protocol-full` — everything on. (What the pilot *should* have been —
  the pilot was `protocol-full` minus `council` minus `parallel`.)
- Ablations, each = `protocol-full` with ONE toggle off:
  `no-council`, `no-review`, `no-firewall`, `no-standup`, `no-decomposition`,
  `no-tiering`. Each names the mechanism it removes.

## Config shape

```json
{
  "regime": "protocol-full",
  "target": "resp",
  "toggles": {
    "decomposition": true, "firewall": true, "tiering": true,
    "review": true, "council": true, "standup": true,
    "crystal": true, "parallel": true
  },
  "models": { "cto": "sonnet", "lead": "sonnet", "worker": "haiku", "review_tier": "sonnet" },
  "grader": "bench/conformance/resp_conformance.sh",   // real frozen exam (run under nix devshell)
  "budget_tokens": 800000
}
```

## What a run records (the manifest)

Every run writes `runs/<run-id>/manifest.json` (schema:
`bench/harness/manifest.schema.json`): the regime + toggles, model mix, the
grader result (frozen-exam pass count), the **post-hoc cross-provider council
findings** (crash/DoS defects that escaped the run — the real robustness
metric, since graded conformance saturates), and the cost split
(coordination vs. product vs. **lead-design** tokens — the bucket the pilot
found missing). Cost and escaped-defects are the two axes of every comparison.

## Status

Design + config surface (this file) is the first stone. Next: the `run-regime`
orchestrator that reads a config and drives the lead/workers with the selected
toggles, then wiring standup+crystal into the `parallel` path so they fire.
Until the orchestrator exists, regimes are run by hand per the runbook with the
matching toggles (as the null-check and pilot were).
