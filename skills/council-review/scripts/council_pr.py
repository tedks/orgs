#!/usr/bin/env python3
"""PR round records for council-review.

A PR council writes its frozen head, merge-base and per-seat outcomes as
machine-readable PR comments ("round records"). This helper resolves a PR to
immutable revisions, reads those records back and derives what each seat must
review next, renders new records, posts them idempotently, and rechecks
clearance against the live PR before anyone relies on it.

It never dispatches reviewers and keeps no state outside the PR comments.
Every rule that can fail is a small pure function so that the fixture suite
(test_council_pr.py) can exercise it. The record schema and the planning rules
are documented in ../references/pr-rounds.md.

Exit codes: 0 ok (check: CLEAN), 1 check: not clean, 2 usage or environment
error, 3 the current branch has no open PR (advisory review applies),
4 refused (the invocation does not name the PR's current revisions).
"""

import argparse
import json
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone

SCHEMA = "council-review-round"
VERSION = 1
MARK_OPEN = "<!-- council-review-round"
MARK_CLOSE = "-->"
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Provider seats, in council order, with the ask-agent CLI and Lead-tier model.
SEATS = {
    "anthropic": {"cli": "claude", "model": "opus"},
    "openai": {"cli": "codex", "model": "gpt-6-sol"},
    "google": {"cli": "agy", "model": "agy-lead-default"},
}
SCOPES = {"full", "delta", "disposition"}
ROUTES = {"pr", "branch-pr", "legacy-formal"}
# Invocation notes record how a valid invocation was routed (alias adoption,
# branch routing). They are context, not mistakes: the ten-council measurement
# counts only refused-then-corrected invocations, carried as `corrections`.
INFO_NOTES = {"legacy-formal-alias", "branch-routed-to-pr", "unpushed-local-commits"}
# Public records carry only closed vocabularies: an argument's normalized
# shape, never its text (a malformed argument may be a private path or pasted
# material), and an EMPTY seat's reason code, never free text.
ARG_SHAPES = {"pr-ref", "branch", "formal-sha", "formal-sha-base", "formal-other",
              "none", "other"}
EMPTY_REASONS = {"unavailable", "usage-limit", "timeout", "permission-denied",
                 "partial-prompt", "not-installed", "tool-error", "abandoned"}
REFUSAL_CODES = {
    "pr-not-open", "head-not-fetchable", "supplied-sha-mismatch",
    "supplied-base-mismatch", "unrecognized-argument", "wrong-pr",
}


