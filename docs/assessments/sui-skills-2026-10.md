# Sui development agent skills: fleet evidence and adoption assessment

Status: measurement in progress. Assessment window: 2026-09-26 through 2026-10-18. Owner: Sui-skills assessment lead. Decision owners: dotfiles CTO for integration, Ted for third-party vendoring and project adoption.

## Decision to make

Choose which Sui, Move and Walrus agent skills earn a place in fleet or project-specific agent context based on observed work, repeated failures, maintenance cost and bounded offline task outcomes. This assessment does not itself integrate a candidate.

## Scope and evidence rules

Usage evidence comes from read-only Claude transcripts and Codex rollouts on framework0, tower0.local and splinter1.local. Project membership is checked against Move, JavaScript and Rust manifests. A session is the unit for pain prevalence; repeated errors and documentation fetches are also counted within and across sessions. Counts will be broken down by week, project, provider and tier. Log coverage and unknown classifications will be visible rather than imputed. Only anonymized command and error shapes and aggregate counts belong here. No human transcript text, wallet address, key, mnemonic or private token is included.

## 1. Observed usage and pain

Pending the fixture-tested measurement script under `tools/sui-usage/`, manual cross-check and host coverage inventory. The final section will show CLI invocations, Move failure loops and turns, documentation fetches, source searches, RPC/transaction error classes and next actions, version drift and ask-agent topics. Pain will be ranked by sessions affected multiplied by measured turns spent, with the metric's limitations stated beside the ranking.

## 2. Candidate survey and bounded spot-checks

Pending public-source verification. Each candidate record will include source, maintainer, license, update and target versions, coverage, form, load cost, behavior and offline paired task results. Tests will use `sui move build/test` or local sui-devstack only.

## 3. Gap analysis and recommendation

Pending the evidence from sections 1 and 2. The final section will include a candidate-by-pain matrix, adoption route, integration cost, a shortlist of at most five, estimated turns and tokens saved, uncertainties and links to separate open product questions in orgs ditz.

## Reproduction and limitations

The source logs remain on their hosts. The script, fixtures, selection rules and exact commands will be documented under `tools/sui-usage/`. Reproduction requires read access to the same explicitly scoped roots and does not copy source transcripts into this repository.
