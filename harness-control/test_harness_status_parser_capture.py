#!/usr/bin/env python3
"""Claude snapshot/parser conformance; --mutation-check kills one mutant per test.

All inputs and HOME directories are synthetic. No live harness configuration
or private session state is read or installed.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/_shared/hooks/capture-claude-status.sh"
FIXTURE = json.loads((ROOT / "harness-control/fixtures/claude-statusline.json").read_text())
SID = FIXTURE["session_id"]
NOW = 2000000000


def default_parser_module():
    return ROOT / "harness-control/harness_status.py"


MODULE = Path(os.environ["HARNESS_STATUS_TEST_MODULE"]) if os.environ.get(
    "HARNESS_STATUS_TEST_MODULE"
) else default_parser_module()


def load_module(path):
    spec = importlib.util.spec_from_file_location("harness_status_test_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARSER = load_module(MODULE)
SCRIPT = Path(os.environ.get("HARNESS_STATUS_TEST_SCRIPT", SCRIPT))


def snapshot():
    result = copy.deepcopy(FIXTURE)
    result.update(schema_version=1, observed_at=NOW, cwd=FIXTURE["workspace"]["current_dir"])
    return result


class ParserTests(unittest.TestCase):
    def test_status_fields(self):
        result = PARSER.parse_claude_status(snapshot(), SID)
        self.assertEqual(result, {
            "state": "available", "source": "claude_statusline", "provider": "anthropic",
            "observed_at": NOW, "session_id": SID, "cwd": "/example/worktree",
            "model": {"id": "claude-example", "display_name": "Example"},
            "context_window": {"size_tokens": 200000, "used_percentage": 25.5, "remaining_percentage": 74.5},
        })
        self.assertNotIn("transcript_path", result)

    def test_envelope_rejection(self):
        good = snapshot()
        self.assertEqual(PARSER.parse_claude_status(good, SID)["state"], "available")
        for value in (None, [], {}, {**good, "schema_version": True}, {**good, "schema_version": 2}):
            self.assertEqual(PARSER.parse_claude_status(value, SID)["reason"], "invalid_snapshot")
        self.assertEqual(PARSER.parse_claude_status(good, "../escape")["reason"], "invalid_session_id")
        self.assertEqual(PARSER.parse_claude_status(good, "00000000-0000-4000-8000-000000000000").get("reason"), "session_mismatch")
        for value in (None, True, -1, float("nan"), float("inf"), 10**400, 253402300800):
            self.assertEqual(PARSER.parse_claude_status({**good, "observed_at": value}, SID)["reason"], "missing_observation_time")
        self.assertEqual(PARSER.parse_claude_usage([], SID)["state"], "unavailable")

    def test_unknown_fields(self):
        data = snapshot()
        data.update(cwd=[], model=[], context_window=None, rate_limits=None)
        result = PARSER.parse_claude_status(data, SID)
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["model"], {"id": None, "display_name": None})
        self.assertIsNone(result["cwd"])
        self.assertEqual(result["context_window"], {"size_tokens": None, "used_percentage": None, "remaining_percentage": None})
        result = PARSER.parse_claude_usage(data, SID)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(len(result["windows"]), 3)
        for window in result["windows"]:
            self.assertIsNone(window["remaining_percentage"])

    def test_string_bounds(self):
        data = snapshot()
        data.update(cwd='x' * 4097, model={'id': 'x' * 4097, 'display_name': 'x' * 4096})
        result = PARSER.parse_claude_status(data, SID)
        self.assertIsNone(result['cwd'])
        self.assertIsNone(result['model']['id'])
        self.assertEqual(len(result['model']['display_name']), 4096)

    def test_percent_fallback(self):
        data = snapshot()
        for context, expected in (({"used_percentage": 0}, (0, 100)), ({"remaining_percentage": 0}, (100, 0)), ({"used_percentage": 12.5}, (12.5, 87.5))):
            data["context_window"] = context
            result = PARSER.parse_claude_status(data, SID)["context_window"]
            self.assertEqual((result["used_percentage"], result["remaining_percentage"]), expected)

    def test_invalid_numeric_fields(self):
        data = snapshot()
        self.assertEqual(PARSER.parse_claude_status(data, SID)["context_window"]["remaining_percentage"], 74.5)
        for value in (True, "10", -1, 101, float("nan"), float("inf"), 10**400):
            data["context_window"] = {"used_percentage": value, "remaining_percentage": value, "context_window_size": False}
            result = PARSER.parse_claude_status(data, SID)["context_window"]
            self.assertEqual(result, {"size_tokens": None, "used_percentage": None, "remaining_percentage": None})

    def test_usage_fields_and_overage(self):
        result = PARSER.parse_claude_usage(snapshot(), SID, now=NOW)
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["observed_at"], NOW)
        self.assertEqual([(w["bucket"], w["used_percentage"], w["remaining_percentage"], w["resets_at"]) for w in result["windows"]], [
            ("five_hour", 0, 100, 2000000100), ("seven_day", 42.5, 57.5, 2000600000), ("spend_limit", 105, 0, 2000700000)])
        self.assertEqual(result["windows"][0]["scope"], "provider_subscription")
        self.assertEqual(result["windows"][2]["scope"], "gateway_spend_limit")

    def test_expired_and_missing_windows(self):
        data = snapshot()
        data["rate_limits"] = {"five_hour": data["rate_limits"]["five_hour"], "unknown_bucket": {"used_percentage": 0, "resets_at": NOW + 900}}
        self.assertEqual(PARSER.parse_claude_usage(data, SID, now=NOW)["state"], "available")
        result = PARSER.parse_claude_usage(data, SID, now=2000000100)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["windows"][0]["reason"], "window_expired")
        self.assertIsNone(result["windows"][0]["used_percentage"])
        self.assertEqual(len(result["windows"]), 3)
        data["observed_at"] = 2000000100
        self.assertEqual(PARSER.parse_claude_usage(data, SID)["state"], "unavailable")

    def test_usage_invalid_fields(self):
        data = snapshot()
        self.assertEqual(PARSER.parse_claude_usage(data, SID)["state"], "available")
        for value in (True, "10", -1, float("nan"), float("inf"), 10**400, 253402300800):
            data["rate_limits"] = {"five_hour": {"used_percentage": 20, "resets_at": value}}
            self.assertEqual(PARSER.parse_claude_usage(data, SID)["state"], "unavailable")
            self.assertEqual(PARSER.parse_claude_usage(data, SID, now=value)["reason"], "invalid_current_time")
        data["rate_limits"] = {"five_hour": {"used_percentage": True, "resets_at": NOW + 100}}
        self.assertEqual(PARSER.parse_claude_usage(data, SID)["state"], "unavailable")
        data["rate_limits"]["five_hour"]["used_percentage"] = 101
        self.assertEqual(PARSER.parse_claude_usage(data, SID)["state"], "unavailable")


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.real_mv = shutil.which("mv")
        self.assertIsNotNone(self.real_mv)
        self.env = {**os.environ, "HOME": str(self.home), "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}
        self.path = self.home / ".claude/session-state" / f"{SID}.status.json"

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, data=None):
        return subprocess.run(["bash", "-c", 'umask 022; exec bash "$1"', "test", str(SCRIPT)],
                              input=json.dumps(FIXTURE if data is None else data), text=True,
                              capture_output=True, env=self.env, cwd=self.home, timeout=10)

    def test_snapshot_allowlist(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        data = json.loads(self.path.read_text())
        self.assertEqual(data["schema_version"], 1)
        self.assertGreater(data["observed_at"], 0)
        self.assertEqual(data["cwd"], "/example/worktree")
        self.assertEqual(data["transcript_path"], "/example/private-transcript.jsonl")
        self.assertEqual(data["rate_limits"], FIXTURE["rate_limits"])
        self.assertNotIn("unrelated_private_field", data)
        self.assertEqual(PARSER.parse_claude_status(data, SID)["session_id"], SID)
        data = copy.deepcopy(FIXTURE)
        del data["workspace"]
        self.assertEqual(self.run_script(data).returncode, 0)
        self.assertEqual(json.loads(self.path.read_text())["cwd"], "/example/fallback")

    def test_private_permissions(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertEqual(list(self.path.parent.glob(".status.*")), [])

    def test_atomic_replace(self):
        self.assertEqual(self.run_script().returncode, 0)
        old = self.path.read_bytes()
        inode = self.path.stat().st_ino
        self.stub("mv", '''python3 - "$@" <<'CHECK'
import json, pathlib, sys
source, destination = map(pathlib.Path, sys.argv[-2:])
assert source.parent == destination.parent
assert json.loads(source.read_text())["model"]["display_name"] == "Updated"
assert json.loads(destination.read_text())["model"]["display_name"] == "Example"
CHECK
[ "$?" -eq 0 ] || exit 1
exec ''' + shlex.quote(self.real_mv) + ''' "$@"''')
        changed = copy.deepcopy(FIXTURE)
        changed["model"]["display_name"] = "Updated"
        self.assertEqual(self.run_script(changed).returncode, 0)
        self.assertNotEqual(self.path.stat().st_ino, inode)
        self.assertNotEqual(self.path.read_bytes(), old)
        self.assertEqual(json.loads(self.path.read_text())["model"]["display_name"], "Updated")

    def test_failed_capture_preserves_old_snapshot(self):
        self.assertEqual(self.run_script().returncode, 0)
        before = self.path.read_bytes()
        self.stub("mv", "exit 1")
        data = copy.deepcopy(FIXTURE)
        data["model"]["display_name"] = "Updated"
        result = self.run_script(data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob(".status.*")), [])

    def test_invalid_session_id_and_json(self):
        self.assertEqual(self.run_script().returncode, 0)
        before = {str(p.relative_to(self.home)): p.read_bytes() for p in (self.home / ".claude").rglob("*") if p.is_file()}
        for value in ("../escape", "../" + "x" * 33, "", None, True, [], SID + "\n"):
            data = copy.deepcopy(FIXTURE)
            data["session_id"] = value
            self.assertEqual(self.run_script(data).returncode, 0)
            self.assertEqual({str(p.relative_to(self.home)): p.read_bytes() for p in (self.home / ".claude").rglob("*") if p.is_file()}, before)
        result = subprocess.run(["bash", str(SCRIPT)], input="{broken", text=True, capture_output=True, env=self.env, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual({str(p.relative_to(self.home)): p.read_bytes() for p in (self.home / ".claude").rglob("*") if p.is_file()}, before)

    def test_field_allowlist_and_absence(self):
        data = copy.deepcopy(FIXTURE)
        data["model"]["extra_private"] = "redacted"
        data["rate_limits"]["unknown_bucket"] = {"secret": "redacted"}
        data["rate_limits"]["five_hour"]["secret"] = "redacted"
        data["transcript_path"] = {"invalid": True}
        self.assertEqual(self.run_script(data).returncode, 0)
        saved = json.loads(self.path.read_text())
        self.assertNotIn("redacted", self.path.read_text())
        self.assertIsNone(saved["transcript_path"])
        self.assertEqual(saved["rate_limits"]["five_hour"]["used_percentage"], 0)
        data = {"session_id": SID}
        self.assertEqual(self.run_script(data).returncode, 0)
        saved = json.loads(self.path.read_text())
        self.assertIsNone(saved["context_window"]["remaining_percentage"])
        self.assertEqual(saved["rate_limits"], {})


# Every behavior-pinning test has a surgical production mutant. Each mutant is
# tested independently in a temporary file, never by editing the working tree.
MUTANTS = {
    "ParserTests.test_string_bounds": ("module", "0 < len(value) <= 4096", "len(value) > 0"),
    "ParserTests.test_status_fields": ("module", '"cwd": _text(snapshot.get("cwd"))', '"cwd": None'),
    "ParserTests.test_envelope_rejection": ("module", 'if snapshot.get("session_id") != expected_session_id:', 'if False:'),
    "ParserTests.test_unknown_fields": ("module", 'remaining = _number(context.get("remaining_percentage"), 100)', 'remaining = _number(context.get("remaining_percentage", 100), 100)'),
    "ParserTests.test_percent_fallback": ("module", 'remaining = 100 - used', 'remaining = used'),
    "ParserTests.test_invalid_numeric_fields": ("module", 'if type(value) not in (int, float):', 'if not isinstance(value, (int, float)):'),
    "ParserTests.test_usage_fields_and_overage": ("module", 'max(0, 100 - used) if available else None', '100 - used if available else None'),
    "ParserTests.test_expired_and_missing_windows": ("module", 'resets_at <= (result["observed_at"] if now is None else now)', 'resets_at < (result["observed_at"] if now is None else now)'),
    "ParserTests.test_usage_invalid_fields": ("module", '_number(window.get("resets_at"), _MAX_TIMESTAMP)', '_number(window.get("resets_at"))'),
    "WriterTests.test_snapshot_allowlist": ("script", 'cwd: (.workspace.current_dir // .cwd)', 'cwd: .cwd'),
    "WriterTests.test_private_permissions": ("script", 'chmod 700 "$state_dir"', 'chmod 755 "$state_dir"'),
    "WriterTests.test_atomic_replace": ("script", '> "$status_tmp" && mv -fT', '> "$state_dir/$session_id.status.json" && mv -fT'),
    "WriterTests.test_failed_capture_preserves_old_snapshot": ("script", "trap 'rm -f -- \"$status_tmp\"' EXIT", ': # removed cleanup'),
    "WriterTests.test_invalid_session_id_and_json": ("script", '[[ "$session_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] || exit 0', ': # removed ID validation'),
    "WriterTests.test_field_allowlist_and_absence": ("script", 'map_values({used_percentage: .used_percentage, resets_at: .resets_at})', 'map_values(.)'),
}


def mutation_check():
    subprocess.run([sys.executable, __file__], check=True, timeout=90)
    tests = {f"{cls.__name__}.{name}" for cls in (ParserTests, WriterTests) for name in unittest.defaultTestLoader.getTestCaseNames(cls)}
    if tests != set(MUTANTS):
        raise RuntimeError("Every test must have a mutation check")
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        for test, (kind, old, new) in MUTANTS.items():
            source = (MODULE if kind == "module" else ROOT / "skills/_shared/hooks/capture-claude-status.sh").read_text()
            if source.count(old) != 1:
                raise RuntimeError(f"Mutation anchor drift for {test}")
            target = Path(directory) / ("mutant.py" if kind == "module" else "mutant.sh")
            target.write_text(source.replace(old, new))
            # Avoid stale Python bytecode across same-size, same-second mutants.
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", f"HARNESS_STATUS_TEST_{kind.upper()}": str(target)}
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), test], env=env, text=True, capture_output=True, timeout=30)
            killed = result.returncode != 0 and "FAIL:" in result.stderr and "ERROR:" not in result.stderr
            print(f"{'KILLED' if killed else 'SURVIVED'} {test}")
            if not killed:
                failures.append(test)
                print(result.stdout + result.stderr)
    return bool(failures)


if __name__ == "__main__":
    if sys.argv[1:] == ["--mutation-check"]:
        raise SystemExit(mutation_check())
    unittest.main()
