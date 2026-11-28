#!/usr/bin/env python3
"""Audit publication inputs without using the usage tooling or its state."""
import argparse
from collections import Counter
import gzip
import hashlib
import io
from itertools import chain
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unicodedata
from urllib.parse import unquote
import zlib

HOME_PREFIX = "/ho" + "me/"
UUID = r"[0-9a-f]{8}(?:[-_][0-9a-f]{4}){3}[-_][0-9a-f]{12}"
COMPACT_UUID = re.compile(r"[0-9a-f]{12}[1-8][0-9a-f]{3}[89ab][0-9a-f]{15}", re.I)
HEX_TOKEN = re.compile(r"(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])", re.I)
DELIMITED_UUID = re.compile(UUID, re.I)
ID_SUFFIX = r"[a-z0-9][a-z0-9_-]*(?![a-z0-9_-])"
MACOS_HOME = "/" + "Users/"
HOME_ROOTS = ("/var" + HOME_PREFIX, HOME_PREFIX, "/" + "root/", MACOS_HOME, MACOS_HOME.upper())
MACOS_PATH_START = r"(?:(?<![\w./-])|(?<=file://)|(?<=file://localhost))"
HOME_START = re.compile(
    "(?:" + "|".join(map(re.escape, HOME_ROOTS)) + ")"
    + "|" + MACOS_PATH_START + "(?i:" + re.escape(MACOS_HOME) + ")"
    + r"|(?<![\w~])~[A-Za-z_][A-Za-z0-9_.-]*"
)
PRINTF_DIRECTIVE = re.compile(
    r"%(?:[0-9]+\$)?[-+#0 ']*(?:[0-9]+|\*(?:[0-9]+\$)?)?"
    r"(?:\.(?:[0-9]*|\*(?:[0-9]+\$)?))?(?:hh|ll|[hlLjzt])?"
    r"[diouxXeEfFgGaAcCsSpn](?!\w)"
)
IDENTIFIERS = (
    ("pane-id", re.compile(r"(?:(?<![\w%])|(?<=_)|(?<=-t)|(?<=\bpane))%[0-9]+(?![\w%])", re.I)),
)
PREFIXES = (
    ("request-id", "req"),
    ("message-id", "msg"),
    ("tool-id", "toolu"),
    ("response-id", "resp"),
    ("reasoning-id", "rs"),
    ("function-call-id", "fc"),
    ("call-id", "call"),
)
PREFIXED_IDS = tuple(
    (rule, re.compile(r"(?<![a-z0-9])" + prefix + "_" + ID_SUFFIX, re.I))
    for rule, prefix in PREFIXES
)
BASE64_CHARS = r"[A-Za-z0-9+/_-]"
BASE64_LINE = re.compile(BASE64_CHARS + r"+={0,2}")
BASE64_RUN = re.compile(BASE64_CHARS + r"{200,}={0,2}")
BASE64_CLASSES = tuple(re.compile(pattern) for pattern in ("[A-Z]", "[a-z]", "[0-9]"))
MIN_WRAP_WIDTH = 40
HEX_RUN = re.compile(r"[0-9a-f]+", re.I)
MIN_HEX_DISTINCT = 8
DOTLESS_PATH = re.compile(r"/?(?:[A-Za-z0-9_-]{1,32}/){2,}[A-Za-z0-9_-]{0,32}")
FORMAT_PERCENT = re.compile(r"(%%3[0-9](?![%\w$]|\.[0-9]))")
GIT_OPTIONS = ("--no-replace-objects",)
ESCAPE = re.compile(r"\\(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|x([0-9a-fA-F]{2})|([0-7]{1,3})|(.))")
SIMPLE_ESCAPES = dict(a="\a", b="\b", f="\f", n="\n", r="\r", t="\t", v="\v")
ENCODING_DEPTH = 4


def normalized(value):
    if value.isascii():
        return value
    return unicodedata.normalize("NFC", "".join(
        char for char in value
        if unicodedata.category(char) != "Cf"
        and char != "\u034f"
        and not "\ufe00" <= char <= "\ufe0f"
        and not "\U000e0100" <= char <= "\U000e01ef"
    ))