class Refusal(Exception):
    """The invocation does not name the PR's current revisions (exit 4)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class EnvError(Exception):
    """A tool or environment failure (exit 2)."""


# --------------------------------------------------------------------------
# Record text


def canonical(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def encode_block(record):
    # '<' and '>' only occur inside JSON strings, so escaping them keeps the
    # JSON valid and guarantees no string can close the HTML comment early.
    text = json.dumps(record, sort_keys=True, indent=1)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"{MARK_OPEN}\n{text}\n{MARK_CLOSE}"


def extract(body):
    """Return (record, error). (None, None) when the body has no record."""
    start = body.find(MARK_OPEN)
    if start < 0:
        return None, None
    if body.find(MARK_OPEN, start + 1) >= 0:
        return None, "more than one record block"
    end = body.find(MARK_CLOSE, start + len(MARK_OPEN))
    if end < 0:
        return None, "unterminated record block"
    try:
        return json.loads(body[start + len(MARK_OPEN):end]), None
    except ValueError as exc:
        return None, f"invalid JSON ({exc})"


# --------------------------------------------------------------------------
# Guards. Each returns a reason string when the input must be ignored.


def trust_reason(comment):
    assoc = comment.get("author_association")
    if assoc not in TRUSTED_ASSOCIATIONS:
        return f"untrusted author association {assoc!r}"
    if comment.get("updated_at") != comment.get("created_at"):
        return "edited after posting"
    return None


def _sha(value):
    return isinstance(value, str) and bool(SHA_RE.match(value))


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate(rec, repo, pr):
    """Return None for a well-formed v1 record of this PR, else a reason."""
    if not isinstance(rec, dict):
        return "record is not an object"
    if rec.get("schema") != SCHEMA:
        return "wrong schema"
    version = rec.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        return "missing version"
    if version > VERSION:
        return f"unsupported future version {version}"
    if version != VERSION:
        return f"unsupported version {version}"
    if rec.get("repo") != repo or rec.get("pr") != pr:
        return "record names another repository or PR"
    phase = rec.get("phase")
    if phase not in ("open", "outcome"):
        return "unknown phase"
    rid = rec.get("round_id")
    if not isinstance(rid, str) or not 0 < len(rid) <= 80:
        return "bad round_id"
    for key in ("head", "base", "target_oid"):
        if not _sha(rec.get(key)):
            return f"bad {key}"
    if not isinstance(rec.get("target_ref"), str) or not rec["target_ref"]:
        return "bad target_ref"
    seats = rec.get("seats")
    if not isinstance(seats, list) or not seats:
        return "no seats"
    names = set()
    for seat in seats:
        why = _seat_reason(seat, rec, phase)
        if why:
            return why
        if seat["seat"] in names:
            return f"seat {seat['seat']} listed twice"
        names.add(seat["seat"])
    if phase == "open":
        covered = rec.get("covered")
        if not isinstance(covered, list):
            return "bad covered list"
        for entry in covered:
            if not isinstance(entry, dict) or entry.get("through") != rec["head"] \
                    or not isinstance(entry.get("seat"), str):
                return "covered entries must name a seat covered through the head"
            if entry["seat"] in names:
                return f"seat {entry['seat']} listed twice"
            names.add(entry["seat"])
        inv = rec.get("invocation")
        if not isinstance(inv, dict) or set(inv) != {"shape", "route", "notes", "corrections"} \
                or inv.get("shape") not in ARG_SHAPES:
            return "bad invocation"
        if inv.get("route") not in ROUTES:
            return "bad invocation route"
        notes = inv.get("notes")
        if not isinstance(notes, list) or not set(notes) <= INFO_NOTES:
            return "bad invocation notes"
        corrections = inv.get("corrections")
        if not isinstance(corrections, list) or not all(
            isinstance(c, dict) and set(c) == {"shape", "reason"}
            and c["shape"] in ARG_SHAPES and c["reason"] in REFUSAL_CODES for c in corrections
        ):
            return "bad invocation corrections"
    elif not _count(rec.get("unresolved_findings")):
        return "bad unresolved_findings"
    return None


def _seat_reason(seat, rec, phase):
    if not isinstance(seat, dict) or not isinstance(seat.get("seat"), str):
        return "bad seat entry"
    name = seat["seat"]
    if not re.match(r"^[a-z][a-z0-9-]{0,30}$", name):
        return "bad seat name"
    scope, start = seat.get("scope"), seat.get("from")
    if scope not in SCOPES or not _sha(start):
        return f"seat {name}: bad scope or from"
    if seat.get("continuity") not in ("fresh", "warm"):
        return f"seat {name}: bad continuity"
    if (scope == "full") != (start == rec["base"]):
        return f"seat {name}: full scope must start at the base"
    if (scope == "disposition") != (start == rec["head"]):
        return f"seat {name}: only a disposition review starts at the head"
    if scope != "full" and seat["continuity"] != "warm":
        return f"seat {name}: a {scope} review requires a warm seat"
    status = seat.get("status")
    if phase == "open":
        if status != "dispatched":
            return f"seat {name}: open records only dispatch"
        return None
    if status == "empty":
        if seat.get("reason") not in EMPTY_REASONS:
            return f"seat {name}: empty seat needs a reason code"
        return None
    if status != "received":
        return f"seat {name}: bad status"
    counts = seat.get("counts")
    if not isinstance(counts, dict) or not all(
        _count(counts.get(k)) for k in ("critical", "important", "nit")
    ):
        return f"seat {name}: bad counts"
    blocking = counts["critical"] + counts["important"]
    if seat.get("verdict") != ("findings" if blocking else "clean"):
        return f"seat {name}: verdict disagrees with counts"
    return None


def frame(rec):
    return (rec["head"], rec["base"], rec["target_ref"], rec["target_oid"])


def outcome_scope_reason(dispatched, outcome):
    """An outcome may only claim what it was dispatched for, or a full review."""
    planned = (dispatched["scope"], dispatched["from"], dispatched["continuity"])
    claimed = (outcome["scope"], outcome["from"], outcome["continuity"])
    if claimed == planned or outcome["scope"] == "full":
        return None
    return f"seat {outcome['seat']}: outcome scope differs from its dispatch"


# --------------------------------------------------------------------------
# Reading records into rounds


def load_records(comments, repo, pr):
    usable, ignored = [], []
    for comment in comments:
        rec, err = extract(comment.get("body") or "")
        if rec is None and err is None:
            continue
        why = err or trust_reason(comment) or validate(rec, repo, pr)
        if why:
            ignored.append({"comment": comment.get("id"), "reason": why})
            continue
        usable.append({"comment": comment.get("id"),
                       "created_at": comment["created_at"], "record": rec})
    usable.sort(key=lambda u: (u["created_at"], str(u["comment"])))
    return usable, ignored


def assemble(usable):
    """Group records into rounds; return (ordered rounds, ignored)."""
    groups, ignored = {}, []
    for item in usable:
        rec = item["record"]
        group = groups.setdefault(rec["round_id"], {"opens": [], "outcomes": []})
        group["opens" if rec["phase"] == "open" else "outcomes"].append(item)
    rounds = []
    for rid, group in groups.items():
        if not group["opens"]:
            ignored.extend({"comment": i["comment"], "reason": "outcome without an open record"}
                           for i in group["outcomes"])
            continue
        rounds.append(_build_round(rid, group))
    rounds.sort(key=lambda r: (r["opened_at"], r["id"]))
    return rounds, ignored


def _build_round(rid, group):
    first = group["opens"][0]
    opened = first["record"]
    rnd = {"id": rid, "open": opened, "opened_at": first["created_at"],
           "conflict": None, "seats": {}, "unresolved": None, "outcome_at": None}
    # Re-posting an identical open record is a retry, not a second round.
    if any(canonical(o["record"]) != canonical(opened) for o in group["opens"][1:]):
        rnd["conflict"] = "conflicting open records"
    dispatched = {s["seat"]: s for s in opened["seats"]}
    received, empty = {}, {}
    for item in group["outcomes"]:
        rec = item["record"]
        if frame(rec) != frame(opened):
            rnd["conflict"] = rnd["conflict"] or "outcome revisions differ from the open record"
            continue
        for seat in rec["seats"]:
            name = seat["seat"]
            if name not in dispatched:
                rnd["conflict"] = rnd["conflict"] or f"outcome for undispatched seat {name}"
                continue
            why = outcome_scope_reason(dispatched[name], seat)
            if why:
                rnd["conflict"] = rnd["conflict"] or why
                continue
            target = received if seat["status"] == "received" else empty
            target.setdefault(name, {})[canonical(seat)] = seat
        rnd["unresolved"] = rec["unresolved_findings"]
        rnd["outcome_at"] = item["created_at"]
    for name in dispatched:
        if len(received.get(name, {})) > 1:
            rnd["conflict"] = rnd["conflict"] or f"conflicting outcomes for seat {name}"
        elif name in received:
            # A late reviewer's received outcome supersedes an earlier EMPTY.
            rnd["seats"][name] = next(iter(received[name].values()))
        elif name in empty:
            rnd["seats"][name] = next(iter(empty[name].values()))
    return rnd


# --------------------------------------------------------------------------
# Coverage and planning


def chain_step(coverage, outcome, round_head):
    """Coverage after one received outcome; None when the chain breaks."""
    if outcome["scope"] == "full":
        return round_head
    if outcome["continuity"] == "warm" and coverage is not None and outcome["from"] == coverage:
        return round_head
    # A delta given to a restarted reviewer, or one that does not start where
    # this seat's coverage ended, proves nothing about the rest of the change.
    return None


def same_frame(rnd, base, target_ref):
    return rnd["open"]["base"] == base and rnd["open"]["target_ref"] == target_ref


def seat_state(rounds, seat, head, base, target_ref, is_ancestor):
    """Return (coverage sha or None, latest verdict at head or None)."""
    coverage, verdict_at = None, {}
    for rnd in rounds:
        if rnd["conflict"] or not same_frame(rnd, base, target_ref):
            continue
        outcome = rnd["seats"].get(seat)
        if not outcome or outcome["status"] != "received":
            continue
        coverage = chain_step(coverage, outcome, rnd["open"]["head"])
        if coverage is not None:
            verdict_at[coverage] = outcome["verdict"]
    coverage = coverage_in_head(coverage, head, is_ancestor)
    return coverage, (verdict_at.get(head) if coverage == head else None)


def coverage_in_head(coverage, head, is_ancestor):
    if coverage is not None and not is_ancestor(coverage, head):
        return None  # force-pushed away: the reviewed commits are not in this head
    return coverage


def plan(resolved, rounds, host, is_ancestor):
    head, base, target_ref = resolved["head"], resolved["base"], resolved["target_ref"]
    order = list(SEATS) + ([host] if host not in SEATS else [])
    seats, covered = [], []
    for name in order:
        coverage, verdict = seat_state(rounds, name, head, base, target_ref, is_ancestor)
        entry = {"seat": name, "mechanism": "native" if name == host else "ask-agent",
                 "cli": SEATS.get(name, {}).get("cli"),
                 "model": SEATS.get(name, {}).get("model"),
                 "fallback": {"scope": "full", "from": base, "continuity": "fresh"}}
        if coverage is None:
            entry.update(scope="full", **{"from": base}, continuity="fresh")
            entry["fallback"] = None
        elif coverage == head and verdict == "clean":
            covered.append({"seat": name, "through": head})
            continue
        elif coverage == head:
            entry.update(scope="disposition", **{"from": head}, continuity="warm")
        else:
            entry.update(scope="delta", **{"from": coverage}, continuity="warm")
        seats.append(entry)
    return {"seats": seats, "covered": covered}


def invocation_notes(route, local_head, head):
    notes = []
    if route == "legacy-formal":
        notes.append("legacy-formal-alias")
    if route == "branch-pr":
        notes.append("branch-routed-to-pr")
    if route != "pr" and local_head and local_head != head:
        notes.append("unpushed-local-commits")
    return notes


def arg_shape(text):
    """Normalize an invocation argument to a public shape; the text is dropped."""
    words = (text or "").split()
    hexsha = re.compile(r"^[0-9a-fA-F]{7,40}$")
    if not words:
        return "none"
    if re.fullmatch(r"(?:PR\s*)?#?\d+", " ".join(words), re.I):
        return "pr-ref"
    if words == ["branch"]:
        return "branch"
    if words[0] == "formal":
        rest = words[1:]
        if len(rest) == 1 and hexsha.match(rest[0]):
            return "formal-sha"
        if len(rest) == 2 and all(hexsha.match(w) for w in rest):
            return "formal-sha-base"
        return "formal-other"
    return "other"


def check_legacy(resolved, sha, base):
    if sha and sha != resolved["head"]:
        raise Refusal("supplied-sha-mismatch",
                      f"supplied SHA {sha} is not the PR's pushed head {resolved['head']}")
    if base and base != resolved["base"]:
        raise Refusal("supplied-base-mismatch",
                      f"supplied base {base} is not the merge-base {resolved['base']}")


def new_round_id(head, now=None, token=None):
    now = now or datetime.now(timezone.utc)
    return f"{head[:12]}-{now.strftime('%Y%m%dT%H%M%SZ')}-{token or secrets.token_hex(3)}"


def open_record(resolved, seat_plan, invocation, round_id):
    return {
        "schema": SCHEMA, "version": VERSION, "phase": "open",
        "repo": resolved["repo"], "pr": resolved["pr"], "round_id": round_id,
        "head": resolved["head"], "base": resolved["base"],
        "target_ref": resolved["target_ref"], "target_oid": resolved["target_oid"],
        "invocation": invocation,
        "covered": [{"seat": c["seat"], "through": c["through"]} for c in seat_plan["covered"]],
        "seats": [{"seat": s["seat"], "mechanism": s["mechanism"], "model": s["model"],
                   "scope": s["scope"], "from": s["from"], "continuity": s["continuity"],
                   "status": "dispatched"} for s in seat_plan["seats"]],
    }


def outcome_record(opened, outcomes, unresolved):
    dispatched = {s["seat"]: s for s in opened["seats"]}
    seats = []
    for out in outcomes:
        base_seat = dispatched.get(out.get("seat"))
        if base_seat is None:
            raise EnvError(f"outcome for undispatched seat {out.get('seat')!r}")
        seat = {k: base_seat[k] for k in ("seat", "mechanism", "model", "scope", "from", "continuity")}
        for key in ("scope", "from", "continuity", "model"):
            if key in out:
                seat[key] = out[key]
        seat["status"] = out.get("status")
        if seat["status"] == "received":
            seat["counts"] = out.get("counts")
            seat["verdict"] = out.get("verdict")
        else:
            seat["reason"] = out.get("reason")
        seats.append(seat)
    rec = {k: opened[k] for k in ("schema", "version", "repo", "pr", "round_id",
                                   "head", "base", "target_ref", "target_oid")}
    rec.update(phase="outcome", seats=seats, unresolved_findings=unresolved)
    why = validate(rec, opened["repo"], opened["pr"])
    if why:
        raise EnvError(f"outcome record invalid: {why}")
    for seat in seats:
        why = outcome_scope_reason(dispatched[seat["seat"]], seat)
        if why:
            raise EnvError(why)
    return rec


def clearance(resolved, rounds, is_ancestor, expect_head=None):
    """CLEAN only when the latest round at this head disposed of every seat.

    Each seat in that round must be explicit: a received outcome, an EMPTY
    outcome, or a `covered` entry whose earlier coverage still holds. A
    dispatched seat with no outcome is silence, and silence blocks.
    """
    head, base, target_ref = resolved["head"], resolved["base"], resolved["target_ref"]
    reasons = []
    if expect_head and expect_head != head:
        reasons.append(f"PR head is {head}, not the expected {expect_head}")
    at_head = [r for r in rounds if not r["conflict"] and same_frame(r, base, target_ref)
               and r["open"]["head"] == head]
    latest = at_head[-1] if at_head else None  # rounds are in opening order
    names = list(SEATS)
    for rnd in rounds:
        names.extend(n for n in list(rnd["seats"]) + [s["seat"] for s in rnd["open"]["seats"]]
                     if n not in names)
    seats = {}
    if latest is None:
        reasons.append("no round was opened at this head")
    else:
        silent = undisposed_seats(latest)
        for name in silent:
            seats[name] = "no-outcome"
            reasons.append(f"seat {name} was dispatched in round {latest['id']} "
                           "but has no recorded outcome (record EMPTY if it is not coming)")
        for entry in latest["open"]["seats"]:
            name = entry["seat"]
            got = latest["seats"].get(name)
            if name in silent or got is None:
                continue
            if got["status"] == "empty":
                seats[name] = "empty"
            else:
                coverage, verdict = seat_state(rounds, name, head, base, target_ref, is_ancestor)
                seats[name] = verdict if coverage == head else "unchained"
        for entry in latest["open"]["covered"]:
            name = entry["seat"]
            coverage, verdict = seat_state(rounds, name, head, base, target_ref, is_ancestor)
            seats[name] = "clean" if (coverage == head and verdict == "clean") else "unchained"
        if latest["outcome_at"] is None and latest["open"]["seats"]:
            reasons.append(f"round {latest['id']} has no outcome record")
        elif latest["unresolved"]:
            reasons.append(f"{latest['unresolved']} earlier findings not yet dispositioned")
    for name in names:
        if name not in seats:
            coverage, _ = seat_state(rounds, name, head, base, target_ref, is_ancestor)
            seats[name] = "stale" if coverage is not None else "missing"
    findings = [n for n, v in seats.items() if v == "findings"]
    if findings:
        reasons.append("open Critical/Important findings at head from: " + ", ".join(findings))
    unchained = [n for n, v in seats.items() if v == "unchained"]
    if unchained:
        reasons.append("seats whose reviews do not chain to full coverage of this head: "
                       + ", ".join(unchained))
    if not any(v == "clean" for v in seats.values()):
        reasons.append("no seat has a received clean review covering this head")
    return {"head": head, "base": base, "target_ref": target_ref, "clean": not reasons,
            "round": latest["id"] if latest else None, "seats": seats, "reasons": reasons,
            "limits": [f"{n}: {v}" for n, v in seats.items() if v in ("empty", "missing", "stale")]}


def undisposed_seats(rnd):
    """Dispatched seats with neither a received nor an EMPTY outcome."""
    return [s["seat"] for s in rnd["open"]["seats"] if s["seat"] not in rnd["seats"]]


def tally(open_rounds, limit=10):
    """open_rounds: [(repo, rnd)]. Count the first `limit` rounds across PRs."""
    seen, rows = set(), []
    for repo, rnd in sorted(open_rounds, key=lambda x: (x[1]["opened_at"], x[0], x[1]["id"])):
        if (repo, rnd["id"]) in seen or not rnd.get("outcome_at"):
            continue  # a retry seen twice, or an abandoned open-only round
        seen.add((repo, rnd["id"]))
        inv = rnd["open"]["invocation"]
        rows.append({"opened_at": rnd["opened_at"], "repo": repo, "pr": rnd["open"]["pr"],
                     "round_id": rnd["id"], "shape": inv["shape"], "route": inv["route"],
                     "notes": list(inv["notes"]),
                     "mistakes": [c["reason"] for c in inv["corrections"]]})
        if len(rows) == limit:
            break
    return {"rounds": len(rows), "window": limit,
            "rounds_with_mistakes": sum(1 for r in rows if r["mistakes"]),
            "mistakes": sum(len(r["mistakes"]) for r in rows),
            "alias_uses": sum(1 for r in rows if "legacy-formal-alias" in r["notes"]),
            "rows": rows}


def render(rec, rounds_note=""):
    lines = []
    if rec["phase"] == "open":
        lines.append(f"**council-review-round v{VERSION}: round `{rec['round_id']}` opened**")
        lines.append("")
        lines.append(f"Frozen head `{rec['head']}`; base `{rec['base']}` "
                     f"(merge-base with `{rec['target_ref']}` at `{rec['target_oid']}`).")
        lines.append("")
        lines.append("| Seat | Mechanism | Model | Reviews |")
        lines.append("|---|---|---|---|")
        for s in rec["seats"]:
            span = f"`{s['from'][:12]}..{rec['head'][:12]}`"
            lines.append(f"| {s['seat']} | {s['mechanism']} | {s['model']} | {s['scope']} {span} ({s['continuity']}) |")
    else:
        lines.append(f"**council-review-round v{VERSION}: round `{rec['round_id']}` outcomes**")
        lines.append("")
        lines.append(f"Head `{rec['head']}`; base `{rec['base']}`. "
                     f"Undispositioned earlier findings: {rec['unresolved_findings']}.")
        lines.append("")
        lines.append("| Seat | Result | Critical | Important | Nit | Reviewed |")
        lines.append("|---|---|---|---|---|---|")
        for s in rec["seats"]:
            span = f"{s['scope']} `{s['from'][:12]}..{rec['head'][:12]}`"
            if s["status"] == "received":
                c = s["counts"]
                lines.append(f"| {s['seat']} | {s['verdict'].upper()} | {c['critical']} | "
                             f"{c['important']} | {c['nit']} | {span} |")
            else:
                lines.append(f"| {s['seat']} | EMPTY: {s['reason']} | | | | {span} |")
    if rounds_note:
        lines += ["", rounds_note]
    lines += ["", "The block below is the authoritative round record. Do not edit it: "
              "an edited record is ignored.", "", encode_block(rec), ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# git / gh boundary


def run(cmd, cwd=None, check=True):
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise EnvError(f"{cmd[0]} not found") from exc
    if check and proc.returncode != 0:
        raise EnvError(f"{' '.join(cmd[:3])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def git_is_ancestor(cwd):
    def is_ancestor(a, b):
        return run(["git", "merge-base", "--is-ancestor", a, b], cwd, check=False).returncode == 0
    return is_ancestor


def find_remote(cwd, repo):
    out = run(["git", "config", "--get-regexp", r"^remote\..*\.url$"], cwd, check=False).stdout
    pattern = re.compile(r"github\.com[:/]" + re.escape(repo) + r"(\.git)?/?$", re.I)
    for line in out.splitlines():
        key, _, url = line.partition(" ")
        if pattern.search(url.strip()):
            return key[len("remote."):-len(".url")]
    raise EnvError(f"no git remote points at github.com/{repo}")


PR_FIELDS = "number,url,state,headRefOid,headRefName,baseRefName,baseRefOid"


def resolve(cwd, pr=None):
    cmd = ["gh", "pr", "view"] + ([str(pr)] if pr is not None else []) + ["--json", PR_FIELDS]
    proc = run(cmd, cwd, check=False)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        if pr is None and "no pull requests found" in msg.lower():
            return None
        raise EnvError(f"gh pr view failed: {msg}")
    info = json.loads(proc.stdout)
    if info.get("state") != "OPEN":
        if pr is None:
            return None  # a branch whose PR is closed has no formal target
        raise Refusal("pr-not-open", f"PR #{info.get('number')} is {info.get('state')}")
    match = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", info.get("url", ""))
    if not match:
        raise EnvError(f"cannot read the repository from PR url {info.get('url')!r}")
    repo, number = match.group(1), int(match.group(2))
    head, target_oid = info["headRefOid"], info["baseRefOid"]
    remote = find_remote(cwd, repo)
    run(["git", "fetch", "--no-tags", "--quiet", remote,
         f"refs/pull/{number}/head", f"refs/heads/{info['baseRefName']}"], cwd)
    for sha in (head, target_oid):
        if run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd, check=False).returncode:
            raise Refusal("head-not-fetchable", f"{sha} is not fetchable; the PR moved, retry")
    base = run(["git", "merge-base", head, target_oid], cwd).stdout.strip()
    local = run(["git", "rev-parse", "HEAD"], cwd, check=False)
    return {"repo": repo, "pr": number, "url": info["url"], "head": head,
            "head_ref": info["headRefName"], "target_ref": info["baseRefName"],
            "target_oid": target_oid, "base": base,
            "local_head": local.stdout.strip() if local.returncode == 0 else None}


def fetch_comments(cwd, repo, pr):
    proc = run(["gh", "api", "--paginate", f"repos/{repo}/issues/{pr}/comments",
                "--jq", ".[]"], cwd)
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def rounds_for(cwd, repo, pr):
    usable, ignored = load_records(fetch_comments(cwd, repo, pr), repo, pr)
    rounds, orphans = assemble(usable)
    return rounds, ignored + orphans + [
        {"round": r["id"], "reason": r["conflict"]} for r in rounds if r["conflict"]]


# --------------------------------------------------------------------------
# Commands


def emit(obj):
    print(json.dumps(obj, indent=1, sort_keys=True))


def parse_pr(text):
    match = re.fullmatch(r"(?:PR\s*)?#?(\d+)", (text or "").strip(), re.I)
    if not match:
        raise Refusal("unrecognized-argument", f"not a PR reference: {text!r}")
    return int(match.group(1))


def cmd_resolve(args):
    resolved = resolve(args.repo_dir, parse_pr(args.pr) if args.pr else None)
    if resolved is None:
        print("no open PR for the current branch: the review is advisory", file=sys.stderr)
        return 3
    emit(resolved)
    return 0


def cmd_plan(args):
    if args.route == "pr" and not args.pr:
        raise EnvError("route pr needs --pr")
    resolved = resolve(args.repo_dir, parse_pr(args.pr) if args.pr else None)
    if resolved is None:
        print("no open PR for the current branch: the review is advisory", file=sys.stderr)
        return 3
    check_legacy(resolved, args.legacy_sha, args.legacy_base)
    rounds, ignored = rounds_for(args.repo_dir, resolved["repo"], resolved["pr"])
    seat_plan = plan(resolved, rounds, args.host, git_is_ancestor(args.repo_dir))
    invocation = {
        "shape": arg_shape(args.raw), "route": args.route,
        "notes": invocation_notes(args.route, resolved["local_head"], resolved["head"]),
        "corrections": [{"shape": arg_shape(raw), "reason": reason}
                        for raw, reason in args.correction or []],
    }
    out = {"resolved": resolved, "plan": seat_plan, "ignored": ignored,
           "previous_rounds": [{"id": r["id"], "head": r["open"]["head"]} for r in rounds]}
    if seat_plan["seats"]:
        rec = open_record(resolved, seat_plan, invocation, new_round_id(resolved["head"]))
        why = validate(rec, resolved["repo"], resolved["pr"])
        if why:
            raise EnvError(f"open record invalid: {why}")
        out["open_record"] = rec
    emit(out)
    return 0


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def cmd_render(args):
    opened = _load_json(args.open_record)
    if args.outcomes:
        rec = outcome_record(opened, _load_json(args.outcomes), args.unresolved)
    else:
        why = validate(opened, opened.get("repo"), opened.get("pr"))
        if why or opened.get("phase") != "open":
            raise EnvError(f"not a valid open record: {why or 'wrong phase'}")
        rec = opened
    sys.stdout.write(render(rec))
    return 0


def cmd_post(args):
    with open(args.body_file, encoding="utf-8") as handle:
        body = handle.read()
    rec, err = extract(body)
    if rec is None:
        raise EnvError(f"body has no record: {err or 'missing block'}")
    why = validate(rec, rec.get("repo"), rec.get("pr"))
    if why:
        raise EnvError(f"refusing to post an invalid record: {why}")
    for comment in fetch_comments(args.repo_dir, rec["repo"], rec["pr"]):
        existing, _ = extract(comment.get("body") or "")
        if existing is not None and not trust_reason(comment) and canonical(existing) == canonical(rec):
            print(f"already posted as comment {comment.get('id')}; not posting again")
            return 0
    run(["gh", "pr", "comment", str(rec["pr"]), "--repo", rec["repo"],
         "--body-file", args.body_file], args.repo_dir)
    print("posted")
    return 0


def cmd_check(args):
    resolved = resolve(args.repo_dir, parse_pr(args.pr) if args.pr else None)
    if resolved is None:
        print("no open PR for the current branch", file=sys.stderr)
        return 3
    rounds, ignored = rounds_for(args.repo_dir, resolved["repo"], resolved["pr"])
    result = clearance(resolved, rounds, git_is_ancestor(args.repo_dir), args.expect_head)
    result["ignored"] = ignored
    emit(result)
    return 0 if result["clean"] else 1


def cmd_tally(args):
    collected = []
    for ref in args.prs:
        match = re.fullmatch(r"([^/\s]+/[^#\s]+)#(\d+)", ref)
        if not match:
            raise EnvError(f"expected OWNER/REPO#N, got {ref!r}")
        repo, pr = match.group(1), int(match.group(2))
        rounds, _ = rounds_for(args.repo_dir, repo, pr)
        collected.extend((repo, r) for r in rounds)
    emit(tally(collected, args.window))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-dir", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("resolve", help="PR (or current branch's PR) to frozen revisions")
    p.add_argument("pr", nargs="?")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("plan", help="read round records and plan each seat's review")
    p.add_argument("--pr")
    p.add_argument("--host", required=True, help="the host's own provider, e.g. anthropic")
    p.add_argument("--route", choices=sorted(ROUTES), required=True)
    p.add_argument("--raw", required=True,
                   help="the argument as typed; only its normalized shape is recorded")
    p.add_argument("--legacy-sha")
    p.add_argument("--legacy-base")
    p.add_argument("--correction", nargs=2, action="append", metavar=("RAW", "REASON"),
                   help="an earlier refused invocation in this session and its refusal code; "
                        "only the shape and code are recorded")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("render", help="render an open or outcome record comment")
    p.add_argument("--open-record", required=True)
    p.add_argument("--outcomes")
    p.add_argument("--unresolved", type=int, default=0)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("post", help="post a record comment unless already present")
    p.add_argument("--body-file", required=True)
    p.set_defaults(func=cmd_post)

    p = sub.add_parser("check", help="recheck the live PR and report clearance")
    p.add_argument("pr", nargs="?")
    p.add_argument("--expect-head")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("tally", help="the invocation-mistake measurement window")
    p.add_argument("prs", nargs="+", metavar="OWNER/REPO#N")
    p.add_argument("--window", type=int, default=10)
    p.set_defaults(func=cmd_tally)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Refusal as exc:
        print(f"refused ({exc.code}): {exc}", file=sys.stderr)
        return 4
    except EnvError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
