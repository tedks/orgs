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
import io
import json
import os
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


def seat(name, scope, start, continuity=None, **extra):
    continuity = continuity or ("fresh" if scope == "full" else "warm")
    return {"seat": name, "mechanism": "native" if name == "anthropic" else "ask-agent",
            "model": cp.SEATS[name]["model"], "scope": scope, "from": start,
            "continuity": continuity, **extra}


def opened(rid, head, seats, base=B, target_ref="master", shape="pr-ref", route="pr",
           notes=(), corrections=(), pr=PR, covered=()):
    return {"schema": cp.SCHEMA, "version": 1, "phase": "open", "repo": REPO, "pr": pr,
            "round_id": rid, "head": head, "base": base, "target_ref": target_ref,
            "target_oid": T, "invocation": {"shape": shape, "route": route, "notes": list(notes),
                                            "corrections": list(corrections)},
            "covered": [{"seat": c, "through": head} for c in covered],
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


class History:
    """Comments in posting order, with GitHub-style metadata."""

    def __init__(self):
        self.comments = []

    def post(self, rec, assoc="OWNER", edited=False, body=None):
        n = len(self.comments)
        at = f"2026-11-03T10:{n // 60:02d}:{n % 60:02d}Z"
        self.comments.append({"id": 1000 + n, "author_association": assoc, "created_at": at,
                              "updated_at": "2026-11-04T00:00:00Z" if edited else at,
                              "body": body if body is not None else cp.render(rec)})
        return rec

    def rounds(self, repo=REPO, pr=PR):
        usable, ignored = cp.load_records(self.comments, repo, pr)
        rounds, orphans = cp.assemble(usable)
        return rounds, ignored + orphans

    def plan(self, res, host="anthropic"):
        rounds, _ = self.rounds()
        return {s["seat"]: s for s in cp.plan(res, rounds, host, is_ancestor)["seats"]}, \
            cp.plan(res, rounds, host, is_ancestor)["covered"]

    def clearance(self, res, expect=None):
        return cp.clearance(res, self.rounds()[0], is_ancestor, expect)


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
        self.assertEqual(covered, [{"seat": "anthropic", "through": H1}])
        self.assertNotIn("anthropic", seats)
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
        self.assert_ignored("invalid JSON", body=cp.MARK_OPEN + "\n{not json\n" + cp.MARK_CLOSE)

    def test_unterminated_block_is_ignored(self):
        self.assert_ignored("unterminated", body=cp.MARK_OPEN + '\n{"a": 1}')

    def test_two_blocks_in_one_comment_are_ignored(self):
        block = cp.encode_block(opened("r1", H1, [full("anthropic")]))
        self.assert_ignored("more than one", body=block + "\n" + block)

    def test_future_version_is_ignored(self):
        rec = dict(opened("r1", H1, [full("anthropic")]), version=2)
        self.assert_ignored("future version", body=cp.encode_block(rec))

    def test_record_copied_from_another_pr_is_ignored(self):
        rec = opened("r1", H1, [full("anthropic")], pr=8)
        self.assert_ignored("another repository or PR", body=cp.encode_block(rec))

    def test_short_sha_is_ignored(self):
        rec = opened("r1", H1[:12], [full("anthropic")])
        self.assert_ignored("bad head", body=cp.encode_block(rec))

    def test_full_scope_not_starting_at_base_is_ignored(self):
        rec = opened("r1", H1, [seat("anthropic", "full", H1)])
        self.assert_ignored("must start at the base", body=cp.encode_block(rec))

    def test_verdict_must_match_counts(self):
        o = opened("r1", H1, [full("anthropic")])
        bad = outcome(o, [dict(received(full("anthropic"), critical=1), verdict="clean")])
        self.assertIn("verdict disagrees", cp.validate(bad, REPO, PR))

    def test_outcome_without_open_record_is_ignored(self):
        h = History()
        o = opened("r1", H1, [full("anthropic")])
        h.post(outcome(o, [received(full("anthropic"))]))
        rounds, ignored = h.rounds()
        self.assertEqual(rounds, [])
        self.assertIn("without an open record", ignored[0]["reason"])

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
                     corrections=[{"shape": "other", "reason": "unrecognized-argument",
                                   "raw": "x"}])
        self.assertEqual(cp.validate(rec, REPO, PR), "bad invocation corrections")

    def test_empty_reason_must_be_a_code(self):
        o = opened("r1", H1, [full("anthropic")])
        bad = outcome(o, [empty(full("anthropic"), "quota at 97% on host tower0")])
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
        self.assertEqual(cp.tally([(REPO, r) for r in rounds])["rounds"], 1)

    def test_conflicting_open_records_make_the_round_count_for_nothing(self):
        h = History()
        h.post(opened("r1", H1, [full("anthropic")]))
        h.post(opened("r1", H2, [full("anthropic")]))
        rounds, _ = h.rounds()
        self.assertEqual(rounds[0]["conflict"], "conflicting open records")
        self.assertEqual(h.plan(resolved(head=H1))[0]["anthropic"]["scope"], "full")

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
        self.assertEqual(result["seats"]["anthropic"], "stale")
        self.assertIn("anthropic: stale", result["limits"])

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


