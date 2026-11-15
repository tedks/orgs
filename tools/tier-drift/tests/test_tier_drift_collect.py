#!/usr/bin/env python3
"""Hermetic behavior tests for the tier-drift collector launcher."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from datetime import datetime

REPO = pathlib.Path(__file__).absolute().parents[1]
SCRIPT = REPO / "scripts/tier-drift-collect"


def aggregate(host: str, collected_at: str = "2026-10-29T00:00:00Z") -> dict:
    return {
        "schema": 1,
        "host": host,
        "collected_at": collected_at,
        "python": "3.12",
        "seconds": 0.1,
        "turns": [],
        "claude_tokens": [],
        "codex_tokens": [],
        "first_use": {},
        "last_use": {},
        "sources": {},
        "diagnostics": {
            "errors": {},
            "deduplicated": {},
            "gemini_cli_projects": [],
            "seen_values": {},
        },
    }


def reset_test_signal_defaults():
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
        signal.signal(sig, signal.SIG_DFL)


class CollectorWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tier-drift-test-")
        self.root = pathlib.Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "hosts": ["node-a"],
                    "ssh_suffix": ".local",
                    "collector": {},
                }
            )
        )
        self.source = self.root / "collector.py"
        self.source.write_text("# test source\n")
        self.out = self.root / "out"
        self.out.mkdir()
        (self.root / "home").mkdir()
        (self.bin / "hostname").write_text("#!/bin/sh\nprintf 'test-runner\\n'\n")
        (self.bin / "ssh").write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, signal, sys, time\n"
            "host = next(arg for arg in sys.argv[1:] if arg.endswith('.local'))[:-6]\n"
            "def log_event(event):\n"
            "    path = os.environ.get('FAKE_SSH_LOG')\n"
            "    if path:\n"
            "        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)\n"
            "        os.write(fd, f'{event} {host} {os.getpid()}\\n'.encode())\n"
            "        os.close(fd)\n"
            "def stop(signal_number, _frame):\n"
            "    raise SystemExit(255)\n"
            "signal.signal(signal.SIGINT, stop)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "log_event('start')\n"
            "try:\n"
            "    if os.environ.get('FAKE_SSH_READY'):\n"
            "        pathlib.Path(os.environ['FAKE_SSH_READY']).touch()\n"
            "    if host in os.environ.get('FAKE_SSH_SLEEP_HOSTS', '').split(','):\n"
            "        time.sleep(float(os.environ.get('FAKE_SSH_DELAY', '0')))\n"
            "    if host in os.environ.get('FAKE_SSH_FAIL_HOSTS', '').split(','):\n"
            "        time.sleep(float(os.environ.get('FAKE_SSH_DELAY', '0')))\n"
            "        print(os.environ.get('FAKE_SSH_ERROR', 'link down'), file=sys.stderr)\n"
            "        raise SystemExit(255)\n"
            "    if host in os.environ.get('FAKE_SSH_ERROR_HOSTS', '').split(','):\n"
            "        print(os.environ.get('FAKE_SSH_ERROR', 'collector failed'), file=sys.stderr)\n"
            "        raise SystemExit(42)\n"
            "    if host in os.environ.get('FAKE_SSH_BAD_BYTES_HOSTS', '').split(','):\n"
            "        sys.stderr.buffer.write(b'bad byte: \\xff\\n')\n"
            "        raise SystemExit(255)\n"
            "    if host in os.environ.get('FAKE_SSH_REMOTE_255_HOSTS', '').split(','):\n"
            "        print('remote collector failed with 255', file=sys.stderr)\n"
            "        raise SystemExit(254 if 'exit 254' in sys.argv[-1] else 255)\n"
            "    time.sleep(float(os.environ.get('FAKE_SSH_DELAY', '0')))\n"
            "    sys.stdout.write(pathlib.Path(os.environ['FAKE_SSH_RESPONSE']).read_text())\n"
            "finally:\n"
            "    log_event('end')\n"
        )
        for path in self.bin.iterdir():
            path.chmod(0o755)
        self.base_env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.root / "home"),
            "LANG": "C.UTF-8",
            "TIER_DRIFT_CONFIG": str(self.config),
            "TIER_DRIFT_SRC": str(self.source),
            "TIER_DRIFT_OUT": str(self.out),
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_collector(self, *hosts, **env):
        return subprocess.run(
            [str(SCRIPT), *hosts],
            cwd=REPO,
            env={**self.base_env, **env},
            text=True,
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_config_is_required_and_no_host_is_contacted(self):
        result = self.run_collector("node-a", TIER_DRIFT_CONFIG="")
        self.assertEqual(result.returncode, 2)
        self.assertIn("TIER_DRIFT_CONFIG is required", result.stderr)
        self.assertFalse((self.out / "node-a.json").exists())

    def test_unconfigured_host_is_rejected_before_ssh(self):
        result = self.run_collector("other-host")
        self.assertEqual(result.returncode, 2)
        self.assertIn("host is not configured", result.stderr)
        self.assertFalse((self.out / "other-host.json").exists())

    def test_unsafe_host_cannot_escape_output_directory(self):
        self.config.write_text(
            json.dumps(
                {
                    "hosts": ["../outside"],
                    "ssh_suffix": ".local",
                    "collector": {},
                }
            )
        )
        result = self.run_collector("../outside")
        self.assertEqual(result.returncode, 2)
        self.assertIn("safe host names", result.stderr)
        self.assertFalse((self.root / "outside.json").exists())

    def test_bare_launcher_refuses_before_archiving_good_output(self):
        bare = self.root / "bare"
        bare.mkdir()
        launcher = bare / "tier-drift-collect"
        shutil.copy2(SCRIPT, launcher)
        old = self.out / "node-a.json"
        original = json.dumps(aggregate("node-a"))
        old.write_text(original)
        result = subprocess.run(
            [str(launcher), "node-a"],
            cwd=bare,
            env=self.base_env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("package is unavailable", result.stderr)
        self.assertEqual(old.read_text(), original)

    def test_zero_exit_invalid_output_is_not_published(self):
        old = self.out / "node-a.json"
        old.write_text(json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z")))
        bad = self.root / "bad-response.txt"
        bad.write_text("login banner\n" + json.dumps(aggregate("node-a")))
        result = self.run_collector("node-a", FAKE_SSH_RESPONSE=str(bad))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid collector output", result.stderr)
        self.assertFalse(old.exists())
        self.assertEqual(len(list(self.out.glob("node-a.json.stale-*"))), 1)
        self.assertFalse((self.out / "node-a.unreachable.json").exists())

    def test_zero_exit_wrong_schema_is_not_published(self):
        wrong = aggregate("node-a")
        wrong["schema"] = 99
        response = self.response_file("wrong.json", wrong)
        result = self.run_collector("node-a", FAKE_SSH_RESPONSE=str(response))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid collector output", result.stderr)
        self.assertFalse((self.out / "node-a.json").exists())

    def test_default_source_is_the_checkout_collector(self):
        empty_home = self.root / "home"
        empty_home.mkdir(exist_ok=True)
        self.config.write_text(
            json.dumps(
                {
                    "hosts": ["test-runner"],
                    "ssh_suffix": ".local",
                    "collector": {},
                }
            )
        )
        result = self.run_collector("test-runner", TIER_DRIFT_SRC="", HOME=str(empty_home))
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads((self.out / "test-runner.json").read_text())
        self.assertEqual(document["schema"], 1)
        self.assertIsInstance(document["host"], str)
        self.assertTrue(document["host"])

    def response_file(self, name: str, doc: dict) -> pathlib.Path:
        path = self.root / name
        path.write_text(json.dumps(doc))
        return path

    def run_concurrently(self, envs):
        log = self.root / "ssh-events.log"
        procs = [
            subprocess.Popen(
                [str(SCRIPT), "node-a"],
                cwd=REPO,
                env={**self.base_env, **env, "FAKE_SSH_LOG": str(log)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for env in envs
        ]
        results = [proc.communicate(timeout=10) + (proc.returncode,) for proc in procs]
        self.assertTrue(log.is_file())
        active = 0
        for line in log.read_text().splitlines():
            event, host, _pid = line.split()
            self.assertEqual(host, "node-a")
            if event == "start":
                self.assertEqual(active, 0, "concurrent collectors overlapped for one host")
                active += 1
            else:
                active -= 1
                self.assertGreaterEqual(active, 0)
        self.assertEqual(active, 0)
        return results

    def assert_fake_ssh_stopped(self, log: pathlib.Path):
        events = [line.split() for line in log.read_text().splitlines()]
        started = [pid for event, host, pid in events if event == "start" and host == "node-a"]
        ended = [pid for event, host, pid in events if event == "end" and host == "node-a"]
        self.assertEqual(len(started), 1, events)
        self.assertEqual(ended, started, events)

    def kill_fake_ssh(self, log: pathlib.Path):
        if not log.exists():
            return
        for line in log.read_text().splitlines():
            fields = line.split()
            if len(fields) != 3:
                continue
            event, host, pid = fields
            if event != "start" or host != "node-a":
                continue
            cmdline = pathlib.Path(f"/proc/{pid}/cmdline")
            try:
                command = cmdline.read_bytes()
            except FileNotFoundError:
                continue
            if os.fsencode(self.bin / "ssh") not in command:
                continue
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_failed_rerun_moves_old_aggregate_and_writes_reportable_status(self):
        old = self.out / "node-a.json"
        old.write_text(json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z")))

        result = self.run_collector(
            "node-a", FAKE_SSH_FAIL_HOSTS="node-a", FAKE_SSH_ERROR="link down"
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(old.exists(), "stale aggregate must not match the report's *.json input")
        stale = list(self.out.glob("node-a.json.stale-*"))
        self.assertEqual(len(stale), 1)
        self.assertEqual(json.loads(stale[0].read_text())["collected_at"], "2026-10-28T00:00:00Z")
        status_path = self.out / "node-a.unreachable.json"
        status = json.loads(status_path.read_text())
        self.assertTrue(aggregate("synthetic").keys() <= status.keys())
        self.assertTrue(
            aggregate("synthetic")["diagnostics"].keys() <= status["diagnostics"].keys()
        )
        self.assertIsInstance(status["python"], str)
        self.assertEqual(status["status"], "unreachable")
        self.assertEqual(status["host"], "node-a (unreachable)")
        self.assertIn("link down", status["error"])
        datetime.fromisoformat(status["attempted_at"].replace("Z", "+00:00"))
        self.assertEqual(status["schema"], 1)
        self.assertEqual(status["turns"], [])
        self.assertEqual(list(self.out.glob("node-a.*.tmp.*")), [])

    def test_failed_first_run_writes_unreachable_document_without_stale_file(self):
        result = self.run_collector(
            "node-a", FAKE_SSH_FAIL_HOSTS="node-a", FAKE_SSH_ERROR="host key unavailable"
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse((self.out / "node-a.json").exists())
        self.assertEqual(
            json.loads((self.out / "node-a.unreachable.json").read_text())["error"],
            "host key unavailable",
        )
        self.assertEqual(list(self.out.glob("node-a.*.tmp.*")), [])

    def test_partial_failure_is_nonfatal_and_report_marks_the_failed_host(self):
        self.config.write_text(
            json.dumps({"hosts": ["node-a", "node-b"], "ssh_suffix": ".local", "collector": {}})
        )
        response = self.response_file("success.json", aggregate("node-b"))

        result = self.run_collector(
            FAKE_SSH_FAIL_HOSTS="node-a",
            FAKE_SSH_ERROR="link down",
            FAKE_SSH_RESPONSE=str(response),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.out / "node-b.json").is_file())
        status = json.loads((self.out / "node-a.unreachable.json").read_text())
        self.assertEqual(status["host"], "node-a (unreachable)")
        self.assertEqual(status["status"], "unreachable")

    def test_remote_collector_error_is_not_misreported_as_unreachable(self):
        old = self.out / "node-a.json"
        old.write_text(json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z")))

        result = self.run_collector(
            "node-a", FAKE_SSH_ERROR_HOSTS="node-a", FAKE_SSH_ERROR="bad collector"
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("collector failed (exit 42)", result.stderr)
        self.assertFalse(old.exists())
        self.assertEqual(len(list(self.out.glob("node-a.json.stale-*"))), 1)
        self.assertFalse((self.out / "node-a.unreachable.json").exists())

    def test_remote_exit_255_is_remapped_and_fails_as_collector_error(self):
        result = self.run_collector("node-a", FAKE_SSH_REMOTE_255_HOSTS="node-a")

        self.assertEqual(result.returncode, 1)
        self.assertIn("collector failed (exit 254)", result.stderr)
        self.assertFalse((self.out / "node-a.unreachable.json").exists())

    def test_non_utf8_ssh_stderr_is_preserved_safely(self):
        result = self.run_collector("node-a", FAKE_SSH_BAD_BYTES_HOSTS="node-a")

        self.assertEqual(result.returncode, 1)
        status = json.loads((self.out / "node-a.unreachable.json").read_text())
        self.assertIn("bad byte: �", status["error"])

    def test_local_collector_exit_255_is_not_unreachable(self):
        self.source.write_text("raise SystemExit(255)\n")
        self.config.write_text(
            json.dumps(
                {
                    "hosts": ["test-runner"],
                    "ssh_suffix": ".local",
                    "collector": {},
                }
            )
        )

        result = self.run_collector("test-runner")

        self.assertEqual(result.returncode, 1)
        self.assertIn("collector failed (exit 255)", result.stderr)
        self.assertFalse((self.out / "test-runner.unreachable.json").exists())

    def test_remote_timeout_archives_old_output_and_reports_unreachable(self):
        old = self.out / "node-a.json"
        old.write_text(json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z")))

        result = self.run_collector(
            "node-a",
            FAKE_SSH_SLEEP_HOSTS="node-a",
            FAKE_SSH_DELAY="2",
            TIER_DRIFT_SSH_TIMEOUT="1",
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(old.exists())
        self.assertEqual(len(list(self.out.glob("node-a.json.stale-*"))), 1)
        status = json.loads((self.out / "node-a.unreachable.json").read_text())
        self.assertEqual(status["status"], "unreachable")
        self.assertIn("timed out", status["error"])

    def test_interrupt_stops_wrapper_without_archiving_output(self):
        old = self.out / "node-a.json"
        original = json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z"))
        old.write_text(original)
        ready = self.root / "ssh-ready"
        log = self.root / "ssh-events.log"
        env = {
            **self.base_env,
            "FAKE_SSH_SLEEP_HOSTS": "node-a",
            "FAKE_SSH_DELAY": "10",
            "FAKE_SSH_READY": str(ready),
            "FAKE_SSH_LOG": str(log),
            "TIER_DRIFT_SSH_TIMEOUT": "300",
        }
        proc = subprocess.Popen(
            [str(SCRIPT), "node-a"],
            cwd=REPO,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=reset_test_signal_defaults,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        try:
            self.assertTrue(ready.exists(), "fake SSH did not start")
            os.killpg(proc.pid, signal.SIGINT)
            stdout, stderr = proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            self.kill_fake_ssh(log)

        self.assertEqual(proc.returncode, 130, (stdout, stderr))
        self.assertEqual(old.read_text(), original)
        self.assertFalse((self.out / "node-a.unreachable.json").exists())
        self.assertEqual(list(self.out.glob("node-a.*.tmp.*")), [])
        self.assert_fake_ssh_stopped(log)

    def test_term_to_wrapper_stops_child_without_archiving_output(self):
        old = self.out / "node-a.json"
        original = json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z"))
        old.write_text(original)
        ready = self.root / "ssh-ready"
        log = self.root / "ssh-events.log"
        env = {
            **self.base_env,
            "FAKE_SSH_SLEEP_HOSTS": "node-a",
            "FAKE_SSH_DELAY": "10",
            "FAKE_SSH_READY": str(ready),
            "FAKE_SSH_LOG": str(log),
            "TIER_DRIFT_SSH_TIMEOUT": "300",
        }
        proc = subprocess.Popen(
            [str(SCRIPT), "node-a"],
            cwd=REPO,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=reset_test_signal_defaults,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        try:
            self.assertTrue(ready.exists(), "fake SSH did not start")
            proc.send_signal(signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            self.kill_fake_ssh(log)

        self.assertEqual(proc.returncode, 143, (stdout, stderr))
        self.assertEqual(old.read_text(), original)
        self.assertFalse((self.out / "node-a.unreachable.json").exists())
        self.assertEqual(list(self.out.glob("node-a.*.tmp.*")), [])
        self.assert_fake_ssh_stopped(log)

    def test_hup_and_quit_to_wrapper_stop_child_without_archiving_output(self):
        for sig, expected_status in ((signal.SIGHUP, 129), (signal.SIGQUIT, 131)):
            with self.subTest(signal=sig):
                out = self.root / f"out-{sig}"
                out.mkdir()
                old = out / "node-a.json"
                original = json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z"))
                old.write_text(original)
                ready = self.root / f"ssh-ready-{sig}"
                log = self.root / f"ssh-events-{sig}.log"
                env = {
                    **self.base_env,
                    "FAKE_SSH_SLEEP_HOSTS": "node-a",
                    "FAKE_SSH_DELAY": "10",
                    "FAKE_SSH_READY": str(ready),
                    "FAKE_SSH_LOG": str(log),
                    "TIER_DRIFT_OUT": str(out),
                    "TIER_DRIFT_SSH_TIMEOUT": "300",
                }
                proc = subprocess.Popen(
                    [str(SCRIPT), "node-a"],
                    cwd=REPO,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    preexec_fn=reset_test_signal_defaults,
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                try:
                    self.assertTrue(ready.exists(), "fake SSH did not start")
                    proc.send_signal(sig)
                    stdout, stderr = proc.communicate(timeout=5)
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                    self.kill_fake_ssh(log)

                self.assertEqual(proc.returncode, expected_status, (stdout, stderr))
                self.assertEqual(old.read_text(), original)
                self.assertFalse((out / "node-a.unreachable.json").exists())
                self.assertEqual(list(out.glob("node-a.*.tmp.*")), [])
                self.assert_fake_ssh_stopped(log)

    def test_cleanup_does_not_remove_inherited_temp_path(self):
        marker = self.root / "keep-me"
        marker.write_text("preserve")
        flock = self.bin / "flock"
        flock.write_text("#!/bin/sh\nexit 1\n")
        flock.chmod(0o755)

        result = self.run_collector(
            "node-a",
            tmp=str(marker),
            err=str(marker),
            status_tmp=str(marker),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "preserve")

    def test_invalid_timeout_fails_before_touching_old_output(self):
        old = self.out / "node-a.json"
        original = json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z"))
        old.write_text(original)

        result = self.run_collector("node-a", TIER_DRIFT_SSH_TIMEOUT="not-a-duration")

        self.assertEqual(result.returncode, 2)
        self.assertIn("TIER_DRIFT_SSH_TIMEOUT", result.stderr)
        self.assertEqual(old.read_text(), original)
        self.assertFalse((self.out / "node-a.unreachable.json").exists())

    def test_success_atomically_replaces_aggregate_and_leaves_no_temp_file(self):
        old = self.out / "node-a.json"
        old.write_text(json.dumps(aggregate("node-a", "2026-10-28T00:00:00Z")))
        (self.out / "node-a.unreachable.json").write_text("old status")
        response = self.response_file("success.json", aggregate("node-a", "2026-10-29T12:00:00Z"))

        result = self.run_collector(FAKE_SSH_RESPONSE=str(response))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(old.read_text())["collected_at"], "2026-10-29T12:00:00Z")
        self.assertFalse((self.out / "node-a.unreachable.json").exists())
        self.assertEqual(list(self.out.glob("node-a.json.tmp.*")), [])

    def test_concurrent_successes_use_distinct_temp_files(self):
        first = self.response_file("first.json", aggregate("node-a", "2026-10-29T10:00:00Z"))
        second = self.response_file("second.json", aggregate("node-a", "2026-10-29T11:00:00Z"))
        envs = [
            {"FAKE_SSH_RESPONSE": str(path), "FAKE_SSH_DELAY": "0.3"} for path in (first, second)
        ]
        results = self.run_concurrently(envs)
        self.assertEqual([rc for _, _, rc in results], [0, 0], results)
        final = json.loads((self.out / "node-a.json").read_text())
        self.assertIn(final["collected_at"], {"2026-10-29T10:00:00Z", "2026-10-29T11:00:00Z"})
        self.assertEqual(list(self.out.glob("node-a.json.tmp.*")), [])

    def test_concurrent_success_and_failure_leave_one_current_status(self):
        response = self.response_file("success.json", aggregate("node-a", "2026-10-29T10:00:00Z"))
        envs = [
            {"FAKE_SSH_RESPONSE": str(response), "FAKE_SSH_DELAY": "0.3"},
            {
                "FAKE_SSH_FAIL_HOSTS": "node-a",
                "FAKE_SSH_ERROR": "link down",
                "FAKE_SSH_DELAY": "0.3",
            },
        ]
        results = self.run_concurrently(envs)
        self.assertEqual([rc for _, _, rc in results], [0, 1], results)
        aggregate_exists = (self.out / "node-a.json").exists()
        status_exists = (self.out / "node-a.unreachable.json").exists()
        self.assertNotEqual(aggregate_exists, status_exists)
        if aggregate_exists:
            final = json.loads((self.out / "node-a.json").read_text())
            self.assertEqual(final["collected_at"], "2026-10-29T10:00:00Z")
        else:
            status = json.loads((self.out / "node-a.unreachable.json").read_text())
            self.assertEqual(status["status"], "unreachable")
        self.assertEqual(list(self.out.glob("node-a.json.tmp.*")), [])


if __name__ == "__main__":
    unittest.main()
