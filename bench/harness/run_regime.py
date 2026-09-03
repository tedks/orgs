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
    "startup_grace_s": 900,     # no redirects until an agent has had time
                                # to produce its first commit
}

DEFAULT_CRYSTAL = {
    "interval_s": 600,
    "timeout_s": 120,           # passed to crystal-check.sh --timeout
    "test_cmd": None,           # None -> derived compileall on the server dir
}

# Review steps, in the order they run. Council sits at the implementer's tier
# per RUNBOOK §6 (self-review, council, one-rung-up), so it runs before lead.
REVIEW_STEP_ORDER = ("native", "council", "lead", "cto")

# The foreign provider seats, named once. The council and the audit MUST
# use the same list: the audit is the yardstick every arm is measured
# with, and a yardstick with a different number of seats in different
# arms is not one.
COUNCIL_SEATS = ("codex", "agy")

# The standup bus lives inside the run tree and is in no .gitignore. It must
# stay out of BOTH the dirtiness test and the sweep commit: out of the commit
# because otherwise every seed, redirect and crystal message enters the diff
# handed to the reviewer and the audit (giving standup-ON arms a different
# yardstick input), and out of the test because a tree that is dirty only
# there would stage nothing and fail the commit.
SWEEP_EXCLUDE = ":(exclude).standup"

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
    orphans_swept: bool = False

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
            "orphans_swept": self.orphans_swept,
        }


def _group_alive(pgid: int) -> bool:
    """Is any process still in this group? Signal 0 tests without delivering."""
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # it exists; we merely may not signal it


def _kill_group(pgid: int, *, term_grace: float = 10.0,
                kill_grace: float = 5.0) -> None:
    """SIGTERM a process GROUP, then SIGKILL whatever is still in it.

    The group, not the leader: an agent CLI spawns children (a test run, a
    server it started, a nested agent), and killing only the leader leaves
    them running -- holding ports, mutating a worktree, and billing tokens
    into the NEXT regime's wall clock. `start_new_session=True` at spawn is
    what makes the group ours to kill.

    Waits on the GROUP rather than on the leader. An earlier version returned
    as soon as the leader exited, which is exactly when an orphaned server is
    still alive and the sweep was needed most.
    """
    for sig, grace in ((signal.SIGTERM, term_grace), (signal.SIGKILL, kill_grace)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            if not _group_alive(pgid):
                return
            time.sleep(0.2)


# Environment this session carries that must NOT reach a benchmark agent.
# Each regime is supposed to be "a fresh process, no inherited context";
# inheriting the orchestrator's own session ids, transcript paths and
# messaging sockets makes that false, and can let a "fresh" reviewer resume
# or message its way back into the context it is supposed to lack.
AGENT_ENV_PREFIXES = ("CLAUDE", "ANTHROPIC_SESSION", "CLAUDECODE",
                      "CODEX", "GEMINI", "ANTIGRAVITY", "AGY")
# Credentials and configuration the seats need in order to run at all. The
# prefixes above are deliberately broad, and a broad scrub that took a
# provider's API key with it would not corrupt the study -- it would simply
# make that seat fail, silently converting a councilled arm into an
# un-councilled one. Everything a CLI authenticates or configures itself with
# is named here explicitly.
AGENT_ENV_KEEP = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN",
    "CODEX_HOME", "CODEX_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
    "ANTIGRAVITY_HOME",
)


def _is_agent_env(key: str) -> bool:
    if key in AGENT_ENV_KEEP:
        return False
    up = key.upper()
    return any(up.startswith(pfx) for pfx in AGENT_ENV_PREFIXES)


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        return
    _kill_group(pgid)


