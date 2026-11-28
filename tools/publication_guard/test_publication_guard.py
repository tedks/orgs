import base64
import contextlib
from datetime import date
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

from tools.publication_guard import build_fixtures, guard

TERM = "quar" + "tzwillow"
ENCODED_TERM = "grove" + ".mistral"

# Council regression list (case, expected verdict, and test witness).
# Round 1
# 1. Percent, shell, and nested JSON escapes: finding / near miss clean
#    (test_repeated_whole_line_decoding, test_escaped_json_string).
# 2. Encoded-looking 200-character token: opaque / shorter clean (test_opaque_boundary).
# 3. Gzip payload split at member boundaries: denied in either view / clean control
#    (test_gzip_member_boundaries).
# 4–5. Active grafts: incomplete; empty tree entry name: finding
#    (test_git_grafts, test_git_empty_directory_name).
# 6–8. Diverged changed base: incomplete; zero commits or files: config error;
#    denied Git headers: review (test_changed_requires_ancestor,
#    test_empty_git_range_requires_waiver, test_empty_tree_requires_waiver,
#    test_git_header_surfaces).
# 9–11. Home variants and colon suffix: hard; delimited and generated compact IDs,
#    underscore-prefixed IDs and attached pane targets: hard until exactly allowed
#    (test_home_variants_and_colon, test_uuid_boundaries_and_separators,
#    test_request_boundaries_and_other_ids, test_pane_boundaries,
#    test_every_generated_id_is_detected_without_allow_list).
# 12–14. Digits, underscores, camel case, BOM, overlaps, varied whitespace,
#    dash encoding and zero-width text: review; invalid entries: config error
#    (test_deny_letter_boundaries, test_deny_bom_overlaps_and_whitespace,
#    test_dash_encoded_deny_list, test_deny_zero_width_and_ascii_policy,
#    test_deny_list_required_and_waivable).
# 15–16. Sensitive names and matches: masked; bad refs and shallow history: incomplete
#    (test_redacted_names_and_keyed_digests, test_deny_list_whole_word_and_redaction,
#    test_bad_git_range, test_shallow_git).
# Round 2
# A–B. Inherited repository selection ignored; empty selected full tree: config error
#    (test_git_ignores_repository_selection_environment,
#    test_full_git_range_rejects_empty_commit_tree).
# C–D. Path continuing after punctuation or a quoted space, an underscore pane
#    filename, a compact ID beside hex, and a compact ID beside an allowed dashed ID:
#    hard (test_home_path_punctuation_and_quoted_space,
#    test_underscore_pane_in_filename, test_compact_extended_tokens).
# E–F. Wrapped body: opaque; ordinary dotless paths and low-diversity text: clean;
#    four provider ID prefixes: hard (test_wrapped_opaque_body, test_opaque_precision,
#    test_response_id_boundary, test_reasoning_id_boundary,
#    test_function_call_id_boundary, test_call_id_boundary).
# G. Extended allowed ID and gzip extra data: hard; gzip comment, empty directory,
#    later overlapping occurrence, and replaced private commit: finding
#    (test_allow_id_is_exact, test_gzip_extra_field_is_reported,
#    test_gzip_comment_is_reported, test_tree_empty_directory_name,
#    test_overlapping_occurrences_of_one_deny_entry, test_git_ignores_replace_refs).
# H–K. Failed baseline: no credit; Git endpoints: resolved;
#    double percent before an escape: decoded; bad list files: config error
#    (test_mutation_runner_requires_passing_baseline,
#    test_git_resolved_endpoints_and_whole_history, test_percent_escape_after_percent,
#    test_deny_entries_reject_controls, test_allow_and_deny_list_load_errors).
# L–S. Tag annotation, Windows and upper-case Linux paths, cross-line phrase,
#    fifth escape round, and zero-width hard-rule disguises: manual review;
#    deliberate UUID overlap and mistyped args are documented limits
#    (test_annotated_tag_resolves_to_commit, test_documented_escape_and_path_boundaries,
#    test_deny_phrase_stays_within_physical_line). Unicode matching is covered
#    below; no general Unicode case-folding equivalence is promised.
# T. Evidence: the mutation runner reports results only after the baseline passes.
# Round 3
# 1–4. Letter-glued and paired compact IDs: hard, 40 hex: clean; decoded wrapped
#    JSON body: opaque; link beyond its exact allowance and date-suffixed pane:
#    hard (test_compact_nonhex_neighbors_and_pair, test_wrapped_opaque_body_in_decoded_record,
#    test_symlink_allowlist_compares_complete_target, test_pane_date_suffix_is_not_a_format_directive).
# 5–6. Leading-slash encoded body and long hex: opaque; short words, uneven wrap,
#    dotless paths: clean; upper-case macOS prefix: hard until exactly allowed
#    (test_base64_with_path_shaped_prefix, test_long_hex_run_is_opaque,
#    test_wrapped_opaque_requires_wide_consistent_lines, test_macos_home_prefix_case_and_exact_allowlist).
# 7–10. Commit-only push documented; dotless and dotted i: review; list errors:
#    specific redacted diagnostics; surrogate pair beside a denied word: review
#    (test_deny_prefilter_matches_unicode_case_variants,
#    test_missing_lists_are_distinct_from_invalid_encoding, test_surrogates_are_separators).
# 11–14. Source-tree provenance and decoding limits documented; doubled path
#    escapes are out of scope; unquoted brackets around an allowed path fail closed
#    (test_documented_escape_and_path_boundaries).
# 15. PR verification distinguishes zero new findings from earlier reviewed matches.
# Round 4
# 1. Standard encoder wrap with a shorter last line: opaque on physical and
#    decoded JSON lines (test_wrapped_standard_encoder_short_last_line).
# 2. Commit-only push uses the reviewed SHA and an explicit ref.
# 3. A letter before an allowed dashed UUID: hard. A mixed-case letters-only
#    body: clean (test_uuid_left_extension_precedes_allowlist,
#    test_opaque_requires_digit_class).
# 4. Lower-case macOS-like URL path, low-diversity hex, and complete directives:
#    clean. A wrapped JSON body is reported once (test_macos_home_prefix_case_and_exact_allowlist,
#    test_long_hex_run_is_opaque, test_complete_printf_directives_with_modifiers,
#    test_decoded_json_long_body_once).
# 5–7. Slash-heavy opaque data, concatenated literals, digest ambiguity, and
#    separate handling of surrogate halves: documented in the README.


