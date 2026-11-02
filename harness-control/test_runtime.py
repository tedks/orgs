#!/usr/bin/env python3
"""Runtime integration tests that require the package's minimal executable PATH."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import harness_control
import server


class RuntimeTest(unittest.TestCase):
    def test_observer_reenters_the_exact_module_without_ambient_python(self):
        with tempfile.TemporaryDirectory() as directory:
            command = harness_control._observer_command(Path(directory), "invalid")
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(1, result.returncode)
        self.assertIn("invalid_operation_id", result.stderr)

    def test_child_environment_scrubs_ambient_python_configuration(self):
        identity = mock.Mock(socket="/socket")
        hostile = {
            "PYTHONPATH": "/hostile",
            "PYTHONWARNINGS": "error",
            "PYTHONPLATLIBDIR": "lib64",
            "NIX_PYTHONPATH": "/hostile-nix",
            "SPAWN_TMUX_LABEL": "wrong",
        }
        with mock.patch.dict(os.environ, hostile):
            env = harness_control._environment(identity)
        self.assertFalse(any(name.startswith("PYTHON") for name in env
                             if name not in {"PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"}))
        self.assertNotIn("NIX_PYTHONPATH", env)
        self.assertNotIn("SPAWN_TMUX_LABEL", env)
        self.assertEqual("/socket", env["SPAWN_TMUX_SOCKET"])

    def test_checkpoint_verification_finds_packaged_git(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Harness Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "harness@example.invalid"], check=True)
            shard = repo / "handoff.md"
            shard.write_text("recoverable state\n")
            subprocess.run(["git", "-C", str(repo), "add", "handoff.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "checkpoint"], check=True)
            commit = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            result = harness_control.verify_checkpoint({
                "private_storage_attested": True,
                "obligations_preserved": True,
                "pause_state_preserved": True,
                "resources_disposition": "active_recorded",
                "authority": "compact_authorized",
                "pause_state_reference": "none",
                "active_inventory_reference": "test",
                "push_attestation": "no_remote_configured",
                "sha256": hashlib.sha256(shard.read_bytes()).hexdigest(),
                "commit": commit,
                "repo_path": str(repo),
                "shard_path": str(shard),
            })
            self.assertIn("shard_bytes_in_exact_commit", result["verified"])

    def test_session_state_rejects_traversal_and_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            state_dir.mkdir()
            old = server.SESSION_STATE_DIR
            server.SESSION_STATE_DIR = state_dir
            self.addCleanup(setattr, server, "SESSION_STATE_DIR", old)
            outside = root / "outside.json"
            outside.write_text('{"launch_dir": "/private"}')
            self.assertEqual({}, server._read_session_state("../outside"))
            sid = "00000000-0000-0000-0000-000000000000"
            (state_dir / f"{sid}.json").write_text("not json")
            self.assertEqual({}, server._read_session_state(sid))
            (state_dir / f"{sid}.json").write_text("[]")
            self.assertEqual({}, server._read_session_state(sid))

    def test_malformed_sessions_index_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            index = project / "sessions-index.json"
            for content in (
                "not json",
                "[]",
                '{"sessions": {}}',
                '{"sessions": [null, "bad", 1]}',
            ):
                index.write_text(content)
                self.assertEqual([], server._read_sessions_index(project))

            index.write_text('{"sessions": [{"sessionId": "valid"}, null]}')
            self.assertEqual(
                [{"sessionId": "valid"}], server._read_sessions_index(project)
            )


if __name__ == "__main__":
    unittest.main()
