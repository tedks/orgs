#!/usr/bin/env python3
"""run_regime.py — drive ONE complete, isolated benchmark run end to end.

Reads a regime config (bench/regimes/configs/*.json), composes the role
prompts its toggles select, launches the build headless, runs the configured
review steps, grades against the frozen exam, runs the escaped-defect audit,
and writes an immutable manifest plus a human-readable summary.

No human in the loop. Python 3 standard library only.

    run_regime.py --config bench/regimes/configs/protocol-full.json
    run_regime.py --config bench/regimes/configs/raw.json --dry-run

=============================================================================
ASSUMPTIONS — stated before the machinery, per doctrine. Each one is a way
this harness can be wrong; none of them is silently relied on.
=============================================================================

A1. `claude -p --output-format json` shape.
    VERIFIED EMPIRICALLY on Claude Code 2.1.259 (2026-09-03): the CLI writes a
    JSON **array** of stream events whose LAST element is the `{"type":
    "result", ...}` object -- not the single object the docs describe. Other
    versions emit that single object, and some emit JSON Lines. All three are
    parsed (see `parse_claude_result`); an unrecognised shape is recorded as a
    failure, never guessed at.

A2. Which usage field is the cumulative one.
    VERIFIED on the same probe: the result event carries BOTH `usage` (the
    LAST turn only -- 9 input tokens on a one-turn probe) and `modelUsage`
    (the per-model aggregate for the whole session -- 908 input tokens for the
    same probe). For an agentic build of hundreds of turns those differ by
    orders of magnitude, so `modelUsage` is summed and `usage` is only a
    fallback. Both, and which was used, are recorded.

A3. Foreign council seats report no token usage.
    `agent-query.sh` yields the reply text and nothing else. Their tokens are
    ESTIMATED as (len(prompt) + len(reply)) // 4 characters-per-token and
    every such number is flagged `"estimated": true`. Do not compare an
    estimated figure with a measured one without saying so.

A4. The manifest schema had to be extended, additively.
    The frozen schema is `additionalProperties: false` with `regime` limited
    to raw|native|protocol, so it could not express six named regimes or the
    new per-step metrics. Rather than widen `regime` (which would change the
    meaning of an existing field), the coarse three-value class is DERIVED
    (`coarse_regime`) and the config's own label rides in the new
    `regime_name`. New fields are additions only; no existing field changed
    meaning. The manifest is validated against the schema before it is
    written, so this stays true.

A5. The exam that grades a run is the PRISTINE copy in the framework
    worktree, never the run tree's -- the org does not grade itself. The run
    tree's copy is hashed against it and any difference is recorded as
    `exam_tampered`, which is evidence, not an error.

A6. Crystal's default boundary-test command is `python3 -m compileall -q
    <server dir>`: stdlib only, and it does not need a git repository (a
    test command that does is out of scope for crystal v0 and would report
    noise). It catches a merge that does not parse, not a semantic conflict.
    Set `crystal.test_cmd` in the config to get a real boundary check.

A7. Council findings are NOT deduplicated across seats. `union` is the SUM
    across seats; two seats reporting the same defect count twice. Semantic
    matching across providers is not something this harness can do honestly,
    so it does not pretend to.

A8. A findings block that fails to parse is NOT zero findings. Counts are
    `null` for that round and `parse_ok` is false. Conflating the two would
    silently deflate the benchmark's primary metric.

A9. Cost buckets follow RUNBOOK §8: coordination = the review seats (native,
    lead, cto, council); product = the build and any fix rounds (a fix round
    is implementer work, as a takeover is). The escaped-defect AUDIT is
    excluded from both -- it is the measuring instrument, not work the org
    did -- and appears only in `tokens_by_phase`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# --------------------------------------------------------------------------
# Paths and defaults
# --------------------------------------------------------------------------

HARNESS_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = HARNESS_DIR / "prompts"
DEFAULT_FRAMEWORK = HARNESS_DIR.parent.parent          # .../framework
DEFAULT_RUNS_ROOT = Path("/home/tedks/Projects/orgs/bench-runs")
DEFAULT_ASK_AGENT = Path.home() / ".claude/skills/ask-agent/scripts/agent-query.sh"

# The canonical mechanism vector. Two config vocabularies are in use and both
# are accepted (see `load_config`):
#
#   * the regimes-README shape, with a single `review` toggle covering the
#     internal review ladder (bench/regimes/configs/{raw,protocol-full,no-*});
#   * the study shape, which splits that ladder into `review_native`,
#     `review_lead` and `review_cto` (bench/regimes/configs/r{1..6}-*).
#
# Everything downstream sees the split form; `review` survives as a derived
# convenience (true when any rung is on) so the coarse regime class and the
# ablation name can still be computed.
CANONICAL_TOGGLES = (
    "decomposition", "firewall", "tiering", "parallel",
    "standup", "crystal", "council",
    "review_native", "review_lead", "review_cto",
)
MECHANISM_TOGGLES = ("decomposition", "firewall", "tiering", "parallel",
                     "standup", "crystal", "council")
REVIEW_TOGGLES = ("review_native", "review_lead", "review_cto")
TOGGLE_KEYS = CANONICAL_TOGGLES        # display order

# Top-level config keys this harness understands. Unknown keys are REJECTED
# rather than ignored: a config that sets `timeout_minute` (or any other near
# miss) and is silently given the default is how a study arm ends up measuring
# something nobody intended.
KNOWN_CONFIG_KEYS = {
    "regime", "target", "toggles", "models", "grader", "budget_tokens",
    "notes", "doctrine",
    # timing, both spellings
    "timeouts", "timeout_minutes",
    "standup", "standup_interval_min",
    "crystal", "crystal_interval_min",
    "review_steps", "max_rounds", "max_review_rounds",
    # target overrides
    "server_path", "spec_path", "worker_ids", "target_desc",
}

DEFAULT_TIMEOUTS = {
    "build_s": 7200,     # the agentic build; the only genuinely long phase
    "review_s": 2400,
    "fix_s": 2400,
    "council_s": 2400,
    "grade_s": 900,
    "crystal_s": 900,
    "standup_s": 300,
    "git_s": 300,
}

DEFAULT_STANDUP = {
    "interval_s": 300,          # how often to observe
    "stall_min": 15,            # minutes without a commit before a stall flag
    "redirect_cooldown_s": 900, # do not re-redirect the same agent faster
}

DEFAULT_CRYSTAL = {
    "interval_s": 600,
    "timeout_s": 120,           # passed to crystal-check.sh --timeout
    "test_cmd": None,           # None -> derived compileall on the server dir
}

# Review steps, in the order they run. Council sits at the implementer's tier
# per RUNBOOK §6 (self-review, council, one-rung-up), so it runs before lead.
REVIEW_STEP_ORDER = ("native", "council", "lead", "cto")

DEFAULT_MAX_ROUNDS = {"native": 2, "council": 2, "lead": 1, "cto": 1}

# What each target is, where its product lands, and how it decomposes. A
# config may override any of these; an unknown target must supply them all.
TARGET_DEFAULTS: dict[str, dict[str, Any]] = {
    "resp": {
        "server_path": "targets/resp/server.py",
        "spec_path": "docs/specs/2026-09-02-resp-tracer.md",
        "worker_ids": ["codec", "engine", "server"],
        "target_desc": "minimal Redis-compatible server speaking the RESP2 wire protocol",
    },
}

# Severity vocabulary. Reviewers are told to emit Critical/Important/Minor;
# foreign seats say "High"/"Major"/"Low" anyway, so they are mapped. Anything
# unrecognised becomes "unknown" and is counted SEPARATELY -- never folded
# into minor, where it would vanish from the metric that matters.
SEVERITY_MAP = {
    "critical": "critical", "crit": "critical", "blocker": "critical",
    "severe": "critical", "fatal": "critical",
    "important": "important", "high": "important", "major": "important",
    "significant": "important",
    "minor": "minor", "medium": "minor", "moderate": "minor", "low": "minor",
    "nit": "minor", "nitpick": "minor", "info": "minor",
    "informational": "minor", "trivial": "minor", "style": "minor",
}
SEVERITY_BUCKETS = ("critical", "important", "minor", "unknown")

# Caps on material inlined into a prompt. A runaway diff must not produce a
# prompt no model can read; truncation is announced in the text so a reviewer
# knows it is seeing part of the picture.
DIFF_CAP = 400_000
CODE_CAP = 300_000
LOG_READ_CAP = 64 * 1024 * 1024   # refuse to parse an agent log larger than this


class ConfigError(Exception):
    """The regime config is unusable. Always fatal, always before any spend."""


class PromptError(Exception):
    """A template and its values disagree. Always fatal: a prompt with a hole
    in it is worse than no run at all."""


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(dt: datetime) -> str:
    """Compact UTC stamp for ids and branch names: 2026-09-03T0915Z."""
    return dt.strftime("%Y-%m-%dT%H%MZ")


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_text(path: Path, *, cap: int | None = None) -> str:
    data = path.read_text(encoding="utf-8", errors="replace")
    if cap is not None and len(data) > cap:
        return data[:cap] + f"\n\n[... truncated at {cap} characters ...]\n"
    return data


def truncate(text: str, cap: int, label: str) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n\n[... {label} truncated at {cap} of {len(text)} characters ...]\n"


@dataclass
class Proc:
    """The result of one subprocess. Nothing here is swallowed: a timeout, a
    nonzero status and a spawn failure are all distinguishable afterwards."""
    argv: list[str]
    returncode: int | None
    timed_out: bool
    duration_s: float
    stdout_path: str | None
    stderr_path: str | None
    spawn_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.spawn_error is None and not self.timed_out and self.returncode == 0

    def summary(self) -> dict:
        return {
            "argv": self.argv,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 3),
            "stdout": self.stdout_path,
            "stderr": self.stderr_path,
            "spawn_error": self.spawn_error,
        }


def _kill_tree(proc: subprocess.Popen) -> None:
    """SIGTERM the child's process GROUP, then SIGKILL what survives.

    The group, not the process: an agent CLI spawns children (a test run, a
    server it started), and killing only the parent leaves them running,
    holding ports and billing tokens. `start_new_session=True` at spawn is
    what makes the group ours to kill.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        return
    for sig, grace in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.2)


def run_capture(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    stdin_data: str | None = None,
    env: dict[str, str] | None = None,
) -> Proc:
    """Run a command with a hard timeout, streaming output to files.

    Output goes to files rather than pipes so an agent that emits hundreds of
    megabytes cannot be buffered into this process's memory. Every subprocess
    in this harness goes through here, so every subprocess has a timeout --
    that is the point of the single chokepoint.
    """
    t0 = time.time()
    so = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
    se = open(stderr_path, "wb") if stderr_path else subprocess.DEVNULL
    proc_env = dict(os.environ)
    if env:
        proc_env.update(env)
    try:
        try:
            p = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                stdout=so,
                stderr=se,
                start_new_session=True,
                env=proc_env,
            )
        except OSError as exc:
            return Proc(argv, None, False, time.time() - t0,
                        str(stdout_path) if stdout_path else None,
                        str(stderr_path) if stderr_path else None,
                        spawn_error=f"{type(exc).__name__}: {exc}")
        timed_out = False
        try:
            p.communicate(
                input=stdin_data.encode("utf-8") if stdin_data is not None else None,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(p)
            try:
                p.communicate(timeout=30)
            except Exception:      # noqa: BLE001 - best effort reaping only
                pass
        except BrokenPipeError:
            # The child exited before reading the prompt. Its status still
            # tells the story; do not lose it to an exception here.
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _kill_tree(p)
        return Proc(argv, p.returncode, timed_out, time.time() - t0,
                    str(stdout_path) if stdout_path else None,
                    str(stderr_path) if stderr_path else None)
    finally:
        for h in (so, se):
            if hasattr(h, "close"):
                h.close()


def git(args: list[str], *, cwd: Path, timeout: float) -> tuple[int, str, str]:
    """Run a small, bounded git command and capture its output in memory.

    Only for commands whose output is known-small (rev-parse, worktree add,
    for-each-ref). `git diff` goes through here too and is capped by the
    caller; a diff large enough to matter is already a finding.
    """
    try:
        cp = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True,
            text=True, errors="replace", timeout=timeout,
        )
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)}: timed out after {timeout}s"
    except OSError as exc:
        return 127, "", f"git {' '.join(args)}: {type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@dataclass
class Config:
    path: Path
    regime: str
    target: str
    toggles: dict[str, bool]
    models: dict[str, str]
    grader: str
    budget_tokens: int | None
    timeouts: dict[str, float]
    standup: dict[str, Any]
    crystal: dict[str, Any]
    steps: dict[str, bool]          # native / council / lead / cto
    max_rounds: dict[str, int]
    server_path: str
    spec_path: str
    worker_ids: list[str]
    target_desc: str
    doctrine: bool
    raw: dict[str, Any]

    @property
    def pure_raw(self) -> bool:
        """No mechanism at all -- the null control. Spec and goal, nothing
        else."""
        return not any(self.toggles[k] for k in CANONICAL_TOGGLES)

    @property
    def builder_role(self) -> str:
        return "lead" if self.toggles["decomposition"] else "implementer"

    @property
    def builder_model(self) -> str:
        return self.models[self.builder_role]


