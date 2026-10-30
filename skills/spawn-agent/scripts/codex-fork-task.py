#!/usr/bin/env python3
"""Task snapshot and ancestry validation for optional Codex fork preparation."""

import argparse
import json
from pathlib import Path
import sys
import uuid


def task_text(path):
    raw = Path(path).read_bytes()
    if not raw or len(raw) >= 32768 or b"\0" in raw:
        raise ValueError("fork task must be nonempty UTF-8, without NUL, and under 32768 bytes")
    return raw.decode("utf-8")


def child_id(path, parent):
    with Path(path).open("rb") as stream:
        line = stream.readline(1024 * 1024)
    if not line.endswith(b"\n"):
        raise ValueError("child session metadata is incomplete or too large")
    record = json.loads(line)
    payload = record["payload"]
    child = str(uuid.UUID(payload["id"]))
    parent = str(uuid.UUID(parent))
    if (record["type"] != "session_meta" or child == parent
            or str(uuid.UUID(payload["forked_from_id"])) != parent):
        raise ValueError("rollout is not a distinct fork of the requested parent")
    return child


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("task")
    prepare = sub.add_parser("compact")
    prepare.add_argument("policy")
    prepare.add_argument("task")
    prepare.add_argument("output")
    identity = sub.add_parser("child")
    identity.add_argument("rollout")
    identity.add_argument("parent")
    args = parser.parse_args()
    if args.action == "preflight":
        task_text(args.task)
    elif args.action == "compact":
        policy = Path(args.policy).read_text(encoding="utf-8")
        task = task_text(args.task)
        Path(args.output).write_text(
            policy + "\n\nThe next assignment follows. Use it to decide what inherited context to preserve. "
            "Summarize context for this assignment; do not execute it during compaction. "
            "It will be delivered as a new user message after compaction.\n\n" + task,
            encoding="utf-8")
    elif args.action == "child":
        print(child_id(args.rollout, args.parent))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
