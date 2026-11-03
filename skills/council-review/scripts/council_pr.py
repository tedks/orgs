#!/usr/bin/env python3
"""PR round records for council-review.

A PR council writes its frozen head, merge-base and per-seat outcomes as
machine-readable PR comments ("round records"). This helper resolves a PR to
immutable revisions, reads those records back and derives what each seat must
review next, renders new records, posts them idempotently, and rechecks
clearance against the live PR before anyone relies on it.

It never dispatches reviewers. Its only state outside PR comments is a small
per-checkout list of refused invocations (inside the git directory), which the
next round's record carries as measurement evidence. Every rule that can fail
is a small function the fixture suite (test_council_pr.py) exercises. The
record schema and the planning rules are in ../references/pr-rounds.md.

Exit codes: 0 ok (check: CLEAN), 1 check: not clean, 2 usage or environment
error, 3 advisory target (no formal round: not a PR reference, or the branch
has no open PR), 4 refused (the invocation does not name the PR's current
revisions, or the PR moved during resolution).
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
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
HEX_ABBREV = re.compile(r"^[0-9a-fA-F]{7,40}$")
SEAT_NAME = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")
REF_NAME = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
ROUND_ID = re.compile(r"^[0-9a-f]{12}-\d{8}T\d{6}Z-[0-9a-f]{6}$")
EVENT_ID = re.compile(r"^[0-9a-f]{8}$")
DIGEST = re.compile(r"^[0-9a-f]{12}$")
# Provider seats, in council order, with the ask-agent CLI and Lead-tier model.
SEATS = {
    "anthropic": {"cli": "claude", "model": "opus"},
    "openai": {"cli": "codex", "model": "gpt-6-sol"},
    "google": {"cli": "agy", "model": "agy-lead-default"},
}
# CLI names are never provider names: `--host claude` would seat Anthropic
# through ask-agent from an Anthropic host.
CLI_NAMES = {"claude", "codex", "agy", "gemini"}
MECHANISMS = {"native", "inline", "ask-agent"}
SCOPES = {"full", "delta", "disposition"}
ROUTES = {"pr", "branch-pr", "legacy-formal"}
# Invocation notes record how a valid invocation was routed (alias adoption,
# branch routing). They are context, not mistakes.
INFO_NOTES = {"legacy-formal-alias", "branch-routed-to-pr", "unpushed-local-commits"}
# Public records carry only closed vocabularies: an argument's normalized
# shape, never its text (a malformed argument may be a private path or pasted
# material), and an EMPTY seat's reason code, never free text.
ARG_SHAPES = {"pr-ref", "branch", "formal-sha", "formal-sha-base", "formal-other",
              "none", "other"}
EMPTY_REASONS = {"unavailable", "usage-limit", "timeout", "permission-denied",
                 "partial-prompt", "not-installed", "tool-error", "abandoned"}
# Refusals caused by the caller's argument. These are the measured mistakes.
CALLER_REFUSALS = {"unrecognized-argument", "pr-not-found", "pr-not-open",
                   "formal-sha-missing", "formal-without-pr", "supplied-sha-mismatch",
                   "supplied-base-mismatch"}
# Refusals that are not the caller's mistake: the PR moved mid-resolution.
OTHER_REFUSALS = {"pr-moved", "head-not-fetchable"}
# Production rounds are measured; evaluation rounds (acceptance replays,
# dogfooding a branch's helper) are recorded but never counted.
COHORTS = {"production", "evaluation"}

COMMON_KEYS = {"schema", "version", "phase", "repo", "pr", "round_id", "head", "base",
               "target_ref", "target_oid", "seats"}
RECORD_KEYS = {"open": COMMON_KEYS | {"invocation", "covered", "standing"},
               "outcome": COMMON_KEYS | {"unresolved_findings"}}
SEAT_KEYS = {"seat", "mechanism", "model", "scope", "from", "continuity", "status"}
STATUS_KEYS = {"dispatched": SEAT_KEYS, "received": SEAT_KEYS | {"verdict", "counts"},
               "empty": SEAT_KEYS | {"reason"}}
PENDING_FILE = "council-review-pending-refusals.json"


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


def unknown_keys(obj, allowed):
    """Closed key sets keep free text out of public records."""
    extra = set(obj) - allowed
    return f"unexpected fields {sorted(extra)}" if extra else None


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
    if phase not in RECORD_KEYS:
        return "unknown phase"
    why = unknown_keys(rec, RECORD_KEYS[phase])
    if why:
        return why
    for key in ("head", "base", "target_oid"):
        if not _sha(rec.get(key)):
            return f"bad {key}"
    if not isinstance(rec.get("round_id"), str) or not ROUND_ID.match(rec["round_id"]) \
            or rec["round_id"][:12] != rec["head"][:12]:
        return "bad round_id (must be <head prefix>-<time>-<hex>)"
    if not isinstance(rec.get("target_ref"), str) or not REF_NAME.match(rec["target_ref"]):
        return "bad target_ref"
    seats = rec.get("seats")
    if not isinstance(seats, list):
        return "bad seats"
    names = set()
    for seat in seats:
        why = _seat_reason(seat, rec, phase)
        if why:
            return why
        if seat["seat"] in names:
            return f"seat {seat['seat']} listed twice"
        names.add(seat["seat"])
    if phase == "outcome":
        return None if _count(rec.get("unresolved_findings")) else "bad unresolved_findings"
    covered = rec.get("covered")
    if not isinstance(covered, list):
        return "bad covered list"
    for entry in covered:
        if not isinstance(entry, dict) or set(entry) != {"seat", "through"} \
                or not isinstance(entry["seat"], str) or not SEAT_NAME.match(entry["seat"]) \
                or entry["through"] != rec["head"]:
            return "covered entries must name a seat covered through the head"
        if entry["seat"] in names:
            return f"seat {entry['seat']} listed twice"
        names.add(entry["seat"])
    if not names:
        return "an open record must dispatch or cover at least one seat"
    standing = rec.get("standing")
    if not isinstance(standing, list) or not all(
            isinstance(f, dict) and set(f) == {"round", "seat", "outcome"}
            and isinstance(f["round"], str) and ROUND_ID.match(f["round"])
            and isinstance(f["seat"], str) and SEAT_NAME.match(f["seat"])
            and isinstance(f["outcome"], str) and DIGEST.match(f["outcome"]) for f in standing) \
            or len({(f["round"], f["seat"], f["outcome"]) for f in standing}) != len(standing):
        return "bad standing list"
    inv = rec.get("invocation")
    if not isinstance(inv, dict) or set(inv) != {"shape", "route", "notes", "corrections",
                                                 "unknown", "cohort"} \
            or inv.get("shape") not in ARG_SHAPES or inv.get("cohort") not in COHORTS:
        return "bad invocation"
    if inv.get("route") not in ROUTES:
        return "bad invocation route"
    notes = inv.get("notes")
    if not isinstance(notes, list) or not set(notes) <= INFO_NOTES:
        return "bad invocation notes"
    corrections = inv.get("corrections")
    if not isinstance(corrections, list) or not all(valid_correction(c) for c in corrections):
        return "bad invocation corrections"
    unknown = inv.get("unknown")
    if not isinstance(unknown, list) or not all(isinstance(u, str) and EVENT_ID.match(u)
                                                for u in unknown):
        return "bad invocation unknown"
    return None


def valid_correction(c):
    return (isinstance(c, dict) and set(c) == {"id", "shape", "reason"}
            and isinstance(c["id"], str) and bool(EVENT_ID.match(c["id"]))
            and c["shape"] in ARG_SHAPES and c["reason"] in CALLER_REFUSALS)


def _seat_reason(seat, rec, phase):
    if not isinstance(seat, dict) or not isinstance(seat.get("seat"), str):
        return "bad seat entry"
    name = seat["seat"]
    if not SEAT_NAME.match(name):
        return "bad seat name"
    status = seat.get("status")
    allowed = STATUS_KEYS.get(status)
    if allowed is None or (phase == "open") != (status == "dispatched"):
        return f"seat {name}: bad status for an {phase} record"
    why = unknown_keys(seat, allowed)
    if why:
        return f"seat {name}: {why}"
    if seat.get("mechanism") not in MECHANISMS:
        return f"seat {name}: bad mechanism"
    if not isinstance(seat.get("model"), str) or not MODEL_NAME.match(seat["model"]):
        return f"seat {name}: bad model"
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
    if status == "empty":
        if seat.get("reason") not in EMPTY_REASONS:
            return f"seat {name}: empty seat needs a reason code"
    elif status == "received":
        counts = seat.get("counts")
        if not isinstance(counts, dict) or set(counts) != {"critical", "important", "nit"} \
                or not all(_count(v) for v in counts.values()):
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


def _order(item):
    cid = item["comment"]
    return (item["created_at"], cid if isinstance(cid, int) else -1)


def load_records(comments, repo, pr):
    usable, ignored = [], []
    for comment in comments:
        rec, err = extract(comment.get("body") or "")
        if rec is None and err is None:
            continue
        why = err or trust_reason(comment) or validate(rec, repo, pr)
        if why:
            entry = {"comment": comment.get("id"), "reason": why}
            # A trusted comment that is not a usable record may still carry
            # findings; they stay evidence, because evidence can only block.
            # Untrusted comments never become evidence, so outsiders cannot
            # block a PR.
            if comment.get("author_association") in TRUSTED_ASSOCIATIONS:
                found = harvest_findings(rec, repo, pr)
                if found is None:
                    entry["unreadable"] = True
                elif found:
                    entry["evidence"] = [dict(f, comment=comment.get("id"),
                                              created_at=comment["created_at"]) for f in found]
            ignored.append(entry)
            continue
        usable.append({"comment": comment.get("id"),
                       "created_at": comment["created_at"], "record": rec})
    usable.sort(key=_order)
    return usable, ignored


def harvest_findings(rec, repo, pr):
    """Received findings in a record that is otherwise unusable.

    Returns a list of {round, seat, outcome}; [] when the record holds none or
    belongs to another PR; None when it cannot be read well enough to know.
    """
    if not isinstance(rec, dict) or rec.get("schema") != SCHEMA:
        return None
    if (rec.get("repo"), rec.get("pr")) != (repo, pr):
        return []
    if rec.get("version") != VERSION or not isinstance(rec.get("round_id"), str) \
            or not ROUND_ID.match(rec["round_id"]) or not isinstance(rec.get("seats"), list):
        return None
    found = []
    for seat in rec["seats"]:
        if not isinstance(seat, dict) or not isinstance(seat.get("seat"), str) \
                or not SEAT_NAME.match(seat["seat"]):
            return None
        counts = seat.get("counts") if isinstance(seat.get("counts"), dict) else {}
        blocking = sum(v for k, v in counts.items() if k in ("critical", "important") and _count(v))
        if seat.get("status") == "received" and (seat.get("verdict") == "findings" or blocking):
            found.append({"round": rec["round_id"], "seat": seat["seat"],
                          "outcome": outcome_digest(seat)})
    return found


def assemble(usable, ignored_records=()):
    """Group records into rounds; return (rounds in opening order, ignored).

    `ignored_records` (from load_records) contribute only finding evidence
    and unreadable markers; they never open, cover or examine anything.
    """
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
            # Kept only as finding evidence: it never examines, covers or
            # becomes a latest round (it has no frame), but its findings stand.
            rounds.append(_orphan_round(rid, group))
            continue
        rounds.append(_build_round(rid, group))
    by_id = {r["id"]: r for r in rounds}
    for entry in ignored_records:
        for f in entry.get("evidence", ()):
            order = (f["created_at"], f["comment"] if isinstance(f["comment"], int) else -1)
            rnd = by_id.get(f["round"])
            if rnd is None:
                rnd = by_id[f["round"]] = _evidence_round(f["round"], order)
                rounds.append(rnd)
            rnd["finding_posts"].setdefault((f["seat"], f["outcome"]), order)
        if entry.get("unreadable"):
            rounds.append(_evidence_round(f"unreadable-{entry['comment']}",
                                          ("", -1), unreadable=entry["comment"]))
    rounds.sort(key=lambda r: r["order"])
    return rounds, ignored


def _evidence_round(rid, order, unreadable=None):
    """A frameless holder for evidence from records that are not usable."""
    return {"id": rid, "orphan": True, "unreadable": unreadable,
            "open": {"head": None, "base": None, "target_ref": None,
                     "seats": [], "covered": [], "standing": [], "invocation": None},
            "opened_at": order[0], "order": order,
            "conflict": "evidence only", "seats": {}, "unresolved": None,
            "outcome_at": None, "named": set(), "frames": {}, "seat_posted": {},
            "finding_posts": {}}


def _finding_posts(outcome_items):
    """First posting time of each seat's received findings in a round's
    outcome records, whatever their validity within the round: evidence of a
    finding is never discarded, even where the round grants nothing."""
    posts = {}
    for item in outcome_items:
        for seat in item["record"]["seats"]:
            if seat["status"] == "received" and seat["verdict"] == "findings":
                # Each distinct outcome is its own evidence; an identical retry
                # is the same evidence and keeps its first posting.
                posts.setdefault((seat["seat"], outcome_digest(seat)), _order(item))
    return posts


def outcome_digest(seat):
    """A short fingerprint of one exact received outcome (canonical form)."""
    return hashlib.sha256(canonical(seat).encode()).hexdigest()[:12]


def _orphan_round(rid, group):
    first = group["outcomes"][0]
    rec = first["record"]
    return {"id": rid, "orphan": True,
            "open": {"head": rec["head"], "base": rec["base"], "target_ref": rec["target_ref"],
                     "seats": [], "covered": [], "standing": [], "invocation": None},
            "opened_at": first["created_at"], "order": _order(first),
            "conflict": "outcome without an open record", "seats": {}, "unresolved": None,
            "outcome_at": None, "named": set(), "frames": {}, "seat_posted": {},
            "finding_posts": _finding_posts(group["outcomes"])}


def _build_round(rid, group):
    first = group["opens"][0]
    opened = first["record"]
    rnd = {"id": rid, "open": opened, "opened_at": first["created_at"], "order": _order(first),
           "conflict": None, "seats": {}, "unresolved": None, "outcome_at": None,
           "named": set(), "frames": {}, "seat_posted": {},
           "finding_posts": _finding_posts(group["outcomes"])}
    # Re-posting an identical open record is a retry, not a second round.
    for item in group["opens"]:
        r = item["record"]
        # Each frame keeps the posting order of the first open that named it.
        rnd["frames"].setdefault((r["head"], r["base"], r["target_ref"]), _order(item))
        rnd["named"].update(s["seat"] for s in item["record"]["seats"])
        rnd["named"].update(c["seat"] for c in item["record"]["covered"])
        if canonical(item["record"]) != canonical(opened):
            rnd["conflict"] = "conflicting open records"
    dispatched = {s["seat"]: s for s in opened["seats"]}
    received, empty = {}, {}
    for item in group["outcomes"]:
        rec = item["record"]
        rnd["named"].update(s["seat"] for s in rec["seats"])
        if _order(item) < rnd["order"]:
            # An outcome cannot answer a dispatch that did not yet exist.
            rnd["conflict"] = rnd["conflict"] or "outcome posted before its open record"
            continue
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
            # Re-posting an identical outcome is a retry; only its first
            # posting carries information (and a posting time).
            if canonical(seat) in target.get(name, {}):
                continue
            target.setdefault(name, {})[canonical(seat)] = seat
            if seat["status"] == "received":
                rnd["seat_posted"].setdefault(name, _order(item))
        # A later record (a late reviewer's, say) can never lower the count.
        rnd["unresolved"] = max(rnd["unresolved"] or 0, rec["unresolved_findings"])
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


def chain_step(coverage, outcome, round_head, is_ancestor):
    """Coverage after one received outcome; None when the chain breaks."""
    if outcome["scope"] == "full":
        return round_head
    if (outcome["continuity"] == "warm" and coverage is not None
            and outcome["from"] == coverage and is_ancestor(coverage, round_head)):
        return round_head
    # A delta given to a restarted reviewer, one that does not start where this
    # seat's coverage ended, or one across a force-push proves nothing about
    # the rest of the change.
    return None


def same_frame(rnd, base, target_ref):
    """True when any of the round's open records has this frame.

    A void round may hold conflicting open records; each of their frames
    counts, so a conflicting record can never hide the void from a head.
    """
    return any(b == base and t == target_ref for _, b, t in rnd["frames"])


def void_resets(rnd, seat):
    """A void (conflicted) round erases the coverage of every seat it names."""
    return bool(rnd["conflict"]) and seat in rnd["named"]


def seat_state(rounds, seat, head, base, target_ref, is_ancestor):
    """Return (coverage sha or None, latest verdict at head or None)."""
    coverage, verdict_at = None, {}
    for rnd in rounds:
        if not same_frame(rnd, base, target_ref):
            continue
        if void_resets(rnd, seat):
            coverage, verdict_at = None, {}
            continue
        if rnd["conflict"]:
            continue
        outcome = rnd["seats"].get(seat)
        if not outcome or outcome["status"] != "received":
            continue
        coverage = chain_step(coverage, outcome, rnd["open"]["head"], is_ancestor)
        if coverage is not None:
            verdict_at[coverage] = outcome["verdict"]
    coverage = coverage_in_head(coverage, head, is_ancestor)
    return coverage, (verdict_at.get(head) if coverage == head else None)


def coverage_in_head(coverage, head, is_ancestor):
    if coverage is not None and not is_ancestor(coverage, head):
        return None  # force-pushed away: the reviewed commits are not in this head
    return coverage


def latest_round_at_head(rounds, head, base, target_ref):
    """The last round opened at this head and frame, void or not."""
    frame_key = (head, base, target_ref)
    at_head = [r for r in rounds if frame_key in r["frames"]]
    return max(at_head, key=lambda r: r["frames"][frame_key], default=None)


def unexamined_findings(rounds, head, base, target_ref, is_ancestor):
    """The one rule for findings: which findings still stand.

    A finding is one exact received findings outcome of one seat in one round,
    named {round, seat, outcome}, collected from every round of the PR whatever its frame or
    validity. It stands until a later round examines it: a round that is
    not void, at a head that is the current head or an ancestor of it, opened
    after the finding was posted, whose open record lists that finding in its
    `standing` snapshot (the snapshot its prompts were built from), and in
    which at least one dispatched seat returned a received review. No seat is
    exempt, the finder included: a late arrival, work on an older head, a
    finding posted after the snapshot, EMPTY outcomes, covered entries and
    silence examine nothing.
    """
    stand = []
    # Evidence comes from every round of the PR: any frame, void or orphaned.
    # Only examination is restricted to valid rounds of the current frame.
    for rnd in rounds:
        for (name, digest), posted in finding_evidence(rnd).items():
            key = finding_key(rnd["id"], name, digest)
            if not any(examines(r, key, posted, head, base, target_ref, is_ancestor)
                       for r in rounds):
                stand.append(key)
    return sorted(stand, key=lambda k: (k["round"], k["seat"], k["outcome"]))


def finding_key(round_id, seat, digest):
    """A finding's identity: the exact outcome, not just its round and seat, so
    a corrected or changed outcome is new evidence no earlier snapshot lists."""
    return {"round": round_id, "seat": seat, "outcome": digest}


def finding_evidence(rnd):
    """{(seat, outcome digest): first posting} of every distinct received
    findings outcome in a round."""
    return rnd["finding_posts"]


def examines(rnd, key, posted, head, base, target_ref, is_ancestor):
    """Whether `rnd` is a received examination of the finding `key`."""
    return (not rnd["conflict"] and same_frame(rnd, base, target_ref)
            and is_ancestor(rnd["open"]["head"], head) and rnd["order"] > posted
            and key in rnd["open"]["standing"]
            and any(o["status"] == "received" for o in rnd["seats"].values()))


def plan(resolved, rounds, host, is_ancestor):
    head, base, target_ref = resolved["head"], resolved["base"], resolved["target_ref"]
    order = list(SEATS) + ([host] if host not in SEATS else [])
    seats, covered = [], []
    for name in order:
        coverage, verdict = seat_state(rounds, name, head, base, target_ref, is_ancestor)
        entry = {"seat": name, "mechanism": "native" if name == host else "ask-agent",
                 "cli": SEATS.get(name, {}).get("cli"),
                 "model": SEATS.get(name, {}).get("model", "lead-default"),
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
    # Standing findings need a received examination: covered seats review
    # the dispositions instead of being carried as covered, and every prompt
    # in the round carries the standing findings (see unexamined_findings).
    standing = unexamined_findings(rounds, head, base, target_ref, is_ancestor)
    if standing:
        for c in covered:
            seats.append({"seat": c["seat"], "mechanism": "native" if c["seat"] == host else "ask-agent",
                          "cli": SEATS.get(c["seat"], {}).get("cli"),
                          "model": SEATS.get(c["seat"], {}).get("model", "lead-default"),
                          "scope": "disposition", "from": head, "continuity": "warm",
                          "fallback": {"scope": "full", "from": base, "continuity": "fresh"}})
        covered = []
    # With nothing to dispatch, a round is still needed when the latest round
    # at this head is void, has no outcome, or reports undispositioned findings:
    # the new round's outcome restates the disposition count.
    latest = latest_round_at_head(rounds, head, base, target_ref)
    outstanding = latest is not None and bool(
        latest["conflict"] or latest["outcome_at"] is None or latest["unresolved"]
        or standing)
    return {"seats": seats, "covered": covered, "standing_findings": standing,
            "open_round": bool(seats) or outstanding}


def invocation_notes(route, local_ahead):
    """local_ahead: the checkout has commits the frozen head does not."""
    notes = []
    if route == "legacy-formal":
        notes.append("legacy-formal-alias")
    if route == "branch-pr":
        notes.append("branch-routed-to-pr")
    if route != "pr" and local_ahead:
        notes.append("unpushed-local-commits")
    return notes


def arg_shape(text):
    """Normalize an invocation argument to a public shape; the text is dropped."""
    words = (text or "").split()
    if not words:
        return "none"
    if re.fullmatch(r"(?:PR\s*)?#?\d+", " ".join(words), re.I):
        return "pr-ref"
    if words == ["branch"]:
        return "branch"
    if words[0].lower() == "formal":
        rest = words[1:]
        if len(rest) == 1 and HEX_ABBREV.match(rest[0]):
            return "formal-sha"
        if len(rest) == 2 and all(HEX_ABBREV.match(w) for w in rest):
            return "formal-sha-base"
        return "formal-other"
    return "other"


def parse_invocation(raw):
    """Route a typed argument. None means an advisory target (exit 3)."""
    text = (raw or "").strip()
    words = text.split()
    match = re.fullmatch(r"(?:PR\s*)?#?(\d+)", text, re.I)
    if match:
        return {"route": "pr", "pr": int(match.group(1)), "sha": None, "base": None}
    if words == ["branch"]:
        return {"route": "branch-pr", "pr": None, "sha": None, "base": None}
    if words and words[0].lower() == "formal":
        rest = words[1:]
        if not rest:
            raise Refusal("formal-sha-missing", "the formal alias needs the pushed head SHA")
        if len(rest) <= 2 and all(HEX_ABBREV.match(w) for w in rest):
            return {"route": "legacy-formal", "pr": None, "sha": rest[0],
                    "base": rest[1] if len(rest) == 2 else None}
        raise Refusal("unrecognized-argument", "formal takes <pushed-sha> [base-sha]")
    # Only a PR-reference prefix ("PR", "PR #", "PR7", "#") is a malformed PR
    # argument; "PR.md" or "pr-notes.md" are files and stay advisory.
    if text.startswith("#") or (words and words[0].upper() == "PR") \
            or re.match(r"^PR[#\d]", text, re.I):
        raise Refusal("unrecognized-argument", "expected PR #<number>")
    return None  # worktree, staged, branch without PR, or a file: advisory


def check_legacy(resolved, sha, base, expand):
    """The alias names the PR's revisions or is refused; abbreviations expand."""
    if not sha:
        raise Refusal("formal-sha-missing", "the formal alias needs the pushed head SHA")
    if expand(sha) != resolved["head"]:
        raise Refusal("supplied-sha-mismatch",
                      f"supplied SHA {sha} is not the PR's pushed head {resolved['head']}")
    if base and expand(base) != resolved["base"]:
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
        "standing": [dict(f) for f in seat_plan["standing_findings"]],
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
        for key in ("scope", "from", "continuity", "model", "mechanism"):
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


