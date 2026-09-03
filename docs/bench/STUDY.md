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

- 2026-09-03: study launched. Orchestrator built (Opus subagent): 2817-line
  `run_regime.py`, 15 prompt templates, 585 tests passing; builder self-found
  and fixed 3 runtime bugs (unpinned STANDUP_BUS, fix-round mis-billing,
  counter race). Dry-runs of r1/r3/r6/raw compose correctly.
- 2026-09-03 **CTO gate — NO-GO (held launch).** Two reviews:
  - **Fork-review** (a Claude fork of the CTO): code clean on adversarial
    read, but returned NO-GO on principle — *a Claude fork reviewing
    Claude-built code is the correlated-blind-spot case this study exists to
    measure*; its GO is necessary, not sufficient.
  - **Cross-provider council** (codex + agy): **~10 Critical study-invalidating
    findings the fork found zero of.** Verified real against the code:
    ablations don't ablate the *instructions* (the lead gets the full runbook
    regardless of toggles, so r4/r5 still tell it to use crystal/standup);
    `git log --all` on reused worker-ids bleeds progress signal across runs;
    the full parent env (session ids, messaging sockets) leaks into the
    "fresh" agents; grading reads the live tree not the committed SHA and the
    conformance regex is unanchored (fakeable); a failed/missing review seat
    is silently counted as zero; crystal conflicts are never delivered to the
    org (inert). **This is the study's thesis — cross-provider review catches
    what same-provider review structurally cannot — demonstrated on the
    study's own harness before a single arm ran.** It is the strongest single
    result so far, and it is why the launch was held rather than producing
    ~5M tokens of contaminated garbage.
  - Builder dispatched to fix all Critical/Important to fixpoint and
    **re-council both providers to CLEAN** before any arm runs. Launch resumes
    only after a re-verified CLEAN.

## Results

_(populated after the runs complete — table of tokens / wall-clock /
bugs-per-review-step / frozen-exam pass / escaped-defects, per regime, with
the analysis: does the council carry robustness? does decomposition/standup/
crystal earn its cost?)_
