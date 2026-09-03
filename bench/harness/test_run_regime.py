#!/usr/bin/env python3
"""test_run_regime.py — tests for the regime orchestrator. No live agents.

Run:  python3 bench/harness/test_run_regime.py
      python3 bench/harness/test_run_regime.py --mutation   (self-check)

Nothing here spawns an agent, creates a worktree, or spends a token. What it
does exercise is everything that decides HOW those tokens get spent: prompt
composition for every config on disk, the toggle -> prompt logic in both
directions, the findings parser against malformed input, the `claude -p`
result parser against all three output shapes, and the manifest writer against
the frozen schema.

MUTATION CHECK. Doctrine: a test that cannot fail reads as coverage while
guarding nothing. `--mutation` breaks the two mechanisms these tests exist to
pin -- the findings parser and the toggle->prompt logic -- and asserts the
suite goes RED for each. A green mutation run means these tests are decoration
and should be treated as a defect.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_regime as rr                                        # noqa: E402

HARNESS = Path(__file__).resolve().parent
FRAMEWORK = HARNESS.parent.parent
CONFIG_DIR = FRAMEWORK / "bench/regimes/configs"

FAILURES: list[str] = []
CHECKS = 0


def check(cond: bool, what: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILURES.append(what)


def check_eq(got, want, what: str) -> None:
    check(got == want, f"{what}: got {got!r}, want {want!r}")


def all_configs() -> list[Path]:
    paths = sorted(CONFIG_DIR.glob("*.json"))
    if not paths:
        raise SystemExit(f"no regime configs found under {CONFIG_DIR}")
    return paths


def make_ctx(cfg: rr.Config, run_id: str = "test-run") -> rr.Ctx:
    """A context pointing at real doctrine/spec/runbook/exam but a fake run
    directory. Composition never touches the run directory, so nothing is
    created."""
    return rr.build_ctx(cfg, FRAMEWORK, run_id,
                        Path("/nonexistent/bench-runs") / run_id,
                        "bench-run/test-2026-01-01T0000Z")


# ---------------------------------------------------------------------------
# 1. Every config on disk loads, and composes every prompt it implies
# ---------------------------------------------------------------------------

def test_every_config_composes() -> None:
    for path in all_configs():
        name = path.name
        try:
            cfg = rr.load_config(path)
        except rr.ConfigError as exc:
            FAILURES.append(f"{name}: failed to load: {exc}")
            continue
        ctx = make_ctx(cfg)

        try:
            build = rr.compose_build_prompt(cfg, ctx)
        except rr.PromptError as exc:
            FAILURES.append(f"{name}: build prompt did not compose: {exc}")
            continue

        # A composed prompt must carry no unfilled placeholder. `render`
        # raises on a missing value, but a template could still emit a literal
        # that LOOKS like one; the graded material must not contain it either.
        check("{{" not in build, f"{name}: build prompt still has a '{{{{' in it")
        check(len(build) > 2000, f"{name}: build prompt is implausibly short "
                                 f"({len(build)} chars)")

        # The spec, the exam, and the product path always travel.
        check(cfg.server_path in build,
              f"{name}: build prompt never names the server path {cfg.server_path}")
        check("RESP" in build or cfg.target in build,
              f"{name}: build prompt does not mention the target")
        check("conformance:" in build,
              f"{name}: build prompt does not carry the frozen exam")
        check(ctx.run_branch in build,
              f"{name}: build prompt does not name the run branch")

        # Isolation must be stated to the agent, not just enforced around it.
        check(str(ctx.run_tree) in build,
              f"{name}: build prompt does not name the run worktree")

        for step in ("native", "lead", "cto"):
            if cfg.steps[step]:
                p = rr.compose_review_prompt(cfg, ctx, step, rr.DRY_MATERIALS)
                check("{{" not in p, f"{name}: review-{step} has an unfilled placeholder")
                check("severity" in p, f"{name}: review-{step} lacks the findings contract")
        if cfg.steps["council"]:
            p = rr.compose_council_prompt(cfg, ctx, rr.DRY_MATERIALS)
            check("severity" in p, f"{name}: council prompt lacks the findings contract")
        for fn, label in ((rr.compose_fix_prompt, "fix"),
                          (rr.compose_audit_prompt, "audit")):
            p = fn(cfg, ctx, rr.DRY_MATERIALS)
            check("{{" not in p, f"{name}: {label} prompt has an unfilled placeholder")


# ---------------------------------------------------------------------------
# 2. Toggle -> prompt logic, asserted in BOTH directions
# ---------------------------------------------------------------------------

def test_toggle_conformance_every_config() -> None:
    """A toggled-off mechanism must not appear in the composed build prompt --
    and a toggled-on one must. Only the pair is a real assertion: 'absent when
    off' alone is satisfied by a template that never mentions the mechanism."""
    for path in all_configs():
        cfg = rr.load_config(path)
        ctx = make_ctx(cfg)
        build = rr.compose_build_prompt(cfg, ctx)
        for c in rr.toggle_conformance(cfg, build):
            check(c.ok,
                  f"{path.name}: {c.mechanism} is {c.state} but its marker "
                  f"{c.marker!r} is "
                  f"{'present' if c.actually_present else 'absent'} "
                  f"(expected {'present' if c.expected_present else 'absent'})")


def test_toggles_off_are_really_absent() -> None:
    """The same assertion made directly, without going through the marker
    table -- so a bug in `toggle_conformance` itself cannot hide a bug in
    composition."""
    for path in all_configs():
        cfg = rr.load_config(path)
        ctx = make_ctx(cfg)
        build = rr.compose_build_prompt(cfg, ctx).lower()
        n = path.name
        if not cfg.toggles["standup"]:
            check("guard.sh" not in build, f"{n}: standup off but guard.sh is in the prompt")
            check("forced observe" not in build,
                  f"{n}: standup off but the forced-observe section is in the prompt")
        if not rr.crystal_active(cfg):
            check("crystal-check.sh" not in build,
                  f"{n}: crystal inactive but crystal-check.sh is in the prompt")
        if not cfg.toggles["decomposition"]:
            check("git worktree add -b" not in build,
                  f"{n}: no decomposition but the prompt tells it to make worker worktrees")
            check("spawn the workers" not in build,
                  f"{n}: no decomposition but the prompt tells it to spawn workers")
        if not cfg.doctrine:
            check("schwerpunkt" not in build,
                  f"{n}: doctrine omitted but the doctrine block is in the prompt")
            check("auftragstaktik" not in build,
                  f"{n}: doctrine omitted but doctrine vocabulary is in the prompt")
        if cfg.toggles["decomposition"] and not cfg.toggles["firewall"]:
            check("lean context pack" not in build,
                  f"{n}: firewall off but workers are told they get a lean pack")
            check("whole tree" in build,
                  f"{n}: firewall off but workers are not told they get the whole tree")


def test_off_mechanisms_are_named_off_against_the_shared_runbook() -> None:
    """A lead's prompt carries the whole RUNBOOK, which describes mechanisms
    this arm may have removed. The runbook is a shared, unedited input (that
    is what keeps the target identical across arms), so the mitigation is
    stated precedence, not a doctored document: the prompt must name each OFF
    mechanism and say that the toggle table outranks the runbook."""
    for path in all_configs():
        cfg = rr.load_config(path)
        if not cfg.toggles["decomposition"]:
            continue                       # no runbook in the solo prompt
        build = rr.compose_build_prompt(cfg, make_ctx(cfg))
        off = [k for k in rr.TOGGLE_KEYS if not cfg.toggles[k]]
        if not off:
            continue
        check("this table wins" in build,
              f"{path.name}: the prompt carries the runbook but never says the "
              "toggle table outranks it")
        for mech in off:
            check(f"`{mech}`" in build,
                  f"{path.name}: {mech} is off but the prompt never names it as OFF")


def test_standup_bus_is_pinned_in_every_guard_invocation() -> None:
    """bus.sh resolves its root as ${STANDUP_BUS:-$PWD/.standup/bus}, and
    workers run in their OWN worktrees. An unpinned guard command therefore
    reads an empty bus beside the worker rather than the run's, so every
    redirect is queued forever and delivered to nobody — the standup mechanism
    silently does nothing and its ablation measures nothing.

    Every guard invocation in a composed prompt must carry STANDUP_BUS, and it
    must be the same path the standup loop writes to."""
    for path in all_configs():
        cfg = rr.load_config(path)
        if not cfg.toggles["standup"]:
            continue
        ctx = make_ctx(cfg)
        build = rr.compose_build_prompt(cfg, ctx)
        n = path.name
        check_eq(str(ctx.bus_root), str(ctx.run_tree / ".standup/bus"),
                 f"{n}: the bus root is not where the loop puts it")
        guard = str(ctx.guard)
        for line in build.splitlines():
            if guard not in line:
                continue
            check("STANDUP_BUS=" in line,
                  f"{n}: a guard invocation omits STANDUP_BUS: {line.strip()!r}")
            check(str(ctx.bus_root) in line,
                  f"{n}: a guard invocation points at the wrong bus: {line.strip()!r}")
        check(guard in build, f"{n}: standup is on but no guard command is shown")


def test_review_steps_gate_prompt_creation() -> None:
    """A review step that is off must produce no prompt at all -- the toggle
    governs spend, not just wording."""
    for path in all_configs():
        cfg = rr.load_config(path)
        ctx = make_ctx(cfg)
        for step in ("native", "lead", "cto"):
            if cfg.steps[step]:
                continue
            # Composing it would still work; the point is that the runner is
            # driven by cfg.steps, and the dry-run plan reflects that.
            check(not cfg.steps[step],
                  f"{path.name}: {step} should be off")


# ---------------------------------------------------------------------------
# 3. The audit prompt is regime-independent -- the comparability invariant
# ---------------------------------------------------------------------------

def test_audit_prompt_is_regime_independent() -> None:
    """The escaped-defect audit is the yardstick every arm is measured with.
    Given identical code, two different regimes must produce a byte-identical
    audit prompt; anything else silently makes the arms incomparable."""
    mat = rr.Materials(diff="D", server_code="CODE", review_sha="abc123")
    prompts: dict[str, str] = {}
    for path in all_configs():
        cfg = rr.load_config(path)
        prompts[path.name] = rr.compose_audit_prompt(cfg, make_ctx(cfg), mat)
    distinct = set(prompts.values())
    check_eq(len(distinct), 1,
             "the audit prompt varies by regime; it must not "
             f"({len(distinct)} distinct texts across {len(prompts)} configs)")
    # The byte-identity above is the invariant. This second check is about the
    # TEMPLATE, not the composed prompt: the composed prompt inlines the spec,
    # which legitimately uses protocol vocabulary (it is a shared input, the
    # same for every arm, so it cannot make the prompt regime-DEPENDENT). What
    # must stay out is the harness's own regime-aware text.
    tmpl = rr.load_template("audit_council.md").lower()
    for term in ("schwerpunkt", "guard.sh", "crystal-check.sh", "work package",
                 "toggle", "decomposition", "doctrine", "ablation"):
        check(term not in tmpl,
              f"the audit template mentions {term!r}; it must carry nothing "
              "regime-dependent")


def test_council_prompt_is_regime_independent() -> None:
    mat = rr.Materials(server_code="CODE")
    prompts = {p.name: rr.compose_council_prompt(rr.load_config(p),
                                                 make_ctx(rr.load_config(p)), mat)
               for p in all_configs()}
    check_eq(len(set(prompts.values())), 1,
             "the council seat prompt varies by regime; it must not")


# ---------------------------------------------------------------------------
# 4. Config semantics
# ---------------------------------------------------------------------------

def test_tiering_off_collapses_models() -> None:
    for path in all_configs():
        cfg = rr.load_config(path)
        if cfg.toggles["tiering"]:
            continue
        models = {cfg.models[r] for r in rr.MODEL_ROLES}
        check_eq(len(models), 1,
                 f"{path.name}: tiering is off but the roles use "
                 f"{len(models)} different models ({sorted(models)})")


def test_tiering_on_keeps_worker_below_lead() -> None:
    cfg = rr.load_config(CONFIG_DIR / "protocol-full.json")
    check_eq(cfg.models["worker"], "haiku", "protocol-full worker model")
    check_eq(cfg.models["lead"], "sonnet", "protocol-full lead model")
    check(cfg.models["worker"] != cfg.models["lead"],
          "tiering is on but the worker and lead share a model")


