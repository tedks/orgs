#!/usr/bin/env python3
"""Scenario fixtures for council_pr.py.

Each test replays a PR history (pushes, force-pushes, retargets, retries,
late reviewers, hostile or broken comments) and asserts the review plan or
clearance verdict that council-review would act on. The end-to-end tests run
the real command line against a temporary git repository and a fake `gh`.
Nothing here contacts GitHub, so no fixture run can enter the ten-council
measurement window.

    PYTHONDONTWRITEBYTECODE=1 python3 test_council_pr.py
    PYTHONDONTWRITEBYTECODE=1 python3 test_council_pr.py --mutation-check
"""

import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import council_pr as cp  # noqa: E402

REPO, PR = "o/r", 7
B, B2, T = "b" * 40, "c" * 40, "e" * 40
H1, H2, H3, HX = "1" * 40, "2" * 40, "3" * 40, "9" * 40  # HX: force-pushed rewrite
PARENTS = {H1: B, H2: H1, H3: H2, HX: B, B: B2, B2: None}


def is_ancestor(a, b):
    while b is not None:
        if a == b:
            return True
        b = PARENTS.get(b)
    return False


def resolved(head=H2, base=B, target_ref="master"):
    return {"repo": REPO, "pr": PR, "head": head, "base": base,
            "target_ref": target_ref, "target_oid": T, "local_head": head}


def rid(name, head):
    """A valid round id (bound to its head) derived from a short fixture name."""
    return f"{head[:12]}-20261103T100000Z-{name.encode().hex()[:6].ljust(6, '0')}"


def corr(event, reason="supplied-sha-mismatch", shape="formal-sha"):
    return {"id": event, "shape": shape, "reason": reason}


def seat(name, scope, start, continuity=None, **extra):
    continuity = continuity or ("fresh" if scope == "full" else "warm")
    return {"seat": name, "mechanism": "native" if name == "anthropic" else "ask-agent",
            "model": cp.SEATS.get(name, {}).get("model", "lead-default"), "scope": scope, "from": start,
            "continuity": continuity, **extra}


def opened(name, head, seats, base=B, target_ref="master", shape="pr-ref", route="pr",
           notes=(), corrections=(), pr=PR, covered=(), cohort="production", standing=()):
    return {"schema": cp.SCHEMA, "version": 1, "phase": "open", "repo": REPO, "pr": pr,
            "round_id": rid(name, head), "head": head, "base": base, "target_ref": target_ref,
            "target_oid": T, "invocation": {"shape": shape, "route": route, "notes": list(notes),
                                            "corrections": list(corrections), "unknown": [],
                                            "cohort": cohort},
            "covered": [{"seat": c, "through": head} for c in covered],
            "standing": [{"round": rid(r, h), "seat": n} for r, h, n in standing],
            "seats": [dict(s, status="dispatched") for s in seats]}


def received(s, critical=0, important=0, nit=0):
    return dict(s, status="received", counts={"critical": critical, "important": important,
                                              "nit": nit},
                verdict="findings" if critical + important else "clean")


def empty(s, reason="usage-limit"):
    return dict(s, status="empty", reason=reason)


def outcome(open_rec, seats, unresolved=0):
    rec = {k: open_rec[k] for k in ("schema", "version", "repo", "pr", "round_id", "head",
                                     "base", "target_ref", "target_oid")}
    rec.update(phase="outcome", seats=seats, unresolved_findings=unresolved)
    return rec


def as_record(block):
    """A comment body as `render` would start it: the header, then `block`."""
    return "**council-review-round v1: round `x` outcomes**\n\n" + block


class History:
    """Comments in posting order, with GitHub-style metadata."""

    def __init__(self):
        self.comments = []

    def post(self, rec, assoc="OWNER", edited=False, body=None, snapshot=True):
        """Post a record. An open record gets the plan's standing snapshot at
        this moment, as the runner's would, unless snapshot=False (a
        hand-trimmed record)."""
        if rec is not None and rec.get("phase") == "open" and snapshot and not rec["standing"]:
            res = resolved(head=rec["head"], base=rec["base"], target_ref=rec["target_ref"])
            rec["standing"] = cp.plan(res, self.rounds()[0], "anthropic", is_ancestor)["standing_findings"]
        n = len(self.comments)
        at = f"2026-11-03T10:{n // 60:02d}:{n % 60:02d}Z"
        self.comments.append({"id": 1000 + n, "author_association": assoc, "created_at": at,
                              "updated_at": "2026-11-04T00:00:00Z" if edited else at,
                              "body": body if body is not None else cp.render(rec)})
        return rec

    def rounds(self, repo=REPO, pr=PR):
        usable, ignored = cp.load_records(self.comments, repo, pr)
        rounds, orphans = cp.assemble(usable, ignored)
        return rounds, ignored + orphans

    def plan(self, res, host="anthropic"):
        rounds, _ = self.rounds()
        got = cp.plan(res, rounds, host, is_ancestor)
        return {s["seat"]: s for s in got["seats"]}, got["covered"]

    def open_round(self, res, host="anthropic"):
        return cp.plan(res, self.rounds()[0], host, is_ancestor)["open_round"]

    def clearance(self, res, expect=None):
        return cp.clearance(res, self.rounds()[0], is_ancestor, expect or res["head"])


def pairs(standing):
    """The {round, seat} part of standing findings (the digest is opaque)."""
    return [{"round": f["round"], "seat": f["seat"]} for f in standing]


def rounds_open(h, index):
    return h.rounds()[0][index]["open"]


def full(name):
    return seat(name, "full", B)


def first_round(h, results=None):
    """Round 1 at H1. results: seat -> ('clean'|'findings'|'empty')."""
    results = results or {"anthropic": "clean", "openai": "clean", "google": "clean"}
    o = h.post(opened("r1", H1, [full(n) for n in results]))
    seats = []
    for name, res in results.items():
        if res == "empty":
            seats.append(empty(full(name)))
        else:
            seats.append(received(full(name), important=1 if res == "findings" else 0))
    h.post(outcome(o, seats, unresolved=0))
    return o


class Planning(unittest.TestCase):
    def test_first_round_reviews_everything_in_full(self):
        seats, covered = History().plan(resolved(head=H1))
        self.assertEqual(set(seats), {"anthropic", "openai", "google"})
        for s in seats.values():
            self.assertEqual((s["scope"], s["from"], s["continuity"]), ("full", B, "fresh"))
        self.assertEqual(seats["anthropic"]["mechanism"], "native")
        self.assertEqual(seats["openai"]["mechanism"], "ask-agent")
        self.assertEqual(seats["openai"]["model"], "gpt-6-sol")
        self.assertEqual(covered, [])

    def test_codex_host_owns_the_openai_seat(self):
        seats, _ = History().plan(resolved(head=H1), host="openai")
        self.assertEqual(seats["openai"]["mechanism"], "native")
        self.assertEqual(seats["anthropic"]["mechanism"], "ask-agent")

    def test_fourth_provider_host_adds_a_seat(self):
        seats, _ = History().plan(resolved(head=H1), host="mistral")
        self.assertEqual(len(seats), 4)
        self.assertEqual(seats["mistral"]["mechanism"], "native")

    def test_fix_push_gives_warm_seats_their_delta_and_empty_seat_full(self):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "empty"})
        seats, _ = h.plan(resolved(head=H2))
        self.assertEqual((seats["anthropic"]["scope"], seats["anthropic"]["from"]), ("delta", H1))
        self.assertEqual(seats["anthropic"]["continuity"], "warm")
        self.assertEqual(seats["anthropic"]["fallback"]["from"], B)
        self.assertEqual((seats["openai"]["scope"], seats["openai"]["from"]), ("delta", H1))
        self.assertEqual((seats["google"]["scope"], seats["google"]["from"]), ("full", B))

    def test_each_seat_gets_its_own_last_reviewed_delta(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1), seat("openai", "delta", H1),
                                      seat("google", "delta", H1)]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1)),
                            empty(seat("openai", "delta", H1)),
                            received(seat("google", "delta", H1))]))
        seats, _ = h.plan(resolved(head=H3))
        self.assertEqual(seats["anthropic"]["from"], H2)
        self.assertEqual(seats["openai"]["from"], H1)  # its EMPTY round covered nothing
        self.assertEqual(seats["google"]["from"], H2)

    def test_force_push_resets_every_seat_to_full(self):
        h = History()
        first_round(h)
        seats, _ = h.plan(resolved(head=HX))
        self.assertTrue(all(s["scope"] == "full" and s["from"] == B for s in seats.values()))

    def test_changed_merge_base_resets_every_seat_to_full(self):
        h = History()
        first_round(h)
        seats, _ = h.plan(resolved(head=H2, base=B2))
        self.assertTrue(all(s["scope"] == "full" and s["from"] == B2 for s in seats.values()))

    def test_retargeted_pr_resets_every_seat_to_full(self):
        h = History()
        first_round(h)
        seats, _ = h.plan(resolved(head=H2, target_ref="release"))
        self.assertTrue(all(s["scope"] == "full" for s in seats.values()))

    def test_same_head_reinvocation_dispatches_only_what_is_open(self):
        h = History()
        first_round(h, {"anthropic": "clean", "openai": "findings", "google": "empty"})
        seats, covered = h.plan(resolved(head=H1))
        # openai's finding stands, so the clean seat examines its disposition
        # instead of being carried as covered.
        self.assertEqual(covered, [])
        self.assertEqual(seats["anthropic"]["scope"], "disposition")
        self.assertEqual((seats["openai"]["scope"], seats["openai"]["from"]), ("disposition", H1))
        self.assertEqual(seats["openai"]["fallback"]["scope"], "full")
        self.assertEqual(seats["google"]["scope"], "full")

    def test_disposition_round_clears_a_seat_at_the_same_head(self):
        h = History()
        first_round(h, {"anthropic": "clean", "openai": "findings", "google": "clean"})
        o2 = h.post(opened("r2", H1, [seat("openai", "disposition", H1)],
                           covered=("anthropic", "google")))
        h.post(outcome(o2, [received(seat("openai", "disposition", H1))]))
        result = h.clearance(resolved(head=H1))
        self.assertTrue(result["clean"], result["reasons"])
        self.assertEqual(result["seats"], {"anthropic": "clean", "openai": "clean",
                                           "google": "clean"})

    def test_warm_failure_fallback_to_full_counts(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1)]))
        h.post(outcome(o2, [received(full("anthropic"))]))  # restarted, given everything
        rounds, ignored = h.rounds()
        self.assertIsNone(rounds[1]["conflict"])
        self.assertEqual(cp.seat_state(rounds, "anthropic", H2, B, "master", is_ancestor)[0], H2)

    def test_delta_that_does_not_start_at_coverage_breaks_the_chain(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H3, [seat("anthropic", "delta", H2)]))  # skipped H1..H2
        h.post(outcome(o2, [received(seat("anthropic", "delta", H2))]))
        seats, _ = h.plan(resolved(head=H3))
        self.assertEqual(seats["anthropic"]["scope"], "full")


