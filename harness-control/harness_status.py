"""Pure parsers for the private Claude statusline snapshot (schema version 1).

Callers bind the expected session independently and load JSON themselves. A
snapshot records the last statusline invocation, not a live provider query;
observed_at is Unix seconds and must accompany every displayed meter. No
missing, malformed or expired window can be interpreted as unused quota.

Published upstream fields: https://code.claude.com/docs/en/statusline
"""

import math
import re


_SESSION_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_BUCKETS = ("five_hour", "seven_day", "spend_limit")
_MAX_TIMESTAMP = 253402300799  # Last Unix second representable in year 9999.


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: object, maximum: float | None = None) -> int | float | None:
    if type(value) not in (int, float):
        return None
    # Avoid float conversion of arbitrarily large JSON integers.
    if value < 0 or value > 1e100 or not math.isfinite(value):
        return None
    return value if maximum is None or value <= maximum else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 4096 else None


def _envelope(snapshot: object, expected_session_id: str) -> dict:
    result = {
        "state": "unavailable", "source": "claude_statusline",
        "provider": "anthropic", "observed_at": None,
    }
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        return {**result, "reason": "invalid_snapshot"}
    if not isinstance(expected_session_id, str) or not _SESSION_ID.fullmatch(expected_session_id):
        return {**result, "reason": "invalid_session_id"}
    if snapshot.get("session_id") != expected_session_id:
        return {**result, "reason": "session_mismatch"}
    observed_at = _number(snapshot.get("observed_at"), _MAX_TIMESTAMP)
    if observed_at is None:
        return {**result, "reason": "missing_observation_time"}
    return {**result, "state": "available", "observed_at": observed_at}


def parse_claude_status(snapshot: object, expected_session_id: str) -> dict:
    """Return session/model/context fields, or an explicit unavailable reason.

    Percentages are numbers in [0, 100]. When only one percentage is known,
    derive the other; do not infer a fresh context from missing token counts.
    """
    result = _envelope(snapshot, expected_session_id)
    if result["state"] != "available":
        return result
    model = _object(snapshot.get("model"))
    context = _object(snapshot.get("context_window"))
    used = _number(context.get("used_percentage"), 100)
    remaining = _number(context.get("remaining_percentage"), 100)
    if remaining is None and used is not None:
        remaining = 100 - used
    if used is None and remaining is not None:
        used = 100 - remaining
    size = context.get("context_window_size")
    if type(size) is not int or size <= 0:
        size = None
    return {
        **result, "session_id": expected_session_id,
        "cwd": _text(snapshot.get("cwd")),
        "model": {"id": _text(model.get("id")), "display_name": _text(model.get("display_name"))},
        "context_window": {"size_tokens": size, "used_percentage": used, "remaining_percentage": remaining},
    }


def parse_claude_usage(snapshot: object, expected_session_id: str, *, now: float | None = None) -> dict:
    """Return supported quota buckets; absent/invalid/expired buckets are unknown.

    Supply current Unix seconds as ``now`` to detect a window that has reset
    since the statusline ran. Without it, expiry is checked at observed_at.
    Subscription windows describe provider-wide usage, not this session's
    consumption. The gateway spend limit may exceed 100 percent used.
    """
    result = _envelope(snapshot, expected_session_id)
    if result["state"] != "available":
        return result
    if now is not None and _number(now, _MAX_TIMESTAMP) is None:
        return {**result, "state": "unavailable", "reason": "invalid_current_time"}
    limits = _object(snapshot.get("rate_limits"))
    windows = []
    for bucket in _BUCKETS:
        window = _object(limits.get(bucket))
        used = _number(window.get("used_percentage"), None if bucket == "spend_limit" else 100)
        resets_at = _number(window.get("resets_at"), _MAX_TIMESTAMP)
        expired = resets_at is not None and resets_at <= (result["observed_at"] if now is None else now)
        available = used is not None and resets_at is not None and not expired
        windows.append({
            "bucket": bucket,
            "scope": "gateway_spend_limit" if bucket == "spend_limit" else "provider_subscription",
            "state": "available" if available else "unavailable",
            "reason": None if available else ("window_expired" if expired else "not_reported_or_invalid"),
            "used_percentage": used if available else None,
            "remaining_percentage": max(0, 100 - used) if available else None,
            "resets_at": resets_at,
        })
    available = any(window["state"] == "available" for window in windows)
    return {**result, "state": "available" if available else "unavailable",
            "reason": None if available else "no_current_windows", "windows": windows}
