"""Read-only, content-free projection of Codex rollout observations.

Rollouts are an unstable local format (observed with codex-cli 0.157.1), not
an API. The caller must associate the file with its live harness first; this
module never infers session identity from modification time or search. The one
exception is ``newest_account_quota``, which searches rollouts only for the
account-scoped meter (it returns no identity, paths or content, and modification
time merely bounds and orders the candidate files). That scan assumes one
OpenAI account per CODEX_HOME (rollouts carry no account id) and follows a
symlinked ``sessions`` root, as ``read_codex_status`` does (same user). Timestamps
describe observations, not freshness guarantees. Token accounting cannot prove
current context remaining, especially across compaction or an active turn.
"""

from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import stat
from collections.abc import Iterable


_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
               "output_tokens", "reasoning_output_tokens", "total_tokens")


def _text(value):
    return value if isinstance(value, str) and value and len(value) <= 4096 else None


def _integer(value):
    return value if type(value) is int and value >= 0 else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value if parsed.tzinfo is not None else None
    except ValueError:
        return None


_PLAN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")


def _plan_type(value):
    return value if isinstance(value, str) and _PLAN.fullmatch(value) else None


def _credits(value):
    """Booleans only. The credit balance is private and is never projected."""
    value = value if isinstance(value, dict) else {}
    return {key: value.get(key) if type(value.get(key)) is bool else None
            for key in ("has_credits", "unlimited")}


def _quota_bucket(quota, stamp, provider, now):
    """Project one raw rate_limits dict to (bucket key, public bucket)."""
    bucket = _text(quota.get("limit_id"))
    evaluated_at = now.timestamp()
    # A legacy snapshot without a bucket ID has explicitly unknown scope.
    return bucket or "unknown", {
        "limit_id": bucket, "limit_name": _text(quota.get("limit_name")),
        "plan_type": _plan_type(quota.get("plan_type")),
        "credits": _credits(quota.get("credits")),
        "scope": "account", "provider": provider,
        "observed_at": stamp, "evaluated_at": now.isoformat(),
        "primary": _window(quota.get("primary"), stamp, evaluated_at),
        "secondary": _window(quota.get("secondary"), stamp, evaluated_at)}


def _tokens(value):
    if not isinstance(value, dict):
        return None
    result = {key: _integer(value.get(key)) for key in _TOKEN_KEYS}
    return result if result["total_tokens"] is not None else None


def _window(value, observed_at, now):
    if not isinstance(value, dict):
        return None
    used = value.get("used_percent")
    if type(used) not in (float, int) or not 0 <= used <= 100 or not math.isfinite(used):
        used = None
    minutes = _integer(value.get("window_minutes"))
    reset = _integer(value.get("resets_at"))
    if minutes == 0:
        minutes = None
    if reset is not None and not 0 < reset <= 253402300799:  # latest UTC datetime
        reset = None
    observed = (datetime.fromisoformat(observed_at.replace("Z", "+00:00")).timestamp()
                if observed_at is not None else None)
    state = "unavailable"
    if (used is not None and minutes is not None and reset is not None
            and observed is not None and observed <= now and observed < reset):
        state = "expired" if reset <= now else "observed"
    return {"state": state, "historical_used_percent": used,
            "used_percent": used if state == "observed" else None,
            "remaining_percent": 100 - used if state == "observed" else None,
            "window_minutes": minutes, "resets_at": reset}


