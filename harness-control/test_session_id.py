#!/usr/bin/env python3
"""Tests for how server.py resolves the current session id.

Most cases fake the process tree (pid -> parent, comm, start time) and use a
temp session-state directory, since real ancestry can't be controlled from a
test. One case reads a REAL /proc/<pid>/stat of a process with an awkward comm.

Run through `nix flake check` from the repository root.
"""

import asyncio
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # importing server.py must not litter __pycache__

_spec = importlib.util.spec_from_file_location("server", Path(__file__).with_name("server.py"))
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

SID = "11111111-1111-1111-1111-111111111111"
PARENT_SID = "22222222-2222-2222-2222-222222222222"
BOOT = "boot-A"
_REAL_SLEEP = asyncio.sleep  # setUp replaces asyncio.sleep; keep the real one for the blocking test


class SessionIdTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        # python(100) -> launcher(99) -> claude(98) -> bash(50) -> claude(40, parent)
        self.ppid = {100: 99, 99: 98, 98: 50, 50: 40, 40: 1}
        self.comm = {100: "python3", 99: "launcher", 98: "claude", 50: "bash", 40: "claude"}
        self.start = {100: "9000", 99: "8000", 98: "7000", 50: "500", 40: "100"}
        for p in [
            mock.patch.object(server, "SESSION_STATE_DIR", self.state),
            mock.patch.object(server.os, "getpid", return_value=100),
            mock.patch.object(server, "_get_parent_pid", side_effect=lambda p: self.ppid.get(p)),
            mock.patch.object(server, "_get_comm", side_effect=lambda p: self.comm.get(p, "")),
            mock.patch.object(server, "_get_starttime", side_effect=lambda p: self.start.get(p)),
            mock.patch.object(server, "_get_boot_id", return_value=BOOT),
            mock.patch.dict(os.environ, {}, clear=False),
        ]:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("CLAUDE_SESSION_ID", None)
        sleeper = mock.patch.object(server.asyncio, "sleep", new_callable=mock.AsyncMock)
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def pointer(self, pid, text):
        (self.state / f"current.{pid}").write_text(text + "\n")

    async def test_finds_the_pointer_on_the_claude_ancestor(self):
        self.pointer(98, f"{SID} 7000 {BOOT}")
        self.assertEqual(await server._get_session_id(), SID)
        self.sleep.assert_not_called()

    async def test_a_pointer_for_a_reused_pid_is_stale(self):
        # Written by a previous claude that had pid 98; this one started later.
        self.pointer(98, f"{SID} 1234 {BOOT}")
        self.assertIsNone(await server._get_session_id())

    async def test_a_pointer_from_before_a_reboot_is_stale(self):
        # Same pid, same tick count since boot -- but a different boot.
        self.pointer(98, f"{SID} 7000 boot-B")
        self.assertIsNone(await server._get_session_id())

    async def test_bare_and_two_field_pointers_are_refused(self):
        # The previous hook wrote a bare "<session_id>"; there is nothing to verify.
        for old_format in (SID, f"{SID} 7000"):
            with self.subTest(old_format=old_format):
                self.pointer(98, old_format)
                self.assertIsNone(await server._get_session_id())

    async def test_stale_pointer_does_not_fall_through_to_a_parent_session(self):
        self.pointer(98, f"{SID} 1234 {BOOT}")
        self.pointer(40, f"{PARENT_SID} 100 {BOOT}")
        self.assertIsNone(await server._get_session_id())

    async def test_does_not_climb_past_the_nearest_claude_into_a_parent_session(self):
        # A nested `claude -p` (98) whose own pointer has not landed yet must not
        # answer with the parent claude's (40) session.
        self.pointer(40, f"{PARENT_SID} 100 {BOOT}")
        self.assertIsNone(await server._get_session_id())

    async def test_still_climbs_through_non_claude_ancestors(self):
        # A launcher whose comm is not claude*: keep climbing to find the pointer.
        self.comm[98] = "node"
        self.pointer(50, f"{SID} 500 {BOOT}")
        self.assertEqual(await server._get_session_id(), SID)

    async def test_env_override_wins(self):
        self.pointer(98, f"{SID} 7000 {BOOT}")
        with mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": PARENT_SID}):
            self.assertEqual(await server._get_session_id(), PARENT_SID)

    async def test_retries_when_the_async_hook_lands_late(self):
        calls = {"n": 0}

        async def land_on_second_sleep(_delay):
            calls["n"] += 1
            if calls["n"] == 2:
                self.pointer(98, f"{SID} 7000 {BOOT}")

        self.sleep.side_effect = land_on_second_sleep
        self.assertEqual(await server._get_session_id(), SID)
        self.assertEqual(calls["n"], 2)

    async def test_gives_up_after_the_configured_attempts(self):
        self.assertIsNone(await server._get_session_id())
        self.assertEqual(self.sleep.call_count, server.POINTER_ATTEMPTS - 1)

    async def test_does_not_wait_when_there_is_no_claude_ancestor(self):
        # Outside claude (or an install whose comm is not claude*) no pointer can
        # ever appear, so the retry would only add latency.
        for pid in self.comm:
            self.comm[pid] = "something-else"
        self.assertIsNone(await server._get_session_id())
        self.sleep.assert_not_called()

    async def test_waiting_does_not_block_the_event_loop(self):
        # Real sleeping here (setUp mocked it out), and an ordering check: a
        # blocking time.sleep in the lookup would let it finish before the other
        # task ever got to run, which a mocked sleep could never reveal.
        async def real_sleep(delay):
            await _REAL_SLEEP(delay)

        self.sleep.side_effect = real_sleep
        events = []

        async def ticker():
            await _REAL_SLEEP(0.01)
            events.append("other task ran")

        async def lookup():
            await server._get_session_id()  # no pointer: waits out every retry
            events.append("lookup finished")

        with mock.patch.object(server, "POINTER_RETRY_DELAY", 0.05):
            await asyncio.gather(lookup(), ticker())
        self.assertEqual(events, ["other task ran", "lookup finished"])