def default_doctrine(toggles: dict[str, bool]) -> bool:
    """Does the build agent carry the doctrine prompt block?

    Doctrine is a protocol artifact: an org role carries it, a bare
    goal-directed build does not, and handing it to a baseline arm would
    contaminate the very thing that arm is the control for. The line that
    separates the study's `goal-*` regimes from its `orgs-*` regimes is drawn
    by the mechanisms themselves rather than by the regime's name: a run with
    no decomposition AND no one-rung-up review is goal-directed, whatever it
    is called. Override with `"doctrine": true|false` in the config.
    """
    return bool(toggles["decomposition"] or toggles["review_lead"]
                or toggles["review_cto"])


def _require_bool(d: dict, key: str, where: str) -> bool:
    if key not in d:
        raise ConfigError(f"{where}: missing toggle '{key}' "
                          "(every toggle must be explicit -- an ablation that "
                          "silently defaults is not an ablation)")
    v = d[key]
    if not isinstance(v, bool):
        raise ConfigError(f"{where}: toggle '{key}' must be true or false, got {v!r}")
    return v


MODEL_ROLES = ("cto", "lead", "worker", "implementer", "review_tier", "fix")


def effective_models(models: dict[str, str], toggles: dict[str, bool]) -> dict[str, str]:
    """Resolve role -> model, collapsing tiers when `tiering` is off.

    tiering off means "one strong model does everything" (regimes README), so
    every role gets the same model: `models.no_tier_model` if given, else the
    lead's, else the cto's, else the worker's. That is what makes
    `no-tiering` an ablation rather than a relabelling.

    `implementer` is the solo builder's role, distinct from `worker` (the
    tier a lead delegates DOWN to). A goal-directed regime builds at
    implementer tier; conflating the two would quietly run the baseline arms
    on a cheaper model than intended.
    """
    out = {k: v for k, v in models.items() if v}
    if not toggles["tiering"]:
        strong = (out.get("no_tier_model") or out.get("lead")
                  or out.get("cto") or out.get("implementer") or out.get("worker"))
        if not strong:
            raise ConfigError("tiering is off but no model is named "
                              "(need one of no_tier_model/lead/cto/implementer/worker)")
        for role in MODEL_ROLES:
            out[role] = strong
        return out
    worker = out.get("worker") or out.get("implementer") or out.get("lead") or out.get("cto")
    lead = out.get("lead") or out.get("cto") or worker
    if not worker or not lead:
        raise ConfigError("models: need at least one of worker/implementer/lead/cto")
    out.setdefault("worker", worker)
    out.setdefault("lead", lead)
    out.setdefault("cto", lead)
    out.setdefault("implementer", out.get("implementer") or lead)
    out.setdefault("review_tier", worker)
    # A fix round is implementer work, so it runs at whichever tier built the
    # thing -- the lead's worker tier under decomposition, the solo
    # implementer's tier otherwise.
    out.setdefault("fix", out["worker"] if toggles["decomposition"] else out["implementer"])
    return out


def _parse_toggles(raw_toggles: dict, where: str) -> dict[str, bool]:
    """Accept either review vocabulary and return the canonical vector.

    The two spellings are mutually exclusive on purpose: a config carrying
    both `review` and `review_lead` has two answers to the same question, and
    guessing which one the author meant is how an ablation silently stops
    ablating.
    """
    have_split = [k for k in REVIEW_TOGGLES if k in raw_toggles]
    have_legacy = "review" in raw_toggles
    if have_split and have_legacy:
        raise ConfigError(
            f"{where}: toggles carry both 'review' and {sorted(have_split)}; "
            "use one vocabulary or the other, never both")
    if not have_split and not have_legacy:
        raise ConfigError(
            f"{where}: no review toggle at all -- give either 'review' or all "
            f"of {list(REVIEW_TOGGLES)}")

    known = set(MECHANISM_TOGGLES) | set(REVIEW_TOGGLES) | {"review"}
    unknown = set(raw_toggles) - known
    if unknown:
        raise ConfigError(f"{where}: unknown toggle(s) {sorted(unknown)} -- "
                          "a misspelled toggle silently changes nothing, which "
                          "is the worst outcome for an ablation")

    out: dict[str, bool] = {}
    for key in MECHANISM_TOGGLES:
        out[key] = _require_bool(raw_toggles, key, where)
    if have_legacy:
        # The single `review` toggle is the internal ladder: a fresh
        # same-tier reviewer plus the one-rung-up lead review (RUNBOOK §6
        # steps 1-3 minus the council seat). The CTO rung is not implied by
        # it -- no existing toggle ever meant that -- so it stays off unless
        # named.
        rv = _require_bool(raw_toggles, "review", where)
        out["review_native"] = rv
        out["review_lead"] = rv
        out["review_cto"] = False
    else:
        missing = [k for k in REVIEW_TOGGLES if k not in raw_toggles]
        if missing:
            raise ConfigError(f"{where}: split review vocabulary is missing "
                              f"{missing} -- every rung must be explicit")
        for key in REVIEW_TOGGLES:
            out[key] = _require_bool(raw_toggles, key, where)
    out["review"] = any(out[k] for k in REVIEW_TOGGLES)
    return out


def load_config(path: Path) -> Config:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config {path}: top level must be an object")

    where = str(path)
    for key in ("regime", "target", "toggles", "models"):
        if key not in raw:
            raise ConfigError(f"{where}: missing required key '{key}'")
    if not isinstance(raw["toggles"], dict):
        raise ConfigError(f"{where}: 'toggles' must be an object")
    if not isinstance(raw["models"], dict):
        raise ConfigError(f"{where}: 'models' must be an object")

    unknown_top = set(raw) - KNOWN_CONFIG_KEYS
    if unknown_top:
        raise ConfigError(f"{where}: unknown top-level key(s) "
                          f"{sorted(unknown_top)} -- refusing to ignore a "
                          "setting that was meant to change the run")

    toggles = _parse_toggles(raw["toggles"], where)
    models = effective_models({str(k): str(v) for k, v in raw["models"].items()},
                              toggles)

    target = str(raw["target"])
    tdefaults = TARGET_DEFAULTS.get(target, {})
    def tget(key: str) -> Any:
        if key in raw:
            return raw[key]
        if key in tdefaults:
            return tdefaults[key]
        raise ConfigError(f"{where}: target '{target}' is unknown to this harness, "
                          f"so the config must supply '{key}'")

    def _positive(value: Any, label: str) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ConfigError(f"{where}: {label} must be a positive number, "
                              f"got {value!r}")
        return float(value)

    timeouts = dict(DEFAULT_TIMEOUTS)
    # `timeout_minutes` is the study configs' spelling of the per-run build
    # budget. It sets the build phase only; the review and grading phases have
    # their own bounds and are not what "the run timed out" means.
    if "timeout_minutes" in raw:
        timeouts["build_s"] = _positive(raw["timeout_minutes"], "timeout_minutes") * 60
    for k, v in (raw.get("timeouts") or {}).items():
        if k not in DEFAULT_TIMEOUTS:
            raise ConfigError(f"{where}: unknown timeout '{k}'")
        timeouts[k] = _positive(v, f"timeout '{k}'")

    standup = dict(DEFAULT_STANDUP)
    if "standup_interval_min" in raw:
        standup["interval_s"] = _positive(raw["standup_interval_min"],
                                          "standup_interval_min") * 60
    standup.update(raw.get("standup") or {})
    crystal = dict(DEFAULT_CRYSTAL)
    if "crystal_interval_min" in raw:
        crystal["interval_s"] = _positive(raw["crystal_interval_min"],
                                          "crystal_interval_min") * 60
    crystal.update(raw.get("crystal") or {})

    # Review steps. `review` in the toggle surface is the internal review
    # ladder (RUNBOOK §6 steps 1-3 minus the council seat); it turns on both
    # the fresh same-tier reviewer and the one-rung-up lead review. The CTO
    # rung is opt-in -- no existing toggle implies it. `council` is its own
    # toggle because provider diversity is the hypothesised keystone.
    rs = raw.get("review_steps") or {}
    if not isinstance(rs, dict):
        raise ConfigError(f"{where}: 'review_steps' must be an object")
    unknown_rs = set(rs) - set(REVIEW_STEP_ORDER)
    if unknown_rs:
        raise ConfigError(f"{where}: unknown review_steps key(s) {sorted(unknown_rs)}")
    steps = {
        "native": bool(rs.get("native", toggles["review_native"])),
        "lead": bool(rs.get("lead", toggles["review_lead"])),
        "cto": bool(rs.get("cto", toggles["review_cto"])),
        "council": bool(rs.get("council", toggles["council"])),
    }

    max_rounds = dict(DEFAULT_MAX_ROUNDS)
    if "max_review_rounds" in raw:
        n = raw["max_review_rounds"]
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ConfigError(f"{where}: max_review_rounds must be an integer >= 1")
        max_rounds = {k: n for k in DEFAULT_MAX_ROUNDS}
    for k, v in (raw.get("max_rounds") or {}).items():
        if k not in DEFAULT_MAX_ROUNDS:
            raise ConfigError(f"{where}: unknown max_rounds key '{k}'")
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise ConfigError(f"{where}: max_rounds '{k}' must be an integer >= 1")
        max_rounds[k] = v

    worker_ids = [str(x) for x in tget("worker_ids")]
    if toggles["decomposition"] and not worker_ids:
        raise ConfigError(f"{where}: decomposition is on but worker_ids is empty")
    for wid in worker_ids:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", wid):
            raise ConfigError(f"{where}: worker id {wid!r} must be lowercase "
                              "[a-z0-9._-] -- it becomes a branch name, a "
                              "directory name and a standup bus agent id")

    return Config(
        path=path,
        regime=str(raw["regime"]),
        target=target,
        toggles=toggles,
        models=models,
        grader=str(raw.get("grader") or f"bench/conformance/{target}_conformance.sh"),
        budget_tokens=raw.get("budget_tokens"),
        timeouts=timeouts,
        standup=standup,
        crystal=crystal,
        steps=steps,
        max_rounds=max_rounds,
        server_path=str(tget("server_path")),
        spec_path=str(tget("spec_path")),
        worker_ids=worker_ids,
        target_desc=str(tget("target_desc")),
        doctrine=bool(raw.get("doctrine", default_doctrine(toggles))),
        raw=raw,
    )


def coarse_regime(toggles: dict[str, bool]) -> str:
    """Map the toggle vector onto the frozen schema's three-value `regime`.

    The schema predates named regimes and cannot be widened without changing
    what an existing field means (A4), so the class is derived and the
    config's own label rides in `regime_name`:

      raw      -- no decomposition, no review, no council: the control arm.
      native   -- a lead fans out, but with no protocol artifacts at all.
      protocol -- anything carrying protocol machinery, ablated or not.
    """
    t = toggles
    if not t["decomposition"] and not t["review"] and not t["council"]:
        return "raw"
    if t["decomposition"] and not any(
        t[k] for k in ("firewall", "review", "council", "standup", "crystal")
    ):
        return "native"
    return "protocol"


# The schema's `ablation` names a disabled component. Its vocabulary predates
# the toggle surface, so map where the two agree and extend where they do not.
ABLATION_NAMES = {
    "firewall": "firewall",
    "standup": "standup",
    "review": "senior_review",
    "council": "council",
    "decomposition": "decomposition",
    "tiering": "tiering",
    "crystal": "crystal",
}


def ablation_of(toggles: dict[str, bool]) -> str | None:
    """Which single mechanism this regime removes, or None.

    None when nothing is off (protocol-full) or when more than one thing is
    off (raw, native) -- in those cases `toggles` is the honest record and a
    single name would be a lie.
    """
    off = [k for k in ABLATION_NAMES if not toggles.get(k, True)]
    if len(off) != 1:
        return None
    return ABLATION_NAMES[off[0]]


# --------------------------------------------------------------------------
# Prompt composition
# --------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def render(template: str, values: dict[str, str], *, where: str) -> str:
    """Substitute {{PLACEHOLDER}} in one pass.

    One pass on purpose: substituted material (a spec, a diff) may legally
    contain brace pairs, and a second pass would try to expand them. A
    placeholder with no value raises -- a prompt shipped with a hole in it is
    worse than a run that never started.
    """
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return ""
        return values[key]

    out = PLACEHOLDER_RE.sub(sub, template)
    if missing:
        raise PromptError(f"{where}: no value supplied for "
                          f"{sorted(set(missing))}")
    return out


def load_template(name: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    path = prompts_dir / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"missing prompt template {path}: {exc}") from exc


def extract_doctrine_block(doctrine_md: str) -> str:
    """Pull the '## Prompt block' blockquote out of DOCTRINE.md, verbatim.

    Extracted at run time rather than copied into a template so the prompt
    cannot drift from the doctrine it claims to quote. If the section moves or
    is renamed, this raises rather than shipping an empty preamble.
    """
    lines = doctrine_md.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.strip().lower() == "## prompt block")
    except StopIteration:
        raise PromptError("DOCTRINE.md has no '## Prompt block' section") from None
    quote: list[str] = []
    for ln in lines[start + 1:]:
        if ln.startswith("> "):
            quote.append(ln[2:])
        elif ln.strip() == ">":
            quote.append("")
        elif quote:
            break                       # the blockquote ended
    text = "\n".join(quote).strip()
    if "schwerpunkt" not in text.lower():
        raise PromptError("the extracted doctrine prompt block does not look "
                          "like the doctrine prompt block (no 'schwerpunkt') -- "
                          "refusing to ship it")
    return text