class RestartedReviewer(unittest.TestCase):
    def test_fresh_reviewer_cannot_record_a_delta(self):
        o = opened("r2", H2, [seat("anthropic", "delta", H1)])
        with self.assertRaises(cp.EnvError):
            cp.outcome_record(o, [{"seat": "anthropic", "status": "received", "continuity": "fresh",
                                   "counts": {"critical": 0, "important": 0, "nit": 0},
                                   "verdict": "clean"}], 0)

    def test_injected_fresh_delta_record_is_ignored(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1)]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1, "fresh"))]))
        rounds, ignored = h.rounds()
        self.assertIn("requires a warm seat", " ".join(i["reason"] for i in ignored))
        self.assertFalse(h.clearance(resolved(head=H2))["clean"])

    def test_outcome_claiming_a_different_delta_conflicts(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H3, [seat("anthropic", "delta", H2)]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1))]))
        rounds, _ = h.rounds()
        self.assertIn("differs from its dispatch", rounds[1]["conflict"])


class HostileAndBrokenRecords(unittest.TestCase):
    def assert_ignored(self, why, **post):
        h = History()
        o = opened("r1", H1, [full("anthropic")])
        h.post(o, **post)
        h.post(outcome(o, [received(full("anthropic"))]))
        rounds, ignored = h.rounds()
        self.assertIn(why, " ".join(i["reason"] for i in ignored))
        seats, _ = h.plan(resolved(head=H1))
        self.assertEqual(seats["anthropic"]["scope"], "full")

    def test_comment_from_non_collaborator_is_ignored(self):
        self.assert_ignored("untrusted author", assoc="NONE")

    def test_contributor_comment_is_ignored(self):
        self.assert_ignored("untrusted author", assoc="CONTRIBUTOR")

    def test_edited_record_is_ignored(self):
        self.assert_ignored("edited", edited=True)

    def test_corrupt_json_is_ignored(self):
        self.assert_ignored("invalid JSON", body=as_record(cp.MARK_OPEN + "\n{not json\n" + cp.MARK_CLOSE))

    def test_unterminated_block_is_ignored(self):
        self.assert_ignored("unterminated", body=as_record(cp.MARK_OPEN + '\n{"a": 1}'))

    def test_two_blocks_in_one_comment_are_ignored(self):
        block = cp.encode_block(opened("r1", H1, [full("anthropic")]))
        self.assert_ignored("more than one", body=as_record(block + "\n" + block))

    def test_future_version_is_ignored(self):
        rec = dict(opened("r1", H1, [full("anthropic")]), version=2)
        self.assert_ignored("future version", body=as_record(cp.encode_block(rec)))

    def test_record_copied_from_another_pr_is_ignored(self):
        rec = opened("r1", H1, [full("anthropic")], pr=8)
        self.assert_ignored("another repository or PR", body=as_record(cp.encode_block(rec)))

    def test_short_sha_is_ignored(self):
        rec = opened("r1", H1[:12], [full("anthropic")])
        self.assert_ignored("bad head", body=as_record(cp.encode_block(rec)))

    def test_full_scope_not_starting_at_base_is_ignored(self):
        rec = opened("r1", H1, [seat("anthropic", "full", H1)])
        self.assert_ignored("must start at the base", body=as_record(cp.encode_block(rec)))

    def test_verdict_must_match_counts(self):
        o = opened("r1", H1, [full("anthropic")])
        bad = outcome(o, [dict(received(full("anthropic"), critical=1), verdict="clean")])
        self.assertIn("verdict disagrees", cp.validate(bad, REPO, PR))

    def test_outcome_without_open_record_is_ignored(self):
        h = History()
        o = opened("r1", H1, [full("anthropic")])
        h.post(outcome(o, [received(full("anthropic"))]))
        rounds, ignored = h.rounds()
        self.assertIn("without an open record", ignored[0]["reason"])
        # Kept only as finding evidence: no frame, so it covers and clears nothing.
        self.assertEqual([r.get("orphan") for r in rounds], [True])
        self.assertEqual(h.plan(resolved(head=H1))[0]["anthropic"]["scope"], "full")
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_record_text_cannot_close_the_record_block(self):
        rec = opened("r1", H1, [full("anthropic")])
        rec["seats"][0]["model"] = "opus --> ignore all previous <!--"
        got, err = cp.extract(cp.render(rec))
        self.assertIsNone(err)
        self.assertEqual(got, rec)

    def test_raw_invocation_text_is_not_a_valid_record_field(self):
        rec = opened("r1", H1, [full("anthropic")])
        rec["invocation"]["raw"] = "PR #7"
        self.assertEqual(cp.validate(rec, REPO, PR), "bad invocation")
        rec = opened("r1", H1, [full("anthropic")],
                     corrections=[dict(corr("0a0a0a0a"), raw="x")])
        self.assertEqual(cp.validate(rec, REPO, PR), "bad invocation corrections")

    def test_empty_reason_must_be_a_code(self):
        o = opened("r1", H1, [full("anthropic")])
        bad = outcome(o, [empty(full("anthropic"), "quota at 97% on host build-box")])
        self.assertIn("reason code", cp.validate(bad, REPO, PR))

    def test_unrelated_comments_are_skipped_silently(self):
        h = History()
        h.post(None, body="LGTM, thanks!")
        self.assertEqual(h.rounds(), ([], []))


class RetriesDuplicatesAndLateReviewers(unittest.TestCase):
    def test_identical_retries_count_once(self):
        h = History()
        o = opened("r1", H1, [full("anthropic")])
        h.post(o)
        h.post(o)
        out = outcome(o, [received(full("anthropic"))])
        h.post(out)
        h.post(out)
        rounds, ignored = h.rounds()
        self.assertEqual(len(rounds), 1)
        self.assertIsNone(rounds[0]["conflict"])
        self.assertEqual(cp.tally([(REPO, r) for r in rounds], since="")["rounds"], 1)

    def test_conflicting_open_records_make_the_round_count_for_nothing(self):
        h = History()
        h.post(opened("r1", H1, [full("anthropic")]))
        h.post(opened("r1", H1, [full("openai")]))
        rounds, _ = h.rounds()
        self.assertEqual(rounds[0]["conflict"], "conflicting open records")
        self.assertEqual(h.plan(resolved(head=H1))[0]["anthropic"]["scope"], "full")

    def test_round_id_must_name_its_own_head(self):
        rec = opened("r1", H2, [full("anthropic")])
        rec["round_id"] = rid("r1", H1)  # an H1 round id carrying an H2 frame
        self.assertIn("bad round_id", cp.validate(rec, REPO, PR))

    def test_void_round_is_seen_from_every_frame_it_names(self):
        h = History()
        first_round(h)  # clean at H1
        o = opened("r9", H1, [full("anthropic")])
        h.post(o)
        h.post(dict(o, seats=[dict(full("openai"), status="dispatched")]))  # conflicting open
        rounds, _ = h.rounds()
        rnd = rounds[-1]
        rnd["frames"][(H2, B, "master")] = rnd["order"]  # as if one open had named another head
        self.assertIs(cp.latest_round_at_head(rounds, H2, B, "master"), rnd)

    def test_conflicting_outcomes_for_a_seat_void_the_round(self):
        h = History()
        o = h.post(opened("r1", H1, [full("anthropic")]))
        h.post(outcome(o, [received(full("anthropic"))]))
        h.post(outcome(o, [received(full("anthropic"), critical=2)]))
        rounds, _ = h.rounds()
        self.assertIn("conflicting outcomes", rounds[0]["conflict"])
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_late_reviewer_belongs_to_its_own_frozen_round(self):
        h = History()
        o1 = first_round(h, {"anthropic": "findings", "openai": "clean", "google": "empty"})
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1), seat("openai", "delta", H1),
                                      full("google")]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1)),
                            received(seat("openai", "delta", H1)),
                            empty(full("google"), "timeout")]))
        h.post(outcome(o1, [received(full("google"))]))  # round 1's google answers late
        rounds, _ = h.rounds()
        self.assertEqual(rounds[0]["seats"]["google"]["status"], "received")
        # Attributed to H1, so it covers H1 only: google needs H1..H2 next.
        seats, _ = h.plan(resolved(head=H2))
        self.assertEqual((seats["google"]["scope"], seats["google"]["from"]), ("delta", H1))
        result = h.clearance(resolved(head=H2))
        self.assertEqual(result["seats"]["google"], "empty")  # EMPTY in the round at H2
        self.assertTrue(result["clean"], result["reasons"])
        self.assertIn("google: empty", result["limits"])