def undisposed_seats(rnd):
    """Dispatched seats with neither a received nor an EMPTY outcome."""
    return [s["seat"] for s in rnd["open"]["seats"] if s["seat"] not in rnd["seats"]]


def clearance(resolved, rounds, is_ancestor, expect_head):
    """CLEAN only when the latest round at this head disposed of every seat.

    Each seat in that round must be explicit: a received outcome, an EMPTY
    outcome, or a `covered` entry whose earlier coverage still holds. A
    dispatched seat with no outcome is silence, and silence blocks. A void
    latest round blocks: an earlier round never stands in for it.
    """
    head, base, target_ref = resolved["head"], resolved["base"], resolved["target_ref"]
    reasons = []
    if expect_head != head:
        reasons.append(f"PR head is {head}, not the expected {expect_head}")
    latest = latest_round_at_head(rounds, head, base, target_ref)
    names = list(SEATS)
    for rnd in rounds:
        names.extend(n for n in sorted(rnd["named"]) if n not in names)
    seats = {}
    if latest is None:
        reasons.append("no round was opened at this head")
    elif latest["conflict"]:
        reasons.append(f"the latest round at this head ({latest['id']}) is void: "
                       f"{latest['conflict']}; run the council again")
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
                seats[name] = "empty"  # standing findings override this below
            else:
                coverage, verdict = seat_state(rounds, name, head, base, target_ref, is_ancestor)
                seats[name] = verdict if coverage == head else "unchained"
        for entry in latest["open"]["covered"]:
            name = entry["seat"]
            coverage, verdict = seat_state(rounds, name, head, base, target_ref, is_ancestor)
            seats[name] = "clean" if (coverage == head and verdict == "clean") else "unchained"
        if latest["outcome_at"] is None:
            reasons.append(f"round {latest['id']} has no outcome record")
        elif latest["unresolved"]:
            reasons.append(f"{latest['unresolved']} earlier findings not yet dispositioned")
    for name in names:
        if name not in seats:
            seats[name] = unlisted_status(rounds, name, head, base, target_ref, is_ancestor)
    unreadable = [r["unreadable"] for r in rounds if r.get("unreadable")]
    if unreadable:
        reasons.append("trusted round-record comments that cannot be read (their findings are "
                       f"unknown): {unreadable}; delete or repost them")
    for finding in unexamined_findings(rounds, head, base, target_ref, is_ancestor):
        seats[finding["seat"]] = "findings"  # one rule, whatever the seat's latest state
    findings = sorted(n for n, v in seats.items() if v == "findings")
    if findings:
        reasons.append("standing Critical/Important findings no seat has examined since, from: "
                       + ", ".join(findings) + " (run the council again)")
    unchained = [n for n, v in seats.items() if v == "unchained"]
    if unchained:
        reasons.append("seats whose reviews do not chain to full coverage of this head: "
                       + ", ".join(unchained))
    if not any(v == "clean" for v in seats.values()):
        reasons.append("no seat has a received clean review covering this head")
    return {"head": head, "base": base, "target_ref": target_ref, "clean": not reasons,
            "round": latest["id"] if latest else None, "seats": seats, "reasons": reasons,
            "limits": [f"{n}: {v}" for n, v in seats.items()
                       if v in ("empty", "missing", "stale", "unlisted")]}


