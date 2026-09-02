# Bench — the nontrivial application benchmark

The bench is the eval for the *protocol itself*. It builds bounded,
externally-gradable programs under different management regimes and measures
whether the org protocol earns its overhead. It is on-brand: an
engineering-research project should measure its own claims rather than assert
them.

## What it answers

1. Does the org protocol produce more conformant, less defective software
   than a single strong agent, or than native harness orchestration without
   the protocol — at what cost in tokens, wall-clock, and human intervention?
2. Which parts of the protocol carry their weight? (ablations)
3. Does the protocol survive injected adversity — an underspecified contract,
   a semantically incompatible clean merge, a late amendment, an attractive
   unnecessary abstraction, a planted rabbit hole, a harness restart?

## Regimes (the independent variable)

| Regime | Description |
|---|---|
| `raw` | one strong agent, raw prompting, no protocol |
| `native` | native harness orchestration (goal/loop, subagents), no org protocol |
| `protocol` | the full org protocol (doctrine + states + runbook + bindings) |

## Sequencing (council ruling, do not collapse)

- **v0.9 — organic shakedown.** One `protocol` run of the RESP target, **no
  injected events**, per-work-package token budgets and timeouts. Purpose:
  find and fix the protocol's own organic failure modes before comparison.
  Injected chaos here would mask systemic defects.
- **v1 — the study.** Codex's nine-run design:
  - 3 smoke runs, one per regime, no events;
  - 3 paired scenarios (`native` vs `protocol`), one injected event each:
    underspecified contract · semantically incompatible clean merge ·
    planted rabbit hole + attractive abstraction.
  Plus the malformed-wire corpus and immutable run manifests (below).
- **Ablations — deferred** until `protocol` completes reliably: drop one of
  firewall / standup / senior review / memory per run and measure the delta.
  This is how the firewall-hardness question gets answered empirically
  (DOCTRINE / founding council).

## Targets

Bounded, RFC- or client-gradable, with real internal boundaries. The org
does **not** write its own exam — grading is external.

- `resp/` — Redis-compatible RESP2 subset (first target; spec in
  `docs/specs/2026-09-02-resp-tracer.md`). Graded by a real `redis-cli`.
- Future: DNS resolver, HTTP/1.1 server, BitTorrent client (each with an
  external conformance suite; seeded variations + hidden requirements so
  success can't come from reproducing a memorized implementation).

## Measurement (why the manifest is immutable)

"The protocol won" must not secretly mean "the protocol got more inference
and more human attention." Every run writes a manifest
(`harness/manifest.schema.json`) recording, at minimum: model versions and
mix, prompts/revisions, injected event + timing, token and model-call
counts, human-intervention minutes, lead wait time, conformance pass rate,
escaped defects (found after the run by the external suite), fix-introduced
regressions, wall-clock, and recovery time after a restart. Manifests are
append-only artifacts under `runs/`.

## Layout

```
bench/
  README.md                     — this file
  harness/
    run-bench.sh                — orchestrates one run; writes a manifest
    manifest.schema.json        — the immutable run-manifest schema
    record.sh                   — manifest helper (append-only field writes)
  conformance/
    resp_conformance.sh         — the frozen RESP exam (real redis-cli)
  malformed-corpus/
    README.md                   — malformed-wire inputs + expected handling
  targets/
    resp/README.md              — pointer to the spec; where the built server lands
  runs/                         — one dir per run; manifests + logs (gitkept)
```

## v0 scope

Scaffold only: the runner, the manifest schema and recorder, the conformance
harness skeleton, and the corpus/target placeholders. The RESP server itself
is the **pilot sprint's** product (built by the org under the protocol), not
part of this scaffold. Running v0.9 waits on that server existing.
