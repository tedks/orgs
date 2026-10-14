#!/usr/bin/env python3
"""Fork preparation validates task bytes without invoking native messaging."""
from pathlib import Path
import importlib.util
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("fork_task", Path(__file__).with_name("codex-fork-task.py"))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

class ForkTaskTests(unittest.TestCase):
    def test_exact_bytes_and_no_native_command(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task"
            task.write_bytes('Unicode λ\nsecond line\n'.encode())
            with patch("sys.argv", [str(helper.__file__), "preflight", str(task)]):
                helper.main()
            self.assertEqual(helper.task_text(task), 'Unicode λ\nsecond line\n')

    def test_invalid_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task"
            for content in [b"", b"x" * 32768, b"x\0y", b"\xff"]:
                task.write_bytes(content)
                with self.assertRaises(ValueError):
                    helper.task_text(task)

if __name__ == "__main__":
    unittest.main()