@dataclass
class Ctx:
    """Everything a prompt needs to know about *this* run. Built once, then
    treated as read-only, so composition is a pure function of (config, ctx)
    and the tests can exercise it with no agent and no worktree."""
    framework: Path
    run_id: str
    run_dir: Path
    run_tree: Path
    run_branch: str
    workers_dir: Path
    worker_branch_prefix: str
    guard: Path
    crystal_script: Path
    standup_script: Path
    spec_text: str
    exam_text: str
    runbook_text: str
    doctrine_block: str
    input_hashes: dict[str, str | None] = field(default_factory=dict)

    @property
    def lead_agent_id(self) -> str:
        return "lead"

    @property
    def solo_agent_id(self) -> str:
        return "implementer"

    @property
    def bus_root(self) -> Path:
        """The ONE standup bus for this run.

        bus.sh resolves its root as ${STANDUP_BUS:-$PWD/.standup/bus}, and
        workers run in their own worktrees -- so an unpinned guard invocation
        reads an empty bus beside the worker instead of the run's, and every
        redirect is queued forever and delivered to nobody. Pinned here, in
        the prompts, and in the loop's environment: all three must agree.
        """
        return self.run_tree / ".standup/bus"


def build_ctx(cfg: Config, framework: Path, run_id: str, run_dir: Path,
              run_branch: str) -> Ctx:
    spec = framework / cfg.spec_path
    exam = framework / cfg.grader
    runbook = framework / "protocol/RUNBOOK.md"
    doctrine = framework / "doctrine/DOCTRINE.md"
    for p in (spec, exam, runbook, doctrine):
        if not p.is_file():
            raise ConfigError(f"required input missing from the framework "
                              f"worktree: {p}")
    return Ctx(
        framework=framework,
        run_id=run_id,
        run_dir=run_dir,
        run_tree=run_dir / "tree",
        run_branch=run_branch,
        workers_dir=run_dir / "workers",
        worker_branch_prefix=f"{run_branch}-wp-",
        guard=framework / "standup/guard.sh",
        crystal_script=framework / "crystal/crystal-check.sh",
        standup_script=framework / "standup/standup.sh",
        spec_text=read_text(spec),
        exam_text=read_text(exam),
        runbook_text=read_text(runbook),
        doctrine_block=extract_doctrine_block(read_text(doctrine)),
        input_hashes={
            "spec": sha256_file(spec),
            "exam": sha256_file(exam),
            "runbook": sha256_file(runbook),
            "doctrine": sha256_file(doctrine),
        },
    )


def _protocol_preamble(cfg: Config, ctx: Ctx) -> str:
    """The doctrine prompt block, verbatim, or nothing at all.

    Every orgs regime carries it (bindings/claude-code.md: 'every role prompt
    begins with the DOCTRINE.md prompt block verbatim'). A goal-directed
    control arm gets no protocol artifacts, and doctrine is a protocol
    artifact -- that omission is the whole content of the control. See
    `default_doctrine`.
    """
    if not cfg.doctrine:
        return ""
    return ("## How we work (doctrine — read it, it governs your judgment)\n\n"
            + ctx.doctrine_block + "\n\n")


def _toggle_summary(cfg: Config) -> str:
    on = [k for k in TOGGLE_KEYS if cfg.toggles[k]]
    off = [k for k in TOGGLE_KEYS if not cfg.toggles[k]]
    lines = ["| mechanism | state |", "|---|---|"]
    for k in TOGGLE_KEYS:
        lines.append(f"| `{k}` | {'ON' if cfg.toggles[k] else 'OFF'} |")
    lines.append("")
    if off:
        lines.append("Mechanisms that are **OFF** for this run — do not "
                     "reintroduce them by hand: " + ", ".join(f"`{k}`" for k in off) + ".")
        lines.append("")
        # The runbook and the spec below describe the whole protocol,
        # including the parts this arm removes. They are shared inputs — every
        # arm reads the same ones, which is what makes the target identical —
        # so instead of editing them per arm (which would break that), the
        # precedence is stated outright. Doctrine's own Precedence section
        # puts the work package's instruction above doctrine defaults, and
        # this table is that instruction.
        lines.append("The runbook and the spec below describe the **full** "
                     "protocol, including the mechanisms this table marks OFF. "
                     "They are shared, unedited inputs. **Where they and this "
                     "table disagree, this table wins**: skip the runbook "
                     "steps that belong to an OFF mechanism, and do not "
                     "produce its artifacts. Removing a mechanism is the "
                     "entire point of this run — reintroducing it by hand "
                     "destroys the measurement.")
    else:
        lines.append("Every mechanism is ON for this run.")
    return "\n".join(lines)


def compose_worker_brief(cfg: Config, ctx: Ctx) -> str:
    values = {
        "DOCTRINE_QUOTED": "\n> ".join(ctx.doctrine_block.splitlines()),
        "WORKERS_DIR": str(ctx.workers_dir),
        "WORKER_BRANCH_PREFIX": ctx.worker_branch_prefix,
        "WORKER_CONTEXT_RULE": load_template(
            "frag_firewall_on.md" if cfg.toggles["firewall"] else "frag_firewall_off.md"),
        "WORKER_STANDUP_RULE": (
            render(load_template("frag_standup_worker_rule.md"),
                   {"GUARD": str(ctx.guard), "BUS_ROOT": str(ctx.bus_root)},
                   where="frag_standup_worker_rule.md")
            if cfg.toggles["standup"] else ""),
    }
    return render(load_template("worker_brief.md"), values, where="worker_brief.md")


def crystal_active(cfg: Config) -> bool:
    """Crystal only means something across concurrent branches: it needs
    decomposition (there are workers), parallel (they overlap in time) and
    its own toggle. Any of the three off and there is nothing to speculate
    about."""
    return cfg.toggles["crystal"] and cfg.toggles["parallel"] and cfg.toggles["decomposition"]


def compose_build_prompt(cfg: Config, ctx: Ctx) -> str:
    """The prompt that builds the target. One implementer, or a lead."""
    if not cfg.toggles["decomposition"]:
        standup_section = ""
        if cfg.toggles["standup"]:
            standup_section = render(
                load_template("frag_standup_solo.md"),
                {"GUARD": str(ctx.guard), "BUS_ROOT": str(ctx.bus_root),
                 "SOLO_AGENT_ID": ctx.solo_agent_id},
                where="frag_standup_solo.md")
        return render(load_template("implementer_solo.md"), {
            "PROTOCOL_PREAMBLE": _protocol_preamble(cfg, ctx),
            "TARGET": cfg.target,
            "RUN_TREE": str(ctx.run_tree),
            "RUN_BRANCH": ctx.run_branch,
            "SERVER_PATH": cfg.server_path,
            "SPEC": ctx.spec_text,
            "EXAM": ctx.exam_text,
            "STANDUP_SECTION": standup_section,
        }, where="implementer_solo.md")

    standup_section = ""
    if cfg.toggles["standup"]:
        standup_section = render(
            load_template("frag_standup_lead.md"),
            {"GUARD": str(ctx.guard), "BUS_ROOT": str(ctx.bus_root),
                 "LEAD_AGENT_ID": ctx.lead_agent_id},
            where="frag_standup_lead.md")
    crystal_section = ""
    if crystal_active(cfg):
        crystal_section = render(load_template("frag_crystal_lead.md"),
                                 {"RUN_BRANCH": ctx.run_branch},
                                 where="frag_crystal_lead.md")
    parallel_note = (
        "One message, several `Agent` calls: that is what makes them run at "
        "the same time. Spawning them one per message serialises the sprint "
        "and is not what this run is measuring."
        if cfg.toggles["parallel"] else
        "**This run is SEQUENTIAL by configuration**: spawn one worker, wait "
        "for it, merge it, then spawn the next. Do not run workers "
        "concurrently — concurrency is the variable that is switched off here."
    )
    return render(load_template("lead.md"), {
        "PROTOCOL_PREAMBLE": _protocol_preamble(cfg, ctx),
        "TARGET": cfg.target,
        "RUN_TREE": str(ctx.run_tree),
        "RUN_BRANCH": ctx.run_branch,
        "WORKERS_DIR": str(ctx.workers_dir),
        "WORKER_BRANCH_PREFIX": ctx.worker_branch_prefix,
        "WORKER_IDS": ", ".join(f"`{w}`" for w in cfg.worker_ids),
        "WORKER_MODEL": cfg.models["worker"],
        "SERVER_PATH": cfg.server_path,
        "SPEC": ctx.spec_text,
        "EXAM": ctx.exam_text,
        "RUNBOOK": ctx.runbook_text,
        "WORKER_BRIEF": compose_worker_brief(cfg, ctx),
        "TOGGLE_SUMMARY": _toggle_summary(cfg),
        "PARALLEL_NOTE": parallel_note,
        "STANDUP_SECTION": standup_section,
        "CRYSTAL_SECTION": crystal_section,
    }, where="lead.md")


REVIEW_ROLE_TEXT = {
    "native": (
        "a peer reviewer at the implementer's own tier",
        "You are not the author's lead and you are not adjudicating; you are "
        "the fresh pair of eyes the author does not have.",
    ),
    "lead": (
        "the accountable lead, one rung up",
        "You are accountable for this component shipping correct. You have "
        "the authority to send it back, and the obligation to say precisely "
        "why.",
    ),
    "cto": (
        "the CTO, reviewing across the whole target",
        "You are accountable for the system, not the file. Weigh whether the "
        "pieces compose, whether a boundary is wrong, and whether anything "
        "here is a defect class rather than a defect.",
    ),
}


def compose_review_prompt(cfg: Config, ctx: Ctx, step: str, mat: "Materials") -> str:
    title, stance = REVIEW_ROLE_TEXT[step]
    return render(load_template("review_claude.md"), {
        "PROTOCOL_PREAMBLE": _protocol_preamble(cfg, ctx),
        "ROLE_TITLE": title,
        "ROLE_STANCE": stance,
        "REVIEW_SHA": mat.review_sha,
        "RUN_BRANCH": ctx.run_branch,
        "RUN_TREE": str(ctx.run_tree),
        "SERVER_PATH": cfg.server_path,
        "DIFF": mat.diff,
        "SERVER_CODE": mat.server_code,
        "SPEC": ctx.spec_text,
        "EXAM": ctx.exam_text,
        "FINDINGS_CONTRACT": load_template("_findings_contract.md"),
    }, where="review_claude.md")


def compose_council_prompt(cfg: Config, ctx: Ctx, mat: "Materials") -> str:
    """The cross-provider council seat prompt.

    Deliberately free of doctrine and toggles: a foreign seat reviews code
    against a spec, and keeping the prompt regime-independent keeps council
    findings comparable across arms of the study.
    """
    return render(load_template("council_seat.md"), {
        "TARGET_DESC": cfg.target_desc,
        "SERVER_CODE": mat.server_code,
        "SPEC": ctx.spec_text,
        "EXAM": ctx.exam_text,
        "FINDINGS_CONTRACT": load_template("_findings_contract.md"),
    }, where="council_seat.md")


def compose_audit_prompt(cfg: Config, ctx: Ctx, mat: "Materials") -> str:
    """The escaped-defect audit seat prompt.

    MUST NOT vary with any toggle. It is the yardstick every regime is held
    against, so anything regime-dependent in here silently makes the arms
    incomparable. test_run_regime.py asserts that two regimes given identical
    code produce byte-identical audit prompts.
    """
    return render(load_template("audit_council.md"), {
        "TARGET_DESC": cfg.target_desc,
        "SERVER_CODE": mat.server_code,
        "SPEC": ctx.spec_text,
        "EXAM": ctx.exam_text,
        "FINDINGS_CONTRACT": load_template("_findings_contract.md"),
    }, where="audit_council.md")


def compose_fix_prompt(cfg: Config, ctx: Ctx, mat: "Materials") -> str:
    return render(load_template("fix_round.md"), {
        "PROTOCOL_PREAMBLE": _protocol_preamble(cfg, ctx),
        "RUN_TREE": str(ctx.run_tree),
        "RUN_BRANCH": ctx.run_branch,
        "SERVER_PATH": cfg.server_path,
        "FINDINGS_JSON": mat.findings_json,
        "FINDINGS_PROSE": mat.findings_prose,
        "SPEC": ctx.spec_text,
        "EXAM": ctx.exam_text,
    }, where="fix_round.md")


@dataclass
class Materials:
    """The run-dependent text a review prompt needs. Filled with clearly
    labelled placeholders under --dry-run so composition can be validated
    before a single token is spent."""
    diff: str = ""
    server_code: str = ""
    review_sha: str = ""
    findings_json: str = "[]"
    findings_prose: str = ""


DRY_MATERIALS = Materials(
    diff="<<DRY RUN: the diff of the run branch against its base goes here>>",
    server_code="<<DRY RUN: the built server's source files go here>>",
    review_sha="<<DRY RUN: the frozen commit sha goes here>>",
    findings_json='[{"severity": "Critical", "claim": "<<DRY RUN: a finding>>"}]',
    findings_prose="<<DRY RUN: the reviewer's prose goes here>>",
)


# --------------------------------------------------------------------------
# Toggle conformance -- proving the composition honoured the config
# --------------------------------------------------------------------------

@dataclass
class MarkerCheck:
    mechanism: str
    state: str          # "on" | "off" | "n/a"
    marker: str
    expected_present: bool
    actually_present: bool

    @property
    def ok(self) -> bool:
        return self.expected_present == self.actually_present