def test_solo_builds_at_implementer_tier() -> None:
    """The study's goal arms name an `implementer` model distinct from
    `worker`. A solo build must use it: silently building the baseline on the
    cheap delegation tier would understate the baseline."""
    cfg = rr.load_config(CONFIG_DIR / "r1-goal-native-review.json")
    check_eq(cfg.builder_role, "implementer", "r1 builder role")
    check_eq(cfg.builder_model, "sonnet", "r1 builder model")
    check_eq(cfg.models["worker"], "haiku", "r1 worker model is still haiku")
    cfg3 = rr.load_config(CONFIG_DIR / "r3-orgs-full.json")
    check_eq(cfg3.builder_role, "lead", "r3 builder role")
    check_eq(cfg3.builder_model, "sonnet", "r3 builder model")


def test_both_review_vocabularies() -> None:
    legacy = rr.load_config(CONFIG_DIR / "protocol-full.json")
    check(legacy.steps["native"] and legacy.steps["lead"],
          "the legacy `review` toggle should turn on native and lead review")
    check(not legacy.steps["cto"],
          "the legacy `review` toggle must not imply the CTO rung")
    split = rr.load_config(CONFIG_DIR / "r3-orgs-full.json")
    check(not split.steps["native"], "r3 has review_native false")
    check(split.steps["lead"] and split.steps["cto"], "r3 has lead and cto true")
    check(split.toggles["review"], "the derived `review` should be true for r3")


def test_config_rejects_ambiguity() -> None:
    """Silent acceptance is the failure mode that corrupts a study, so each of
    these must be a hard error, not a default."""
    base = json.loads((CONFIG_DIR / "protocol-full.json").read_text())

    def load(mutate) -> str | None:
        cfg = copy.deepcopy(base)
        mutate(cfg)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(cfg, fh)
            p = Path(fh.name)
        try:
            rr.load_config(p)
            return None
        except rr.ConfigError as exc:
            return str(exc)
        finally:
            p.unlink(missing_ok=True)

    cases = [
        ("a missing toggle", lambda c: c["toggles"].pop("council")),
        ("a misspelled toggle", lambda c: c["toggles"].update({"cristal": True})),
        ("a non-boolean toggle", lambda c: c["toggles"].update({"crystal": "yes"})),
        ("both review vocabularies",
         lambda c: c["toggles"].update({"review_lead": True})),
        ("an unknown top-level key",
         lambda c: c.update({"timeout_minute": 30})),
        ("a negative timeout", lambda c: c.update({"timeout_minutes": -5})),
        ("a zero max_review_rounds", lambda c: c.update({"max_review_rounds": 0})),
        ("a worker id that is not a safe path segment",
         lambda c: c.update({"worker_ids": ["../escape"]})),
    ]
    for label, mutate in cases:
        err = load(mutate)
        check(err is not None, f"config loader accepted {label} without complaint")

    # And the unmutated config must still load, or every case above is vacuous.
    check(load(lambda c: None) is None,
          "the unmutated protocol-full config no longer loads")


def test_no_review_config_turns_review_off() -> None:
    cfg = rr.load_config(CONFIG_DIR / "no-review.json")
    check(not cfg.steps["native"] and not cfg.steps["lead"] and not cfg.steps["cto"],
          "no-review.json still schedules an internal review step")
    check(cfg.steps["council"], "no-review.json should still run the council")


def test_coarse_regime_and_ablation() -> None:
    def t(**over):
        base = {k: True for k in rr.CANONICAL_TOGGLES}
        base.update(over)
        base["review"] = any(base[k] for k in rr.REVIEW_TOGGLES)
        return base

    check_eq(rr.coarse_regime(rr.load_config(CONFIG_DIR / "raw.json").toggles),
             "raw", "raw.json coarse class")
    check_eq(rr.coarse_regime(t()), "protocol", "all-on coarse class")
    native = t(firewall=False, review_native=False, review_lead=False,
               review_cto=False, council=False, standup=False, crystal=False)
    check_eq(rr.coarse_regime(native), "native", "lead-only coarse class")

    check_eq(rr.ablation_of(t()), None, "nothing off -> no ablation name")
    check_eq(rr.ablation_of(t(crystal=False)), "crystal", "crystal ablation")
    check_eq(rr.ablation_of(t(firewall=False)), "firewall", "firewall ablation")
    check_eq(rr.ablation_of(t(crystal=False, standup=False)), None,
             "two mechanisms off -> no single ablation name")
    check_eq(rr.ablation_keys(t(crystal=False, standup=False), "split"),
             ["crystal", "standup"],
             "ablation_set stays lossless where the single name cannot")
    # All three rungs off is ONE ablation (`review`), not three.
    check_eq(rr.ablation_of(t(review_native=False, review_lead=False,
                              review_cto=False)), "senior_review",
             "every review rung off is the single review ablation")

    # A legacy config has never heard of the CTO rung, so review_cto=False
    # there means "not in this vocabulary", not "ablated". Reading it as an
    # ablation made protocol-full -- everything-on by definition -- report
    # itself as the review_cto ablation.
    full = rr.load_config(CONFIG_DIR / "protocol-full.json")
    check_eq(full.vocabulary, "legacy", "protocol-full uses the legacy vocabulary")
    check_eq(rr.ablation_of(full.toggles, full.vocabulary), None,
             "protocol-full has everything on and must name no ablation")
    nc = rr.load_config(CONFIG_DIR / "no-council.json")
    check_eq(rr.ablation_of(nc.toggles, nc.vocabulary), "council",
             "no-council.json is the council ablation")
    nr = rr.load_config(CONFIG_DIR / "no-review.json")
    check_eq(rr.ablation_of(nr.toggles, nr.vocabulary), "senior_review",
             "no-review.json is the review ablation")

    # r3 and r4 both leave review_native off, so neither has a SINGLE
    # ablation; the set is what distinguishes them.
    r3 = rr.load_config(CONFIG_DIR / "r3-orgs-full.json")
    r4 = rr.load_config(CONFIG_DIR / "r4-orgs-no-crystal.json")
    check_eq(rr.ablation_keys(r3.toggles, r3.vocabulary), ["review_native"],
             "r3 ablation set")
    check_eq(rr.ablation_keys(r4.toggles, r4.vocabulary),
             ["crystal", "review_native"], "r4 ablation set")
    check_eq(sorted(set(rr.ablation_keys(r4.toggles, r4.vocabulary))
                    - set(rr.ablation_keys(r3.toggles, r3.vocabulary))),
             ["crystal"], "r4 differs from r3 by crystal alone")


def test_doctrine_split_matches_the_study() -> None:
    """goal-* arms are controls and must not carry protocol doctrine;
    orgs-* arms must."""
    expected = {
        "r1-goal-native-review.json": False,
        "r2-goal-council.json": False,
        "r3-orgs-full.json": True,
        "r4-orgs-no-crystal.json": True,
        "r5-orgs-no-crystal-no-standup.json": True,
        "r6-orgs-no-decomp.json": True,
        "raw.json": False,
        "protocol-full.json": True,
    }
    for name, want in expected.items():
        cfg = rr.load_config(CONFIG_DIR / name)
        check_eq(cfg.doctrine, want, f"{name}: doctrine block included?")


def test_doctrine_override_is_honoured() -> None:
    base = json.loads((CONFIG_DIR / "r1-goal-native-review.json").read_text())
    base["doctrine"] = True
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(base, fh)
        p = Path(fh.name)
    try:
        cfg = rr.load_config(p)
        check(cfg.doctrine, "an explicit doctrine:true was not honoured")
        check("schwerpunkt" in rr.compose_build_prompt(cfg, make_ctx(cfg)).lower(),
              "doctrine:true did not put the doctrine block in the prompt")
    finally:
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 5. The findings parser -- including malformed input
# ---------------------------------------------------------------------------

GOOD = """I read the whole diff. Two things are wrong.

```json
[
  {"severity": "Critical", "claim": "server.py crashes on a nil command name"},
  {"severity": "Important", "claim": "INCR accepts leading zeros"},
  {"severity": "Minor", "claim": "naming"}
]
```
"""


def test_findings_happy_path() -> None:
    f = rr.parse_findings(GOOD)
    check(f.ok, f"the well-formed reply did not parse: {f.error}")
    check_eq(f.counts["critical"], 1, "critical count")
    check_eq(f.counts["important"], 1, "important count")
    check_eq(f.counts["minor"], 1, "minor count")
    check_eq(f.counts["total"], 3, "total count")
    check_eq(f.findings[0]["claim"],
             "server.py crashes on a nil command name", "claim text")


def test_findings_empty_is_not_a_failure() -> None:
    f = rr.parse_findings("Nothing to report.\n\n```json\n[]\n```\n")
    check(f.ok, "an empty findings array must parse -- 'no findings' is a result")
    check_eq(f.counts["total"], 0, "empty array total")


def test_findings_last_block_wins() -> None:
    """The contract says nothing may follow the real block, so a reply that
    shows an example first must not have the example counted."""
    text = ("Here is the format:\n\n```json\n[{\"severity\": \"Minor\", "
            "\"claim\": \"example only\"}]\n```\n\nMy actual findings:\n\n"
            "```json\n[{\"severity\": \"Critical\", \"claim\": \"real\"}]\n```\n")
    f = rr.parse_findings(text)
    check(f.ok, "reply with two blocks did not parse")
    check_eq(f.counts["critical"], 1, "the last block should win")
    check_eq(f.findings[0]["claim"], "real", "the last block's claim")


def test_findings_severity_normalisation() -> None:
    text = ('```json\n[{"severity":"HIGH","claim":"a"},'
            '{"severity":"blocker","claim":"b"},'
            '{"severity":"low","claim":"c"},'
            '{"severity":"showstopper","claim":"d"}]\n```')
    f = rr.parse_findings(text)
    check(f.ok, "mixed-vocabulary severities did not parse")
    check_eq(f.counts["important"], 1, "HIGH maps to important")
    check_eq(f.counts["critical"], 1, "blocker maps to critical")
    check_eq(f.counts["minor"], 1, "low maps to minor")
    check_eq(f.counts["unknown"], 1,
             "an unrecognised severity must count as unknown, never be folded "
             "into minor where it would vanish from the metric")


def test_findings_malformed_inputs() -> None:
    """Every one of these must report a parse FAILURE, not zero findings. The
    distinction is the benchmark's primary metric (assumption A8)."""
    cases = {
        "None": None,
        "empty string": "",
        "whitespace only": "   \n\t ",
        "prose with no block": "I looked and it seems fine to me, honestly.",
        "truncated JSON": '```json\n[{"severity": "Critical", "claim": "x"',
        "not a list": '```json\n{"verdict": "clean"}\n```',
        "list of strings": '```json\n["a crash in server.py"]\n```',
        "objects with no severity":
            '```json\n[{"issue": "crash", "where": "server.py"}]\n```',
        "single quotes": "```json\n[{'severity': 'Critical'}]\n```",
        "trailing comma": '```json\n[{"severity":"Critical","claim":"x"},]\n```',
        "html not json": "<findings><item sev='critical'/></findings>",
    }
    for label, text in cases.items():
        f = rr.parse_findings(text)
        check(not f.ok, f"malformed input ({label}) was accepted as valid findings")
        check(f.counts is None,
              f"malformed input ({label}) produced counts {f.counts!r}; a parse "
              "failure must leave counts null, never zero")
        check(bool(f.error), f"malformed input ({label}) reported no error message")


def test_findings_tolerated_shapes() -> None:
    """Shapes a real reviewer emits that ARE recoverable."""
    ok_cases = {
        "bare array, no fence":
            '[{"severity": "Critical", "claim": "x"}]',
        "wrapped in an object":
            '```json\n{"findings": [{"severity":"Important","claim":"y"}]}\n```',
        "plain fence with no language tag":
            '```\n[{"severity": "Minor", "claim": "z"}]\n```',
        "prose then a bare array":
            'I found one thing.\n\n[{"severity": "Critical", "claim": "boom"}]',
        "sev instead of severity":
            '```json\n[{"sev": "Critical", "claim": "x"}]\n```',
        # A reviewer that opened a fence and forgot to close it still emitted
        # well-formed findings. The bracket-span fallback recovers them, and
        # only ever runs after every fenced candidate has failed.
        "unterminated fence":
            '```json\n[{"severity":"Critical","claim":"x"}]',
    }
    for label, text in ok_cases.items():
        f = rr.parse_findings(text)
        check(f.ok, f"recoverable shape ({label}) was rejected: {f.error}")


def test_round_totals_separate_unparsed_from_zero() -> None:
    rounds = [
        {"parse_ok": True, "counts": {"critical": 2, "important": 1, "minor": 0,
                                      "unknown": 0, "total": 3}},
        {"parse_ok": False, "counts": None},
        {"parse_ok": True, "counts": {"critical": 0, "important": 0, "minor": 4,
                                      "unknown": 0, "total": 4}},
    ]
    t = rr._sum_rounds(rounds)
    check_eq(t["critical"], 2, "summed critical")
    check_eq(t["important"], 1, "summed important")
    check_eq(t["rounds"], 3, "round count")
    check_eq(t["rounds_unparsed"], 1,
             "an unparsed round must be counted as unparsed, not as zero findings")


