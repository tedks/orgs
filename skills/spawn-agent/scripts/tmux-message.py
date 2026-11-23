#!/usr/bin/env python3
"""Blocking tmux delivery. Screen evidence is heuristic, not atomic input ownership.

Only the live input is compared for typing; output may move freely. One lock
serializes cooperating senders through receipt, and one paste belongs to one
invocation. Uncertainty is returned to the caller rather than delegated silently.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("screen", Path(__file__).with_name("claude-send-screen.py"))
styles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(styles)

PROMPT = re.compile(r"^\s*([›❯])(?:[ \u00a0]|$)(.*)$")
PASTE = re.compile(r"\[Pasted (?:text|Text)(?:[^\]\n]*)\]", re.I)
# Match after normalized() removes composer whitespace, including row breaks.
IMAGE_PLACEHOLDER = re.compile(r"\[Image#[0-9]+\]", re.I)
FOOTER = re.compile(r"^\s*(?:.*(?:Context \d+%|\d+% context left| · )|tab to queue message|\? for shortcuts|esc to interrupt)", re.I)
MODAL = re.compile(r"Quick safety check|Yes, I trust this folder|No, exit|Do you trust the contents|Press enter to continue|Would you like to (?:proceed|run)|Do you want to (?:proceed|allow)|Allow once|Esc to cancel", re.I)
QUEUE = re.compile(r"Messages to be submitted|queued messages?", re.I)


CLAUDE_RESUME = re.compile(r"Resume this session with:\s*\n\s*claude --resume ([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?=\s|$)", re.I)


def resume_records(frame):
    return Counter(session.lower() for session in CLAUDE_RESUME.findall(styles.strip_ansi(frame.history or frame.raw)))


# Codex 0.170.0 renders these as standalone info/error history rows.
COMPACT_COMPLETED = re.compile(
    r"• Context compacted(?: · (?:[0-9]+h [0-9]{2}m [0-9]{2}s|[0-9]+m [0-9]{2}s|[0-9]+s))?"
)
COMPACT_REFUSED = "■ '/compact' is disabled while a task is in progress."


def compact_records(frame, inp):
    """Count exact notices above the composer, with visible counts separately."""
    visible = frame.raw.splitlines()
    history = (frame.history or frame.raw).splitlines()
    first_visible = len(history) - len(visible)
    notices, visible_notices = Counter(), Counter()
    for index, raw in enumerate(history[:first_visible + inp.start]):
        row = styles.strip_ansi(raw).rstrip(" ")
        if COMPACT_COMPLETED.fullmatch(row):
            outcome = "completed"
        elif row == COMPACT_REFUSED:
            outcome = "refused"
        else:
            continue
        notice = (outcome, row)
        notices[notice] += 1
        if index >= first_visible:
            visible_notices[notice] += 1
    return notices, visible_notices


def normalized(text):
    # Line wrapping, indentation and terminal padding do not identify a message.
    return "".join(text.split())


@dataclass
class Frame:
    raw: str
    x: int
    y: int
    history: str = ""
    width: int = 0
    height: int = 0


@dataclass
class Input:
    kind: str
    text: str = ""
    start: int = 0
    end: int = 0
    cursor: tuple = (0, 0)
    harness: str = ""

    def fingerprint(self):
        # Relative cursor: output scrolling above the input is not human typing.
        return self.kind, self.text, self.cursor, self.harness


DIAGNOSTIC_SCHEMA = "tmux-message-structure-v1"
DIAGNOSTIC_REASONS = frozenset({
    "none",
    "mixed-input-after-paste", "receipt-timeout", "paste-not-observed",
    "input-changed-after-paste", "input-changed-before-enter", "modal-after-paste",
    "modal", "human-typing", "existing-input", "unsupported-layout",
    "compact-requires-codex", "compact-refused", "conflicting-command-evidence",
    "pane-width-changed",
    "unstable-composer", "input-changed-before-paste", "image-placeholder",
    "receiver-changed", "unresolved-paste", "attempt-state-unavailable",
})
DIAGNOSTIC_STYLES = frozenset({"bold", "dim", "italic", "underline", "inverse", "fg", "bg"})
DIAGNOSTIC_MAX_ROWS = 12
DIAGNOSTIC_MAX_CELLS = 160
DIAGNOSTIC_MAX_SAMPLES = 16
DIAGNOSTIC_MAX_BYTES = 65536
DIAGNOSTIC_MAX_ELAPSED_MS = 2147483647
DIAGNOSTIC_MAX_STYLE_SPANS = 32


def _diagnostic_sgr(flags, params):
    """Normalize numeric SGR to a small vocabulary; never retain parameters."""
    result = set(flags)
    index = 0
    while index < len(params):
        code = params[index]
        if code == 0:
            result.clear()
        elif code in (1, 2, 3, 4, 7):
            result.add({1: "bold", 2: "dim", 3: "italic", 4: "underline", 7: "inverse"}[code])
        elif code == 22:
            result.difference_update(("bold", "dim"))
        elif code in (23, 24, 27):
            result.discard({23: "italic", 24: "underline", 27: "inverse"}[code])
        elif code == 39:
            result.discard("fg")
        elif code == 49:
            result.discard("bg")
        elif code in (38, 48):
            result.add("fg" if code == 38 else "bg")
            # Extended RGB/index parameters are colors, not independent SGR
            # style toggles. Keep neither their values nor their positions.
            if index + 1 < len(params) and params[index + 1] == 5:
                if index + 2 >= len(params):
                    return None
                index += 2
            elif index + 1 < len(params) and params[index + 1] == 2:
                if index + 4 >= len(params):
                    return None
                index += 4
            else:
                return None
        elif 30 <= code <= 37 or 90 <= code <= 97:
            result.add("fg")
        elif 40 <= code <= 47 or 100 <= code <= 107:
            result.add("bg")
        index += 1
    return sorted(result & DIAGNOSTIC_STYLES)


def _diagnostic_row(raw):
    """Return width-preserving placeholders and allowlisted style spans only."""
    layout, spans, flags = [], [], []
    cells = 0
    index = 0
    truncated = False
    while index < len(raw):
        char = raw[index]
        if char == "\x1b":
            match = re.match(r"\x1b\[([0-9;]{0,32})m", raw[index:])
            if match is None:
                return None
            params = [int(part or "0") for part in match.group(1).split(";")]
            flags = _diagnostic_sgr(flags, params)
            if flags is None:
                return None
            index += len(match.group(0))
            continue
        if char == "\t":
            replacement = "\t"
            width = 1
        elif char == " ":
            replacement = " "
            width = 1
        elif unicodedata.category(char) in {"Mn", "Me"} or unicodedata.combining(char):
            index += 1
            continue
        elif (unicodedata.category(char) in {"Cc", "Cf", "Cs", "Co", "Cn"}
              or char in {"\u2028", "\u2029"}):
            return None
        elif char.isspace():
            replacement = " "
            width = 1
        else:
            width = max(1, min(2, styles.cell_width(char)))
            replacement = "#" * width
        if cells + width > DIAGNOSTIC_MAX_CELLS:
            truncated = True
            break
        if flags and (not spans or spans[-1]["end"] != cells or spans[-1]["flags"] != flags):
            if len(spans) >= DIAGNOSTIC_MAX_STYLE_SPANS:
                truncated = True
                break
        layout.append(replacement)
        if flags:
            if spans and spans[-1]["end"] == cells and spans[-1]["flags"] == flags:
                spans[-1]["end"] += width
            else:
                spans.append({"start": cells, "end": cells + width, "flags": list(flags)})
        cells += width
        index += 1
    return {"layout": "".join(layout), "styles": spans}, truncated


def structural_sample(frame, inp, phase, elapsed_ms):
    """Sanitize an already sampled composer; never store raw pane text/escapes."""
    kind = inp.kind if inp.kind in {"empty", "text", "suggestion", "modal", "unknown"} else "unknown"
    harness = inp.harness if inp.harness in {"codex", "claude"} else "unknown"
    width = frame.width if isinstance(frame.width, int) and 0 <= frame.width <= 1000 else 0
    height = frame.height if isinstance(frame.height, int) and 0 <= frame.height <= 1000 else 0
    cursor = [min(1000, max(0, value)) if isinstance(value, int) else 0 for value in inp.cursor[:2]]
    sample = {"phase": phase, "elapsed_ms": min(DIAGNOSTIC_MAX_ELAPSED_MS, max(0, int(elapsed_ms))),
              "dimensions": [width, height], "cursor": cursor, "kind": kind,
              "harness": harness, "structure": "unavailable", "rows": [],
              "markers": [], "predicates": {}}
    if kind in {"unknown", "modal"} or not 0 <= inp.start < inp.end:
        return sample
    # composer() uses splitlines(). If control characters change that row
    # count, refuse structure rather than indexing a different raw region.
    split = frame.raw.splitlines()
    newline_rows = frame.raw.split("\n")
    if newline_rows and newline_rows[-1] == "":
        newline_rows.pop()
    if (len(split) != len(newline_rows)
            or len(styles.strip_ansi(frame.raw).splitlines()) != len(split)
            or inp.end > len(split)):
        return sample
    raw_rows = split[inp.start:inp.end]
    first = styles.strip_ansi(raw_rows[0])
    expected_prompt = "›" if harness == "codex" else "❯" if harness == "claude" else ""
    if (not expected_prompt or not (first.startswith(expected_prompt + " ")
                                or first.startswith(expected_prompt + "\u00a0"))):
        return sample
    truncated = len(raw_rows) > DIAGNOSTIC_MAX_ROWS
    for raw in raw_rows[:DIAGNOSTIC_MAX_ROWS]:
        result = _diagnostic_row(raw)
        if result is None:
            sample["rows"] = []
            return sample
        row, cut = result
        sample["rows"].append(row)
        truncated |= cut
    if not sample["rows"]:
        return sample
    sample["structure"] = "truncated" if truncated else "available"
    # Marker names and bounded numeric counts are protocol structure, not text.
    if harness in {"codex", "claude"}:
        sample["markers"].append({"type": harness + "_prompt", "count": 1})
    for name, pattern in (
        ("pasted_content", r"\[Pasted Content ([0-9]{1,7}) chars\]"),
        ("pasted_text", r"\[Pasted text #[0-9]{1,7} \+([0-9]{1,7}) lines\]"),
        ("image", r"\[Image #([0-9]{1,7})\]"),
    ):
        for index, match in enumerate(re.finditer(pattern, inp.text, re.I)):
            if index >= 4:
                break
            sample["markers"].append({"type": name, "count": min(100000, int(match.group(1)))})
    return sample


class StructuralDiagnostic:
    """Bounded sanitized observations in memory; no disk access until finish."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.started = clock, clock()
        self.pre_paste = None
        self.post_paste = []
        self.events = []
        self.truncated = False

    def observe(self, frame, inp, phase):
        try:
            sample = structural_sample(frame, inp, phase, (self.clock() - self.started) * 1000)
        except DeliveryError:
            raise
        except Exception:
            sample = {"phase": phase, "elapsed_ms": 0, "dimensions": [0, 0],
                      "cursor": [0, 0], "kind": "unknown", "harness": "unknown",
                      "structure": "unavailable", "rows": [], "markers": [], "predicates": {}}
        if phase == "post_paste":
            self.post_paste.append(sample)
            if len(self.post_paste) > DIAGNOSTIC_MAX_SAMPLES:
                self.post_paste.pop(0)
                self.truncated = True
        else:
            self.pre_paste = sample

    def predicate(self, name, value):
        if name not in {"input_evidence", "pre_enter_ownership", "receipt_new", "command_completion", "ready"}:
            return
        sample = self.post_paste[-1] if self.post_paste else self.pre_paste
        if sample is not None:
            sample["predicates"][name] = bool(value)

    def event(self, name):
        if name in {"paste", "enter"} and len(self.events) < 8:
            self.events.append({"type": name, "elapsed_ms": min(DIAGNOSTIC_MAX_ELAPSED_MS,
                                                                     max(0, int((self.clock() - self.started) * 1000)))})

    def to_bytes(self, outcome, reason, input_method, enters):
        record = {"schema": DIAGNOSTIC_SCHEMA,
                  "outcome": outcome if outcome in {"delivered", "ambiguous", "deferred"} else "other",
                  "reason": reason if reason in DIAGNOSTIC_REASONS else "other",
                  "input_method": input_method if input_method in {"paste", "typed"} else "other",
                  "enters": min(2, max(0, int(enters))), "pre_paste": self.pre_paste,
                  "post_paste": list(self.post_paste), "events": list(self.events),
                  "truncated": self.truncated}
        while True:
            data = json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            if len(data) + 1 <= DIAGNOSTIC_MAX_BYTES:
                return data + b"\n"
            if record["post_paste"]:
                record["post_paste"].pop(0)
                record["truncated"] = True
            else:
                record["pre_paste"] = None
                record["truncated"] = True