# Protocol vocabulary that lives in the SHARED spec, and the mechanism each
# term names. Every arm reads the same spec -- that is what makes the target
# identical and the comparison fair -- but it means an arm with a mechanism
# switched OFF can still read about that mechanism in its spec. That is a
# confound in the shared input, not a bug in composition, and it is surfaced
# rather than silently patched: editing the spec per arm would trade this
# confound for a worse one (the arms would no longer share a target).
SPEC_PROTOCOL_TERMS = {
    "decomposition": ("work package", "fan-out"),
    "review_lead": ("review ladder", "lead review"),
    "council": ("council review",),
    "firewall": ("firewalled entit",),
}


def spec_confounds(cfg: Config, spec_text: str) -> list[tuple[str, str]]:
    """Protocol terms the shared spec uses for mechanisms this arm has OFF."""
    low = spec_text.lower()
    out: list[tuple[str, str]] = []
    for mech, terms in SPEC_PROTOCOL_TERMS.items():
        if cfg.toggles.get(mech, False):
            continue
        for term in terms:
            if term in low:
                out.append((mech, term))
    return out


def toggle_conformance(cfg: Config, build_prompt: str) -> list[MarkerCheck]:
    """Check the BUILD prompt against the toggles, in both directions.

    Both directions is the point. "The marker is absent when the mechanism is
    off" is satisfied by a template that never mentions it at all, so each
    check is paired with its opposite: present when on, absent when off. That
    pairing is what makes the assertion mutation-checkable.

    Scoped to the build-phase prompt only. Whether a council RUNS is a
    property of the run, not of what the builder was told, so `council` is
    checked by whether the council prompt gets composed at all (see the plan).
    """
    lowered = build_prompt.lower()
    checks: list[MarkerCheck] = []

    def add(mech: str, marker: str, active: bool | None) -> None:
        if active is None:
            checks.append(MarkerCheck(mech, "n/a", marker, False,
                                      marker.lower() in lowered))
            return
        checks.append(MarkerCheck(mech, "on" if active else "off", marker,
                                  active, marker.lower() in lowered))

    # Markers are chosen to be unique to the MECHANISM's own text, not merely
    # topical. "work package" would look like a decomposition marker and is
    # not one: the doctrine block and the shared spec both use the phrase, so
    # it reads as present in a regime that has no decomposition at all.
    # `git worktree add -b` is the decomposition machinery itself, and appears
    # in no other template.
    add("doctrine", "schwerpunkt", cfg.doctrine)
    add("standup", "guard.sh", cfg.toggles["standup"])
    add("crystal", "crystal-check.sh", crystal_active(cfg))
    add("decomposition", "git worktree add -b", cfg.toggles["decomposition"])
    if cfg.toggles["decomposition"]:
        add("firewall", "lean context pack", cfg.toggles["firewall"])
    else:
        # No workers, so no context pack either way. Recorded as n/a with the
        # marker asserted absent, rather than quietly skipped.
        add("firewall", "lean context pack", None)
    return checks


# --------------------------------------------------------------------------
# Findings parsing
# --------------------------------------------------------------------------