class LegacyAliasAndMeasurement(unittest.TestCase):
    def test_alias_with_the_pushed_head_is_accepted_and_noted(self):
        cp.check_legacy(resolved(head=H2), H2, B)
        self.assertEqual(cp.invocation_notes("legacy-formal", H2, H2), ["legacy-formal-alias"])

    def test_alias_with_a_stale_sha_is_refused(self):
        with self.assertRaises(cp.Refusal) as ctx:
            cp.check_legacy(resolved(head=H2), H1, None)
        self.assertEqual(ctx.exception.code, "supplied-sha-mismatch")

    def test_alias_with_a_last_reviewed_sha_as_base_is_refused(self):
        with self.assertRaises(cp.Refusal) as ctx:
            cp.check_legacy(resolved(head=H2), H2, H1)
        self.assertEqual(ctx.exception.code, "supplied-base-mismatch")

    def test_plain_pr_invocation_has_no_notes(self):
        self.assertEqual(cp.invocation_notes("pr", H1, H2), [])

    def test_branch_route_notes_unpushed_commits(self):
        self.assertEqual(cp.invocation_notes("branch-pr", H3, H2),
                         ["branch-routed-to-pr", "unpushed-local-commits"])

    def test_tally_spans_prs_in_time_order_and_stops_at_ten(self):
        rows = []
        for i in range(12):
            pr = 7 if i % 2 else 8
            corrections = [{"shape": "formal-sha", "reason": "supplied-sha-mismatch"}] if i == 3 else []
            notes = ["legacy-formal-alias"] if i == 5 else []
            rec = opened(f"r{i}", H1, [full("anthropic")], notes=notes, corrections=corrections, pr=pr)
            rows.append(("o/r", {"id": f"r{i}", "open": rec, "opened_at": f"2026-11-1{i // 10}T00:{i % 10:02d}Z"}))
        rows.append(("o/r", rows[0][1]))  # the same round seen twice
        result = cp.tally(list(reversed(rows)))
        self.assertEqual(result["rounds"], 10)
        self.assertEqual([r["round_id"] for r in result["rows"]], [f"r{i}" for i in range(10)])
        self.assertEqual({r["pr"] for r in result["rows"]}, {7, 8})  # no per-PR reset
        # A valid alias use is adoption, not a mistake; only the correction counts.
        self.assertEqual(result["rounds_with_mistakes"], 1)
        self.assertEqual(result["mistakes"], 1)
        self.assertEqual(result["alias_uses"], 1)

    def test_round_ids_are_unique_per_invocation(self):
        self.assertNotEqual(cp.new_round_id(H1), cp.new_round_id(H1))

    def test_argument_shapes(self):
        cases = {"PR #7": "pr-ref", "#7": "pr-ref", "": "none", "branch": "branch",
                 f"formal {H1}": "formal-sha", f"formal {H1[:9]} {B}": "formal-sha-base",
                 "formal /home/someone/private.md": "formal-other",
                 "/home/someone/notes.md": "other"}
        for text, shape in cases.items():
            self.assertEqual(cp.arg_shape(text), shape, text)

    def test_pr_argument_forms(self):
        for text in ("PR #7", "#7", "7", "pr #7", "PR#7"):
            self.assertEqual(cp.parse_pr(text), 7)
        with self.assertRaises(cp.Refusal):
            cp.parse_pr("abc1234")


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
        os.environ["FAKE_GH_STATE"] = str(self.state)
        old_path = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        self.publish(self.h1)

    def commit(self, name):
        (self.work / f"{name}.txt").write_text(name)
        git(self.work, "add", f"{name}.txt")
        git(self.work, "commit", "--quiet", "-m", name)
        return git(self.work, "rev-parse", "HEAD")

    def publish(self, head, force=False, branch_pr=True):
        git(self.work, "push", "--quiet", "--force" if force else "--no-force",
            "origin", f"{head}:refs/pull/7/head")
        comments = json.loads(self.state.read_text())["comments"] if self.state.exists() else []
        self.state.write_text(json.dumps({
            "branch_pr": True if branch_pr else None, "comments": comments,
            "pr": {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN",
                   "headRefOid": head, "headRefName": "feature", "baseRefName": "master",
                   "baseRefOid": self.base}}))

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cp.main(["--repo-dir", str(self.work), *args])
        return code, out.getvalue()

    def run_round(self, verdicts):
        code, out = self.cli("plan", "--pr", "7", "--host", "anthropic", "--route", "pr",
                             "--raw", "PR #7")
        self.assertEqual(code, 0)
        plan = json.loads(out)
        rec_path, body = self.tmp / "open.json", self.tmp / "body.md"
        rec_path.write_text(json.dumps(plan["open_record"]))
        body.write_text(self.cli("render", "--open-record", str(rec_path))[1])
        self.assertEqual(self.cli("post", "--body-file", str(body)), (0, "posted\n"))
        self.assertIn("already posted", self.cli("post", "--body-file", str(body))[1])
        outcomes = self.tmp / "outcomes.json"
        outcomes.write_text(json.dumps([
            {"seat": s["seat"], "status": "received", "verdict": verdicts.get(s["seat"], "clean"),
             "counts": {"critical": 0, "important": int(verdicts.get(s["seat"]) == "findings"),
                        "nit": 0}} for s in plan["open_record"]["seats"]]))
        body.write_text(self.cli("render", "--open-record", str(rec_path), "--outcomes",
                                 str(outcomes))[1])
        self.assertEqual(self.cli("post", "--body-file", str(body))[0], 0)
        return plan

    def test_pr_lifecycle_from_first_round_to_clearance(self):
        plan = self.run_round({"anthropic": "findings"})
        self.assertEqual(plan["resolved"]["base"], self.base)
        self.assertTrue(all(s["scope"] == "full" for s in plan["plan"]["seats"]))
        self.assertEqual(self.cli("check", "7")[0], 1)  # findings open at head

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

    def test_force_push_resets_to_full(self):
        self.run_round({})
        git(self.work, "checkout", "--quiet", "master")
        git(self.work, "checkout", "--quiet", "-b", "rewrite")
        rewritten = self.commit("rewritten")
        self.publish(rewritten, force=True)
        code, out = self.cli("plan", "--pr", "7", "--host", "anthropic", "--route", "pr",
                             "--raw", "PR #7")
        self.assertEqual(code, 0)
        self.assertTrue(all(s["scope"] == "full" for s in json.loads(out)["plan"]["seats"]))

    def test_branch_without_pr_is_advisory(self):
        self.publish(self.h1, branch_pr=False)
        self.assertEqual(self.cli("resolve")[0], 3)

    def test_legacy_alias_with_stale_sha_is_refused(self):
        code, _ = self.cli("plan", "--host", "anthropic", "--route", "legacy-formal",
                           "--raw", f"formal {self.base}", "--legacy-sha", self.base)
        self.assertEqual(code, 4)

    def test_private_text_never_reaches_public_output(self):
        secret = "/home/someone/private/notes-token-SECRETVALUE.md"
        code, out = self.cli("plan", "--pr", "7", "--host", "anthropic", "--route", "pr",
                             "--raw", f"PR #7 {secret}", "--correction", secret,
                             "unrecognized-argument")
        self.assertEqual(code, 0, out)
        plan = json.loads(out)
        inv = plan["open_record"]["invocation"]
        self.assertEqual(inv["shape"], "other")
        self.assertEqual(inv["corrections"], [{"shape": "other", "reason": "unrecognized-argument"}])
        rec_path = self.tmp / "open.json"
        rec_path.write_text(json.dumps(plan["open_record"]))
        body = self.cli("render", "--open-record", str(rec_path))[1]
        self.assertNotIn("SECRETVALUE", body)
        (self.tmp / "body.md").write_text(body)
        self.cli("post", "--body-file", str(self.tmp / "body.md"))
        code, tallied = self.cli("tally", "o/r#7")
        self.assertEqual(code, 0)
        self.assertNotIn("SECRETVALUE", tallied)
        self.assertEqual(json.loads(tallied)["mistakes"], 1)
        self.assertNotIn("SECRETVALUE", self.state.read_text())

    def test_unknown_refusal_code_is_rejected(self):
        code, _ = self.cli("plan", "--pr", "7", "--host", "anthropic", "--route", "pr",
                           "--raw", "PR #7", "--correction", "x", "my own words")
        self.assertEqual(code, 2)

    def test_unknown_remote_is_an_error_not_a_review(self):
        git(self.work, "config", "remote.origin.url", "https://github.com/x/y.git")
        self.assertEqual(self.cli("resolve", "7")[0], 2)


# --------------------------------------------------------------------------

MUTATIONS = {
    "trust_reason": lambda comment: None,
    "chain_step": lambda coverage, outcome, round_head: round_head,
    "same_frame": lambda rnd, base, target_ref: True,
    "coverage_in_head": lambda coverage, head, is_ancestor: coverage,
    "outcome_scope_reason": lambda dispatched, outcome: None,
    "check_legacy": lambda resolved, sha, base: None,
    "undisposed_seats": lambda rnd: [],
    "arg_shape": lambda text: text,
}


def run_suite(verbosity):
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    return unittest.TextTestRunner(verbosity=verbosity, stream=sys.stderr).run(suite)


def mutation_check():
    survived = []
    for name, mutant in MUTATIONS.items():
        original = getattr(cp, name)
        setattr(cp, name, mutant)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                result = run_suite(0)
        finally:
            setattr(cp, name, original)
        killed = not result.wasSuccessful()
        print(f"mutant {name}: {'killed' if killed else 'SURVIVED'}")
        if not killed:
            survived.append(name)
    return 1 if survived else 0


if __name__ == "__main__":
    if "--mutation-check" in sys.argv:
        sys.exit(mutation_check())
    sys.exit(0 if run_suite(2).wasSuccessful() else 1)