def run_capture(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    stdin_data: str | None = None,
    env: dict[str, str] | None = None,
    scrub_agent_env: bool = False,
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
    if scrub_agent_env:
        for k in list(proc_env):
            if _is_agent_env(k):
                proc_env.pop(k, None)
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
        try:
            pgid = os.getpgid(p.pid)
        except (ProcessLookupError, PermissionError):
            pgid = None
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
        # Sweep the group even when the leader exited CLEANLY. A clean exit is
        # not evidence that nothing survives: the conformance exam backgrounds
        # a server, an agent can leave a child behind, and a survivor holds a
        # TCP port and keeps mutating a worktree into the NEXT regime -- an
        # isolation leak between runs that no error would ever report.
        orphans_swept = False
        if pgid is not None and _group_alive(pgid):
            orphans_swept = True
            _kill_group(pgid, term_grace=5.0, kill_grace=5.0)
        return Proc(argv, p.returncode, timed_out, time.time() - t0,
                    str(stdout_path) if stdout_path else None,
                    str(stderr_path) if stderr_path else None,
                    orphans_swept=orphans_swept)
    finally:
        for h in (so, se):
            if hasattr(h, "close"):
                h.close()


def git_to_file(args: list[str], *, cwd: Path, timeout: float, out: Path,
                cap: int) -> tuple[int, str, bool]:
    """Run git with its stdout streamed to a FILE, then read back at most
    `cap` bytes.

    For `git diff`, whose size an agent controls: capture_output() buffers the
    whole thing in this process first, so a committed multi-gigabyte file
    would exhaust memory and kill the overnight run before it wrote any
    evidence. Streaming to disk bounds what ever reaches memory.

    Returns (returncode, text, truncated).
    """
    err = out.with_suffix(out.suffix + ".err")
    proc = run_capture(["git", *args], cwd=cwd, timeout=timeout,
                       stdout_path=out, stderr_path=err)
    if proc.spawn_error or proc.timed_out:
        return (124 if proc.timed_out else 127), "", False
    try:
        size = out.stat().st_size
        with open(out, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(cap)
    except OSError:
        return (proc.returncode if proc.returncode is not None else 127), "", False
    return proc.returncode or 0, text, size > cap


def git(args: list[str], *, cwd: Path, timeout: float) -> tuple[int, str, str]:
    """Run a small, bounded git command and capture its output in memory.

    Only for commands whose output is known-small: rev-parse, worktree add,
    for-each-ref, status --porcelain. Anything an AGENT can make arbitrarily
    large (a diff, a file listing) goes through `git_to_file` instead.
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
    vocabulary: str
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
    out.setdefault("implementer", lead)
    # The native reviewer is described to itself as "a peer reviewer at the
    # implementer's own tier", so it defaults to whoever BUILDS in this
    # regime -- the worker under decomposition, the solo implementer
    # otherwise. Defaulting it to `worker` in a goal-directed arm put a
    # cheaper model in a seat whose prompt claims parity.
    out.setdefault("review_tier",
                   out["worker"] if toggles["decomposition"] else out["implementer"])
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

    vocabulary = ("legacy" if "review" in raw["toggles"] else "split")
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

    # Nested blocks get the same treatment as the top level: an unknown key
    # here is a setting that was meant to change the run and silently did
    # not, and a wrongly-typed one is a TypeError hours into an unattended
    # run rather than a message before it starts.
    def _nested(name: str, defaults: dict, numeric: tuple[str, ...]) -> dict:
        """Return ONLY the keys the config actually set.

        Returning a defaults-filled dict and then `.update()`-ing it over the
        target wrote the DEFAULT interval back over the value already derived
        from `standup_interval_min` -- so the helper written to stop a setting
        silently not taking effect did exactly that.
        """
        out: dict[str, Any] = {}
        block = raw.get(name)
        if block is None:
            return out
        # `is None` above, not truthiness: an empty list, "", 0 or false are
        # malformed blocks, and treating them as absent skipped validation.
        if not isinstance(block, dict):
            raise ConfigError(f"{where}: '{name}' must be an object")
        unknown = set(block) - set(defaults)
        if unknown:
            raise ConfigError(f"{where}: unknown {name} key(s) "
                              f"{sorted(unknown)}")
        for k, v in block.items():
            if k in numeric:
                out[k] = _positive(v, f"{name}.{k}")
            else:
                out[k] = v
        return out

    standup = dict(DEFAULT_STANDUP)
    if "standup_interval_min" in raw:
        standup["interval_s"] = _positive(raw["standup_interval_min"],
                                          "standup_interval_min") * 60
    standup.update(_nested("standup", DEFAULT_STANDUP,
                           ("interval_s", "stall_min", "redirect_cooldown_s",
                            "startup_grace_s")))
    crystal = dict(DEFAULT_CRYSTAL)
    if "crystal_interval_min" in raw:
        crystal["interval_s"] = _positive(raw["crystal_interval_min"],
                                          "crystal_interval_min") * 60
    block = _nested("crystal", DEFAULT_CRYSTAL, ("interval_s", "timeout_s"))
    if block.get("test_cmd") is not None and not isinstance(block["test_cmd"], str):
        raise ConfigError(f"{where}: crystal.test_cmd must be a string")
    crystal.update(block)

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

    # Write the resolved ladder BACK onto the toggle vector, so there is one
    # source of truth. Previously `review_steps` could switch a rung on or
    # off while `toggles` -- which is what the manifest, the coarse regime
    # and the ablation name are computed from -- still described the other
    # arrangement, i.e. the record would not say what ran.
    toggles["review_native"] = steps["native"]
    toggles["review_lead"] = steps["lead"]
    toggles["review_cto"] = steps["cto"]
    toggles["council"] = steps["council"]
    toggles["review"] = any(toggles[k] for k in REVIEW_TOGGLES)

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
        vocabulary=vocabulary,
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
    "parallel": "parallel",
    "review_native": "review_native",
    "review_lead": "review_lead",
    "review_cto": "review_cto",
}

# `review` is the OR of the three rungs, so it is off only when all three
# are. Counting both it and the rungs would make a single-rung ablation look
# like several mechanisms at once and yield no name at all.
ABLATION_DERIVED = ("review",)


def ablation_keys(toggles: dict[str, bool], vocabulary: str) -> list[str]:
    """The mechanisms this regime switches OFF, named in its own vocabulary.

    Vocabulary matters. A legacy config has one `review` toggle and has never
    heard of the CTO rung, so `review_cto: False` there means "not part of
    this vocabulary", not "ablated" -- reading it as an ablation made
    protocol-full, which is supposed to be everything-on, report itself as the
    review_cto ablation.

    A split-vocabulary config names each rung, so each is ablatable on its
    own; but when ALL THREE are off that is the single `review` ablation, not
    three.
    """
    if vocabulary == "legacy":
        keys = list(MECHANISM_TOGGLES) + ["review"]
    else:
        rungs_off = [k for k in REVIEW_TOGGLES if not toggles.get(k, True)]
        if len(rungs_off) == len(REVIEW_TOGGLES):
            keys = list(MECHANISM_TOGGLES) + ["review"]
        else:
            keys = list(MECHANISM_TOGGLES) + list(REVIEW_TOGGLES)
    return sorted(ABLATION_NAMES[k] for k in keys if not toggles.get(k, True))


def ablation_of(toggles: dict[str, bool], vocabulary: str = "split") -> str | None:
    """Which single mechanism this regime removes, or None.

    None when nothing is off (protocol-full) or when more than one thing is
    off (raw, r5, r6) -- in those cases a single name would be a lie, and
    `ablation_set` carries the full truth instead.
    """
    off = ablation_keys(toggles, vocabulary)
    return off[0] if len(off) == 1 else None


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
    def agent_token(self) -> str:
        """A token unique to THIS run, used to build every standup agent id.

        standup.sh finds an agent's last activity with
        `git log --all --fixed-strings --grep=<agent-id>`, and `--all` in this
        bare-repo layout means every ref in the whole project. With ids like
        `codec`, `engine`, `server` or `lead`, that grep matches unrelated
        commits on master and on other runs' branches -- measured on the real
        repo: `codec` matched 12 commits, the newest 344 minutes old. Every
        agent therefore reads as stalled from the first observe, and the
        standup-ON arms get a stream of fabricated "you have not committed"
        redirects that the standup-OFF arms never see. That is not a
        measurement of situational awareness; it is harassment applied to
        half the study.

        A run-unique token cannot appear in history, so a match means the
        agent really did commit, in this run.
        """
        return "bench" + hashlib.sha256(
            f"{self.run_id}|{self.run_branch}".encode()).hexdigest()[:8]

    def standup_id(self, short: str) -> str:
        return f"{self.agent_token}-{short}"

    @property
    def lead_agent_id(self) -> str:
        return self.standup_id("lead")

    @property
    def solo_agent_id(self) -> str:
        return self.standup_id("implementer")

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


# Runbook sections and the mechanism each one instructs. The runbook is the
# lead's PROCESS document -- for a process ablation it is not a shared input
# like the spec, it IS the independent variable. Handing r4 (crystal off) a
# runbook whose §7 tells it to run speculative merge checks means the arm was
# still instructed to do the thing that was supposedly removed, and r3-vs-r4
# then measures a background loop rather than the mechanism.
RUNBOOK_SECTION_GATES = {
    "5. standup": "standup",
    "6. review ladder": "review",
    "7. speculative merge check": "crystal",
}


def filter_runbook(runbook: str, toggles: dict[str, bool]) -> tuple[str, list[str]]:
    """Drop the runbook sections whose mechanism this arm does not have.

    A removed section leaves a visible stub naming what was removed, rather
    than a silent gap in the numbering -- a lead that notices §6 is missing
    would otherwise go looking for it, and finding nothing is a worse
    instruction than being told plainly that this arm does not do that.

    Returns (filtered text, the names of the removed sections).
    """
    lines = runbook.splitlines()
    out: list[str] = []
    removed: list[str] = []
    skipping: str | None = None
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip()
            low = heading.lower()
            gate = next((tog for key, tog in RUNBOOK_SECTION_GATES.items()
                         if low.startswith(key)), None)
            if gate is not None and not toggles.get(gate, True):
                skipping = heading
                removed.append(heading)
                out.append(f"## {heading}")
                out.append("")
                out.append(f"**REMOVED for this run — `{gate}` is OFF.** This "
                           "arm of the benchmark does not run this step. Do "
                           "not perform it and do not produce its artifacts.")
                out.append("")
                continue
            skipping = None
        if skipping is None:
            out.append(line)
    text = "\n".join(out)
    if runbook.endswith("\n"):
        text += "\n"          # splitlines() drops it; an all-on arm must get
                              # the document back byte-for-byte
    return text, removed


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


def crystal_test_cmd(cfg: Config) -> str:
    server_dir = str(Path(cfg.server_path).parent) or "."
    return cfg.crystal["test_cmd"] or f"python3 -m compileall -q {server_dir}"


def _worker_id_table(cfg: Config, ctx: Ctx) -> str:
    """The short id (branch, directory, status file) beside the run-unique
    tracking id (commit messages, standup bus).

    Two ids because they answer to two different consumers: git wants a name a
    human can read in `git branch`, and `standup.sh` greps `git log --all` --
    across every ref in a shared bare repo -- so its id has to be one that
    cannot occur anywhere else.
    """
    rows = ["  | short id | tracking id (in every commit message) |",
            "  |---|---|"]
    for w in cfg.worker_ids:
        rows.append(f"  | `{w}` | `Bench-Agent: {ctx.standup_id(w)}` |")
    rows.append(f"  | `lead` (you) | `Bench-Agent: {ctx.lead_agent_id}` |")
    return "\n".join(rows)


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
        # The spec is shared by every arm and describes a team protocol. A
        # goal-directed arm is the control for that protocol, so it is told
        # plainly that the process half of the spec is not its job -- without
        # which the control arm reads "produce every protocol artifact" as a
        # GOAL and starts doing the thing it exists to be the absence of.
        return render(load_template("implementer_solo.md"), {
            "PROTOCOL_PREAMBLE": _protocol_preamble(cfg, ctx),
            "TARGET": cfg.target,
            "RUN_TREE": str(ctx.run_tree),
            "RUN_BRANCH": ctx.run_branch,
            "SERVER_PATH": cfg.server_path,
            "SPEC": ctx.spec_text,
            "EXAM": ctx.exam_text,
            "SPEC_SCOPE_NOTE": load_template("frag_spec_scope_note.md"),
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
        if cfg.toggles["standup"]:
            delivery = load_template("frag_crystal_delivery_bus.md")
        else:
            # No bus means nothing can push a conflict to the lead. Saying so,
            # and handing it the command, is honest; the previous text
            # promised reports "at standup" that could never arrive.
            delivery = render(
                load_template("frag_crystal_delivery_selfserve.md"),
                {"CRYSTAL": str(ctx.crystal_script),
                 "RUN_BRANCH": ctx.run_branch,
                 "CRYSTAL_TEST_CMD": crystal_test_cmd(cfg)},
                where="frag_crystal_delivery_selfserve.md")
        crystal_section = render(load_template("frag_crystal_lead.md"),
                                 {"RUN_BRANCH": ctx.run_branch,
                                  "CRYSTAL_DELIVERY": delivery},
                                 where="frag_crystal_lead.md")
    # The whole instruction, both branches, lives in PARALLEL_NOTE. Previously
    # the surrounding bullet said "all in ONE message, so they run
    # concurrently" unconditionally and only the note flipped -- so the
    # sequential arm was told both things and could honour either.
    parallel_note = (
        "**Spawn the workers with your `Agent` tool, all in ONE message**, so "
        "they run concurrently rather than one after another. One message, "
        "several `Agent` calls: that is what makes them run at the same time. "
        "Spawning them one per message serialises the sprint and is not what "
        "this run is measuring."
        if cfg.toggles["parallel"] else
        "**This run is SEQUENTIAL by configuration.** Spawn ONE worker, wait "
        "for it to finish, merge it, then spawn the next. Never have two "
        "workers running at the same time and never put two `Agent` calls in "
        "one message — concurrency is the variable that is switched off in "
        "this arm."
    )
    return render(load_template("lead.md"), {
        "PROTOCOL_PREAMBLE": _protocol_preamble(cfg, ctx),
        "TARGET": cfg.target,
        "RUN_TREE": str(ctx.run_tree),
        "RUN_BRANCH": ctx.run_branch,
        "WORKERS_DIR": str(ctx.workers_dir),
        "WORKER_BRANCH_PREFIX": ctx.worker_branch_prefix,
        "WORKER_ID_TABLE": _worker_id_table(cfg, ctx),
        "WORKER_MODEL": cfg.models["worker"],
        "SERVER_PATH": cfg.server_path,
        "SPEC": ctx.spec_text,
        "EXAM": ctx.exam_text,
        "RUNBOOK": filter_runbook(ctx.runbook_text, cfg.toggles)[0],
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


def compose_review_prompt(cfg: Config, ctx: Ctx, step: str, mat: "Materials",
                          review_cwd: Path | None = None,
                          have_no_tree: bool = False) -> str:
    """`review_cwd` is where the reviewer will actually stand.

    It is NOT the product tree: reviewers run in a detached checkout of the
    frozen sha so they cannot edit what they judge. Telling them the product
    tree is "your working directory" -- which the prompt did while the process
    ran somewhere else -- both misdirects them and invites the write the
    detached worktree exists to prevent.
    """
    title, stance = REVIEW_ROLE_TEXT[step]
    return render(load_template("review_claude.md"), {
        "PROTOCOL_PREAMBLE": _protocol_preamble(cfg, ctx),
        "ROLE_TITLE": title,
        "ROLE_STANCE": stance,
        "REVIEW_SHA": mat.review_sha,
        "RUN_BRANCH": ctx.run_branch,
        "RUN_TREE": str(review_cwd or ctx.run_tree),
        "TREE_NOTE": (
            "Your working directory is a checkout of exactly that revision. "
            "You may read anything in it, but review that revision — not "
            "whatever the tree may hold later."
            if not have_no_tree else
            "**You have no checkout this round** — your working directory is "
            "empty. Review the diff and the source inlined below and nothing "
            "else; do not go looking for files."),
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
    before a single token is spent.

    `tree` is the clean detached checkout of `review_sha` -- where the
    reviewers stand and where the inlined source was read from. None when the
    checkout could not be made.
    """
    diff: str = ""
    server_code: str = ""
    review_sha: str = ""
    findings_json: str = "[]"
    findings_prose: str = ""
    tree: Path | None = None
    # True only when the ENTRY POINT's actual body was inlined. The council
    # and audit prompts carry no diff, so a seat with this false would be
    # reviewing nothing -- and its empty reply would be banked as a clean
    # round. The callers refuse to run in that case.
    server_inlined: bool = False


DRY_MATERIALS = Materials(
    diff="<<DRY RUN: the diff of the run branch against its base goes here>>",
    server_code="<<DRY RUN: the built server's source files go here>>",
    review_sha="<<DRY RUN: the frozen commit sha goes here>>",
    findings_json='[{"severity": "Critical", "claim": "<<DRY RUN: a finding>>"}]',
    findings_prose="<<DRY RUN: the reviewer's prose goes here>>",
    server_inlined=True,
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
             "total_tokens": 0, "source": "unavailable", "estimated": False,
             "incomplete": True}
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
    out["incomplete"] = source.startswith("usage")
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
            "total_tokens": 0, "source": reason, "estimated": False,
            "incomplete": True}


def add_tokens(*buckets: dict) -> dict:
    """Sum token buckets, carrying the QUALITY flags forward.

    `estimated` and `incomplete` must survive aggregation. They did not:
    every coordination bucket is an add_tokens() aggregate, and the
    incompleteness check downstream read `source`, which was dropped here --
    so the check worked for `product` (raw dicts) and was permanently dead
    for `coordination`, the bucket the review-ladder ablation is compared on.
    """
    out = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
           "total_tokens": 0}
    estimated = False
    incomplete = False
    for b in buckets:
        if not b:
            continue
        for k in ("input", "output", "cache_read", "cache_creation", "total_tokens"):
            out[k] += int(b.get(k) or 0)
        estimated = estimated or bool(b.get("estimated"))
        incomplete = incomplete or _is_incomplete(b)
    out["estimated"] = estimated
    out["incomplete"] = incomplete
    return out


