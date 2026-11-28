#!/usr/bin/env python3
"""Audit publication inputs without using the usage tooling or its state."""
import argparse
from collections import Counter
import gzip
import hashlib
import io
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
COMPACT_UUID = r"[0-9a-f]{12}[1-8][0-9a-f]{3}[89ab][0-9a-f]{15}"
ID_SUFFIX = r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?(?![a-z0-9])"
PATH_TOKEN = r"""(?:\\ |[^\s"'\x60<>|,;{}\[\]()\\])"""
HOME_ROOTS = ("/var" + HOME_PREFIX, HOME_PREFIX, "/" + "Users/", "/" + "root/")
HOME_PATHS = (
    "(?:" + "|".join(map(re.escape, HOME_ROOTS)) + ")" + PATH_TOKEN + "*"
    + r"|(?<![\w~])~[A-Za-z_][A-Za-z0-9_.-]*" + PATH_TOKEN + "*"
)
IDENTIFIERS = (
    ("uuid", re.compile(UUID, re.I)),
    ("codex-id", re.compile(rf"(?<![0-9a-f]){COMPACT_UUID}(?![0-9a-f])", re.I)),
    ("request-id", re.compile(r"(?<![a-z0-9])req_" + ID_SUFFIX, re.I)),
    ("message-id", re.compile(r"(?<![a-z0-9])msg_" + ID_SUFFIX, re.I)),
    ("tool-id", re.compile(r"(?<![a-z0-9])toolu_" + ID_SUFFIX, re.I)),
    ("home-path", re.compile(HOME_PATHS)),
    ("pane-id", re.compile(r"(?:(?<![\w%])|(?<=-t)|(?<=\bpane))%[0-9]+(?![\w%$]|\.[0-9])", re.I)),
    ("opaque", re.compile(r"[a-zA-Z0-9+/_-]{200,}={0,2}")),
)
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


def list_entries(path):
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        entry = normalized(line).strip()
        if entry and not entry.startswith("#"):
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
    lower = line.lower()
    seen = set()
    for prefix, pattern, entry in deny:
        if prefix not in lower:
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
    # Preserve the escaped literal percent in format strings such as %%30.
    return "%%".join(unquote(part, errors="surrogateescape") for part in text.split("%%"))


def text_views(line):
    yield line
    if "%" not in line and "\\" not in line:
        return
    seen = {line}
    pending = [line]
    for _ in range(ENCODING_DEPTH):
        next_views = []
        for text in pending:
            for decoded in (decoded_percent(text) if "%" in text else text,
                            ESCAPE.sub(decoded_escape, text) if "\\" in text else text):
                if decoded not in seen:
                    seen.add(decoded)
                    next_views.append(decoded)
                    yield decoded
        if not next_views:
            break
        pending = next_views


def matches(line, deny):
    for rule, pattern in IDENTIFIERS:
        for match in pattern.finditer(line):
            value = match[0]
            if rule in ("request-id", "message-id", "tool-id"):
                # Ignore short all-letter source words that resemble a prefix.
                suffix = value.split("_", 1)[1]
                if len(suffix) < 8 and suffix.isalpha():
                    continue
            yield rule, value, match.start() + 1, None
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
            if rule == "home-path" and value in self.allowed_paths:
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
            if stream.peek(2).startswith(b"\x1f\x8b"):
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
        for number, data in enumerate(stream, 1):
            if count_bytes:
                self.bytes += len(data)
            try:
                line = data.decode("utf-8").rstrip("\r\n")
                if "\x00" in line:
                    raise ValueError("NUL in text")
            except ValueError:
                self.record("undecodable", location, surface, number, member=member)
                continue
            self.text(line, location, surface, number, member)

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
        env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0")

        def git(*args):
            return subprocess.run(
                ["git", "--no-replace-objects", "-C", str(repo), *args],
                env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            ).stdout

        try:
            if git("rev-parse", "--is-shallow-repository").strip() != b"false":
                self.record("incomplete-git", "<range>", "git")
                return
            grafts = env.get("GIT_GRAFT_FILE") or os.fsdecode(
                git("rev-parse", "--git-path", "info/grafts").rstrip(b"\n"))
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
            ends = [git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()
                    for ref in revisions.split("..")]
            if changed:
                git("merge-base", "--is-ancestor", *ends)
            commits = git("rev-list", "--reverse", b"..".join(ends), "--").decode("ascii").splitlines()
            for commit in commits:
                self.commits += 1
                headers, separator, message = git("cat-file", "commit", commit).partition(b"\n\n")
                self.lines(io.BytesIO(headers), f"{commit}:<header>", "commit-header")
                if separator:
                    self.messages += 1
                    self.lines(io.BytesIO(message), f"{commit}:<message>", "message")
                else:
                    self.record("incomplete-git", f"{commit}:<message>", "git")
                self.git_tree(git, commit, changed)
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
        return not (self.files if self.scope == "tree" else self.commits)

    def summary(self):
        print(json.dumps(dict(
            scope=self.scope, partial=self.scope == "changed-files",
            files=self.files, bytes=self.bytes, commits=self.commits, messages=self.messages,
            hard=self.hard, review=self.review,
        )))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tree", type=Path, help="directory to audit")
    source.add_argument("--git-range", metavar="BASE..TIP", help="audit each commit tree and message")
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
        if len(endpoints) != 2 or not all(
            ref and not ref.startswith(".") and not ref.endswith(".") for ref in endpoints
        ):
            parser.error("--git-range requires an explicit BASE..TIP")
    try:
        allow = {entry for entry, _ in list_entries(args.allow_list)} if args.allow_list else set()
        deny = []
        if not args.deny_list and not args.allow_empty_deny_list:
            raise ValueError("Supply a nonempty deny list or explicitly waive it.")
        for list_number, path in enumerate(args.deny_list, 1):
            try:
                entries = list(list_entries(path))
            except FileNotFoundError:
                if not args.allow_empty_deny_list:
                    raise
                continue
            if not entries and not args.allow_empty_deny_list:
                raise ValueError("Every supplied deny list must contain an entry.")
            deny.extend((entry, list_number, number) for entry, number in entries)
        patterns = deny_patterns(deny)
    except (OSError, UnicodeError):
        print("Configuration error: a supplied list could not be read as UTF-8.", file=sys.stderr)
        return 2
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
        print("Configuration error: the selected scan is empty.", file=sys.stderr)
        return 2
    return int(bool(audit.hard or audit.review))


if __name__ == "__main__":
    sys.exit(main())