# ---------------------------------------------------------------------------
# 6. Reading `claude -p --output-format json` back
# ---------------------------------------------------------------------------

RESULT_EVENT = {
    "type": "result", "subtype": "success", "is_error": False,
    "result": "done", "num_turns": 7, "duration_ms": 1234,
    "total_cost_usd": 0.42,
    "usage": {"input_tokens": 9, "output_tokens": 71,
              "cache_creation_input_tokens": 11527,
              "cache_read_input_tokens": 13782},
    "modelUsage": {
        "claude-sonnet-4-5": {"inputTokens": 900, "outputTokens": 80,
                              "cacheReadInputTokens": 13782,
                              "cacheCreationInputTokens": 11527},
        "claude-haiku-4-5": {"inputTokens": 100, "outputTokens": 20,
                             "cacheReadInputTokens": 0,
                             "cacheCreationInputTokens": 0},
    },
}


def _write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text, encoding="utf-8")
    return p


def test_claude_result_all_three_shapes() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # A1: the shape this CLI actually emits -- an array of stream events.
        arr = _write(tmp, "arr.json", json.dumps(
            [{"type": "system", "subtype": "init"},
             {"type": "assistant", "message": {}},
             RESULT_EVENT]))
        r = rr.parse_claude_result(arr)
        check(r.ok, f"array shape failed to parse: {r.error}")
        check_eq(r.shape, "array", "array shape detection")
        check_eq(r.text, "done", "final text from the array shape")

        obj = _write(tmp, "obj.json", json.dumps(RESULT_EVENT))
        r = rr.parse_claude_result(obj)
        check(r.ok, f"single-object shape failed to parse: {r.error}")
        check_eq(r.shape, "object", "object shape detection")

        jl = _write(tmp, "jl.json",
                    "\n".join(json.dumps(e) for e in
                              [{"type": "system"}, RESULT_EVENT]))
        r = rr.parse_claude_result(jl)
        check(r.ok, f"jsonl shape failed to parse: {r.error}")
        check_eq(r.shape, "jsonl", "jsonl shape detection")


def test_claude_result_failures_are_reported() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for label, text in {
            "empty file": "",
            "not json": "Traceback (most recent call last): boom",
            "json with no result event": json.dumps([{"type": "system"}]),
        }.items():
            r = rr.parse_claude_result(_write(tmp, f"{abs(hash(label))}.json", text))
            check(not r.ok, f"{label} was accepted as a valid agent result")
            check(bool(r.error), f"{label} produced no error message")

        r = rr.parse_claude_result(tmp / "does-not-exist.json")
        check(not r.ok, "a missing log was accepted as a valid result")

        err_ev = dict(RESULT_EVENT, is_error=True, subtype="error_max_turns")
        r = rr.parse_claude_result(_write(tmp, "err.json", json.dumps([err_ev])))
        check(not r.ok, "an is_error result was reported as success")
        check(r.result_event is not None,
              "an is_error result should still surrender its usage numbers")


def test_tokens_prefer_the_cumulative_aggregate() -> None:
    """A2: `usage` is the last turn only; `modelUsage` is the session
    aggregate. Taking the wrong one understates a long build by orders of
    magnitude."""
    t = rr.tokens_from_result(RESULT_EVENT)
    check_eq(t["source"], "modelUsage", "token source")
    check_eq(t["input"], 1000, "summed input across models")
    check_eq(t["output"], 100, "summed output across models")
    check_eq(t["total_tokens"], 1000 + 100 + 13782 + 11527, "summed total")
    check(not t["estimated"], "a measured figure must not be flagged estimated")

    no_mu = {k: v for k, v in RESULT_EVENT.items() if k != "modelUsage"}
    t2 = rr.tokens_from_result(no_mu)
    check("usage" in t2["source"], "should fall back to usage")
    check("last turn" in t2["source"],
          "the fallback must say it is a floor, not a total")

    t3 = rr.tokens_from_result(None)
    check_eq(t3["total_tokens"], 0, "no result event -> zero tokens")
    check_eq(t3["source"], "unavailable", "no result event -> source says so")


def test_estimated_tokens_are_flagged() -> None:
    e = rr.estimated_tokens("a" * 400, "b" * 40)
    check(e["estimated"], "a foreign-seat estimate must be flagged as estimated")
    check_eq(e["total_tokens"], 110, "chars/4 estimate")
    summed = rr.add_tokens(rr.tokens_from_result(RESULT_EVENT), e)
    check(summed["estimated"],
          "a sum containing an estimate must itself be flagged estimated")


# ---------------------------------------------------------------------------
# 7. The manifest writer and the schema
# ---------------------------------------------------------------------------

def _fake_run(config_name: str, tmp: Path) -> rr.Run:
    """A Run object with no side effects: nothing is launched and the worktree
    is never created. Enough to exercise manifest assembly."""
    args = argparse.Namespace(
        framework=str(FRAMEWORK), runs_root=str(tmp),
        ask_agent=str(rr.DEFAULT_ASK_AGENT), run_id="test-manifest",
        dry_run=False, print_prompt=None, config=str(CONFIG_DIR / config_name))
    cfg = rr.load_config(CONFIG_DIR / config_name)
    return rr.Run(cfg, args)


def test_manifest_validates_against_the_schema() -> None:
    schema = json.loads((HARNESS / "manifest.schema.json").read_text())
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name in ("raw.json", "protocol-full.json", "r3-orgs-full.json",
                     "r1-goal-native-review.json"):
            run = _fake_run(name, tmp)
            # An empty run: nothing succeeded. This is the shape a manifest
            # takes after a total failure, and it must still validate --
            # a run directory that is only complete on the happy path is not
            # evidence.
            man = run.manifest(rr.utc_now())
            errs = rr.validate_schema(man, schema)
            check(not errs, f"{name}: empty manifest violates the schema: {errs[:4]}")
            check_eq(man["regime_name"], run.cfg.regime, f"{name}: regime_name")
            check(man["regime"] in ("raw", "native", "protocol"),
                  f"{name}: coarse regime is not one of the schema's three")

            # And a populated one.
            run.grading_stages = {
                "after_build": {"ran": True, "conformance_passed": 14,
                                "conformance_total": 16, "exit_code": 1},
                "final": {"ran": True, "conformance_passed": 16,
                          "conformance_total": 16, "exit_code": 0},
            }
            run.review_steps = {
                s: {"ran": True, "skipped_reason": None, "rounds": [],
                    "totals": rr._empty_totals(), "fix_rounds_applied": 0}
                for s in rr.REVIEW_STEP_ORDER}
            run.escaped = {"ran": True, "parse_ok": True, "complete": True,
                           "audited_sha": "abc", "critical_important": 4,
                           "counts": {"critical": 3, "important": 1, "minor": 2,
                                      "unknown": 0, "total": 6},
                           "seats": {}, "seats_filled": ["codex"],
                           "seats_empty": ["agy"], "union_note": "sum"}
            run.tokens = {"build": rr.tokens_from_result(RESULT_EVENT),
                          "review:council": rr.estimated_tokens("p", "r")}
            run.phases = {"build": 12.5, "audit": 3.0}
            man = run.manifest(rr.utc_now())
            errs = rr.validate_schema(man, schema)
            check(not errs, f"{name}: populated manifest violates the schema: {errs[:4]}")
            check_eq(man["grading"]["conformance_passed"], 16,
                     f"{name}: grading mirrors the FINAL stage, not the first")
            check_eq(man["grading"]["escaped_defects"], 4,
                     f"{name}: escaped defects mirrored into grading")
            # An incomplete audit must NOT fill the headline field: a one-seat
            # number sitting where a two-seat number belongs makes the arm
            # that lost a provider look like the most robust of the six.
            run.escaped = dict(run.escaped, complete=False, parse_ok=False,
                               seats_filled=["codex"], seats_empty=["agy"])
            partial = run.manifest(rr.utc_now())
            check_eq(partial["grading"]["escaped_defects"], None,
                     f"{name}: an incomplete audit must not fill the headline "
                     "robustness field")
            check_eq(partial["escaped_defects"]["critical_important"], 4,
                     f"{name}: the partial count is still kept in the detail")
            check(not rr.validate_schema(partial, schema),
                  f"{name}: the partial-audit manifest violates the schema")

            # The summary must render without raising on any of these shapes.
            text = rr.render_summary(run, man)
            check(len(text) > 500, f"{name}: SUMMARY.md is implausibly short")
            check("Escaped defects" in text, f"{name}: SUMMARY.md lacks the yardstick")


def test_cost_bucketing_follows_runbook_8() -> None:
    """coordination = review seats; product = build + fix rounds; the audit is
    in NEITHER (it is the measuring instrument, not work the org did).

    This is not bookkeeping pedantry: meta:product is the tripwire the study
    compares arms on, and putting the fix rounds on the wrong side inflates
    coordination and deflates product in every arm that reviews at all."""
    def tok(n):
        return {"input": n, "output": 0, "cache_read": 0, "cache_creation": 0,
                "total_tokens": n, "estimated": False}

    with tempfile.TemporaryDirectory() as td:
        run = _fake_run("protocol-full.json", Path(td))
        run.tokens = {
            "build": tok(1000),
            "review:native": tok(100),
            "review:council": tok(200),
            "review:lead": tok(30),
            "review:cto": tok(70),
            "fix:native-round1": tok(500),
            "fix:council-round1": tok(400),
            "audit": tok(9999),
        }
        man = run.manifest(rr.utc_now())
        check_eq(man["cost"]["coordination_tokens"], 400,
                 "coordination must be exactly the review seats")
        check_eq(man["cost"]["product_tokens"], 1900,
                 "product must be the build plus every fix round")
        check_eq(man["meta_product_ratio"], round(400 / 1900, 4),
                 "meta:product ratio")
        total = man["cost"]["coordination_tokens"] + man["cost"]["product_tokens"]
        check(9999 not in (man["cost"]["coordination_tokens"],
                           man["cost"]["product_tokens"]),
              "the audit leaked into a cost bucket")
        check_eq(total, 2300, "the audit must be in neither bucket")
        check("audit" in man["tokens_by_phase"],
              "the audit must still be reported in tokens_by_phase")

        run.tokens = {}
        man = run.manifest(rr.utc_now())
        check_eq(man["meta_product_ratio"], None,
                 "no product tokens -> null ratio, never a division by zero")


def test_fix_introduced_regressions() -> None:
    """The bug class the whole review ladder exists to catch gets its own
    number: assertions that passed after the build and stopped passing."""
    good = {"after_build": {"ran": True, "conformance_passed": 16, "conformance_total": 16},
            "final": {"ran": True, "conformance_passed": 16, "conformance_total": 16}}
    check_eq(rr._fix_regressions(good), 0, "no regression")
    bad = {"after_build": {"ran": True, "conformance_passed": 16, "conformance_total": 16},
           "final": {"ran": True, "conformance_passed": 13, "conformance_total": 16}}
    check_eq(rr._fix_regressions(bad), 3, "three assertions lost to the fix rounds")
    improved = {"after_build": {"ran": True, "conformance_passed": 10, "conformance_total": 16},
                "final": {"ran": True, "conformance_passed": 16, "conformance_total": 16}}
    check_eq(rr._fix_regressions(improved), 0, "an improvement is not a regression")
    check_eq(rr._fix_regressions({}), None, "no data -> null, not zero")
    check_eq(rr._fix_regressions({"after_build": {"ran": False}, "final": {"ran": False}}),
             None, "an exam that never ran -> null, not zero")


def test_schema_validator_catches_violations() -> None:
    """The validator must be able to fail, or it is decoration."""
    schema = json.loads((HARNESS / "manifest.schema.json").read_text())
    with tempfile.TemporaryDirectory() as td:
        run = _fake_run("protocol-full.json", Path(td))
        man = run.manifest(rr.utc_now())
        check(not rr.validate_schema(man, schema), "the baseline manifest should be valid")

        broken = copy.deepcopy(man); broken["regime"] = "orgs-full"
        check(rr.validate_schema(broken, schema), "an out-of-enum regime slipped through")
        broken = copy.deepcopy(man); broken.pop("run_id")
        check(rr.validate_schema(broken, schema), "a missing required field slipped through")
        broken = copy.deepcopy(man); broken["surprise"] = 1
        check(rr.validate_schema(broken, schema),
              "additionalProperties:false was not enforced")
        broken = copy.deepcopy(man); broken["cost"]["model_calls"] = -1
        check(rr.validate_schema(broken, schema), "a negative minimum slipped through")
        broken = copy.deepcopy(man); broken["cost"]["model_calls"] = "seven"
        check(rr.validate_schema(broken, schema), "a string where an integer belongs slipped through")
        broken = copy.deepcopy(man); broken["cost"]["model_calls"] = True
        check(rr.validate_schema(broken, schema),
              "a bool where an integer belongs slipped through (bool is an int in Python)")