def parse_rollout(lines: Iterable[str | None], expected_session_id: str | None = None, *,
                  expected_source: str | None = None, now: datetime | None = None) -> dict:
    """Project complete JSONL records; ignore an unfinished trailing record.

    Requires an authoritative session_meta record first. A CLI fork may retain
    later inherited session_meta rows; they never replace that first identity.
    Malformed complete records and a
    mismatched expected UUID fail closed with no partial identity/status data.
    Unknown record types and all conversation content are discarded. A missing
    quota update preserves the last observation, not an invented fresh value.
    Expired/invalid quota windows expose historical usage separately and never
    expose remaining quota. ``now`` permits deterministic offline evaluation.
    The reader uses None for a skipped record: invalidate token accounting,
    without inventing a compaction event or changing the authoritative identity.
    """
    def failure(reason):
        return {"state": "unsupported", "source": "codex_rollout", "reason": reason}

    if expected_session_id is not None and (
            not isinstance(expected_session_id, str) or not _ID.fullmatch(expected_session_id)):
        return failure("invalid_expected_session_id")
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        return failure("invalid_observation_time")
    evaluated_at = now.timestamp()
    result = {"state": "observed", "source": "codex_rollout", "session_id": None,
              "cwd": None, "model": None, "model_provider": None,
              "identity_observed_at": None, "model_observed_at": None,
              "token_usage": None, "quota_buckets": {},
              "context_remaining": None, "context_remaining_state": "unsupported",
              "compaction": {"event_count": 0, "last_timestamp": None}}
    incomplete = False
    initial_source = None
    for line in lines:
        if line is None:
            result["token_usage"] = None
            continue
        if incomplete:
            return failure("incomplete_nonfinal_record")
        if not line.endswith("\n"):
            incomplete = True
            continue  # the writer has not committed this JSONL record yet
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            return failure("malformed_record")
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            return failure("malformed_record")
        kind, payload = record.get("type"), record["payload"]
        stamp = _timestamp(record.get("timestamp"))
        if kind == "session_meta":
            if result["session_id"] is not None:
                if initial_source != "cli":
                    return failure("inherited_metadata_without_cli_root")
                continue
            sid = payload.get("id")
            if not isinstance(sid, str) or not _ID.fullmatch(sid):
                return failure("invalid_session_meta")
            if expected_session_id is not None and sid.lower() != expected_session_id.lower():
                return failure("session_id_mismatch")
            if expected_source is not None and payload.get("source") != expected_source:
                return failure("session_source_mismatch")
            initial_source = payload.get("source")
            result.update(session_id=sid.lower(), cwd=_text(payload.get("cwd")),
                          model_provider=_text(payload.get("model_provider")),
                          identity_observed_at=stamp)
        elif result["session_id"] is None:
            return failure("missing_session_meta")
        elif kind == "turn_context":
            result.update(model=_text(payload.get("model")), model_observed_at=stamp,
                          cwd=_text(payload.get("cwd")))
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info")
            if isinstance(info, dict):
                result["token_usage"] = {"observed_at": stamp,
                    "total": _tokens(info.get("total_token_usage")),
                    "last": _tokens(info.get("last_token_usage")),
                    "context_window": _integer(info.get("model_context_window"))}
            quota = payload.get("rate_limits")
            if isinstance(quota, dict):
                key, projected = _quota_bucket(quota, stamp, result["model_provider"], now)
                result["quota_buckets"][key] = projected
        elif kind == "compacted":
            result["compaction"]["event_count"] += 1
            result["compaction"]["last_timestamp"] = stamp
            # Pre-compaction accounting cannot describe the new context.
            result["token_usage"] = None
    if result["session_id"] is None:
        return failure("missing_session_meta")
    return result


def _codex_home_candidate(pid, home, proc):
    """CODEX_HOME from the pinned process, else its HOME/.codex, else home/.codex.

    May return a relative path; raises OSError/RuntimeError on unreadable input.
    """
    environment = dict(item.split(b"=", 1) for item in
                       (proc / str(pid) / "environ").read_bytes().split(b"\0") if b"=" in item)
    configured = environment.get(b"CODEX_HOME")
    if configured:
        return Path(configured.decode("utf-8", "surrogateescape"))
    pinned_home = environment.get(b"HOME")
    if pinned_home:
        home = Path(pinned_home.decode("utf-8", "surrogateescape"))
    else:
        home = Path.home() if home is None else home
    return home / ".codex"