def list_entries(path, *, deny=False):
    text = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    for number, line in enumerate(text.split("\n"), 1):
        line = normalized(line)
        entry = line.strip()
        if entry and not entry.startswith("#"):
            if deny and any(unicodedata.category(char) == "Cc" for char in line):
                raise ValueError("Deny entries must be free of control characters.")
            yield entry, number


def deny_patterns(entries):
    patterns = []
    for entry, list_number, line_number in entries:
        if not entry.isascii():
            raise ValueError("Deny entries must be ASCII after normalization.")
        encoded = re.sub(r"[^A-Za-z0-9-]", "-", entry)
        for variant in sorted({entry, encoded}):
            parts = variant.split()
            pattern = r"\s+".join(map(re.escape, parts))
            patterns.append((parts[0].lower(), re.compile(f"(?=({pattern}))", re.I),
                             (list_number, line_number)))
    return patterns


def letter_boundary(left, right):
    return not (left.isalpha() and right.isalpha()) or (left.islower() and right.isupper())


def deny_matches(line, deny):
    if not deny:
        return
    line = normalized(line)
    # The Unicode case variants recognized by re.I are broader than lower().
    lower = line.lower() if line.isascii() else None
    seen = set()
    for prefix, pattern, entry in deny:
        if lower is not None and prefix not in lower:
            continue
        for match in pattern.finditer(line):
            start, end = match.span(1)
            if start and not letter_boundary(line[start - 1], line[start]):
                continue
            if end < len(line) and not letter_boundary(line[end - 1], line[end]):
                continue
            key = (start, end, entry)
            if key not in seen:
                seen.add(key)
                yield "deny-list", match[1], start + 1, entry


def decoded_escape(match):
    for digits in match.groups()[:3]:
        if digits:
            point = int(digits, 16)
            return chr(point) if point <= sys.maxunicode else match[0]
    if match[4]:
        return chr(int(match[4], 8))
    return SIMPLE_ESCAPES.get(match[5], match[5])


def decoded_percent(text):
    # A format literal such as %%30 must not turn into a pane target.
    pieces = FORMAT_PERCENT.split(text)
    return (
        "%%".join(unquote(part, errors="surrogateescape") for part in text.split("%%")),
        "".join(piece if index % 2 else unquote(piece, errors="surrogateescape")
                for index, piece in enumerate(pieces)),
    )


def text_views(line):
    yield line
    if "%" not in line and "\\" not in line:
        return
    seen = {line}
    pending = [line]
    for _ in range(ENCODING_DEPTH):
        next_views = []
        for text in pending:
            views = decoded_percent(text) if "%" in text else ()
            if "\\" in text:
                views = (*views, ESCAPE.sub(decoded_escape, text))
            for decoded in views:
                if decoded not in seen:
                    seen.add(decoded)
                    next_views.append(decoded)
                    yield decoded
        if not next_views:
            break
        pending = next_views


def uuid_matches(line):
    dashed = list(DELIMITED_UUID.finditer(line))
    right_edges = {match.end() for match in dashed}
    for match in dashed:
        start, end = match.span()
        # Include adjacent alphanumeric text in the exact allow-list check.
        while start and line[start - 1].isalnum():
            start -= 1
        while end < len(line) and line[end].isalnum():
            end += 1
        yield "uuid", line[start:end], start + 1, None
    for match in HEX_TOKEN.finditer(line):
        token = match[0]
        # Short prefixes or suffixes sometimes get glued to a compact ID.
        # A compact suffix can also follow the last group of a dashed ID.
        if (32 <= len(token) <= 39 and (
            COMPACT_UUID.fullmatch(token[:32]) or COMPACT_UUID.fullmatch(token[-32:])
        )) or (match.end() - 32 in right_edges and COMPACT_UUID.fullmatch(token[-32:])) or (
            len(token) == 64 and COMPACT_UUID.fullmatch(token[:32]) and COMPACT_UUID.fullmatch(token[32:])
        ):
            yield "codex-id", token, match.start() + 1, None


