#!/usr/bin/env python3
"""Detect observed quota replenishment and submit each event at most once.

The input is token-usage's raw ``meters --check --json`` object, with the
producer's additive account_scope and account_epoch fields on each reading.
This module does not infer account identity or provider fetch success.
"""

import argparse
import fcntl
import hashlib
import json
import math
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
FRESH_FOR = timedelta(minutes=20)
WINDOWS = {
    "openai": ("openai", 10080),
    "openai.secondary": ("openai", 300),
    "anthropic.seven_day": ("anthropic", 10080),
    "anthropic.five_hour": ("anthropic", 300),
}
ACCEPTED = "accepted"
UNKNOWN = "unknown"


def timestamp(value, *, allow_epoch=False):
    if allow_epoch and isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if math.isfinite(value):
                return datetime.fromtimestamp(value, UTC)
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def valid_percent(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 100
    except (OverflowError, TypeError):
        return False


def valid_reading(name, raw, now):
    """Return a normalized observation or None; invalid input never advances state."""
    if name not in WINDOWS or not isinstance(raw, dict):
        return None
    provider, minutes = WINDOWS[name]
    scope, epoch = raw.get("account_scope"), raw.get("account_epoch")
    if not all(isinstance(v, str) and v and v == v.strip() for v in (scope, epoch)):
        return None
    source = raw.get("source")
    if not isinstance(source, str) or not source or source != source.strip():
        return None
    used = raw.get("used_percent")
    if not valid_percent(used):
        return None
    window = raw.get("window_minutes")
    if type(window) is not int or window != minutes:
        return None
    observed = timestamp(raw.get("observed"))
    reset = timestamp(raw.get("resets_at"), allow_epoch=True)
    if (observed is None or reset is None or observed > now
            or now - observed > FRESH_FOR or reset <= observed):
        return None
    return {
        "provider": provider, "name": name, "account_scope": scope,
        "account_epoch": epoch, "source": source, "window_minutes": minutes,
        "observed": observed.isoformat(), "reset_at": reset.isoformat(),
        "used_percent": float(used),
    }


def rejection_reason(name, raw, now):
    """Small operator signal; raw provider/account values never enter logs."""
    if not isinstance(raw, dict):
        return "invalid_record"
    if not all(isinstance(raw.get(k), str) and raw[k] and raw[k] == raw[k].strip()
               for k in ("account_scope", "account_epoch")):
        return "missing_identity"
    if type(raw.get("window_minutes")) is not int or raw["window_minutes"] != WINDOWS[name][1]:
        return "unsupported_window"
    observed = timestamp(raw.get("observed"))
    if observed is None:
        return "invalid_observed"
    if observed > now:
        return "future_observation"
    if now - observed > FRESH_FOR:
        return "stale_observation"
    return "invalid_meter"


def load_state(path):
    try:
        with path.open(encoding="utf-8") as stream:
            state = json.load(stream)
    except FileNotFoundError:
        return {"version": 1, "series": {}, "events": {}}
    if (not isinstance(state, dict) or state.get("version") != 1
            or not isinstance(state.get("series"), dict)
            or not isinstance(state.get("events"), dict)):
        raise ValueError("invalid monitor state; refusing to overwrite it")
    return state


def save_state(path, state):
    """Replace and fsync before any possible external send."""
    fd, temp = tempfile.mkstemp(prefix=".quota-reset-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def series_key(item):
    # One active baseline per meter. Old source/account identities cannot be
    # resurrected by switching away and back; event dedup remains permanent.
    return item["name"]


def event_key(item):
    raw = json.dumps([item["provider"], item["name"], item["account_scope"],
                      item["account_epoch"], item["reset_at"]], separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def process(meters, state_path, sender, now=None):
    """Serialize observers and senders; ambiguous sends remain in_flight/unknown.

    ``sender(event)`` returns ACCEPTED only for transport acceptance; any
    other return is UNKNOWN. Exceptions leave the durable in_flight intent.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None or not isinstance(meters, dict):
        raise ValueError("expected aware time and a meter object")
    now = now.astimezone(UTC)
    state_path = Path(state_path)
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(state_path.parent.stat().st_mode) & 0o077:
        raise ValueError("state directory must be private (mode 0700 or stricter)")
    lock_path = state_path.with_name(state_path.name + ".lock")
    counts = {"accepted": 0, "unknown": 0, "detected": 0, "rejected": {}}
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state(state_path)
        for name in WINDOWS:
            item = valid_reading(name, meters.get(name), now)
            if item is None:
                if name in meters:
                    counts["rejected"][name] = rejection_reason(name, meters[name], now)
                continue
            key = series_key(item)
            previous = state["series"].get(key)
            identity = [item["account_scope"], item["account_epoch"], item["source"]]
            if previous is not None and previous["identity"] != identity:
                previous = None  # scope, epoch or source transition: baseline only
            if previous is not None and timestamp(item["observed"]) <= timestamp(previous["observed"]):
                continue
            observed = timestamp(item["observed"])
            reset = timestamp(item["reset_at"])
            if previous is None:
                current = {"observed": item["observed"], "reset_at": item["reset_at"],
                           "used_percent": item["used_percent"], "identity": identity}
                event = None
            else:
                prior_reset = timestamp(previous["reset_at"])
                decreased = previous["used_percent"] > item["used_percent"]
                crossed = prior_reset <= observed and reset > prior_reset
                event = item if crossed and decreased else None
                current = {"observed": item["observed"], "reset_at": item["reset_at"],
                           "used_percent": item["used_percent"], "identity": identity}
            state["series"][key] = current
            if event is None:
                save_state(state_path, state)
                continue
            eid = event_key(event)
            if eid in state["events"]:
                save_state(state_path, state)
                continue
            event = {**event, "id": eid, "previous_used_percent": previous["used_percent"],
                     "previous_observed": previous["observed"],
                     "previous_reset_at": previous["reset_at"],
                     "remaining_percent": 100.0 - event["used_percent"]}
            event["message"] = (f"{event['provider']} {event['name']} quota replenishment observed since "
                                f"{previous['observed']}; current observation {event['observed']}: "
                                f"{event['remaining_percent']:g}% remaining.")
            state["events"][eid] = {"event": event, "delivery": "in_flight"}
            save_state(state_path, state)  # durable intent precedes the call
            counts["detected"] += 1
            result = sender(event)
            delivery = ACCEPTED if result == ACCEPTED else UNKNOWN
            state["events"][eid]["delivery"] = delivery
            save_state(state_path, state)
            counts[delivery] += 1
    return counts


def command_sender(path):
    def send(event):
        try:
            result = subprocess.run([path], input=json.dumps(event), text=True,
                                    stdout=subprocess.DEVNULL, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return UNKNOWN
        return ACCEPTED if result.returncode == 0 else UNKNOWN
    return send


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--notify-command", required=True,
                        help="one executable; event JSON on stdin; exit zero means transport acceptance")
    parser.add_argument("--meters-file", type=Path,
                        help="isolated fixture input; default runs token-usage meters --check --json")
    args = parser.parse_args(argv)
    try:
        if args.meters_file:
            meters = json.loads(args.meters_file.read_text(encoding="utf-8"))
        else:
            result = subprocess.run(["token-usage", "meters", "--check", "--json"],
                                    capture_output=True, text=True, timeout=60, check=False)
            if result.returncode:
                print("quota-reset: token-usage meter check failed", file=sys.stderr)
                return 2
            meters = json.loads(result.stdout)
        counts = process(meters, args.state_file, command_sender(args.notify_command))
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"quota-reset: {error}", file=sys.stderr)
        return 2
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