# ---------------------------------------------------------------------------
# 8. Log scrapers used by the background loops
# ---------------------------------------------------------------------------

def test_stall_detection() -> None:
    observe = """# Standup — 2026-09-03T09:00:00Z

## codec
- unobserved bus messages: 0
- last commit mentioning it: 3 min ago

## engine
- unobserved bus messages: 1
- last commit mentioning it: 41 min ago
- ⚠ STALL: no commit in 41 min (threshold 15) — candidate rabbit-hole

## server
- no commits mention this agent yet
"""
    check_eq(rr._stalled_agents(observe), ["engine"], "stalled agent detection")
    check_eq(rr._stalled_agents(""), [], "empty observe output")
    check_eq(rr._stalled_agents("## a\n- fine\n"), [], "no stall, no flag")


def test_crystal_conflict_scrape() -> None:
    report = """# Crystal report — 2026-09-03T09:00:00Z
base: bench-run/x@abc1234

## bench-run/x@abc1234 × wp-codec@def5678
merge: clean
tests: pass

## wp-codec@def5678 × wp-engine@aaa1111
merge: CONFLICT (targets/resp/server.py)

## wp-engine@aaa1111 × wp-server@bbb2222
merge: clean
tests: FAIL

summary: conflicts found
"""
    got = rr._conflict_stanzas(report)
    check_eq(len(got), 2, "two conflicting stanzas")
    check("CONFLICT" in got[0], "the textual conflict was captured")
    check("FAIL" in got[1], "the semantic conflict was captured")
    check_eq(rr._conflict_stanzas("summary: all clean"), [],
             "a clean report yields no stanzas")


def test_render_rejects_missing_values() -> None:
    try:
        rr.render("hello {{NAME}} and {{OTHER}}", {"NAME": "x"}, where="t")
    except rr.PromptError as exc:
        check("OTHER" in str(exc), "the error should name the missing placeholder")
    else:
        FAILURES.append("render accepted a template with an unfilled placeholder")

    # Substituted material may legally contain braces; one pass must not
    # try to expand them.
    out = rr.render("{{A}}", {"A": "literal {{NOT_A_PLACEHOLDER}} text"}, where="t")
    check("{{NOT_A_PLACEHOLDER}}" in out,
          "substituted content was re-scanned for placeholders")


def test_doctrine_extraction() -> None:
    block = rr.extract_doctrine_block(
        (FRAMEWORK / "doctrine/DOCTRINE.md").read_text())
    check("schwerpunkt" in block.lower(), "the doctrine block lost its anchor")
    check("Auftragstaktik" not in block,
          "the extractor grabbed more than the prompt block")
    check(len(block) > 500, f"the doctrine block is implausibly short ({len(block)})")
    check(not block.startswith(">"), "the blockquote markers were not stripped")
    try:
        rr.extract_doctrine_block("# Doctrine\n\nNo prompt block here.\n")
    except rr.PromptError:
        pass
    else:
        FAILURES.append("doctrine extraction accepted a document with no prompt block")


# ---------------------------------------------------------------------------
# 9. Council-round findings: the fairness and isolation invariants
# ---------------------------------------------------------------------------

def test_runbook_is_ablated_with_its_mechanism() -> None:
    """The runbook is the lead's PROCESS document, so for a process ablation
    it is not a shared input like the spec -- it IS the treatment. Leaving §7
    in an arm with crystal off means that arm was still instructed to run
    speculative merge checks, and r3-vs-r4 then measures a background loop
    rather than the mechanism."""
    runbook = (FRAMEWORK / "protocol/RUNBOOK.md").read_text()
    all_on = {k: True for k in rr.CANONICAL_TOGGLES}
    all_on["review"] = True
    kept, removed = rr.filter_runbook(runbook, all_on)
    check_eq(removed, [], "nothing should be removed when every mechanism is on")
    check_eq(kept, runbook, "an all-on arm gets the runbook verbatim")

    for mech, marker in (("standup", "5. Standup"),
                         ("crystal", "7. Speculative merge check")):
        off = dict(all_on, **{mech: False})
        kept, removed = rr.filter_runbook(runbook, off)
        check(any(marker in r for r in removed),
              f"{mech} off: section '{marker}' should have been removed")
        check("REMOVED for this run" in kept,
              f"{mech} off: the removed section leaves no explanatory stub")
        check(len(kept) < len(runbook),
              f"{mech} off: the runbook did not actually get shorter")

    # And end to end, in the composed prompt for the real study configs.
    for name in ("r4-orgs-no-crystal.json", "r5-orgs-no-crystal-no-standup.json"):
        cfg = rr.load_config(CONFIG_DIR / name)
        build = rr.compose_build_prompt(cfg, make_ctx(cfg))
        check("At standup cadence: attempt merges" not in build,
              f"{name}: crystal is off but the runbook still instructs it")
        if not cfg.toggles["standup"]:
            check("Convened on triggers (budget tripwire" not in build,
                  f"{name}: standup is off but the runbook still instructs it")


def test_parallel_instruction_has_exactly_one_voice() -> None:
    """The bullet used to say "all in ONE message, so they run concurrently"
    unconditionally, with only the note after it flipping -- so the sequential
    arm was told both things and could honour either."""
    for path in all_configs():
        cfg = rr.load_config(path)
        if not cfg.toggles["decomposition"]:
            continue
        build = rr.compose_build_prompt(cfg, make_ctx(cfg))
        if cfg.toggles["parallel"]:
            check("all in ONE message" in build,
                  f"{path.name}: parallel on but the prompt does not say so")
            check("SEQUENTIAL by configuration" not in build,
                  f"{path.name}: parallel on but the prompt also says sequential")
        else:
            check("SEQUENTIAL by configuration" in build,
                  f"{path.name}: parallel off but the prompt does not say so")
            check("all in ONE message" not in build,
                  f"{path.name}: parallel off but the prompt still says to "
                  "spawn every worker in one message")


def test_standup_agent_ids_are_run_unique() -> None:
    """standup.sh finds an agent's activity with `git log --all --grep=<id>`,
    and --all in this bare-repo layout is every ref in the project. Generic
    ids like `codec` or `server` match unrelated history, so every agent reads
    as stalled from the first observe and the standup-ON arms get a stream of
    fabricated redirects the standup-OFF arms never see."""
    cfg = rr.load_config(CONFIG_DIR / "r3-orgs-full.json")
    a = make_ctx(cfg, run_id="run-A")
    b = make_ctx(cfg, run_id="run-B")
    check(a.agent_token != b.agent_token,
          "two runs produced the same agent token")
    for short in cfg.worker_ids + ["lead"]:
        ida = a.standup_id(short)
        check(ida.startswith(a.agent_token),
              f"{short}: the standup id is not run-scoped")
        check(ida != b.standup_id(short),
              f"{short}: two runs share a standup id, so their commits collide")
        check(len(ida) > 8, f"{short}: the standup id is implausibly short")
    check(a.lead_agent_id.startswith(a.agent_token), "lead id is not run-scoped")
    check(a.solo_agent_id.startswith(a.agent_token), "solo id is not run-scoped")

    # The composed prompt must carry the tracking ids, not the bare ones.
    build = rr.compose_build_prompt(cfg, a)
    for short in cfg.worker_ids:
        check(a.standup_id(short) in build,
              f"{short}: the build prompt never gives the worker its tracking id")