class Clearance(unittest.TestCase):
    def converged(self, google="clean", unresolved=0):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": google})
        g = seat("google", "delta", H1) if google != "empty" else full("google")
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1), seat("openai", "delta", H1), g]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1)),
                            received(seat("openai", "delta", H1)),
                            empty(g) if google == "empty" else received(g)], unresolved))
        return h

    def test_clean_when_every_present_seat_covers_head(self):
        result = self.converged().clearance(resolved(head=H2), expect=H2)
        self.assertTrue(result["clean"], result["reasons"])
        self.assertEqual(result["limits"], [])

    def test_empty_seat_is_listed_never_clean(self):
        result = self.converged(google="empty").clearance(resolved(head=H2))
        self.assertTrue(result["clean"])
        self.assertEqual(result["seats"]["google"], "empty")
        self.assertIn("google: empty", result["limits"])

    def test_dispatched_seat_without_outcome_blocks(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H2, [seat(n, "delta", H1) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1))]))  # the others: silence
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["openai"], "no-outcome")
        # Recording the silent seats EMPTY makes the round complete.
        h.post(outcome(o2, [empty(seat("openai", "delta", H1), "timeout"),
                            empty(seat("google", "delta", H1), "abandoned")]))
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])

    def test_open_round_with_no_outcome_record_blocks(self):
        h = History()
        first_round(h)
        h.post(opened("r2", H1, [seat("openai", "disposition", H1)], covered=("anthropic", "google")))
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_covered_seat_must_really_be_covered(self):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        # A hand-made open record claims anthropic is covered clean; its record says findings.
        o2 = h.post(opened("r2", H1, [seat("openai", "disposition", H1)],
                           covered=("anthropic", "google")))
        h.post(outcome(o2, [received(seat("openai", "disposition", H1))]))
        result = h.clearance(resolved(head=H1))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["anthropic"], "unchained")

    def test_seat_absent_from_latest_round_is_not_clean(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H1, [seat("openai", "disposition", H1)]))  # omits the others
        h.post(outcome(o2, [received(seat("openai", "disposition", H1))]))
        result = h.clearance(resolved(head=H1))
        self.assertEqual(result["seats"]["anthropic"], "unlisted")
        self.assertIn("anthropic: unlisted", result["limits"])

    def test_moved_head_refuses_clearance(self):
        result = self.converged().clearance(resolved(head=H3), expect=H2)
        self.assertFalse(result["clean"])
        self.assertTrue(any("not the expected" in r for r in result["reasons"]))
        self.assertTrue(any("no seat" in r for r in result["reasons"]))

    def test_expected_head_differs_from_live_head(self):
        result = self.converged().clearance(resolved(head=H2), expect=H1)
        self.assertFalse(result["clean"])

    def test_undispositioned_findings_block(self):
        result = self.converged(unresolved=2).clearance(resolved(head=H2))
        self.assertFalse(result["clean"])

    def test_open_findings_at_head_block(self):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_no_present_seat_is_never_clean(self):
        h = History()
        first_round(h, {"anthropic": "empty", "openai": "empty", "google": "empty"})
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_force_push_after_clean_voids_clearance(self):
        result = self.converged().clearance(resolved(head=HX))
        self.assertFalse(result["clean"])


class RoundOneRegressions(unittest.TestCase):
    """Scenarios from the first formal council and acceptance audit."""

    def test_conflicted_latest_round_does_not_resurrect_older_clearance(self):
        h = History()
        first_round(h)  # r1 at H1: all three clean
        o2 = h.post(opened("r2", H1, [full(n) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [received(full(n)) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [received(full("anthropic"), important=1)]))  # differing retry
        result = h.clearance(resolved(head=H1))
        self.assertFalse(result["clean"])
        self.assertTrue(any("void" in r for r in result["reasons"]), result["reasons"])
        # Planning does not quietly cover the seats the void round named.
        seats, covered = h.plan(resolved(head=H1))
        self.assertEqual(covered, [])
        self.assertEqual({s["scope"] for s in seats.values()}, {"full"})

    def test_void_round_resets_only_the_seats_it_named(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H1, [seat("openai", "disposition", H1)]))
        h.post(outcome(o2, [received(seat("openai", "disposition", H1))]))
        h.post(outcome(o2, [received(seat("openai", "disposition", H1), critical=1)]))
        seats, covered = h.plan(resolved(head=H1))
        self.assertEqual(seats["openai"]["scope"], "full")  # its coverage was voided
        # The void round's Critical is still evidence: it stands, so the seats
        # the void did not touch are dispatched to examine it, not carried.
        self.assertEqual(covered, [])
        self.assertEqual({seats["anthropic"]["scope"], seats["google"]["scope"]}, {"disposition"})
        self.assertTrue(h.open_round(resolved(head=H1)))

    def test_delta_across_a_force_push_is_not_coverage(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", HX, [seat(n, "delta", H1) for n in ("anthropic", "openai")]))
        h.post(outcome(o2, [received(seat(n, "delta", H1)) for n in ("anthropic", "openai")]))
        result = h.clearance(resolved(head=HX))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["anthropic"], "unchained")

    def test_late_record_cannot_lower_the_unresolved_count(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1), full("google")]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1)), empty(full("google"))], 3))
        h.post(outcome(o2, [received(full("google"))], 0))  # google answers late
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertTrue(any("not yet dispositioned" in r for r in result["reasons"]))

    def test_outstanding_count_opens_a_disposition_only_round(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H2, [seat(n, "delta", H1) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [received(seat(n, "delta", H1)) for n in ("anthropic", "openai", "google")], 2))
        self.assertTrue(h.open_round(resolved(head=H2)))
        o3 = h.post(opened("r3", H2, [], covered=("anthropic", "openai", "google")))
        h.post(outcome(o3, [], 0))
        result = h.clearance(resolved(head=H2))
        self.assertTrue(result["clean"], result["reasons"])
        self.assertFalse(h.open_round(resolved(head=H2)))  # nothing left: no new round

    def test_findings_from_a_seat_the_latest_round_omitted_still_block(self):
        """Round-1 I1 originally had a present seat receive in round 2; under the
        standing-findings rule that round examines mistral's finding (its
        snapshot lists it), so the blocking case is now a round with no received
        review. The guard is not weaker: an unexamined finding still blocks."""
        h = History()
        o1 = h.post(opened("r1", H1, [full("anthropic"), full("mistral")]))
        h.post(outcome(o1, [received(full("anthropic")), received(full("mistral"), important=1)]))
        # An Anthropic host reruns: mistral is neither dispatched nor covered,
        # and the seat that was dispatched never answered.
        o2 = h.post(opened("r2", H1, [full("openai")], covered=("anthropic",)))
        h.post(outcome(o2, [empty(full("openai"), "timeout")]))
        result = h.clearance(resolved(head=H1))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["mistral"], "findings")
        standing = cp.plan(resolved(head=H1), h.rounds()[0], "anthropic", is_ancestor)["standing_findings"]
        self.assertEqual(pairs(standing), [{"round": rid("r1", H1), "seat": "mistral"}])

    def test_clean_seat_omitted_from_latest_round_is_a_limit_not_clean(self):
        h = History()
        first_round(h)
        o2 = h.post(opened("r2", H1, [full("openai")], covered=("anthropic",)))
        h.post(outcome(o2, [received(full("openai"))]))
        result = h.clearance(resolved(head=H1))
        self.assertEqual(result["seats"]["google"], "unlisted")
        self.assertIn("google: unlisted", result["limits"])

    def test_unknown_fields_never_reach_a_valid_record(self):
        rec = opened("r1", H1, [full("anthropic")])
        self.assertIsNone(cp.validate(rec, REPO, PR))
        for mutate in (lambda r: r.update(raw="pasted text"),
                       lambda r: r["seats"][0].update(note="private"),
                       lambda r: r["seats"][0].update(model="/home/u/secret notes"),
                       lambda r: r["seats"][0].update(mechanism="by hand"),
                       lambda r: r.update(round_id="r1 free text")):
            bad = json.loads(json.dumps(rec))
            mutate(bad)
            self.assertIsNotNone(cp.validate(bad, REPO, PR))

    def test_host_must_be_a_provider_not_a_cli(self):
        for host in ("claude", "codex", "agy"):
            with self.assertRaises(cp.EnvError):
                cp.check_host(host, False)
        with self.assertRaises(cp.EnvError):
            cp.check_host("mistral", False)
        cp.check_host("mistral", True)
        cp.check_host("anthropic", False)

    def test_open_record_must_name_some_seat(self):
        self.assertIn("at least one seat", cp.validate(opened("r1", H1, []), REPO, PR))


