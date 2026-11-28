import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
            files=1, bytes=len(value.encode()), commits=0, messages=0, hard=0, review=0,
        )])

    def test_uuid(self):
        value = "-".join(("dd5aabc4", "c2df", "4276", "8111", "abcddcba3210"))
        self.identifier_twin("uuid", value.upper(), value)

    def test_request_id(self):
        value = "req_" + "4ebcf1" * 4
        self.identifier_twin("request-id", value)

    def test_codex_id(self):
        value = "01" + "ac1234" * 5
        self.identifier_twin("codex-id", value)

    def test_home_path(self):
        self.identifier_twin("home-path", guard.HOME_PREFIX + "example/sample")
        self.write(guard.HOME_PREFIX + "example/sample-secret")
        self.assertEqual(self.scan("--allow-list", self.allow)[0], 1)

    def test_pane_id(self):
        pane = "%" + "6281"
        self.identifier_twin("pane-id", pane)
        self.write(f"tmux-message send {pane} foo\nactive pane: {pane}\n")
        self.assertEqual([record["rule"] for record in self.scan()[1][:-1]], ["pane-id"] * 2)
        self.write('50% done, 15%2, escaped %%30, %02d, %10.2f, %1$s and #{pane_id}')
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
        _, raw, _ = self.scan("--unredacted")
        self.assertEqual(raw[1]["context"], f"known {TERM.upper()}.")
        (self.tree / f"{TERM}.txt").rename(self.tree / "sample.txt")
        self.write(f"x{TERM} {TERM}2 {TERM}_suffix")
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
        self.assertEqual(records[0]["line"], 2)
        self.assertEqual(records[0]["rule"], "deny-list")
        self.assertEqual(records[-1]["bytes"], len(first) + len(second))
        path.write_bytes(gzip.compress(first) + gzip.compress(b"other\n"))
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
        self.assertEqual((records[0]["surface"], records[0]["line"]), ("gzip-name", 2))
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
        self.assertEqual(self.run_guard("--tree", self.tree)[0], 2)
        self.assertEqual(self.run_guard("--tree", self.tree, "--allow-empty-deny-list")[0], 0)
        self.deny.write_text("# comment only\n\n", encoding="utf-8")
        self.assertEqual(self.scan()[0], 2)
        self.assertEqual(self.scan("--allow-empty-deny-list")[0], 0)
        self.deny.unlink()
        rc, _, error = self.scan()
        self.assertEqual(rc, 2)
        self.assertNotIn(str(self.deny), error)
        self.assertEqual(self.scan("--allow-empty-deny-list")[0], 0)

    def test_symlink_target(self):
        link = self.tree / "shortcut"
        link.symlink_to(guard.HOME_PREFIX + "example")
        rc, records, _ = self.scan()
        self.assertEqual(rc, 1)
        self.assertEqual((records[0]["rule"], records[0]["surface"]), ("home-path", "link"))
        link.unlink()
        link.symlink_to("local-target")
        self.assertEqual(self.scan()[0], 0)

    @unittest.skipUnless(shutil.which("git"), "Git is needed for commit range tests")
    def test_git_range_audits_intermediate_commits_and_messages(self):
        repo = self.tree
        env = dict(os.environ, HOME=str(self.root), XDG_CONFIG_HOME=str(self.root),
                   GIT_CONFIG_NOSYSTEM="1")

        def git(*args):
            return subprocess.check_output([
                "git", "-C", str(repo), "-c", "user.name=Sample",
                "-c", "user.email=sample@example.invalid", *args,
            ], stderr=subprocess.STDOUT, env=env).decode().strip()

        git("init")
        self.write(TERM, "legacy.txt")
        git("add", ".")
        git("commit", "-m", "Base tree")
        base = git("rev-parse", "HEAD")
        self.write(TERM)
        git("add", ".")
        git("commit", "-m", f"First change\n\n{TERM}")
        first = git("rev-parse", "HEAD")
        self.write("new text")
        git("add", ".")
        git("commit", "-m", "Second change")
        args = ("--deny-list", self.deny, "--repo", repo, "--git-range")
        rc, all_records, _ = self.run_guard(*args, f"{base}..HEAD")
        self.assertEqual(rc, 1)
        self.assertEqual(all_records[-1]["files"], 4)
        self.assertEqual(all_records[-1]["messages"], 2)
        self.assertEqual(all_records[-1]["review"], 4)
        rc, changed, _ = self.run_guard(*args, f"{base}..HEAD", "--changed")
        self.assertEqual(rc, 1)
        self.assertEqual([(r["surface"], r["line"]) for r in changed[:-1]],
                         [("message", 3), ("content", 1)])
        self.assertEqual(changed[-1]["files"], 2)
        self.assertEqual(self.run_guard(*args, f"{first}..HEAD", "--changed")[0], 0)

    def test_bad_git_range(self):
        self.assertEqual(self.run_guard(
            "--deny-list", self.deny, "--repo", self.tree, "--git-range", "absent..HEAD",
        )[0], 1)

    def test_builder_is_deterministic_and_guard_checks_output(self):
        files = build_fixtures.build(self.tree, self.allow, seed=304)
        initial = [p.read_bytes() for p in (*files, self.allow)]
        build_fixtures.build(self.tree, self.allow, seed=304)
        self.assertEqual([p.read_bytes() for p in (*files, self.allow)], initial)
        build_fixtures.build(self.tree, self.allow, seed=305)
        self.assertNotEqual([p.read_bytes() for p in (*files, self.allow)], initial)
        self.assertEqual(self.scan()[0], 1)
        rc, records, _ = self.scan("--allow-list", self.allow)
        self.assertEqual(rc, 0)
        self.assertEqual(records[-1]["files"], 2)
        self.assertGreater(records[-1]["bytes"], 0)

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


MUTATIONS = {
    "uuid": "test_uuid",
    "request-id": "test_request_id",
    "codex-id": "test_codex_id",
    "home-path": "test_home_path",
    "pane-id": "test_pane_id",
    "deny-list": "test_deny_list_whole_word_and_redaction",
    "dash-encoded": "test_dash_encoded_deny_list",
    "unreadable": "test_unreadable_gzip_and_special_file",
    "undecodable": "test_undecodable",
    "incomplete-git": "test_bad_git_range",
}


def mutation_check():
    failed = []
    for disabled, method in MUTATIONS.items():
        original = guard.Audit.record

        def record(self, rule, *args, **kwargs):
            if rule != disabled:
                original(self, rule, *args, **kwargs)


        def match_original_terms(entries):
            # Removing the variant branch still matches the exact raw terms.
            source = "|".join(map(guard.re.escape, sorted(entries)))
            return guard.re.compile(rf"(?<!\w)(?:{source})(?!\w)", guard.re.I)

        mutation = (patch.object(guard, "deny_patterns", match_original_terms)
                    if disabled == "dash-encoded" else patch.object(guard.Audit, "record", record))
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
    print(f"Mutants killed: {len(MUTATIONS) - len(failed)}/{len(MUTATIONS)}")
    return bool(failed)


if __name__ == "__main__":
    if sys.argv[1:] == ["--mutation-check"]:
        sys.exit(mutation_check())
    unittest.main()
