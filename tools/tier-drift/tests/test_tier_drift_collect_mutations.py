#!/usr/bin/env python3
"""Prove lock-wait cancellation test rejects the original foreground wait."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

repo = Path(__file__).absolute().parents[1]
source = (repo / "scripts/tier-drift-collect").read_text()
old = '  flock -x "$host_lock" &\n  run_pid=$!\n  wait "$run_pid"\n  run_pid=\n'
assert source.count(old) == 1, "mutation target changed"

with tempfile.TemporaryDirectory(prefix="tier-drift-lock-mutant-") as scratch:
    root = Path(scratch)
    (root / "scripts").mkdir()
    shutil.copytree(
        repo / "src/tier_drift",
        root / "src/tier_drift",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    mutant = root / "scripts/tier-drift-collect"
    mutant.write_text(source.replace(old, '  flock -x "$host_lock"\n'))
    mutant.chmod(0o755)
    command = [
        sys.executable,
        str(repo / "tests/test_tier_drift_collect.py"),
        "CollectorWrapperTests.test_cancel_while_waiting_for_host_lock_never_collects",
    ]
    env = {**os.environ, "TIER_DRIFT_TEST_SCRIPT": str(mutant), "TIER_DRIFT_TEST_SIGNAL": "SIGTERM"}
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    assert (
        result.returncode != 0
        and "TimeoutExpired" in result.stderr
        and "test_cancel_while_waiting_for_host_lock_never_collects" in result.stderr
    ), (
        "foreground-lock mutant survived or failed for another reason:\n"
        f"{result.stdout}{result.stderr}"
    )
print("KILLED foreground-lock mutant: cancelled waiter exceeded prompt-exit bound")