class RoundTwoRegressions(unittest.TestCase):
    """Scenarios from the second council round and acceptance audits."""

    def test_late_findings_in_an_earlier_round_block_a_newer_clean_round(self):
        h = History()
        o1 = first_round(h, {"anthropic": "clean", "openai": "clean", "google": "empty"})
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1), seat("openai", "delta", H1),
                                      full("google")]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1)),
                            received(seat("openai", "delta", H1)), empty(full("google"))]))
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])
        h.post(outcome(o1, [received(full("google"), important=1)]))  # google, late, with findings
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertTrue(any("standing" in r for r in result["reasons"]), result["reasons"])
        self.assertTrue(h.open_round(resolved(head=H2)))

    def test_finder_gone_empty_at_the_same_head_still_blocks(self):
        h = History()
        o1 = h.post(opened("a", H2, [full("anthropic"), full("openai")]))
        h.post(outcome(o1, [received(full("anthropic"), critical=1), received(full("openai"))]))
        o2 = h.post(opened("b", H2, [seat("anthropic", "disposition", H2)], covered=("openai",)))
        h.post(outcome(o2, [empty(seat("anthropic", "disposition", H2), "timeout")], 0))
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["anthropic"], "findings")

    def test_finder_gone_empty_after_a_fix_push_is_a_limit(self):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        # Even an empty "fix" push keeps the finding standing: the plan lists it
        # so every prompt in the next round makes the present seats judge it.
        standing = cp.plan(resolved(head=H2), h.rounds()[0], "anthropic", is_ancestor)["standing_findings"]
        self.assertEqual(pairs(standing), [{"round": rid("r1", H1), "seat": "anthropic"}])
        o2 = h.post(opened("b", H2, [seat(n, "delta", H1) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [empty(seat("anthropic", "delta", H1), "timeout"),
                            received(seat("openai", "delta", H1)), received(seat("google", "delta", H1))]))
        result = h.clearance(resolved(head=H2))  # present seats examined the fix in their delta
        self.assertTrue(result["clean"], result["reasons"])
        self.assertIn("anthropic: empty", result["limits"])

    def test_present_seat_disposition_review_clears_an_empty_finder_without_a_push(self):
        h = History()
        o1 = h.post(opened("a", H2, [full("anthropic"), full("openai")]))
        h.post(outcome(o1, [received(full("anthropic"), important=1), received(full("openai"))], 0))
        # The lead rejects the finding with evidence; the finder is now out of quota.
        seats, covered = h.plan(resolved(head=H2))
        self.assertEqual(seats["openai"]["scope"], "disposition")  # dispatched, not carried
        self.assertEqual(covered, [])
        o2 = h.post(opened("b", H2, [seat("anthropic", "disposition", H2),
                                      seat("openai", "disposition", H2)]))
        h.post(outcome(o2, [empty(seat("anthropic", "disposition", H2), "usage-limit"),
                            received(seat("openai", "disposition", H2))], 0))
        result = h.clearance(resolved(head=H2))
        self.assertTrue(result["clean"], result["reasons"])
        self.assertEqual(result["seats"]["anthropic"], "empty")
        self.assertIn("anthropic: empty", result["limits"])

    def test_late_finding_stays_blocking_until_someone_examines_it(self):
        h = History()
        o1 = first_round(h, {"anthropic": "clean", "openai": "clean", "google": "empty"})
        o2 = h.post(opened("r2", H2, [seat("anthropic", "delta", H1), seat("openai", "delta", H1),
                                      full("google")]))
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1)),
                            received(seat("openai", "delta", H1)), empty(full("google"))]))
        h.post(outcome(o1, [received(full("google"), important=1)]))  # late, at H1
        # A new round that only records the finder EMPTY and carries the rest examines nothing.
        o3 = h.post(opened("r3", H2, [seat("google", "delta", H1)], covered=("anthropic", "openai")))
        h.post(outcome(o3, [empty(seat("google", "delta", H1), "usage-limit")], 0))
        self.assertFalse(h.clearance(resolved(head=H2))["clean"])
        seats, covered = h.plan(resolved(head=H2))
        self.assertEqual({seats["anthropic"]["scope"], seats["openai"]["scope"]}, {"disposition"})
        o4 = h.post(opened("r4", H2, [seat("google", "delta", H1), seat("anthropic", "disposition", H2),
                                      seat("openai", "disposition", H2)]))
        h.post(outcome(o4, [empty(seat("google", "delta", H1), "usage-limit"),
                            received(seat("anthropic", "disposition", H2)),
                            received(seat("openai", "disposition", H2))], 0))
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])

    def test_void_frame_is_ordered_by_its_own_open(self):
        h = History()
        h.post(opened("v", H1, [seat("anthropic", "full", B2)], base=B2))  # void round, first frame
        first_round(h)  # a clean round at (H1, B)
        v2 = opened("v", H1, [full("anthropic")])  # the void round later names (H1, B) too
        h.post(v2)
        rounds, _ = h.rounds()
        latest = cp.latest_round_at_head(rounds, H1, B, "master")
        self.assertEqual(latest["id"], rid("v", H1))
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_pending_updates_hold_the_lock(self):
        tmp = Path(tempfile.mkdtemp(prefix="council-lock."))
        self.addCleanup(shutil.rmtree, tmp)
        git(tmp, "init", "--quiet")
        observed = []
        original = cp.write_pending

        def probe(cwd, state):
            with open(cp.pending_path(cwd) + ".lock", "a") as other:
                try:
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    observed.append("unlocked")
                    fcntl.flock(other, fcntl.LOCK_UN)
                except BlockingIOError:
                    observed.append("locked")
            original(cwd, state)
        cp.write_pending = probe
        try:
            cp.remember_refusal(str(tmp), "PR seven", "unrecognized-argument", "production")
            inv = {"corrections": cp.carried(str(tmp), "production")[0], "unknown": []}
            cp.consume_pending(str(tmp), inv)
        finally:
            cp.write_pending = original
        self.assertEqual(observed, ["locked", "locked"])

    def test_identical_findings_retry_is_not_late_information(self):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        o2 = h.post(opened("r2", H2, [seat(n, "delta", H1) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [received(seat(n, "delta", H1)) for n in ("anthropic", "openai", "google")]))
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])
        # Someone re-posts round 1's identical outcome record by hand.
        h.post(outcome(rounds_open(h, 0), [received(full(n), important=1 if n == "anthropic" else 0)
                                           for n in ("anthropic", "openai", "google")], 0))
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])

    def test_late_clean_on_an_older_head_does_not_erase_newer_findings(self):
        # AUDIT-7 / Anthropic P9 / OpenAI round 4: a later arrival is not a later review.
        h = History()
        o1 = h.post(opened("r1", H1, [full(n) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o1, [empty(full("anthropic"), "timeout"), received(full("openai")),
                            empty(full("google"), "timeout")]))
        o2 = h.post(opened("r2", H2, [full("anthropic"), seat("openai", "delta", H1), full("google")]))
        h.post(outcome(o2, [received(full("anthropic"), important=1),
                            received(seat("openai", "delta", H1)), empty(full("google"), "timeout")]))
        h.post(outcome(o1, [received(full("anthropic"))]))  # old H1 clean arrives late
        standing = cp.plan(resolved(head=H2), h.rounds()[0], "anthropic", is_ancestor)["standing_findings"]
        self.assertEqual(pairs(standing), [{"round": rid("r2", H2), "seat": "anthropic"}])
        o3 = h.post(opened("r3", H2, [seat("anthropic", "disposition", H2), full("google"),
                                      seat("openai", "disposition", H2)]))
        h.post(outcome(o3, [empty(seat("anthropic", "disposition", H2), "timeout"),
                            empty(full("google"), "timeout"),
                            empty(seat("openai", "disposition", H2), "timeout")]))
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["anthropic"], "findings")

    def test_finding_posted_after_the_snapshot_is_not_examined_by_that_round(self):
        h = History()
        first_round(h, {"anthropic": "clean", "openai": "clean", "google": "empty"})
        o2 = opened("r2", H2, [seat("anthropic", "delta", H1), seat("openai", "delta", H1), full("google")])
        h.post(o2)  # snapshot taken now: nothing stands
        h.post(outcome(rounds_open(h, 0), [received(full("google"), important=1)]))  # arrives after
        h.post(outcome(o2, [received(seat("anthropic", "delta", H1)),
                            received(seat("openai", "delta", H1)), empty(full("google"))]))
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["google"], "findings")

    def test_round_that_does_not_list_a_finding_does_not_examine_it(self):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        o2 = h.post(opened("r2", H2, [seat(n, "delta", H1) for n in ("anthropic", "openai", "google")]),
                    snapshot=False)  # hand-trimmed: claims nothing stands
        h.post(outcome(o2, [empty(seat("anthropic", "delta", H1), "timeout"),
                            received(seat("openai", "delta", H1)), received(seat("google", "delta", H1))]))
        self.assertFalse(h.clearance(resolved(head=H2))["clean"])

    def test_finding_survives_a_merge_base_change(self):
        # AUDIT-8 I6 scenario A: master merged into the branch moves the merge-base.
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        new = resolved(head=H2, base=B2)
        standing = cp.plan(new, h.rounds()[0], "anthropic", is_ancestor)["standing_findings"]
        self.assertEqual(pairs(standing), [{"round": rid("r1", H1), "seat": "anthropic"}])
        def full2(n):
            return seat(n, "full", B2)
        trimmed = h.post(opened("t", H2, [full2(n) for n in ("anthropic", "openai", "google")],
                                base=B2), snapshot=False)
        h.post(outcome(trimmed, [empty(full2("anthropic"), "usage-limit"),
                                 received(full2("openai")), received(full2("google"))]))
        self.assertFalse(h.clearance(new)["clean"])  # nobody was asked about it
        o = h.post(opened("u", H2, [full2(n) for n in ("anthropic", "openai", "google")], base=B2))
        h.post(outcome(o, [empty(full2("anthropic"), "usage-limit"),
                           received(full2("openai")), received(full2("google"))]))
        self.assertTrue(h.clearance(new)["clean"])  # the listing round examined it

    def test_finding_in_a_void_round_still_stands(self):
        # AUDIT-8 I6 scenario B: an unrelated conflicting record voids the round.
        h = History()
        o1 = h.post(opened("r1", H1, [full(n) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o1, [received(full("anthropic"), important=1), received(full("openai")),
                            received(full("google"))]))
        h.post(outcome(o1, [received(full("openai"), nit=1)]))  # mistaken second outcome: void
        self.assertTrue(h.rounds()[0][0]["conflict"])
        standing = cp.plan(resolved(head=H1), h.rounds()[0], "anthropic", is_ancestor)["standing_findings"]
        self.assertEqual(pairs(standing), [{"round": rid("r1", H1), "seat": "anthropic"}])
        o2 = h.post(opened("r2", H1, [full(n) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [empty(full("anthropic"), "usage-limit"), received(full("openai")),
                            received(full("google"))]))
        self.assertTrue(h.clearance(resolved(head=H1))["clean"])

    def test_distinct_later_finding_in_the_same_round_is_not_pre_examined(self):
        h = History()
        o1 = h.post(opened("r1", H1, [full(n) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o1, [received(full("anthropic"), important=1), received(full("openai")),
                            received(full("google"))]))
        o2 = h.post(opened("r2", H1, [seat(n, "disposition", H1) if n == "anthropic" else full(n)
                                      for n in ("anthropic", "openai", "google")]))  # lists r1/anthropic
        h.post(outcome(o1, [received(full("anthropic"), critical=2)]))  # distinct, posted after r2 opened
        h.post(outcome(o2, [empty(seat("anthropic", "disposition", H1), "timeout"),
                            received(full("openai")), received(full("google"))]))
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_outcome_posted_before_its_open_record_examines_nothing(self):
        h = History()
        first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        o2 = opened("r2", H1, [seat("anthropic", "disposition", H1), full("openai")])
        o2["standing"] = cp.plan(resolved(head=H1), h.rounds()[0], "anthropic",
                                 is_ancestor)["standing_findings"]
        h.post(outcome(o2, [received(full("openai"))]))  # an orphan outcome...
        h.post(o2, snapshot=False)                        # ...then an open record claiming it
        rounds, _ = h.rounds()
        self.assertIn("before its open record", rounds[-1]["conflict"])
        self.assertFalse(h.clearance(resolved(head=H1))["clean"])

    def test_corrected_finding_after_an_examining_round_stands(self):
        # AUDIT-9: a nonidentical correction to r1 arrives after r2 examined r1.
        h = History()
        o1 = h.post(opened("r1", H1, [full(n) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o1, [received(full("anthropic"), important=1), received(full("openai")),
                            empty(full("google"))]))
        o2 = h.post(opened("r2", H2, [full(n) for n in ("anthropic", "openai", "google")]))
        h.post(outcome(o2, [received(full(n)) for n in ("anthropic", "openai", "google")]))
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])
        h.post(outcome(o1, [received(full("anthropic"), important=2)]))
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["anthropic"], "findings")

    def test_changed_evidence_between_plan_and_post_is_not_in_the_snapshot(self):
        # AUDIT-9: the snapshot already names the old (round, seat) pair.
        h = History()
        o1 = first_round(h, {"anthropic": "findings", "openai": "clean", "google": "clean"})
        snap = cp.plan(resolved(head=H2), h.rounds()[0], "anthropic", is_ancestor)["standing_findings"]
        h.post(outcome(o1, [received(full("anthropic"), critical=1)]))  # changed, after plan
        # The correction voids r1, so every seat reviews in full; only the
        # examination question remains: the snapshot names the OLD outcome.
        o2 = opened("r2", H2, [full(n) for n in ("anthropic", "openai", "google")])
        o2["standing"] = snap
        h.post(o2, snapshot=False)
        h.post(outcome(o2, [empty(full("anthropic"), "timeout"),
                            received(full("openai")), received(full("google"))]))
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["anthropic"], "findings")
        self.assertEqual(result["seats"]["openai"], "clean")  # coverage is not the reason

    def edited_finding_history(self, snapshot=True):
        """Anthropic P10: round a's findings outcome comment is later edited."""
        h = History()
        o1 = h.post(opened("a", H2, [full(n) for n in ("anthropic", "openai", "google")]))
        out = outcome(o1, [received(full("anthropic"), critical=2), received(full("openai")),
                           empty(full("google"))])
        h.post(out, edited=True)
        o2 = h.post(opened("b", H2, [full(n) for n in ("anthropic", "openai", "google")]),
                    snapshot=snapshot)
        h.post(outcome(o2, [empty(full("anthropic"), "timeout"), received(full("openai")),
                            empty(full("google"), "timeout")]))
        return h

    def test_edited_trusted_record_is_unknown_evidence(self):
        # P10: an edited findings comment blocks whatever later rounds list...
        for snapshot in (False, True):
            result = self.edited_finding_history(snapshot=snapshot).clearance(resolved(head=H2))
            self.assertFalse(result["clean"])
            self.assertTrue(any("unknown" in r for r in result["reasons"]), result["reasons"])

    def test_record_edited_to_clean_still_blocks(self):
        # Round 6: the edit itself may have removed the findings.
        h = History()
        o1 = h.post(opened("a", H2, [full(n) for n in ("anthropic", "openai")]))
        now_clean = outcome(o1, [received(full("anthropic")), received(full("openai"))])
        h.post(now_clean, edited=True)
        o2 = h.post(opened("b", H2, [full(n) for n in ("anthropic", "openai")]))
        h.post(outcome(o2, [received(full("anthropic")), received(full("openai"))]))
        self.assertFalse(h.clearance(resolved(head=H2))["clean"])

    def test_quoting_the_marker_in_discussion_is_not_a_record(self):
        # Anthropic P11: a review comment quoting the helper's source.
        h = History()
        first_round(h)
        h.post(None, body='Nit N4: `MARK_OPEN = "<!-- council-review-round"` at line 31 -->')
        h.post(None, body="> <!-- council-review-round\n> quoted from the record above")
        self.assertTrue(h.clearance(resolved(head=H1))["clean"])
        self.assertEqual(h.rounds()[1], [])  # nothing ignored, nothing unreadable

    def edited_history(self, body):
        h = History()
        o1 = h.post(opened("a", H2, [full(n) for n in ("anthropic", "openai")]))
        h.post(outcome(o1, [received(full("anthropic")), received(full("openai"))]))
        h.post(None, edited=True, body=body)
        return h

    def test_edited_record_cannot_escape_by_changing_its_fields_or_shape(self):
        # Round 7: repo/pr changed, the JSON start broken, or the block fenced.
        o = opened("a", H2, [full("anthropic")])
        moved = dict(outcome(o, [received(full("anthropic"), critical=1)]), pr=999)
        for body in (as_record(cp.encode_block(moved)),
                     as_record(cp.MARK_OPEN + "\nnot json any more\n" + cp.MARK_CLOSE),
                     as_record("```\n" + cp.encode_block(outcome(o, [received(full("anthropic"))]))
                               + "\n```")):
            result = self.edited_history(body).clearance(resolved(head=H2))
            self.assertFalse(result["clean"], body[:40])
            self.assertTrue(any("unknown" in r for r in result["reasons"]))

    def test_record_header_with_a_bad_payload_is_not_discussion(self):
        for block in (cp.MARK_OPEN + "\nthis is not JSON\n" + cp.MARK_CLOSE, "no block at all"):
            h = History()
            first_round(h)
            h.post(None, body=as_record(block))  # unedited, trusted
            self.assertFalse(h.clearance(resolved(head=H1))["clean"], block)

    def test_honestly_edited_helper_record_blocks_as_unknown(self):
        # Round 7 I8: a web edit may return CRLF line endings or touch the
        # marker line; either way the record is unknown, never discussion.
        o = opened("a", H2, [full("anthropic")])
        body = cp.render(outcome(o, [received(full("anthropic"), important=1)]))
        for edit in (body.replace("\n", "\r\n"),
                     "Update: fixed a typo below.\n\n" + body,  # Anthropic round 8 I12 (P13)
                     body.replace(cp.MARK_OPEN + "\n", cp.MARK_OPEN + " \n"),
                     body.replace("Do not edit", "Do not ever edit")):
            result = self.edited_history(edit).clearance(resolved(head=H2))
            self.assertFalse(result["clean"])
            self.assertTrue(any("unknown" in r for r in result["reasons"]))

    def test_repost_clears_only_once_the_edited_comment_is_gone(self):
        # CTO audit 14 I12: the remedy is repost, then delete the damaged comment.
        h = History()
        o1 = h.post(opened("a", H2, [full(n) for n in ("anthropic", "openai")]))
        rec = outcome(o1, [received(full("anthropic")), received(full("openai"))])
        h.post(dict(rec), edited=True)  # an honest typo fix in the web editor
        h.post(dict(rec))  # the runner reposts the round's record from its own data
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertTrue(any("reposting alone clears nothing" in r for r in result["reasons"]))
        damaged = h.comments[1]["id"]
        h.comments = [c for c in h.comments if c["id"] != damaged]  # deleted on GitHub
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])

    def test_unedited_crlf_record_is_read(self):
        h = History()
        o1 = h.post(opened("a", H2, [full(n) for n in ("anthropic", "openai")]))
        rec = outcome(o1, [received(full("anthropic"), important=1), received(full("openai"))])
        h.post(None, body=cp.render(rec).replace("\n", "\r\n"))
        rounds, ignored = h.rounds()
        self.assertEqual(ignored, [])
        self.assertEqual(h.clearance(resolved(head=H2))["seats"]["anthropic"], "findings")

    def test_fenced_record_example_is_discussion(self):
        h = History()
        o = first_round(h)
        example = "Example record:\n```\n" + cp.MARK_OPEN + "\n{ corrupt example\n" + cp.MARK_CLOSE + "\n```"
        h.post(None, body=example)
        reference = open(os.path.join(os.path.dirname(os.path.abspath(cp.__file__)),
                                      "..", "references", "pr-rounds.md")).read()
        h.post(None, body="Per the reference:\n\n" + reference)
        quoted = cp.render(outcome(o, [received(full("anthropic"), critical=1)]))
        h.post(None, body="This record looked wrong to me:\n```\n" + quoted + "\n```")
        indented = "\n".join("    " + line for line in quoted.split("\n"))
        h.post(None, body=indented)  # an indented Markdown code block (OpenAI round 8)
        h.post(None, body="**council-review-round v1 notes**: the header alone is not a record")
        # An honest typo fix to a discussion comment keeps it discussion.
        h.post(None, edited=True, body="Fixed typo. Example:\n```\n" + quoted + "\n```")
        self.assertTrue(h.clearance(resolved(head=H1))["clean"])
        self.assertEqual(cp.plan(resolved(head=H1), h.rounds()[0], "anthropic", is_ancestor)
                         ["blocking_records"], [])

    def test_unedited_invalid_trusted_record_is_read_leniently(self):
        h = History()
        o1 = h.post(opened("a", H2, [full(n) for n in ("anthropic", "openai")]))
        bad = outcome(o1, [received(full("anthropic"), important=1), received(full("openai"))])
        bad["extra"] = "invalid field"  # fails validation, but is exactly what was posted
        h.post(None, body=as_record(cp.encode_block(bad)))
        result = h.clearance(resolved(head=H2))
        self.assertFalse(result["clean"])
        self.assertEqual(result["seats"]["anthropic"], "findings")

    def test_untrusted_comment_findings_are_not_evidence(self):
        h = History()
        o1 = h.post(opened("a", H2, [full(n) for n in ("anthropic", "openai")]))
        h.post(outcome(o1, [received(full("anthropic")), received(full("openai"))]))
        h.post(outcome(o1, [received(full("anthropic"), critical=9)]), assoc="NONE")  # outsider
        self.assertTrue(h.clearance(resolved(head=H2))["clean"])

    def test_unreadable_trusted_record_blocks_as_unknown(self):
        h = History()
        first_round(h)
        h.post(None, body=as_record(cp.MARK_OPEN + "\n{broken\n" + cp.MARK_CLOSE))
        result = h.clearance(resolved(head=H1))
        self.assertFalse(result["clean"])
        self.assertTrue(any("unknown" in r for r in result["reasons"]))
        got = cp.plan(resolved(head=H1), h.rounds()[0], "anthropic", is_ancestor)
        self.assertEqual(got["blocking_records"], [h.comments[-1]["id"]])  # before any seat is spent
        h2 = History()
        o = first_round(h2)
        future = dict(outcome(o, [received(full("anthropic"))]), version=2)
        h2.post(None, body=as_record(cp.encode_block(future)))
        self.assertFalse(h2.clearance(resolved(head=H1))["clean"])

    def test_parse_keeps_pr_named_files_advisory(self):
        for advisory in ("PR.md", "pr-notes.md", "pr/x.py", "prompts/review.txt"):
            self.assertIsNone(cp.parse_invocation(advisory), advisory)
        for bad in ("PR", "PR x", "PR#x", "#"):
            with self.assertRaises(cp.Refusal, msg=bad):
                cp.parse_invocation(bad)

    def test_concurrent_rounds_carrying_one_refusal_count_it_once(self):
        rows = []
        for i, name in enumerate(("a", "b")):
            rec = opened(name, H1, [full("anthropic")], corrections=[corr("0badcafe")])
            rows.append(("o/r", {"id": name, "open": rec, "outcome_at": "x",
                                 "opened_at": f"2026-11-10T00:0{i}:00Z"}))
        result = cp.tally(rows, since="2026-11-01T00:00:00Z")
        self.assertEqual((result["rounds"], result["mistakes"]), (2, 1))

    def test_unknown_capture_is_reported_not_zero(self):
        rec = opened("u", H1, [full("anthropic")])
        rec["invocation"]["unknown"] = ["deadbeef"]
        result = cp.tally([("o/r", {"id": "u", "open": rec, "outcome_at": "x",
                                     "opened_at": "2026-11-10T00:00:00Z"})], since="2026-11-01T00:00:00Z")
        self.assertEqual(result["rounds_with_unknown_corrections"], 1)