def home_tokens(line):
    consumed = 0
    for root in HOME_START.finditer(line):
        start, end = root.span()
        if start < consumed:
            continue
        outer_quote = line[start - 1] if start and line[start - 1] in "\"'" else None
        quote = outer_quote
        parts = [root[0]]
        while end < len(line):
            char = line[end]
            if char == quote:
                end += 1
                if outer_quote and (end == len(line) or line[end].isspace()
                                    or line[end] in ",.:;})]>"):
                    break
                outer_quote = None
                quote = None
                continue
            if char == "\\" and end + 1 < len(line) and line[end + 1] in " \\\"'":
                end += 1
                char = line[end]
            elif not quote:
                if char.isspace() or char in "\x60<>|;{}":
                    break
                if char in "\"'":
                    if line.find(char, end + 1) < 0:
                        break
                    quote = char
                    end += 1
                    continue
            parts.append(char)
            end += 1
        consumed = end
        yield "home-path", "".join(parts), start + 1, None


def opaque_path(value):
    return DOTLESS_PATH.fullmatch(value) is not None


def opaque_body(value):
    unpadded = value.rstrip("=")
    if len(unpadded) < 200:
        return False
    if HEX_RUN.fullmatch(unpadded):
        return len(set(unpadded.lower())) >= MIN_HEX_DISTINCT
    return all(pattern.search(value) for pattern in BASE64_CLASSES) and not opaque_path(value)


def wrapped_bodies(lines):
    parts = []
    start = None
    width = 0
    for number, line in chain(lines, ((None, ""),)):
        part = line.strip()
        candidate = BASE64_LINE.fullmatch(part) and not opaque_path(part)
        short_tail = parts and candidate and len(part) < width and not parts[-1].endswith("=")
        if short_tail:
            # Encoders can emit a shorter final line, including without padding.
            parts.append(part)
        if parts and (not candidate or len(part) != width or parts[-1].endswith("=")):
            if len(parts) > 1:
                body = "".join(parts)
                if opaque_body(body):
                    if short_tail:
                        candidate = False
                    yield start, body, "\n".join(parts)
            parts.clear()
        if candidate and len(part) >= MIN_WRAP_WIDTH:
            if not parts:
                start, width = number, len(part)
            parts.append(part)


def decoded_wrapped(view):
    if "\n" not in view and "\r" not in view:
        return
    def scan_payload(start, payload):
        for _, body, _ in wrapped_bodies(enumerate(payload.splitlines(), 1)):
            yield "opaque", body, start + 1, None

    # Scan quoted payloads separately so their interior lines are only read once.
    start = 0
    for match in re.finditer(r'(?="([^"]*)")', view):
        if "\n" in match[1] or "\r" in match[1]:
            yield from scan_payload(start, view[start:match.start()])
            yield from scan_payload(match.start(1), match[1])
            start = match.end(1) + 1
    yield from scan_payload(start, view[start:])


def matches(line, deny):
    yield from uuid_matches(line)
    yield from home_tokens(line)
    for rule, pattern in IDENTIFIERS:
        for match in pattern.finditer(line):
            if rule == "pane-id" and PRINTF_DIRECTIVE.match(line, match.start()):
                continue
            yield rule, match[0], match.start() + 1, None
    for rule, pattern in PREFIXED_IDS:
        for match in pattern.finditer(line):
            suffix = match[0].split("_", 1)[1]
            if rule in ("request-id", "message-id", "tool-id"):
                if len(suffix) < 8 and suffix.isalpha():
                    continue
            elif len(suffix) < 8 or (len(suffix) < 20 and not any(c.isdigit() for c in suffix)):
                continue
            yield rule, match[0], match.start() + 1, None
    for match in BASE64_RUN.finditer(line):
        if opaque_body(match[0]):
            yield "opaque", match[0], match.start() + 1, None
    yield from decoded_wrapped(line)
    yield from deny_matches(line, deny)


def decoded_matches(line, deny):
    seen = Counter()
    for view in text_views(line):
        counts = Counter()
        for rule, value, column, entry in matches(view, deny):
            key = (rule, value, entry)
            counts[key] += 1
            if counts[key] > seen[key]:
                seen[key] = counts[key]
                yield rule, value, column, entry, view != line


def opaque_name(name):
    return any("\ud800" <= char <= "\udfff" for char in name)


def member_blocks(stream):
    chunk_size = 65536
    decoder = zlib.decompressobj(wbits=31)
    while not decoder.eof:
        block = stream.read(chunk_size)
        if not block:
            raise EOFError("Truncated member")
        while block and not decoder.eof:
            yield decoder.decompress(block, chunk_size)
            block = decoder.unconsumed_tail
    stream.seek(-len(decoder.unused_data), os.SEEK_CUR)


