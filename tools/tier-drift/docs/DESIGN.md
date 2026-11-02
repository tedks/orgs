# tier-drift design

## Purpose

Model capabilities move fast enough that your intuition about which model a
job needs goes stale within months. Work that needed the frontier model in
the spring often fits a mid or cheap tier by the autumn, and habits do not
follow on their own. tier-drift is a **token optimizer** built on your own
usage history. It tells you:

- which models you have been **ignoring** that you could be using, e.g. a
  cheaper tier that shipped weeks ago and never got a turn;
- where you are sending **work to a state-of-the-art model that a mid or cheap
  tier now handles**, even though it could not a few months ago;
- which **same-price upgrades** you have not switched to yet;
- which workloads are shaped so that tier choice dominates cost, e.g. long
  agentic runs that are mostly cached context re-reads.

It reads logs from every machine you use, but it is not fleet telemetry. The
point is keeping up with changing model capabilities, judged against what
you actually ran.

## When it runs

On demand, and the natural trigger is **a new model shipping**: add it to the
catalog, re-run, and read what changed. Later it should run as a feature of
discord-agents and swarm-ide, so that a model release produces a dispatch
report where you already work, without anyone having to remember to run it.

## Architecture

```
 each host                          operator's machine
┌───────────────────┐   ssh    ┌─────────────────────────────────────────┐
│ collector.py      │ ───────▶ │ aggregate  ─▶  insights  ─▶  report     │
│ (stdlib, py3.6+)  │  JSON    │     ▲             ▲                     │
│ reads local logs, │ aggregs  │     │         catalog/models.toml       │
│ emits aggregates  │          │  host docs    (hand-edited, sourced)    │
└───────────────────┘          └─────────────────────────────────────────┘
```

**Collector** (`src/tier_drift/collector.py`, done). One self-contained file,
piped over ssh and run by whatever `python3` the host has. The floor is
Python 3.6, and tests enforce it statically and on a real host. It reads
Claude Code, Codex, Antigravity and Gemini CLI logs and emits aggregates
only: never prompt text, paths or session ids. Its docstring lists each
counting rule with the measurement behind it. The ones that move totals
are fork and resume deduplication (Claude and Codex both copy history into
new files), cumulative Codex token counters with resets, and Gemini CLI's
whole-array snapshots.

Launch channel (direct / automated / unattributed) is decided only on a
**positive signal a tool writes**:

| signal | channel |
|---|---|
| Claude `entrypoint` `cli` / `claude-desktop` | direct |
| Claude `isSidechain`; Codex `source: {"subagent": …}` | automated (the agent's own subagents) |
| a launcher's session registry, e.g. discord-agents' `~/.config/discord-agents/sessions.json` | direct, through that launcher |
| Codex `originator` naming a tool you drive, e.g. swarm-ide's `swarm_ide` | direct, through that tool |
| operator-configured prompt markers (a review tool's seat prompt, an ask-agent staging path) | automated |
| Claude builds with no `entrypoint`: more than one human turn / exactly one | direct / automated, marked *inferred* |

Anything else is **unattributed**. `claude -p` and `codex exec` are used
alike by chat bots, review tools and cron jobs, so they carry no launcher
of their own. Two shortcuts are wrong and must stay out. The cwd names the
project worked on, not the launcher: a bot runs agents in whatever project
you ask about. And a prose search for a tool's name matches every session
whose instructions mention it.

Registries only help from the day a launcher starts keeping one. A launcher
that wants its history attributed should keep an append-only record of the
session ids it starts.

**Catalog** (`catalog/models.toml`, drafted). The one hand-edited input.
Each model has a tier (a price class within its vendor), a status, a price
with a cached-read rate marked `published` or `assumed-0.1x`, and an
optional drop-in successor. Every benchmark score names its **source**,
because one model's SWE-bench Verified score was measured 12 points apart
by two sources. Leave a field out rather than guess: a missing field drops
the model from the insights that need it.

**Aggregate** (`aggregate.py`, drafted). Merges the per-host documents.
It rejects a schema mismatch and a host that appears twice.

**Insights** (`insights.py`, drafted). Rules computed from usage and the
catalog. Nothing is hand-written, so re-running re-derives everything:

| rule | says |
|---|---|
| `unknown-model` | a model you ran is not in the catalog; add it |
| `tier-down` | a cheaper model that matches one you relied on |
| `context-shape` | a cache-heavy workload on an expensive tier, priced on cheaper ones |
| `ignored-cheaper` | a cheaper current model that gets almost none of your turns |
| `drop-in` | a same-price successor you have not finished moving to |
| `tier-mix` | a vendor where your delegated work does not use cheap tiers |

Capability claims carry a confidence tied to provenance. **strong** means
the candidate wins at least one same-source comparison and loses none.
**mixed** means it wins some and loses others, and both are shown, because
one favourable benchmark is not the story. **indicative** means its only
wins come from comparing scores across sources.

Every rule rolls usage up by catalog id first, because one model appears
under several names in the logs.

**Report** (not started). A rendered page, grouped by insight kind, with
per-version usage charts split into direct, automated and unattributed.
It should be generated from data end to end: a first hand-built report
went stale the moment its numbers were corrected.

## Principles

- **Measure before trusting a count.** Every overcount found so far came
  from a source writing the same event more than once. Re-measure after any
  harness upgrade.
- **Prefer a blank to a guess.** Missing prices, dates and launch channels
  are shown as missing.
- **List prices, not bills.** Dollar figures describe the relative weight of
  a dispatch decision. Most usage runs on plans, not metered API calls.
- **Private by construction.** Collected data lives in `out/` (gitignored)
  and is never committed.

## Status and next steps

Tracked in ditz. In order:

1. **Collector:** done, with one test per counting rule, a static and a
   real-host check of the Python 3.6 floor, and a privacy test.
2. **Engine** (catalog, aggregate, insights): drafted. It is checked by a
   golden test that must reproduce independently computed figures on a
   frozen snapshot of real usage (kept outside the repo; see
   `tests/test_golden.py`). Per-rule unit tests are still to come,
   including for the two bugs found by reading real output:
   ignored-cheaper suggesting a superseded model, and tier-down reporting
   one favourable benchmark while hiding same-source losses.
3. **CLI:** `tier-drift collect [hosts…]` (local plus ssh; config passed
   base64-encoded, because ssh joins its arguments into one remote shell
   command) and `tier-drift report`.
4. **Report** rendering, generated from data.
5. **discord-agents and swarm-ide integration**, triggered by a model
   release, plus launch-history records in those launchers.
6. **Catalog refresh assistance:** flag entries older than a vendor's
   newest release, and draft entries for unknown models without inventing
   prices or scores.
