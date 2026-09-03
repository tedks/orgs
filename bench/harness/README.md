# bench/harness — the regime orchestrator

`run_regime.py` takes one regime config and runs one complete, isolated
benchmark run end to end with no human in the loop, producing a manifest.
Python 3 standard library only.

```bash
# validate a config and see exactly what would happen — launches nothing
python3 bench/harness/run_regime.py --config bench/regimes/configs/r3-orgs-full.json --dry-run

# print one composed prompt in full
python3 bench/harness/run_regime.py --config .../r1-goal-native-review.json \
        --dry-run --print-prompt build

# run it for real
python3 bench/harness/run_regime.py --config bench/regimes/configs/r3-orgs-full.json

# the tests: no agents, no worktrees, no tokens
python3 bench/harness/test_run_regime.py
python3 bench/harness/test_run_regime.py --mutation
```

Exit status: `0` clean, `1` the run finished but recorded failures (read
`manifest.json` → `failures`), `2` the config or environment is unusable and
nothing was spent, `3` the manifest could not be written.

## What one run does

1. **Isolate.** A fresh branch `bench-run/<regime>-<utc-ts>` off `master`, in
   its own worktree at `<runs-root>/<run-id>/tree`. Workers get sub-worktrees
   under `<run-id>/workers/<id>` — never a shared tree; the pilot corrupted
   its index that way. Nothing outside the run directory is written.
2. **Compose** the build prompt from the toggles (see below).
3. **Build**: one headless `claude -p`, fresh process, prompt on stdin, cwd =
   the run tree, with the config's timeout. The standup and crystal loops run
   alongside it when their toggles are on.
4. **Grade** with the frozen exam under nix (`tag=after_build`).
5. **Review** — each enabled step separately, each round recorded, with a fix
   round between rounds and an early stop at fixpoint.
6. **Grade again** (`tag=final`). The difference from step 4 is
   `fix_introduced_regressions`.
7. **Audit** for escaped defects: codex + agy against the final server.
8. **Write** `manifest.json` (validated against `manifest.schema.json`),
   `SUMMARY.md`, and a copy of the config.

The run directory is complete even when the run fails — the manifest is
written from a `finally` block, and every failure is recorded with its phase.

## Config

Two review vocabularies are accepted, because two are in use:

| shape | review toggles | used by |
|---|---|---|
| regimes-README | `review` (the internal ladder: native + one-rung-up lead) | `raw`, `protocol-full`, `no-*` |
| study | `review_native`, `review_lead`, `review_cto` | `r1`–`r6` |

A config carrying both is an error, as is a missing toggle, a misspelled one,
or an unknown top-level key. Silently ignoring a setting that was meant to
change the run is how a study arm ends up measuring something nobody intended.

Timing keys, either spelling: `timeout_minutes` (the build budget) or
`timeouts.build_s`; `standup_interval_min` or `standup.interval_s`;
`crystal_interval_min` or `crystal.interval_s`; `max_review_rounds` or
`max_rounds.<step>`.

Model roles: `implementer` is the solo builder, `worker` is the tier a lead
delegates *down* to. They are distinct — a goal-directed arm builds at
implementer tier, and conflating them would quietly run the baseline on a
cheaper model. With `tiering: false` every role collapses onto one model.

`doctrine` (bool) overrides whether the build agent carries the DOCTRINE.md
prompt block. The default is derived: a run with no decomposition *and* no
one-rung-up review is goal-directed and gets none, which is what separates
the study's `goal-*` control arms from its `orgs-*` arms.

## Toggles → prompt

`--dry-run` prints a conformance table that checks each mechanism's marker in
**both** directions — present when the mechanism is on, absent when it is off.
Only the pair is an assertion: "absent when off" alone is satisfied by a
template that never mentions the mechanism at all.

| mechanism | marker in the build prompt |
|---|---|
| doctrine | `schwerpunkt` |
| standup | `guard.sh` |
| crystal | `crystal-check.sh` |
| decomposition | `git worktree add -b` |
| firewall | `lean context pack` (vs. `whole tree` when off) |

Note what is *not* a marker: `work package` appears in the doctrine block and
in the shared spec, so it reads as present in regimes that have no
decomposition whatsoever.

### The shared inputs are not edited per arm

Every arm reads the same spec and the same runbook — that is what makes the
target identical and the comparison fair. It also means an arm can read about
a mechanism it does not have. Editing those documents per arm would trade this
confound for a worse one, so instead:

- the lead's prompt states precedence outright: the toggle table outranks the
  runbook, skip the steps belonging to an OFF mechanism;
- `--dry-run` prints a **SHARED-INPUT NOTE** listing protocol vocabulary the
  spec uses for mechanisms this arm has off, so the operator can judge it
  before spending anything.

## Measurement

`manifest.json` follows `manifest.schema.json` (validated before writing).
Beyond the frozen fields:

- **`review_steps`** — bugs caught by step, by round. A round whose findings
  block did not parse counts toward `rounds_unparsed` and toward *no* severity
  count. "Could not parse" is never recorded as "zero findings".
- **`escaped_defects`** — the robustness yardstick: a cross-provider audit of
  the final server, from a prompt that is **regime-independent by contract**
  so the arms are comparable. `null`, not zero, when no seat returned a
  parsable block. Counts are the sum across seats; no semantic dedup is
  attempted, so two seats reporting one defect count twice.
- **`tokens_by_phase`** — each entry carries `source` and an `estimated` flag.
  A `claude -p` phase is measured from the result event's `modelUsage`
  (the session aggregate — the top-level `usage` is the last turn only, and
  summing it would understate a long build by orders of magnitude). A foreign
  ask-agent seat reports no usage at all and is estimated at characters/4.
  **Never compare an estimated figure with a measured one without saying so.**
- **`regime`** stays the frozen three-value class, derived from the toggles;
  the config's own label is `regime_name` and `toggles` is the authoritative
  record.

Cost buckets follow RUNBOOK §8: coordination = the review seats, product =
the build plus fix rounds. The escaped-defect audit is in neither — it is the
measuring instrument, not work the org did.

### Grading integrity

The exam that grades a run is the **pristine copy in this worktree**, never
the run tree's — the org does not grade itself. The two are hashed against
each other and a difference is recorded as `harness.exam_tampered`, which is
evidence about the run, not a reason to stop it.

## Running the six-regime study

Sequentially, one at a time — parallel runs contend for API and compute and
would corrupt the wall-clock measurement:

```bash
for cfg in bench/regimes/configs/r[1-6]-*.json; do
    python3 bench/harness/run_regime.py --config "$cfg" || true   # a failed arm is data
done
```

Each arm leaves its worktree and branch behind on purpose; they are the
evidence. Each `SUMMARY.md` ends with the two commands that remove them.
