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
        self.git("commit", "--allow-empty", "-m", "Base tree")
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

    def test_request_id(self):
        value = "req_" + "4ebcf1" * 4
        self.identifier_twin("request-id", value)

    def test_codex_id(self):
        value = "".join(("02dd5aabc4a9", "7c2d", "a111", "abcddcba3210"))
        self.identifier_twin("codex-id", value)
        for ordinary in (value[:12] + "0" + value[13:], value[:16] + "d" + value[17:], "f" + value):
            with self.subTest(ordinary=ordinary):
                self.write(ordinary)
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

    def test_opaque_boundary(self):
        chunk = "Rk9vXy9-" * 25
        self.write(chunk)
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual([r["rule"] for r in records[:-1]], ["opaque"])
        self.assertNotIn(chunk, json.dumps(records))
        self.write(chunk[:-1])
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
        self.assertEqual(self.scan("--allow-empty-deny-list")[0], 0)

    def test_empty_tree_requires_waiver(self):
        rc, results, _ = self.scan()
        self.assertEqual(rc, 2)
        self.assertEqual((results[-1]["scope"], results[-1]["files"]), ("tree", 0))
        self.assertEqual(self.scan("--allow-empty-scan")[0], 0)
        self.write("")
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

    def test_git_range_audits_intermediate_commits_and_messages(self):
        self.init_git()
        self.write(TERM, "legacy.txt")
        self.git("add", ".")
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
            for flags in ((), ("--changed",)):
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
    return patch.object(guard, "IDENTIFIERS", tuple(
        (name, re.compile(pattern, re.I) if name == rule else original)
        for name, original in guard.IDENTIFIERS
    ))


def only_raw_deny_entries(entries):
    return [(term.lower(), re.compile(rf"(?=({re.escape(term)}))", re.I), (source, line))
            for term, source, line in entries]


def mutation_check():
    mutations = [(rule, method, suppress_finding(rule=rule)) for rule, method in RULE_TESTS.items()]
    mutations.extend([
        ("uuid-boundary", "test_uuid_boundaries_and_separators",
         replace_pattern("uuid", r"(?<![0-9a-f])" + guard.UUID)),
        ("compact-version", "test_codex_id",
         replace_pattern("codex-id", r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")),
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
    ])
    failed = []
    for disabled, method, mutation in mutations:
        with mutation:
            output = io.StringIO()
            suite = unittest.TestSuite([PublicationGuard(method)])
            result = unittest.TextTestRunner(stream=output).run(suite)
        if result.failures and not result.errors:
            failure = result.failures[0][1].strip().splitlines()[-1]
            print(f"KILLED {disabled}: {method} ({len(result.failures)} assertions): {failure}")
        else:
            failed.append(disabled)
            print(f"NOT KILLED {disabled}: {output.getvalue()}")
    print(f"Mutants killed: {len(mutations) - len(failed)}/{len(mutations)}")
    return bool(failed)


if __name__ == "__main__":
    if sys.argv[1:] == ["--mutation-check"]:
        sys.exit(mutation_check())
    unittest.main()