FENCE_RE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n(.*?)```", re.DOTALL)


@dataclass
class Findings:
    ok: bool
    findings: list[dict]
    counts: dict[str, int] | None
    error: str | None
    source: str | None          # which candidate block parsed

    def to_json(self) -> dict:
        return {
            "parse_ok": self.ok,
            "parse_error": self.error,
            "source": self.source,
            "counts": self.counts,
            "findings": self.findings,
        }


def _normalise_severity(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    return SEVERITY_MAP.get(value.strip().lower(), "unknown")


def _as_findings_list(obj: Any) -> list[dict] | None:
    """Accept a bare list, or an object wrapping one under an obvious key.

    Strict about the elements: every one must be a mapping carrying a
    severity. A block of free-form objects is a parse failure, not zero
    findings (A8) -- silently returning [] here would deflate the benchmark's
    primary metric.
    """
    if isinstance(obj, dict):
        for key in ("findings", "results", "issues"):
            if isinstance(obj.get(key), list):
                obj = obj[key]
                break
        else:
            return None
    if not isinstance(obj, list):
        return None
    out: list[dict] = []
    for item in obj:
        if not isinstance(item, dict):
            return None
        sev = item.get("severity", item.get("sev"))
        if sev is None:
            return None
        out.append({
            "severity_raw": sev if isinstance(sev, str) else repr(sev),
            "severity": _normalise_severity(sev),
            "claim": str(item.get("claim", item.get("description", item.get("title", "")))),
        })
    return out


def count_findings(findings: Iterable[dict]) -> dict[str, int]:
    counts = {b: 0 for b in SEVERITY_BUCKETS}
    total = 0
    for f in findings:
        counts[f.get("severity", "unknown")] = counts.get(f.get("severity", "unknown"), 0) + 1
        total += 1
    counts["total"] = total
    return counts


def parse_findings(text: str | None) -> Findings:
    """Pull the findings block out of a reviewer's reply.

    Candidates, in order of preference: every fenced block (last first,
    because the contract says nothing may follow the real one), then the whole
    reply parsed as JSON, then the last bracketed span that parses. The first
    candidate that yields a well-formed findings list wins.

    An empty array is a legitimate result -- "no findings" is a respected
    outcome and must be distinguishable from "could not parse", which returns
    ok=False and counts=None.
    """
    if text is None:
        return Findings(False, [], None, "no reviewer output at all", None)
    if not text.strip():
        return Findings(False, [], None, "reviewer produced empty output", None)

    candidates: list[tuple[str, str]] = []
    for m in FENCE_RE.finditer(text):
        candidates.append(("fenced", m.group(1)))
    candidates.reverse()                      # last fenced block first
    candidates.append(("whole-reply", text))
    # Last resort: the final bracketed span in the reply.
    lb, rb = text.rfind("["), text.rfind("]")
    if lb != -1 and rb > lb:
        candidates.append(("bracket-span", text[lb:rb + 1]))

    errors: list[str] = []
    for source, blob in candidates:
        blob = blob.strip()
        if not blob:
            continue
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError as exc:
            errors.append(f"{source}: {exc.msg} at line {exc.lineno}")
            continue
        parsed = _as_findings_list(obj)
        if parsed is None:
            errors.append(f"{source}: JSON parsed but is not a list of "
                          "{{severity, claim}} objects")
            continue
        return Findings(True, parsed, count_findings(parsed), None, source)

    return Findings(False, [], None,
                    "no parsable findings block; tried: " + " | ".join(errors[:5]),
                    None)


# --------------------------------------------------------------------------
# Reading back what `claude -p` produced
# --------------------------------------------------------------------------

@dataclass
class ClaudeResult:
    ok: bool
    error: str | None
    shape: str | None
    result_event: dict | None
    text: str | None

    def tokens(self) -> dict:
        return tokens_from_result(self.result_event)


def parse_claude_result(path: Path) -> ClaudeResult:
    """Find the `type: "result"` event in a `claude -p --output-format json`
    log, across the three shapes seen in the wild (A1)."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return ClaudeResult(False, f"cannot stat {path}: {exc}", None, None, None)
    if size == 0:
        return ClaudeResult(False, f"{path} is empty (the agent produced no output)",
                            None, None, None)
    if size > LOG_READ_CAP:
        return ClaudeResult(False, f"{path} is {size} bytes, over the "
                            f"{LOG_READ_CAP}-byte parse cap", None, None, None)
    text = path.read_text(encoding="utf-8", errors="replace")

    doc: Any = None
    shape: str | None = None
    try:
        doc = json.loads(text)
        shape = "array" if isinstance(doc, list) else "object"
    except json.JSONDecodeError:
        events = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if events:
            doc, shape = events, "jsonl"

    if doc is None:
        return ClaudeResult(False, f"{path} is not JSON in any known shape "
                            "(array, object, or JSON lines)", None, None, None)

    candidates = doc if isinstance(doc, list) else [doc]
    results = [e for e in candidates
               if isinstance(e, dict) and e.get("type") == "result"]
    if not results and isinstance(doc, dict) and "result" in doc:
        results = [doc]
    if not results:
        return ClaudeResult(False, f"{path}: no event of type 'result' "
                            f"(shape={shape}, {len(candidates)} events)",
                            shape, None, None)
    ev = results[-1]
    txt = ev.get("result")
    if not isinstance(txt, str):
        txt = None
    if ev.get("is_error"):
        return ClaudeResult(False,
                            f"agent reported an error: subtype="
                            f"{ev.get('subtype')!r} api_error_status="
                            f"{ev.get('api_error_status')!r}",
                            shape, ev, txt)
    return ClaudeResult(True, None, shape, ev, txt)


def tokens_from_result(ev: dict | None) -> dict:
    """Cumulative token usage for one `claude -p` run.

    `modelUsage` is the per-model aggregate for the whole session; the
    top-level `usage` is the LAST turn only (A2). Components are recorded
    alongside the total so nobody has to trust the addition.
    """
    empty = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
             "total_tokens": 0, "source": "unavailable", "estimated": False}
    if not isinstance(ev, dict):
        return empty
    mu = ev.get("modelUsage")
    tot = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    source = None
    if isinstance(mu, dict) and mu:
        for _model, u in mu.items():
            if not isinstance(u, dict):
                continue
            tot["input"] += int(u.get("inputTokens") or 0)
            tot["output"] += int(u.get("outputTokens") or 0)
            tot["cache_read"] += int(u.get("cacheReadInputTokens") or 0)
            tot["cache_creation"] += int(u.get("cacheCreationInputTokens") or 0)
        source = "modelUsage"
    else:
        u = ev.get("usage")
        if isinstance(u, dict):
            tot["input"] = int(u.get("input_tokens") or 0)
            tot["output"] = int(u.get("output_tokens") or 0)
            tot["cache_read"] = int(u.get("cache_read_input_tokens") or 0)
            tot["cache_creation"] = int(u.get("cache_creation_input_tokens") or 0)
            source = "usage (last turn only -- a floor, not a total)"
    if source is None:
        return empty
    out = dict(tot)
    out["total_tokens"] = sum(tot.values())
    out["source"] = source
    out["estimated"] = False
    out["cost_usd"] = ev.get("total_cost_usd")
    out["num_turns"] = ev.get("num_turns")
    return out


def estimated_tokens(prompt: str, reply: str) -> dict:
    """A foreign seat reports no usage, so its cost is estimated (A3)."""
    return {
        "input": len(prompt) // 4,
        "output": len(reply) // 4,
        "cache_read": 0,
        "cache_creation": 0,
        "total_tokens": (len(prompt) + len(reply)) // 4,
        "source": "estimate: characters / 4",
        "estimated": True,
    }


def zero_tokens(reason: str) -> dict:
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
            "total_tokens": 0, "source": reason, "estimated": False}


def add_tokens(*buckets: dict) -> dict:
    out = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
           "total_tokens": 0}
    estimated = False
    for b in buckets:
        if not b:
            continue
        for k in ("input", "output", "cache_read", "cache_creation", "total_tokens"):
            out[k] += int(b.get(k) or 0)
        estimated = estimated or bool(b.get("estimated"))
    out["estimated"] = estimated
    return out


# --------------------------------------------------------------------------
# Minimal JSON-schema validation
# --------------------------------------------------------------------------
#
# Necessity check (doctrine: what concretely fails if we just don't?): without
# it, a manifest can drift out of schema silently -- a renamed field, a null
# where an integer belongs -- and the drift is discovered only when the study
# is assembled from a dozen runs and half of them do not line up. Rerunning a
# regime costs hundreds of thousands of tokens. This validator covers exactly
# the constructs the manifest schema uses and nothing more.

_JSON_TYPES: dict[str, tuple] = {
    "object": (dict,), "array": (list,), "string": (str,),
    "boolean": (bool,), "null": (type(None),),
}


def _type_ok(value: Any, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    types = _JSON_TYPES.get(name)
    if types is None:
        return True                        # unknown keyword: do not invent a rule
    return isinstance(value, types)


def validate_schema(instance: Any, schema: dict, path: str = "$") -> list[str]:
    """Validate against the subset of JSON Schema this project's schema uses:
    type (string or list), enum, required, properties, additionalProperties
    (false or a subschema), items, minimum. Returns a list of errors."""
    errs: list[str] = []
    if not isinstance(schema, dict):
        return errs

    if "type" in schema:
        names = schema["type"]
        names = [names] if isinstance(names, str) else list(names)
        if not any(_type_ok(instance, n) for n in names):
            errs.append(f"{path}: expected type {'/'.join(names)}, "
                        f"got {type(instance).__name__}")
            return errs                     # a type mismatch makes the rest noise

    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} is not one of {schema['enum']}")

    if "minimum" in schema and isinstance(instance, (int, float)) \
            and not isinstance(instance, bool):
        if instance < schema["minimum"]:
            errs.append(f"{path}: {instance} < minimum {schema['minimum']}")

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errs.append(f"{path}: missing required property '{req}'")
        props = schema.get("properties", {})
        for key, val in instance.items():
            if key in props:
                errs.extend(validate_schema(val, props[key], f"{path}.{key}"))
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errs.append(f"{path}: property '{key}' is not allowed "
                                "(additionalProperties: false)")
                elif isinstance(extra, dict):
                    errs.extend(validate_schema(val, extra, f"{path}.{key}"))

    if isinstance(instance, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(instance):
            errs.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))
    return errs


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

class Run:
    """One benchmark run. Owns the run directory, the failure ledger, and the
    manifest -- which is written even when the run falls over, because a run
    directory that is complete only on the happy path is not evidence."""

    def __init__(self, cfg: Config, args: argparse.Namespace):
        self.cfg = cfg
        self.args = args
        self.started = utc_now()
        self.framework = Path(args.framework).resolve()
        self.ask_agent = Path(args.ask_agent).resolve()

        ts = stamp(self.started)
        self.run_id = args.run_id or f"{ts}-{cfg.regime}-{cfg.target}"
        self.run_branch = f"bench-run/{cfg.regime}-{ts}"
        self.run_dir = Path(args.runs_root).resolve() / self.run_id
        self.ctx = build_ctx(cfg, self.framework, self.run_id, self.run_dir,
                             self.run_branch)

        self.failures: list[dict] = []
        self._failures_lock = threading.Lock()
        self.phases: dict[str, float] = {}
        self.tokens: dict[str, dict] = {}
        self.review_steps: dict[str, dict] = {}
        self.grading_stages: dict[str, dict] = {}
        self.escaped: dict | None = None
        self.model_calls = 0
        self.standup_stats = {"ran": False, "observes": 0, "redirects": 0,
                              "stalls_seen": 0, "errors": 0}
        self.crystal_stats = {"ran": False, "checks": 0, "conflicts": 0,
                              "errors": 0, "reports": []}
        self.worktree_created = False
        self.base_sha = "unknown"
        self.head_sha = "unknown"
        self.exam_tampered: bool | None = None

    # -- bookkeeping -------------------------------------------------------

    def fail(self, phase: str, kind: str, detail: str, **extra: Any) -> None:
        """Record a failure. Never raises, never swallows: everything that
        went wrong ends up in the manifest, with its phase."""
        entry = {"phase": phase, "kind": kind, "detail": detail,
                 "at": iso(utc_now())}
        entry.update(extra)
        with self._failures_lock:
            self.failures.append(entry)
        print(f"  ! {phase}/{kind}: {detail}", file=sys.stderr, flush=True)

    def _count_calls(self, n: int) -> None:
        """Council and audit seats run in threads, so `+=` on a plain int
        can lose an increment (load/add/store is not atomic). Locked."""
        with self._failures_lock:
            self.model_calls += n

    def log(self, msg: str) -> None:
        print(f"[{iso(utc_now())}] {msg}", flush=True)

    def path(self, *parts: str) -> Path:
        p = self.run_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # -- isolation ---------------------------------------------------------

    def create_worktree(self) -> bool:
        """Fresh branch off master in a worktree of its very own.

        Everything the agents do happens in there. Nothing in this harness
        writes to any other worktree; that is the isolation claim, and it is
        the reason a run can be thrown away whole.
        """
        rc, _out, err = git(["rev-parse", "--verify", "-q", "refs/heads/master"],
                            cwd=self.framework, timeout=self.cfg.timeouts["git_s"])
        if rc != 0:
            self.fail("isolation", "no-base-branch",
                      f"refs/heads/master not found in {self.framework}: {err.strip()}")
            return False
        rc, out, _ = git(["rev-parse", "refs/heads/master"], cwd=self.framework,
                         timeout=self.cfg.timeouts["git_s"])
        self.base_sha = out.strip() or "unknown"

        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.ctx.run_tree.exists():
            self.fail("isolation", "run-tree-exists",
                      f"{self.ctx.run_tree} already exists; refusing to reuse it")
            return False
        rc, _out, err = git(
            ["worktree", "add", "-b", self.run_branch,
             str(self.ctx.run_tree), "master"],
            cwd=self.framework, timeout=self.cfg.timeouts["git_s"])
        if rc != 0:
            self.fail("isolation", "worktree-add-failed", err.strip() or f"rc={rc}")
            return False
        self.worktree_created = True
        self.ctx.workers_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"worktree {self.ctx.run_tree} on {self.run_branch} "
                 f"(base {self.base_sha[:12]})")

        # A5: the exam that grades this run is the pristine one. Detect, and
        # record, if the run tree's copy diverges -- that is evidence about
        # the run, not a reason to stop it.
        run_exam = self.ctx.run_tree / self.cfg.grader
        pristine = self.framework / self.cfg.grader
        if run_exam.is_file():
            self.exam_tampered = sha256_file(run_exam) != sha256_file(pristine)
        return True

    def refresh_head(self) -> None:
        rc, out, _ = git(["rev-parse", self.run_branch], cwd=self.framework,
                         timeout=self.cfg.timeouts["git_s"])
        if rc == 0 and out.strip():
            self.head_sha = out.strip()

    def check_exam_tamper(self) -> None:
        run_exam = self.ctx.run_tree / self.cfg.grader
        if run_exam.is_file():
            tampered = sha256_file(run_exam) != sha256_file(self.framework / self.cfg.grader)
            if tampered and not self.exam_tampered:
                self.fail("integrity", "exam-modified",
                          f"the run tree's copy of {self.cfg.grader} differs from "
                          "the frozen one; grading used the pristine copy")
            self.exam_tampered = tampered

    # -- materials ---------------------------------------------------------

    def collect_materials(self) -> Materials:
        """The diff and the built source, frozen at the current head."""
        self.refresh_head()
        rc, diff, err = git(["diff", f"{self.base_sha}..{self.head_sha}"],
                            cwd=self.ctx.run_tree, timeout=self.cfg.timeouts["git_s"])
        if rc != 0:
            self.fail("materials", "diff-failed", err.strip() or f"rc={rc}")
            diff = "(the diff could not be computed; see the manifest failures)"
        code = self.collect_server_code()
        return Materials(
            diff=truncate(diff, DIFF_CAP, "diff"),
            server_code=code,
            review_sha=self.head_sha,
        )

    def collect_server_code(self) -> str:
        """Every Python file beside the server, inlined with headers.

        Inlined rather than referenced because a foreign council seat may not
        be able to read the filesystem at all (A3's sibling problem) -- and
        because a review of a named revision should not depend on what the
        working tree happens to hold when the seat gets around to looking.
        """
        server = self.ctx.run_tree / self.cfg.server_path
        if not server.is_file():
            return ("(no server was produced at "
                    f"{self.cfg.server_path} -- there is nothing to review)")
        srcdir = server.parent
        files = sorted(p for p in srcdir.rglob("*.py")
                       if "__pycache__" not in p.parts)
        # Put the entry point first; a reviewer reads it as the way in.
        files.sort(key=lambda p: (p != server, str(p)))
        chunks: list[str] = []
        used = 0
        for p in files:
            rel = p.relative_to(self.ctx.run_tree)
            try:
                body = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                chunks.append(f"### `{rel}`\n\n(unreadable: {exc})\n")
                continue
            if used + len(body) > CODE_CAP:
                chunks.append(f"### `{rel}`\n\n[omitted: the {CODE_CAP}-character "
                              "inlining budget was exhausted]\n")
                continue
            used += len(body)
            chunks.append(f"### `{rel}`\n\n```python\n{body}\n```\n")
        if not chunks:
            return f"(no Python sources found under {srcdir})"
        return "\n".join(chunks)

    # -- agent invocations -------------------------------------------------

    def claude(self, name: str, prompt: str, *, model: str, timeout: float,
               cwd: Path | None = None) -> tuple[Proc, ClaudeResult]:
        """One headless `claude -p`, fresh process, prompt on stdin."""
        self.path("prompts", f"{name}.txt").write_text(prompt, encoding="utf-8")
        out = self.path("logs", f"{name}.json")
        err = self.path("logs", f"{name}.stderr.txt")
        argv = ["claude", "-p", "--model", model,
                "--output-format", "json", "--dangerously-skip-permissions"]
        self.log(f"  -> claude -p ({model}) {name}  [timeout {int(timeout)}s]")
        proc = run_capture(argv, cwd=cwd or self.ctx.run_tree, timeout=timeout,
                           stdout_path=out, stderr_path=err, stdin_data=prompt)
        res = parse_claude_result(out)
        if proc.timed_out:
            self.fail(name, "timeout", f"claude -p exceeded {timeout}s and was killed")
        elif proc.spawn_error:
            self.fail(name, "spawn-failed", proc.spawn_error)
        elif proc.returncode != 0:
            self.fail(name, "nonzero-exit", f"claude -p exited {proc.returncode}",
                      stderr_tail=_tail(err))
        if not res.ok:
            self.fail(name, "unparsable-result", res.error or "unknown")
        else:
            self._count_calls(int(res.result_event.get("num_turns") or 0) or 1)
        return proc, res

    def seat(self, name: str, seat_name: str, prompt: str, *,
             timeout: float) -> tuple[Proc, str | None]:
        """One foreign council seat through ask-agent. Prompt via a file, not
        argv -- these prompts are hundreds of kilobytes."""
        pf = self.path("prompts", f"{name}.txt")
        pf.write_text(prompt, encoding="utf-8")
        out = self.path("logs", f"{name}.txt")
        err = self.path("logs", f"{name}.stderr.txt")
        if not self.ask_agent.is_file():
            self.fail(name, "ask-agent-missing", f"{self.ask_agent} not found")
            return Proc([str(self.ask_agent)], None, False, 0.0, None, None,
                        spawn_error="not found"), None
        argv = [str(self.ask_agent), seat_name, "-d", str(self.ctx.run_tree),
                "-f", str(pf)]
        self.log(f"  -> ask-agent {seat_name} {name}  [timeout {int(timeout)}s]")
        proc = run_capture(argv, cwd=self.ctx.run_tree, timeout=timeout,
                           stdout_path=out, stderr_path=err)
        self._count_calls(1)
        if proc.timed_out:
            self.fail(name, "timeout", f"{seat_name} exceeded {timeout}s and was killed")
        elif proc.spawn_error:
            self.fail(name, "spawn-failed", proc.spawn_error)
        elif proc.returncode != 0:
            self.fail(name, "nonzero-exit",
                      f"{seat_name} exited {proc.returncode}", stderr_tail=_tail(err))
        try:
            reply = out.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.fail(name, "no-reply", f"cannot read {out}: {exc}")
            reply = None
        return proc, reply

    # -- phases ------------------------------------------------------------

    def phase_build(self) -> None:
        t0 = time.time()
        prompt = compose_build_prompt(self.cfg, self.ctx)
        model = self.cfg.builder_model
        stop = threading.Event()
        threads: list[threading.Thread] = []
        if self.cfg.toggles["standup"]:
            threads.append(self._spawn_loop("standup", self._standup_loop, stop))
        if crystal_active(self.cfg):
            threads.append(self._spawn_loop("crystal", self._crystal_loop, stop))
        else:
            self.crystal_stats["skipped_reason"] = _crystal_skip_reason(self.cfg)
        try:
            proc, res = self.claude("build", prompt, model=model,
                                    timeout=self.cfg.timeouts["build_s"])
        finally:
            stop.set()
            for th in threads:
                th.join(timeout=90)
                if th.is_alive():
                    self.fail("build", "loop-hung",
                              f"the {th.name} loop did not stop within 90s")
        self.tokens["build"] = res.tokens() if res.ok else zero_tokens(
            "build result unparsable")
        self.phases["build"] = time.time() - t0
        self.path("logs", "build.result.json").write_text(
            json.dumps({"proc": proc.summary(), "parsed_ok": res.ok,
                        "error": res.error, "shape": res.shape,
                        "final_text": res.text}, indent=2), encoding="utf-8")
        self.refresh_head()
        self.check_exam_tamper()

    def _spawn_loop(self, name: str, fn: Callable[[threading.Event], None],
                    stop: threading.Event) -> threading.Thread:
        def wrapper() -> None:
            try:
                fn(stop)
            except Exception as exc:                      # noqa: BLE001
                self.fail(name, "loop-crashed", f"{type(exc).__name__}: {exc}")
        th = threading.Thread(target=wrapper, name=name, daemon=True)
        th.start()
        return th

    def _standup_loop(self, stop: threading.Event) -> None:
        """Observe on a cadence; redirect an agent that has stalled.

        The standup exists because the agent that most needs redirecting is
        the one that has stopped observing. It cannot ask for help, so the
        environment checks on it.
        """
        self.standup_stats["ran"] = True
        env = {"STANDUP_BUS": str(self.ctx.bus_root),
               "STANDUP_STALL_MIN": str(self.cfg.standup["stall_min"])}
        agents = list(self.cfg.worker_ids) if self.cfg.toggles["decomposition"] else []
        agents.append(self.ctx.lead_agent_id if self.cfg.toggles["decomposition"]
                      else self.ctx.solo_agent_id)
        # Seed each inbox so `standup.sh observe` can see the agent at all
        # (it enumerates agents by their bus directory), and so the first
        # thing every agent reads is that it is being observed.
        for a in agents:
            run_capture([str(self.ctx.framework / "standup/bus.sh"), "send", a, "info",
                         "Standup is observing this run. Keep status/<id>.md "
                         "current and commit granularly."],
                        cwd=self.ctx.run_tree, timeout=30,
                        stdout_path=self.path("logs", "standup-seed.txt"),
                        stderr_path=self.path("logs", "standup-seed.err.txt"),
                        env=env)
        last_redirect: dict[str, float] = {}
        log = self.path("logs", "standup.log")
        n = 0
        while True:
            n += 1
            out = self.path("logs", f"standup-observe-{n:03d}.txt")
            proc = run_capture([str(self.ctx.standup_script), "observe"],
                               cwd=self.ctx.run_tree,
                               timeout=self.cfg.timeouts["standup_s"],
                               stdout_path=out,
                               stderr_path=self.path("logs", f"standup-observe-{n:03d}.err.txt"),
                               env=env)
            self.standup_stats["observes"] += 1
            if not proc.ok:
                self.standup_stats["errors"] += 1
            text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== observe #{n} @ {iso(utc_now())} "
                         f"(rc={proc.returncode}) =====\n{text}\n")
            for agent in _stalled_agents(text):
                self.standup_stats["stalls_seen"] += 1
                now = time.time()
                if now - last_redirect.get(agent, 0.0) < self.cfg.standup["redirect_cooldown_s"]:
                    continue
                last_redirect[agent] = now
                msg = ("Standup: you have not committed in a while. Reorient. "
                       "In one line, name the spec goal your current action "
                       "serves; if you cannot name it, you are moving, not "
                       "progressing — stop, commit what works, and re-plan. "
                       "A thrice-failed approach is a signal, not a dare.")
                r = run_capture([str(self.ctx.standup_script), "redirect", agent, msg],
                                cwd=self.ctx.run_tree,
                                timeout=self.cfg.timeouts["standup_s"],
                                stdout_path=self.path("logs", "standup-redirects.txt"),
                                stderr_path=self.path("logs", "standup-redirects.err.txt"),
                                env=env)
                if r.ok:
                    self.standup_stats["redirects"] += 1
                    with open(log, "a", encoding="utf-8") as fh:
                        fh.write(f"REDIRECT -> {agent}: {msg}\n")
                else:
                    self.standup_stats["errors"] += 1
            if stop.wait(self.cfg.standup["interval_s"]):
                return

    def _crystal_loop(self, stop: threading.Event) -> None:
        """Speculatively merge the worker branches against each other.

        Most speculative merges are clean; the value is early warning on the
        rare real one, textual or semantic. Nothing here touches a ref or a
        worktree.
        """
        self.crystal_stats["ran"] = True
        server_dir = str(Path(self.cfg.server_path).parent) or "."
        test_cmd = self.cfg.crystal["test_cmd"] or f"python3 -m compileall -q {server_dir}"
        log = self.path("logs", "crystal.log")
        n = 0
        while True:
            if stop.wait(self.cfg.crystal["interval_s"]):
                return
            n += 1
            rc, out, _ = git(["for-each-ref", "--format=%(refname:short)",
                              f"refs/heads/{self.ctx.worker_branch_prefix}*"],
                             cwd=self.ctx.run_tree, timeout=self.cfg.timeouts["git_s"])
            branches = [b.strip() for b in out.splitlines() if b.strip()]
            if rc != 0 or len(branches) < 1:
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"\n===== check #{n} @ {iso(utc_now())}: "
                             f"no worker branches yet =====\n")
                continue
            rpt = self.path("logs", f"crystal-{n:03d}.txt")
            proc = run_capture(
                [str(self.ctx.crystal_script), "--base", self.ctx.run_branch,
                 "--test-cmd", test_cmd,
                 "--timeout", str(int(self.cfg.crystal["timeout_s"])), *branches],
                cwd=self.ctx.run_tree, timeout=self.cfg.timeouts["crystal_s"],
                stdout_path=rpt,
                stderr_path=self.path("logs", f"crystal-{n:03d}.err.txt"))
            self.crystal_stats["checks"] += 1
            text = rpt.read_text(encoding="utf-8", errors="replace") if rpt.exists() else ""
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== check #{n} @ {iso(utc_now())} "
                         f"(rc={proc.returncode}) branches={branches} =====\n{text}\n")
            # crystal-check.sh: 0 clean, 1 conflicts found, 2 error.
            if proc.returncode == 1:
                self.crystal_stats["conflicts"] += 1
                self.crystal_stats["reports"].append({
                    "check": n, "at": iso(utc_now()), "branches": branches,
                    "report": str(rpt.relative_to(self.run_dir)),
                    "stanzas": _conflict_stanzas(text),
                })
            elif proc.returncode != 0:
                self.crystal_stats["errors"] += 1

    def phase_grade(self, tag: str) -> dict:
        """Run the frozen exam, from the pristine copy, under nix."""
        t0 = time.time()
        server = self.ctx.run_tree / self.cfg.server_path
        exam = self.framework / self.cfg.grader
        result: dict[str, Any] = {
            "ran": False, "exam": str(exam), "server": str(server),
            "conformance_total": 0, "conformance_passed": 0,
            "passed_all": False, "exit_code": None, "timed_out": False,
        }
        if not server.is_file():
            result["reason"] = f"no server at {self.cfg.server_path}"
            self.fail(f"grade:{tag}", "no-server", result["reason"])
            self.grading_stages[tag] = result
            self.phases[f"grade:{tag}"] = time.time() - t0
            return result
        out = self.path("logs", f"conformance-{tag}.log")
        err = self.path("logs", f"conformance-{tag}.err.log")
        argv = ["nix", "develop", str(self.framework / "bench"), "--command",
                "bash", str(exam), "python3", str(server)]
        self.log(f"  -> grading ({tag}) via the frozen exam under nix")
        proc = run_capture(argv, cwd=self.ctx.run_tree,
                           timeout=self.cfg.timeouts["grade_s"],
                           stdout_path=out, stderr_path=err)
        text = ((out.read_text(encoding="utf-8", errors="replace") if out.exists() else "")
                + "\n"
                + (err.read_text(encoding="utf-8", errors="replace") if err.exists() else ""))
        result["ran"] = True
        result["exit_code"] = proc.returncode
        result["timed_out"] = proc.timed_out
        m = re.search(r"conformance:\s*(\d+)\s+passed,\s*(\d+)\s+failed", text)
        if m:
            passed, failed = int(m.group(1)), int(m.group(2))
            result["conformance_passed"] = passed
            result["conformance_total"] = passed + failed
            result["passed_all"] = (failed == 0 and proc.returncode == 0)
        else:
            # Exit 2 means the exam could not run (no redis-cli, server never
            # came up). Record that honestly rather than scoring it 0/0 pass.
            result["reason"] = ("the exam printed no 'conformance: N passed' "
                                f"line (exit {proc.returncode})")
            self.fail(f"grade:{tag}", "exam-did-not-report", result["reason"],
                      log_tail=_tail(out), stderr_tail=_tail(err))
        if proc.timed_out:
            self.fail(f"grade:{tag}", "timeout",
                      f"the exam exceeded {self.cfg.timeouts['grade_s']}s")
        result["failures"] = re.findall(r"^FAIL: (.+)$", text, re.MULTILINE)
        self.grading_stages[tag] = result
        self.phases[f"grade:{tag}"] = time.time() - t0
        self.log(f"     {tag}: {result['conformance_passed']}/"
                 f"{result['conformance_total']} assertions passed")
        return result

    # -- review ladder -----------------------------------------------------

    def phase_reviews(self) -> None:
        for step in REVIEW_STEP_ORDER:
            if not self.cfg.steps[step]:
                self.review_steps[step] = {
                    "ran": False,
                    "skipped_reason": f"the config leaves review step '{step}' off",
                    "rounds": [], "totals": _empty_totals(),
                    "fix_rounds_applied": 0,
                }
                continue
            self.log(f"review step: {step}")
            if step == "council":
                self.review_steps[step] = self._council_step()
            else:
                self.review_steps[step] = self._claude_review_step(step)

    def _claude_review_step(self, step: str) -> dict:
        model = {"native": self.cfg.models["review_tier"],
                 "lead": self.cfg.models["lead"],
                 "cto": self.cfg.models["cto"]}[step]
        rounds: list[dict] = []
        fixes = 0
        t0 = time.time()
        tok = []
        for rnd in range(1, self.cfg.max_rounds[step] + 1):
            mat = self.collect_materials()
            prompt = compose_review_prompt(self.cfg, self.ctx, step, mat)
            name = f"review-{step}-round{rnd}"
            proc, res = self.claude(name, prompt, model=model,
                                    timeout=self.cfg.timeouts["review_s"])
            tok.append(res.tokens() if res.ok else zero_tokens("unparsable"))
            fnd = parse_findings(res.text)
            rec = {
                "round": rnd, "model": model, "reviewed_sha": mat.review_sha,
                "proc": proc.summary(), **fnd.to_json(),
            }
            rounds.append(rec)
            self.path("reviews", f"review-{step}-round{rnd}.json").write_text(
                json.dumps(rec, indent=2), encoding="utf-8")
            if not fnd.ok:
                self.fail(name, "findings-unparsable", fnd.error or "unknown")
                break                       # a fix round on nothing is spend for nothing
            actionable = fnd.counts["critical"] + fnd.counts["important"]
            if actionable == 0:
                self.log(f"     {step} round {rnd}: CLEAN")
                break                       # fixpoint
            self.log(f"     {step} round {rnd}: {fnd.counts['critical']} critical, "
                     f"{fnd.counts['important']} important")
            if rnd >= self.cfg.max_rounds[step]:
                break                       # no round left to verify a fix in
            if self._apply_fix(f"{step}-round{rnd}", fnd, res.text or ""):
                fixes += 1
            else:
                break
        self.phases[f"review:{step}"] = time.time() - t0
        self.tokens[f"review:{step}"] = add_tokens(*tok)
        return {"ran": True, "skipped_reason": None, "rounds": rounds,
                "totals": _sum_rounds(rounds), "fix_rounds_applied": fixes}

    def _council_step(self) -> dict:
        """Cross-provider council: one seat per foreign provider, in parallel.

        An unavailable seat is a noted empty seat, never backfilled with
        another seat from a provider already present -- provider diversity is
        the whole point of the mechanism under test.
        """
        rounds: list[dict] = []
        fixes = 0
        t0 = time.time()
        tok: list[dict] = []
        for rnd in range(1, self.cfg.max_rounds["council"] + 1):
            mat = self.collect_materials()
            prompt = compose_council_prompt(self.cfg, self.ctx, mat)
            seats = {}
            results: dict[str, tuple[Proc, str | None]] = {}
            threads = []

            def go(seat_name: str, rnd: int = rnd) -> None:
                results[seat_name] = self.seat(
                    f"council-{seat_name}-round{rnd}", seat_name, prompt,
                    timeout=self.cfg.timeouts["council_s"])

            for seat_name in ("codex", "agy"):
                th = threading.Thread(target=go, args=(seat_name,),
                                      name=f"council-{seat_name}")
                th.start()
                threads.append(th)
            for th in threads:
                th.join(timeout=self.cfg.timeouts["council_s"] + 120)
                if th.is_alive():
                    self.fail("council", "seat-hung",
                              f"{th.name} did not return within its timeout")

            union = {b: 0 for b in SEVERITY_BUCKETS}
            union["total"] = 0
            any_ok = False
            for seat_name in ("codex", "agy"):
                proc, reply = results.get(seat_name, (None, None))
                fnd = parse_findings(reply)
                tok.append(estimated_tokens(prompt, reply or ""))
                seats[seat_name] = {
                    "proc": proc.summary() if proc else None,
                    **fnd.to_json(),
                }
                if fnd.ok:
                    any_ok = True
                    for b in SEVERITY_BUCKETS:
                        union[b] += fnd.counts[b]
                    union["total"] += fnd.counts["total"]
                else:
                    self.fail(f"council-{seat_name}-round{rnd}",
                              "findings-unparsable", fnd.error or "unknown")
            rec = {
                "round": rnd, "reviewed_sha": mat.review_sha,
                "seats": seats,
                "parse_ok": any_ok,
                "counts": union if any_ok else None,
                "union_note": "sum across seats; no cross-seat semantic "
                              "deduplication is attempted (A7)",
                "seats_filled": [s for s, v in seats.items() if v["parse_ok"]],
                "seats_empty": [s for s, v in seats.items() if not v["parse_ok"]],
            }
            rounds.append(rec)
            self.path("reviews", f"review-council-round{rnd}.json").write_text(
                json.dumps(rec, indent=2), encoding="utf-8")
            if not any_ok:
                break
            actionable = union["critical"] + union["important"]
            self.log(f"     council round {rnd}: {union['critical']} critical, "
                     f"{union['important']} important "
                     f"(seats filled: {rec['seats_filled']})")
            if actionable == 0:
                break                       # fixpoint
            if rnd >= self.cfg.max_rounds["council"]:
                break
            merged = [f for s in seats.values() for f in s["findings"]]
            prose = "\n".join(
                f"- ({s}) {v['parse_error'] or 'see findings'}"
                for s, v in seats.items() if not v["parse_ok"])
            fnd_all = Findings(True, merged, count_findings(merged), None, "council")
            if self._apply_fix(f"council-round{rnd}", fnd_all, prose):
                fixes += 1
            else:
                break
        self.phases["review:council"] = time.time() - t0
        self.tokens["review:council"] = add_tokens(*tok)
        return {"ran": True, "skipped_reason": None, "rounds": rounds,
                "totals": _sum_rounds(rounds), "fix_rounds_applied": fixes}

    def _apply_fix(self, tag: str, fnd: Findings, prose: str) -> bool:
        actionable = [f for f in fnd.findings
                      if f["severity"] in ("critical", "important")]
        if not actionable:
            return False
        mat = Materials(
            findings_json=json.dumps(actionable, indent=2),
            findings_prose=("### The reviewer's own words\n\n" + prose.strip()
                            if prose.strip() else ""),
        )
        prompt = compose_fix_prompt(self.cfg, self.ctx, mat)
        proc, res = self.claude(f"fix-{tag}", prompt,
                                 model=self.cfg.models["fix"],
                                 timeout=self.cfg.timeouts["fix_s"])
        # Bucketed as PRODUCT, under its own `fix:` key -- a fix round is
        # implementer work (RUNBOOK §8 counts a takeover as product), so
        # folding it into the review seat's total would inflate coordination
        # and deflate product in every arm that reviews at all.
        self.tokens[f"fix:{tag}"] = (res.tokens() if res.ok
                                     else zero_tokens("fix result unparsable"))
        self.phases[f"fix:{tag}"] = proc.duration_s
        self.refresh_head()
        self.check_exam_tamper()
        return res.ok

    # -- the yardstick -----------------------------------------------------

    def phase_audit(self) -> None:
        """The escaped-defect audit: identical for every regime, run last.

        This is the robustness metric. It runs against the FINAL server, after
        whatever review the regime did, and asks a fresh cross-provider pair
        what got through. Because the prompt is regime-independent by
        construction, the counts are comparable across arms.
        """
        t0 = time.time()
        mat = self.collect_materials()
        prompt = compose_audit_prompt(self.cfg, self.ctx, mat)
        results: dict[str, tuple[Proc, str | None]] = {}
        threads = []

        def go(seat_name: str) -> None:
            results[seat_name] = self.seat(f"audit-{seat_name}", seat_name,
                                           prompt, timeout=self.cfg.timeouts["council_s"])

        for seat_name in ("codex", "agy"):
            th = threading.Thread(target=go, args=(seat_name,), name=f"audit-{seat_name}")
            th.start()
            threads.append(th)
        for th in threads:
            th.join(timeout=self.cfg.timeouts["council_s"] + 120)
            if th.is_alive():
                self.fail("audit", "seat-hung", f"{th.name} did not return in time")

        seats: dict[str, dict] = {}
        union = {b: 0 for b in SEVERITY_BUCKETS}
        union["total"] = 0
        tok = []
        any_ok = False
        for seat_name in ("codex", "agy"):
            proc, reply = results.get(seat_name, (None, None))
            fnd = parse_findings(reply)
            tok.append(estimated_tokens(prompt, reply or ""))
            seats[seat_name] = {"proc": proc.summary() if proc else None,
                                **fnd.to_json()}
            if fnd.ok:
                any_ok = True
                for b in SEVERITY_BUCKETS:
                    union[b] += fnd.counts[b]
                union["total"] += fnd.counts["total"]
            else:
                self.fail(f"audit-{seat_name}", "findings-unparsable",
                          fnd.error or "unknown")
        self.escaped = {
            "ran": True,
            "audited_sha": mat.review_sha,
            "seats": seats,
            "parse_ok": any_ok,
            "counts": union if any_ok else None,
            "critical_important": (union["critical"] + union["important"]) if any_ok else None,
            "union_note": "sum across seats; no cross-seat semantic "
                          "deduplication is attempted (A7)",
            "seats_filled": [s for s, v in seats.items() if v["parse_ok"]],
            "seats_empty": [s for s, v in seats.items() if not v["parse_ok"]],
        }
        self.path("reviews", "audit-escaped-defects.json").write_text(
            json.dumps(self.escaped, indent=2), encoding="utf-8")
        self.tokens["audit"] = add_tokens(*tok)
        self.phases["audit"] = time.time() - t0
        if any_ok:
            self.log(f"     escaped defects (Critical+Important): "
                     f"{self.escaped['critical_important']}")

    # -- output ------------------------------------------------------------

    def manifest(self, ended: datetime | None) -> dict:
        final = self.grading_stages.get("final") or self.grading_stages.get("after_build") or {}
        coordination = add_tokens(*[self.tokens.get(f"review:{s}", {})
                                    for s in REVIEW_STEP_ORDER])
        product = add_tokens(self.tokens.get("build", {}),
                             *[v for k, v in self.tokens.items()
                               if k.startswith("fix:")])
        wall = (ended - self.started).total_seconds() if ended else \
            (utc_now() - self.started).total_seconds()
        esc_count = (self.escaped or {}).get("critical_important")

        man: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": iso(self.started),
            "ended_at": iso(ended) if ended else None,
            "regime": coarse_regime(self.cfg.toggles),
            "regime_name": self.cfg.regime,
            "target": self.cfg.target,
            "git_revision": self.base_sha,
            "injected_event": None,
            "ablation": ablation_of(self.cfg.toggles),
            "toggles": dict(self.cfg.toggles),
            "models": dict(self.cfg.models),
            "cost": {
                "coordination_tokens": int(coordination["total_tokens"]),
                "product_tokens": int(product["total_tokens"]),
                "model_calls": int(self.model_calls),
                "wall_clock_seconds": round(wall, 3),
                "human_intervention_minutes": 0.0,
                "lead_wait_seconds": None,
            },
            "grading": {
                "conformance_total": int(final.get("conformance_total", 0)),
                "conformance_passed": int(final.get("conformance_passed", 0)),
                "malformed_total": None,
                "malformed_passed": None,
                "escaped_defects": esc_count,
                "fix_introduced_regressions": _fix_regressions(self.grading_stages),
                "recovery_seconds_after_restart": None,
            },
            "grading_stages": self.grading_stages,
            "review_steps": self.review_steps,
            "escaped_defects": self.escaped,
            "tokens_by_phase": self.tokens,
            "wall_clock_by_phase": {k: round(v, 3) for k, v in self.phases.items()},
            "standup": self.standup_stats,
            "crystal": self.crystal_stats,
            "failures": self.failures,
            "meta_product_ratio": (
                round(coordination["total_tokens"] / product["total_tokens"], 4)
                if product["total_tokens"] else None),
            "artifacts": {
                "run_dir": str(self.run_dir),
                "run_tree": str(self.ctx.run_tree),
                "run_branch": self.run_branch,
                "head_sha": self.head_sha,
                "config": str(self.cfg.path),
                "prompts": "prompts/",
                "logs": "logs/",
                "reviews": "reviews/",
            },
            "harness": {
                "script": str(Path(__file__).resolve()),
                "framework": str(self.framework),
                "ask_agent": str(self.ask_agent),
                "input_hashes": self.ctx.input_hashes,
                "exam_tampered": self.exam_tampered,
                "grader": self.cfg.grader,
                "cost_bucketing": (
                    "coordination = review seats (native/council/lead/cto); "
                    "product = build + fix rounds; the escaped-defect audit is "
                    "the measuring instrument and is excluded from both "
                    "(RUNBOOK §8, assumption A9)"),
                "token_sources": (
                    "claude -p: summed modelUsage (the per-session aggregate); "
                    "foreign seats: estimated at characters/4 and flagged"),
            },
            "notes": (f"regime '{self.cfg.regime}' via run_regime.py; "
                      f"coarse class '{coarse_regime(self.cfg.toggles)}' derived "
                      "from the toggles (see manifest.schema.json regime_name)"),
        }
        return man

    def write_outputs(self, ended: datetime | None) -> dict:
        man = self.manifest(ended)
        schema_path = HARNESS_DIR / "manifest.schema.json"
        errors: list[str] = []
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            errors = validate_schema(man, schema)
        except (OSError, json.JSONDecodeError) as exc:
            errors = [f"could not load {schema_path}: {exc}"]
        if errors:
            # Recorded in the manifest itself, not raised: a manifest that
            # fails validation is still the only record of what happened.
            man.setdefault("failures", []).append({
                "phase": "manifest", "kind": "schema-invalid",
                "detail": "; ".join(errors[:20]), "at": iso(utc_now()),
            })
            for e in errors[:20]:
                print(f"  ! manifest schema: {e}", file=sys.stderr)
        out = self.run_dir / "manifest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(man, indent=2, sort_keys=False) + "\n",
                       encoding="utf-8")
        (self.run_dir / "SUMMARY.md").write_text(render_summary(self, man),
                                                 encoding="utf-8")
        (self.run_dir / "config.json").write_text(
            json.dumps(self.cfg.raw, indent=2) + "\n", encoding="utf-8")
        return man

    # -- driver ------------------------------------------------------------

    def execute(self) -> int:
        ended: datetime | None = None
        try:
            if not self.create_worktree():
                return 2
            self.phase_build()
            self.phase_grade("after_build")
            self.phase_reviews()
            self.phase_grade("final")
            self.phase_audit()
        except KeyboardInterrupt:
            self.fail("run", "interrupted", "the operator interrupted the run")
        except Exception as exc:                            # noqa: BLE001
            self.fail("run", "unhandled-exception", f"{type(exc).__name__}: {exc}")
        finally:
            ended = utc_now()
            try:
                man = self.write_outputs(ended)
                self.log(f"manifest: {self.run_dir / 'manifest.json'}")
                self.log(f"summary:  {self.run_dir / 'SUMMARY.md'}")
            except Exception as exc:                        # noqa: BLE001
                print(f"FATAL: could not write the manifest: {exc}", file=sys.stderr)
                return 3
        return 1 if self.failures else 0


def _tail(path: Path, n: int = 2000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-n:]


def _empty_totals() -> dict:
    d = {b: 0 for b in SEVERITY_BUCKETS}
    d.update({"total": 0, "rounds": 0, "rounds_unparsed": 0})
    return d


def _sum_rounds(rounds: list[dict]) -> dict:
    """Sum severities across a step's rounds.

    Rounds whose findings block did not parse contribute nothing to the
    counts and are counted separately as `rounds_unparsed` -- so a step whose
    reviewer emitted garbage reads as "1 round, 1 unparsed", never as "0
    findings" (A8).
    """
    tot = _empty_totals()
    for r in rounds:
        tot["rounds"] += 1
        counts = r.get("counts")
        if not r.get("parse_ok") or not isinstance(counts, dict):
            tot["rounds_unparsed"] += 1
            continue
        for b in SEVERITY_BUCKETS:
            tot[b] += int(counts.get(b, 0))
        tot["total"] += int(counts.get("total", 0))
    return tot


def _fix_regressions(stages: dict) -> int | None:
    """Assertions that passed after the build and stopped passing by the end.

    The bug class the whole review ladder exists to catch is the fix that
    breaks something -- so it gets its own number, or null when either grading
    stage did not produce one.
    """
    a, b = stages.get("after_build"), stages.get("final")
    if not a or not b or not a.get("ran") or not b.get("ran"):
        return None
    if not a.get("conformance_total") or not b.get("conformance_total"):
        return None
    lost = a["conformance_passed"] - b["conformance_passed"]
    return lost if lost > 0 else 0


def _stalled_agents(observe_text: str) -> list[str]:
    """Agent ids that `standup.sh observe` flagged as stalled."""
    out: list[str] = []
    current: str | None = None
    for line in observe_text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
        elif "STALL" in line and current:
            out.append(current)
            current = None      # one flag per agent per observe
    return out


def _conflict_stanzas(report: str) -> list[str]:
    """The `a@sha × b@sha` headers whose stanza reported a conflict."""
    stanzas: list[str] = []
    header: str | None = None
    for line in report.splitlines():
        if line.startswith("## "):
            header = line[3:].strip()
        elif header and (line.startswith("merge: CONFLICT")
                         or line.startswith("tests: FAIL")):
            stanzas.append(f"{header} — {line.strip()}")
            header = None
    return stanzas


def _crystal_skip_reason(cfg: Config) -> str:
    missing = [k for k in ("crystal", "parallel", "decomposition") if not cfg.toggles[k]]
    return ("crystal needs concurrent worker branches; off because "
            + ", ".join(f"{k} is off" for k in missing))


# --------------------------------------------------------------------------
# Human-readable summary
# --------------------------------------------------------------------------

def render_summary(run: "Run", man: dict) -> str:
    cfg = run.cfg
    L: list[str] = []
    A = L.append
    A(f"# Bench run — `{cfg.regime}` on `{cfg.target}`")
    A("")
    A(f"- **run id:** `{man['run_id']}`")
    A(f"- **started / ended:** {man['started_at']} → {man['ended_at']}")
    A(f"- **coarse regime:** `{man['regime']}`  ·  **ablation:** "
      f"{('`' + man['ablation'] + '`') if man['ablation'] else 'none named (see toggles)'}")
    A(f"- **branch:** `{man['artifacts']['run_branch']}` "
      f"(base `{man['git_revision'][:12]}`, head `{man['artifacts']['head_sha'][:12]}`)")
    A(f"- **tree:** `{man['artifacts']['run_tree']}`")
    A("")
    A("## Toggles")
    A("")
    A("| " + " | ".join(TOGGLE_KEYS) + " |")
    A("|" + "---|" * len(TOGGLE_KEYS))
    A("| " + " | ".join("ON" if cfg.toggles[k] else "off" for k in TOGGLE_KEYS) + " |")
    A("")
    A(f"Models: " + ", ".join(f"`{k}`={v}" for k, v in sorted(man["models"].items())))
    A("")
    A("## Grading — the frozen exam")
    A("")
    if not run.grading_stages:
        A("The exam never ran. See failures below.")
    else:
        A("| stage | passed | total | exit | note |")
        A("|---|---|---|---|---|")
        for tag, g in run.grading_stages.items():
            A(f"| {tag} | {g.get('conformance_passed')} | "
              f"{g.get('conformance_total')} | {g.get('exit_code')} | "
              f"{g.get('reason', '')} |")
    if run.exam_tampered:
        A("")
        A("> **The run tree's copy of the exam was modified.** Grading used the "
          "pristine copy; the modification is recorded as evidence.")
    A("")
    A("## Bugs caught, by review step")
    A("")
    A("| step | ran | rounds | critical | important | minor | unparsed rounds | fix rounds |")
    A("|---|---|---|---|---|---|---|---|")
    for step in REVIEW_STEP_ORDER:
        s = run.review_steps.get(step)
        if not s:
            A(f"| {step} | — | | | | | | |")
            continue
        t = s["totals"]
        A(f"| {step} | {'yes' if s['ran'] else 'no'} | {t['rounds']} | "
          f"{t['critical']} | {t['important']} | {t['minor']} | "
          f"{t['rounds_unparsed']} | {s['fix_rounds_applied']} |")
        if not s["ran"] and s.get("skipped_reason"):
            A(f"| | _{s['skipped_reason']}_ | | | | | | |")
    A("")
    A("## Escaped defects — the robustness yardstick")
    A("")
    if not run.escaped:
        A("The audit did not run.")
    elif not run.escaped.get("parse_ok"):
        A("Both audit seats failed to return a parsable findings block; the "
          "count is **null**, not zero. See failures below.")
    else:
        c = run.escaped["counts"]
        A(f"**{run.escaped['critical_important']}** Critical+Important survived "
          f"to the final server "
          f"(critical {c['critical']}, important {c['important']}, "
          f"minor {c['minor']}, unknown {c['unknown']}).")
        A("")
        A(f"Seats filled: {run.escaped['seats_filled'] or 'none'}; "
          f"empty: {run.escaped['seats_empty'] or 'none'}.")
        A("")
        for seat, v in run.escaped["seats"].items():
            if not v["parse_ok"]:
                continue
            A(f"**{seat}**")
            for f in v["findings"]:
                A(f"- `{f['severity']}` {f['claim']}")
            A("")
    A("## Cost")
    A("")
    cost = man["cost"]
    A(f"- coordination tokens: **{cost['coordination_tokens']:,}**")
    A(f"- product tokens: **{cost['product_tokens']:,}**")
    A(f"- meta:product ratio: **{man['meta_product_ratio']}**")
    A(f"- model calls: {cost['model_calls']} · wall clock: "
      f"{cost['wall_clock_seconds']:.0f}s · human intervention: "
      f"{cost['human_intervention_minutes']} min")
    A("")
    A("| phase | tokens | estimated? | seconds |")
    A("|---|---|---|---|")
    for phase, tk in man["tokens_by_phase"].items():
        A(f"| {phase} | {int(tk.get('total_tokens', 0)):,} | "
          f"{'yes' if tk.get('estimated') else 'no'} | "
          f"{man['wall_clock_by_phase'].get(phase, 0):.0f} |")
    A("")
    A("> Foreign-seat token counts are estimated at characters/4 (assumption "
      "A3) and must not be compared with measured figures without saying so. "
      "The escaped-defect audit is excluded from the cost buckets: it is the "
      "measuring instrument, not work the org did.")
    A("")
    if run.standup_stats.get("ran") or run.crystal_stats.get("ran"):
        A("## Situational awareness")
        A("")
        if run.standup_stats.get("ran"):
            s = run.standup_stats
            A(f"- **standup:** {s['observes']} observes, {s['stalls_seen']} "
              f"stall flags, {s['redirects']} redirects sent, {s['errors']} errors.")
        if run.crystal_stats.get("ran"):
            c = run.crystal_stats
            A(f"- **crystal:** {c['checks']} speculative checks, "
              f"{c['conflicts']} reporting a conflict, {c['errors']} errors.")
            for r in c["reports"]:
                for st in r["stanzas"]:
                    A(f"  - check #{r['check']}: {st}")
        elif run.crystal_stats.get("skipped_reason"):
            A(f"- **crystal:** skipped — {run.crystal_stats['skipped_reason']}")
        A("")
    A("## Failures")
    A("")
    if not run.failures:
        A("None recorded.")
    else:
        for f in run.failures:
            A(f"- **{f['phase']}/{f['kind']}** — {f['detail']}")
    A("")
    A("## Cleaning up")
    A("")
    A("This run left a git worktree and a branch behind on purpose — they are "
      "the evidence. When you are finished with them:")
    A("")
    A("```bash")
    A(f"git -C {man['harness']['framework']} worktree remove --force "
      f"{man['artifacts']['run_tree']}")
    A(f"git -C {man['harness']['framework']} branch -D {man['artifacts']['run_branch']}")
    A("```")
    A("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------

def dry_run(cfg: Config, args: argparse.Namespace) -> int:
    started = utc_now()
    ts = stamp(started)
    run_id = args.run_id or f"dry-{ts}-{cfg.regime}-{cfg.target}"
    run_branch = f"bench-run/{cfg.regime}-{ts}"
    run_dir = Path(args.runs_root).resolve() / run_id
    framework = Path(args.framework).resolve()
    ctx = build_ctx(cfg, framework, run_id, run_dir, run_branch)

    prompts: dict[str, str] = {"build": compose_build_prompt(cfg, ctx)}
    for step in ("native", "lead", "cto"):
        if cfg.steps[step]:
            prompts[f"review-{step}"] = compose_review_prompt(cfg, ctx, step, DRY_MATERIALS)
    if cfg.steps["council"]:
        prompts["council-seat"] = compose_council_prompt(cfg, ctx, DRY_MATERIALS)
    prompts["fix"] = compose_fix_prompt(cfg, ctx, DRY_MATERIALS)
    prompts["audit-seat"] = compose_audit_prompt(cfg, ctx, DRY_MATERIALS)

    pdir = run_dir / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    for name, text in prompts.items():
        (pdir / f"{name}.txt").write_text(text, encoding="utf-8")

    out: list[str] = []
    A = out.append
    A("=" * 78)
    A(f"DRY RUN — regime '{cfg.regime}' on target '{cfg.target}'")
    A("=" * 78)
    A("")
    A(f"config          {cfg.path}")
    A(f"framework       {framework}")
    A(f"run id          {run_id}")
    A(f"run dir         {run_dir}")
    A(f"worktree        {run_dir / 'tree'}   (WOULD be created; not created now)")
    A(f"branch          {run_branch}  <- off refs/heads/master")
    A(f"worker branches {ctx.worker_branch_prefix}<id> for id in "
      f"{cfg.worker_ids if cfg.toggles['decomposition'] else '(none — no decomposition)'}")
    A(f"worker trees    {ctx.workers_dir}/<id>")
    A("")
    A("TOGGLES")
    for k in TOGGLE_KEYS:
        A(f"  {k:<14} {'ON' if cfg.toggles[k] else 'off'}")
    A("")
    A("MODELS (after tier collapse)" if not cfg.toggles["tiering"] else "MODELS")
    for role in MODEL_ROLES:
        A(f"  {role:<14} {cfg.models.get(role)}")
    A("")
    A(f"DOCTRINE BLOCK  {'included' if cfg.doctrine else 'OMITTED (goal-directed arm)'}")
    A("")
    A("PLAN")
    builder = "LEAD (decomposes, spawns workers)" if cfg.toggles["decomposition"] \
        else "SOLO IMPLEMENTER (whole spec, goal-directed)"
    A(f"  1. build        {builder}")
    A(f"                  model={cfg.builder_model} (role={cfg.builder_role})"
      f"  timeout={int(cfg.timeouts['build_s'])}s")
    if cfg.toggles["decomposition"]:
        A(f"                  workers run "
          f"{'IN PARALLEL' if cfg.toggles['parallel'] else 'SEQUENTIALLY'} "
          f"at model={cfg.models['worker']}")
    if cfg.toggles["standup"]:
        A(f"     · standup loop every {cfg.standup['interval_s']}s "
          f"(stall threshold {cfg.standup['stall_min']} min, redirect cooldown "
          f"{cfg.standup['redirect_cooldown_s']}s)")
    else:
        A("     · standup loop NOT started")
    if crystal_active(cfg):
        server_dir = str(Path(cfg.server_path).parent) or "."
        A(f"     · crystal loop every {cfg.crystal['interval_s']}s, test-cmd "
          f"{cfg.crystal['test_cmd'] or f'python3 -m compileall -q {server_dir}'!r}")
    else:
        A(f"     · crystal loop NOT started — {_crystal_skip_reason(cfg)}")
    A(f"  2. grade        frozen exam (pristine copy) under nix, tag=after_build")
    A("  3. review steps, each recorded separately:")
    for step in REVIEW_STEP_ORDER:
        if not cfg.steps[step]:
            A(f"       {step:<8} OFF")
            continue
        if step == "council":
            A(f"       {step:<8} ON  seats=codex+agy (parallel), "
              f"max {cfg.max_rounds[step]} round(s), fix between rounds")
        else:
            model = {"native": cfg.models["review_tier"], "lead": cfg.models["lead"],
                     "cto": cfg.models["cto"]}[step]
            A(f"       {step:<8} ON  model={model}, max {cfg.max_rounds[step]} "
              f"round(s), fix between rounds at model={cfg.models['fix']}")
    A("  4. grade        frozen exam again, tag=final")
    A("  5. audit        escaped defects: codex+agy against the FINAL server "
      "(regime-independent prompt)")
    A("  6. manifest     manifest.json (schema-validated) + SUMMARY.md")
    A("")
    A("TOGGLE CONFORMANCE OF THE COMPOSED BUILD PROMPT")
    A("  Each mechanism is checked in BOTH directions: its marker must be")
    A("  present when it is on and absent when it is off.")
    A("")
    checks = toggle_conformance(cfg, prompts["build"])
    A(f"  {'mechanism':<15}{'state':<7}{'marker':<22}{'expect':<9}{'actual':<9}result")
    bad = 0
    for c in checks:
        if not c.ok:
            bad += 1
        A(f"  {c.mechanism:<15}{c.state:<7}{c.marker:<22}"
          f"{('present' if c.expected_present else 'absent'):<9}"
          f"{('present' if c.actually_present else 'absent'):<9}"
          f"{'OK' if c.ok else '*** MISMATCH ***'}")
    A("")
    A("  step prompts composed: "
      + ", ".join(sorted(k for k in prompts if k.startswith(("review-", "council")))) or "  (none)")
    A(f"  council prompt composed: {'yes' if 'council-seat' in prompts else 'no'} "
      f"(council toggle {'ON' if cfg.steps['council'] else 'off'})")
    A("")
    A("COMPOSED PROMPTS")
    for name, text in prompts.items():
        h = hashlib.sha256(text.encode()).hexdigest()[:12]
        A(f"  {name:<16} {len(text):>8,} chars  sha256:{h}  "
          f"{pdir / (name + '.txt')}")
    A("")
    confounds = spec_confounds(cfg, ctx.spec_text)
    if confounds:
        A("SHARED-INPUT NOTE (not a composition error — an operator decision)")
        A(f"  The spec {cfg.spec_path} is shared by every arm, and it uses")
        A("  protocol vocabulary for mechanisms this arm has switched OFF:")
        for mech, term in confounds:
            A(f"    {mech:<15} spec says {term!r}")
        A("  The build prompt adds no such machinery, but the agent still")
        A("  reads these words in the spec. Editing the spec per arm would")
        A("  break the 'identical target' invariant, so this is surfaced")
        A("  rather than patched. Decide whether it matters for this study.")
        A("")
    A(f"INPUT HASHES (pinned material read from {framework})")
    for k, v in ctx.input_hashes.items():
        A(f"  {k:<10} {v}")
    A("")
    A("Nothing was launched. No worktree, no branch, no agent, no tokens.")
    A(f"{'ALL TOGGLE CHECKS PASSED' if bad == 0 else f'{bad} TOGGLE CHECK(S) FAILED'}")
    A("=" * 78)
    text = "\n".join(out)
    print(text)
    (run_dir / "PLAN.txt").write_text(text + "\n", encoding="utf-8")

    if args.print_prompt:
        if args.print_prompt not in prompts:
            print(f"\n(no prompt named {args.print_prompt!r}; have: "
                  f"{', '.join(sorted(prompts))})", file=sys.stderr)
            return 2
        print("\n" + "=" * 78)
        print(f"PROMPT: {args.print_prompt}")
        print("=" * 78)
        print(prompts[args.print_prompt])
    return 1 if bad else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_regime.py",
        description="Run one isolated benchmark regime end to end and write "
                    "its manifest.")
    p.add_argument("--config", required=True, type=Path,
                   help="regime config JSON (bench/regimes/configs/*.json)")
    p.add_argument("--framework", default=str(DEFAULT_FRAMEWORK),
                   help="the pristine worktree holding the doctrine, runbook, "
                        "spec, frozen exam and tooling (default: this "
                        "script's own worktree)")
    p.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT),
                   help=f"where run directories are created "
                        f"(default: {DEFAULT_RUNS_ROOT})")
    p.add_argument("--ask-agent", default=str(DEFAULT_ASK_AGENT),
                   help="path to the ask-agent query script used for the "
                        "foreign council seats")
    p.add_argument("--run-id", default=None,
                   help="override the generated run id")
    p.add_argument("--dry-run", action="store_true",
                   help="compose every prompt, check the toggle conformance, "
                        "print the plan — and launch nothing")
    p.add_argument("--print-prompt", default=None, metavar="NAME",
                   help="with --dry-run, also print one composed prompt in "
                        "full (e.g. build, review-native, audit-seat)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(Path(args.config).resolve())
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.dry_run:
            return dry_run(cfg, args)
        for tool in ("claude", "git", "nix"):
            if shutil.which(tool) is None:
                print(f"required tool not on PATH: {tool}", file=sys.stderr)
                return 2
        run = Run(cfg, args)
        run.log(f"run {run.run_id}  regime={cfg.regime}  target={cfg.target}")
        return run.execute()
    except (ConfigError, PromptError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