def codex_home_for(pid: int, home: Path | None = None, *, proc: Path = Path("/proc")) -> Path | None:
    """Absolute CODEX_HOME of the pinned process, or None when not determinable."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        codex_home = _codex_home_candidate(pid, home, proc)
    except (OSError, ValueError, UnicodeError, RuntimeError):
        return None
    return codex_home if codex_home.is_absolute() else None


def read_codex_status(pid: int, home: Path | None = None, *, proc: Path = Path("/proc"),
                      max_bytes: int = 128 * 1024 * 1024,
                      max_line_bytes: int = 4 * 1024 * 1024) -> dict:
    """Read the unique writable CLI rollout held by the pinned native process.

    CODEX_HOME comes only from that process's environment, falling back to its
    HOME/.codex, then ``home/.codex``. Read-only picker descriptors do not establish ownership. An
    empty writable descriptor is unclassified, so identity remains temporarily
    unavailable rather than risking selection of an old root during a switch.

    Read the identity header plus at most max_bytes from the tail. Oversized
    non-header records are skipped and invalidate earlier token accounting;
    fields absent from the scanned window stay
    unknown. ``history_complete`` and ``compaction.count_scope`` distinguish
    scanned-window counts from complete-file counts. No whole-file scan is
    required for a large session. rollout_path is private integration metadata.
    """
    def failure(reason):
        return {"state": "unsupported", "source": "codex_rollout", "reason": reason}

    if type(pid) is not int or pid <= 0:
        return failure("invalid_pid")
    if (type(max_bytes) is not int or max_bytes <= 0
            or type(max_line_bytes) is not int or max_line_bytes <= 0):
        return failure("invalid_read_limits")
    candidates = {}
    try:
        process_dir = proc / str(pid)
        codex_home = _codex_home_candidate(pid, home, proc)
        if not codex_home.is_absolute():
            return failure("relative_codex_home_unsupported")
        sessions = (codex_home / "sessions").resolve()
        for fd in (process_dir / "fd").iterdir():
            try:
                path = Path(os.readlink(fd))
            except FileNotFoundError:
                continue
            if not path.name.startswith("rollout-") or path.suffix != ".jsonl":
                continue
            if not path.resolve().is_relative_to(sessions):
                continue
            try:
                fields = dict(line.split(":", 1) for line in
                              (process_dir / "fdinfo" / fd.name).read_text().splitlines() if ":" in line)
                flags = int(fields["flags"].strip(), 8)
                if flags & os.O_ACCMODE == os.O_RDONLY:
                    continue
                descriptor_stat = fd.stat()
                if not stat.S_ISREG(descriptor_stat.st_mode):
                    return failure("invalid_rollout_file")
                with fd.open("rb") as stream:
                    descriptor_stat = os.fstat(stream.fileno())
                    if not stat.S_ISREG(descriptor_stat.st_mode):
                        return failure("invalid_rollout_file")
                    raw = stream.readline(max_line_bytes + 1)
            except FileNotFoundError:
                continue  # this descriptor demonstrably closed during discovery
            if not raw:
                return failure("unclassified_empty_writable_rollout")
            if len(raw) > max_line_bytes or not raw.endswith(b"\n"):
                return failure("invalid_session_meta")
            meta = json.loads(raw)
            if not isinstance(meta, dict) or meta.get("type") != "session_meta":
                return failure("invalid_session_meta")
            payload = meta.get("payload")
            if not isinstance(payload, dict):
                return failure("invalid_session_meta")
            if payload.get("source") != "cli":
                continue
            sid = payload.get("id")
            if not isinstance(sid, str) or not _ID.fullmatch(sid):
                return failure("invalid_session_meta")
            candidates[(descriptor_stat.st_dev, descriptor_stat.st_ino)] = (
                fd, path, sid, descriptor_stat.st_size)
        if len(candidates) != 1:
            return failure("ambiguous_or_missing_live_rollout")
        selected_identity, candidate = next(iter(candidates.items()))
        fd, path, sid, initial_size = candidate
        with fd.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != selected_identity:
                return failure("rollout_descriptor_changed")
            header = stream.readline(max_line_bytes + 1)
            if len(header) > max_line_bytes or not header.endswith(b"\n"):
                return failure("invalid_session_meta")
            if len(header) > initial_size:
                return failure("rollout_changed_during_read")
            start = max(len(header), initial_size - max_bytes)
            complete_history = start == len(header)
            stream.seek(start - 1)
            skipping = stream.read(1) != b"\n"
            skipped_records = False

            def lines():
                nonlocal skipping, skipped_records
                yield header.decode("utf-8")
                remaining = initial_size - start
                while remaining > 0:
                    raw = stream.readline(min(max_line_bytes + 1, remaining))
                    if not raw:
                        raise ValueError("truncated")
                    remaining -= len(raw)
                    if skipping or len(raw) > max_line_bytes:
                        skipping = not raw.endswith(b"\n")
                        skipped_records = True
                        yield None  # the skipped record may have been compaction
                        continue
                    if not raw.endswith(b"\n"):
                        break  # partial trailing UTF-8 is not yet a JSONL record
                    yield raw.decode("utf-8")
            result = parse_rollout(lines(), expected_session_id=sid, expected_source="cli")
            if os.fstat(stream.fileno()).st_size < initial_size:
                return failure("rollout_changed_during_read")
        if result["state"] == "observed":
            result["rollout_path"] = str(path)
            result["history_complete"] = complete_history and not skipped_records
            result["read_window"] = {"snapshot_bytes": initial_size, "tail_start": start,
                                     "tail_bytes": initial_size - start,
                                     "oversized_or_partial_leading_records_skipped": skipped_records}
            result["compaction"]["count_scope"] = (
                "complete_file" if result["history_complete"] else "scanned_window")
        return result
    except (OSError, ValueError, UnicodeError, KeyError, RuntimeError):
        return failure("unreadable_or_invalid_rollout")


_MAX_AGE = timedelta(days=8)
_MAX_ENTRIES = 100000  # hard cap on rollout entries examined per call
_SKEW_SECONDS = 120  # clock/mtime skew margin for the early-stop bound
_HEADER_BYTES = 64 * 1024  # only model_provider is needed from the first line
_SEARCH_BYTES = 8 * 1024 * 1024  # per-file backward-search cap


class _Budget:
    """Global count of directory entries pulled; the cap is _MAX_ENTRIES."""

    def __init__(self):
        self.examined = 0
        self.truncated = False

    def spend(self) -> bool:
        if self.examined >= _MAX_ENTRIES:
            self.truncated = True
            return False
        self.examined += 1
        return True


def _numbered_dirs(parent: Path, width: int, budget: _Budget):
    """Real (non-symlink) subdirectories named by a fixed-width integer, descending.

    Entries are pulled lazily and counted against ``budget``.
    """
    found = []
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if not budget.spend():
                    break
                if (len(entry.name) == width and entry.name.isascii() and entry.name.isdigit()
                        and entry.is_dir(follow_symlinks=False)):
                    found.append((int(entry.name), Path(entry.path)))
    except OSError:
        return []
    return sorted(found, reverse=True)


def _day_files(sessions: Path, budget: _Budget):
    """(directory, name) of entries in valid sessions/YYYY/MM/DD dirs, newest day first.

    Walks only that layout (names are validated as real calendar dates); files
    outside it are ignored. Directories are not pruned by date. Every entry is
    pulled lazily and counted against ``budget``; iteration stops at the cap.
    """
    for year, year_dir in _numbered_dirs(sessions, 4, budget):
        for month, month_dir in _numbered_dirs(year_dir, 2, budget):
            for day, day_dir in _numbered_dirs(month_dir, 2, budget):
                try:
                    date(year, month, day)
                except ValueError:
                    continue
                try:
                    with os.scandir(day_dir) as entries:
                        for entry in entries:
                            if not budget.spend():
                                return
                            yield day_dir, entry.name
                except OSError:
                    continue
                if budget.truncated:
                    return
            if budget.truncated:
                return
        if budget.truncated:
            return


def _rollout_candidates(sessions: Path, now: datetime, max_files: int):
    """((mtime, path) of regular rollout-*.jsonl modified in the last 8 days, newest first, truncated).

    ``truncated`` is True when the _MAX_ENTRIES examination cap was hit.
    """
    cutoff = (now - _MAX_AGE).timestamp()
    found = []
    budget = _Budget()
    for directory, name in _day_files(sessions, budget):
        if not name.startswith("rollout-") or not name.endswith(".jsonl"):
            continue
        path = directory / name
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mtime < cutoff:
                continue
            path.resolve().relative_to(sessions)  # ValueError when it escapes
        except (OSError, ValueError, RuntimeError):
            continue
        found.append((info.st_mtime, path))
    found.sort(key=lambda item: item[0], reverse=True)
    return found[:max_files], budget.truncated


def _stamp_value(value):
    stamp = _timestamp(value)
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None


def _scan_tail(data: bytes, max_line_bytes: int, newest: dict):
    for line in data.split(b"\n"):
        if b"rate_limits" not in line or len(line) > max_line_bytes:
            continue
        try:
            record = json.loads(line)
        except (ValueError, RuntimeError):  # RecursionError on deeply nested input
            continue
        if not isinstance(record, dict) or record.get("type") != "event_msg":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        quota = payload.get("rate_limits")
        stamp = _timestamp(record.get("timestamp"))
        when = _stamp_value(stamp)
        if not isinstance(quota, dict) or when is None:
            continue
        key = _text(quota.get("limit_id")) or "unknown"
        if key not in newest or when >= newest[key][0]:
            newest[key] = (when, stamp, quota)


def _file_quota(path: Path, tail_bytes: int, max_line_bytes: int, search_bytes: int = _SEARCH_BYTES,
                expected: frozenset = frozenset()):
    """(provider, {bucket: (when, stamp, quota)}, covered) from one rollout; None if unreadable.

    Reads the last ``tail_bytes``; when they hold no valid meter, or lack some
    ``expected`` bucket, the window doubles backwards up to ``search_bytes`` (only
    the newly exposed earlier bytes are read each round). ``covered`` is False
    when no meter was found although earlier, unread bytes remain.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            return None
        provider = None
        header = stream.readline(_HEADER_BYTES + 1)
        if header.endswith(b"\n") and len(header) <= _HEADER_BYTES:
            try:
                meta = json.loads(header)
                if isinstance(meta, dict) and meta.get("type") == "session_meta" \
                        and isinstance(meta.get("payload"), dict):
                    provider = _text(meta["payload"].get("model_provider"))
            except (ValueError, RuntimeError):
                pass
        size = info.st_size
        window = tail_bytes
        limit = max(tail_bytes, search_bytes)
        raw, hi = b"", size  # raw holds bytes [lo, size)
        while True:
            start = max(0, size - window)
            lo = max(0, start - 1)
            stream.seek(lo)
            raw = stream.read(hi - lo) + raw
            hi = lo
            data = raw
            if start > 0:
                # Drop a leading partial line unless the tail begins on a boundary.
                data = data[1:] if data[:1] == b"\n" else data[data.find(b"\n") + 1:] if b"\n" in data else b""
            data = data[:data.rfind(b"\n") + 1]  # an unfinished trailing line is not a record
            newest = {}
            _scan_tail(data, max_line_bytes, newest)
            if start == 0 or (newest and expected <= newest.keys()):
                return provider, newest, True
            if window >= limit:
                return provider, newest, False  # expected buckets may lie in unread bytes
            window = min(window * 2, limit)