class LegacyAliasAndMeasurement(unittest.TestCase):
    full_sha = staticmethod(lambda sha: {H2[:12]: H2, H1[:9]: H1}.get(sha, sha))

    def test_alias_with_the_pushed_head_is_accepted_and_noted(self):
        cp.check_legacy(resolved(head=H2), H2, B, self.full_sha)
        self.assertEqual(cp.invocation_notes("legacy-formal", False), ["legacy-formal-alias"])

    def test_alias_with_an_abbreviated_head_is_accepted(self):
        cp.check_legacy(resolved(head=H2), H2[:12], None, self.full_sha)

    def test_alias_with_a_stale_sha_is_refused(self):
        with self.assertRaises(cp.Refusal) as ctx:
            cp.check_legacy(resolved(head=H2), H1[:9], None, self.full_sha)
        self.assertEqual(ctx.exception.code, "supplied-sha-mismatch")

    def test_alias_with_a_last_reviewed_sha_as_base_is_refused(self):
        with self.assertRaises(cp.Refusal) as ctx:
            cp.check_legacy(resolved(head=H2), H2, H1, self.full_sha)
        self.assertEqual(ctx.exception.code, "supplied-base-mismatch")

    def test_alias_without_a_sha_is_refused(self):
        for raw in ("formal",):
            with self.assertRaises(cp.Refusal) as ctx:
                cp.parse_invocation(raw)
            self.assertEqual(ctx.exception.code, "formal-sha-missing")
        with self.assertRaises(cp.Refusal):
            cp.check_legacy(resolved(head=H2), None, None, self.full_sha)

    def test_plain_pr_invocation_has_no_notes(self):
        self.assertEqual(cp.invocation_notes("pr", True), [])

    def test_branch_route_notes_only_commits_ahead(self):
        self.assertEqual(cp.invocation_notes("branch-pr", True),
                         ["branch-routed-to-pr", "unpushed-local-commits"])
        self.assertEqual(cp.invocation_notes("branch-pr", False), ["branch-routed-to-pr"])

    def test_invocation_routing(self):
        self.assertEqual(cp.parse_invocation("PR #7")["pr"], 7)
        self.assertEqual(cp.parse_invocation("#7")["route"], "pr")
        self.assertEqual(cp.parse_invocation("branch")["route"], "branch-pr")
        got = cp.parse_invocation(f"formal {H2[:12]} {B}")
        self.assertEqual((got["route"], got["sha"], got["base"]), ("legacy-formal", H2[:12], B))
        for advisory in ("", "staged", "skills/council-review/SKILL.md"):
            self.assertIsNone(cp.parse_invocation(advisory))
        for bad in ("PR #7 extra", "PR seven", "#7x", "formal not-a-sha"):
            with self.assertRaises(cp.Refusal) as ctx:
                cp.parse_invocation(bad)
            self.assertEqual(ctx.exception.code, "unrecognized-argument", bad)

    def tally_rows(self):
        rows = []
        for i in range(12):
            pr = 7 if i % 2 else 8
            corrections = [corr("0000000%d" % (i % 10))] if i == 3 else []
            notes = ["legacy-formal-alias"] if i == 5 else []
            rec = opened(f"r{i}", H1, [full("anthropic")], notes=notes, corrections=corrections, pr=pr)
            rows.append(("o/r", {"id": f"r{i}", "open": rec, "outcome_at": "x",
                                 "opened_at": f"2026-11-1{i // 10}T00:{i % 10:02d}Z"}))
        return rows

    def test_tally_spans_prs_in_time_order_and_stops_at_ten(self):
        rows = self.tally_rows()
        rows.append(("o/r", rows[0][1]))  # the same round seen twice
        crashed = opened("crashed", H1, [full("anthropic")], pr=8)
        rows.append(("o/r", {"id": "crashed", "open": crashed, "outcome_at": None,
                             "opened_at": "2026-11-09T00:00Z"}))  # never ran
        evaluation = opened("eval", H1, [full("anthropic")], pr=8, cohort="evaluation")
        rows.append(("o/r", {"id": "eval", "open": evaluation, "outcome_at": "x",
                             "opened_at": "2026-11-09T00:01Z"}))  # acceptance replay
        early = opened("early", H1, [full("anthropic")], pr=8)
        rows.append(("o/r", {"id": "early", "open": early, "outcome_at": "x",
                             "opened_at": "2026-11-01T00:00Z"}))  # before the rollout
        result = cp.tally(list(reversed(rows)), since="2026-11-02T00:00Z")
        self.assertEqual(result["rounds"], 10)
        self.assertEqual([r["round_id"] for r in result["rows"]], [f"r{i}" for i in range(10)])
        self.assertEqual({r["pr"] for r in result["rows"]}, {7, 8})  # no per-PR reset
        # A valid alias use is adoption, not a mistake; only the correction counts.
        self.assertEqual(result["rounds_with_mistakes"], 1)
        self.assertEqual(result["mistakes"], 1)
        self.assertEqual(result["alias_uses"], 1)

    def test_round_ids_are_unique_and_valid(self):
        a, b = cp.new_round_id(H1), cp.new_round_id(H1)
        self.assertNotEqual(a, b)
        self.assertTrue(cp.ROUND_ID.match(a))

    def test_argument_shapes(self):
        cases = {"PR #7": "pr-ref", "#7": "pr-ref", "": "none", "branch": "branch",
                 f"formal {H1}": "formal-sha", f"formal {H1[:9]} {B}": "formal-sha-base",
                 "formal /home/u/private.md": "formal-other",
                 "/home/u/notes.md": "other"}
        for text, shape in cases.items():
            self.assertEqual(cp.arg_shape(text), shape, text)