class RealProcTest(unittest.TestCase):
    def test_stat_parsing_survives_an_awkward_comm(self):
        # comm containing spaces and a ") " would break a naive split; use a REAL process.
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "claude) S 1 2 3"
            exe.symlink_to(os.environ.get("HARNESS_TEST_SLEEP", "/bin/sleep"))
            proc = subprocess.Popen([str(exe), "30"])
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            for _ in range(50):  # the child has exec'd once its comm changes
                if Path(f"/proc/{proc.pid}/comm").read_text().startswith("claude"):
                    break
                time.sleep(0.02)
            stat = Path(f"/proc/{proc.pid}/stat").read_text()
            expected = re.match(r"\d+ \(.*\) \S (.*)", stat, re.S).group(1).split()
            # expected[0] is field 4 (ppid), so field 22 (start time) is expected[18]
            self.assertEqual(server._get_starttime(proc.pid), expected[18])
            self.assertEqual(server._get_parent_pid(proc.pid), os.getpid())

    def _reset_boot_id_cache(self):
        server._boot_id_cache = None

    def _real_boot_id(self):
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            self.skipTest("/proc/sys/kernel/random/boot_id is unreadable on this host")

    def test_boot_id_matches_the_kernel_and_is_cached(self):
        self._reset_boot_id_cache()
        self.addCleanup(self._reset_boot_id_cache)
        real = self._real_boot_id()
        self.assertEqual(server._get_boot_id(), real)
        with mock.patch("pathlib.Path.read_text", side_effect=AssertionError("not cached: hit the filesystem again")):
            self.assertEqual(server._get_boot_id(), real)  # cached: the patched read_text is never reached

    def test_boot_id_falls_back_to_the_same_string_the_hook_uses_when_unreadable(self):
        self._reset_boot_id_cache()
        self.addCleanup(self._reset_boot_id_cache)
        with mock.patch("pathlib.Path.read_text", side_effect=OSError):
            self.assertEqual(server._get_boot_id(), "unknown")

    def test_a_transient_boot_id_read_failure_is_not_cached(self):
        # A one-shot cache (e.g. lru_cache) would memoize "unknown" forever on
        # the first glitch, permanently mismatching every pointer's real boot
        # id from then on -- reintroducing the resumed-session-null bug this
        # file exists to fix, until the server restarts. Only a SUCCESS may
        # be cached.
        self._reset_boot_id_cache()
        self.addCleanup(self._reset_boot_id_cache)
        real = self._real_boot_id()
        call_count = {"n": 0}
        real_read_text = Path.read_text

        def flaky_once(self, *a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("transient")
            return real_read_text(self, *a, **kw)

        with mock.patch("pathlib.Path.read_text", flaky_once):
            self.assertEqual(server._get_boot_id(), "unknown")  # 1st call: transient failure, not cached
            self.assertEqual(server._get_boot_id(), real)       # 2nd call: succeeds, now cached
        # a real value, once obtained, is cached even through later failures
        with mock.patch("pathlib.Path.read_text", side_effect=OSError):
            self.assertEqual(server._get_boot_id(), real)


if __name__ == "__main__":
    unittest.main(verbosity=2)