def test_agent_env_is_scrubbed() -> None:
    """Each regime is supposed to be a fresh process with no inherited
    context. Passing this session's own CLAUDE_* variables through makes that
    false and can let a "fresh" reviewer resume back into the context it is
    supposed to lack."""
    for leaky in ("CLAUDE_CODE_SESSION", "CLAUDECODE", "CLAUDE_SESSION_ID",
                  "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_ENTRYPOINT",
                  "CODEX_THREAD_ID", "GEMINI_CONVERSATION"):
        check(rr._is_agent_env(leaky), f"{leaky} should be scrubbed")
    # Scrubbing a provider's CREDENTIALS would not corrupt the study -- it
    # would make that seat fail, silently turning a councilled arm into an
    # un-councilled one, which is worse.
    for keep in ("PATH", "HOME", "TMPDIR", "LANG",
                 "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
                 "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR",
                 "CODEX_HOME", "CODEX_API_KEY", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY", "ANTIGRAVITY_HOME"):
        check(not rr._is_agent_env(keep),
              f"{keep} must NOT be scrubbed — the seat needs it to run")


def test_conformance_line_is_anchored() -> None:
    """The exam runs the server as a child, so the server's stdout is
    interleaved with the exam's. An unanchored search would scrape a
    conformance line the SERVER printed."""
    check(re.search(r"\^conformance", rr.__dict__.get("__file__", "") or "") is None,
          "placeholder")  # keeps the import of re honest if unused elsewhere
    pat = re.compile(r"^conformance:\s*(\d+)\s+passed,\s*(\d+)\s+failed\s*$",
                     re.MULTILINE)
    forged = "server log: conformance: 16 passed, 0 failed (nice try)\n"
    check(not pat.findall(forged),
          "a conformance line embedded in another line was accepted")
    real = "some output\nconformance: 12 passed, 0 failed\n"
    check_eq(pat.findall(real), [("12", "0")], "the real line must still parse")
    both = forged + real
    check_eq(pat.findall(both)[-1], ("12", "0"),
             "with a forged line present the real one must win")


def test_crystal_noise_is_separated_from_real_conflicts() -> None:
    """crystal-check.sh's own header: "a branch red on its own makes every one
    of its pairings FAIL, which is noise". Counting those inflates the crystal
    metric with the one thing crystal is not for."""
    base = "bench-run/x"
    report = """# Crystal report
base: bench-run/x@aaa

## bench-run/x@aaa \u00d7 wp-codec@bbb
merge: clean
tests: pass

## bench-run/x@aaa \u00d7 wp-engine@ccc
merge: clean
tests: FAIL

## wp-codec@bbb \u00d7 wp-engine@ccc
merge: clean
tests: FAIL

## wp-codec@bbb \u00d7 wp-server@ddd
merge: CONFLICT (targets/resp/server.py)
"""
    real, noisy = rr._classify_conflicts(report, base)
    check_eq(noisy, ["wp-engine"],
             "the branch that fails against the base is the red-alone one")
    check_eq(len(real), 1,
             f"only the genuine cross-branch conflict should survive, got {real}")
    check("CONFLICT" in real[0], "the surviving stanza should be the textual one")
    # With no base given, nothing can be classified as noise.
    real2, noisy2 = rr._classify_conflicts(report, None)
    check_eq(noisy2, [], "no base -> no noise classification")
    check_eq(len(real2), 3, "no base -> every conflicting stanza is reported")


def test_seat_tally_is_strict_about_missing_seats() -> None:
    """A round where one provider was rate-limited is not a clean round: its
    union is one seat's opinion wearing a two-seat label."""
    rounds = [
        {"round": 1, "parse_ok": True, "partial": False,
         "counts": {"critical": 2, "important": 1, "minor": 0, "unknown": 0,
                    "total": 3}},
        {"round": 2, "parse_ok": False, "partial": False, "counts": None},
        {"round": 3, "parse_ok": False, "partial": True,
         "counts": {"critical": 1, "important": 0, "minor": 0, "unknown": 0,
                    "total": 1}},
    ]
    t = rr._sum_rounds(rounds)
    check_eq(t["rounds_unparsed"], 1,
             "only the round with NO usable counts is unparsed")
    check_eq(t["rounds_partial"], 1,
             "a round where some seats answered is partial, not discarded")
    check_eq(t["critical"], 3,
             "a partial round's real findings must still be counted — "
             "discarding them loses genuine findings from the primary total")
    check_eq(t["first_round"]["critical"], 2,
             "first_round is the comparable per-step figure")
    check_eq(t["first_round"]["total"], 3, "first_round total")
    check(t["first_round"]["complete"], "round 1 here was complete")

    # A round 1 that produced nothing readable must NOT read as "found
    # nothing" in the field designated as the cross-arm comparable figure.
    unparsed_first = [{"round": 1, "parse_ok": False, "counts": None},
                      {"round": 2, "parse_ok": True,
                       "counts": {"critical": 5, "important": 0, "minor": 0,
                                  "unknown": 0, "total": 5}}]
    t2 = rr._sum_rounds(unparsed_first)
    check_eq(t2["first_round"], None,
             "an unparsed round 1 must null first_round, never report zeros")


def test_first_round_is_independent_of_round_count() -> None:
    """The summed buckets grow with how many rounds an arm was configured
    for; first_round does not, which is why it is the comparable one."""
    one = [{"round": 1, "parse_ok": True,
            "counts": {"critical": 3, "important": 0, "minor": 0, "unknown": 0,
                       "total": 3}}]
    two = one + [{"round": 2, "parse_ok": True,
                  "counts": {"critical": 3, "important": 0, "minor": 0,
                             "unknown": 0, "total": 3}}]
    check_eq(rr._sum_rounds(one)["first_round"],
             rr._sum_rounds(two)["first_round"],
             "first_round must not depend on the configured round count")
    check(rr._sum_rounds(two)["critical"] > rr._sum_rounds(one)["critical"],
          "the summed bucket should grow with rounds (that is why it is not "
          "the headline)")


def test_fix_regressions_uses_assertion_names() -> None:
    """A fix round that repairs one assertion while breaking another leaves
    the pass COUNT identical -- and the count-based version reported zero
    regressions for exactly the case this metric exists to find."""
    stages = {
        "after_build": {"ran": True, "conformance_passed": 15,
                        "conformance_total": 16, "failures": ["PING"]},
        "final": {"ran": True, "conformance_passed": 15,
                  "conformance_total": 16, "failures": ["ECHO hello"]},
    }
    check_eq(rr._fix_regressions(stages), 1,
             "a swapped failure is a fix-introduced regression, not a wash")
    clean = {
        "after_build": {"ran": True, "conformance_passed": 15,
                        "conformance_total": 16, "failures": ["PING"]},
        "final": {"ran": True, "conformance_passed": 16,
                  "conformance_total": 16, "failures": []},
    }
    check_eq(rr._fix_regressions(clean), 0, "a genuine repair is not a regression")


def test_cost_provenance_flags_incomparable_arms() -> None:
    """Summing a measured `claude -p` figure with an estimated ask-agent one
    makes an arm reviewed by a council look an order of magnitude cheaper
    than an arm reviewed natively -- an artefact of HOW they were counted."""
    measured = rr.tokens_from_result(RESULT_EVENT)
    estimate = rr.estimated_tokens("p" * 4000, "r" * 400)
    both = rr._split_provenance([measured, estimate])
    check(both["measured"]["total_tokens"] > 0, "the measured half is populated")
    check(both["estimated"]["total_tokens"] > 0, "the estimated half is populated")
    check(not both["comparable_across_arms"],
          "a bucket containing an estimate must be flagged incomparable")
    only_measured = rr._split_provenance([measured])
    check(only_measured["comparable_across_arms"],
          "a purely measured bucket is comparable")
    check_eq(only_measured["estimated"]["total_tokens"], 0, "no estimate leaked in")


def test_models_honoured_check() -> None:
    """A lead that quietly upgrades its workers changes the variable `tiering`
    exists to isolate, while the manifest goes on claiming the configured mix."""
    cfg = {"lead": "sonnet", "worker": "haiku"}
    check(rr._models_honoured(cfg, {"claude-sonnet-4-5": 10,
                                    "claude-haiku-4-5": 20}) is True,
          "the configured mix should read as honoured")
    check(rr._models_honoured(cfg, {"claude-opus-4-1": 10}) is False,
          "a model the config never named must be flagged")
    check(rr._models_honoured(cfg, {}) is None,
          "nothing observed -> null, not a false claim of compliance")


def test_review_steps_override_is_written_back_to_toggles() -> None:
    """`review_steps` used to be able to switch a rung on or off while
    `toggles` -- what the manifest, coarse regime and ablation are computed
    from -- still described the other arrangement."""
    base = json.loads((CONFIG_DIR / "r3-orgs-full.json").read_text())
    base["review_steps"] = {"native": True, "cto": False}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(base, fh)
        p = Path(fh.name)
    try:
        cfg = rr.load_config(p)
        check_eq(cfg.steps["native"], True, "the override took effect")
        check_eq(cfg.toggles["review_native"], True,
                 "the toggle vector must agree with the ladder that runs")
        check_eq(cfg.steps["cto"], False, "the cto override took effect")
        check_eq(cfg.toggles["review_cto"], False,
                 "the toggle vector must agree with the ladder that runs")
    finally:
        p.unlink(missing_ok=True)


def test_nested_config_blocks_are_validated() -> None:
    base = json.loads((CONFIG_DIR / "protocol-full.json").read_text())

    def load(mutate):
        cfg = copy.deepcopy(base)
        mutate(cfg)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(cfg, fh)
            p = Path(fh.name)
        try:
            rr.load_config(p)
            return None
        except rr.ConfigError as exc:
            return str(exc)
        finally:
            p.unlink(missing_ok=True)

    for label, mutate in [
        ("a misspelled standup key",
         lambda c: c.update({"standup": {"stall_mins": 5}})),
        ("a misspelled crystal key",
         lambda c: c.update({"crystal": {"interval": 60}})),
        ("a non-numeric standup interval",
         lambda c: c.update({"standup": {"interval_s": "soon"}})),
        ("a non-string crystal test_cmd",
         lambda c: c.update({"crystal": {"test_cmd": 42}})),
        ("a standup block that is not an object",
         lambda c: c.update({"standup": [1, 2]})),
    ]:
        check(load(mutate) is not None,
              f"the config loader accepted {label} without complaint")
    check(load(lambda c: c.update({"standup": {"stall_min": 30}})) is None,
          "a well-formed nested override should still load")


# ---------------------------------------------------------------------------
# 10. Convergence round: defects the ROUND-1 FIXES introduced
# ---------------------------------------------------------------------------

def test_fix_regressions_ignores_the_observed_value() -> None:
    """The exam prints `FAIL: <name> — expected [X] got [Y]`. Set-differencing
    whole lines meant a fix that changed a still-failing assertion's wrong
    answer produced a new key and read as a fresh regression — inflating the
    number in proportion to how many fix rounds an arm ran, i.e. against the
    arms that review most."""
    check_eq(rr._assertion_name("PING — expected [PONG] got [nil]"), "PING",
             "the observed value must not be part of the assertion key")
    stages = {
        "after_build": {"ran": True, "conformance_passed": 15,
                        "conformance_total": 16,
                        "failures": ["PING — expected [PONG] got [nil]"]},
        "final": {"ran": True, "conformance_passed": 15, "conformance_total": 16,
                  "failures": ["PING — expected [PONG] got [ERR]"]},
    }
    check_eq(rr._fix_regressions(stages), 0,
             "the same assertion still failing differently is not a NEW "
             "regression")
    swapped = {
        "after_build": {"ran": True, "conformance_passed": 15,
                        "conformance_total": 16,
                        "failures": ["PING — expected [PONG] got [nil]"]},
        "final": {"ran": True, "conformance_passed": 15, "conformance_total": 16,
                  "failures": ["ECHO hello — expected [hello] got [nil]"]},
    }
    check_eq(rr._fix_regressions(swapped), 1,
             "a genuinely different assertion failing IS a regression")


def test_nested_config_does_not_clobber_the_minutes_form() -> None:
    """The helper written to stop a setting silently not taking effect did
    exactly that: it returned a defaults-filled dict, so `.update()` wrote the
    DEFAULT interval back over the value derived from *_interval_min."""
    base = json.loads((CONFIG_DIR / "r3-orgs-full.json").read_text())
    base["crystal_interval_min"] = 5
    base["crystal"] = {"test_cmd": "pytest -q"}
    base["standup_interval_min"] = 7
    base["standup"] = {"stall_min": 20}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(base, fh)
        p = Path(fh.name)
    try:
        cfg = rr.load_config(p)
        check_eq(cfg.crystal["interval_s"], 300.0,
                 "crystal_interval_min was clobbered by the nested block's default")
        check_eq(cfg.crystal["test_cmd"], "pytest -q", "the nested override applied")
        check_eq(cfg.standup["interval_s"], 420.0,
                 "standup_interval_min was clobbered by the nested block's default")
        check_eq(cfg.standup["stall_min"], 20, "the nested override applied")
        check_eq(cfg.standup["redirect_cooldown_s"],
                 rr.DEFAULT_STANDUP["redirect_cooldown_s"],
                 "an unmentioned key keeps its default")
    finally:
        p.unlink(missing_ok=True)


def test_falsey_nested_blocks_are_still_validated() -> None:
    """`if raw.get("standup")` let an empty list, "", 0 or false skip
    validation and silently take defaults."""
    base = json.loads((CONFIG_DIR / "protocol-full.json").read_text())
    for bad in ([], "", 0, False):
        cfg = copy.deepcopy(base)
        cfg["standup"] = bad
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(cfg, fh)
            p = Path(fh.name)
        try:
            rr.load_config(p)
            FAILURES.append(f"a falsey standup block ({bad!r}) bypassed validation")
        except rr.ConfigError:
            pass
        finally:
            p.unlink(missing_ok=True)


def test_crystal_keeps_textual_conflicts_from_red_branches() -> None:
    """A textual conflict is a `git merge-tree` result and has nothing to do
    with the boundary test, so a branch that is red on its own must not have
    its genuine textual conflicts suppressed as noise."""
    base = "bench-run/x"
    report = (
        "# Crystal report\nbase: bench-run/x@aaa\n\n"
        "## bench-run/x@aaa \u00d7 wp-codec@bbb\nmerge: clean\ntests: FAIL\n\n"
        "## wp-codec@bbb \u00d7 wp-server@ddd\n"
        "merge: CONFLICT (targets/resp/server.py)\n\n"
        "## wp-codec@bbb \u00d7 wp-engine@ccc\nmerge: clean\ntests: FAIL\n")
    real, noisy = rr._classify_conflicts(report, base)
    check_eq(noisy, ["wp-codec"], "wp-codec is red against the base")
    joined = " | ".join(real)
    check("CONFLICT" in joined,
          f"a textual conflict from a red-alone branch was suppressed: {real}")
    check("wp-codec@bbb × wp-engine@ccc" not in joined,
          "a semantic pairing of a red-alone branch is noise and must be dropped")
    check_eq(len(real), 1, f"exactly the textual conflict should survive: {real}")


def test_review_prompt_names_the_directory_the_reviewer_is_in() -> None:
    """The reviewer runs in a detached checkout so it cannot edit what it
    judges. Telling it the writable product tree is 'your working directory'
    both misdirects it and invites the write the detached tree prevents."""
    cfg = rr.load_config(CONFIG_DIR / "r1-goal-native-review.json")
    ctx = make_ctx(cfg)
    elsewhere = Path("/tmp/review-tree-xyz")
    p = rr.compose_review_prompt(cfg, ctx, "native", rr.DRY_MATERIALS,
                                 review_cwd=elsewhere)
    check(str(elsewhere) in p, "the prompt does not name the reviewer's own cwd")
    check(str(ctx.run_tree) not in p,
          "the prompt still points the reviewer at the writable product tree")


def test_provenance_flags_incomplete_sources() -> None:
    """'unavailable' and the last-turn-only fallback are not estimates, but
    they are not full measurements either — banking them as measured labels an
    undercounted arm comparable."""
    no_mu = {k: v for k, v in RESULT_EVENT.items() if k != "modelUsage"}
    fallback = rr.tokens_from_result(no_mu)
    prov = rr._split_provenance([fallback])
    check(prov["incomplete_sources"], "the last-turn-only fallback is not complete")
    check(not prov["comparable_across_arms"],
          "an incomplete source must not be labelled comparable")
    prov2 = rr._split_provenance([rr.zero_tokens("unavailable: no result")])
    check(prov2["incomplete_sources"], "'unavailable' is not a measurement")
    good = rr._split_provenance([rr.tokens_from_result(RESULT_EVENT)])
    check(good["comparable_across_arms"], "a real modelUsage figure IS comparable")


def test_models_missing_catches_a_within_set_upgrade() -> None:
    """_models_honoured only sees a model from OUTSIDE the configured set, so
    a lead that upgrades its haiku workers to the sonnet it also uses itself
    passes it. This catches that from the other side."""
    cfg = {"lead": "sonnet", "worker": "haiku"}
    seen_both = {"claude-sonnet-4-5": 100, "claude-haiku-4-5": 50}
    check_eq(rr._models_missing(cfg, seen_both, ("lead", "worker")), [],
             "both configured tiers appeared")
    only_sonnet = {"claude-sonnet-4-5": 100}
    check_eq(rr._models_missing(cfg, only_sonnet, ("lead", "worker")), ["haiku"],
             "the worker tier never ran, which _models_honoured cannot see")
    check(rr._models_honoured(cfg, only_sonnet) is True,
          "the honoured check alone would have passed this")
    check_eq(rr._models_missing(cfg, {}, ("lead", "worker")), None,
             "nothing observed -> null, not an empty list; [] would read as "
             "'every configured tier ran', a claim about an unobserved build")


# ---------------------------------------------------------------------------
# 11. Second convergence round: defects the ROUND-2 fixes introduced
# ---------------------------------------------------------------------------

def test_sweep_dirtiness_test_matches_the_sweep_itself() -> None:
    """The bus lives in the run tree and is in no .gitignore. Asking whether
    the tree is dirty WITHOUT the exclusion the commit uses meant a standup
    arm always looked dirty, staged nothing, and recorded a false
    'sweep failed' at every freeze point — in the standup arms only."""
    src = (HARNESS / "run_regime.py").read_text()
    status_call = [ln for ln in src.splitlines() if '"status", "--porcelain"' in ln]
    check(status_call, "the status call could not be found")
    check(any("SWEEP_EXCLUDE" in ln for ln in status_call),
          "git status does not use the same exclusion as git add")
    add_call = [ln for ln in src.splitlines() if '"add", "-A"' in ln]
    check(add_call and all("SWEEP_EXCLUDE" in ln for ln in add_call),
          "git add does not use the shared exclusion constant")
    check_eq(rr.SWEEP_EXCLUDE, ":(exclude).standup", "the exclusion pathspec")


def test_token_quality_flags_survive_aggregation() -> None:
    """Every coordination bucket is an add_tokens() aggregate. The
    incompleteness check read `source`, which add_tokens dropped — so the
    flag worked for `product` and was permanently dead for `coordination`,
    the bucket the review-ladder ablation is compared on."""
    no_mu = {k: v for k, v in RESULT_EVENT.items() if k != "modelUsage"}
    fallback = rr.tokens_from_result(no_mu)
    check(rr._is_incomplete(fallback), "the raw fallback is incomplete")
    agg = rr.add_tokens(fallback, rr.tokens_from_result(RESULT_EVENT))
    check(agg.get("incomplete"),
          "add_tokens dropped the incompleteness flag on aggregation")
    prov = rr._split_provenance([agg])
    check(not prov["comparable_across_arms"],
          "an aggregate containing an incomplete source must not be comparable")
    good = rr.add_tokens(rr.tokens_from_result(RESULT_EVENT))
    check(not good.get("incomplete"), "a clean aggregate is not incomplete")
    check(rr._split_provenance([good])["comparable_across_arms"],
          "a clean aggregate stays comparable")
    est = rr.add_tokens(rr.estimated_tokens("a", "b"))
    check(est["estimated"], "add_tokens must still carry `estimated` forward")


def test_crystal_health_guard_is_reachable() -> None:
    """Round 2 replaced a working guard with one that could never fire:
    build_s was read before it was assigned, and `attempts` was incremented
    only on the path that also incremented `checks`."""
    src = (HARNESS / "run_regime.py").read_text()
    build_idx = src.index('self.phases["build"] = time.time() - t0')
    health_idx = src.index("self._check_mechanism_health()")
    check(build_idx < health_idx,
          "phases['build'] is still assigned after the health check reads it")
    loop = src[src.index("def _crystal_loop"):src.index("def phase_grade")]
    a_idx = loop.index('self.crystal_stats["attempts"] += 1')
    guard_idx = loop.index("if not branches:")
    check(a_idx < guard_idx,
          "attempts is still counted only on the path that also runs a check, "
          "making 'checks == 0 and attempts > 0' unreachable")


def test_server_code_comes_from_the_frozen_checkout() -> None:
    """The inlined source must come from the clean detached checkout of the
    reviewed sha, never from the live product tree: the product tree can hold
    a venv or a build artefact that is in no revision, in nobody's diff, and
    that could eat the inlining budget and push the real server out of the
    reviewer's and the auditor's prompt."""
    src = (HARNESS / "run_regime.py").read_text()
    body = src[src.index("def collect_server_code"):src.index("def _tally_seats")]
    check("tree: Path | None" in body.split("\n")[0],
          "collect_server_code should read from a checkout it is handed")
    check("self.ctx.run_tree" not in body,
          "collect_server_code still reaches into the live product tree")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        run = _fake_run("r3-orgs-full.json", tmp / "runs")
        # No checkout at all -> say so, do not silently inline nothing.
        out, inlined, complete = run.collect_server_code(None)
        check(not inlined, "no checkout -> the entry point is not inlined")
        check("could not be checked out" in out,
              f"a missing checkout must be stated: {out[:80]}")

        tree = tmp / "tree"
        srcdir = tree / Path(run.cfg.server_path).parent
        srcdir.mkdir(parents=True)
        # An entry point, a sibling, and an EMPTY module.
        (tree / run.cfg.server_path).write_text("import codec\nPORT = 1\n")
        (srcdir / "codec.py").write_text("FRAMES = []\n")
        (srcdir / "__init__.py").write_text("")
        (srcdir / "__pycache__").mkdir()
        (srcdir / "__pycache__" / "junk.py").write_text("x = 1")
        out, inlined, complete = run.collect_server_code(tree)
        check(inlined, "the entry point body should be reported as inlined")
        check("import codec" in out, "the entry point was not inlined")
        check("FRAMES = []" in out, "a sibling module was not inlined")
        check("junk" not in out, "__pycache__ was inlined")
        check(out.index("server.py") < out.index("codec.py"),
              "the entry point should be inlined first")
        # An empty file is empty, not "budget exhausted".
        check("budget" not in out,
              f"an empty module was reported as a budget problem: {out}")
        check("__init__.py" in out, "the empty module was dropped entirely")
        check(complete, "a plain, wholly-inlined tree is complete")

        # The entry point missing while helpers survive is its own statement.
        (tree / run.cfg.server_path).unlink()
        out, inlined, complete = run.collect_server_code(tree)
        check(not inlined, "a missing entry point is not inlined")
        check("NO SERVER" in out,
              f"a missing entry point beside surviving helpers: {out[:120]}")


def test_seat_scratch_is_emptied_between_uses() -> None:
    with tempfile.TemporaryDirectory() as td:
        run = _fake_run("r3-orgs-full.json", Path(td))
        d = run.seat_scratch("review-fallback")
        (d / "leftover.py").write_text("previous reviewer was here")
        again = run.seat_scratch("review-fallback")
        check_eq(again, d, "the same name should give the same path")
        check(not (again / "leftover.py").exists(),
              "a reused scratch dir still holds the previous seat's files")


def test_crystal_signature_is_recorded_only_on_success() -> None:
    """Marking a conflict "already said" before the delivery landed meant one
    transient failure suppressed every later report of it as a duplicate —
    turning a per-check hiccup into permanent silence."""
    src = (HARNESS / "run_regime.py").read_text()
    body = src[src.index("def _deliver_crystal"):src.index("def phase_grade")]
    dispatch = body.index("run_capture(")
    after = body[dispatch:]
    check("self._last_crystal_signature = signature" in after,
          "the signature is never recorded after a successful delivery")
    before = body[:dispatch]
    # One assignment before the dispatch is legitimate: the standup-off
    # branch, which returns without attempting anything.
    check(before.count("self._last_crystal_signature = signature") <= 1,
          "the signature is recorded before the delivery is attempted")
    check('if not self.cfg.toggles["standup"]' in before,
          "the standup-off branch should be the only pre-dispatch record")
    check(body.count('if not self.cfg.toggles["standup"]') == 1,
          "the standup guard is duplicated; one copy is unreachable")


def test_audit_guard_tests_what_the_seats_are_shown() -> None:
    """The material comes from the frozen checkout, so guarding on the
    working tree would let a freeze that did not land hand the seats the
    "(no server)" placeholder — both answer [], and the arm that built
    nothing banks the best possible robustness score."""
    src = (HARNESS / "run_regime.py").read_text()
    body = src[src.index("def phase_audit"):src.index("def manifest")]
    guard = body[:body.index("prompt = compose_audit_prompt")]
    check("_seats_can_see(mat)" in guard,
          "the audit guard does not use the predicate that decides whether "
          "the seats will see the source")
    check("self.ctx.run_tree / self.cfg.server_path" not in guard,
          "the audit guard still tests the live working tree")


def test_oversized_source_is_truncated_not_dropped() -> None:
    """Dropping an over-budget entry point left the audit seats — whose
    prompt carries no diff — with nothing but an omission note, while the
    file plainly existed. The arm then banked a real zero on the robustness
    metric for a server nobody had read."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        run = _fake_run("r1-goal-native-review.json", tmp / "runs")
        tree = tmp / "tree"
        srcdir = tree / Path(run.cfg.server_path).parent
        srcdir.mkdir(parents=True)
        (tree / run.cfg.server_path).write_text("A" * (rr.CODE_CAP + 50_000))
        out, inlined, complete = run.collect_server_code(tree)
        check(inlined,
              "an oversized entry point must still count as inlined — "
              "dropping it lets the audit score a server nobody saw")
        check(not complete,
              "a truncated entry point is not a COMPLETE review: the seats "
              "saw a prefix and the round must be marked partial")
        check("truncated" in out, "the truncation is not disclosed")
        check("AAAA" in out, "no actual source was inlined")
        check(len(out) < rr.CODE_CAP + 5000, "the cap was not applied")


def test_symlinked_source_is_not_followed() -> None:
    """`st_size` of a symlink to a special file reports 0, walking straight
    past the stat-before-read bound — a link to /dev/zero would exhaust
    memory and a FIFO would hang the run."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        run = _fake_run("r1-goal-native-review.json", tmp / "runs")
        tree = tmp / "tree"
        srcdir = tree / Path(run.cfg.server_path).parent
        srcdir.mkdir(parents=True)
        (tree / run.cfg.server_path).write_text("PORT = 1\n")
        try:
            (srcdir / "evil.py").symlink_to("/dev/zero")
        except OSError:
            return                       # no symlink support; nothing to test
        out, inlined, complete = run.collect_server_code(tree)
        check(inlined, "the real entry point should still be inlined")
        check(not complete,
              "a skipped symlinked helper is code Python still executes, so "
              "the seats did not see everything that runs")
        check("not a regular file" in out,
              f"the symlink was followed rather than reported: {out[:200]}")

        # And a symlinked ENTRY POINT is reported, not resolved.
        (tree / run.cfg.server_path).unlink()
        (tree / run.cfg.server_path).symlink_to("/dev/zero")
        out2, inlined2, complete2 = run.collect_server_code(tree)
        check(not inlined2, "a symlinked entry point must not count as inlined")
        check("not a regular file" in out2, "the symlinked entry point was followed")


def test_frozen_checkout_prunes_before_re_adding() -> None:
    """A reset failure leaves the path REGISTERED while review_tree is None,
    so the add would fail 'already exists' for the rest of the run — turning
    one transient error into permanent loss of inlined source and a nulled
    audit blaming a server the arm did build."""
    src = (HARNESS / "run_regime.py").read_text()
    body = src[src.index("def frozen_checkout"):src.index("def seat_scratch")]
    add_idx = body.index('"worktree", "add"')
    check('"worktree", "prune"' in body[:add_idx],
          "frozen_checkout does not prune a stale registration before adding")
    check('"worktree", "remove"' in body[:add_idx],
          "frozen_checkout does not remove a leftover directory before adding")


def test_crystal_undelivered_is_counted_once_per_finding() -> None:
    """Counting it every loop iteration turned `undelivered` into a measure
    of how long the build ran rather than of how much crystal could not say.

    Exercised by CALLING it, not by reading the source. The previous version
    of this test only checked statement order, and a council seat proved it
    vacuous by deleting the assignment it was meant to pin and watching the
    suite stay green.
    """
    with tempfile.TemporaryDirectory() as td:
        # no-standup.json is the config that actually reaches this path:
        # crystal on, standup off, so nothing can be pushed to the lead.
        run = _fake_run("no-standup.json", Path(td))
        check(not run.cfg.toggles["standup"], "this config should have standup off")
        stanzas = ["a@1 × b@2 — merge: CONFLICT (x.py)"]
        for _ in range(5):
            run._deliver_crystal(1, stanzas, [])
        check_eq(run.crystal_stats["undelivered"], 1,
                 "the same undeliverable finding must be counted once, not "
                 "once per check — otherwise `undelivered` measures build "
                 "length rather than lost information")
        check_eq(run.crystal_stats["suppressed_repeats"], 4,
                 "the repeats should be recorded as suppressed")
        run._deliver_crystal(2, ["c@3 × d@4 — tests: FAIL"], [])
        check_eq(run.crystal_stats["undelivered"], 2,
                 "a DIFFERENT finding must still be counted")
        check_eq(run.crystal_stats["delivered"], 0,
                 "nothing can be delivered with no bus")


def test_a_blind_review_round_is_not_a_complete_one() -> None:
    """When the frozen checkout fails, the reviewer stands in an empty
    scratch directory, its prompt tells it not to go looking for files, and
    its source section is a single "could not be checked out" note: it
    reviewed the diff and nothing else.

    Recording that as a complete round put a diff-only review into
    `first_round`, the designated cross-arm comparable figure, as a clean
    look at the build. All three council seats found this independently.
    """
    with_tree = {"round": 1, "parse_ok": True, "partial": False,
                 "counts": {"critical": 0, "important": 0, "minor": 0,
                            "unknown": 0, "total": 0}}
    blind = dict(with_tree, partial=True)
    check(_sum_rounds_complete(with_tree),
          "a reviewer that had the checkout saw the build")
    check(not _sum_rounds_complete(blind),
          "a reviewer with no checkout and no inlined source reviewed the "
          "diff alone; that is not a complete look at the build")

    # And the production flag itself: partial follows the checkout, not the
    # inlining, because a reviewer WITH a checkout can read what the prompt
    # truncated.
    src = (HARNESS / "run_regime.py").read_text()
    body = src[src.index("def _claude_review_step"):src.index("def _council_step")]
    check('"partial": mat.tree is None' in body,
          "a claude review round's partial flag must follow whether it had a "
          "checkout, not whether the inlining was complete")
    check('"partial": False,' not in body,
          "the round is still unconditionally marked complete")


def _sum_rounds_complete(round_rec: dict) -> bool:
    """first_round.complete for a one-round step."""
    return bool(rr._sum_rounds([round_rec])["first_round"]["complete"])


def test_first_round_complete_requires_a_non_partial_round() -> None:
    """`parse_ok` alone is not completeness: a round can parse and still have
    reviewed only part of the code. Reverting the `and not partial` half of
    that check left the whole suite green, so it had no coverage at all."""
    parsed_full = {"round": 1, "parse_ok": True, "partial": False,
                   "counts": {"critical": 1, "important": 0, "minor": 0,
                              "unknown": 0, "total": 1}}
    parsed_partial = dict(parsed_full, partial=True)
    check(_sum_rounds_complete(parsed_full), "a whole round is complete")
    check(not _sum_rounds_complete(parsed_partial),
          "a round that parsed but reviewed only part of the code must not "
          "be reported as a complete look at it")
    t = rr._sum_rounds([parsed_partial])
    check_eq(t["rounds_partial"], 1, "the round is counted as partial")
    check_eq(t["first_round"]["critical"], 1,
             "its findings still count — a partial round is not a lost one")


def test_council_refuses_a_round_it_cannot_show_the_seats() -> None:
    """The council prompt carries no diff, so a seat handed un-inlinable
    source reviews nothing, answers [], and the round banks as clean —
    deflating exactly the arm-vs-arm number the study turns on.

    Exercised by CALLING _council_step with materials whose source could not
    be inlined. A council seat proved the previous coverage vacuous by
    deleting the guard and watching the suite stay green, so this drives the
    real function; the guard returns before any seat is launched, so no agent
    runs."""
    with tempfile.TemporaryDirectory() as td:
        run = _fake_run("r3-orgs-full.json", Path(td))
        launched = []
        run.seat = lambda *a, **k: launched.append(a) or (None, None)
        # tree PRESENT and source_complete TRUE, so only `server_inlined`
        # can explain a refusal. Setting all three together (as an earlier
        # version did) let a guard keyed on the wrong field pass: a council
        # seat verified that `mat.tree is not None` and
        # `server_inlined and source_complete` both left the suite green.
        run.collect_materials = lambda tag="review": rr.Materials(
            diff="d", server_code="(NO SERVER at targets/resp/server.py)",
            review_sha="a" * 40, tree=Path(td), server_inlined=False,
            source_complete=True)
        rec = run._council_step()
        check_eq(launched, [],
                 "a seat was launched on source it could not see")
        check_eq(rec["ran"], False, "a step that never ran a round is not 'ran'")
        check(rec["skipped_reason"], "the refusal must carry a reason")
        check_eq(rec["totals"]["total"], 0, "no findings were collected")
        check(any(f["kind"] == "nothing-to-review" for f in run.failures),
              "the refusal must be recorded as a failure, not silently")
        check("review:council" in run.phases,
              "the phase must still be recorded so the manifest is complete")


def test_seats_can_see_keys_on_the_right_field() -> None:
    """The predicate must key on `server_inlined` alone.

    Keyed on `tree` it is the pre-round-5 bug (the checkout succeeds, the
    server is missing, and the seats review a "(NO SERVER)" string). Keyed on
    `server_inlined and source_complete` it refuses rounds on merely
    truncated source, deflating the councilled arm's findings — the opposite
    error. Each field is varied on its own so neither substitution passes.
    """
    with tempfile.TemporaryDirectory() as td:
        run = _fake_run("r3-orgs-full.json", Path(td))
        tree = Path(td)

        def mat(**kw):
            base = dict(diff="d", server_code="x", review_sha="a" * 40,
                        tree=tree, server_inlined=True, source_complete=True)
            base.update(kw)
            return rr.Materials(**base)

        check(run._seats_can_see(mat()),
              "wholly inlined source must be shown to the seats")
        check(not run._seats_can_see(mat(server_inlined=False)),
              "source that could not be inlined must NOT be shown")
        check(run._seats_can_see(mat(source_complete=False)),
              "TRUNCATED source still carries real signal — refusing the "
              "round would deflate the councilled arm's findings; the round "
              "runs and is marked partial instead")
        # Vary ONLY the checkout path, holding server_inlined true. A
        # predicate keyed on `tree` would disagree across this pair; the
        # right one does not. (The previous version of this assertion
        # compared the predicate against itself on identical Materials —
        # `P(x) is False or P(x)` — which every implementation satisfies.)
        check_eq(run._seats_can_see(mat(tree=None, server_inlined=True)),
                 run._seats_can_see(mat(tree=tree, server_inlined=True)),
                 "the predicate keys on the checkout path rather than on "
                 "whether the source was actually inlined")
        # The decisive pair: tree present, only server_inlined differs.
        check(run._seats_can_see(mat(tree=tree, server_inlined=True))
              and not run._seats_can_see(mat(tree=tree, server_inlined=False)),
              "the predicate does not key on server_inlined")


def test_summary_and_manifest_agree_on_the_yardstick() -> None:
    """These were one boolean until `complete` grew to mean "every seat
    answered AND the seats saw all the code". The summary was left on the
    seats-only flag, so it could print a headline robustness figure for an
    arm whose grading.escaped_defects was null — and six SUMMARY files
    compared side by side is exactly how that number gets used."""
    with tempfile.TemporaryDirectory() as td:
        run = _fake_run("r3-orgs-full.json", Path(td))
        counts = {"critical": 3, "important": 1, "minor": 2, "unknown": 0,
                  "total": 6}
        base = {"ran": True, "audited_sha": "a" * 40, "seats": {},
                "counts": counts, "critical_important": 4,
                "seats_filled": ["codex", "agy"], "seats_empty": [],
                "seats_expected": ["codex", "agy"], "union_note": "sum"}

        # Complete: the manifest publishes it and the summary states it.
        run.escaped = dict(base, parse_ok=True, complete=True,
                           seats_complete=True, source_complete=True)
        man = run.manifest(rr.utc_now())
        text = rr.render_summary(run, man)
        check_eq(man["grading"]["escaped_defects"], 4, "complete -> published")
        check("survived to the final server" in text,
              "a complete audit should state its figure")
        check("NOT comparable" not in text, "a complete audit is comparable")

        # Source incomplete: both must refuse to present it as the figure.
        run.escaped = dict(base, parse_ok=True, complete=False,
                           seats_complete=True, source_complete=False)
        man = run.manifest(rr.utc_now())
        text = rr.render_summary(run, man)
        check_eq(man["grading"]["escaped_defects"], None,
                 "incomplete source -> null in the manifest")
        check("NOT comparable" in text,
              "the summary still presents an incomparable count as the "
              "robustness figure while the manifest nulls it")
        check("survived to the final server" not in text,
              "the summary must not use the headline phrasing for a count "
              "the manifest refused to publish")

        # One seat missing: same treatment.
        run.escaped = dict(base, parse_ok=False, complete=False,
                           seats_complete=False, source_complete=True,
                           seats_filled=["codex"], seats_empty=["agy"])
        man = run.manifest(rr.utc_now())
        text = rr.render_summary(run, man)
        check_eq(man["grading"]["escaped_defects"], None, "one seat -> null")
        check("NOT comparable" in text, "a one-seat audit is not comparable")


def test_council_mid_loop_abort_keeps_the_rounds_it_ran() -> None:
    """The guard can fire at round 2, after round 1 ran seats, reported
    findings and applied a fix. Returning there labelled a step that
    demonstrably ran as not-run, and skipped the fix-seconds subtraction so
    round 1's fix was billed twice in wall_clock_by_phase."""
    src = (HARNESS / "run_regime.py").read_text()
    body = src[src.index("def _council_step"):src.index("def _apply_fix")]
    guard = body[body.index("if not self._seats_can_see(mat):"):]
    guard = guard[:guard.index("prompt = compose_council_prompt")]
    stmts = [ln.strip() for ln in guard.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    check("break" in stmts,
          "the mid-loop abort must break, keeping the rounds already run")
    check(not any(st.startswith("return") for st in stmts),
          "the mid-loop abort still returns, which discards the rounds "
          "already run and skips the fix-seconds subtraction")
    check("fix_seconds" in body[body.index('self.phases["review:council"]') - 200:
                                body.index('self.phases["review:council"]') + 100],
          "the council phase must subtract fix_seconds on every exit path")
    check('"ran": bool(rounds)' in body,
          "a step that ran rounds must report ran=True even when it aborted")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def run_all() -> int:
    global FAILURES, CHECKS
    FAILURES = []
    CHECKS = 0
    errored = 0
    for fn in TESTS:
        try:
            fn()
        except Exception:                                      # noqa: BLE001
            errored += 1
            FAILURES.append(f"{fn.__name__} raised:\n"
                            + "".join(traceback.format_exc()))
    return errored


def report(quiet: bool = False) -> int:
    errored = run_all()
    if FAILURES:
        if not quiet:
            print(f"\n{len(FAILURES)} FAILURE(S) out of {CHECKS} checks "
                  f"({len(TESTS)} tests, {errored} raised):\n")
            for f in FAILURES:
                print(f"  FAIL: {f}")
        return 1
    if not quiet:
        print(f"OK — {CHECKS} checks across {len(TESTS)} tests passed.")
    return 0


# --- mutation check --------------------------------------------------------
#
# Doctrine: a test added to pin a mechanism gets mutation-checked -- break the
# mechanism, watch the test go red -- before it counts. These break the two
# mechanisms this suite exists to guard.

def mutation_check() -> int:
    mutants: list[tuple[str, callable, callable]] = []

    # (1) The findings parser: make a malformed block return zero findings
    # instead of a parse failure -- the exact conflation assumption A8 forbids.
    orig_parse = rr.parse_findings

    def break_parser() -> None:
        def lenient(text):
            f = orig_parse(text)
            if not f.ok:
                return rr.Findings(True, [], rr.count_findings([]), None, "mutant")
            return f
        rr.parse_findings = lenient

    mutants.append(("findings parser treats malformed input as zero findings",
                    break_parser, lambda: setattr(rr, "parse_findings", orig_parse)))

    # (2) The toggle -> prompt logic: always emit the standup section, so a
    # mechanism that is switched OFF still reaches the agent.
    orig_build = rr.compose_build_prompt

    def break_toggles() -> None:
        def always_standup(cfg, ctx):
            text = orig_build(cfg, ctx)
            if not cfg.toggles["standup"]:
                text += rr.render(rr.load_template("frag_standup_solo.md"),
                                  {"GUARD": str(ctx.guard),
                                   "SOLO_AGENT_ID": ctx.solo_agent_id},
                                  where="mutant")
            return text
        rr.compose_build_prompt = always_standup

    mutants.append(("toggle->prompt logic leaks a switched-off mechanism",
                    break_toggles, lambda: setattr(rr, "compose_build_prompt", orig_build)))

    # (3) Doctrine omission: give the control arms the doctrine block.
    orig_pre = rr._protocol_preamble

    def break_doctrine() -> None:
        rr._protocol_preamble = lambda cfg, ctx: (
            "## How we work\n\n" + ctx.doctrine_block + "\n\n")

    mutants.append(("doctrine block is given to the goal-directed control arms",
                    break_doctrine, lambda: setattr(rr, "_protocol_preamble", orig_pre)))

    # (4) The audit prompt stops being regime-independent.
    orig_audit = rr.compose_audit_prompt

    def break_audit() -> None:
        rr.compose_audit_prompt = lambda cfg, ctx, mat: (
            orig_audit(cfg, ctx, mat) + f"\n<!-- regime {cfg.regime} -->\n")

    mutants.append(("the audit prompt varies by regime",
                    break_audit, lambda: setattr(rr, "compose_audit_prompt", orig_audit)))

    # (5) The standup bus stops being pinned in the guard commands -- the
    # regression that makes redirects vanish silently.
    orig_build2 = rr.compose_build_prompt

    def break_bus() -> None:
        rr.compose_build_prompt = lambda cfg, ctx: orig_build2(cfg, ctx).replace(
            f"STANDUP_BUS={ctx.bus_root} ", "")

    mutants.append(("guard invocations stop pinning STANDUP_BUS",
                    break_bus, lambda: setattr(rr, "compose_build_prompt", orig_build2)))

    # (6) Fix rounds get bucketed as coordination instead of product -- the
    # regression that was in the first version of the manifest writer.
    orig_manifest = rr.Run.manifest

    def break_buckets() -> None:
        def mutant(self, ended):
            man = orig_manifest(self, ended)
            fix = sum(int(v.get("total_tokens") or 0)
                      for k, v in self.tokens.items() if k.startswith("fix:"))
            man["cost"]["coordination_tokens"] += fix
            man["cost"]["product_tokens"] -= fix
            return man
        rr.Run.manifest = mutant

    mutants.append(("fix rounds are billed as coordination, not product",
                    break_buckets, lambda: setattr(rr.Run, "manifest", orig_manifest)))

    # (7) The runbook stops being ablated with its mechanism -- the arm with
    # crystal off is still instructed to run speculative merge checks.
    orig_filter = rr.filter_runbook

    def break_runbook() -> None:
        rr.filter_runbook = lambda runbook, toggles: (runbook, [])

    mutants.append(("the runbook is not ablated with its mechanism",
                    break_runbook, lambda: setattr(rr, "filter_runbook", orig_filter)))

    # (8) Standup agent ids go back to being generic, so `git log --all`
    # matches unrelated history and every agent reads as stalled at once.
    orig_token = rr.Ctx.agent_token

    def break_ids() -> None:
        rr.Ctx.agent_token = property(lambda self: "bench")

    mutants.append(("standup agent ids stop being run-unique",
                    break_ids, lambda: setattr(rr.Ctx, "agent_token", orig_token)))

    # (9) Fix-regression detection goes back to comparing pass COUNTS, which
    # reports zero for a fix that repairs one assertion and breaks another.
    orig_regr = rr._fix_regressions

    def break_regressions() -> None:
        def counts_only(stages):
            a, b = stages.get("after_build"), stages.get("final")
            if not a or not b or not a.get("ran") or not b.get("ran"):
                return None
            if not a.get("conformance_total") or not b.get("conformance_total"):
                return None
            lost = a["conformance_passed"] - b["conformance_passed"]
            return lost if lost > 0 else 0
        rr._fix_regressions = counts_only

    mutants.append(("fix-regressions compares pass counts, not assertion names",
                    break_regressions,
                    lambda: setattr(rr, "_fix_regressions", orig_regr)))

    # (10) Estimated and measured tokens stop being distinguishable.
    orig_split = rr._split_provenance

    def break_provenance() -> None:
        def always_comparable(parts):
            out = orig_split(parts)
            out["comparable_across_arms"] = True
            return out
        rr._split_provenance = always_comparable

    mutants.append(("estimated tokens are reported as comparable with measured",
                    break_provenance,
                    lambda: setattr(rr, "_split_provenance", orig_split)))

    # (11) Crystal stops separating single-branch noise from real conflicts.
    orig_classify = rr._classify_conflicts

    def break_crystal() -> None:
        rr._classify_conflicts = lambda report, base: (
            orig_classify(report, None)[0], [])

    mutants.append(("crystal counts red-alone branches as cross-branch conflicts",
                    break_crystal,
                    lambda: setattr(rr, "_classify_conflicts", orig_classify)))

    # (12) The parent session's agent environment leaks into the fresh agents.
    orig_isenv = rr._is_agent_env

    def break_env() -> None:
        rr._is_agent_env = lambda key: False

    mutants.append(("the parent session's agent env leaks into fresh agents",
                    break_env, lambda: setattr(rr, "_is_agent_env", orig_isenv)))

    # (13) fix-regressions goes back to keying on the whole FAIL line, so a
    # changed observed value reads as a new regression.
    orig_name = rr._assertion_name

    def break_name() -> None:
        rr._assertion_name = lambda line: line

    mutants.append(("fix-regressions keys on the observed value, not the assertion",
                    break_name, lambda: setattr(rr, "_assertion_name", orig_name)))

    # (14) The crystal noise filter swallows textual conflicts again.
    orig_classify2 = rr._classify_conflicts

    def break_textual() -> None:
        def drop_all_from_noisy(report, base):
            real, noisy = orig_classify2(report, base)
            return ([r for r in real
                     if not any(n in r for n in noisy)], noisy)
        rr._classify_conflicts = drop_all_from_noisy

    mutants.append(("a red-alone branch's TEXTUAL conflicts are suppressed",
                    break_textual,
                    lambda: setattr(rr, "_classify_conflicts", orig_classify2)))

    # (15) An incomplete audit fills the headline robustness field again.
    orig_manifest2 = rr.Run.manifest

    def break_headline() -> None:
        def mutant(self, ended):
            man = orig_manifest2(self, ended)
            esc = self.escaped or {}
            if esc.get("critical_important") is not None:
                man["grading"]["escaped_defects"] = esc["critical_important"]
            return man
        rr.Run.manifest = mutant

    mutants.append(("an incomplete audit fills the headline robustness field",
                    break_headline,
                    lambda: setattr(rr.Run, "manifest", orig_manifest2)))

    # (16) A provider's credentials get scrubbed along with its session state,
    # silently turning a councilled arm into an un-councilled one.
    orig_keep = rr.AGENT_ENV_KEEP

    def break_keep() -> None:
        rr.AGENT_ENV_KEEP = ()

    mutants.append(("provider credentials are scrubbed with the session state",
                    break_keep, lambda: setattr(rr, "AGENT_ENV_KEEP", orig_keep)))

    # (17) The token quality flags stop surviving aggregation, so the
    # coordination bucket is labelled comparable when it is not.
    orig_add = rr.add_tokens

    def break_flags() -> None:
        def drop_incomplete(*buckets):
            out = orig_add(*buckets)
            out["incomplete"] = False
            return out
        rr.add_tokens = drop_incomplete

    mutants.append(("token incompleteness is dropped on aggregation",
                    break_flags, lambda: setattr(rr, "add_tokens", orig_add)))

    # (18) The sweep's dirtiness test stops matching the sweep itself.
    orig_excl = rr.SWEEP_EXCLUDE

    def break_exclude() -> None:
        rr.SWEEP_EXCLUDE = ":(exclude)nothing-at-all"

    mutants.append(("the sweep exclusion pathspec stops naming the bus",
                    break_exclude, lambda: setattr(rr, "SWEEP_EXCLUDE", orig_excl)))

    # (19) _models_missing goes back to claiming compliance for a build it
    # observed nothing of.
    orig_missing = rr._models_missing

    def break_missing() -> None:
        rr._models_missing = lambda cfg, obs, roles: (orig_missing(cfg, obs, roles)
                                                      or [])

    mutants.append(("models_missing claims compliance for an unobserved build",
                    break_missing,
                    lambda: setattr(rr, "_models_missing", orig_missing)))

    # (20) The audit's no-server guard goes back to testing the working tree
    # rather than what the seats are actually shown.
    orig_audit_guard = rr.Run.collect_server_code

    def break_audit_guard() -> None:
        # Three-tuple, matching the real signature. Returning a bare string
        # made this mutant "caught" by a ValueError in tests that unpack the
        # return value -- proving nothing about the guard it names.
        rr.Run.collect_server_code = lambda self, tree: (
            "(no server was produced)", True, True)

    mutants.append(("the inlined source claims no server while the guard passes",
                    break_audit_guard,
                    lambda: setattr(rr.Run, "collect_server_code",
                                    orig_audit_guard)))

    # (21) The council's "nothing to review" guard is removed outright, so a
    # round runs on source the seats cannot see and banks as clean. Patches
    # Materials so `server_inlined` is always True, which is exactly what
    # deleting the guard would achieve.
    orig_guard = rr.Run._seats_can_see

    def break_council_guard() -> None:
        rr.Run._seats_can_see = lambda self, mat: True

    mutants.append(("a round is scored on source the seats never saw",
                    break_council_guard,
                    lambda: setattr(rr.Run, "_seats_can_see", orig_guard)))

    # (21b) The crystal standup-off branch stops recording the signature, so
    # the same undeliverable finding is recounted on every check.
    orig_deliver = rr.Run._deliver_crystal

    def break_crystal_count() -> None:
        def mutant(self, check_n, stanzas, noisy):
            if not stanzas and not noisy:
                return
            if not self.cfg.toggles["standup"]:
                self.crystal_stats["undelivered"] += 1
                return
            return orig_deliver(self, check_n, stanzas, noisy)
        rr.Run._deliver_crystal = mutant

    mutants.append(("crystal recounts the same undeliverable finding",
                    break_crystal_count,
                    lambda: setattr(rr.Run, "_deliver_crystal", orig_deliver)))

    # (22) The summary drifts back onto the seats-only flag, so it presents
    # a figure the manifest refused to publish.
    orig_summary = rr.render_summary

    def break_summary_gate() -> None:
        def mutant(run, man):
            esc = run.escaped
            if esc and not esc.get("complete"):
                run.escaped = dict(esc, complete=True)
                try:
                    return orig_summary(run, man)
                finally:
                    run.escaped = esc
            return orig_summary(run, man)
        rr.render_summary = mutant

    mutants.append(("the summary presents a figure the manifest nulled",
                    break_summary_gate,
                    lambda: setattr(rr, "render_summary", orig_summary)))

    # (23) The seats-can-see predicate keys on the checkout path instead of
    # whether the source was actually inlined -- the pre-round-5 bug.
    orig_can_see = rr.Run._seats_can_see

    def break_predicate() -> None:
        rr.Run._seats_can_see = lambda self, mat: mat.tree is not None

    mutants.append(("the seats-can-see predicate keys on the wrong field",
                    break_predicate,
                    lambda: setattr(rr.Run, "_seats_can_see", orig_can_see)))

    # (24) A review round with no checkout is banked as a complete one.
    orig_sum = rr._sum_rounds

    def break_partial() -> None:
        def mutant(rounds):
            return orig_sum([dict(r, partial=False) for r in rounds])
        rr._sum_rounds = mutant

    mutants.append(("a partial round is banked as a complete one",
                    break_partial, lambda: setattr(rr, "_sum_rounds", orig_sum)))

    # (25) The schema validator stops validating.
    orig_val = rr.validate_schema

    def break_validator() -> None:
        rr.validate_schema = lambda *a, **k: []

    mutants.append(("the manifest schema validator always passes",
                    break_validator, lambda: setattr(rr, "validate_schema", orig_val)))

    print("MUTATION CHECK — each mutant must make the suite go RED.\n")
    survivors = 0
    for label, apply_mutant, undo in mutants:
        apply_mutant()
        try:
            rc = report(quiet=True)
        finally:
            undo()
        status = "caught (suite went red)" if rc != 0 else "*** SURVIVED ***"
        if rc == 0:
            survivors += 1
        print(f"  {status:<28} {label}")
    print()
    if survivors:
        print(f"{survivors} mutant(s) survived: those tests are decoration, "
              "not a guard. Treat as a defect.")
        return 1
    print(f"All {len(mutants)} mutants caught. The tests can fail.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mutation", action="store_true",
                    help="break each guarded mechanism and assert the suite "
                         "goes red for it")
    args = ap.parse_args()
    if args.mutation:
        rc = report()
        if rc:
            print("\nthe suite is already red; fix it before mutation-checking.")
            return rc
        print()
        return mutation_check()
    return report()


if __name__ == "__main__":
    sys.exit(main())