def block_lines(blocks):
    pending = []
    for block in blocks:
        parts = block.split(b"\n")
        for data in parts[:-1]:
            pending.append(data)
            yield b"".join(pending) + b"\n"
            pending.clear()
        pending.append(parts[-1])
    if any(pending):
        yield b"".join(pending)


def git_environment():
    # Inherited Git overrides can redirect -C to a different repository
    # or change which object store or history that repository exposes.
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    return dict(env, GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0")


class Audit:
    def __init__(self, allow, deny, scope, raw=False):
        self.allowed_ids = {entry.casefold() for entry in allow}
        self.allowed_paths = allow
        self.deny = deny
        self.scope = scope
        self.raw = raw
        self.key = os.urandom(32)
        self.names = {}
        self.files = self.messages = self.commits = self.bytes = 0
        self.empty_trees = 0
        self.base = self.tip = None
        self.hard = self.review = 0

    def digest(self, value):
        data = value.encode("utf-8", errors="surrogatepass")
        return hashlib.blake2b(data, key=self.key, digest_size=8).hexdigest()

    def display_name(self, location):
        if self.raw:
            return location
        if location not in self.names:
            mask = opaque_name(location) or any(decoded_matches(location, self.deny))
            self.names[location] = f"<name:{self.digest(location)}>" if mask else location
        return self.names[location]

    def record(self, rule, location, surface, line=None, column=None, value=None, context=None,
               *, entry=None, decoded=False, member=None):
        severity = "review" if rule == "deny-list" else "hard"
        if severity == "review":
            self.review += 1
        else:
            self.hard += 1
        result = dict(severity=severity, rule=rule, file=self.display_name(location), surface=surface)
        if line is not None:
            result["line"] = line
        if column is not None:
            result["column"] = column
        if member is not None:
            result["member"] = member
        if decoded:
            result["view"] = "decoded"
        if entry is not None:
            result["list"], result["entry"] = entry
        if self.raw and value is not None:
            result["match"] = value
        elif value is not None and entry is None:
            result["digest"] = self.digest(value)
        if self.raw and context is not None:
            result["context"] = context
        print(json.dumps(result, ensure_ascii=True))

    def text(self, line, location, surface, number, member=None):
        for rule, value, column, entry, decoded in decoded_matches(line, self.deny):
            if rule == "home-path" and (line if surface == "link" else value) in self.allowed_paths:
                continue
            if rule not in ("home-path", "deny-list", "opaque") and value.casefold() in self.allowed_ids:
                continue
            self.record(rule, location, surface, number, column, value, line,
                        entry=entry, decoded=decoded, member=member)

    def name(self, location, name):
        if opaque_name(name):
            self.record("undecodable", location, "name")
        self.text(name, location, "name", 1)

    def contents(self, stream, location, surface):
        try:
            if surface == "link":
                self.lines((stream.read(),), location, surface)
            elif stream.peek(2).startswith(b"\x1f\x8b"):
                members = self.gzip_members(stream, location)
                if members > 1:
                    stream.seek(0)
                    with gzip.GzipFile(fileobj=stream) as expanded:
                        self.lines(expanded, location, surface, count_bytes=False)
            elif surface == "content" and location.endswith(".gz"):
                self.record("unreadable", location, surface)
            else:
                self.lines(stream, location, surface)
        except (OSError, EOFError, zlib.error):
            self.record("unreadable", location, surface)

    def gzip_members(self, stream, location):
        member = 0
        while stream.peek(1):
            if stream.peek(1).startswith(b"\x00"):
                stream.read(1)  # Gzip allows zero padding between members.
                continue
            member += 1
            start = stream.tell()
            self.gzip_header(stream, location, member)
            stream.seek(start)
            self.lines(block_lines(member_blocks(stream)), location, "gzip-member", member=member)
        return member

    def gzip_header(self, stream, location, member):
        header = stream.read(10)
        if len(header) != 10 or header[:3] != b"\x1f\x8b\x08":
            raise gzip.BadGzipFile("Invalid member header")
        flags = header[3]
        if flags & 0x04:
            extra_length = int.from_bytes(stream.read(2), "little")
            if extra_length:
                self.record("undecodable", location, "gzip-extra", member=member)
                stream.read(extra_length)
        for bit, surface in ((0x08, "gzip-name"), (0x10, "gzip-comment")):
            if not flags & bit:
                continue
            value = bytearray()
            while byte := stream.read(1):
                if byte == b"\x00":
                    break
                value.extend(byte)
            self.lines((bytes(value),), location, surface, member=member)

    def lines(self, stream, location, surface, *, member=None, count_bytes=True):
        def inspect_lines():
            for number, data in enumerate(stream, 1):
                if count_bytes:
                    self.bytes += len(data)
                try:
                    line = data.decode("utf-8")
                    if "\x00" in line:
                        raise ValueError("NUL in text")
                except ValueError:
                    self.record("undecodable", location, surface, number, member=member)
                    yield number, ""
                    continue
                if surface != "link":
                    line = line.rstrip("\r\n")
                self.text(line, location, surface, number, member)
                yield number, line

        for number, body, context in wrapped_bodies(inspect_lines()):
            self.record("opaque", location, surface, number, value=body,
                        context=context, member=member)

    def filesystem(self, root):
        if root.is_symlink() or not root.is_dir():
            self.record("unreadable", "<tree>", "directory")
            return
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    children = sorted(entries, key=lambda entry: entry.name)
            except OSError:
                self.record("unreadable", directory.relative_to(root).as_posix(), "directory")
                continue
            if not children and directory != root:
                name = directory.relative_to(root).as_posix()
                self.name(name, name)
            for entry in children:
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                try:
                    mode = entry.stat(follow_symlinks=False).st_mode
                    if stat.S_ISDIR(mode):
                        pending.append(path)
                        continue
                    self.files += 1
                    self.name(name, name)
                    if stat.S_ISLNK(mode):
                        with io.BufferedReader(io.BytesIO(os.fsencode(path.readlink()))) as stream:
                            self.contents(stream, name, "link")
                    elif stat.S_ISREG(mode):
                        with path.open("rb") as stream:
                            self.contents(stream, name, "content")
                    else:
                        self.record("unreadable", name, "content")
                except OSError:
                    self.record("unreadable", name, "entry")

    def git_range(self, repo, revisions, changed):
        env = git_environment()

        def git(*args):
            return subprocess.run(
                ["git", *GIT_OPTIONS, "-C", str(repo), *args],
                env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            ).stdout

        try:
            if git("rev-parse", "--is-shallow-repository").strip() != b"false":
                self.record("incomplete-git", "<range>", "git")
                return
            grafts = os.fsdecode(git("rev-parse", "--git-path", "info/grafts").rstrip(b"\n"))
            grafts_path = repo / grafts
            try:
                if not stat.S_ISREG(grafts_path.stat().st_mode):
                    self.record("incomplete-git", "<range>", "git")
                    return
                with grafts_path.open("rb") as stream:
                    if any(line.strip() and not line.lstrip().startswith(b"#") for line in stream):
                        self.record("incomplete-git", "<range>", "git")
                        return
            except FileNotFoundError:
                pass
            base_ref, tip_ref = revisions.split("..")

            def resolve(ref):
                return git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode("ascii").strip()

            self.tip = resolve(tip_ref)
            self.base = resolve(base_ref) if base_ref else None
            if changed:
                git("merge-base", "--is-ancestor", self.base, self.tip)
            selection = f"{self.base}..{self.tip}" if self.base else self.tip
            commits = git("rev-list", "--reverse", selection, "--").decode("ascii").splitlines()
            for commit in commits:
                self.commits += 1
                headers, separator, message = git("cat-file", "commit", commit).partition(b"\n\n")
                self.lines(io.BytesIO(headers), f"{commit}:<header>", "commit-header")
                if separator:
                    self.messages += 1
                    self.lines(io.BytesIO(message), f"{commit}:<message>", "message")
                else:
                    self.record("incomplete-git", f"{commit}:<message>", "git")
                before = self.files
                self.git_tree(git, commit, changed)
                if not changed and self.files == before:
                    self.empty_trees += 1
        except (OSError, ValueError, subprocess.CalledProcessError):
            self.record("incomplete-git", "<range>", "git")

    def git_tree(self, git, commit, changed):
        selected = None
        if changed:
            selected = set(git(
                "diff-tree", "-r", "-t", "-m", "--root", "--no-commit-id", "--no-renames",
                "--no-ext-diff", "--no-textconv", "--no-relative", "--name-only", "-z", commit,
            ).split(b"\0"))
        for entry in git("ls-tree", "--full-tree", "-rtz", commit).split(b"\0"):
            if not entry:
                continue
            metadata, filename = entry.split(b"\t", 1)
            if selected is not None and filename not in selected:
                continue
            mode, kind, oid = metadata.split()
            name = filename.decode("utf-8", errors="surrogateescape")
            location = f"{commit}:{name}"
            self.name(location, name)
            if kind == b"tree":
                continue
            self.files += 1
            if kind != b"blob":
                self.record("incomplete-git", location, "gitlink")
                continue
            try:
                blob = git("cat-file", "blob", oid)
            except subprocess.CalledProcessError:
                self.record("incomplete-git", location, "git")
                continue
            surface = "link" if mode == b"120000" else "content"
            with io.BufferedReader(io.BytesIO(blob)) as stream:
                self.contents(stream, location, surface)

    def empty(self):
        if self.scope == "tree":
            return not self.files
        return not self.commits or (self.scope == "full-tree" and self.empty_trees > 0)

    def summary(self):
        fields = dict(
            scope=self.scope, partial=self.scope == "changed-files",
            files=self.files, bytes=self.bytes, commits=self.commits, messages=self.messages,
            hard=self.hard, review=self.review,
        )
        if self.scope != "tree":
            fields.update(base=self.base, tip=self.tip, empty_trees=self.empty_trees)
        print(json.dumps(fields))


def load_list(path, kind):
    try:
        return list(list_entries(path, deny=kind == "deny"))
    except FileNotFoundError as error:
        raise ValueError(f"The {kind} list file is missing.") from error
    except UnicodeError as error:
        raise ValueError(f"The {kind} list could not be read as UTF-8.") from error
    except OSError as error:
        raise ValueError(f"The {kind} list could not be read.") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tree", type=Path, help="directory to audit")
    source.add_argument("--git-range", metavar="[BASE]..TIP", help="audit each commit tree and message")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Git repository")
    parser.add_argument("--changed", action="store_true", help="audit changed file post-images only")
    parser.add_argument("--allow-list", type=Path, help="one exact synthetic identifier or path per line")
    parser.add_argument("--deny-list", type=Path, action="append", default=[],
                        help="one private review term per line; can be repeated")
    parser.add_argument("--allow-empty-deny-list", action="store_true")
    parser.add_argument("--allow-empty-scan", action="store_true")
    parser.add_argument("--unredacted", action="store_true", help="include matched text and private context")
    args = parser.parse_args(argv)
    if args.changed and not args.git_range:
        parser.error("--changed requires --git-range")
    if args.git_range is not None:
        endpoints = args.git_range.split("..")
        if (len(endpoints) != 2 or not endpoints[1] or
                any(ref.startswith(".") or ref.endswith(".") for ref in endpoints)):
            parser.error("--git-range requires BASE..TIP or ..TIP")
        if args.changed and not endpoints[0]:
            parser.error("--changed requires an explicit BASE")
    try:
        allow = {entry for entry, _ in load_list(args.allow_list, "allow")} if args.allow_list else set()
        deny = []
        if not args.deny_list and not args.allow_empty_deny_list:
            raise ValueError("Supply a nonempty deny list or explicitly waive it.")
        for list_number, path in enumerate(args.deny_list, 1):
            entries = load_list(path, "deny")
            if not entries and not args.allow_empty_deny_list:
                raise ValueError("Every supplied deny list must contain an entry.")
            deny.extend((entry, list_number, number) for entry, number in entries)
        patterns = deny_patterns(deny)
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    scope = "tree" if args.tree else "changed-files" if args.changed else "full-tree"
    audit = Audit(allow, patterns, scope, args.unredacted)
    if args.tree:
        audit.filesystem(args.tree)
    else:
        audit.git_range(args.repo, args.git_range, args.changed)
    audit.summary()
    if not audit.hard and audit.empty() and not args.allow_empty_scan:
        print("Configuration error: the selection is empty or contains an empty commit tree.", file=sys.stderr)
        return 2
    return int(bool(audit.hard or audit.review))


if __name__ == "__main__":
    sys.exit(main())