def _is_incomplete(bucket: dict) -> bool:
    """A figure that is neither a full measurement nor an honest estimate."""
    if bucket.get("incomplete"):
        return True
    source = str(bucket.get("source") or "")
    return source.startswith("unavailable") or "last turn" in source


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
                              "stalls_seen": 0, "stalls_in_grace": 0,
                              "errors": 0, "agents": []}
        self.crystal_stats = {"ran": False, "checks": 0, "attempts": 0,
                              "conflicts": 0, "real_conflicts": 0,
                              "delivered": 0, "undelivered": 0,
                              "noisy_branches": [], "errors": 0, "reports": [],
                              "branchless_attempts": 0,
                              "suppressed_repeats": 0}
        self.worktree_created = False
        self.base_sha = "unknown"
        self.head_sha = "unknown"
        self.exam_tampered: bool | None = None
        self.frozen_exam: Path | None = None
        self.swept: list[dict] = []
        self.seat_invocations = 0
        self.models_observed: dict[str, int] = {}
        self.review_tree: Path | None = None
        self._last_crystal_signature: tuple | None = None

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
        """Assistant turns from a `claude -p` run.

        Kept separate from foreign-seat invocations: a Claude turn and a whole
        codex session are not the same unit, and adding them produced a
        `model_calls` figure that meant nothing. Locked, because council and
        audit seats run in threads and `+=` on a plain int is not atomic.
        """
        with self._failures_lock:
            self.model_calls += n

    def _count_seat(self) -> None:
        with self._failures_lock:
            self.seat_invocations += 1

    def _note_models(self, ev: dict | None) -> None:
        """Record which models the build ACTUALLY used.

        The manifest records the configured model mix, but nothing made the
        lead honour it -- a lead that upgrades its workers changes the very
        variable `tiering` exists to test, and the manifest would still claim
        the configured mix. `modelUsage` names every model the session
        touched, so the claim becomes checkable.
        """
        mu = (ev or {}).get("modelUsage")
        if not isinstance(mu, dict):
            return
        for model, usage in mu.items():
            if isinstance(usage, dict):
                self.models_observed[str(model)] = int(usage.get("outputTokens") or 0)

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
        if rc != 0 or len(self.base_sha) != 40:
            self.fail("isolation", "base-sha-unresolved",
                      f"could not resolve refs/heads/master to a sha: {out!r}")
            return False

        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.ctx.run_tree.exists():
            self.fail("isolation", "run-tree-exists",
                      f"{self.ctx.run_tree} already exists; refusing to reuse it")
            return False
        # Branch from the resolved SHA, not from the NAME `master`. Between the
        # rev-parse above and this call another worktree can move master, and
        # a base_sha in the manifest that is not the base the branch was cut
        # from makes every diff this run computes wrong.
        rc, _out, err = git(
            ["worktree", "add", "-b", self.run_branch,
             str(self.ctx.run_tree), self.base_sha],
            cwd=self.framework, timeout=self.cfg.timeouts["git_s"])
        if rc != 0:
            self.fail("isolation", "worktree-add-failed", err.strip() or f"rc={rc}")
            return False
        self.worktree_created = True
        self.ctx.workers_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"worktree {self.ctx.run_tree} on {self.run_branch} "
                 f"(base {self.base_sha[:12]})")

        # A5: the exam that grades this run is the pristine one, SNAPSHOTTED
        # into the run directory at setup. Grading the live framework copy
        # would let an edit to this worktree mid-run change the yardstick out
        # from under a run whose manifest already recorded the old hash --
        # and six sequential overnight runs give that plenty of opportunity.
        pristine = self.framework / self.cfg.grader
        try:
            self.frozen_exam = self.run_dir / "frozen-exam.sh"
            shutil.copyfile(pristine, self.frozen_exam)
            os.chmod(self.frozen_exam, 0o755)
        except OSError as exc:
            self.fail("isolation", "exam-snapshot-failed", str(exc))
            return False
        if sha256_file(self.frozen_exam) != self.ctx.input_hashes.get("exam"):
            self.fail("isolation", "exam-moved-during-setup",
                      "the framework's exam changed between reading it for the "
                      "prompts and snapshotting it for grading")
            return False
        self.check_exam_tamper()
        return True

    def refresh_head(self) -> None:
        rc, out, _ = git(["rev-parse", self.run_branch], cwd=self.framework,
                         timeout=self.cfg.timeouts["git_s"])
        if rc == 0 and out.strip():
            self.head_sha = out.strip()

    def check_exam_tamper(self) -> None:
        """Has the run tree's copy of the frozen exam moved?

        Deletion and replacement-by-a-directory count as tampering too. The
        earlier version only compared hashes when the path was a regular
        file, so `rm` -- the easiest way to get the exam out of the way --
        left `exam_tampered` reading False.
        """
        run_exam = self.ctx.run_tree / self.cfg.grader
        expected = self.ctx.input_hashes.get("exam")
        if not run_exam.exists():
            tampered, how = True, "the run tree's copy of the exam was deleted"
        elif not run_exam.is_file():
            tampered, how = True, "the run tree's exam path is no longer a file"
        else:
            got = sha256_file(run_exam)
            tampered = got != expected
            how = f"the run tree's copy of {self.cfg.grader} differs from the frozen one"
        if tampered and not self.exam_tampered:
            self.fail("integrity", "exam-modified",
                      f"{how}; grading used the harness's own snapshot")
        self.exam_tampered = tampered

    # -- materials ---------------------------------------------------------

    def freeze_tree(self, tag: str) -> str:
        """Commit anything the agent left uncommitted, so the sha the reviewers
        are given actually names the bytes they are shown and graded.

        RUNBOOK §6 wants a review launched against a named, immutable
        revision. Previously the diff came from `base..head` (committed) while
        the inlined source and the graded server came from the WORKING TREE --
        so an agent that stopped mid-edit had its uncommitted work graded and
        reviewed under a sha that did not contain it.

        Sweeping rather than discarding, because the alternatives are worse:
        discarding silently throws away work the agent believes it did, and
        grading a dirty tree makes "the seat cleared sha X" meaningless. The
        sweep is deterministic and identical in every arm, and it is recorded.
        The prompts tell the agent this happens.
        """
        # Bounded, and to a file: the path list is agent-controlled, so a run
        # that creates enough paths could exhaust memory here.
        status_out = self.path("logs", f"status-{tag}.txt")
        # The SAME exclusion the `add` below uses. Asking whether the tree is
        # dirty without it meant a standup arm -- whose .standup/ bus is
        #untracked and in no .gitignore -- always looked dirty, staged
        # nothing, and recorded a false "sweep failed: the frozen sha may not
        # name what is graded" at every freeze point, in the standup arms only.
        rc, out, truncated = git_to_file(
            ["status", "--porcelain", "--", ".", SWEEP_EXCLUDE],
            cwd=self.ctx.run_tree,
            timeout=self.cfg.timeouts["git_s"], out=status_out, cap=1_000_000)
        if rc != 0:
            # NOT the same as clean. Treating a git failure as "nothing to
            # commit" leaves dirty bytes reviewed and graded under a sha that
            # does not contain them -- silently, which is the worst version.
            self.fail("materials", "status-failed",
                      f"git status exited {rc} at '{tag}'; cannot tell whether "
                      "the tree is clean, so the frozen sha may not name what "
                      "is graded")
            self.refresh_head()
            return self.head_sha
        if not out.strip():
            self.refresh_head()
            return self.head_sha
        n = len(out.strip().splitlines())
        if truncated:
            n = f"{n}+"
        # `:(exclude).standup` keeps the standup bus out of the commit. It sits
        # inside the run tree and is in no .gitignore, so `add -A` swept every
        # seed, redirect and crystal message into the diff -- the diff handed
        # to the reviewer AND to the escaped-defect audit, giving standup-ON
        # arms a different yardstick input from standup-OFF arms.
        rc_a, _o, err_a = git(["add", "-A", "--", ".", SWEEP_EXCLUDE],
                              cwd=self.ctx.run_tree,
                              timeout=self.cfg.timeouts["git_s"])
        rc_c, _o2, err_c = git(
            ["-c", "user.name=bench-harness",
             "-c", "user.email=bench@localhost",
             "commit", "-q", "-m",
             f"harness: sweep {n} uncommitted path(s) into the {tag} revision"],
            cwd=self.ctx.run_tree, timeout=self.cfg.timeouts["git_s"])
        if rc_a != 0 or rc_c != 0:
            self.fail("materials", "sweep-failed",
                      (err_a + " " + err_c).strip() or "git add/commit failed")
        else:
            self.swept.append({"tag": tag, "paths": n, "at": iso(utc_now())})
            self.fail("materials", "uncommitted-work-swept",
                      f"the agent left {n} uncommitted path(s) at '{tag}'; they "
                      "were committed so the frozen sha names what is graded")
        self.refresh_head()
        return self.head_sha

    def collect_materials(self, tag: str = "review") -> Materials:
        """The diff and the built source, genuinely frozen at one revision."""
        sha = self.freeze_tree(tag)
        out = self.path("logs", f"diff-{tag}.patch")
        rc, diff, truncated = git_to_file(
            ["diff", f"{self.base_sha}..{sha}"], cwd=self.ctx.run_tree,
            timeout=self.cfg.timeouts["git_s"], out=out, cap=DIFF_CAP)
        if rc != 0:
            self.fail("materials", "diff-failed", f"git diff exited {rc}")
            diff = "(the diff could not be computed; see the manifest failures)"
        elif truncated:
            diff += (f"\n\n[... diff truncated at {DIFF_CAP} characters; the "
                     f"full patch is at {out.name} ...]\n")
        tree = self.frozen_checkout(sha)
        code, inlined = self.collect_server_code(tree)
        return Materials(diff=diff, server_code=code, review_sha=sha,
                         tree=tree, server_inlined=inlined)

    def collect_server_code(self, tree: Path | None) -> tuple[str, bool]:
        """Inline every Python file beside the server, from the frozen checkout.

        Returns (text, entry_point_inlined). The flag is load-bearing: an
        audit prompt whose source section is nothing but omission notes must
        not be scored as "no defects found", so the callers refuse to run a
        seat that would see nothing.

        Read from `tree` -- the clean detached checkout of the reviewed sha --
        so the inlined source cannot drift from the sha the seats are told
        they are reviewing, and so a venv or build artefact in the live tree
        cannot eat the budget and push the real server out of the prompt.

        Only REGULAR files are inlined. A symlink is not followed: `st_size`
        of a link to a special file reports 0, which walks straight past the
        stat-before-read bound and lets a read of /dev/zero exhaust memory or
        a FIFO hang the run. A benchmark server has no business being a
        symlink, so one is reported rather than resolved.
        """
        if tree is None:
            return ("(the frozen revision could not be checked out, so no "
                    "source could be inlined)", False)
        server = tree / self.cfg.server_path
        srcdir = server.parent
        if server.is_symlink() or (server.exists() and not server.is_file()):
            return (f"(`{self.cfg.server_path}` is not a regular file in "
                    f"{self.head_sha[:12]} -- it is a symlink or a special "
                    "file, and is not inlined)", False)
        if not server.is_file():
            if srcdir.is_dir() and any(srcdir.rglob("*.py")):
                return (f"(NO SERVER at {self.cfg.server_path} in "
                        f"{self.head_sha[:12]}, although other Python files "
                        "exist beside it -- the entry point the exam runs is "
                        "missing)", False)
            return (f"(no server was produced at {self.cfg.server_path} -- "
                    "there is nothing to review)", False)
        files = sorted(f for f in srcdir.rglob("*.py")
                       if "__pycache__" not in f.parts)
        files.sort(key=lambda f: (f != server, str(f)))   # entry point first
        chunks: list[str] = []
        used = 0
        entry_inlined = False
        for f in files:
            rel = f.relative_to(tree)
            if f.is_symlink() or not f.is_file():
                chunks.append(f"### `{rel}`\n\n(not a regular file; not "
                              "inlined)\n")
                continue
            try:
                size = f.stat().st_size
            except OSError as exc:
                chunks.append(f"### `{rel}`\n\n(unreadable: {exc})\n")
                continue
            budget = CODE_CAP - used
            if budget <= 0:
                chunks.append(f"### `{rel}`\n\n[omitted: {size} bytes; the "
                              f"{CODE_CAP}-character inlining budget is "
                              "exhausted]\n")
                continue
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read(budget)
            except OSError as exc:
                chunks.append(f"### `{rel}`\n\n(unreadable: {exc})\n")
                continue
            used += len(body)
            # TRUNCATE, never drop. Dropping an over-budget entry point left
            # the audit seats with nothing but a note while the file plainly
            # existed, so the arm banked a real zero on the robustness metric
            # for a server nobody had read.
            note = ""
            if size > budget:
                note = (f"\n\n[truncated: {size} bytes, inlined the first "
                        f"{len(body)} characters]")
            chunks.append(f"### `{rel}`\n\n```python\n{body}\n```{note}\n")
            if f == server and body.strip():
                entry_inlined = True
        return "\n".join(chunks), entry_inlined

    def _tally_seats(self, seats: dict, results: dict, prompt: str,
                     tok: list, tag: str) -> tuple[dict, list[str], list[str]]:
        """Parse each seat's reply, bank its estimated cost, and tally.

        Shared by the council and the audit so the two cannot drift apart in
        how they treat a missing seat -- which is exactly the thing that must
        stay identical for the audit to be a yardstick.
        """
        union = {b: 0 for b in SEVERITY_BUCKETS}
        union["total"] = 0
        filled: list[str] = []
        empty: list[str] = []
        for seat_name in COUNCIL_SEATS:
            proc, reply = results.get(seat_name, (None, None))
            fnd = parse_findings(reply)
            tok.append(estimated_tokens(prompt, reply or ""))
            seats[seat_name] = {"proc": proc.summary() if proc else None,
                                **fnd.to_json()}
            if fnd.ok:
                filled.append(seat_name)
                for b in SEVERITY_BUCKETS:
                    union[b] += fnd.counts[b]
                union["total"] += fnd.counts["total"]
            else:
                empty.append(seat_name)
                self.fail(f"{tag}-{seat_name}", "findings-unparsable",
                          fnd.error or "unknown")
        return union, filled, empty

    def frozen_checkout(self, sha: str) -> Path | None:
        """A throwaway detached worktree at the reviewed revision.

        Reviewers run headless with --dangerously-skip-permissions. Pointing
        them at the live product tree gave them write access to the artefact
        they are judging: a reviewer that "helpfully" edits the server changes
        what the NEXT grading run measures, with the edit attributed to
        nobody. It also let a reviewer read whatever the working tree happens
        to hold at the moment it looks, rather than the revision it was told
        to review.

        A detached checkout of the frozen sha fixes both: the reviewer sees
        exactly the named revision, and anything it writes lands in a
        directory the run throws away.

        It is also where the inlined source is read from, so the sha the
        seats are told they are reviewing and the bytes they are shown cannot
        disagree.

        Returns None if the checkout cannot be made. The caller degrades to
        the diff alone and records it -- never to the product tree, which is
        the leak this exists to close.
        """
        wt = self.run_dir / "review-tree"
        if self.review_tree is None:
            # Prune first. A previous reset failure leaves the path REGISTERED
            # while `self.review_tree` is None, so the add below would fail
            # "already exists" for the rest of the run -- turning one
            # transient error into permanent loss of inlined source and a
            # nulled audit that blames a server the arm did build.
            if wt.exists():
                git(["worktree", "remove", "--force", str(wt)],
                    cwd=self.framework, timeout=self.cfg.timeouts["git_s"])
            git(["worktree", "prune"], cwd=self.framework,
                timeout=self.cfg.timeouts["git_s"])
            rc, _o, err = git(["worktree", "add", "--detach", str(wt), sha],
                              cwd=self.framework, timeout=self.cfg.timeouts["git_s"])
            if rc != 0:
                # Falling back to the product tree would re-open the exact
                # leak this worktree exists to close: a reviewer running with
                # permissions skipped, able to edit the artefact it is
                # judging. An empty scratch dir is the safe fallback -- the
                # diff and the source are inlined in the prompt anyway.
                self.fail("review", "frozen-checkout-failed",
                          f"{err.strip() or rc}; the reviewers will get the "
                          "diff alone and no inlined source")
                return None
            self.review_tree = wt
        else:
            # Re-point it at this round's revision and discard whatever a
            # previous reviewer left behind.
            rc, _o, err = git(["checkout", "--detach", "--force", sha],
                              cwd=wt, timeout=self.cfg.timeouts["git_s"])
            rc2, _o2, _e2 = git(["clean", "-qfdx"], cwd=wt,
                                timeout=self.cfg.timeouts["git_s"])
            if rc != 0 or rc2 != 0:
                self.fail("review", "frozen-checkout-reset-failed",
                          (err.strip() or f"checkout rc={rc} clean rc={rc2}")
                          + "; the reviewers will get the diff alone")
                self.review_tree = None
                return None
        return wt

    def seat_scratch(self, name: str) -> Path:
        """An empty directory for a foreign seat to sit in.

        Council and audit seats used to be given `-d <the run tree>`. Two
        problems, both fatal to the study rather than to the run: the audit is
        supposed to be regime-INDEPENDENT, and a seat standing in the product
        tree can read the contracts, ledger and status files that exist only
        in the orgs arms; and two write-capable seats running concurrently in
        one worktree can race each other and the product. Their code is
        inlined in the prompt precisely so they need no filesystem.
        """
        d = self.run_dir / "seat-scratch" / name
        if d.exists() or d.is_symlink():
            # Emptied on every handout: reusing it let one seat's leftovers
            # contaminate a later, supposedly fresh one. NOT ignore_errors --
            # an undeletable leftover, or a path replaced by a symlink, is
            # exactly the contamination this is here to prevent, so it is
            # reported and worked around rather than silently tolerated.
            try:
                if d.is_symlink() or not d.is_dir():
                    d.unlink()
                else:
                    shutil.rmtree(d)
            except OSError as exc:
                self.fail("seat", "scratch-not-clean",
                          f"could not empty {d}: {exc}; using a fresh path so "
                          "the seat does not inherit leftovers")
                d = d.with_name(f"{name}-{int(time.time()*1000)}")
        d.mkdir(parents=True, exist_ok=True)
        return d

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
                           stdout_path=out, stderr_path=err, stdin_data=prompt,
                           scrub_agent_env=True)
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
        if res.result_event is not None:
            # Count and bill it even when ok is False. A run that hit
            # max-turns or an API error still spent every token it spent;
            # discarding a measured figure because the run ended badly
            # under-reports that arm's real cost.
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
        scratch = self.seat_scratch(name)
        argv = [str(self.ask_agent), seat_name, "-d", str(scratch), "-f", str(pf)]
        self.log(f"  -> ask-agent {seat_name} {name}  [timeout {int(timeout)}s]")
        proc = run_capture(argv, cwd=scratch, timeout=timeout,
                           stdout_path=out, stderr_path=err,
                           scrub_agent_env=True)
        if proc.timed_out:
            self.fail(name, "timeout", f"{seat_name} exceeded {timeout}s and was killed")
        elif proc.spawn_error:
            self.fail(name, "spawn-failed", proc.spawn_error)
        elif proc.returncode != 0:
            self.fail(name, "nonzero-exit",
                      f"{seat_name} exited {proc.returncode}", stderr_tail=_tail(err))
        if not proc.spawn_error:
            self._count_seat()
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
            # Long enough for a loop blocked in its own subprocess to finish
            # it and notice the stop. Joining for less abandons a LIVE
            # thread that goes on writing to the bus and reading shared refs
            # while the next phase grades -- and, being a daemon, dies
            # mid-git-operation at interpreter exit.
            join_s = max(self.cfg.timeouts["crystal_s"],
                         self.cfg.timeouts["standup_s"]) + 60
            for th in threads:
                th.join(timeout=join_s)
                if th.is_alive():
                    self.fail("build", "loop-hung",
                              f"the {th.name} loop did not stop within "
                              f"{join_s:.0f}s; it may still be running")
            # Recorded BEFORE the health check, which reads it. Setting it
            # after the finally block left build_s at 0.0, so `had_time` was
            # always False and the dead-crystal guard could never fire.
            self.phases["build"] = time.time() - t0
            self._check_mechanism_health()
        self.tokens["build"] = res.tokens()
        self._note_models(res.result_event)
        self.phases.setdefault("build", time.time() - t0)
        self.path("logs", "build.result.json").write_text(
            json.dumps({"proc": proc.summary(), "parsed_ok": res.ok,
                        "error": res.error, "shape": res.shape,
                        "final_text": res.text}, indent=2), encoding="utf-8")
        self.refresh_head()
        self.check_exam_tamper()

    def _check_mechanism_health(self) -> None:
        """Did the mechanisms this arm claims to run actually run?

        An ablation compares an arm WITH a mechanism against one without. If
        the mechanism was configured on but never functioned -- the loop
        crashed on its first iteration, every observe errored, no seat was
        reachable -- then both arms ran without it and the difference between
        them measures noise. Nothing about that surfaces as an error today:
        the counters are local and the run exits cleanly.

        So the claim is checked, and a mechanism that was on but did nothing
        is a recorded failure of the RUN, not a silent zero in the study.
        """
        if self.cfg.toggles["standup"]:
            st = self.standup_stats
            if not st["ran"]:
                self.fail("standup", "mechanism-dead",
                          "standup is ON but its loop never started")
            elif st["observes"] == 0:
                self.fail("standup", "mechanism-dead",
                          "standup is ON but completed zero observes; this arm "
                          "did not actually receive the mechanism")
            elif st["errors"] >= st["observes"]:
                self.fail("standup", "mechanism-dead",
                          f"standup is ON but every one of its {st['observes']} "
                          "observes errored; treat this arm as standup-OFF")
        if crystal_active(self.cfg):
            cr = self.crystal_stats
            # The loop waits one interval before its first attempt and skips
            # attempts with no worker branches yet, so zero checks is only
            # evidence of a dead mechanism if the build outlasted an interval
            # AND branches existed to check. Otherwise it just means the
            # sprint was short or the lead fanned out late.
            build_s = self.phases.get("build", 0.0)
            had_time = build_s > float(self.cfg.crystal["interval_s"])
            if not cr["ran"]:
                self.fail("crystal", "mechanism-dead",
                          "crystal is ON but its loop never started")
            elif cr["checks"] == 0 and had_time and \
                    cr["branchless_attempts"] == cr["attempts"] and cr["attempts"]:
                # It looked, every time, and never found a worker branch under
                # the expected prefix. Either the lead never fanned out or it
                # ignored the branch names it was given -- both mean this arm
                # ran without the mechanism whatever the manifest says.
                self.fail("crystal", "mechanism-dead",
                          f"crystal is ON but found no worker branch under "
                          f"{self.ctx.worker_branch_prefix!r} in any of "
                          f"{cr['attempts']} attempts over {build_s:.0f}s")
            elif cr["checks"] == 0 and had_time and cr["attempts"] > 0:
                self.fail("crystal", "mechanism-dead",
                          f"crystal is ON but ran zero checks in {build_s:.0f}s "
                          f"across {cr['attempts']} attempts; this arm did not "
                          "actually receive the mechanism")
            elif cr["checks"] == 0:
                self.crystal_stats["inactive_reason"] = (
                    f"no check ran: build was {build_s:.0f}s, interval "
                    f"{self.cfg.crystal['interval_s']:.0f}s, "
                    f"{cr['attempts']} attempt(s) found worker branches")
            elif cr["errors"] >= cr["checks"]:
                self.fail("crystal", "mechanism-dead",
                          f"crystal is ON but every one of its {cr['checks']} "
                          "checks errored; treat this arm as crystal-OFF")

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
        agents = ([self.ctx.standup_id(w) for w in self.cfg.worker_ids]
                  if self.cfg.toggles["decomposition"] else [])
        agents.append(self.ctx.lead_agent_id if self.cfg.toggles["decomposition"]
                      else self.ctx.solo_agent_id)
        self.standup_stats["agents"] = agents
        # Seed each inbox so `standup.sh observe` can see the agent at all
        # (it enumerates agents by their bus directory), and so the first
        # thing every agent reads is that it is being observed.
        for a in agents:
            r = run_capture([str(self.ctx.framework / "standup/bus.sh"), "send", a,
                             "info",
                             "Standup is observing this run. Keep your status "
                             "file current and commit granularly."],
                            cwd=self.ctx.run_tree, timeout=30,
                            stdout_path=self.path("logs", "standup-seed.txt"),
                            stderr_path=self.path("logs", "standup-seed.err.txt"),
                            env=env)
            if not r.ok:
                # A failed seed means this agent has no inbox, so `observe`
                # cannot see it and no redirect can ever reach it: the
                # mechanism is OFF for that agent while the manifest says ON.
                self.standup_stats["errors"] += 1
                self.fail("standup", "seed-failed",
                          f"could not create a bus inbox for {a} "
                          f"(rc={r.returncode}); standup cannot observe or "
                          "redirect it, so the mechanism is not actually "
                          "running for that agent")
        last_redirect: dict[str, float] = {}
        log = self.path("logs", "standup.log")
        started = time.time()
        grace = float(self.cfg.standup["startup_grace_s"])
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
                # No redirect during the opening grace period. An agent has to
                # be given time to produce its first commit before "you have
                # not committed" is true rather than merely early.
                if now - started < grace:
                    self.standup_stats["stalls_in_grace"] += 1
                    continue
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
                    self.fail("standup", "redirect-failed",
                              f"could not deliver a redirect to {agent} "
                              f"(rc={r.returncode})")
            if stop.wait(self.cfg.standup["interval_s"]):
                return

    def _crystal_loop(self, stop: threading.Event) -> None:
        """Speculatively merge the worker branches against each other.

        Most speculative merges are clean; the value is early warning on the
        rare real one, textual or semantic. Nothing here touches a ref or a
        worktree.
        """
        self.crystal_stats["ran"] = True
        test_cmd = crystal_test_cmd(self.cfg)
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
            # Every iteration is an attempt, branches or not. Counting only
            # the iterations that went on to run a check made
            # "checks == 0 and attempts > 0" logically impossible, which is
            # the condition the dead-mechanism guard tests.
            self.crystal_stats["attempts"] += 1
            if not branches:
                self.crystal_stats["branchless_attempts"] += 1
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
                stanzas, noisy = _classify_conflicts(text, self.ctx.run_branch)
                self.crystal_stats["conflicts"] += 1
                if stanzas:
                    self.crystal_stats["real_conflicts"] += 1
                if noisy:
                    self.crystal_stats["noisy_branches"] = sorted(
                        set(self.crystal_stats["noisy_branches"]) | set(noisy))
                self.crystal_stats["reports"].append({
                    "check": n, "at": iso(utc_now()), "branches": branches,
                    "report": str(rpt.relative_to(self.run_dir)),
                    "stanzas": stanzas,
                    "noisy_branches": noisy,
                })
                self._deliver_crystal(n, stanzas, noisy)
            elif proc.returncode != 0:
                self.crystal_stats["errors"] += 1
                self.fail("crystal", "check-failed",
                          f"crystal-check.sh exited {proc.returncode} on check "
                          f"#{n}; no speculative merge information was produced")

    def _deliver_crystal(self, check: int, stanzas: list[str],
                         noisy: list[str]) -> None:
        """Tell the lead about a speculative conflict.

        Without this the loop wrote to a log nobody in the run can read, while
        frag_crystal_lead.md promised the lead that conflicts "get reported to
        you at standup". The r3-vs-r4 crystal ablation would then have
        measured the presence of a paragraph rather than the mechanism: no
        conflict could ever change what the org did.

        Delivery rides the standup bus, which is the only channel an agent is
        told to read. When standup is OFF there is no such channel -- the
        prompt says so in that case, and the harness records that the report
        could not be delivered rather than pretending it was.
        """
        if not stanzas and not noisy:
            return
        # Say a thing once. The loop runs every few minutes for the whole
        # build, so a worker branch that stays un-compilable would otherwise
        # inject the same message dozens of times into the lead's context --
        # and this path has none of the per-agent cooldown _standup_loop
        # applies. Re-notify only when what there is to say has changed.
        signature = (tuple(stanzas), tuple(noisy))
        if signature == self._last_crystal_signature:
            self.crystal_stats["suppressed_repeats"] += 1
            return
        if not self.cfg.toggles["standup"]:
            # No bus, so nothing can be pushed to the lead; the prompt tells
            # it to run the check itself. Recorded once per distinct finding,
            # AFTER the repeat check -- counting it every loop iteration
            # inflated `undelivered` into a measure of how long the build ran.
            self.crystal_stats["undelivered"] += 1
            self._last_crystal_signature = signature
            return
        if stanzas:
            body = ("Standup — Crystal speculative merge check #%d found a "
                    "conflict between branches that are each green alone:\n"
                    "  - %s\n"
                    "Adjudicate now, before it is merged: contract changed -> "
                    "the provider migrates its callers; assumption was invalid "
                    "-> the consumer fixes it; disputed -> you decide. Whoever "
                    "merges second cleans up." % (check, "\n  - ".join(stanzas[:8])))
        else:
            body = ("Standup — Crystal speculative merge check #%d found no "
                    "cross-branch conflict." % check)
        if noisy:
            body += ("\nNote: %s fail the boundary test on their OWN, before "
                     "any merge. That is not a cross-branch conflict, but it "
                     "does mean those branches are currently broken."
                     % ", ".join(noisy))
        env = {"STANDUP_BUS": str(self.ctx.bus_root)}
        r = run_capture([str(self.ctx.standup_script), "redirect",
                         self.ctx.lead_agent_id, body],
                        cwd=self.ctx.run_tree,
                        timeout=self.cfg.timeouts["standup_s"],
                        stdout_path=self.path("logs", "crystal-delivery.txt"),
                        stderr_path=self.path("logs", "crystal-delivery.err.txt"),
                        env=env)
        if r.ok:
            # Recorded only on SUCCESS. Marking the signature seen before the
            # delivery landed meant one transient failure suppressed every
            # later report of the same conflict as a duplicate -- turning
            # "observed but could not act" from a per-check hiccup into a
            # permanent silence.
            self._last_crystal_signature = signature
            self.crystal_stats["delivered"] += 1
        else:
            self.crystal_stats["undelivered"] += 1
            self.fail("crystal", "delivery-failed",
                      f"a conflict report could not be delivered to the lead "
                      f"(rc={r.returncode}); it will be retried on the next "
                      "check that still finds it")

    def phase_grade(self, tag: str) -> dict:
        """Run the frozen exam, from the pristine copy, under nix."""
        t0 = time.time()
        server = self.ctx.run_tree / self.cfg.server_path
        exam = self.frozen_exam or (self.framework / self.cfg.grader)
        result: dict[str, Any] = {
            "ran": False, "exam": str(exam), "server": str(server),
            "conformance_total": 0, "conformance_passed": 0,
            "passed_all": False, "exit_code": None, "timed_out": False,
            "trustworthy": False,
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
        # Kept apart on purpose. The exam prints its summary on STDOUT and its
        # FAIL lines on STDERR; concatenating them and taking the last match
        # let a line on stderr override the real score. The score is scraped
        # from stdout only.
        out_text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        err_text = err.read_text(encoding="utf-8", errors="replace") if err.exists() else ""
        text = out_text + "\n" + err_text
        result["ran"] = True
        result["exit_code"] = proc.returncode
        result["timed_out"] = proc.timed_out
        # Anchored to the start of a line, and the LAST such line wins.
        # The exam runs the server as a child, so the server's own stdout is
        # interleaved with the exam's -- an unanchored search would happily
        # scrape a "conformance: 16 passed, 0 failed" that the SERVER printed.
        # The exam emits this line last, immediately before exiting.
        matches = re.findall(r"^conformance:\s*(\d+)\s+passed,\s*(\d+)\s+failed\s*$",
                             out_text, re.MULTILINE)
        m = matches[-1] if matches else None
        if m:
            passed, failed = int(m[0]), int(m[1])
            result["conformance_passed"] = passed
            result["conformance_total"] = passed + failed
            result["passed_all"] = (failed == 0 and proc.returncode == 0)
            # The exam contracts exit 0 (all pass) or 1 (an assertion failed).
            # Anything else means the harness itself went wrong -- and a score
            # scraped out of a run that went wrong is not a score. Recorded,
            # but flagged untrustworthy rather than silently counted.
            # Cross-check the scraped line against the exit status, which the
            # server cannot forge: the exam exits 0 only when nothing failed
            # and 1 only when something did. A line that disagrees with the
            # status did not come from the exam.
            consistent = ((proc.returncode == 0 and failed == 0)
                          or (proc.returncode == 1 and failed > 0))
            result["trustworthy"] = (proc.returncode in (0, 1)
                                     and not proc.timed_out and consistent)
            result["line_count"] = len(matches)
            if not result["trustworthy"]:
                self.fail(f"grade:{tag}", "exam-result-inconsistent",
                          f"the scraped conformance line ({passed} passed, "
                          f"{failed} failed) does not agree with the exam's exit "
                          f"status {proc.returncode}; the counts are recorded "
                          "but marked untrustworthy")
            if len(matches) > 1:
                self.fail(f"grade:{tag}", "exam-line-duplicated",
                          f"{len(matches)} conformance lines were printed; the "
                          "last was used, but the server may be emitting one")
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
        fix_seconds = 0.0
        tok = []
        for rnd in range(1, self.cfg.max_rounds[step] + 1):
            mat = self.collect_materials(f"{step}-round{rnd}")
            review_cwd = mat.tree or self.seat_scratch(
                f"review-fallback-{step}-round{rnd}")
            prompt = compose_review_prompt(
                self.cfg, self.ctx, step, mat, review_cwd=review_cwd,
                have_no_tree=mat.tree is None)
            name = f"review-{step}-round{rnd}"
            proc, res = self.claude(name, prompt, model=model,
                                    timeout=self.cfg.timeouts["review_s"],
                                    cwd=review_cwd)
            tok.append(res.tokens())
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
            applied, secs = self._apply_fix(f"{step}-round{rnd}", fnd,
                                            res.text or "")
            fix_seconds += secs
            if applied:
                fixes += 1
            else:
                break
        # The step's own wall clock EXCLUDES the fix rounds nested inside
        # it: they are recorded under their own `fix:` phase, and leaving
        # them here too made wall_clock_by_phase sum to more than the run.
        self.phases[f"review:{step}"] = max(0.0, (time.time() - t0) - fix_seconds)
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
        fix_seconds = 0.0
        tok: list[dict] = []
        for rnd in range(1, self.cfg.max_rounds["council"] + 1):
            mat = self.collect_materials(f"council-round{rnd}")
            if not mat.server_inlined:
                # The council prompt carries no diff, so a seat here would be
                # reviewing nothing -- and would correctly answer `[]`, which
                # banks as a clean round and deflates this arm's
                # bugs-caught-by-council figure. Refuse the round instead.
                self.fail(f"council-round{rnd}", "nothing-to-review",
                          "the server's source could not be inlined, so the "
                          "seats would see nothing; the round is recorded as "
                          "not run rather than as finding nothing")
                self.phases["review:council"] = time.time() - t0
                self.tokens["review:council"] = add_tokens(*tok)
                return {"ran": False,
                        "skipped_reason": "no source could be inlined for the "
                                          "seats to review",
                        "rounds": rounds, "totals": _sum_rounds(rounds),
                        "fix_rounds_applied": fixes}
            prompt = compose_council_prompt(self.cfg, self.ctx, mat)
            seats = {}
            results: dict[str, tuple[Proc, str | None]] = {}
            threads = []

            def go(seat_name: str, rnd: int = rnd) -> None:
                results[seat_name] = self.seat(
                    f"council-{seat_name}-round{rnd}", seat_name, prompt,
                    timeout=self.cfg.timeouts["council_s"])

            for seat_name in COUNCIL_SEATS:
                th = threading.Thread(target=go, args=(seat_name,),
                                      name=f"council-{seat_name}",
                                      daemon=True)
                th.start()
                threads.append(th)
            for th in threads:
                th.join(timeout=self.cfg.timeouts["council_s"] + 120)
                if th.is_alive():
                    self.fail("council", "seat-hung",
                              f"{th.name} did not return within its timeout")

            union, filled, empty = self._tally_seats(
                seats, results, prompt, tok, f"council-round{rnd}")
            any_ok = bool(filled)
            rec = {
                "round": rnd, "reviewed_sha": mat.review_sha,
                "seats": seats,
                # parse_ok means EVERY seat answered. A round where one
                # provider was rate-limited is not a clean round: its union
                # is one seat's opinion wearing a two-seat label.
                "parse_ok": len(filled) == len(COUNCIL_SEATS),
                "partial": bool(filled) and len(filled) < len(COUNCIL_SEATS),
                "counts": union if any_ok else None,
                "union_note": "sum across seats; no cross-seat semantic "
                              "deduplication is attempted (A7)",
                "seats_expected": list(COUNCIL_SEATS),
                "seats_filled": filled,
                "seats_empty": empty,
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
            applied, secs = self._apply_fix(f"council-round{rnd}", fnd_all, prose)
            fix_seconds += secs
            if applied:
                fixes += 1
            else:
                break
        self.phases["review:council"] = max(0.0, (time.time() - t0) - fix_seconds)
        self.tokens["review:council"] = add_tokens(*tok)
        return {"ran": True, "skipped_reason": None, "rounds": rounds,
                "totals": _sum_rounds(rounds), "fix_rounds_applied": fixes}

    def _apply_fix(self, tag: str, fnd: Findings,
                   prose: str) -> tuple[bool, float]:
        """Run one fix round. Returns (the code actually changed, seconds).

        "Applied" means the tree MOVED, not that the agent's process parsed.
        An agent that disputed every finding, or that simply did nothing,
        leaves the revision where it was -- counting that as a fix round
        applied would credit the review ladder with work it did not cause,
        and would send the loop into another review round over identical code.
        """
        actionable = [f for f in fnd.findings
                      if f["severity"] in ("critical", "important")]
        if not actionable:
            return False, 0.0
        before = self.head_sha
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
        self.tokens[f"fix:{tag}"] = res.tokens()
        self.phases[f"fix:{tag}"] = proc.duration_s
        self.freeze_tree(f"fix-{tag}")
        self.check_exam_tamper()
        changed = self.head_sha != before
        if not changed:
            self.fail(f"fix-{tag}", "fix-changed-nothing",
                      "the fix agent finished without moving the revision; "
                      "the findings were disputed or ignored")
        elif not res.ok:
            # It committed real changes and then errored (max turns, API
            # failure). Those changes exist and must be re-reviewed; treating
            # the round as un-applied would end convergence over code nobody
            # looked at again.
            self.fail(f"fix-{tag}", "fix-applied-then-errored",
                      "the fix agent changed the code and then failed; the "
                      "changes stand and the next round reviews them")
        return changed, proc.duration_s

    # -- the yardstick -----------------------------------------------------

    def phase_audit(self) -> None:
        """The escaped-defect audit: identical for every regime, run last.

        This is the robustness metric. It runs against the FINAL server, after
        whatever review the regime did, and asks a fresh cross-provider pair
        what got through. Because the prompt is regime-independent by
        construction, the counts are comparable across arms.
        """
        t0 = time.time()
        mat = self.collect_materials("audit")
        # Guard on what the SEATS are shown, not on the working tree. The
        # material now comes from the frozen checkout, so a freeze that did
        # not land would let a working-tree check pass while the seats were
        # handed the "(no server was produced ...)" placeholder -- both
        # correctly answer [], and the arm that built nothing banks zero
        # escaped defects: the best possible score on the headline
        # robustness metric.
        if not mat.server_inlined:
            # Keyed on what the seats will actually SEE, not on the file
            # existing. An entry point that exists but could not be inlined
            # (over budget, a symlink, an unreadable file) leaves the seats
            # with omission notes; both answer `[]` and the arm banks zero
            # escaped defects -- the best possible score on the headline
            # robustness metric -- for a server nobody read.
            reason = (f"the server at {self.cfg.server_path} could not be "
                      f"inlined for the audited revision {mat.review_sha[:12]}, "
                      "so the seats would see nothing; escaped_defects is null "
                      "rather than zero")
            self.escaped = {"ran": False, "reason": reason, "parse_ok": False,
                            "complete": False, "counts": None,
                            "critical_important": None, "seats": {},
                            "seats_expected": list(COUNCIL_SEATS),
                            "seats_filled": [], "seats_empty": list(COUNCIL_SEATS)}
            self.fail("audit", "no-server", reason)
            self.phases["audit"] = time.time() - t0
            return
        prompt = compose_audit_prompt(self.cfg, self.ctx, mat)
        results: dict[str, tuple[Proc, str | None]] = {}
        threads = []

        def go(seat_name: str) -> None:
            results[seat_name] = self.seat(f"audit-{seat_name}", seat_name,
                                           prompt, timeout=self.cfg.timeouts["council_s"])

        for seat_name in COUNCIL_SEATS:
            th = threading.Thread(target=go, args=(seat_name,),
                                  name=f"audit-{seat_name}", daemon=True)
            th.start()
            threads.append(th)
        for th in threads:
            th.join(timeout=self.cfg.timeouts["council_s"] + 120)
            if th.is_alive():
                self.fail("audit", "seat-hung", f"{th.name} did not return in time")

        seats: dict[str, dict] = {}
        tok: list[dict] = []
        union, filled, empty = self._tally_seats(seats, results, prompt, tok, "audit")
        any_ok = bool(filled)
        complete = len(filled) == len(COUNCIL_SEATS)
        self.escaped = {
            "ran": True,
            "audited_sha": mat.review_sha,
            "seats": seats,
            "parse_ok": complete,
            # complete=False means the yardstick was shorter for this arm than
            # for the others. An overnight rate-limit on one provider would
            # otherwise silently halve one regime's escaped-defect count and
            # make it look like the most robust build of the six.
            "complete": complete,
            "counts": union if any_ok else None,
            "critical_important": (union["critical"] + union["important"]) if any_ok else None,
            "union_note": "sum across seats; no cross-seat semantic "
                          "deduplication is attempted (A7)",
            "seats_expected": list(COUNCIL_SEATS),
            "seats_filled": filled,
            "seats_empty": empty,
        }
        if not complete:
            self.fail("audit", "yardstick-incomplete",
                      f"only {filled or 'no'} seat(s) answered the escaped-defect "
                      "audit; this arm's robustness number is NOT comparable "
                      "with an arm whose audit had every seat")
        self.path("reviews", "audit-escaped-defects.json").write_text(
            json.dumps(self.escaped, indent=2), encoding="utf-8")
        self.tokens["audit"] = add_tokens(*tok)
        self.phases["audit"] = time.time() - t0
        if any_ok:
            self.log(f"     escaped defects (Critical+Important): "
                     f"{self.escaped['critical_important']}")

    # -- output ------------------------------------------------------------

    def manifest(self, ended: datetime | None) -> dict:
        # ONLY the final stage. Falling back to `after_build` published a
        # pre-review score under the headline `grading` field whenever the run
        # died after the reviews touched the code -- a number that is not
        # wrong so much as answering a different question than its name.
        final = self.grading_stages.get("final") or {}
        if not final and self.grading_stages:
            self.fail("manifest", "no-final-grade",
                      "the final grading stage never ran; grading is reported "
                      "as zero rather than back-filled from an earlier stage")
        coord_parts = [self.tokens.get(f"review:{s}", {}) for s in REVIEW_STEP_ORDER]
        prod_parts = [self.tokens.get("build", {})] + [
            v for k, v in self.tokens.items() if k.startswith("fix:")]
        coordination = add_tokens(*coord_parts)
        product = add_tokens(*prod_parts)
        provenance = {
            "coordination": _split_provenance(coord_parts),
            "product": _split_provenance(prod_parts),
            "note": (
                "A `claude -p` seat's tokens are MEASURED; a foreign "
                "ask-agent seat reports none and is ESTIMATED at "
                "characters/4. They are summed into one number because the "
                "schema has one field, but two arms whose review ladders use "
                "different seat types are NOT comparable on "
                "coordination_tokens -- compare `measured` against `measured`. "
                "This is a limitation of what ask-agent reports, not of the "
                "arithmetic."),
        }
        wall = (ended - self.started).total_seconds() if ended else \
            (utc_now() - self.started).total_seconds()
        # Only a COMPLETE audit fills the headline robustness field. A
        # one-seat audit's number sitting in the same field as a two-seat
        # one's makes the arm that lost a provider look like the most robust
        # build of the six. The partial count is still in `escaped_defects`.
        esc = self.escaped or {}
        esc_count = esc.get("critical_important") if esc.get("complete") else None

        man: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": iso(self.started),
            "ended_at": iso(ended) if ended else None,
            "regime": coarse_regime(self.cfg.toggles),
            "regime_name": self.cfg.regime,
            "target": self.cfg.target,
            "git_revision": self.base_sha,
            "injected_event": None,
            "ablation": ablation_of(self.cfg.toggles, self.cfg.vocabulary),
            "ablation_set": ablation_keys(self.cfg.toggles, self.cfg.vocabulary),
            "toggles": dict(self.cfg.toggles),
            "models": dict(self.cfg.models),
            "cost": {
                "coordination_tokens": int(coordination["total_tokens"]),
                "product_tokens": int(product["total_tokens"]),
                "model_calls": int(self.model_calls),
                "seat_invocations": int(self.seat_invocations),
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
            "cost_provenance": provenance,
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
            "budget_tokens": self.cfg.budget_tokens,
            "budget_overrun": (
                None if not self.cfg.budget_tokens else
                max(0, coordination["total_tokens"] + product["total_tokens"]
                    - int(self.cfg.budget_tokens))),
            "models_observed": dict(self.models_observed),
            "models_honoured": _models_honoured(self.cfg.models, self.models_observed),
            "models_missing": _models_missing(
                self.cfg.models, self.models_observed,
                ("lead", "worker") if self.cfg.toggles["decomposition"]
                else ("implementer",)),
            "swept_commits": self.swept,
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


def _split_provenance(parts: list[dict]) -> dict:
    """Split a token bucket into what was measured and what was estimated.

    The single `coordination_tokens` figure mixes a `claude -p` seat's real
    modelUsage with a foreign seat's characters/4 guess. Summed, an arm whose
    review is one council round looks an order of magnitude cheaper than an
    arm whose review is a native reviewer -- an artefact of HOW the two were
    counted, not of what they cost. Reporting both halves is the most this
    harness can honestly do: ask-agent reports no usage at all.
    """
    measured = {"input": 0, "output": 0, "cache_read": 0,
                "cache_creation": 0, "total_tokens": 0}
    estimated = dict(measured)
    incomplete = False
    for part in parts:
        if not part:
            continue
        target = estimated if part.get("estimated") else measured
        for k in measured:
            target[k] += int(part.get(k) or 0)
        # "unavailable" and the last-turn-only `usage` fallback are not
        # estimates, but they are not full measurements either: banking them
        # as measured would label an undercounted arm comparable.
        if _is_incomplete(part):
            incomplete = True
    return {"measured": measured, "estimated": estimated,
            "incomplete_sources": incomplete,
            "comparable_across_arms": (estimated["total_tokens"] == 0
                                       and not incomplete)}


def _models_honoured(configured: dict, observed: dict) -> bool | None:
    """Did the build actually use the models the config asked for?

    Nothing forces a lead to pass the configured worker model to its `Agent`
    calls. A lead that quietly upgrades its workers changes the very variable
    `tiering` exists to isolate, while the manifest goes on reporting the
    configured mix. `modelUsage` names every model the session touched, so the
    claim can at least be checked. None when nothing was observed.
    """
    if not observed:
        return None
    want = {v.lower() for v in configured.values()}
    for model in observed:
        low = model.lower()
        # modelUsage gives full ids ("claude-haiku-4-5"); configs give
        # aliases ("haiku"). A configured alias must appear in the id.
        if not any(alias in low for alias in want):
            return False
    return True


def _models_missing(configured: dict, observed: dict,
                    roles: tuple) -> list[str] | None:
    """Configured models for the named roles that never appear in modelUsage.

    `_models_honoured` can only see a model from OUTSIDE the configured set,
    so a lead that upgrades its haiku workers to the sonnet it also uses
    itself passes it. This catches that from the other side: if `worker` is
    haiku and no haiku appears anywhere in the session, the workers did not
    run at the tier the config asked for -- which is the variable `tiering`
    exists to isolate.
    """
    if not observed:
        # Null, not an empty list. An empty list reads as "every configured
        # tier ran", which is a claim about a build nothing was observed of.
        return None
    seen = " ".join(observed).lower()
    return sorted({configured[r].lower() for r in roles
                   if r in configured and configured[r].lower() not in seen})


def _empty_totals() -> dict:
    d = {b: 0 for b in SEVERITY_BUCKETS}
    d.update({"total": 0, "rounds": 0, "rounds_unparsed": 0, "rounds_partial": 0})
    d["first_round"] = {b: 0 for b in SEVERITY_BUCKETS}
    d["first_round"]["total"] = 0
    return d


def _sum_rounds(rounds: list[dict]) -> dict:
    """Aggregate a step's rounds.

    Two numbers, because they answer different questions and conflating them
    biases the study:

    `first_round` -- what this step caught on a clean look at the build. This
    is the comparable "bugs caught by this step" figure, because it does not
    depend on how many rounds the step was configured for.

    the summed buckets -- every finding reported across every round. A defect
    that was reported, not fixed, and reported again counts twice here, and an
    arm configured for more rounds accumulates more. No deduplication is
    attempted: matching two seats' prose descriptions of "the same" defect is
    not something this harness can do honestly.

    Rounds whose findings block did not parse contribute to no severity count
    and are tallied as `rounds_unparsed` -- "could not parse" is never
    recorded as "zero findings" (A8). A round where some but not all seats
    answered is tallied as `rounds_partial`: its counts are kept (dropping
    them would be worse) but the round is visibly not a full one.
    """
    tot = _empty_totals()
    for r in rounds:
        tot["rounds"] += 1
        counts = r.get("counts")
        # Usability is about the COUNTS, not about parse_ok. A partial council
        # round has parse_ok False (not every seat answered) but real findings
        # from the seat that did; discarding them lost genuine findings from
        # the primary per-step total.
        if not isinstance(counts, dict):
            tot["rounds_unparsed"] += 1
            if r.get("round") == 1:
                # Round 1 produced nothing readable. `first_round` is the
                # comparable "bugs caught by this step" figure, so leaving it
                # at zero would read as "the reviewer found nothing" -- the
                # exact A8 conflation this harness refuses everywhere else.
                tot["first_round"] = None
            continue
        if r.get("partial") or not r.get("parse_ok"):
            tot["rounds_partial"] += 1
        for b in SEVERITY_BUCKETS:
            tot[b] += int(counts.get(b, 0))
        tot["total"] += int(counts.get("total", 0))
        if r.get("round") == 1 and tot["first_round"] is not None:
            for b in SEVERITY_BUCKETS:
                tot["first_round"][b] = int(counts.get(b, 0))
            tot["first_round"]["total"] = int(counts.get("total", 0))
            tot["first_round"]["complete"] = bool(r.get("parse_ok"))
    return tot


def _assertion_name(fail_line: str) -> str:
    """`<name> — expected [X] got [Y]` -> `<name>`."""
    return fail_line.split(" — expected", 1)[0].strip()


def _fix_regressions(stages: dict) -> int | None:
    """Assertions that passed after the build and stopped passing by the end.

    The bug class the whole review ladder exists to catch is the fix that
    breaks something, so it gets its own number.

    Compared as SETS of failing assertion names, not as pass counts. A fix
    round that repairs one assertion while breaking a different one leaves the
    count identical, and the count-based version reported zero regressions for
    exactly the case this metric exists to find. The exam prints each failure
    as `FAIL: <description>`, which `phase_grade` captures per stage.
    """
    a, b = stages.get("after_build"), stages.get("final")
    if not a or not b or not a.get("ran") or not b.get("ran"):
        return None
    if not a.get("conformance_total") or not b.get("conformance_total"):
        return None
    before, after = a.get("failures"), b.get("failures")
    if isinstance(before, list) and isinstance(after, list):
        # Compare assertion NAMES only. The exam prints
        # `FAIL: <name> — expected [X] got [Y]`, so the observed value is part
        # of the line: a fix that changes a still-failing assertion's wrong
        # answer would otherwise produce a new string and read as a fresh
        # regression -- inflating the number in proportion to how many fix
        # rounds an arm ran, i.e. against the arms that review most.
        return len({_assertion_name(x) for x in after}
                   - {_assertion_name(x) for x in before})
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
    return _classify_conflicts(report, base=None)[0]


def _classify_conflicts(report: str, base: str | None) -> tuple[list[str], list[str]]:
    """Split a Crystal report into real conflicts and single-branch noise.

    crystal-check.sh's own header warns: "a branch red on its own makes every
    one of its pairings FAIL, which is noise". One worker whose work-in-
    progress does not compile therefore turns every pair it appears in into a
    reported conflict, and counting those inflates the crystal metric with
    exactly the thing crystal is not for.

    The report gives us the discriminator for free: it checks base × branch
    before it checks branch × branch. A branch whose stanza against the BASE
    already fails is red alone, so its later pairings are dropped and the
    branch is named instead -- which is the actionable fact anyway.

    Returns (real cross-branch conflicts, branches that are red on their own).
    """
    stanzas: list[tuple[str, str, str]] = []      # (left, right, verdict)
    header: str | None = None
    for line in report.splitlines():
        if line.startswith("## "):
            header = line[3:].strip()
        elif header and (line.startswith("merge: CONFLICT")
                         or line.startswith("tests: FAIL")):
            left, _, right = header.partition(" × ")
            stanzas.append((left.strip(), right.strip(), line.strip()))
            header = None
        elif header and (line.startswith("tests: pass")
                         or line.startswith("merge: clean")):
            continue                                # keep the header alive
    # `name@sha` -> name, so a stanza can be matched against the base name.
    def bare(ref: str) -> str:
        return ref.rsplit("@", 1)[0]

    noisy: list[str] = []
    if base:
        for left, right, verdict in stanzas:
            if verdict.startswith("tests: FAIL") and bare(left) == base:
                noisy.append(bare(right))
    real: list[str] = []
    for left, right, verdict in stanzas:
        # Only SEMANTIC verdicts can be noise from a red-alone branch. A
        # textual conflict is a `git merge-tree` result and has nothing to do
        # with the boundary test, so suppressing it would hide a genuine
        # cross-branch conflict and bias the crystal arm toward "found
        # nothing".
        if verdict.startswith("tests: FAIL") and (bare(left) in noisy
                                                  or bare(right) in noisy):
            continue
        if base and bare(left) == base and verdict.startswith("tests: FAIL"):
            continue                                # the red-alone finding itself
        real.append(f"{left} × {right} — {verdict}")
    return real, sorted(set(noisy))


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
      f"{('`' + man['ablation'] + '`') if man['ablation'] else (', '.join(man['ablation_set']) or 'none — every mechanism on')}")
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
        A(f"     · crystal loop every {cfg.crystal['interval_s']}s, test-cmd "
          f"{crystal_test_cmd(cfg)!r}")
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