class DiagnosticFile:
    """A pre-reserved owner-only file; cleanup is bound to its inode."""
    def __init__(self, directory_fd, fd, name):
        self.directory_fd, self.fd, self.name = directory_fd, fd, name
        identity = os.fstat(fd)
        self.identity = (identity.st_dev, identity.st_ino)
        self.closed = False

    @classmethod
    def reserve(cls, path):
        if not isinstance(path, Path) or not path.is_absolute() or len(path.parts) < 3:
            raise ValueError("unsafe-diagnostic-path")
        parts = path.parts[1:]
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("unsafe-diagnostic-path")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_fd = os.open("/", flags)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            mode = os.fstat(directory_fd)
            if (mode.st_uid != os.getuid() or not stat.S_ISDIR(mode.st_mode)
                    or stat.S_IMODE(mode.st_mode) != 0o700):
                raise ValueError("unsafe-diagnostic-path")
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_fd)
            try:
                reserved = cls(directory_fd, fd, parts[-1])
            except Exception:
                os.close(fd)
                raise
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                reserved.abort()
                raise
            return reserved
        except Exception:
            try:
                os.close(directory_fd)
            except OSError:
                pass
            raise

    def _name_is_own(self):
        try:
            now = os.stat(self.name, dir_fd=self.directory_fd, follow_symlinks=False)
            return (now.st_dev, now.st_ino) == self.identity
        except OSError:
            return False

    def _remove_if_own_name(self):
        if self._name_is_own():
            try:
                os.unlink(self.name, dir_fd=self.directory_fd)
            except OSError:
                pass

    def abort(self):
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.fd)
        except OSError:
            pass
        self._remove_if_own_name()
        try:
            os.close(self.directory_fd)
        except OSError:
            pass

    def finish(self, diagnostic, outcome, reason, input_method, enters):
        try:
            data = diagnostic.to_bytes(outcome, reason, input_method, enters)
            if not self._name_is_own():
                raise OSError("diagnostic-name-changed")
            offset = 0
            while offset < len(data):
                written = os.write(self.fd, data[offset:])
                if written <= 0:
                    raise OSError("diagnostic-write-failed")
                offset += written
            if not self._name_is_own():
                raise OSError("diagnostic-name-changed")
            os.close(self.fd)
            os.close(self.directory_fd)
            self.closed = True
            return True
        except Exception:
            # Transport has already decided its result. A late diagnostic
            # failure, including an interruption here, cannot revise it.
            self.abort()
            return False


