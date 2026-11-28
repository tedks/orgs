#!/usr/bin/env python3
"""Audit publication inputs without using the usage tooling or its state."""
import argparse
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
import zlib

HOME_PREFIX = "/ho" + "me/"
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
IDENTIFIERS = (
    ("uuid", re.compile(rf"(?<![0-9a-f]){UUID}(?![0-9a-f])", re.I)),
    ("request-id", re.compile(r"\breq_(?:[a-z0-9]+_)*[a-z0-9][a-z0-9-]*\b", re.I)),
    ("codex-id", re.compile(r"(?<![0-9a-f])01[0-9a-f]{30}(?![0-9a-f])", re.I)),
    ("home-path", re.compile(re.escape(HOME_PREFIX) + r"""(?:\\ |[^\s"'\x60<>|,;:{}\[\]()\\])+""")),
    ("pane-id", re.compile(r"(?<![\w%])%[0-9]+(?![\w%$]|\.[0-9])")),
)
JSON_STRING = re.compile(r'"(?:[^"\\\x00-\x1f]|\\.)*"')


def list_entries(path):
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def deny_patterns(entries):
    variants = entries | {re.sub(r"[^\w-]|_", "-", value) for value in entries}
    groups = "|".join(map(re.escape, sorted(variants, key=lambda value: (-len(value), value))))
    return re.compile(rf"(?<!\w)(?:{groups})(?!\w)", re.I) if groups else None


def digest(value):
    data = value.encode("utf-8", errors="surrogatepass")
    return hashlib.sha256(data).hexdigest()[:16]


def request_literal(value):
    # Serialized request ids have an opaque suffix. Ignore short source words
    # made only of letters. A digit, hyphen or underscore also marks opacity.
    suffix = value[4:]
    return len(suffix) >= 8 or any(not char.isalpha() for char in suffix)


def matches(line, deny):
    for rule, pattern in IDENTIFIERS:
        for match in pattern.finditer(line):
            value = match[0]
            if rule != "request-id" or request_literal(value):
                yield rule, value, match.start() + 1
    if deny:
        for match in deny.finditer(line):
            yield "deny-list", match[0], match.start() + 1


def escaped_matches(line, deny):
    if "\\" not in line:
        return
    for match in JSON_STRING.finditer(line):
        if "\\" not in match[0]:
            continue
        try:
            decoded = json.loads(match[0])
        except json.JSONDecodeError:
            continue
        raw = {(rule, value) for rule, value, _ in matches(match[0], deny)}
        for rule, value, _ in matches(decoded, deny):
            if (rule, value) not in raw:
                yield rule, value, match.start() + 1


