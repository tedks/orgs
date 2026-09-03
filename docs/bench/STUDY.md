# RESP ablation study — overnight autonomous run (2026-09-03)

CEO directive: run a focused ablation study of the org protocol on the RESP
target, fully isolated per regime, no human in the loop. This file is the
durable plan and the results log; it must let any fresh agent pick the study
up mid-flight.

## The six regimes (fresh, isolated, non-contaminating)

Each runs in its own git worktree+branch off `master`, in a **fresh headless
`claude -p` process** — no shared context, no shared working tree. Run
**sequentially, not in parallel** (parallel runs contend for API/compute and
would corrupt the wall-clock measurement; fairness requires one at a time).

| id | regime | mechanisms on |
|---|---|---|
| r1 | goal → native review | one agent implements the whole spec; then a fresh same-provider reviewer |
| r2 | goal → council | one agent implements; then cross-provider council to fixpoint |
| r3 | orgs-full | decomposition + parallel workers + standup → council → lead → CTO review, with crystal speculative-merging |
| r4 | orgs, − crystal | r3 minus crystal |
| r5 | orgs, − crystal − standup | r4 minus standup |
| r6 | orgs, − crystal − standup − decomp | one implementer + council + lead/CTO review (no decomposition/firewall/workers) |

Configs: `bench/regimes/configs/r{1..6}-*.json`.

## What is measured (per regime, into `runs/<id>/manifest.json` + `SUMMARY.md`)

- **Tokens**, split by phase: build, each review step, the audit. From the
  `claude -p --output-format json` usage fields; ask-agent (codex/agy) token
  reporting is rougher and marked as such.
- **Wall-clock**, by phase (measured by the orchestrator, not self-reported).
- **Bugs caught by review steps** — total AND broken down by step (native /
  council-per-seat / lead / CTO), per round. This is the primary signal: does
  each review layer earn its place?
- **Correctness** — the REAL frozen exam (`resp_conformance.sh`) under the nix
  redis devshell (`nix develop bench`); pass/fail counts. Plus **escaped
  defects**: one identical post-hoc audit council (codex+agy, fresh) against
  every regime's FINAL server — the robustness metric, run identically so it's
  comparable across regimes.

## Fairness invariants (violating any corrupts the study)

1. Each regime: fresh process, fresh worktree, no inherited context.
2. Identical target, identical frozen exam, identical audit council.
3. Sequential execution (no parallel API/compute contention).
4. The orchestrator itself is council-reviewed to fixpoint + fork-reviewed by
   the CTO before ANY regime runs — a bug in it silently biases everything.

## Execution sequence (the autonomous chain)

1. **Orchestrator built** (subagent, Opus) → council-review to fixpoint → done.
2. **CTO review**: fork-self to review `run_regime.py`; confirm the council
   happened; `--dry-run` one orgs + one raw config to sanity-check prompt
   composition and isolation. Gate: do not proceed until clean.
3. **Launch the driver** (`bench/harness/run_study.sh`, backgrounded): runs
   r1..r6 sequentially through `run_regime.py`, logging to `runs/`. One
   background job (robust to notification drops) — its completion re-invokes
   the CTO.
4. **Collect + document**: aggregate the six manifests into a results table in
   this file (below), commit, push, open/annotate a PR. Report to the CEO.

## Status log

- 2026-09-03: study launched. Orchestrator build in progress (subagent
  `orchestrator-builder`, Opus, council-to-fixpoint required). Six configs
  committed. Driver + results pending orchestrator validation.

## Results

_(populated after the runs complete — table of tokens / wall-clock /
bugs-per-review-step / frozen-exam pass / escaped-defects, per regime, with
the analysis: does the council carry robustness? does decomposition/standup/
crystal earn its cost?)_