def unlisted_status(rounds, name, head, base, target_ref, is_ancestor):
    """A seat the latest round did not name: never clean (standing findings
    override this in clearance)."""
    coverage, verdict = seat_state(rounds, name, head, base, target_ref, is_ancestor)
    if coverage == head:
        return "unlisted"
    return "stale" if coverage is not None else "missing"


def tally(open_rounds, since, limit=10):
    """open_rounds: [(repo, rnd)]. Count the first `limit` production rounds
    across PRs opened at or after `since` (the rollout's deploy time)."""
    seen, seen_events, rows = set(), set(), []
    for repo, rnd in sorted(open_rounds, key=lambda x: (x[1]["opened_at"], x[0], x[1]["id"])):
        if (repo, rnd["id"]) in seen or not rnd.get("outcome_at") or rnd["opened_at"] < since:
            continue  # a retry seen twice, an abandoned open-only round, or pre-rollout
        if rnd["open"]["invocation"]["cohort"] != "production":
            continue
        seen.add((repo, rnd["id"]))
        inv = rnd["open"]["invocation"]
        rows.append({"opened_at": rnd["opened_at"], "repo": repo, "pr": rnd["open"]["pr"],
                     "round_id": rnd["id"], "shape": inv["shape"], "route": inv["route"],
                     "notes": list(inv["notes"]),
                     # Two rounds planned concurrently may carry one refusal; count it once.
                     "mistakes": [c["reason"] for c in inv["corrections"]
                                  if c["id"] not in seen_events],
                     "unknown": len(inv["unknown"])})
        seen_events.update(c["id"] for c in inv["corrections"])
        if len(rows) == limit:
            break
    return {"rounds": len(rows), "window": limit,
            "rounds_with_mistakes": sum(1 for r in rows if r["mistakes"]),
            "mistakes": sum(len(r["mistakes"]) for r in rows),
            "alias_uses": sum(1 for r in rows if "legacy-formal-alias" in r["notes"]),
            # Rounds whose refusal capture was lost: their mistake count is a floor.
            "rounds_with_unknown_corrections": sum(1 for r in rows if r["unknown"]),
            "rows": rows}


