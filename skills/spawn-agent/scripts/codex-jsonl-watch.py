#!/usr/bin/env python3
"""One-shot watchers for structured Codex rollout events.

The follower consumes only newline-terminated JSONL records.  Bytes after the
last newline stay buffered across polls, so a record observed halfway through
an append is neither parsed nor discarded.  Codex may rewrite a rollout to its
compacted form when the next turn starts; the follower restarts at byte zero
after that shrink and lets its structured record predicate reject history.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any


SESSION_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class WatchError(Exception):
    """A user-facing watcher failure."""


class WatchTimeout(Exception):
    """The requested rollout event did not arrive before the deadline."""


def resolve_rollout(value: str, codex_home: Path) -> Path:
    """Resolve an explicit rollout path or a Codex session UUID."""
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate.resolve()

    if not SESSION_ID.fullmatch(value):
        raise WatchError(f"rollout file not found and value is not a session UUID: {value}")

    sessions = codex_home / "sessions"
    session_id = value.lower()
    matches = list(sessions.glob(f"*/*/*/rollout-*-{session_id}.jsonl"))
    if len(matches) != 1:
        raise WatchError(
            f"expected one rollout for session {value}, found {len(matches)} under {sessions}"
        )
    return matches[0].resolve()


def complete_record_offset(path: Path) -> int:
    """Return the byte after the final newline, preserving any partial record."""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        if end == 0:
            return 0

        block_size = 8192
        position = end
        while position:
            size = min(block_size, position)
            position -= size
            stream.seek(position)
            block = stream.read(size)
            newline = block.rfind(b"\n")
            if newline >= 0:
                return position + newline + 1
        return 0


def follow_records(
    path: Path, offset: int, timeout: float, *, restart_on_shrink: bool = False
) -> Iterator[dict[str, Any]]:
    """Yield complete JSON objects appended at or after offset."""
    deadline = time.monotonic() + timeout
    pending = b""

    while True:
        try:
            size = path.stat().st_size
            if size < offset:
                if not restart_on_shrink:
                    raise WatchError(f"rollout was truncated while being watched: {path}")
                # A manual compaction can replace the inherited rollout with a
                # smaller compacted transcript as the next turn begins. Any
                # partial bytes belong to the old file image, so discard them
                # and rescan the new image. Recap matching remains safe because
                # it requires the unique prefix on an assistant final_answer.
                offset = 0
                pending = b""
            with path.open("rb") as stream:
                stream.seek(offset)
                chunk = stream.read()
        except FileNotFoundError:
            chunk = b""

        if chunk:
            # Advance by bytes read, not by complete lines. Otherwise the next
            # poll would duplicate a partial trailing write in `pending`.
            offset += len(chunk)
            pending += chunk
            lines = pending.split(b"\n")
            pending = lines.pop()
            for raw_line in lines:
                if raw_line.endswith(b"\r"):
                    raw_line = raw_line[:-1]
                if not raw_line:
                    continue
                try:
                    record = json.loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # A newline-terminated malformed record cannot become valid
                    # through a later append; skip it without stopping the feed.
                    continue
                if isinstance(record, dict):
                    yield record

        if time.monotonic() >= deadline:
            raise WatchTimeout
        time.sleep(0.25)


def final_message(record: dict[str, Any], marker: str) -> str | None:
    payload = record.get("payload")
    if not isinstance(payload, dict) or not (
        record.get("type") == "response_item"
        and payload.get("type") == "message"
        and payload.get("role") == "assistant"
        and payload.get("phase") == "final_answer"
    ):
        return None

    content = payload.get("content")
    if not isinstance(content, list):
        return None
    text = "".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict)
        and part.get("type") == "output_text"
        and isinstance(part.get("text", ""), str)
    )
    return text if text.startswith(marker) else None


def positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timeout must be a positive number") from error
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive number")
    return timeout


def nonnegative_offset(value: str) -> int:
    try:
        offset = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("offset must be a non-negative integer") from error
    if offset < 0:
        raise argparse.ArgumentTypeError("offset must be a non-negative integer")
    return offset


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"),
        help="Codex state directory used when resolving a session UUID",
    )
    subparsers = result.add_subparsers(dest="command", required=True)

    cursor = subparsers.add_parser(
        "cursor", help="print the safe byte offset after the last complete record"
    )
    cursor.add_argument("rollout", help="rollout JSONL path or session UUID")

    recap = subparsers.add_parser(
        "recap", help="print the first matching final assistant recap, exactly once"
    )
    recap.add_argument("rollout", help="rollout JSONL path or session UUID")
    recap.add_argument("marker", help="unique prefix required at the start of the final answer")
    recap.add_argument("timeout", nargs="?", type=positive_timeout, default=3600.0)
    recap.add_argument("--after-byte", type=nonnegative_offset, default=0)

    compaction = subparsers.add_parser(
        "compaction", help="wait for a context_compacted event after a byte offset"
    )
    compaction.add_argument("rollout", help="rollout JSONL path or session UUID")
    compaction.add_argument("after_byte", type=nonnegative_offset)
    compaction.add_argument("timeout", nargs="?", type=positive_timeout, default=600.0)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        path = resolve_rollout(args.rollout, args.codex_home)
        if args.command == "cursor":
            print(complete_record_offset(path))
            return 0

        if args.command == "recap" and (not args.marker or "\n" in args.marker):
            raise WatchError("recap marker must be one non-empty line")

        offset = args.after_byte
        for record in follow_records(
            path, offset, args.timeout, restart_on_shrink=args.command == "recap"
        ):
            if args.command == "recap":
                message = final_message(record, args.marker)
                if message is not None:
                    sys.stdout.write(message)
                    sys.stdout.flush()
                    return 0
            elif isinstance(record.get("payload"), dict) and (
                record.get("type") == "compacted" or (
                    record.get("type") == "event_msg"
                    and record["payload"].get("type") == "context_compacted"
                )
            ):
                return 0
        return 1
    except WatchTimeout:
        noun = "recap" if args.command == "recap" else "compaction"
        print(f"Error: timed out after {args.timeout:g}s waiting for {noun} in {path}", file=sys.stderr)
        return 124
    except (OSError, WatchError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
