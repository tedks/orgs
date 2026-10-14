#!/usr/bin/env python3
"""Return only a conservative Claude/Codex composer state, never screen text.

The caller verifies the shared Claude live-composer classifier and modal
detector; Codex uses the known prompt and footer. Raw visible rows preserve
cursor coordinates. Wrapped layouts the parser cannot compare exactly become
unknown. The helper never prints composer content.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import unicodedata

CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return CSI_RE.sub("", text)


def sgr_span(raw_line: str, needle: str, attribute: str) -> bool:
    """Return true only when every visible character has the named SGR style."""
    chars = []
    flags = []
    styles = {"bold": False, "dim": False}
    offset = 0
    for match in CSI_RE.finditer(raw_line):
        chunk = raw_line[offset : match.start()]
        chars.extend(chunk)
        flags.extend([styles[attribute]] * len(chunk))
        code = match.group(0)
        if code.endswith("m"):
            params = code[2:-1]
            try:
                values = [int(item) if item else 0 for item in params.split(";")] if params else [0]
            except ValueError:
                return False
            index = 0
            while index < len(values):
                value = values[index]
                if value in {0, 22}:
                    styles = {"bold": False, "dim": False}
                elif value == 1:
                    styles["bold"] = True
                elif value == 2:
                    styles["dim"] = True
                elif value in {38, 48, 58}:
                    # Extended foreground/background/underline colors have
                    # numeric payloads that can themselves contain 2. Skip
                    # the mode and its color components instead of treating
                    # them as attributes.
                    if index + 1 >= len(values):
                        return False
                    mode = values[index + 1]
                    if mode == 5 and index + 2 < len(values):
                        index += 2
                    elif mode == 2 and index + 4 < len(values):
                        index += 4
                    else:
                        return False
                index += 1
        offset = match.end()
    tail = raw_line[offset:]
    chars.extend(tail)
    flags.extend([styles[attribute]] * len(tail))
    visible = "".join(chars)
    start = visible.find(needle)
    return start >= 0 and all(flags[start : start + len(needle)])


def dim_span(raw_line: str, needle: str) -> bool:
    return sgr_span(raw_line, needle, "dim")


def cell_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char) or unicodedata.category(char) in {"Cf", "Mn", "Me"}:
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def claude_combined_input_evidence(kind: str, text: str, harness: str,
                                   draft: str, payload: str, at_end: bool) -> bool:
    """Recognize only the exact Claude draft append or its measured marker form."""
    if kind != "text" or harness != "claude" or not at_end:
        return False
    if not draft:
        return False
    if text == draft + "\n" + payload:
        return True
    suffix = text[len(draft):] if text.startswith(draft) else ""
    marker = re.fullmatch(r"\[Pasted text #[1-9][0-9]* \+([1-9][0-9]*) lines\]", suffix)
    return bool(marker and marker.group(1) == str(payload.count("\n") + 1))


def claude_combined_fingerprint(text: str, cursor_x: int, cursor_y: int) -> str:
    """Hash a recognized Claude combined input and its prompt-relative cursor."""
    material = f"claude\0{text}\0{cursor_x}\0{cursor_y}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def codex_surface(screen: str) -> bool:
    clean = strip_ansi(screen)
    return "›" in clean and ("Context " in clean or "tab to queue message" in clean
                             or re.search(r"^  GPT-6-Sol · [^›❯\n]+$", clean, re.MULTILINE) is not None)


def state(screen: str, payload: str, cx: int, cy: int,
          co_submit_draft: str | None = None,
          fingerprint_path: pathlib.Path | None = None) -> str:
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in payload):
        return "unknown"
    clean_screen = strip_ansi(screen)
    lines = clean_screen.splitlines()
    if codex_surface(screen):
        return codex_state(lines, screen.splitlines(), payload, cx, cy)
    # Current Claude Code renders the live composer between two horizontal
    # rules, with no side gutters. Require that exact frame around the last
    # prompt marker; a transcript line containing ❯ is not sufficient.
    rules = [i for i, line in enumerate(lines) if line.strip() and set(line.strip()) == {"─"}]
    prompts = [i for i, line in enumerate(lines) if "❯" in line]
    if not prompts:
        return "unknown"
    idx = prompts[-1]
    before = [i for i in rules if i < idx]
    after = [i for i in rules if i > idx]
    if not before or not after:
        return "unknown"
    top, bottom = before[-1], after[0]
    if top >= idx or bottom <= idx:
        return "unknown"
    line = lines[idx]
    fragment = line.split("❯", 1)[1]
    if fragment.startswith(("\u00a0", " ")):
        fragment = fragment[1:]
    parts = [fragment]
    for row in lines[idx + 1 : bottom]:
        if "❯" in row:
            return "unknown"
        # Claude's hard-newline continuations are indented two spaces. Soft
        # wrapping changes the measured cursor row and fails exact ownership.
        parts.append(row[2:] if row.startswith("  ") else row)
    observed = "\n".join(part.rstrip() for part in parts)
    # Terminal padding is discarded, but internal spaces and line breaks
    # remain exact. A wrapped visual row without the known hard-newline indent
    # will not compare as the payload and therefore fails closed.
    wanted = payload.rstrip("\n")
    generic_observed = observed.rstrip("\n")
    if generic_observed == "":
        return "empty" if cy == idx and cx == 2 else "busy"
    if co_submit_draft is not None:
        prefix = co_submit_draft + "\n"
        if not payload.startswith(prefix):
            return "unknown"
        outgoing = payload[len(prefix):]
        relative_row = cy - idx
        if relative_row < 0 or relative_row >= len(parts) or cy >= bottom:
            return "busy"
        if any(part.rstrip() for part in parts[relative_row + 1:]):
            return "busy"
        candidate = "\n".join(part.rstrip() for part in parts[:relative_row + 1])
        at_end = (relative_row == candidate.count("\n")
                  and cx == 2 + cell_width(parts[relative_row].rstrip()))
        if claude_combined_input_evidence("text", candidate, "claude",
                                          co_submit_draft, outgoing, at_end):
            if fingerprint_path is not None:
                fingerprint_path.write_text(
                    claude_combined_fingerprint(candidate, cx, relative_row),
                    encoding="ascii")
            return "own"
        return "busy"
    observed = generic_observed
    expected_y = idx + payload.count("\n")
    expected_x = 2 + cell_width(payload.rsplit("\n", 1)[-1])
    if observed == wanted and (cy, cx) == (expected_y, expected_x):
        return "own"
    # Claude paints a suggestion in an empty composer without a distinct style.
    # A human can type that exact text and Home the cursor, producing the same
    # capture. Therefore a suggestion is never evidence of an empty composer.
    if observed.startswith('Try "'):
        return "unknown"
    return "busy"


def codex_state(lines: list[str], raw_lines: list[str], payload: str, cx: int, cy: int) -> str:
    # Match the live prompt/context/footer shape. A Working row is allowed
    # between prompt and context because generation can continue while the
    # composer stays empty. Known shortcut, agent, and warning footer text may follow.
    matches = [i for i, line in enumerate(lines) if "›" in line]
    if not matches:
        return "unknown"
    idx = matches[-1]
    queue_rows = [
        i for i in range(idx + 1, len(lines))
        if re.fullmatch(r"  tab to queue message {2,}\d+% context left", lines[i])
    ]
    if queue_rows:
        queue_row = queue_rows[0]
        # This Codex busy-composer hint is a single measured footer shape. It
        # must be the final nonblank row, separated from the prompt by exactly
        # one blank row. This measured shape supports only a short single-line
        # prompt; wrapped/multiline layouts remain unknown. Never infer key
        # semantics from the hint.
        if len(queue_rows) != 1 or queue_row - idx != 2 or "\n" in payload:
            return "unknown"
        if lines[idx + 1].strip():
            return "unknown"
        if any(line.strip() for line in lines[queue_row + 1 :]):
            return "unknown"
        if queue_row >= len(raw_lines) or not sgr_span(raw_lines[queue_row], "tab", "bold"):
            return "unknown"
        fragment = lines[idx].split("›", 1)[1]
        if fragment.startswith(" "):
            fragment = fragment[1:]
        observed = fragment.rstrip()
        if observed == "":
            return "empty" if cy == idx and cx == 2 else "busy"
        expected_y = idx
        expected_x = 2 + cell_width(payload.rsplit("\n", 1)[-1])
        return "own" if observed == payload.rstrip("\n") and (cy, cx) == (expected_y, expected_x) else "busy"

    # Codex 0.157.1 also renders the model/context row ABOVE a separate
    # queue hint. Require the whole measured suffix, including bold "tab";
    # neither arbitrary footer text nor an echoed hint proves a live composer.
    separate_queue = [i for i in range(idx + 1, len(lines))
                      if lines[i] == "  tab to queue message"]
    if separate_queue:
        hint = separate_queue[0]
        if (len(separate_queue) != 1 or hint - idx != 3 or "\n" in payload
                or lines[idx + 1].strip()
                or not re.fullmatch(r"  [^›❯]+ · Context \d{1,3}% left(?: · [^›❯]+)?", lines[idx + 2])
                or any(line.strip() for line in lines[hint + 1 :])
                or hint >= len(raw_lines)
                or not sgr_span(raw_lines[hint], "tab", "bold")):
            return "unknown"
        fragment = lines[idx].split("›", 1)[1]
        if not fragment.startswith(" "):
            return "unknown"
        observed = fragment[1:].rstrip()
        if observed == "":
            return "empty" if (cy, cx) == (idx, 2) else "busy"
        if observed == "Ask Codex to do anything":
            return "empty" if (cy, cx) == (idx, 2) and dim_span(raw_lines[idx], observed) else "busy"
        return "own" if observed == payload and (cy, cx) == (idx, 2 + cell_width(payload)) else "busy"

    contexts = [i for i, line in enumerate(lines) if i > idx and "Context " in line]
    if contexts:
        footer = contexts[0]
    else:
        # Codex 0.157.1 fresh fork: known model/branch footer, no Context yet.
        # Require its shortcuts/warnings suffix rather than arbitrary prompt text.
        model_rows = [i for i in range(idx + 1, len(lines))
                      if re.fullmatch(r"  GPT-6-Sol · [^›❯]+", lines[i])]
        if len(model_rows) != 1:
            return "unknown"
        footer = model_rows[0]
        suffix = [line for line in lines[footer + 1:] if line.strip()]
        shortcuts = len(suffix) == 1 and re.fullmatch(
            r"  \? for shortcuts +⚠ \d+ warnings · f2 to view", suffix[0])
        compact_menu = (payload == "/compact" and not suffix and idx >= 2
                        and lines[idx - 2] == "› /compact  summarize conversation to prevent hitting the context limit"
                        and not lines[idx - 1].strip() and lines[idx] == "› /compact")
        if not shortcuts and not compact_menu:
            return "unknown"
    if any(line.strip() and not ("? for shortcuts" in line or "warning" in line.lower() or "agents" in line.lower()) for line in lines[footer + 1 :]):
        return "unknown"
    fragment = lines[idx].split("›", 1)[1]
    if fragment.startswith(" "):
        fragment = fragment[1:]
    continuations = []
    for row in lines[idx + 1 : footer]:
        if not row.strip():
            continuations.append("")
        elif row.startswith("  "):
            continuations.append(row[2:].rstrip())
        elif row.startswith("Working ("):
            continue
        else:
            return "unknown"
    observed = "\n".join([fragment.rstrip(), *continuations]).rstrip("\n")
    if observed == "":
        return "empty" if cy == idx and cx == 2 else "busy"
    expected_y = idx + payload.count("\n")
    expected_x = 2 + cell_width(payload.rsplit("\n", 1)[-1])
    if observed == payload.rstrip("\n") and (cy, cx) == (expected_y, expected_x):
        return "own"
    if observed == "Ask Codex to do anything":
        if cy == idx and cx == 2 and idx < len(raw_lines) and dim_span(raw_lines[idx], observed):
            return "empty"
        return "busy"
    return "busy"


def slash_command_syntax(text: str) -> bool:
    return bool(re.fullmatch(r"/[A-Za-z][A-Za-z0-9_-]*(?: [^\r\n\x00-\x1f\x7f]*)?", text))


def command_like(text: str) -> bool:
    return text.lstrip().startswith(("/", "!"))


def command_draft(text: str) -> bool:
    """Only a short exact single-line command in an ordinary composer can clear."""
    if (len(text.encode("utf-8")) > 200 or text != text.rstrip() or text.endswith(";")
            or any(unicodedata.category(ch) == "Cc" for ch in text)):
        return False
    return slash_command_syntax(text) or (text.startswith("!") and bool(text[1:].strip()))


def command_rows(screen: str, glyph: str, start: int, end: int) -> bool:
    """Reject extra command rows, including trimmed blank continuations."""
    rows = strip_ansi(screen).splitlines()
    if glyph == "❯":
        return end == start + 1
    return end - start == 2 and all(not row.strip() for row in rows[start + 1:end])


def contains_payload(text: str, payload: str) -> bool:
    """Conservative replay guard: a full payload survives wrapping/spacing."""
    wanted = "".join(payload.split())
    return bool(wanted) and wanted in "".join(text.split())


def observe(screen: str, payload: str, cx: int, cy: int, path: pathlib.Path,
            co_submit_draft: str | None = None) -> str:
    """Write only a validated exact draft to a caller-owned private scratch file."""
    path.write_text("", encoding="utf-8")
    result = state(screen, payload, cx, cy, co_submit_draft,
                   path if co_submit_draft is not None else None)
    if co_submit_draft is not None:
        # Combined delivery owns only the validated hash fingerprint; never
        # turn a changed or unsupported post-paste composer into a saved draft.
        return result
    if result != "busy":
        return result
    lines = strip_ansi(screen).splitlines()
    glyph = "›" if codex_surface(screen) else "❯"
    prompts = [i for i, row in enumerate(lines) if glyph in row]
    if not prompts:
        return result
    idx = prompts[-1]
    if glyph == "❯":
        ends = [i for i in range(idx + 1, len(lines)) if lines[i].strip() and set(lines[i].strip()) == {"─"}]
    else:
        ends = [i for i in range(idx + 1, len(lines)) if "Context " in lines[i] or "tab to queue message" in lines[i] or re.match(r"  GPT-6-Sol · ", lines[i])]
    if not ends:
        return result
    fragment = lines[idx].split(glyph, 1)[1]
    if fragment.startswith((" ", "\u00a0")):
        fragment = fragment[1:]
    parts = [fragment.rstrip()] + [row[2:].rstrip() if row.startswith("  ") else row.rstrip() for row in lines[idx + 1:ends[0]]]
    draft = "\n".join(parts).rstrip("\n")
    command = command_draft(draft) and command_rows(screen, glyph, idx, ends[0])
    if command_like(draft) and not command:
        return result
    # These measured busy queues cannot verify multiline appended input.
    if not command and glyph == "›" and any(re.fullmatch(r"  tab to queue message(?: {2,}\d+% context left)?", row) for row in lines[idx + 1:]):
        return result
    home = ("\n" not in draft and (cx, cy) == (2, idx)
            and state(screen, draft, 2 + cell_width(draft), idx) == "own")
    if (draft and not contains_payload(draft, payload)
            and (state(screen, draft, cx, cy) == "own" or home)
            and not re.search(r"\[Pasted (?:text|Content)", draft, re.I)):
        path.write_text(draft, encoding="utf-8")
        if command:
            return "command-home" if home else "command"
        return "draft-home" if home else "draft"
    return result


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--strip-ansi":
        sys.stdout.write(strip_ansi(sys.stdin.read()))
        return 0
    args = sys.argv[1:]
    observe_path = None
    co_submit_draft = None
    while args and args[0].startswith("--"):
        if len(args) >= 2 and args[0] == "--observe-file" and observe_path is None:
            observe_path = pathlib.Path(args[1])
            del args[:2]
        elif len(args) >= 2 and args[0] == "--co-submit-draft-file" and co_submit_draft is None:
            try:
                co_submit_draft = pathlib.Path(args[1]).read_bytes().decode("utf-8")
            except (OSError, UnicodeError):
                print("unknown")
                return 0
            del args[:2]
        else:
            return 64
    if len(args) != 3 or (co_submit_draft is not None and observe_path is None):
        return 64
    try:
        payload = pathlib.Path(args[0]).read_bytes().decode("utf-8")
        screen = sys.stdin.read()
    except (OSError, UnicodeError):
        print("unknown")
        return 0
    try:
        cx, cy = int(args[1]), int(args[2])
    except (IndexError, ValueError):
        print("unknown")
        return 0
    print(observe(screen, payload, cx, cy, observe_path, co_submit_draft)
          if observe_path else state(screen, payload, cx, cy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
