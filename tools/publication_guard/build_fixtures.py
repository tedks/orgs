#!/usr/bin/env python3
"""Build two synthetic count fixtures without accessing any transcripts."""
import argparse
from datetime import date, datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import random
import uuid

DAY = date(2032, 6, 15)
HOME = "/ho" + "me/user"
PROJECTS = ("project-a", "project-b")


def stamp(time):
    return time.isoformat(timespec="seconds").replace("+00:00", "Z")


def claude_rows(rng, allowed, start):
    for index, project in enumerate(PROJECTS):
        cwd = f"{HOME}/{project}"
        session = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        allowed.add(session)
        encoded = cwd.replace("/", "-")
        file = f".claude/projects/{encoded}/{session}.jsonl"
        for turn in range(3):
            request = "req_" + f"{rng.getrandbits(96):024x}"
            allowed.add(request)
            time = start + timedelta(minutes=4 + index + turn * 11)
            usage = {
                "input_tokens": rng.randint(21, 89),
                "cache_creation_input_tokens": rng.randint(80, 240),
                "cache_read_input_tokens": rng.randint(450, 1600),
                "output_tokens": rng.randint(17, 81),
            }
            # Two chunks of one request exercise per-field maxima.
            for final in (False, True) if turn == 0 else (True,):
                message_id = str(uuid.UUID(int=rng.getrandbits(128), version=4))
                allowed.add(message_id)
                yield {"file": file, "rec": {
                    "type": "assistant", "timestamp": stamp(time), "sessionId": session,
                    "uuid": message_id, "requestId": request, "cwd": cwd, "isSidechain": False,
                    "message": {
                        "model": "claude-synthetic",
                        "stop_reason": "end_turn" if final else None,
                        "usage": usage if final else dict(usage, output_tokens=1),
                    },
                }}


def codex_rows(rng, allowed, start):
    for index, project in enumerate(PROJECTS):
        cwd = f"{HOME}/{project}"
        opened = start + timedelta(minutes=index)
        # A generated UUIDv7 with a timestamp prefix and seeded remaining bits.
        millis = int(opened.timestamp()) * 1000
        session = str(uuid.UUID(fields=(
            millis >> 16, millis & 0xffff, 0x7000 | rng.getrandbits(12),
            0x80 | rng.getrandbits(6), rng.getrandbits(8), rng.getrandbits(48),
        )))
        allowed.update((session, session.replace("-", "")))
        file = f".codex/sessions/{opened:%Y/%m/%d}/rollout-{opened:%Y-%m-%dT%H-%M-%S}-{session}.jsonl"
        yield {"file": file, "rec": {
            "type": "session_meta", "timestamp": stamp(opened), "payload": {
                "id": session, "cwd": cwd, "originator": "fixture", "source": "cli",
            },
        }}
        yield {"file": file, "rec": {
            "type": "turn_context", "timestamp": stamp(opened),
            "payload": {"cwd": cwd, "model": "gpt-synthetic"},
        }}
        totals = dict.fromkeys((
            "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_output_tokens", "total_tokens",
        ), 0)
        for turn in range(3):
            time = opened + timedelta(minutes=(5, 15, 45)[turn])
            input_tokens = rng.randint(1400, 2300)
            output_tokens = rng.randint(29, 133)
            last = dict(
                input_tokens=input_tokens,
                cached_input_tokens=rng.randint(200, 1000),
                cache_write_input_tokens=0,
                output_tokens=output_tokens,
                reasoning_output_tokens=11,
                total_tokens=input_tokens + output_tokens,
            )
            totals = {key: total + last[key] for key, total in totals.items()}
            payload = {
                "type": "token_count",
                "info": {
                    "last_token_usage": last, "total_token_usage": totals,
                    "model_context_window": 32000,
                },
                "rate_limits": {"primary": {
                    "used_percent": rng.randint(5, 40), "window_minutes": 10080,
                    "resets_at": int((opened + timedelta(days=3)).timestamp()),
                }},
            }
            yield {"file": file, "rec": {
                "type": "event_msg", "timestamp": stamp(time), "payload": payload,
            }}
            if turn == 1:
                # The same cumulative counters were emitted again.
                yield {"file": file, "rec": {
                    "type": "event_msg", "timestamp": stamp(time + timedelta(seconds=10)),
                    "payload": payload,
                }}


def build(output, allow_list, seed, day=DAY):
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    names = [output / f"{provider}-{day}.jsonl.gz" for provider in ("claude", "codex")]
    if allow_list.resolve() in {name.resolve() for name in names}:
        raise ValueError("The allow list needs a path distinct from both fixtures.")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    allowed = {HOME, *(f"{HOME}/{project}" for project in PROJECTS)}
    for path, generate in zip(names, (claude_rows, codex_rows)):
        with path.open("wb") as file, gzip.GzipFile(
            filename="", mode="wb", fileobj=file, mtime=0,
        ) as stream:
            for row in generate(rng, allowed, start):
                stream.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
    allow_list.write_text("".join(f"{entry}\n" for entry in sorted(allowed)), encoding="utf-8")
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-list", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--day", type=date.fromisoformat, default=DAY,
                        help="synthetic fixture date in YYYY-MM-DD")
    args = parser.parse_args()
    if not date(2005, 1, 1) <= args.day <= date(2100, 1, 1):
        parser.error("--day must be between 2005-01-01 and 2100-01-01")
    build(args.output, args.allow_list, args.seed, args.day)


if __name__ == "__main__":
    main()