def composer(frame, expected_codex_text=None, expected_codex_footer=None):
    lines = styles.strip_ansi(frame.raw).splitlines()
    raw = frame.raw.splitlines()
    # Keep the pre-existing dialog guard on Codex and unknown layouts. A
    # measured live Claude composer is the only frame that can override broad
    # footer wording such as "esc to cancel".
    if not styles.claude_composer_frame(frame.raw, frame.y) and MODAL.search("\n".join(lines[-25:])):
        return Input("modal")
    if styles.dialog_active(frame.raw, frame.y):
        return Input("modal")
    # Locate a prompt whose input contains the cursor. Do not assume a fixed
    # row, model name, footer spacing, or number of wrapped rows.
    candidates = [(i, PROMPT.match(line)) for i, line in enumerate(lines) if i <= frame.y and PROMPT.match(line)]
    for idx, match in reversed(candidates):
        glyph, first = match.groups()
        if glyph == "❯":
            shape = styles.claude_composer_frame(frame.raw, frame.y)
            if shape is None or shape[0] != idx:
                continue
            end = shape[1]
            harness = "claude"
        else:
            footers = [i for i in range(idx + 1, len(lines)) if FOOTER.match(lines[i])]
            if footers:
                end = footers[0]
            else:
                # An idle Codex placeholder with the cursor at its start is
                # still a composer when the single status row changes wording.
                # Require the measured blank separator and indented final
                # status row; arbitrary transcript/choice rows stay unknown.
                ghost = (first in {"", "Ask Codex to do anything"}
                         and (not first or styles.dim_span(raw[idx], first))
                         and frame.x == 2)
                status = next((i for i in range(len(lines) - 1, idx, -1)
                               if lines[i].strip()), -1)
                if (not styles.sgr_span(raw[idx], "›", "bold")
                        or status < idx + 2 or lines[status - 1].strip()
                        or not lines[status].startswith("  ")
                        or any(glyph in lines[status] for glyph in "›❯")):
                    continue
                content = lines[idx + 1:status - 1]
                pasted = "\n".join([first] + [row[2:] for row in content])
                marker = re.fullmatch(r"\[Pasted Content ([0-9]+) chars\]", pasted, re.I)
                counts = ({str(len(expected_codex_text)),
                           str(len(expected_codex_text.encode("utf-16-le")) // 2)}
                          if expected_codex_text is not None else set())
                own_paste = (expected_codex_footer == lines[status]
                             and expected_codex_text is not None
                             and (normalized(pasted) == normalized(expected_codex_text)
                                  or bool(marker and marker.group(1) in counts))
                             and all(not row or row.startswith("  ") for row in content)
                             and frame.y == status - 2
                             and frame.x == 2 + styles.cell_width(
                                 content[-1][2:] if content else first))
                if not ((ghost and frame.y == idx and not content)
                        or own_paste):
                    continue
                end = status
            harness = "codex"
        if not idx <= frame.y < end:
            continue
        parts = [first] + [line[2:] if line.startswith("  ") else line for line in lines[idx + 1:end]]
        text = "\n".join(parts).rstrip()
        cursor = (frame.x, frame.y - idx)
        kind = "empty" if not text.strip() else "text"
        if text and frame.y == idx and frame.x <= len(match.group(0)) - len(first):
            if harness == "codex" and styles.dim_span(raw[idx], first):
                kind = "empty"
                text = ""
            elif (harness == "claude" and
                  (first.startswith('Try ') or
                   (end == idx + 1 and styles.dim_span(raw[idx], first)))):
                # Claude also paints arbitrary idle suggestions in dim text.
                # Dim style is a heuristic: the reversible Space/BSpace
                # probe in ready() must verify that the text disappears
                # before any paste is authorized.
                kind = "suggestion"
        return Input(kind, text, idx, end, cursor, harness)
    return Input("unknown")


def compact_prompt_row(frame, inp):
    # The shared parser trims whitespace. Keep the prompt row untrimmed and
    # require exactly one empty separator between that row and its footer.
    if inp.end != inp.start + 2:
        return None
    rows = styles.strip_ansi(frame.raw).splitlines()
    return rows[inp.start] if not rows[inp.start + 1] else None


def compact_input_is_empty(frame, inp):
    if inp.kind != "empty" or inp.cursor != (2, 0):
        return False
    row = compact_prompt_row(frame, inp)
    return row is not None and not PROMPT.match(row).group(2).isspace()


def empty_composer(frame, inp):
    if inp.harness == "codex":
        return compact_input_is_empty(frame, inp)
    if inp.harness != "claude" or inp.kind != "empty" or inp.cursor != (2, 0):
        return False
    return (inp.end == inp.start + 1
            and not PROMPT.match(styles.strip_ansi(frame.raw).splitlines()[inp.start]).group(2))


def records(frame, inp, archived_codex_status=None):
    """Candidate receipts outside the live composer, with semantic row markers.

    A new occurrence is required relative to the pre-paste history. Assistant
    prose containing the text without a user/queue marker is not a receipt.
    """
    visible = frame.raw.splitlines()
    # History includes the visible screen. Cut off the live input using the
    # captured visible suffix instead of treating its prompt as submitted text.
    history = frame.history.splitlines() if frame.history else visible
    prefix_len = max(0, len(history) - len(visible))
    rows = history[:prefix_len + inp.start] if inp.kind not in {"unknown", "modal"} else history[:prefix_len]
    result = Counter()
    lines = [styles.strip_ansi(row) for row in rows]
    visible_plain = styles.strip_ansi(frame.raw).splitlines()
    observed_status = (visible_plain[inp.end] if inp.harness == "codex"
                       and 0 <= inp.end < len(visible_plain) else None)
    # A redraw can archive a still-unsent fallback composer while its live
    # status row changes and the current input becomes unknown. Keep the row
    # observed before paste as an exclusion in that case.
    composer_statuses = {status for status in (observed_status, archived_codex_status)
                         if status is not None}
    queued = False
    for index, line in enumerate(lines):
        if QUEUE.search(line):
            queued = True
            continue
        match = PROMPT.match(line)
        queue_match = re.match(r"^\s*↳\s?(.*)", line) if queued else None
        if not match and not queue_match:
            if line.strip() and not line.startswith("  "):
                queued = False
            continue
        kind = "queued" if queue_match else "submitted"
        text = queue_match.group(1) if queue_match else match.group(2)
        end = index + 1
        while end < len(lines) and lines[end].startswith("  ") and lines[end].strip():
            if FOOTER.match(lines[end]) or PROMPT.match(lines[end]) or re.match(r"^\s*↳", lines[end]):
                break
            text += "\n" + lines[end][2:].rstrip()
            end += 1
        following = next((row for row in lines[end:] if row.strip()), "")
        previous = next((row for row in reversed(lines[:index]) if row.strip()), "")
        # Full-screen redraw can archive an UNSENT input box in scrollback.
        # Its footer/rules still identify it as a composer, not a receipt.
        rule = lambda row: bool(row.strip()) and set(row.strip()) == {"─"}
        # The bold prompt, blank separator and indented next row can be either
        # an archived unsent Codex box or a genuine submitted row. When the
        # changed-footer fallback was used, neither is a proven receipt.
        archived_codex_box = (archived_codex_status is not None
                              and end < len(lines) and not lines[end].strip()
                              and styles.sgr_span(rows[index], "›", "bold")
                              and following.startswith("  ") and following.strip()
                              and not any(glyph in following for glyph in "›❯"))
        if kind == "submitted" and (FOOTER.match(following) or rule(following)
                                    or rule(previous) or following in composer_statuses
                                    or archived_codex_box):
            continue
        result[(kind, normalized(text))] += 1
    return result


def paste_evidence(inp, payload):
    if inp.kind != "text":
        return False
    if normalized(inp.text) == normalized(payload):
        return True
    # Codex also collapses a whole paste into a character-count marker.
    # Require the entire input to be that marker: surrounding text is mixed.
    content = re.fullmatch(r"\[Pasted Content ([0-9]+) chars\]", inp.text, re.I)
    if content:
        # Terminal clients count either Unicode code points or UTF-16 units.
        counts = {str(len(payload)), str(len(payload.encode("utf-16-le")) // 2)}
        return content.group(1) in counts
    # A newly introduced collapsed marker is sufficient evidence of our paste.
    # Any visible text surrounding it must be consistent with this payload.
    matches = list(PASTE.finditer(inp.text))
    if len(matches) != 1:
        return False
    m = matches[0]
    before, after = normalized(inp.text[:m.start()]), normalized(inp.text[m.end():])
    wanted = normalized(payload)
    return (len(before) + len(after) < len(wanted)
            and wanted.startswith(before) and wanted.endswith(after))


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from agent_skills_config import load_config, tmux_command


class DeliveryError(Exception):
    def __init__(self, reason, code=2):
        self.reason, self.code = reason, code


class Tmux:
    def __init__(self, target, *, socket=None):
        try:
            self.base = ["tmux", "-S", socket] if socket is not None else tmux_command()
        except (OSError, ValueError) as error:
            raise DeliveryError("tmux-context-unavailable") from error
        # Resolve and lock on the same selected server used for subsequent input.
        # A config edit between this selection and the child resolver cannot
        # redirect pane identity to another server with the same pane ID.
        resolver_env = dict(os.environ, AGENT_SKILLS_TMUX_SOCKET="")
        for name in ("SPAWN_TMUX_SOCKET", "SPAWN_TMUX_LABEL", "TMUX"):
            resolver_env.pop(name, None)
        if len(self.base) == 3:
            name = "SPAWN_TMUX_SOCKET" if self.base[1] == "-S" else "SPAWN_TMUX_LABEL"
            resolver_env[name] = self.base[2]
        try:
            self.identity = subprocess.run(
                [str(Path(__file__).with_name("tmux-resolve.sh")), target],
                check=True, capture_output=True, text=True, timeout=5, env=resolver_env).stdout.strip()
        except subprocess.CalledProcessError as error:
            raise DeliveryError("missing-or-ambiguous-target") from error
        if not re.fullmatch(r"\d+:%\d+", self.identity):
            raise DeliveryError("invalid-target")
        self.pane = self.identity.split(":")[1]
        self.receiver = None

    def run(self, *args):
        return subprocess.run(self.base + list(args), check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=5).stdout

    def receiver_identity(self, *, allow_dead=False):
        # list-panes and an exact row filter avoid display-message's fallback
        # on missing targets. A respawn can retain the pane ID but changes PID.
        fields = ("pid", "pane_id", "socket_path", "start_time", "pane_pid", "pane_tty", "pane_dead")
        fmt = "\t".join("#{" + name + "}" for name in fields)
        rows = self.run("list-panes", "-t", self.pane, "-F", fmt).splitlines()
        for row in rows:
            values = row.split("\t")
            if len(values) != len(fields) or ":".join(values[:2]) != self.identity:
                continue
            receiver = dict(zip(fields, values))
            dead = receiver.pop("pane_dead")
            if ((dead == "0" or (allow_dead and dead == "1")) and Path(receiver["socket_path"]).is_absolute()
                    and all(re.fullmatch(r"[1-9][0-9]*", receiver[k]) for k in ("start_time", "pane_pid"))
                    and receiver["pane_tty"]):
                return receiver
        raise DeliveryError("receiver-changed")

    def check_receiver(self, *, allow_dead=False):
        if (getattr(self, "receiver", None) is not None
                and self.receiver_identity(allow_dead=allow_dead) != self.receiver):
            raise DeliveryError("receiver-changed")

    def frame(self):
        # Recheck coordinates around capture; discard frames that scroll/resize
        # while being sampled. No application internals are involved.
        fmt = "#{cursor_x}:#{cursor_y}:#{pane_width}:#{pane_height}:#{pane_in_mode}"
        before = self.run("display-message", "-p", "-t", self.pane, fmt).strip()
        history = self.run("capture-pane", "-e", "-p", "-t", self.pane, "-S", "-2000")
        after = self.run("display-message", "-p", "-t", self.pane, fmt).strip()
        # A retained dead pane can show the original process's final exit
        # notice. Only capture is allowed after death, never key delivery.
        self.check_receiver(allow_dead=True)
        values = before.split(":")
        if before != after or len(values) != 5 or values[-1] != "0":
            return Frame("", -1, -1)
        raw = "\n".join(history.splitlines()[-int(values[3]):]) + "\n"
        try:
            width = int(values[2])
        except ValueError:
            width = 0  # Width was not required by the transport before diagnostics.
        return Frame(raw, int(values[0]), int(values[1]), history,
                     width, int(values[3]))

    def keys(self, *keys):
        self.check_receiver()
        self.run("send-keys", "-t", self.pane, *keys)

    def type_command(self, text):
        self.check_receiver()
        self.run("send-keys", "-t", self.pane, "-l", "--", text)

    def paste(self, path):
        name = "tmux-message-" + uuid.uuid4().hex
        self.run("load-buffer", "-b", name, str(path))
        try:
            self.check_receiver()
            self.run("paste-buffer", "-p", "-r", "-d", "-t", self.pane, "-b", name)
        finally:
            try:
                self.run("delete-buffer", "-b", name)
            except subprocess.CalledProcessError:
                pass


def read_response_rows(pane, socket):
    """Read visible response rows above recognized input, never send keys.

    This is the supported Python observation API. Unknown, modal, or moving
    frames return None; target/read failures are sanitized DeliveryError.
    """
    if (not isinstance(pane, str) or not re.fullmatch(r"%\d+", pane)
            or not isinstance(socket, str) or not Path(socket).is_absolute()):
        raise DeliveryError("invalid-observation-target")
    try:
        frame = Tmux(pane, socket=socket).frame()
        inp = composer(frame)
        if inp.kind in {"unknown", "modal"}:
            return None
        return styles.strip_ansi(frame.raw).splitlines()[:inp.start]
    except (subprocess.SubprocessError, OSError, ValueError, TypeError, AttributeError, LookupError) as error:
        raise DeliveryError("observation-read-failed") from error


@contextmanager
def pane_lock(identity, timeout):
    # Share the compatibility sender's namespace. This lock coordinates senders,
    # not humans, and needs no registry or persistent per-message state.
    directory = Path(os.environ.get("CLAUDE_SEND_LOCK_DIR", f"/tmp/claude-send-locks-{os.getuid()}"))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise DeliveryError("unsafe-lock-directory")
    directory.chmod(0o700)
    path = directory / (hashlib.sha256(identity.encode()).hexdigest() + ".lock")
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DeliveryError("sender-busy")
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        yield
    finally:
        os.close(fd)


ATTEMPT_ID = re.compile(r"[0-9a-f]{64}-[0-9a-f]{32}")
DISPOSITIONS = ("receipt-confirmed", "acknowledged", "draft-removed", "receiver-replaced")


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def private_pending(payload):
    directory = Path(tempfile.mkdtemp(prefix="tmux-message-"))
    path = directory / "message"
    try:
        write_private(path, payload.encode("utf-8"))
    except OSError:
        path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return path


class PasteJournal:
    """Owner-only attempts published before paste, with metadata-only resolution."""

    def __init__(self):
        state = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
        self.root = Path(state) / "tmux-message"
        if not self.root.is_absolute():
            raise DeliveryError("attempt-state-unavailable")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise DeliveryError("attempt-state-unavailable")

    @staticmethod
    def receiver_key(tmux):
        return hashlib.sha256(json.dumps(tmux.receiver, sort_keys=True).encode()).hexdigest()

    def unresolved(self, prefix=""):
        attempts = []
        for path in self.root.iterdir():
            name = path.name.removeprefix(".")
            if not name.startswith(prefix) or not ATTEMPT_ID.fullmatch(name) or path.is_symlink():
                continue
            if path.name.startswith("."):
                # A stopped sender may have published completion but not
                # removed the private bytes yet. No pane state is involved.
                try:
                    self.cleanup_completed(path)
                except OSError:
                    pass
            elif (path / "attempt.json").exists():
                try:
                    resolution = self.read_record(path, "resolution")
                except (FileNotFoundError, ValueError):
                    attempts.append(path)
                else:
                    disposition = resolution.get("disposition") if isinstance(resolution, dict) else None
                    if disposition in (*DISPOSITIONS, "transport-finished"):
                        try:
                            self.purge_resolved_payload(path)
                        except OSError:
                            pass  # Retain the disposition and retry cleanup on a later listing.
                    elif disposition != "enter-confirmed":
                        attempts.append(path)
        return sorted(attempts)

    def prepare(self, tmux, payload):
        path = self.root / (self.receiver_key(tmux) + "-" + uuid.uuid4().hex)
        path.mkdir(mode=0o700)
        record = {"version": 1, "id": path.name, "created_ns": time.time_ns(),
                  "receiver": tmux.receiver, "lock_identity": tmux.identity,
                  "sender": {"uid": os.getuid(), "pid": os.getpid(), "parent_pid": os.getppid(),
                             "tmux": os.environ.get("TMUX"), "pane": os.environ.get("TMUX_PANE")},
                  "pending_file": str(path / "message")}
        try:
            self.write_record(path, "attempt", record)
            write_private(path / "message", payload.encode("utf-8"))
            sync_directory(path)
            sync_directory(self.root)
            sync_directory(self.root.parent)
        except (DeliveryError, OSError):
            # No pane input has occurred. Reclaim the files from this attempt
            # if the filesystem is still writable.
            try:
                self.cleanup_completed(path)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def write_record(path, name, record):
        # Readers never see a partial JSON record. Serialize writes with the
        # same pane lock used for delivery, including offline resolution.
        temporary = path / (".record-" + uuid.uuid4().hex)
        try:
            write_private(temporary, (json.dumps(record) + "\n").encode())
            temporary.rename(path / (name + ".json"))
            sync_directory(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def read_record(path, name):
        return json.loads((path / (name + ".json")).read_text(encoding="utf-8"))

    def report(self, path):
        record = self.read_record(path, "attempt")
        try:
            record["outcome"] = self.read_record(path, "outcome")
        except FileNotFoundError:
            # A signal or crash can prevent a controlled outcome. The
            # write-ahead record establishes no Enter count or receiver state.
            record["outcome"] = None
        return record

    def discard(self, path):
        # Hide a conclusively finished attempt before deleting its payload.
        # A concurrent listing may have seen the old name and skip its removal.
        finished = path.with_name("." + path.name)
        try:
            path.rename(finished)
        except OSError:
            # Keep a terminal disposition if this volume permits updating
            # the record but not renaming the entire attempt directory.
            self.mark_finished(path, "transport-finished")
            self.purge_resolved_payload(path)
            return
        sync_directory(self.root)
        self.cleanup_completed(finished)

    def mark_finished(self, path, disposition):
        self.write_record(path, "resolution", {"disposition": disposition, "resolved_ns": time.time_ns()})

    @staticmethod
    def purge_resolved_payload(path):
        payload = path / "message"
        if payload.exists():
            # A listing can see the atomic resolution rename before the
            # resolving process fsyncs it. Flush it before erasing the bytes.
            sync_directory(path)
            payload.unlink(missing_ok=True)
            sync_directory(path)

    @staticmethod
    def cleanup_completed(finished):
        (finished / "message").unlink(missing_ok=True)
        (finished / "attempt.json").unlink(missing_ok=True)
        try:
            finished.rmdir()
        except FileNotFoundError:
            return  # Another reader completed the same cleanup.
        sync_directory(finished.parent)

    def resolve(self, attempt_id, disposition):
        path = self.root / attempt_id
        record = self.read_record(path, "attempt")
        with pane_lock(record["lock_identity"], 10):
            if not (path / "attempt.json").exists():
                raise DeliveryError("attempt-not-unresolved")
            try:
                resolution = self.read_record(path, "resolution")
            except FileNotFoundError:
                self.write_record(path, "resolution", {"disposition": disposition,
                                                       "resolved_ns": time.time_ns(), "pid": os.getpid()})
            else:
                if resolution["disposition"] != disposition:
                    raise DeliveryError("attempt-already-resolved")
            self.purge_resolved_payload(path)


class Sender:
    def __init__(self, tmux, options, payload, path, clock=time.monotonic, sleep=time.sleep,
                 diagnostic=None, journal=None):
        self.tmux, self.o, self.payload, self.path = tmux, options, payload, path
        self.clock, self.sleep = clock, sleep
        self.diagnostic = diagnostic
        self.diagnostic_phase = "readiness"
        self.pasted = False
        self.enters = 0
        self.enter_confirmed = False
        self.typed = getattr(options, "typed_command", False)
        self.verify_compact = getattr(options, "verify_compact", False)
        self.journal = journal
        self.attempt = None
        self.blocking_attempt = None
        self.codex_fallback_footer = None
        if self.typed and getattr(options, "literal_exit", False):
            raise DeliveryError("conflicting-input-modes")
        if self.typed and (len(payload.encode("utf-8")) > 200 or payload != payload.rstrip() or payload.endswith(";")):
            raise DeliveryError("unsupported-typed-command")
        if self.typed and not styles.slash_command_syntax(payload):
            raise DeliveryError("unsupported-typed-command")

    def input_evidence(self, inp):
        if self.typed:
            return inp.kind == "text" and inp.text == self.payload
        return paste_evidence(inp, self.payload)

    def sample(self):
        frame = self.tmux.frame()
        inp = composer(frame,
                       self.payload if self.pasted and self.codex_fallback_footer else None,
                       self.codex_fallback_footer)
        if self.diagnostic is not None:
            self.diagnostic.observe(frame, inp, self.diagnostic_phase)
        return frame, inp

    def at_end(self, inp):
        return inp.cursor == (2 + styles.cell_width(inp.text.rsplit("\n", 1)[-1]), inp.text.count("\n"))

    def ready(self):
        deadline = self.clock() + self.o.max_wait
        previous = None
        stable_since = self.clock()
        probed = False
        probe_empty_credit = False
        last_reason = "unsupported-layout"
        seen_composer = False
        consecutive_known = 0
        while self.clock() < deadline:
            frame, inp = self.sample()
            now = self.clock()
            verified_empty = empty_composer(frame, inp)
            fp = (*inp.fingerprint(), verified_empty)
            # Screen text cannot establish ownership of an attached image.
            # Visual wrapping may split the placeholder across composer rows.
            # Never append or submit alongside its visible placeholder.
            if inp.harness == "claude" and IMAGE_PLACEHOLDER.search(normalized(inp.text)):
                raise DeliveryError("image-placeholder")
            if now >= deadline:
                break
            if probe_empty_credit and not verified_empty:
                probe_empty_credit = False
            if inp.kind == "modal":
                raise DeliveryError("modal")
            if inp.kind == "unknown":
                # A coordinate/capture race is not evidence that input
                # changed. Keep the last known fingerprint, but require two
                # fresh known samples after the gap before acting on it.
                consecutive_known = 0
                if seen_composer and last_reason == "unsupported-layout":
                    last_reason = "unstable-composer"
                self.sleep(min(self.o.poll_interval, max(0, deadline - self.clock())))
                continue
            if self.verify_compact:
                if inp.harness != "codex":
                    raise DeliveryError("compact-requires-codex")
                if not compact_input_is_empty(frame, inp):
                    raise DeliveryError("existing-input")
            consecutive_known += 1
            if inp.kind in {"empty", "text", "suggestion"}:
                seen_composer = True
                if last_reason == "unsupported-layout":
                    last_reason = "unstable-composer"
            if previous is None:
                stable_since = now
            if previous is not None and fp != previous:
                # Text/cursor changes within a known input indicate typing.
                # A startup unknown -> empty transition is ordinary readiness.
                if inp.kind in {"text", "suggestion", "empty"} and previous[0] in {"text", "suggestion", "empty"}:
                    if not self.o.backoff:
                        raise DeliveryError("human-typing")
                    last_reason = "human-typing"
                stable_since = now
            twice = consecutive_known >= 2 and previous is not None and fp == previous
            previous = fp
            # The full stability window was already observed before probing a
            # suggestion. The default 8-second window within a 10-second
            # readiness budget cannot fit twice; require two fresh empty
            # samples after the probe instead of restarting that window.
            # Any intervening nonempty or unreadable sample revokes the credit.
            settled = (now - stable_since >= getattr(self.o, "stable_window", self.o.stable_wait)
                       or (probe_empty_credit and inp.kind == "empty"))
            if twice and settled:
                if verified_empty:
                    if self.diagnostic is not None:
                        self.diagnostic.predicate("ready", True)
                    return frame, inp
                # Retirement's literal exit permits only Claude's canonical
                # idle suggestion at the input-start cursor, never draft text.
                if (getattr(self.o, "literal_exit", False) and self.payload == "/exit"
                        and inp.kind == "suggestion" and inp.harness == "claude"
                        and re.fullmatch(r'Try "[^\n]*"', inp.text)):
                    return frame, inp
                if inp.kind == "suggestion" and not probed:
                    # Operator-authorized probe: real draft text remains; a ghost
                    # suggestion should disappear. Never clear actual text.
                    self.tmux.keys("Space", "BSpace")
                    probed = True
                    probe_empty_credit = True
                    previous = None
                    stable_since = self.clock()
                else:
                    last_reason = "existing-input"
                    if not self.o.backoff:
                        raise DeliveryError(last_reason)
            self.sleep(min(self.o.poll_interval, max(0, deadline - self.clock())))
        raise DeliveryError(last_reason)

    def deliver(self):
        result = self._deliver()
        result["input_method"] = "typed" if self.typed or getattr(self.o, "literal_exit", False) else "paste"
        return result

    def type_payload(self):
        self.pasted = True  # A failed input command can still change the composer.
        self.diagnostic_phase = "post_paste"
        if self.diagnostic is not None:
            self.diagnostic.event("paste")
        self.tmux.type_command(self.payload)

    def owns_compact(self, frame, inp):
        return (inp.harness == "codex" and self.input_evidence(inp) and self.at_end(inp)
                and compact_prompt_row(frame, inp) == f"› {self.payload}")

    def deliver_compact(self):
        self.type_payload()
        start = self.clock()
        deadline = start + self.o.render_wait + self.o.submit_delay
        owned_since = None
        while self.clock() < deadline:
            frame, inp = self.sample()
            now = self.clock()
            if now >= deadline:
                break
            owned = self.owns_compact(frame, inp)
            if self.diagnostic is not None:
                self.diagnostic.predicate("input_evidence", owned)
            if owned:
                if owned_since is None:
                    owned_since = now
                if now >= start + self.o.submit_delay and now - owned_since >= self.o.poll_interval:
                    before, live = self.sample()
                    owns_live = self.owns_compact(before, live)
                    if self.diagnostic is not None:
                        self.diagnostic.predicate("pre_enter_ownership", owns_live)
                    if not owns_live or self.clock() >= deadline:
                        raise DeliveryError("input-changed-before-enter", 3)
                    return self.submit_compact(before, live)
            elif inp.kind == "modal":
                raise DeliveryError("modal-after-paste", 3)
            elif (owned_since is not None or inp.kind in {"text", "suggestion"}
                  or (inp.harness and inp.harness != "codex")):
                raise DeliveryError("input-changed-after-paste", 3)
            elif now >= start + self.o.render_wait:
                break
            self.sleep(min(self.o.poll_interval, max(0, deadline - self.clock())))
        raise DeliveryError("paste-not-observed", 3)

    def submit_compact(self, before, live):
        if before.width <= 0:
            raise DeliveryError("unsupported-layout", 3)
        baseline, _ = compact_records(before, live)
        self.enters = 1  # Count the attempt even if the tmux operation fails.
        if self.diagnostic is not None:
            self.diagnostic.event("enter")
        self.tmux.keys("Enter")
        deadline = self.clock() + self.o.receipt_wait

        # Hold either observation through the window so a later contradictory
        # notice cannot turn two possible outcomes into a definite answer.
        observed = set()
        while self.clock() < deadline:
            frame, inp = self.sample()
            now = self.clock()
            if now >= deadline:
                break
            if frame.width > 0 and frame.width != before.width:
                # Reflow can make a wrapped baseline notice look like new text.
                raise DeliveryError("pane-width-changed", 3)
            if (frame.width <= 0 or inp.kind == "modal"
                    or (inp.harness and inp.harness != "codex")):
                raise DeliveryError("unsupported-layout", 3)
            if inp.harness == "codex":
                notices, visible_notices = compact_records(frame, inp)
                # Clearing and repainting a screen can duplicate an old notice
                # in scrollback. Only simultaneous visible copies can establish
                # an excess over the baseline for text that is already known.
                new_text = notices.keys() - baseline.keys()
                extra_visible = (visible_notices - baseline).keys()
                observed.update(outcome for outcome, _ in new_text | extra_visible)
                if len(observed) > 1:
                    raise DeliveryError("conflicting-command-evidence", 3)
            self.sleep(min(self.o.poll_interval, deadline - now))
        if "refused" in observed:
            raise DeliveryError("compact-refused", 3)
        if "completed" in observed:
            if self.diagnostic is not None:
                self.diagnostic.predicate("command_completion", True)
            return {"status": "delivered", "receipt": "command", "enters": self.enters,
                    "command_outcome": "completed"}
        raise DeliveryError("receipt-timeout", 3)

    def _deliver(self):
        if self.journal is not None:
            blocked = self.journal.unresolved(self.journal.receiver_key(self.tmux) + "-")
            if blocked:
                self.blocking_attempt = blocked[0].name
                raise DeliveryError("unresolved-paste")
        _, inp = self.ready()
        if self.journal is not None and not (self.typed or getattr(self.o, "literal_exit", False)):
            try:
                self.attempt = self.journal.prepare(self.tmux, self.payload)
            except OSError as error:
                raise DeliveryError("attempt-state-unavailable") from error
        # One final sample catches input beginning just after the stable period.
        before, check = self.sample()
        if (check.fingerprint() != inp.fingerprint()
                or (check.kind == "empty" and not empty_composer(before, check))):
            raise DeliveryError("input-changed-before-paste")
        if check.harness == "codex":
            rows = styles.strip_ansi(before.raw).splitlines()
            if check.end < len(rows) and not FOOTER.match(rows[check.end]):
                self.codex_fallback_footer = rows[check.end]
        if self.verify_compact:
            if not compact_input_is_empty(before, check):
                raise DeliveryError("input-changed-before-paste")
            return self.deliver_compact()
        literal = getattr(self.o, "literal_exit", False)
        if literal and (self.payload != "/exit" or check.harness != "claude"):
            raise DeliveryError("literal-exit-requires-claude-exit")
        resume_before = resume_records(before) if literal else Counter()
        compact_before = styles.strip_ansi(before.history or before.raw).count("• Context compacted")
        baseline = records(before, check, archived_codex_status=self.codex_fallback_footer)
        if literal:
            self.pasted = True  # A failed input command can still change the composer.
            self.diagnostic_phase = "post_paste"
            if self.diagnostic is not None:
                self.diagnostic.event("paste")
            self.tmux.keys("-l", self.payload)
        elif self.typed:
            self.type_payload()
        else:
            # Receipt observation may read a retained dead pane. Establish
            # liveness separately before marking an outgoing input attempt.
            self.tmux.check_receiver()
            self.pasted = True
            self.diagnostic_phase = "post_paste"
            if self.diagnostic is not None:
                self.diagnostic.event("paste")
            self.tmux.paste(self.attempt / "message" if self.attempt is not None else self.path)
        start = self.clock()
        deadline = start + self.o.render_wait + self.o.submit_delay + self.o.receipt_wait
        owned = None
        evidence_since = None
        last_enter = None
        input_disappeared = False
        max_enters = 1 if literal else 2
        accepted_forms = {normalized(self.payload)}
        while self.clock() < deadline:
            frame, current = self.sample()
            now = self.clock()
            if now >= deadline:
                break
            receipt = records(frame, current, archived_codex_status=self.codex_fallback_footer)
            if self.diagnostic is not None:
                self.diagnostic.predicate("receipt_new", False)
            if literal and self.enters == 1 and current.kind == "unknown":
                resumed = resume_records(frame)
                fresh = [session for session, count in resumed.items() if count > resume_before[session]]
                if fresh:
                    if self.diagnostic is not None:
                        self.diagnostic.predicate("command_completion", True)
                    return {"status": "delivered", "receipt": "command", "command": "claude-exit",
                            "resume_session_id": fresh[0], "enters": 1, "transport": "literal"}
            if (self.payload == "/compact" and self.enters and current.kind == "empty"
                    and styles.strip_ansi(frame.history or frame.raw).count("• Context compacted") > compact_before):
                if self.diagnostic is not None:
                    self.diagnostic.predicate("command_completion", True)
                return {"status": "delivered", "receipt": "command", "enters": self.enters}
            # A collapsed receipt is usable only if the same marker was seen
            # in this attempt's input. Existing marker history is in baseline.
            for kind in ("submitted", "queued"):
                if not literal and self.enters and any(receipt[(kind, form)] > baseline[(kind, form)] for form in accepted_forms):
                    if self.diagnostic is not None:
                        self.diagnostic.predicate("receipt_new", True)
                    return {"status": "delivered", "receipt": kind, "enters": self.enters}
            if current.kind == "modal":
                raise DeliveryError("modal-after-paste", 3)
            if owned is not None and current.kind == "empty":
                input_disappeared = True
            evidence = self.input_evidence(current)
            if self.diagnostic is not None:
                self.diagnostic.predicate("input_evidence", evidence)
            if evidence:
                fp = current.fingerprint()
                if owned is not None and fp != owned and self.enters:
                    raise DeliveryError("input-changed-after-paste", 3)
                if owned != fp:
                    evidence_since = now
                owned = fp
                accepted_forms.add(normalized(current.text))
                due = start + self.o.submit_delay if last_enter is None else last_enter + self.o.retry_wait
                if (now >= due and now - evidence_since >= self.o.poll_interval
                        and self.enters < max_enters and not input_disappeared):
                    # Refresh receipt AND input immediately before each Enter.
                    confirm, live = self.sample()
                    fresh = records(confirm, live, archived_codex_status=self.codex_fallback_footer)
                    for kind in ("submitted", "queued"):
                        if not literal and self.enters and any(fresh[(kind, form)] > baseline[(kind, form)] for form in accepted_forms):
                            if self.diagnostic is not None:
                                self.diagnostic.predicate("receipt_new", True)
                            return {"status": "delivered", "receipt": kind, "enters": self.enters}
                    if live.fingerprint() != owned or not self.input_evidence(live):
                        if self.diagnostic is not None:
                            self.diagnostic.predicate("pre_enter_ownership", False)
                        raise DeliveryError("input-changed-before-enter", 3)
                    if self.diagnostic is not None:
                        self.diagnostic.predicate("pre_enter_ownership", True)
                    self.enters += 1  # Count the attempted key even if tmux fails.
                    try:
                        self.tmux.keys("Enter")
                    except DeliveryError as error:
                        if error.reason == "receiver-changed":
                            self.enters -= 1  # Target verification failed before dispatch.
                        raise
                    self.enter_confirmed = True
                    if self.diagnostic is not None:
                        self.diagnostic.event("enter")
                    last_enter = self.clock()
            elif current.kind in {"text", "suggestion"} and (owned is not None or now - start >= self.o.render_wait):
                raise DeliveryError("mixed-input-after-paste", 3)
            elif owned is None and now - start >= self.o.render_wait:
                raise DeliveryError("paste-not-observed", 3)
            # Once input disappears, just wait for receipt. Never press Enter
            # into the next empty input, even if history rendering is delayed.
            self.sleep(min(self.o.poll_interval, max(0, deadline - self.clock())))
        raise DeliveryError("receipt-timeout", 3)


def options(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("target")
    p.add_argument("--prompt-file", "-f", type=Path)
    p.add_argument("--diagnostic-file", type=Path,
                   help="write one owner-only structural record for this send attempt")
    p.add_argument("--typed-command", action="store_true", help="type one single-line slash command with literal keys; retain all composer/receipt guards")
    p.add_argument("--verify-compact", action="store_true",
                   help="verify the rendered outcome of a bare Codex /compact with --typed-command")
    p.add_argument("--stable-window", "--stable-wait", dest="stable_wait", type=float, default=None, help="composer settle window; default: submit-delay")
    for name, default in (("max-wait", 10), ("submit-delay", 8),
                          ("render-wait", 3), ("receipt-wait", 15), ("retry-wait", 3),
                          ("poll-interval", 0.25)):
        p.add_argument("--" + name, type=float, default=default)
    p.add_argument("--literal-exit", action="store_true", help="type a bare Claude /exit literally, send at most one Enter, and verify a fresh resume notice")
    p.add_argument("--backoff", action="store_true", help="wait for stable input within --max-wait instead of exiting on typing")
    p.add_argument("message", nargs="?")
    o, extra = p.parse_known_intermixed_args(argv)
    if o.verify_compact and (extra or not o.typed_command or o.literal_exit
                             or o.prompt_file is not None or o.message != "/compact"):
        p.exit(1, json.dumps({"status": "error", "reason": "verify-compact-requires-typed-bare-argument"}) + "\n")
    if extra:
        p.error("unrecognized arguments: " + " ".join(extra))
    if o.stable_wait is None:
        o.stable_wait = o.submit_delay
    o.stable_window = o.stable_wait
    for name in ("stable_wait", "max_wait", "submit_delay", "render_wait", "receipt_wait", "retry_wait", "poll_interval"):
        value = getattr(o, name)
        maximum = math.inf if name == "receipt_wait" else 600
        if not math.isfinite(value) or (not 0 < value <= maximum and not (name in {"submit_delay", "stable_wait"} and value == 0)):
            p.error(name.replace("_", "-") + " must be finite and positive (submit-delay and stable-window may be zero); options except receipt-wait are capped at 600 seconds")
    if not o.verify_compact and bool(o.prompt_file) == (o.message is not None):
        p.error("provide exactly one message or --prompt-file")
    if not o.target or o.target.startswith("-"):
        p.error("invalid target")
    return o


def journal_command(argv):
    parser = argparse.ArgumentParser(description="Inspect or resolve a private paste attempt without pane input")
    if argv[0] == "--resolve":
        parser.add_argument("id")
        parser.add_argument("--disposition", required=True, choices=DISPOSITIONS)
    o = parser.parse_args(argv[1:])
    if argv[0] == "--resolve" and not ATTEMPT_ID.fullmatch(o.id):
        parser.error("invalid attempt ID")
    try:
        journal = PasteJournal()
        if argv[0] == "--resolve":
            journal.resolve(o.id, o.disposition)
            print(json.dumps({"status": "resolved", "id": o.id, "disposition": o.disposition}))
        else:
            attempts = []
            for path in journal.unresolved():
                try:
                    attempts.append(journal.report(path))
                except FileNotFoundError:
                    # A successful in-flight send can remove its own record.
                    continue
            print(json.dumps(attempts))
    except (DeliveryError, OSError, ValueError, KeyError) as error:
        reason = error.reason if isinstance(error, DeliveryError) else "attempt-state-unavailable"
        print(json.dumps({"status": "error", "reason": reason}), file=sys.stderr)
        return 2
    return 0


def deliver_locked(sender):
    try:
        result = sender.deliver()
    except (DeliveryError, OSError, subprocess.SubprocessError) as error:
        if sender.attempt is not None:
            if not sender.pasted or sender.enter_confirmed:
                # A known Enter restores the existing pending-file ambiguity
                # path. The journal only blocks possible stranded pastes.
                try:
                    if sender.enter_confirmed:
                        sender.path = private_pending(sender.payload)
                    sender.journal.discard(sender.attempt)
                except OSError:
                    if sender.enter_confirmed:
                        try:
                            sender.journal.mark_finished(sender.attempt, "enter-confirmed")
                        except OSError:
                            pass  # Keep the original outcome and any surviving evidence.
                else:
                    sender.attempt = None
            else:
                try:
                    sender.journal.write_record(sender.attempt, "outcome", {
                        "status": "ambiguous", "enters": sender.enters,
                        "submit_not_attempted": sender.enters == 0,
                        "enter_confirmed": False,
                        "reason": error.reason if isinstance(error, DeliveryError) else "tmux-operation-failed",
                    })
                except OSError:
                    # Even without final metadata, the write-ahead record and
                    # original payload remain discoverable and unresolved.
                    pass
        raise
    if sender.attempt is not None:
        try:
            sender.journal.discard(sender.attempt)
        except OSError:
            # Cleanup cannot take away a verified application receipt.
            result["attempt_cleanup"] = "failed"
    return result


def main():
    if sys.argv[1:2] in (["--unresolved"], ["--resolve"]):
        return journal_command(sys.argv[1:])
    o = options()
    try:
        payload = o.prompt_file.read_bytes().decode("utf-8") if o.prompt_file else o.message
        if o.literal_exit and payload != "/exit":
            raise ValueError("--literal-exit accepts only the bare /exit command")
        if not payload.strip() or any(unicodedata.category(c) == "Cc" and c != "\n" for c in payload):
            raise ValueError("message must be nonblank UTF-8 text without control characters other than newlines")
    except (OSError, UnicodeError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    diagnostic_file = None
    if o.diagnostic_file is not None:
        try:
            diagnostic_file = DiagnosticFile.reserve(o.diagnostic_file)
        except (OSError, ValueError):
            print(json.dumps({"status": "error", "reason": "unsafe-diagnostic-path"}), file=sys.stderr)
            return 1
    path = None
    try:
        if o.typed_command or o.literal_exit:
            path = private_pending(payload)
    except OSError:
        if diagnostic_file is not None:
            diagnostic_file.abort()
        print(json.dumps({"status": "error", "reason": "pending-file-failed"}), file=sys.stderr)
        return 1
    sender = None
    def interrupted(signum, _frame):
        raise DeliveryError("signal-" + str(signum), 128 + signum)
    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        tmux = Tmux(o.target)
        sender = Sender(tmux, o, payload, path,
                        diagnostic=StructuralDiagnostic() if diagnostic_file is not None else None)
        tmux.receiver = tmux.receiver_identity()
        try:
            sender.journal = PasteJournal()
        except OSError as error:
            raise DeliveryError("attempt-state-unavailable") from error
        with pane_lock(tmux.identity, o.max_wait):
            result = deliver_locked(sender)
        result["pane"] = tmux.pane
        if diagnostic_file is not None:
            written = diagnostic_file.finish(sender.diagnostic, result["status"], "none",
                                             result["input_method"], sender.enters)
            result["diagnostic_status"] = "written" if written else "write-failed"
        print(json.dumps(result))
        if path is not None:
            path.unlink()
            path.parent.rmdir()
        return 0
    except (DeliveryError, OSError, subprocess.SubprocessError) as error:
        pasted = sender is not None and sender.pasted
        code = error.code if isinstance(error, DeliveryError) else (3 if pasted else 2)
        if pasted and code == 2:
            code = 3
        reason = error.reason if isinstance(error, DeliveryError) else "tmux-operation-failed"
        result = {"status": "ambiguous" if pasted else "deferred", "reason": reason,
                  "needs_review": pasted or reason in {"unsupported-layout", "unstable-composer", "modal", "unresolved-paste"},
                  "paste_attempted": pasted and not sender.typed,
                  "input_attempted": pasted, "input_method": "typed" if o.typed_command or o.literal_exit else "paste",
                  "enters": sender.enters if sender else 0}
        if o.verify_compact and pasted:
            code = 3
            refused = reason == "compact-refused"
            result["command_outcome"] = "refused" if refused else "unknown"
            if refused:
                result.update(status="refused", needs_review=False)
        if sender:
            result["pane"] = sender.tmux.pane
            if sender.blocking_attempt is not None:
                result["blocking_attempt_id"] = sender.blocking_attempt
            if pasted and not sender.typed and not o.literal_exit:
                result["submit_not_attempted"] = sender.enters == 0
            path = sender.path
            if pasted and sender.attempt is not None:
                if path is None:
                    path = sender.attempt / "message"
                if not sender.enter_confirmed:
                    result["attempt_id"] = sender.attempt.name
        try:
            result["pending_file"] = str(path if path is not None else private_pending(payload))
        except OSError:
            result["pending_file"] = None
            result["pending_retention"] = "failed"
        if diagnostic_file is not None and not diagnostic_file.closed:
            if sender is None:
                diagnostic_file.abort()
            else:
                written = diagnostic_file.finish(sender.diagnostic, result["status"], reason,
                                                 result["input_method"], sender.enters)
                result["diagnostic_status"] = "written" if written else "write-failed"
        print(json.dumps(result), file=sys.stderr)
        return code


if __name__ == "__main__":
    sys.exit(main())