class Audit:
    def __init__(self, allow, deny, raw=False):
        self.allowed_ids = {entry.casefold() for entry in allow}
        self.allowed_paths = allow
        self.deny = deny_patterns(deny)
        self.raw = raw
        self.files = self.messages = self.commits = self.bytes = 0
        self.hard = self.review = 0

    def record(self, rule, location, surface, line=None, column=None, value=None, context=None):
        severity = "review" if rule == "deny-list" else "hard"
        if severity == "review":
            self.review += 1
        else:
            self.hard += 1
        if not self.raw and any(chain(matches(location, self.deny), escaped_matches(location, self.deny))):
            location = f"<name:{digest(location)}>"
        result = dict(severity=severity, rule=rule, file=location, surface=surface)
        if line is not None:
            result.update(line=line, column=column)
        if value is not None:
            result["match" if self.raw else "digest"] = value if self.raw else digest(value)
        if self.raw and context is not None:
            result["context"] = context
        print(json.dumps(result, ensure_ascii=True))

    def text(self, line, location, surface, number):
        for rule, value, column in chain(matches(line, self.deny), escaped_matches(line, self.deny)):
            if rule == "home-path" and value in self.allowed_paths:
                continue
            if rule not in ("home-path", "deny-list") and value.casefold() in self.allowed_ids:
                continue
            self.record(rule, location, surface, number, column, value, line)

    def name(self, location, name):
        if any(0xDC80 <= ord(char) <= 0xDCFF for char in name):
            self.record("undecodable", location, "name")
        self.text(name, location, "name", 1)

    def contents(self, stream, location, surface):
        try:
            if stream.peek(2).startswith(b"\x1f\x8b"):
                with gzip.GzipFile(fileobj=stream) as expanded:
                    self.lines(expanded, location, surface)
                stream.seek(0)
                self.gzip_headers(stream, location)
            elif surface == "content" and location.endswith(".gz"):
                self.record("unreadable", location, surface)
            else:
                self.lines(stream, location, surface)
        except (OSError, EOFError, zlib.error):
            self.record("unreadable", location, surface)

    def gzip_headers(self, stream, location):
        # GzipFile throws away original names and comments. Walk the members
        # separately, retaining neither compressed nor expanded data.
        chunk_size = 65536
        member = 0
        while stream.peek(1):
            if stream.peek(1).startswith(b"\x00"):
                stream.read(1)  # Gzip allows zero padding between members.
                continue
            member += 1
            start = stream.tell()
            header = stream.read(10)
            if len(header) != 10 or header[:3] != b"\x1f\x8b\x08":
                raise gzip.BadGzipFile("Invalid member header")
            flags = header[3]
            if flags & 0x04:
                extra_length = int.from_bytes(stream.read(2), "little")
                if extra_length:
                    self.record("undecodable", location, "gzip-extra", member)
                    stream.read(extra_length)
            for bit, surface in ((0x08, "gzip-name"), (0x10, "gzip-comment")):
                if not flags & bit:
                    continue
                value = bytearray()
                while byte := stream.read(1):
                    if byte == b"\x00":
                        break
                    value.extend(byte)
                self.bytes += len(value)
                try:
                    self.text(value.decode("utf-8"), location, surface, member)
                except UnicodeError:
                    self.record("undecodable", location, surface, member)

            stream.seek(start)
            decoder = zlib.decompressobj(wbits=31)
            while not decoder.eof:
                block = stream.read(chunk_size)
                if not block:
                    raise EOFError("Truncated member")
                while block and not decoder.eof:
                    decoder.decompress(block, chunk_size)
                    block = decoder.unconsumed_tail
            stream.seek(-len(decoder.unused_data), os.SEEK_CUR)

    def lines(self, stream, location, surface):
        for number, data in enumerate(stream, 1):
            self.bytes += len(data)
            try:
                line = data.decode("utf-8").rstrip("\r\n")
                if "\x00" in line:
                    raise ValueError("NUL in text")
            except ValueError:
                self.record("undecodable", location, surface, number)
                continue
            self.text(line, location, surface, number)

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
            ends = [git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()
                    for ref in revisions.split("..")]
            commits = git("rev-list", "--reverse", b"..".join(ends), "--").decode("ascii").splitlines()
            for commit in commits:
                self.commits += 1
                _, separator, message = git("cat-file", "commit", commit).partition(b"\n\n")
                if separator:
                    self.messages += 1
                    with io.BufferedReader(io.BytesIO(message)) as stream:
                        self.contents(stream, f"{commit}:<message>", "message")
                else:
                    self.record("incomplete-git", f"{commit}:<message>", "git")
                selected = None
                if changed:
                    selected = set(git(
                        "diff-tree", "-r", "-m", "--root", "--no-commit-id", "--no-renames",
                        "--no-ext-diff", "--no-textconv", "--no-relative", "--name-only", "-z", commit,
                    ).split(b"\0"))
                for entry in git("ls-tree", "--full-tree", "-rz", commit).split(b"\0"):
                    if not entry:
                        continue
                    metadata, filename = entry.split(b"\t", 1)
                    if selected is not None and filename not in selected:
                        continue
                    mode, kind, oid = metadata.split()
                    name = os.fsdecode(filename)
                    location = f"{commit}:{name}"
                    self.files += 1
                    self.name(location, name)
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
        except (OSError, ValueError, subprocess.CalledProcessError):
            self.record("incomplete-git", "<range>", "git")

    def summary(self):
        print(json.dumps(dict(
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
        allow = list_entries(args.allow_list) if args.allow_list else set()
        deny = set()
        for path in args.deny_list:
            try:
                deny.update(list_entries(path))
            except FileNotFoundError:
                if not args.allow_empty_deny_list:
                    raise
    except (OSError, UnicodeError):
        print("Configuration error: a supplied list could not be read as UTF-8.", file=sys.stderr)
        return 2
    if not deny and not args.allow_empty_deny_list:
        print("Configuration error: supply a nonempty deny list or explicitly waive it.", file=sys.stderr)
        return 2
    audit = Audit(allow, deny, args.unredacted)
    if args.tree:
        audit.filesystem(args.tree)
    else:
        audit.git_range(args.repo, args.git_range, args.changed)
    audit.summary()
    return int(bool(audit.hard or audit.review))


if __name__ == "__main__":
    sys.exit(main())