def newest_account_quota(codex_home: Path, *, now: datetime | None = None, max_files: int = 32,
                         tail_bytes: int = 1024 * 1024,
                         max_line_bytes: int = 4 * 1024 * 1024,
                         search_bytes: int = _SEARCH_BYTES,
                         expected_buckets: Iterable[str] | None = None) -> dict:
    """Newest rate_limits observation per bucket across this CODEX_HOME's rollouts.

    The OpenAI meter is account-wide but each session only records its own last
    event, so an idle session's meter goes stale. This searches the most recently
    modified rollouts (at most ``max_files``, modified within 8 days) and picks
    per bucket the record with the greatest valid timestamp. Assumes one OpenAI
    account per CODEX_HOME (rollouts carry no account id) and follows a symlinked
    ``sessions`` root (same user, as ``read_codex_status`` does).

    Only ``sessions/YYYY/MM/DD/rollout-*.jsonl`` (valid calendar-date names) is
    read; files elsewhere are ignored. A long-lived session keeps appending
    under its start day's directory, so directories are not pruned by date:
    every rollout entry is lstat'd (newest day first) and filtered by the 8-day
    mtime. At most ``_MAX_ENTRIES`` entries are examined; hitting that cap makes
    the result incomplete with reason ``too_many_rollouts``. Each file's
    first line (at most 64 KiB) supplies model_provider only. Its last
    ``tail_bytes`` are parsed; if they hold no valid meter the window grows
    backwards up to ``search_bytes`` (default 8 MiB). A file whose window still
    lacks the meter (or, with ``expected_buckets``, any expected bucket) although
    earlier bytes remain makes the result
    ``"incomplete": true`` with ``reason_incomplete``
    ``"file_without_meter_in_window"``; an older file's meter must then not be
    taken as complete. When ``expected_buckets`` is given and a file's window
    holds only some of them, the backward search in that file continues (same
    cap); buckets still unfound after the whole scan are listed in
    ``missing_buckets`` and mark the result incomplete. Partial/unfinished/malformed (including too deeply
    nested) lines are ignored.

    mtime only orders candidates and bounds the scan: a record cannot be newer
    than its file's mtime, so scanning stops (``stopped_early``) once the best
    timestamp of every bucket found is at least 120 s past the next candidate's
    mtime. With ``expected_buckets`` the scan continues until all of them are
    found; without it, it stops after at least one bucket, so ``account_latest``
    covers only the buckets seen. Rollouts copied with preserved mtimes
    (cp -p, rsync -t) can be missed. Returns no paths, session ids, cwd or
    content, and never the credit balance.
    """
    def unavailable(reason):
        return {"state": "unavailable", "source": "codex_rollouts_newest", "reason": reason}

    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        return unavailable("invalid_observation_time")
    if any(type(value) is not int or value <= 0
           for value in (max_files, tail_bytes, max_line_bytes, search_bytes)):
        return unavailable("invalid_read_limits")
    try:
        expected = frozenset(expected_buckets) if expected_buckets is not None else set()
        if not all(isinstance(name, str) for name in expected):
            return unavailable("invalid_expected_buckets")
    except TypeError:
        return unavailable("invalid_expected_buckets")
    try:
        sessions = (Path(codex_home) / "sessions").resolve()
        if not sessions.is_dir():
            return unavailable("sessions_unreadable")
        paths, truncated = _rollout_candidates(sessions, now, max_files)
    except (OSError, ValueError, UnicodeError, RuntimeError):
        return unavailable("sessions_unreadable")
    best = {}
    scanned = 0
    stopped_early = False
    incomplete = False
    for mtime, path in paths:
        if (best and expected <= best.keys()
                and min(entry[0] for entry in best.values()).timestamp() >= mtime + _SKEW_SECONDS):
            stopped_early = True
            break
        try:
            found = _file_quota(path, tail_bytes, max_line_bytes, search_bytes, expected)
        except (OSError, ValueError, UnicodeError, RuntimeError):
            continue
        if found is None:
            continue
        scanned += 1
        provider, newest, covered = found
        incomplete = incomplete or not covered
        for key, (when, stamp, quota) in newest.items():
            if key not in best or when > best[key][0]:
                best[key] = (when, stamp, quota, provider)
    if not best:
        return unavailable("too_many_rollouts" if truncated else "file_without_meter_in_window"
                           if incomplete else "no_recent_rate_limits")
    buckets = {}
    for key, (_, stamp, quota, provider) in best.items():
        buckets[key] = _quota_bucket(quota, stamp, provider, now)[1]
    result = {"state": "observed", "source": "codex_rollouts_newest", "scope": "account",
              "quota_buckets": buckets, "files_scanned": scanned,
              "stopped_early": stopped_early, "incomplete": incomplete or truncated,
              "evaluated_at": now.isoformat()}
    missing = sorted(expected - best.keys())
    if missing:
        result.update(incomplete=True, missing_buckets=missing)
    if truncated:
        result["reason_incomplete"] = "too_many_rollouts"
    elif incomplete:
        result["reason_incomplete"] = "file_without_meter_in_window"
    elif missing:
        result["reason_incomplete"] = "expected_buckets_missing"
    return result
