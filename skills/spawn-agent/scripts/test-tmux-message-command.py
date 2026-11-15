#!/usr/bin/env python3
"""Exercise the shared tmux-message command against an external skill tree."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


COMMAND = Path(__file__).resolve().with_name("tmux-message-command")


class TmuxMessageWrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tmux-message-wrapper-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.skills = self.root / "external/skills"
        transport = self.skills / "spawn-agent/scripts/tmux-message.sh"
        transport.parent.mkdir(parents=True)
        transport.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        transport.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("AGENT_SKILLS_")}
        self.env["HOME"] = str(self.home)

    def run_command(self, env=None):
        return subprocess.run(
            [COMMAND, "one", "two words"],
            env=self.env | (env or {}),
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def test_explicit_and_installed_external_transport(self):
        self.assertTrue(os.access(COMMAND, os.X_OK))
        explicit = self.run_command({"AGENT_SKILLS_ROOT": str(self.skills)})
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(explicit.stdout, "one\ntwo words\n")

        installed = self.home / ".claude/skills"
        installed.parent.mkdir(parents=True)
        installed.symlink_to(self.skills, target_is_directory=True)
        default = self.run_command()
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stdout, explicit.stdout)

    def test_missing_and_relative_roots_fail_closed(self):
        missing = self.run_command()
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("install the shared skills", missing.stderr)
        for value in ("", "relative/skills"):
            with self.subTest(value=value):
                result = self.run_command({"AGENT_SKILLS_ROOT": value})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must be an absolute path", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
