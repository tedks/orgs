"""The collector is piped over ssh and run by whatever python3 a host has.
Long-lived hosts can still run Python 3.6, so that is the floor, enforced
statically here. `TIER_DRIFT_FLOOR_HOST=<host>` additionally runs it for
real over ssh on a host at the floor."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "tier_drift" / "collector.py"
FLOOR = (3, 6)

# Parse cleanly on 3.6 but fail there at runtime.
POST_FLOOR_ATTRS = {
    "removeprefix": (3, 9),
    "removesuffix": (3, 9),
    "fromisoformat": (3, 7),
    "isascii": (3, 7),
}
POST_FLOOR_MODULES = {
    "dataclasses": (3, 7),
    "contextvars": (3, 7),
    "graphlib": (3, 9),
    "tomllib": (3, 11),
}


def tree():
    return ast.parse(SRC.read_text(), feature_version=FLOOR)


def test_parses_under_the_floor_grammar():
    tree()  # raises SyntaxError on walrus, match, positional-only, etc.


def test_imports_are_stdlib_only_and_absolute():
    stdlib = sys.stdlib_module_names
    for node in ast.walk(tree()):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import would break when piped over ssh"
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            assert top in stdlib, f"{name} is not stdlib; the collector must be self-contained"
            assert top not in POST_FLOOR_MODULES, f"{name} needs python {POST_FLOOR_MODULES[top]}"


def test_no_post_floor_apis():
    # feature_version does not reject every newer construct (e.g. the 3.8
    # f"{x=}" specifier); test_runs_on_a_real_floor_host is the backstop.
    for node in ast.walk(tree()):
        if isinstance(node, ast.Attribute) and node.attr in POST_FLOOR_ATTRS:
            raise AssertionError(
                f"line {node.lineno}: .{node.attr} needs python {POST_FLOOR_ATTRS[node.attr]}"
            )


def test_no_annotations():
    # PEP 585/604 annotations (list[str], X | None) evaluate at def time on 3.6
    for node in ast.walk(tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args.args + node.args.kwonlyargs
            assert node.returns is None and all(a.annotation is None for a in args), (
                f"line {node.lineno}: keep the collector annotation-free"
            )
        if isinstance(node, ast.AnnAssign):
            raise AssertionError(f"line {node.lineno}: annotated assignment")


@pytest.mark.skipif(
    not os.environ.get("TIER_DRIFT_FLOOR_HOST"), reason="set TIER_DRIFT_FLOOR_HOST=<host> to run"
)
def test_runs_on_a_real_floor_host():
    host = os.environ["TIER_DRIFT_FLOOR_HOST"]
    # ssh joins its arguments into ONE remote shell command, so anything with
    # shell metacharacters (`;`, parentheses) must not be passed bare. -V needs
    # no quoting at all. Python 3.6 prints the version to stdout, older to stderr.
    probe = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "python3", "-V"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    version = (probe.stdout or probe.stderr).strip()
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "python3", "-"],
        input=SRC.read_text(),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, f"collector failed on {host} ({version}):\n{result.stderr}"
    assert '"schema": 1' in result.stdout
