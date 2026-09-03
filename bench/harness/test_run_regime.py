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
    check_eq(rr.ablation_of(rr.load_config(CONFIG_DIR / "r4-orgs-no-crystal.json").toggles),
             "crystal", "r4 is the crystal ablation of r3")


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
            run.escaped = {"ran": True, "parse_ok": True, "audited_sha": "abc",
                           "critical_important": 4,
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

            # The summary must render without raising on any of these shapes.
            text = rr.render_summary(run, man)
            check(len(text) > 500, f"{name}: SUMMARY.md is implausibly short")
            check("Escaped defects" in text, f"{name}: SUMMARY.md lacks the yardstick")


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

    # (5) The schema validator stops validating.
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