# --------------------------------------------------------------------------
# End to end: real git objects, fake gh

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_GH_STATE"]
state = json.load(open(path))
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    if len(args) > 2 and not args[2].startswith("--"):
        pass
    elif state.get("branch_pr") is None:
        sys.stderr.write("no pull requests found for branch \"x\"\n"); sys.exit(1)
    print(json.dumps(state["pr"])); sys.exit(0)
if args[:1] == ["api"]:
    for c in state["comments"]:
        print(json.dumps(c))
    sys.exit(0)
if args[:2] == ["pr", "comment"]:
    body = open(args[args.index("--body-file") + 1]).read()
    n = len(state["comments"])
    at = "2026-11-03T12:00:%02dZ" % n
    state["comments"].append({"id": 5000 + n, "author_association": "OWNER",
                              "created_at": at, "updated_at": at, "body": body})
    json.dump(state, open(path, "w")); sys.exit(0)
sys.stderr.write("fake gh: unsupported %r\n" % args); sys.exit(2)
'''


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="council-pr-test."))
        self.addCleanup(shutil.rmtree, self.tmp)
        remote, self.work = self.tmp / "remote.git", self.tmp / "work"
        git(self.tmp, "init", "--quiet", "--bare", str(remote))
        git(self.tmp, "init", "--quiet", "-b", "master", str(self.work))
        for key, val in (("user.name", "t"), ("user.email", "t@example.invalid"),
                         ("commit.gpgsign", "false"),
                         ("remote.origin.url", "https://github.com/o/r.git"),
                         ("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
                         (f"url.{remote}.insteadOf", "https://github.com/o/r.git")):
            git(self.work, "config", key, val)
        self.base = self.commit("base")
        git(self.work, "push", "--quiet", "origin", "master")
        git(self.work, "checkout", "--quiet", "-b", "feature")
        self.h1 = self.commit("first")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(0o755)
        self.state = self.tmp / "gh.json"
        saved = {k: os.environ.get(k) for k in ("FAKE_GH_STATE", "PATH")}
        self.addCleanup(self.restore_env, saved)
        os.environ["FAKE_GH_STATE"] = str(self.state)
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{saved['PATH']}"
        self.publish(self.h1)

    @staticmethod
    def restore_env(saved):
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def commit(self, name):
        (self.work / f"{name}.txt").write_text(name)
        git(self.work, "add", f"{name}.txt")
        git(self.work, "commit", "--quiet", "-m", name)
        return git(self.work, "rev-parse", "HEAD")

    def publish(self, head, force=False, branch_pr=True, reported_head=None):
        git(self.work, "push", "--quiet", "--force" if force else "--no-force",
            "origin", f"{head}:refs/pull/7/head")
        comments = json.loads(self.state.read_text())["comments"] if self.state.exists() else []
        self.state.write_text(json.dumps({
            "branch_pr": True if branch_pr else None, "comments": comments,
            "pr": {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN",
                   "headRefOid": reported_head or head, "headRefName": "feature",
                   "baseRefName": "master", "baseRefOid": self.base}}))

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cp.main(["--repo-dir", str(self.work), *args])
        return code, out.getvalue()

    def plan(self, raw="PR #7", *extra):
        return self.cli("plan", "--raw", raw, "--host", "anthropic", *extra)

    def post_open(self, plan):
        rec_path, body = self.tmp / "open.json", self.tmp / "body.md"
        rec_path.write_text(json.dumps(plan["open_record"]))
        body.write_text(self.cli("render", "--open-record", str(rec_path))[1])
        self.assertEqual(self.cli("post", "--body-file", str(body)), (0, "posted\n"))
        self.assertIn("already posted", self.cli("post", "--body-file", str(body))[1])
        return rec_path

    def post_outcomes(self, rec_path, entries, unresolved=0):
        outcomes, body = self.tmp / "outcomes.json", self.tmp / "body.md"
        outcomes.write_text(json.dumps(entries))
        code, text = self.cli("render", "--open-record", str(rec_path), "--outcomes",
                              str(outcomes), "--unresolved", str(unresolved))
        self.assertEqual(code, 0)
        body.write_text(text)
        self.assertEqual(self.cli("post", "--body-file", str(body))[0], 0)

    def run_round(self, verdicts, raw="PR #7"):
        code, out = self.plan(raw)
        self.assertEqual(code, 0, out)
        plan = json.loads(out)
        rec_path = self.post_open(plan)
        self.post_outcomes(rec_path, [
            {"seat": s["seat"], "status": "received", "verdict": verdicts.get(s["seat"], "clean"),
             "counts": {"critical": 0, "important": int(verdicts.get(s["seat"]) == "findings"),
                        "nit": 0}} for s in plan["open_record"]["seats"]])
        return plan

    def test_pr_lifecycle_from_first_round_to_clearance(self):
        plan = self.run_round({"anthropic": "findings"})
        self.assertEqual(plan["resolved"]["base"], self.base)
        self.assertTrue(all(s["scope"] == "full" for s in plan["plan"]["seats"]))
        self.assertEqual(self.cli("check", "7", "--expect-head", self.h1)[0], 1)  # findings

        h2 = self.commit("fix")
        self.publish(h2)
        plan = self.run_round({})
        self.assertEqual({(s["scope"], s["from"]) for s in plan["plan"]["seats"]},
                         {("delta", self.h1)})
        code, out = self.cli("check", "7", "--expect-head", h2)
        self.assertEqual(code, 0, out)

        h3 = self.commit("late push")
        self.publish(h3)
        code, out = self.cli("check", "7", "--expect-head", h2)
        self.assertEqual(code, 1)
        self.assertIn("not the expected", out)

    def test_render_requires_an_explicit_unresolved_count(self):
        code, out = self.plan()
        rec_path = self.post_open(json.loads(out))
        (self.tmp / "o.json").write_text("[]")
        code, _ = self.cli("render", "--open-record", str(rec_path), "--outcomes",
                           str(self.tmp / "o.json"))
        self.assertEqual(code, 2)

    def test_force_push_resets_to_full(self):
        self.run_round({})
        git(self.work, "checkout", "--quiet", "master")
        git(self.work, "checkout", "--quiet", "-b", "rewrite")
        rewritten = self.commit("rewritten")
        self.publish(rewritten, force=True)
        code, out = self.plan()
        self.assertEqual(code, 0)
        self.assertTrue(all(s["scope"] == "full" for s in json.loads(out)["plan"]["seats"]))

    def test_pr_that_moved_during_resolution_is_refused(self):
        h2 = self.commit("pushed meanwhile")
        self.publish(h2, reported_head=self.h1)  # gh reports h1; the remote already has h2
        self.assertEqual(self.plan()[0], 4)
        self.assertFalse(os.path.exists(cp.pending_path(str(self.work))))  # not a caller mistake

    def test_branch_without_pr_is_advisory(self):
        self.publish(self.h1, branch_pr=False)
        self.assertEqual(self.plan("branch")[0], 3)

    def test_branch_with_pr_is_formal(self):
        code, out = self.plan("branch")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["open_record"]["invocation"]["route"], "branch-pr")

    def test_advisory_targets_never_open_a_round(self):
        for raw in ("", "staged", "skills/x.md"):
            self.assertEqual(self.plan(raw)[0], 3, raw)

    def test_legacy_alias_with_stale_sha_is_refused_and_counted_once(self):
        self.assertEqual(self.plan(f"formal {self.base[:10]}")[0], 4)
        plan = self.run_round({}, raw=f"formal {self.h1[:10]}")  # corrected: abbreviated head
        inv = plan["open_record"]["invocation"]
        self.assertEqual(inv["notes"], ["legacy-formal-alias"])
        self.assertEqual([(c["shape"], c["reason"]) for c in inv["corrections"]],
                         [("formal-sha", "supplied-sha-mismatch")])
        h2 = self.commit("fix")
        self.publish(h2)
        plan = self.run_round({})
        self.assertEqual(plan["open_record"]["invocation"]["corrections"], [])  # not again

    def test_alias_without_a_pr_is_refused(self):
        self.publish(self.h1, branch_pr=False)
        self.assertEqual(self.plan(f"formal {self.h1}")[0], 4)

    def test_private_text_never_reaches_public_output(self):
        secret = "/home/u/private/notes-token-SECRETVALUE.md"
        self.assertEqual(self.plan(f"PR #7 {secret}")[0], 4)  # refused, remembered as a shape
        self.assertNotIn("SECRETVALUE", Path(cp.pending_path(str(self.work))).read_text())
        code, out = self.plan()
        plan = json.loads(out)
        self.assertEqual([(c["shape"], c["reason"]) for c in plan["open_record"]["invocation"]["corrections"]],
                         [("other", "unrecognized-argument")])
        rec_path = self.post_open(plan)
        code, tallied = self.cli("tally", "o/r#7", "--since", "2026-01-01T00:00:00Z")
        self.assertEqual(json.loads(tallied)["rounds"], 0)  # no outcome yet: not a council
        self.post_outcomes(rec_path, [{"seat": s["seat"], "status": "empty", "reason": "timeout"}
                                      for s in plan["open_record"]["seats"]])
        code, tallied = self.cli("tally", "o/r#7", "--since", "2026-01-01T00:00:00Z")
        self.assertEqual(code, 0)
        self.assertNotIn("SECRETVALUE", tallied)
        self.assertEqual(json.loads(tallied)["mistakes"], 1)
        self.assertNotIn("SECRETVALUE", self.state.read_text())

    def test_evaluation_rounds_are_recorded_but_not_measured(self):
        code, out = self.plan("PR #7", "--evaluation")
        plan = json.loads(out)
        self.assertEqual(plan["open_record"]["invocation"]["cohort"], "evaluation")
        rec_path = self.post_open(plan)
        self.post_outcomes(rec_path, [{"seat": s["seat"], "status": "empty", "reason": "timeout"}
                                      for s in plan["open_record"]["seats"]])
        code, tallied = self.cli("tally", "o/r#7", "--since", "2026-01-01T00:00:00Z")
        self.assertEqual(json.loads(tallied)["rounds"], 0)

    def test_target_advanced_after_last_push_still_resolves(self):
        git(self.work, "checkout", "--quiet", "master")
        tip = self.commit("someone else merged")
        git(self.work, "push", "--quiet", "origin", "master")
        git(self.work, "checkout", "--quiet", "feature")
        # gh still reports the base as it was at the PR's last push.
        code, out = self.plan()
        self.assertEqual(code, 0, out)
        res = json.loads(out)["resolved"]
        self.assertEqual(res["target_oid"], tip)
        self.assertEqual(res["base"], self.base)  # merge-base unchanged: no needless reset
        self.assertEqual(self.cli("check", "PR #7", "--expect-head", self.h1)[0], 1)  # parses

    def pending(self):
        return json.loads(Path(cp.pending_path(str(self.work))).read_text())

    def test_retried_post_does_not_consume_a_newer_identical_refusal(self):
        self.assertEqual(self.plan("formal")[0], 4)
        code, out = self.plan()
        plan = json.loads(out)
        rec_path = self.post_open(plan)  # posts, then a retry ("already posted") consumes again
        self.assertEqual(self.plan("formal")[0], 4)  # the same mistake, made again
        body = self.tmp / "body.md"
        body.write_text(self.cli("render", "--open-record", str(rec_path))[1])
        self.assertIn("already posted", self.cli("post", "--body-file", str(body))[1])
        self.assertEqual([i["reason"] for i in self.pending()["items"]], ["formal-sha-missing"])

    def test_unreadable_pending_state_is_kept_and_reported_unknown(self):
        path = Path(cp.pending_path(str(self.work)))
        path.write_text("{not json")
        code, out = self.plan()
        inv = json.loads(out)["open_record"]["invocation"]
        self.assertEqual(len(inv["unknown"]), 1)
        self.assertEqual(len(list(path.parent.glob(path.name + ".unreadable-*"))), 1)
        self.post_open(json.loads(out))
        self.assertFalse(path.exists())  # reported once, then cleared by id

    def test_many_refusals_are_all_kept(self):
        for _ in range(25):
            self.assertEqual(self.plan("PR seven")[0], 4)
        code, out = self.plan()
        self.assertEqual(len(json.loads(out)["open_record"]["invocation"]["corrections"]), 25)

    def test_evaluation_and_production_refusals_stay_apart(self):
        self.assertEqual(self.plan("PR seven")[0], 4)                  # production mistake
        self.assertEqual(self.plan("PR eight", "--evaluation")[0], 4)  # evaluator's mistake
        code, out = self.plan("PR #7", "--evaluation")
        ev = json.loads(out)["open_record"]["invocation"]
        self.assertEqual([c["shape"] for c in ev["corrections"]], ["other"])
        self.post_open(json.loads(out))
        code, out = self.plan()
        prod = json.loads(out)["open_record"]["invocation"]
        self.assertEqual(len(prod["corrections"]), 1)  # the production one survived
        self.assertNotEqual(prod["corrections"][0]["id"], ev["corrections"][0]["id"])

    def test_tally_since_must_be_a_github_timestamp(self):
        self.assertEqual(self.cli("tally", "o/r#7", "--since", "2026-11-03")[0], 2)

    def test_host_cli_name_is_an_error(self):
        self.assertEqual(self.cli("plan", "--raw", "PR #7", "--host", "claude")[0], 2)

    def test_unknown_remote_is_an_error_not_a_review(self):
        git(self.work, "config", "remote.origin.url", "https://github.com/x/y.git")
        self.assertEqual(self.plan()[0], 2)


# --------------------------------------------------------------------------

MUTATIONS = {
    "trust_reason": lambda comment: None,
    "chain_step": lambda coverage, outcome, round_head, is_ancestor: round_head,
    "same_frame": lambda rnd, base, target_ref: True,
    "coverage_in_head": lambda coverage, head, is_ancestor: coverage,
    "outcome_scope_reason": lambda dispatched, outcome: None,
    "check_legacy": lambda resolved, sha, base, expand: None,
    "undisposed_seats": lambda rnd: [],
    "arg_shape": lambda text: text,
    "void_resets": lambda rnd, seat: False,
    "latest_round_at_head": lambda rounds, head, base, target_ref: next(
        (r for r in reversed(rounds) if not r["conflict"] and r["open"]["head"] == head), None),
    "unknown_keys": lambda obj, allowed: None,
    "unlisted_status": lambda rounds, name, head, base, target_ref, is_ancestor: "missing",
    "consume_pending": lambda cwd, invocation: None,
    "target_tip": lambda tips, ref, reported: reported,
    "carried": lambda cwd, cohort: (
        [{k: i[k] for k in ("id", "shape", "reason")} for i in cp.read_pending(cwd)["items"]], []),
    "check_host": lambda host, new_provider: None,
    "unexamined_findings": lambda rounds, head, base, target_ref, is_ancestor: [],
    "finding_evidence": lambda rnd: {} if rnd["conflict"] else rnd["finding_posts"],
    "harvest_findings": lambda rec, repo, pr: [],
    "edited_trusted": lambda comment: False,
    "is_candidate": lambda body: cp.MARK_OPEN in body,
    "normalize": lambda body: body,
    "bare_marker_line": lambda body: False,
    "RECORD_HEADER": re.compile(r"\s*\*\*council-review-round v"),
    # Pair-only identity: every outcome of one seat in one round is the same finding.
    "finding_key": lambda round_id, seat, digest: {"round": round_id, "seat": seat,
                                                   "outcome": "0" * 12},
    "examines": lambda rnd, key, posted, head, base, target_ref, is_ancestor: (
        not rnd["conflict"] and rnd["order"] > posted
        and any(o["status"] == "received" for o in rnd["seats"].values())),
    "pending_lock": lambda cwd: contextlib.nullcontext(),
}


def run_suite(verbosity):
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    return unittest.TextTestRunner(verbosity=verbosity, stream=sys.stderr).run(suite)


def consume_by_shape(cwd, invocation):
    """The pre-audit consumption rule: match by shape and code, not identity."""
    state = cp.read_pending(cwd)
    for c in invocation["corrections"]:
        for item in state["items"]:
            if (item["shape"], item["reason"]) == (c["shape"], c["reason"]):
                state["items"].remove(item)
                break
    state["unknown"] = []
    cp.write_pending(cwd, state)


def unexamined_current_frame_only(rounds, head, base, target_ref, is_ancestor):
    """The pre-AUDIT-8 collection: findings only from valid current-frame rounds."""
    stand = []
    for rnd in rounds:
        if rnd["conflict"] or not cp.same_frame(rnd, base, target_ref):
            continue
        for name, posted in rnd["finding_posts"].items():
            key = {"round": rnd["id"], "seat": name}
            if not any(cp.examines(r, key, posted, head, base, target_ref, is_ancestor) for r in rounds):
                stand.append(key)
    return stand


def extract_anywhere(body):
    """The pre-round-6 extract: the marker anywhere in a comment is a record."""
    start = body.find(cp.MARK_OPEN)
    if start < 0:
        return None, None
    end = body.find(cp.MARK_CLOSE, start + len(cp.MARK_OPEN))
    if end < 0:
        return None, "unterminated record block"
    try:
        return json.loads(body[start + len(cp.MARK_OPEN):end]), None
    except ValueError as exc:
        return None, f"invalid JSON ({exc})"


def bare_marker_line_unfenced(body):
    """Anthropic's round-8 proposal: any exact marker line, fences ignored."""
    return cp.MARK_OPEN in body.split("\n")


def mutation_check():
    survived = []
    first_open_order = ("latest_round_at_head", lambda rounds, head, base, target_ref: max(
        (r for r in rounds if (head, base, target_ref) in r["frames"]),
        key=lambda r: r["order"], default=None))
    mutants = list(MUTATIONS.items()) + [("consume_pending", consume_by_shape), first_open_order,
                                         ("unexamined_findings", unexamined_current_frame_only),
                                         ("extract", extract_anywhere),
                                         ("bare_marker_line", bare_marker_line_unfenced)]
    for name, mutant in mutants:
        original = getattr(cp, name)
        setattr(cp, name, mutant)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                result = run_suite(0)
        finally:
            setattr(cp, name, original)
        killed = not result.wasSuccessful()
        label = {consume_by_shape: "consume_pending (by shape)",
                 first_open_order[1]: "latest_round_at_head (first-open order)",
                 unexamined_current_frame_only: "unexamined_findings (current frame only)"}.get(mutant, name)
        print(f"mutant {label}: {'killed' if killed else 'SURVIVED'}")
        if not killed:
            survived.append(name)
    return 1 if survived else 0


if __name__ == "__main__":
    if "--mutation-check" in sys.argv:
        sys.exit(mutation_check())
    sys.exit(0 if run_suite(2).wasSuccessful() else 1)
