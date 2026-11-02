#!/usr/bin/env python3
"""Exercise the built command with hostile ambient Python configuration."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


EXPECTED = {
    "get_status",
    "get_usage",
    "record_checkpoint",
    "self_compact",
    "self_exit",
    "send_to_self",
    "read_own_pane",
    "get_operation",
    "cancel_operation",
}


async def probe(command: str) -> None:
    with tempfile.TemporaryDirectory(prefix="harness-control-package-") as directory:
        home = Path(directory)
        hostile = home / "hostile-python"
        hostile.mkdir()
        (hostile / "mcp.py").write_text("raise AssertionError('ambient mcp imported')\n")
        (hostile / "harness_identity.py").write_text(
            "raise AssertionError('ambient identity reader imported')\n"
        )
        nix_path_marker = home / "nix-pythonpath-executed"
        (hostile / "ambient.pth").write_text(
            f"import pathlib; pathlib.Path({str(nix_path_marker)!r}).write_text('bad')\n"
        )
        user_site = home / ".local" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        user_site.mkdir(parents=True)
        (user_site / "harness_identity.py").write_text(
            "raise AssertionError('user site identity reader imported')\n"
        )
        env = {
            "HOME": str(home),
            "PATH": "/ambient-path-must-not-be-required",
            "PYTHONHOME": str(hostile),
            "PYTHONPATH": str(hostile),
            "PYTHONPLATLIBDIR": "lib64",
            "PYTHONWARNINGS": "error",
            "PYTHONDEVMODE": "1",
            "PYTHONINSPECT": "1",
            "PYTHONSAFEPATH": "0",
            "NIX_PYTHONPATH": str(hostile),
            "AGENT_SKILLS_ROOT": str(hostile),
        }
        old_cwd = Path.cwd()
        os.chdir(home)
        started = time.monotonic()
        try:
            params = StdioServerParameters(command=command, args=[], env=env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    missing = EXPECTED - names
                    if missing:
                        raise AssertionError(f"missing tools: {sorted(missing)}")
                    result = await client.call_tool("get_status", {})
                    if result.isError:
                        raise AssertionError(result)
                    payload = json.loads(next(item.text for item in result.content
                                              if item.type == "text"))
                    if payload.get("state") != "unavailable":
                        raise AssertionError(payload)
                    if payload.get("reason") != "no supported harness in process ancestry":
                        raise AssertionError(payload)
                    if nix_path_marker.exists():
                        raise AssertionError("ambient NIX_PYTHONPATH executed a .pth file")
        finally:
            os.chdir(old_cwd)
        print(f"package MCP probe passed in {time.monotonic() - started:.3f}s")


if __name__ == "__main__":
    if len(sys.argv) != 3 or not all(Path(value).is_absolute() for value in sys.argv[1:]):
        raise SystemExit("usage: test_package.py /absolute/harness-control /absolute/module-dir")
    with tempfile.TemporaryDirectory(prefix="harness-control-negative-") as directory:
        hostile = Path(directory)
        (hostile / "harness_identity.py").write_text(
            "raise AssertionError('ambient identity reader imported')\n"
        )
        negative_env = dict(
            os.environ,
            PYTHONPATH=os.pathsep.join((str(hostile), sys.argv[2])),
            AGENT_SKILLS_ROOT=str(hostile),
        )
        negative = subprocess.run(
            [sys.executable, "-m", "server"], env=negative_env,
            input=b"", capture_output=True, timeout=10,
        )
        if negative.returncode == 0 or b"ambient identity reader imported" not in negative.stderr:
            raise AssertionError("negative wrapper control did not detect ambient Python import")
    asyncio.run(probe(sys.argv[1]))