class PublicationGuard(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.tree = self.root / "tree"
        self.tree.mkdir()
        self.deny = self.root / "deny.txt"
        self.deny.write_text(f"{TERM}\n{ENCODED_TERM}\n", encoding="utf-8")
        self.allow = self.root / "allow.txt"

    def run_guard(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = guard.main(list(map(str, args)))
        return result, [json.loads(line) for line in stdout.getvalue().splitlines()], stderr.getvalue()

    def scan(self, *args):
        return self.run_guard("--tree", self.tree, "--deny-list", self.deny, *args)

    def write(self, value, name="sample.txt"):
        (self.tree / name).write_text(value, encoding="utf-8")

    def git(self, *args, input=None, author="Sample"):
        env = dict(os.environ, HOME=str(self.root), XDG_CONFIG_HOME=str(self.root),
                   GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME=author, GIT_COMMITTER_NAME=author,
                   GIT_AUTHOR_EMAIL="sample@example.invalid",
                   GIT_COMMITTER_EMAIL="sample@example.invalid", GIT_GRAFT_FILE=os.devnull)
        return subprocess.run(
            ["git", "-C", str(self.tree), *args], stderr=subprocess.PIPE, env=env,
            input=input, stdout=subprocess.PIPE, encoding="utf-8", check=True,
        ).stdout.strip()

    def init_git(self):
        if not shutil.which("git"):
            self.skipTest("Git is needed for commit range tests")
        self.git("init")
        self.write("ordinary", "seed.txt")
        self.git("add", ".")
        self.git("commit", "-m", "Base tree")
        return self.git("rev-parse", "HEAD")

    def git_scan(self, range_, *args, repo=None):
        return self.run_guard("--deny-list", self.deny, "--repo", repo or self.tree,
                              "--git-range", range_, *args)

    def identifier_twin(self, rule, value, allowed=None):
        self.write(value)
        rc, findings, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([item["rule"] for item in findings[:-1]], [rule])
        self.assertEqual(findings[0]["line"], 1)
        self.assertNotIn(value, json.dumps(findings))
        self.allow.write_text((allowed or value) + "\n", encoding="utf-8")
        rc, findings, _ = self.scan("--allow-list", self.allow)
        self.assertEqual(rc, 0)
        self.assertEqual(findings, [dict(
            scope="tree", partial=False, files=1, bytes=len(value.encode()), commits=0, messages=0,
            hard=0, review=0,
        )])

    def test_uuid(self):
        value = "-".join(("dd5aabc4", "c2df", "4276", "8111", "abcddcba3210"))
        self.identifier_twin("uuid", value.upper(), value)

    def test_uuid_left_extension_precedes_allowlist(self):
        value = "-".join(("dd5aabc4", "c2df", "4276", "8111", "abcddcba3210"))
        self.allow.write_text(value + "\n", encoding="utf-8")
        self.write("x" + value)
        rc, rows, _ = self.scan("--allow-list", self.allow, "--unredacted")
        self.assertEqual(rc, 1)
        self.assertEqual([(row["rule"], row["match"]) for row in rows[:-1]], [("uuid", "x" + value)])
        self.write(value + "\nx:" + value)
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_request_id(self):
        value = "req_" + "4ebcf1" * 4
        self.identifier_twin("request-id", value)

    def test_codex_id(self):
        value = "".join(("02dd5aabc4a9", "7c2d", "a111", "abcddcba3210"))
        self.identifier_twin("codex-id", value)
        for ordinary in (value[:12] + "0" + value[13:], value[:16] + "d" + value[17:], "f" * 40):
            with self.subTest(ordinary=ordinary):
                self.write(ordinary)
                self.assertEqual(self.scan()[0], 0)

    def test_compact_extended_tokens(self):
        compact = "".join(("02dd5aabc4a9", "7c2d", "a111", "abcddcba3210"))
        dashed = "-".join(("bd5aab34", "c2df", "4276", "8111", "abcddcba3210"))
        self.allow.write_text(f"{compact}\n{dashed}\n", encoding="utf-8")
        self.write(f"f{compact}\n{dashed}{compact}")
        rc, records, _ = self.scan("--allow-list", self.allow)
        self.assertEqual(rc, 1)
        self.assertEqual([(r["line"], r["rule"]) for r in records[:-1]],
                         [(1, "codex-id"), (2, "uuid"), (2, "codex-id")])
        self.write(f"{compact}\n{dashed}\n{'f' * 40}")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_compact_nonhex_neighbors_and_pair(self):
        compact = "".join(("02dd5aabc4a9", "7c2d", "a111", "abcddcba3210"))
        for value in ("sess" + compact, "x" + compact, compact + "json", compact + compact):
            with self.subTest(value=value):
                self.write(value)
                self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["codex-id"])
        self.write("fa15d08e" + compact)
        self.assertEqual(self.scan()[0], 0)

    def test_uuid_boundaries_and_separators(self):
        parts = ("bd5aab34", "c2df", "4276", "8111", "abcddcba3210")
        self.write("a" + "-".join(parts) + "\n" + "_".join(parts))
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["uuid", "uuid"])
        self.write("-".join(parts[:-1] + (parts[-1][:-1],)))
        self.assertEqual(self.scan()[0], 0)

    def test_request_boundaries_and_other_ids(self):
        suffix = "4ebcf1" * 4
        IDs = [tag + "_" + suffix for tag in ("req", "msg", "toolu")]
        self.write("\n".join("prefix_" + value for value in IDs))
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]],
                         ["request-id", "message-id", "tool-id"])
        self.write("\n".join("prefix" + value for value in IDs))
        self.assertEqual(self.scan()[0], 0)

    def check_prefixed_id(self, prefix, rule):
        value = prefix + "_" + "a2c6d9" * 4
        self.write(f"prefix_{value}")
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], [rule])
        self.write(f"prefix{value}\n{prefix}_count")
        self.assertEqual(self.scan()[0], 0)

    def test_response_id_boundary(self):
        self.check_prefixed_id("resp", "response-id")

    def test_reasoning_id_boundary(self):
        self.check_prefixed_id("rs", "reasoning-id")

    def test_function_call_id_boundary(self):
        self.check_prefixed_id("fc", "function-call-id")

    def test_call_id_boundary(self):
        self.check_prefixed_id("call", "call-id")

    def test_allow_id_is_exact(self):
        allowed = "req_" + "a2c6d9" * 4
        self.allow.write_text(allowed, encoding="utf-8")
        for suffix in ("Z9", "_", "-"):
            with self.subTest(suffix=suffix):
                self.write(allowed + suffix)
                rc, results, _ = self.scan("--allow-list", self.allow)
                self.assertEqual(rc, 1)
                self.assertEqual([r["rule"] for r in results[:-1]], ["request-id"])
        self.write(allowed)
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_home_path(self):
        self.identifier_twin("home-path", guard.HOME_PREFIX + "example/sample")
        self.write(guard.HOME_PREFIX + "example/sample-secret")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 1)

    def test_home_variants_and_colon(self):
        roots = ("/var" + guard.HOME_PREFIX, "/" + "Users/", "/" + "root/", "~" + "sample/")
        paths = [root + "example" for root in roots]
        self.allow.write_text("\n".join(paths), encoding="utf-8")
        self.write("\n".join(paths))
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["home-path"] * 4)
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)
        self.write(paths[0] + ":private")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 1)

    def test_macos_home_prefix_case_and_exact_allowlist(self):
        lower = "/" + "Users/morrow/work"
        upper = "/" + "USERS/morrow/work"
        self.allow.write_text(lower, encoding="utf-8")
        self.write(upper)
        self.assertEqual([r["rule"] for r in self.scan("--allow-list", self.allow)[1][:-1]],
                         ["home-path"])
        self.write(lower)
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)
        self.write(upper)
        self.allow.write_text(upper, encoding="utf-8")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)
        self.write("https://example.invalid/" + "users/morrow/work\n/" + "uSeRS/morrow/work")
        self.assertEqual(self.scan()[0], 0)

    def test_home_path_punctuation_and_quoted_space(self):
        allowed = guard.HOME_PREFIX + "example/item"
        self.allow.write_text(allowed, encoding="utf-8")
        for tail in (",tail", "[tail]", "(tail)", '" tail"', r"\ tail"):
            with self.subTest(tail=tail):
                self.write(allowed + tail)
                rc, results, _ = self.scan("--allow-list", self.allow)
                self.assertEqual(rc, 1)
                self.assertEqual([r["rule"] for r in results[:-1]], ["home-path"])
        self.write(f'"{allowed} tail"')
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 1)
        self.write(f'"{allowed}"" tail"')
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 1)
        self.write(f'{{"cwd":"{allowed}","next":0}}')
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_pane_id(self):
        pane = "%" + "6281"
        self.identifier_twin("pane-id", pane)
        self.write(f"tmux-message send {pane} foo\nactive pane: {pane}\n")
        self.assertEqual([record["rule"] for record in self.scan()[1][:-1]], ["pane-id"] * 2)
        self.write('50% done, 15%2, escaped %%30, %02d, %10.2f, %1$s and #{pane_id}')
        self.assertEqual(self.scan()[0], 0)

    def test_pane_boundaries(self):
        pane = "%" + "4193"
        self.write(f"-t{pane}\npane{pane}")
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["pane-id"] * 2)
        self.write(f"percentage{pane}\n{pane}s\n{pane}$s")
        self.assertEqual(self.scan()[0], 0)

    def test_underscore_pane_in_filename(self):
        prefix = "pane_"
        pane = "%" + "12"
        self.write("ordinary", name=f"{prefix}{pane}.log")
        self.assertEqual([(r["rule"], r["surface"]) for r in self.scan()[1][:-1]],
                         [("pane-id", "name")])
        (self.tree / f"{prefix}{pane}.log").rename(self.tree / f"{prefix}{pane}.2f")
        self.assertEqual(self.scan()[0], 0)

    def test_pane_date_suffix_is_not_a_format_directive(self):
        pane = "%" + "12"
        filename = self.tree / f"pane_{pane}.20400512.log"
        filename.write_text("ordinary", encoding="utf-8")
        self.assertEqual([(r["rule"], r["surface"]) for r in self.scan()[1][:-1]],
                         [("pane-id", "name")])
        filename.rename(self.tree / f"pane_{pane}.2f")
        self.write(f"format {pane}$s and {pane}.2f.log")
        self.assertEqual(self.scan()[0], 0)

    def test_complete_printf_directives_with_modifiers(self):
        percent = "%"
        modifiers = (("hh", "d"), ("h", "d"), ("ll", "d"), ("l", "d"), ("L", "f"),
                     ("j", "d"), ("z", "u"), ("t", "d"))
        self.write("\n".join([percent + "12.3" + mark + conv for mark, conv in modifiers] + [
            percent + "1$-10s", percent + "2$-08.4lld",
        ]))
        self.assertEqual(self.scan()[0], 0)
        self.write("\n".join((percent + "12.3ll", percent + "1$-10")))
        self.assertEqual([row["rule"] for row in self.scan()[1][:-1]], ["pane-id", "pane-id"])

    def test_deny_list_whole_word_and_redaction(self):
        self.write(f"known {TERM.upper()}.", name=f"{TERM}.txt")
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual({r["surface"] for r in records[:-1]}, {"name", "content"})
        self.assertEqual({r["severity"] for r in records[:-1]}, {"review"})
        self.assertEqual(records[-1]["hard"], 0)
        self.assertNotIn(TERM, json.dumps(records).lower())
        self.assertNotIn("context", records[1])
        self.assertNotIn("digest", records[1])
        self.assertEqual((records[1]["list"], records[1]["entry"]), (1, 1))
        _, raw, _ = self.scan("--unredacted")
        self.assertEqual(raw[1]["context"], f"known {TERM.upper()}.")
        (self.tree / f"{TERM}.txt").rename(self.tree / "sample.txt")
        self.write(f"x{TERM} {TERM}suffix")
        self.assertEqual(self.scan()[0], 0)

    def test_deny_letter_boundaries(self):
        self.write(f"{TERM}2 {TERM}_suffix my{TERM.capitalize()} {TERM}Label")
        self.assertEqual(len(self.scan()[1][:-1]), 4)
        self.write(f"x{TERM} {TERM}tail")
        self.assertEqual(self.scan()[0], 0)

    def test_deny_bom_overlaps_and_whitespace(self):
        longer = TERM + " valley"
        self.deny.write_text(f"\ufeff{TERM}\n", encoding="utf-8")
        other = self.root / "second.txt"
        other.write_text(f"# heading\n{longer}\n", encoding="utf-8")
        self.write(f"{TERM}\t\u00a0valley")
        rc, records, _ = self.scan("--deny-list", other)
        self.assertEqual(rc, 1)
        self.assertEqual({(r["list"], r["entry"]) for r in records[:-1]}, {(1, 1), (2, 2)})
        self.write(f"x{TERM}\tvalley")
        self.assertEqual(self.scan("--deny-list", other)[0], 0)

    def test_overlapping_occurrences_of_one_deny_entry(self):
        self.deny.write_text("a-a", encoding="utf-8")
        self.write("xa-a-a")
        rc, rows, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([(r["column"], r["entry"]) for r in rows[:-1]], [(4, 1)])
        self.write("xa-ax")
        self.assertEqual(self.scan()[0], 0)

    def test_deny_zero_width_and_ascii_policy(self):
        self.deny.write_text(TERM[:2] + "\u200c" + TERM[2:], encoding="utf-8")
        self.write(TERM[:3] + "\u034f\u200b" + TERM[3:])
        self.assertEqual(self.scan()[0], 1)
        self.write("x" + TERM[:2] + "\u200b" + TERM[2:])
        self.assertEqual(self.scan()[0], 0)
        self.deny.write_text("k" + "notreed", encoding="utf-8")
        self.write("\u212a" + "notreed")
        self.assertEqual(self.scan()[0], 1)
        self.write("xk" + "notreed")
        self.assertEqual(self.scan()[0], 0)
        # The decomposed entry NFC-normalizes to a non-ASCII term.
        non_ascii = "murale" + "\u0301"
        self.deny.write_text(non_ascii, encoding="utf-8")
        rc, _, error = self.scan()
        self.assertEqual(rc, 2)
        self.assertNotIn("mural", error)

    def test_deny_prefilter_matches_unicode_case_variants(self):
        self.deny.write_text("finch\n", encoding="utf-8")
        spellings = ["f" + letter + "nch" for letter in ("\u0131", "\u0130")]
        self.write("\n".join(spellings))
        self.assertEqual([(r["rule"], r["line"]) for r in self.scan()[1][:-1]],
                         [("deny-list", 1), ("deny-list", 2)])
        self.write("x" + spellings[0])
        self.assertEqual(self.scan()[0], 0)

    def test_surrogates_are_separators(self):
        escaped_surrogate_pair = r"\ud83d\ude4a"
        self.write(escaped_surrogate_pair + TERM)
        self.assertEqual([(row["rule"], row["view"]) for row in self.scan()[1][:-1]],
                         [("deny-list", "decoded")])
        self.write(escaped_surrogate_pair + TERM + "tail")
        self.assertEqual(self.scan()[0], 0)

    def test_dash_encoded_deny_list(self):
        value = ENCODED_TERM.replace(".", "-").upper()
        self.write("-home-example-" + value + "-extra")
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([record["rule"] for record in records[:-1]], ["deny-list"])
        self.write("-home-example-x" + value + "x-extra")
        self.assertEqual(self.scan()[0], 0)

    def test_gzip_members_and_magic(self):
        first = b"first\n"
        second = f"{TERM}\n".encode()
        path = self.tree / "compressed.data"
        path.write_bytes(gzip.compress(first) + gzip.compress(second))
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([(r["surface"], r["line"]) for r in records[:-1]],
                         [("gzip-member", 1), ("content", 2)])
        self.assertEqual(records[0]["member"], 2)
        self.assertEqual(records[-1]["bytes"], len(first) + len(second))
        path.write_bytes(gzip.compress(first) + gzip.compress(b"other\n"))
        self.assertEqual(self.scan()[0], 0)

    def test_gzip_member_boundaries(self):
        path = self.tree / "archive.gz"

        def write(first, second):
            path.write_bytes(gzip.compress(first.encode()) + gzip.compress(second.encode()))

        write("prefix", TERM)
        rc, results, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([(r["surface"], r["member"]) for r in results[:-1]], [("gzip-member", 2)])
        write(TERM[:3], TERM[3:])
        rc, results, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([r["surface"] for r in results[:-1]], ["content"])
        write("prefix", TERM + "suffix")
        self.assertEqual(self.scan()[0], 0)

    def test_gzip_records_each_member_name(self):
        def compressed(name):
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode="wb", filename=name) as stream:
                stream.write(b"ordinary\n" * 20000)
            return buffer.getvalue()

        path = self.tree / "archive.gz"
        path.write_bytes(compressed("first") + compressed(TERM))
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual((records[0]["surface"], records[0]["member"]), ("gzip-name", 2))
        path.write_bytes(compressed("first") + compressed("second"))
        self.assertEqual(self.scan()[0], 0)

    def gzip_field(self, flag, payload):
        stream = bytearray(gzip.compress(b"ordinary\n", mtime=0))
        stream[3] |= flag
        stream[10:10] = payload
        (self.tree / "archive.gz").write_bytes(stream)

    def test_gzip_extra_field_is_reported(self):
        self.gzip_field(4, b"\x05\x00AB\x01\x00x")
        rc, rows, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([(r["rule"], r["surface"], r["member"]) for r in rows[:-1]],
                         [("undecodable", "gzip-extra", 1)])
        self.gzip_field(4, b"\x00\x00")
        self.assertEqual(self.scan()[0], 0)

    def test_gzip_comment_is_reported(self):
        self.gzip_field(16, TERM.encode() + b"\0")
        rc, rows, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([(r["rule"], r["surface"], r["member"]) for r in rows[:-1]],
                         [("deny-list", "gzip-comment", 1)])
        self.gzip_field(16, b"neutral\0")
        self.assertEqual(self.scan()[0], 0)

    def test_escaped_json_string(self):
        value = guard.HOME_PREFIX + "example"
        self.write(json.dumps({"path": value}).replace("/", r"\/"))
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([r["rule"] for r in records[:-1]], ["home-path"])
        self.allow.write_text(value + "\n", encoding="utf-8")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_repeated_whole_line_decoding(self):
        partial = f"%{ord(TERM[0]):02X}" + TERM[1:]
        nested = quote(partial, safe="")
        escaped = r"\x" + f"{ord(TERM[0]):02X}" + TERM[1:]
        mixed = r"\u0025" + partial[1:]
        shell_escaped = TERM[0] + "\\" + TERM[1:]
        for content in (nested, escaped, mixed, json.dumps(json.dumps([escaped])), shell_escaped):
            with self.subTest(content=content):
                self.write(content)
                rc, records, _ = self.scan()
                self.assertEqual(rc, 1)
                self.assertEqual([(r["rule"], r["view"]) for r in records[:-1]],
                                 [("deny-list", "decoded")])
                self.write(content.replace(TERM[1:], "neutral"))
                self.assertEqual(self.scan()[0], 0)

    def test_percent_escape_after_percent(self):
        escaped = f"%%{ord(TERM[0]):02X}" + TERM[1:]
        self.write(escaped)
        self.assertEqual([(r["rule"], r["view"]) for r in self.scan()[1][:-1]],
                         [("deny-list", "decoded")])
        self.write(escaped.replace(TERM[1:], "neutral") + " %%30")
        self.assertEqual(self.scan()[0], 0)

    def test_opaque_boundary(self):
        chunk = "Rk9vXy9-" * 25
        self.write(chunk)
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([r["rule"] for r in records[:-1]], ["opaque"])
        self.assertNotIn(chunk, json.dumps(records))
        self.write(chunk[:-1])
        self.assertEqual(self.scan()[0], 0)

    def test_wrapped_opaque_body(self):
        chunk = "Rk9vXy9-" * 10
        self.write(f"prefix!\n{chunk}\n{chunk}\n{chunk}\n")
        rc, rows, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([(r["rule"], r["line"]) for r in rows[:-1]], [("opaque", 2)])
        self.write(f"{chunk}\n{chunk}\nordinary text\n{chunk}")
        self.assertEqual(self.scan()[0], 0)

    def test_wrapped_opaque_body_in_decoded_record(self):
        chunk = "Rk9vXy9-" * 10
        for data in (json.dumps({"blob": "\n".join([chunk] * 3)}),
                     "%0A".join([chunk] * 3),
                     json.dumps(json.dumps({"blob": "\n".join([chunk] * 3)}))):
            with self.subTest(data=data):
                self.write(data)
                self.assertEqual([(r["rule"], r["view"]) for r in self.scan()[1][:-1]],
                                 [("opaque", "decoded")])
        self.write(json.dumps({"blob": f"{chunk}\nnot a body\n{chunk}\n{chunk}"}))
        self.assertEqual(self.scan()[0], 0)

    def test_wrapped_standard_encoder_short_last_line(self):
        encoded = base64.encodebytes(bytes(range(150))).decode("ascii")
        lines = encoded.splitlines()
        self.assertEqual([len(line) for line in lines], [76, 76, 48])
        for rendered in (encoded, json.dumps({"blob": encoded})):
            with self.subTest(rendered=rendered):
                self.write(rendered)
                rc, rows, _ = self.scan("--unredacted")
                self.assertEqual(rc, 1)
                self.assertEqual([(row["rule"], row["match"]) for row in rows[:-1]],
                                 [("opaque", "".join(lines))])
        truncated = "\n".join(lines[:-1])
        for rendered in (truncated, json.dumps({"blob": truncated})):
            self.write(rendered)
            self.assertEqual(self.scan()[0], 0)

    def test_decoded_json_long_body_once(self):
        encoded = base64.encodebytes(bytes(index % 251 for index in range(285))).decode("ascii")
        self.assertEqual([len(line) for line in encoded.splitlines()], [76] * 5)
        self.write(json.dumps({"blob": encoded}))
        rc, rows, _ = self.scan("--unredacted")
        self.assertEqual(rc, 1)
        self.assertEqual([(row["rule"], row["match"]) for row in rows[:-1]],
                         [("opaque", "".join(encoded.splitlines()))])

    def test_base64_with_path_shaped_prefix(self):
        body = "rk9vXy9" * 30
        for prefix in ("/", "logs/"):
            with self.subTest(prefix=prefix):
                self.write(prefix + body)
                self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["opaque"])
        self.write("/" + "IndexedPath9/" * 20)
        self.assertEqual(self.scan()[0], 0)

    def test_long_hex_run_is_opaque(self):
        body = "7a1f4b2c" * 25
        self.write(body)
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["opaque"])
        self.write(body[:-1])
        self.assertEqual(self.scan()[0], 0)
        for low_diversity in ("f" * 200, "7a1F4b2" * 30):
            self.write(low_diversity)
            self.assertEqual(self.scan()[0], 0)

    def test_opaque_requires_digit_class(self):
        letters = "BravoxQz" * 30
        self.assertEqual(len(letters), 240)
        self.write(letters)
        self.assertEqual(self.scan()[0], 0)
        self.write(letters + "1")
        self.assertEqual([row["rule"] for row in self.scan()[1][:-1]], ["opaque"])

    def test_wrapped_opaque_requires_wide_consistent_lines(self):
        line = "Rk9vXy9-" * 10
        self.write("\n".join([line] * 3))
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["opaque"])
        forty = line[:40]
        self.write("\n".join([forty] * 5))
        self.assertEqual([r["rule"] for r in self.scan()[1][:-1]], ["opaque"])
        self.write("\n".join([forty[:-1]] * 6))
        self.assertEqual(self.scan()[0], 0)
        self.write("\n".join((line, line + "A123", line)))
        self.assertEqual(self.scan()[0], 0)
        self.write("\n".join(("Maple", "robin", "Node2", "Birch", "Page3") * 15))
        self.assertEqual(self.scan()[0], 0)

    def test_opaque_precision(self):
        chunk = "Rk9vXy9-" * 25
        self.write(chunk)
        self.assertEqual(self.scan()[0], 1)
        self.write("Z" * 220 + "\n" + "/" + "IndexedPath9/" * 20 + "\n"
                   + "source/" + "IndexedPath9/" * 20)
        self.assertEqual(self.scan()[0], 0)

    def test_unreadable_gzip_and_special_file(self):
        path = self.tree / "text.gz"
        for data in (b"", b"wrong data", gzip.compress(b"text")[:-2]):
            with self.subTest(data=data):
                path.write_bytes(data)
                rc, records, _ = self.scan()
                self.assertEqual(rc, 1)
                self.assertEqual([item["rule"] for item in records[:-1]], ["unreadable"])
        path.write_bytes(gzip.compress(b"text"))
        self.assertEqual(self.scan()[0], 0)
        os.mkfifo(self.tree / "pipe")
        self.assertEqual([item["rule"] for item in self.scan()[1][:-1]], ["unreadable"])

    def test_undecodable(self):
        path = self.tree / "sample.txt"
        for data in (b"valid\n\xffbad", b"valid\n\x00bad"):
            path.write_bytes(data)
            rc, records, _ = self.scan()
            self.assertEqual(rc, 1)
            self.assertEqual(records[0]["rule"], "undecodable")
            self.assertEqual(records[0]["line"], 2)
            self.assertEqual(records[-1]["bytes"], len(data))
        path.write_bytes("valid\nλ".encode())
        self.assertEqual(self.scan()[0], 0)

    def test_deny_list_required_and_waivable(self):
        self.write("ordinary")
        self.assertEqual(self.run_guard("--tree", self.tree)[0], 2)
        self.assertEqual(self.run_guard("--tree", self.tree, "--allow-empty-deny-list")[0], 0)
        another = self.root / "extra.txt"
        another.write_text(TERM, encoding="utf-8")
        self.deny.write_text("# comment only\n\n", encoding="utf-8")
        self.assertEqual(self.scan()[0], 2)
        self.assertEqual(self.scan("--allow-empty-deny-list")[0], 0)
        self.assertEqual(self.scan("--deny-list", another)[0], 2)
        self.assertEqual(self.scan("--deny-list", another, "--allow-empty-deny-list")[0], 0)
        self.deny.unlink()
        rc, _, error = self.scan()
        self.assertEqual(rc, 2)
        self.assertNotIn(str(self.deny), error)
        self.assertEqual(self.scan("--allow-empty-deny-list")[0], 2)

    def test_deny_entries_reject_controls(self):
        self.write(TERM)
        for control in ("\x00", "\t", "\r", "\x7f"):
            with self.subTest(control=control):
                self.deny.write_text(TERM[:2] + control + TERM[2:] + "\n", encoding="utf-8")
                rc, _, error = self.scan()
                self.assertEqual(rc, 2)
                self.assertIn("control", error)
                self.assertNotIn(TERM[:3], error)
        self.deny.write_bytes(TERM.encode() + b"\r\n")
        self.assertEqual(self.scan()[0], 1)

    def test_allow_and_deny_list_load_errors(self):
        self.write("ordinary")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 2)
        self.assertIn("allow list", self.scan("--allow-list", self.allow)[2])
        self.deny.unlink()
        rc, _, error = self.scan("--allow-empty-deny-list")
        self.assertEqual(rc, 2)
        self.assertIn("deny list", error)
        self.assertNotIn(str(self.deny), error)
        self.deny.write_text(TERM, encoding="utf-8")
        self.allow.write_text("", encoding="utf-8")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_missing_lists_are_distinct_from_invalid_encoding(self):
        self.write("ordinary")
        other = self.root / "other.txt"
        for kind, path in (("allow", self.allow), ("deny", other)):
            with self.subTest(kind=kind):
                rc, _, error = self.scan(f"--{kind}-list", path)
                self.assertEqual(rc, 2)
                self.assertIn(f"{kind} list file is missing", error)
                self.assertNotIn(str(path), error)
                path.write_bytes(b"\xff")
                rc, _, error = self.scan(f"--{kind}-list", path)
                self.assertEqual(rc, 2)
                self.assertIn(f"{kind} list could not be read as UTF-8", error)
                path.unlink()


    def test_empty_tree_requires_waiver(self):
        rc, results, _ = self.scan()
        self.assertEqual(rc, 2)
        self.assertEqual((results[-1]["scope"], results[-1]["files"]), ("tree", 0))
        self.assertEqual(self.scan("--allow-empty-scan")[0], 0)
        self.write("")
        self.assertEqual(self.scan()[0], 0)

    def test_tree_empty_directory_name(self):
        self.write("ordinary")
        directory = self.tree / TERM
        directory.mkdir()
        rc, rows, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([(r["rule"], r["surface"]) for r in rows[:-1]], [("deny-list", "name")])
        directory.rename(self.tree / "ordinary")
        self.assertEqual(self.scan()[0], 0)

    def test_redacted_names_and_keyed_digests(self):
        self.write("ordinary", name=os.fsdecode(b"near-\xff-private"))
        pane = "%" + "8813"
        self.write(pane)
        # Fix the two test keys to isolate the cause of the output difference.
        with patch.object(guard.os, "urandom", side_effect=[b"a" * 32, b"b" * 32]):
            first = self.scan()[1][:-1]
            second = self.scan()[1][:-1]
        self.assertEqual([r["rule"] for r in first], ["undecodable", "pane-id"])
        self.assertRegex(first[0]["file"], r"^<name:[0-9a-f]+>$")
        self.assertNotIn("near-", json.dumps(first))
        self.assertNotEqual(first[0]["file"], second[0]["file"])
        self.assertNotEqual(first[1]["digest"], second[1]["digest"])
        self.assertEqual(first[1]["file"], "sample.txt")
        self.assertNotIn(pane, json.dumps(first))
        (self.tree / os.fsdecode(b"near-\xff-private")).rename(self.tree / "neutral.txt")
        self.write("ordinary")
        self.assertEqual(self.scan()[0], 0)

    def test_symlink_target(self):
        link = self.tree / "shortcut"
        link.symlink_to(guard.HOME_PREFIX + "example")
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual((records[0]["rule"], records[0]["surface"]), ("home-path", "link"))
        link.unlink()
        link.symlink_to("local-target")
        self.assertEqual(self.scan()[0], 0)

    def test_symlink_allowlist_compares_complete_target(self):
        allowed = guard.HOME_PREFIX + "example/work"
        self.allow.write_text(allowed, encoding="utf-8")
        link = self.tree / "shortcut"
        for full in (allowed + " extra", allowed + "\n"):
            link.symlink_to(full)
            rc, rows, _ = self.scan("--allow-list", self.allow)
            self.assertEqual(rc, 1)
            self.assertEqual([(r["rule"], r["surface"]) for r in rows[:-1]], [("home-path", "link")])
            link.unlink()
        link.symlink_to(allowed)
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_git_range_audits_intermediate_commits_and_messages(self):
        self.init_git()
        (self.tree / "seed.txt").unlink()
        self.write(TERM, "legacy.txt")
        self.git("add", "-A")
        self.git("commit", "-m", "Older file")
        base = self.git("rev-parse", "HEAD")
        self.write(TERM)
        self.git("add", ".")
        self.git("commit", "-m", f"First change\n\n{TERM}")
        first = self.git("rev-parse", "HEAD")
        self.write("new text")
        self.git("add", ".")
        self.git("commit", "-m", "Second change")
        rc, all_records, _ = self.git_scan(f"{base}..HEAD")
        self.assertEqual(rc, 1)
        self.assertEqual(all_records[-1]["files"], 4)
        self.assertEqual(all_records[-1]["messages"], 2)
        self.assertEqual(all_records[-1]["review"], 4)
        self.assertEqual((all_records[-1]["scope"], all_records[-1]["partial"]), ("full-tree", False))
        rc, changed, _ = self.git_scan(f"{base}..HEAD", "--changed")
        self.assertEqual(rc, 1)
        self.assertEqual([(r["surface"], r["line"]) for r in changed[:-1]],
                         [("message", 3), ("content", 1)])
        self.assertEqual(changed[-1]["files"], 2)
        self.assertEqual((changed[-1]["scope"], changed[-1]["partial"]), ("changed-files", True))
        self.assertEqual(self.git_scan(f"{first}..HEAD", "--changed")[0], 0)

    def test_bad_git_range(self):
        base = self.init_git()
        self.git("commit", "--allow-empty", "-m", "Next")
        rc, results, _ = self.git_scan("absent..HEAD")
        self.assertEqual(rc, 1)
        self.assertEqual([r["rule"] for r in results[:-1]], ["incomplete-git"])
        self.assertEqual(self.git_scan(f"{base}..HEAD")[0], 0)

    def test_empty_git_range_requires_waiver(self):
        base = self.init_git()
        self.assertEqual(self.git_scan(f"{base}..HEAD")[0], 2)
        self.assertEqual(self.git_scan(f"{base}..HEAD", "--allow-empty-scan")[0], 0)
        self.git("commit", "--allow-empty", "-m", "Next")
        self.assertEqual(self.git_scan(f"{base}..HEAD")[0], 0)

    def test_full_git_range_rejects_empty_commit_tree(self):
        base = self.init_git()
        empty = self.git("mktree", input="")
        commit = self.git("commit-tree", empty, "-p", base, "-m", "Empty")
        full = self.git("rev-parse", f"{base}^{{tree}}")
        tip = self.git("commit-tree", full, "-p", commit, "-m", "Restore")
        rc, rows, _ = self.git_scan(f"{base}..{tip}")
        self.assertEqual(rc, 2)
        self.assertEqual((rows[-1]["commits"], rows[-1]["empty_trees"]), (2, 1))
        self.assertEqual(self.git_scan(f"{base}..{tip}", "--allow-empty-scan")[0], 0)
        self.git("commit", "--allow-empty", "-m", "Same tree")
        self.assertEqual(self.git_scan(f"{base}..HEAD")[0], 0)

    def test_git_resolved_endpoints_and_whole_history(self):
        base = self.init_git()
        self.git("branch", "base")
        self.git("commit", "--allow-empty", "-m", "Next")
        tip = self.git("rev-parse", "HEAD")
        rc, rows, _ = self.git_scan("..HEAD")
        self.assertEqual(rc, 0)
        self.assertEqual((rows[-1]["base"], rows[-1]["tip"], rows[-1]["commits"]), (None, tip, 2))
        rc, rows, _ = self.git_scan("base..HEAD", "--changed")
        self.assertEqual(rc, 0)
        self.assertEqual((rows[-1]["base"], rows[-1]["tip"], rows[-1]["commits"]), (base, tip, 1))
        self.assertEqual((rows[-1]["files"], rows[-1]["empty_trees"]), (0, 0))
        with self.assertRaises(SystemExit) as rejected:
            self.git_scan("..HEAD", "--changed")
        self.assertEqual(rejected.exception.code, 2)

    def test_annotated_tag_resolves_to_commit(self):
        base = self.init_git()
        self.git("commit", "--allow-empty", "-m", "Ordinary")
        self.git("tag", "-a", "sample", "-m", TERM)
        tip = self.git("rev-parse", "HEAD")
        rc, rows, _ = self.git_scan(f"{base}..sample")
        self.assertEqual(rc, 0)
        self.assertEqual(rows[-1]["tip"], tip)
        self.git("commit", "--allow-empty", "-m", TERM)
        self.git("tag", "-a", "next", "-m", "Ordinary")
        rc, rows, _ = self.git_scan(f"{tip}..next")
        self.assertEqual(rc, 1)
        self.assertEqual([row["surface"] for row in rows[:-1]], ["message"])

    def test_documented_escape_and_path_boundaries(self):
        escaped = f"%{ord(TERM[0]):02X}" + TERM[1:]
        escaped_percent = "%" + "25"
        for _ in range(guard.ENCODING_DEPTH - 1):
            escaped = escaped.replace("%", escaped_percent)
        self.write(escaped)
        self.assertEqual(self.scan()[0], 1)
        self.write(escaped.replace("%", escaped_percent))
        self.assertEqual(self.scan()[0], 0)

        path = guard.HOME_PREFIX + "example"
        self.allow.write_text(path, encoding="utf-8")
        self.write(f"[{path}]")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 1)
        self.write(f'"{path}"')
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

        for outside in (r"C:\Users\morrow\work", "/" + "HOME/morrow/work",
                        "%%2F" + "home" + "%%2F" + "quux", path[:3] + "\u200b" + path[3:]):
            with self.subTest(outside=outside):
                self.write(outside)
                self.assertEqual(self.scan()[0], 0)

    def test_deny_phrase_stays_within_physical_line(self):
        self.deny.write_text(f"{TERM} valley", encoding="utf-8")
        self.write(f"{TERM}\tvalley")
        self.assertEqual(self.scan()[0], 1)
        self.write(f"{TERM}\nvalley")
        self.assertEqual(self.scan()[0], 0)
        self.deny.write_text(f"{TERM}\n", encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)

    def test_git_ignores_repository_selection_environment(self):
        self.init_git()
        self.git("branch", "base")
        self.git("commit", "--allow-empty", "-m", TERM)
        other = self.root / "other"
        other.mkdir()
        self.git("-C", str(other), "init")
        (other / "seed.txt").write_text("ordinary", encoding="utf-8")
        self.git("-C", str(other), "add", ".")
        self.git("-C", str(other), "commit", "-m", "Base tree")
        self.git("-C", str(other), "branch", "base")
        self.git("-C", str(other), "commit", "--allow-empty", "-m", "Ordinary")
        overrides = (
            {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)},
            {"GIT_COMMON_DIR": str(other / ".git")},
            {"GIT_OBJECT_DIRECTORY": str(other / ".git/objects")},
        )
        for override in overrides:
            with self.subTest(variables=tuple(override)), patch.dict(os.environ, override):
                rc, rows, _ = self.git_scan("base..HEAD")
                self.assertEqual(rc, 1)
                self.assertEqual([r["surface"] for r in rows[:-1]], ["message"])
        with patch.dict(os.environ, GIT_DIR=str(self.tree / ".git"), GIT_WORK_TREE=str(self.tree)):
            self.assertEqual(self.git_scan("base..HEAD", repo=other)[0], 0)

    def test_git_ignores_replace_refs(self):
        base = self.init_git()
        tree = self.git("rev-parse", "HEAD^{tree}")
        private = self.git("commit-tree", tree, "-p", base, "-m", TERM)
        clean = self.git("commit-tree", tree, "-p", base, "-m", "Ordinary")
        self.git("replace", private, clean)
        rc, rows, _ = self.git_scan(f"{base}..{private}")
        self.assertEqual(rc, 1)
        self.assertEqual([r["surface"] for r in rows[:-1]], ["message"])
        self.git("replace", "-d", private)
        self.git("replace", clean, private)
        self.assertEqual(self.git_scan(f"{base}..{clean}")[0], 0)

    def test_changed_requires_ancestor(self):
        base = self.init_git()
        self.git("commit", "--allow-empty", "-m", "One history")
        tip = self.git("rev-parse", "HEAD")
        other = self.git("commit-tree", self.git("rev-parse", "HEAD^{tree}"), "-p", base,
                         "-m", "Other history")
        rc, results, _ = self.git_scan(f"{other}..{tip}", "--changed")
        self.assertEqual(rc, 1)
        self.assertEqual([r["rule"] for r in results[:-1]], ["incomplete-git"])
        self.assertEqual(self.git_scan(f"{base}..{tip}", "--changed")[0], 0)
        self.assertEqual(self.git_scan(f"{other}..{tip}")[0], 0)

    def test_git_empty_directory_name(self):
        base = self.init_git()
        empty = self.git("mktree", input="")
        for directory, expected in ((TERM, 1), ("ordinary", 0)):
            tree = self.git("mktree", input=f"040000 tree {empty}\t{directory}\n")
            tip = self.git("commit-tree", tree, "-p", base, "-m", "Fixture directory")
            for flags in (("--allow-empty-scan",), ("--changed",)):
                rc, results, _ = self.git_scan(f"{base}..{tip}", *flags)
                self.assertEqual(rc, expected)
                self.assertEqual(results[-1]["files"], 0)
                self.assertEqual([r["surface"] for r in results[:-1]], ["name"] * expected)

    def test_git_header_surfaces(self):
        base = self.init_git()
        tree = self.git("rev-parse", "HEAD^{tree}")
        for author, count in ((TERM, 3), ("Sample", 0)):
            tip = self.git("commit-tree", tree, "-p", base, "-m", "Header fixture", author=author)
            header, message = self.git("cat-file", "commit", tip).split("\n\n", 1)
            tip = self.git("hash-object", "-t", "commit", "-w", "--stdin",
                           input=f"{header}\nx-audit {author}\n\n{message}\n")
            rc, results, _ = self.git_scan(f"{base}..{tip}")
            self.assertEqual(rc, int(bool(count)))
            self.assertEqual([r["surface"] for r in results[:-1]], ["commit-header"] * count)

    def test_git_grafts(self):
        base = self.init_git()
        self.git("commit", "--allow-empty", "-m", "Next")
        grafts = self.tree / ".git/info/grafts"
        for content, expected in (("# control\n", 0), (self.git("rev-parse", "HEAD") + "\n", 1)):
            grafts.write_text(content, encoding="utf-8")
            rc, results, _ = self.git_scan(f"{base}..HEAD")
            self.assertEqual(rc, expected)
            self.assertEqual([r["rule"] for r in results[:-1]], ["incomplete-git"] * expected)

    def test_shallow_git(self):
        base = self.init_git()
        self.git("commit", "--allow-empty", "-m", "Next")
        shallow = self.root / "shallow"
        self.git("clone", "--depth=1", self.tree.as_uri(), str(shallow))
        rc, results, _ = self.git_scan("HEAD..HEAD", "--allow-empty-scan", repo=shallow)
        self.assertEqual(rc, 1)
        self.assertEqual([r["rule"] for r in results[:-1]], ["incomplete-git"])
        self.assertEqual(self.git_scan(f"{base}..HEAD")[0], 0)

    def test_builder_is_deterministic_and_guard_checks_output(self):
        files = build_fixtures.build(self.tree, self.allow, seed=304)
        initial = [p.read_bytes() for p in (*files, self.allow)]
        build_fixtures.build(self.tree, self.allow, seed=304)
        self.assertEqual([p.read_bytes() for p in (*files, self.allow)], initial)
        build_fixtures.build(self.tree, self.allow, seed=305)
        self.assertNotEqual([p.read_bytes() for p in (*files, self.allow)], initial)
        rc, rejected, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual({r["rule"] for r in rejected[:-1]}, {"uuid", "request-id", "home-path"})
        rc, records, _ = self.scan("--allow-list", self.allow)
        self.assertEqual(rc, 0)
        self.assertEqual(records[-1]["files"], 2)
        self.assertGreater(records[-1]["bytes"], 0)

    def test_every_generated_id_is_detected_without_allow_list(self):
        fixture_dir = self.root / "fixtures"
        build_fixtures.build(fixture_dir, self.allow, seed=304, day=date(2050, 2, 3))
        self.write(self.allow.read_text(encoding="utf-8"))
        rc, results, _ = self.scan("--unredacted")
        self.assertEqual(rc, 1)
        expected = set(self.allow.read_text(encoding="utf-8").splitlines())
        self.assertEqual({r["match"] for r in results[:-1]}, expected)
        self.assertTrue(any(r["rule"] == "codex-id" for r in results[:-1]))
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 0)

    def test_mutation_runner_requires_passing_baseline(self):
        def fail():
            self.fail("Constructed baseline failure")

        def check(baseline):
            output = io.StringIO()
            mutations = [("sample", "test_uuid", suppress_finding(rule="uuid"))]
            rc = run_mutations(unittest.TestSuite([unittest.FunctionTestCase(baseline)]),
                               mutations, output)
            return rc, output.getvalue()

        rc, log = check(fail)
        self.assertEqual(rc, 1)
        self.assertIn("Unmutated tests failed", log)
        self.assertNotIn("KILLED", log)
        rc, log = check(lambda: None)
        self.assertEqual(rc, 0)
        self.assertIn("Mutants killed: 1/1", log)

    def test_builder_record_contract(self):
        files = build_fixtures.build(self.tree, self.allow, seed=304)
        parts = []
        for file in files:
            with gzip.open(file, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            self.assertTrue(all(row.keys() == {"file", "rec"} for row in rows))
            parts.append(rows)
        claude, codex = parts
        self.assertEqual(len(claude), 8)
        self.assertEqual(len({row["rec"]["requestId"] for row in claude}), 6)
        self.assertEqual(len({row["file"] for row in codex}), 2)
        self.assertEqual({row["rec"]["type"] for row in codex},
                         {"session_meta", "turn_context", "event_msg"})
        for row in codex:
            rec = row["rec"]
            if rec["type"] == "event_msg":
                self.assertEqual(rec["payload"]["type"], "token_count")
                self.assertIn("total_token_usage", rec["payload"]["info"])
                self.assertIn("primary", rec["payload"]["rate_limits"])


RULE_TESTS = {
    "uuid": "test_uuid",
    "request-id": "test_request_id",
    "codex-id": "test_codex_id",
    "message-id": "test_request_boundaries_and_other_ids",
    "tool-id": "test_request_boundaries_and_other_ids",
    "home-path": "test_home_path",
    "pane-id": "test_pane_id",
    "deny-list": "test_deny_list_whole_word_and_redaction",
    "opaque": "test_opaque_boundary",
    "unreadable": "test_unreadable_gzip_and_special_file",
    "undecodable": "test_undecodable",
    "incomplete-git": "test_bad_git_range",
}


def suppress_finding(*, rule=None, surface=None):
    record = guard.Audit.record

    def filtered(self, found_rule, location, found_surface, *args, **kwargs):
        if found_rule != rule and found_surface != surface:
            record(self, found_rule, location, found_surface, *args, **kwargs)

    return patch.object(guard.Audit, "record", filtered)


def replace_pattern(rule, pattern):
    setting = "IDENTIFIERS" if rule == "pane-id" else "PREFIXED_IDS"
    return patch.object(guard, setting, tuple(
        (name, re.compile(pattern, re.I) if name == rule else original)
        for name, original in getattr(guard, setting)
    ))


def only_raw_deny_entries(entries):
    return [(term.lower(), re.compile(rf"(?=({re.escape(term)}))", re.I), (source, line))
            for term, source, line in entries]


def baseline_passes(suite, stream):
    result = unittest.TextTestRunner(stream=stream).run(suite)
    if not result.wasSuccessful() or result.skipped:
        print("Unmutated tests failed or were skipped. No mutant results credited.", file=stream)
        return False
    return True


def run_mutations(baseline, mutations, stream):
    if not baseline_passes(baseline, stream):
        return 1
    failures = 0
    for disabled, method, mutation in mutations:
        with mutation:
            output = io.StringIO()
            suite = unittest.TestSuite([PublicationGuard(method)])
            result = unittest.TextTestRunner(stream=output).run(suite)
        if result.failures and not result.errors:
            failure = next(line for line in result.failures[0][1].splitlines()
                           if line.startswith("AssertionError"))
            print(f"KILLED {disabled}: {method} ({len(result.failures)} assertions): {failure}", file=stream)
        else:
            failures += 1
            print(f"NOT KILLED {disabled}: {output.getvalue()}", file=stream)
    print(f"Mutants killed: {len(mutations) - failures}/{len(mutations)}", file=stream)
    return int(bool(failures))


def mutation_check():
    original_uuid = guard.uuid_matches
    original_wrapped = guard.wrapped_bodies
    original_decoded_wrapped = guard.decoded_wrapped
    original_home = guard.home_tokens
    original_deny = guard.deny_patterns
    original_list_entries = guard.list_entries
    original_load_list = guard.load_list
    original_deny_matches = guard.deny_matches
    original_opaque_path = guard.opaque_path
    original_init = guard.Audit.__init__
    original_summary = guard.Audit.summary
    original_text = guard.Audit.text
    original_git_environment = guard.git_environment

    def only_plain_uuids(line):
        return (result for result in original_uuid(line)
                if result[0] != "codex-id" or len(result[1]) == 32)

    def short_paths(line):
        for rule, value, column, entry in original_home(line):
            yield rule, re.split(r"[,()\[\] ]", value, maxsplit=1)[0], column, entry

    class PrefixAllow(set):
        def __contains__(self, value):
            return any(value.startswith(allowed) for allowed in self)

    def prefix_allow(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.allowed_ids = PrefixAllow(self.allowed_ids)

    def no_overlaps(entries):
        return [(prefix, re.compile(pattern.pattern[3:-1], re.I), entry)
                for prefix, pattern, entry in original_deny(entries)]

    def without_endpoints(self):
        self.base = self.tip = None
        original_summary(self)

    def permit_missing_deny(path, kind):
        return [] if kind == "deny" and not path.exists() else original_load_list(path, kind)

    def without_compact_pair(line):
        return (result for result in original_uuid(line)
                if result[0] != "codex-id" or len(result[1]) != 64)

    def without_uuid_left_extension(line):
        for rule, value, column, entry in original_uuid(line):
            if rule == "uuid":
                first = guard.DELIMITED_UUID.search(value).start()
                value, column = value[first:], column + first
            yield rule, value, column, entry

    def without_short_final_line(lines):
        for number, body, context in original_wrapped(lines):
            first, *_, last = context.splitlines()
            if len(first) == len(last):
                yield number, body, context

    def duplicate_decoded_interior(view):
        yield from original_decoded_wrapped(view)
        for _, body, _ in original_wrapped(enumerate(view.splitlines(), 1)):
            yield "opaque", body, 1, None

    def partial_link_target(self, line, location, surface, number, member=None):
        if surface == "link":
            line = line.split(maxsplit=1)[0]
        original_text(self, line, location, surface, number, member)

    def old_case_prefilter(line, deny):
        lower = guard.normalized(line).lower()
        return original_deny_matches(line, [entry for entry in deny if entry[0] in lower])

    def old_missing_error(path, kind):
        if not path.exists():
            raise ValueError(f"The {kind} list could not be read as UTF-8.")
        return original_load_list(path, kind)

    def keep_git_override(variable):
        def inherited():
            env = original_git_environment()
            if variable in os.environ:
                env[variable] = os.environ[variable]
            return env

        return patch.object(guard, "git_environment", inherited)

    def count_empty_diff_as_tree(self):
        if self.scope == "changed-files" and not self.files:
            self.empty_trees += 1
        original_summary(self)

    mutations = [(rule, method, suppress_finding(rule=rule)) for rule, method in RULE_TESTS.items()]
    mutations.extend([
        ("uuid-boundary", "test_uuid_boundaries_and_separators",
         patch.object(guard, "DELIMITED_UUID", re.compile(r"(?<![0-9a-f])" + guard.UUID, re.I))),
        ("compact-version", "test_codex_id",
         patch.object(guard, "COMPACT_UUID", re.compile(r"[0-9a-f]{32}", re.I))),
        ("request-boundary", "test_request_boundaries_and_other_ids",
         replace_pattern("request-id", r"\breq_" + guard.ID_SUFFIX)),
        ("pane-boundary", "test_pane_boundaries",
         replace_pattern("pane-id", r"(?<![\w%])%[0-9]+(?![\w%$]|\.[0-9])")),
        ("deny-boundary", "test_deny_letter_boundaries",
         patch.object(guard, "letter_boundary", lambda a, b: not re.fullmatch(r"\w\w", a + b))),
        ("dash-encoded", "test_dash_encoded_deny_list",
         patch.object(guard, "deny_patterns", only_raw_deny_entries)),
        ("whole-line-decoding", "test_repeated_whole_line_decoding",
         patch.object(guard, "text_views", lambda line: iter((line,)))),
        ("member-boundary", "test_gzip_member_boundaries", suppress_finding(surface="gzip-member")),
        ("gzip-header", "test_gzip_records_each_member_name", suppress_finding(surface="gzip-name")),
        ("commit-header", "test_git_header_surfaces", suppress_finding(surface="commit-header")),
        ("empty-range-refusal", "test_empty_git_range_requires_waiver",
         patch.object(guard.Audit, "empty", lambda self: False)),
        ("git-environment", "test_git_ignores_repository_selection_environment",
         patch.object(guard, "git_environment", lambda: dict(os.environ))),
        ("empty-full-commit-tree", "test_full_git_range_rejects_empty_commit_tree",
         patch.object(guard.Audit, "empty", lambda self: not self.commits)),
        ("complete-home-token", "test_home_path_punctuation_and_quoted_space",
         patch.object(guard, "home_tokens", short_paths)),
        ("underscore-pane", "test_underscore_pane_in_filename",
         replace_pattern("pane-id", r"(?:(?<![\w%])|(?<=-t)|(?<=\bpane))%[0-9]+(?![\w%$]|\.[0-9])")),
        ("compact-token", "test_compact_extended_tokens",
         patch.object(guard, "uuid_matches", only_plain_uuids)),
        ("wrapped-opaque", "test_wrapped_opaque_body",
         patch.object(guard, "BASE64_LINE", re.compile(r"(?!)"))),
        ("opaque-precision", "test_opaque_precision",
         patch.object(guard, "opaque_body", lambda value: len(value.rstrip("=")) >= 200)),
        ("exact-id-allowlist", "test_allow_id_is_exact", patch.object(guard.Audit, "__init__", prefix_allow)),
        ("gzip-extra", "test_gzip_extra_field_is_reported", suppress_finding(surface="gzip-extra")),
        ("gzip-comment", "test_gzip_comment_is_reported", suppress_finding(surface="gzip-comment")),
        ("empty-directory-name", "test_tree_empty_directory_name", suppress_finding(surface="name")),
        ("git-ignore-replace", "test_git_ignores_replace_refs", patch.object(guard, "GIT_OPTIONS", ())),
        ("overlap-same-entry", "test_overlapping_occurrences_of_one_deny_entry",
         patch.object(guard, "deny_patterns", no_overlaps)),
        ("mutation-baseline", "test_mutation_runner_requires_passing_baseline",
         patch.object(sys.modules[__name__], "baseline_passes", lambda suite, stream: True)),
        ("resolved-endpoints", "test_git_resolved_endpoints_and_whole_history",
         patch.object(guard.Audit, "summary", without_endpoints)),
        ("adjacent-percent", "test_percent_escape_after_percent",
         patch.object(guard, "decoded_percent", lambda text: (
             "%%".join(guard.unquote(part, errors="surrogateescape") for part in text.split("%%")),
         ))),
        ("deny-control-entries", "test_deny_entries_reject_controls",
         patch.object(guard, "list_entries", lambda path, **kwargs: original_list_entries(path))),
        ("missing-deny-list", "test_allow_and_deny_list_load_errors",
         patch.object(guard, "load_list", permit_missing_deny)),
        ("allow-list-message", "test_allow_and_deny_list_load_errors",
         patch.object(guard, "load_list", lambda path, kind: original_load_list(path, "deny"))),
        ("compact-alphabetic-neighbors", "test_compact_nonhex_neighbors_and_pair",
         patch.object(guard, "HEX_TOKEN", re.compile(r"(?<![a-z0-9])[0-9a-f]{32,}(?![a-z0-9])", re.I))),
        ("compact-id-pair", "test_compact_nonhex_neighbors_and_pair",
         patch.object(guard, "uuid_matches", without_compact_pair)),
        ("decoded-wrap", "test_wrapped_opaque_body_in_decoded_record",
         patch.object(guard, "decoded_wrapped", lambda view: ())),
        ("whole-link-target", "test_symlink_allowlist_compares_complete_target",
         patch.object(guard.Audit, "text", partial_link_target)),
        ("complete-format-directive", "test_pane_date_suffix_is_not_a_format_directive",
         replace_pattern("pane-id", r"(?:(?<![\w%])|(?<=_)|(?<=-t)|(?<=\bpane))%[0-9]+(?![\w%$]|\.[0-9])")),
        ("opaque-path-prefix", "test_base64_with_path_shaped_prefix",
         patch.object(guard, "opaque_path", lambda value: value.startswith("/") or original_opaque_path(value))),
        ("long-hex", "test_long_hex_run_is_opaque",
         patch.object(guard, "HEX_RUN", re.compile(r"(?!)"))),
        ("opaque-wrap-minimum-width", "test_wrapped_opaque_requires_wide_consistent_lines",
         patch.object(guard, "MIN_WRAP_WIDTH", 1)),
        ("macos-home-prefix-case", "test_macos_home_prefix_case_and_exact_allowlist",
         patch.object(guard, "HOME_START", re.compile(guard.HOME_START.pattern.replace(
             "|" + re.escape(guard.MACOS_HOME.upper()), "")))),
        ("deny-case-prefilter", "test_deny_prefilter_matches_unicode_case_variants",
         patch.object(guard, "deny_matches", old_case_prefilter)),
        ("missing-list-diagnostic", "test_missing_lists_are_distinct_from_invalid_encoding",
         patch.object(guard, "load_list", old_missing_error)),
        ("git-common-dir-override", "test_git_ignores_repository_selection_environment",
         keep_git_override("GIT_COMMON_DIR")),
        ("git-object-dir-override", "test_git_ignores_repository_selection_environment",
         keep_git_override("GIT_OBJECT_DIRECTORY")),
        ("empty-diff-is-not-empty-tree", "test_git_resolved_endpoints_and_whole_history",
         patch.object(guard.Audit, "summary", count_empty_diff_as_tree)),
        ("short-final-wrap-line", "test_wrapped_standard_encoder_short_last_line",
         patch.object(guard, "wrapped_bodies", without_short_final_line)),
        ("uuid-left-extension", "test_uuid_left_extension_precedes_allowlist",
         patch.object(guard, "uuid_matches", without_uuid_left_extension)),
        ("opaque-digit-class", "test_opaque_requires_digit_class",
         patch.object(guard, "BASE64_CLASSES", guard.BASE64_CLASSES[:-1])),
        ("opaque-hex-diversity", "test_long_hex_run_is_opaque",
         patch.object(guard, "MIN_HEX_DISTINCT", 1)),
        ("macos-home-unrestricted-case", "test_macos_home_prefix_case_and_exact_allowlist",
         patch.object(guard, "HOME_START", re.compile(guard.HOME_START.pattern, re.I))),
        ("printf-complete-directive", "test_complete_printf_directives_with_modifiers",
         patch.object(guard, "PRINTF_DIRECTIVE", re.compile(
             r"%[0-9]+(?:\.[0-9]+|\$(?:[0-9]+)?(?:\.[0-9]+)?)[diouxXeEfFgGaAcCsSpn](?!\w)"))),
        ("duplicate-decoded-json-body", "test_decoded_json_long_body_once",
         patch.object(guard, "decoded_wrapped", duplicate_decoded_interior)),
    ])
    for rule, prefix in guard.PREFIXES[3:]:
        method = "test_" + rule.replace("-", "_") + "_boundary"
        mutations.append((rule + "-boundary", method, replace_pattern(rule, r"\b" + prefix + "_" + guard.ID_SUFFIX)))
    baseline = unittest.defaultTestLoader.loadTestsFromTestCase(PublicationGuard)
    return run_mutations(baseline, mutations, sys.stdout)


if __name__ == "__main__":
    if sys.argv[1:] == ["--mutation-check"]:
        sys.exit(mutation_check())
    unittest.main()