def render(rec):
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
            lines.append(f"| {s['seat']} | {s['mechanism']} | {s['model']} | "
                         f"{s['scope']} {span} ({s['continuity']}) |")
        for c in rec["covered"]:
            lines.append(f"| {c['seat']} | — | — | covered through head (clean earlier) |")
        if rec["standing"]:
            lines.append("")
            lines.append("Standing findings this round examines: " + ", ".join(
                f"{f['seat']} in `{f['round']}`" for f in rec["standing"]) + ".")
    else:
        lines.append(f"**council-review-round v{VERSION}: round `{rec['round_id']}` outcomes**")
        lines.append("")
        lines.append(f"Head `{rec['head']}`; base `{rec['base']}`. "
                     f"Undispositioned earlier findings: {rec['unresolved_findings']}.")
        if rec["seats"]:
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
    lines += ["", "The block below is the authoritative round record. Do not edit it: "
              "an edited record is ignored. Post findings in a separate comment.", "",
              encode_block(rec), ""]
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


def git_expand(cwd):
    def expand(sha):
        proc = run(["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], cwd,
                   check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None
    return expand


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
        if pr is not None and "could not resolve to a pullrequest" in msg.lower():
            raise Refusal("pr-not-found", f"PR #{pr} does not exist here")
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
    head, target_ref = info["headRefOid"], info["baseRefName"]
    remote = find_remote(cwd, repo)
    refs = (f"refs/pull/{number}/head", f"refs/heads/{target_ref}")
    run(["git", "fetch", "--no-tags", "--quiet", remote, *refs], cwd)
    # The head is consistent only if the remote's PR ref still equals what gh
    # reported; locally cached objects would otherwise hide a moved PR. The
    # target tip comes from the remote itself: gh's baseRefOid is recorded at
    # the PR's last push and lags a target branch that has moved since.
    tips = {}
    for line in run(["git", "ls-remote", remote, *refs], cwd).stdout.splitlines():
        sha, _, ref = line.partition("\t")
        tips[ref.strip()] = sha.strip()
    if tips.get(refs[0]) != head:
        raise Refusal("pr-moved", "the PR head moved while resolving; run again")
    target_oid = target_tip(tips, refs[1], info.get("baseRefOid"))
    if not target_oid or not SHA_RE.match(target_oid):
        raise EnvError(f"target branch {target_ref} not found on the remote")
    for sha in (head, target_oid):
        if run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd, check=False).returncode:
            raise Refusal("head-not-fetchable", f"{sha} is not fetchable; run again")
    base = run(["git", "merge-base", head, target_oid], cwd).stdout.strip()
    local = run(["git", "rev-parse", "HEAD"], cwd, check=False)
    return {"repo": repo, "pr": number, "url": info["url"], "head": head,
            "head_ref": info["headRefName"], "target_ref": target_ref,
            "target_oid": target_oid, "base": base,
            "local_head": local.stdout.strip() if local.returncode == 0 else None}


def target_tip(tips, ref, reported):
    """The live remote tip of the target branch. `reported` (gh's baseRefOid,
    which lags a target that moved after the PR's last push) is deliberately
    ignored; it stays in the signature so the mutation check can restore the
    stale source and prove a fixture fails."""
    return tips.get(ref)


def fetch_comments(cwd, repo, pr):
    proc = run(["gh", "api", "--paginate", f"repos/{repo}/issues/{pr}/comments",
                "--jq", ".[]"], cwd)
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def rounds_for(cwd, repo, pr):
    usable, ignored = load_records(fetch_comments(cwd, repo, pr), repo, pr)
    rounds, orphans = assemble(usable, ignored)
    return rounds, ignored + orphans + [
        {"round": r["id"], "reason": r["conflict"]} for r in rounds
        if r["conflict"] and not r.get("orphan")]


# Refused invocations wait here (per checkout, inside the git directory) until
# a round record carries them. Each entry has a random id, so consuming it is
# exact and retry-safe. A file that cannot be read is moved aside, never
# discarded, and replaced by an `unknown` marker that the next round records:
# lost capture is reported as unknown, never as zero.

PENDING_VERSION = 1


def pending_path(cwd):
    path = run(["git", "rev-parse", "--git-path", PENDING_FILE], cwd).stdout.strip()
    return path if os.path.isabs(path) else os.path.join(cwd, path)


def _valid_pending(state):
    return (isinstance(state, dict) and set(state) == {"version", "unknown", "items"}
            and state["version"] == PENDING_VERSION
            and isinstance(state["unknown"], list)
            and all(isinstance(u, str) and EVENT_ID.match(u) for u in state["unknown"])
            and isinstance(state["items"], list)
            and all(isinstance(i, dict) and set(i) == {"id", "shape", "reason", "cohort"}
                    and valid_correction({k: i[k] for k in ("id", "shape", "reason")})
                    and i["cohort"] in COHORTS for i in state["items"]))


def read_pending(cwd):
    path = pending_path(cwd)
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
        if _valid_pending(state):
            return state
    except FileNotFoundError:
        return {"version": PENDING_VERSION, "unknown": [], "items": []}
    except (OSError, ValueError):
        pass
    # Unreadable or malformed: keep the bytes for inspection, record the loss.
    marker = secrets.token_hex(4)
    try:
        os.replace(path, f"{path}.unreadable-{marker}")
    except OSError as exc:
        raise EnvError(f"cannot set aside unreadable {path}: {exc}") from exc
    state = {"version": PENDING_VERSION, "unknown": [marker], "items": []}
    write_pending(cwd, state)
    return state


def write_pending(cwd, state):
    path = pending_path(cwd)
    if not state["unknown"] and not state["items"]:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = f"{path}.tmp-{secrets.token_hex(4)}"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(tmp, path)


@contextlib.contextmanager
def pending_lock(cwd):
    """Serialize read-modify-write of the pending file across sessions."""
    with open(pending_path(cwd) + ".lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def remember_refusal(cwd, raw, code, cohort):
    if code in CALLER_REFUSALS:
        with pending_lock(cwd):
            _remember(cwd, raw, code, cohort)


def _remember(cwd, raw, code, cohort):
    state = read_pending(cwd)
    state["items"].append({"id": secrets.token_hex(4), "shape": arg_shape(raw),
                           "reason": code, "cohort": cohort})
    write_pending(cwd, state)


def carried(cwd, cohort):
    """(corrections, unknown) the next `cohort` round records."""
    with pending_lock(cwd):
        state = read_pending(cwd)
    corrections = [{k: i[k] for k in ("id", "shape", "reason")}
                   for i in state["items"] if i["cohort"] == cohort]
    # Only a production round reports lost capture, so evaluation never hides it.
    return corrections, (list(state["unknown"]) if cohort == "production" else [])


def consume_pending(cwd, invocation):
    """Remove exactly the entries a posted open record carried, by id."""
    with pending_lock(cwd):
        state = read_pending(cwd)
        ids = {c["id"] for c in invocation["corrections"]}
        state["items"] = [i for i in state["items"] if i["id"] not in ids]
        state["unknown"] = [u for u in state["unknown"] if u not in invocation["unknown"]]
        write_pending(cwd, state)


# --------------------------------------------------------------------------
# Commands


def emit(obj):
    print(json.dumps(obj, indent=1, sort_keys=True))


def check_host(host, new_provider):
    if host in CLI_NAMES:
        raise EnvError(f"--host takes a provider, not a CLI name: {host!r} "
                       "(anthropic, openai or google)")
    if host not in SEATS and not (new_provider and SEAT_NAME.match(host)):
        raise EnvError(f"unknown provider {host!r}; pass --new-provider to add a fourth seat")


def cmd_plan(args):
    check_host(args.host, args.new_provider)
    cohort = "evaluation" if args.evaluation else "production"
    try:
        route = parse_invocation(args.raw)
        if route is None:
            print("advisory target: use the advisory workflow", file=sys.stderr)
            return 3
        resolved = resolve(args.repo_dir, route["pr"])
        if resolved is None:
            if route["route"] == "legacy-formal":
                raise Refusal("formal-without-pr",
                              "no open PR for this branch; a gate without a PR is declared by "
                              "its governing workflow, not by this alias")
            print("no open PR for the current branch: the review is advisory", file=sys.stderr)
            return 3
        if route["route"] == "legacy-formal":
            check_legacy(resolved, route["sha"], route["base"], git_expand(args.repo_dir))
    except Refusal as exc:
        try:
            remember_refusal(args.repo_dir, args.raw, exc.code, cohort)
        except (EnvError, OSError) as err:
            print(f"measurement: this refusal could not be recorded ({err}); "
                  "it is unknown to the tally", file=sys.stderr)
        raise
    rounds, ignored = rounds_for(args.repo_dir, resolved["repo"], resolved["pr"])
    seat_plan = plan(resolved, rounds, args.host, git_is_ancestor(args.repo_dir))
    is_ancestor = git_is_ancestor(args.repo_dir)
    local = resolved["local_head"]
    invocation = {
        "shape": arg_shape(args.raw), "route": route["route"],
        "notes": invocation_notes(route["route"], bool(local) and not is_ancestor(local, resolved["head"])),
        "cohort": cohort,
    }
    invocation["corrections"], invocation["unknown"] = carried(args.repo_dir, cohort)
    out = {"resolved": resolved, "plan": seat_plan, "ignored": ignored,
           "previous_rounds": [{"id": r["id"], "head": r["open"]["head"],
                                "void": bool(r["conflict"])} for r in rounds]}
    if seat_plan["open_round"]:
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
    why = validate(opened, opened.get("repo"), opened.get("pr"))
    if why or opened.get("phase") != "open":
        raise EnvError(f"not a valid open record: {why or 'wrong phase'}")
    if args.outcomes:
        if args.unresolved is None:
            raise EnvError("--unresolved is required with --outcomes")
        rec = outcome_record(opened, _load_json(args.outcomes), args.unresolved)
    else:
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
    posted = False
    for comment in fetch_comments(args.repo_dir, rec["repo"], rec["pr"]):
        existing, _ = extract(comment.get("body") or "")
        if existing is not None and not trust_reason(comment) and canonical(existing) == canonical(rec):
            print(f"already posted as comment {comment.get('id')}; not posting again")
            posted = True
            break
    if not posted:
        run(["gh", "pr", "comment", str(rec["pr"]), "--repo", rec["repo"],
             "--body-file", args.body_file], args.repo_dir)
        print("posted")
    if rec["phase"] == "open":
        consume_pending(args.repo_dir, rec["invocation"])
    return 0


def cmd_check(args):
    number = None
    if args.pr:
        route = parse_invocation(args.pr)
        if not route or route["route"] != "pr":
            raise EnvError(f"check takes a PR reference, got {args.pr!r}")
        number = route["pr"]
    resolved = resolve(args.repo_dir, number)
    if resolved is None:
        print("no open PR for the current branch", file=sys.stderr)
        return 3
    rounds, ignored = rounds_for(args.repo_dir, resolved["repo"], resolved["pr"])
    result = clearance(resolved, rounds, git_is_ancestor(args.repo_dir), args.expect_head)
    result["ignored"] = ignored
    emit(result)
    return 0 if result["clean"] else 1


def cmd_tally(args):
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", args.since):
        raise EnvError("--since must be UTC as YYYY-MM-DDTHH:MM:SSZ, like GitHub timestamps")
    collected = []
    for ref in args.prs:
        match = re.fullmatch(r"([^/\s]+/[^#\s]+)#(\d+)", ref)
        if not match:
            raise EnvError(f"expected OWNER/REPO#N, got {ref!r}")
        repo, pr = match.group(1), int(match.group(2))
        rounds, _ = rounds_for(args.repo_dir, repo, pr)
        collected.extend((repo, r) for r in rounds)
    emit(tally(collected, args.since, args.window))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-dir", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="route the argument, read round records, plan each seat")
    p.add_argument("--raw", required=True,
                   help="the council-review argument exactly as typed; only its shape is recorded")
    p.add_argument("--host", required=True, help="the host's own provider: anthropic, openai, google")
    p.add_argument("--new-provider", action="store_true",
                   help="allow --host to name a fourth provider")
    p.add_argument("--evaluation", action="store_true",
                   help="acceptance replays and dogfooding only: excluded from measurement")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("render", help="render an open or outcome record comment")
    p.add_argument("--open-record", required=True)
    p.add_argument("--outcomes")
    p.add_argument("--unresolved", type=int, help="earlier findings not yet dispositioned")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("post", help="post a record comment unless already present")
    p.add_argument("--body-file", required=True)
    p.set_defaults(func=cmd_post)

    p = sub.add_parser("check", help="recheck the live PR and report clearance")
    p.add_argument("pr", nargs="?")
    p.add_argument("--expect-head", required=True, help="the full SHA you intend to merge")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("tally", help="the invocation-mistake measurement window")
    p.add_argument("prs", nargs="+", metavar="OWNER/REPO#N")
    p.add_argument("--since", required=True,
                   help="the rollout's deploy time, ISO 8601 UTC (e.g. 2026-11-04T00:00:00Z)")
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
