#!/usr/bin/env python3
"""search-guard: notice whole-tree searches from broad roots, and refuse them
when an agent issued them.

One classifier, three callers:

  wrap      the PATH wrappers ~/.bin/{rg,find,grep} hand it their argv. It
            decides from the exact argv the binary would receive (globs already
            expanded, variables already substituted, so nothing is expanded
            again: a `~` here is a file named ~).
  check     a harness hook hands it command TEXT (a Bash tool call, a
            `bash -lc` script). It lexes the text without evaluating it.
  measure   scans Claude transcripts and Codex rollouts for the same shapes, so
            the rate can be re-measured after a change.

What "broad" means, stated once:

  A search is broad when it walks one of the broad roots (~, ~/Projects, /,
  /home, /nix, /nix/store, /tmp, /var/tmp) with nothing that bounds the walk.
  Only the root itself counts: ~/Projects/example is a project, not a broad
  root, and /tmp/run-123 is somebody's scratch directory. A relative path, `.`,
  `..` or no path at all is resolved against the working directory first, so
  `rg foo` run from ~/Projects is as broad as `rg foo ~/Projects`.

  The only bound is a depth limit of MAX_DEPTH or less: rg --max-depth/-d,
  find -maxdepth (the last one given wins, as in the tools). Filters are not
  bounds, because they filter what a full walk finds: `find ~ -name apksigner`,
  `rg --files -g '**/ditz/*.md' ~/Projects`, `rg -t py foo ~` and
  `grep -r --include='*.md' foo ~` each still read every directory under the
  root. The depth limit has a ceiling for the same reason: `find ~ -maxdepth 6`
  was a measured shape.

Assumptions, and what happens outside them:
  - $HOME is the same path on every host an `ssh host '...'` reaches (true on
    this fleet; elsewhere a remote command is judged against the local HOME).
  - Text is lexed, never evaluated. A variable other than $HOME, a command
    substitution used as a path, an alias, a function or eval is opaque, and
    opaque means allowed: this is a guard against accidents, not against an
    agent that is trying to search $HOME.
  - Every failure to CLASSIFY is an ALLOW: a crash, a parse it cannot follow.
    The guard must never be the reason a legitimate command fails. A failure
    to LOG a refusal that was already decided is not one of these -- the
    refusal still happens, with a line on stderr saying the log was skipped.
    Only the tripwire's count misses the event. See cmd_wrap/cmd_hook.
"""
import argparse
import json
import os
import posixpath
import re
import socket
import sys
import time
from datetime import datetime, timezone

MAX_DEPTH = 3
OVERRIDE_ENV = "SEARCH_UNBOUNDED"
LOG_MAX_BYTES = 5 * 1024 * 1024
# What `wrap` exits with to mean "refused". Not 2: python itself exits 2 when
# it cannot open the script or argparse rejects the arguments, and a broken
# install must read as "allow", not "refuse".
REFUSE_EXIT = 97

SHELLS = {"sh", "bash", "dash", "zsh", "ksh"}
GREP_NAMES = {"grep", "egrep", "fgrep", "rgrep"}
TOOLS = {"rg", "find"} | GREP_NAMES
INFO_FLAGS = {"--help", "--version", "-help", "-version", "-h", "-V"}


def home_dir():
    return os.environ.get("HOME") or posixpath.expanduser("~")


def broad_roots(home):
    roots = {"/", "/home", "/nix", "/nix/store", "/tmp", "/var/tmp"}
    if home and home != "/":
        home = posixpath.normpath(home)
        roots |= {home, posixpath.join(home, "Projects")}
    return roots


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or posixpath.join(home_dir(), ".local", "state")
    return posixpath.join(base, "search-guard")


# --------------------------------------------------------------------------
# paths

_GLOB = re.compile(r"[*?\[]")
_DYNAMIC = re.compile(r"\$|`")


def normalize(path, cwd, home, expand=True):
    """Absolute, normalised spelling of a path argument, or None if it cannot be
    known without evaluating shell text.

    expand=True is for command text, where the shell has yet to expand `~` and
    $HOME. expand=False is for argv the shell already expanded: there `~` and
    `$HOME` are literal file names."""
    if expand:
        if path == "~" or path.startswith("~/"):
            path = home + path[1:]
        for var in ("${HOME}", "$HOME"):
            if path == var or path.startswith(var + "/"):
                path = home + path[len(var):]
        if _DYNAMIC.search(path) or path.startswith("~"):
            return None
    if not path.startswith("/"):
        if not cwd:
            return None
        path = posixpath.join(cwd, path)
    out = posixpath.normpath(path)
    # normpath keeps a leading '//' (POSIX allows it to mean something else);
    # for a search root it never does here.
    return "/" + out.lstrip("/") if out.startswith("//") else out


def broad_root_of(path, cwd, home, roots, expand=True):
    """The broad root this path walks, or None.

    A path that globs every child of a broad root (`~/Projects/*`, `/tmp/*/`,
    `~/**`) walks that root as surely as naming it. Any narrower glob
    (`/tmp/run-*`, `~/Projects/*/node_modules`) does not. Only command text has
    unexpanded globs; the wrapper sees the expansion."""
    p = normalize(path, cwd, home, expand)
    if p is None:
        return None
    if p in roots:
        return p
    head, tail = posixpath.split(p)
    if expand and tail in ("*", "**", ".*") and head in roots:
        return head
    return None


# --------------------------------------------------------------------------
# argv classification

class Verdict:
    __slots__ = ("tool", "root", "argv")

    def __init__(self, tool, root, argv):
        self.tool, self.root, self.argv = tool, root, argv

    def hint(self):
        where = "your worktree" if self.root != "/tmp" else "your own /tmp/<dir>"
        if self.tool in ("Grep", "Glob"):
            scoped = f"set path to {where}"
        elif self.tool == "find":
            scoped = f"find <{where}> ..., or add -maxdepth {MAX_DEPTH} or less"
        elif self.tool == "grep":
            scoped = f"grep -r PATTERN <{where}> (grep has no depth limit)"
        else:
            scoped = f"{self.tool} PATTERN <{where}>, or add --max-depth {MAX_DEPTH} or less"
        return (f"search-guard: refused `{self.tool}` over {self.root}: it walks the whole tree "
                f"(name/glob/type filters do not shorten the walk). Scope it: {scoped}. "
                f"Override: {OVERRIDE_ENV}=1.")

    def as_dict(self):
        return {"tool": self.tool, "root": self.root, "argv": self.argv}


def _depth_ok(value):
    try:
        return int(value) <= MAX_DEPTH
    except (TypeError, ValueError):
        return False


# rg options that take a value as the next word (or attached: -tpy, --type=py).
RG_SHORT_VALUE = set("ABCEMTdefgjmrt")
RG_LONG_VALUE = {
    "after-context", "before-context", "context", "regexp", "file", "glob",
    "iglob", "type", "type-not", "type-add", "type-clear", "max-depth",
    "max-count", "max-columns", "max-filesize", "encoding", "threads", "sort",
    "sortr", "color", "colors", "path-separator", "pre", "pre-glob", "replace",
    "ignore-file", "engine", "dfa-size-limit", "regex-size-limit",
    "context-separator", "field-context-separator", "field-match-separator",
    "hostname-bin", "hyperlink-format", "generate", "maxdepth",
}
RG_NO_SEARCH = {"--type-list", "--pcre2-version"} | INFO_FLAGS


def classify_rg(argv, cwd, home, roots, stdin_is_data, expand):
    positional, patterns_given, files_mode, depth = [], False, False, None
    i, n = 1, len(argv)
    while i < n:
        a = argv[i]
        if a == "--":
            positional.extend(argv[i + 1:])
            break
        if a in RG_NO_SEARCH or a.startswith("--generate"):
            return None
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in RG_LONG_VALUE and not eq:
                val = argv[i + 1] if i + 1 < n else ""
                i += 1
            if name in ("regexp", "file"):
                patterns_given = True
            elif name == "files":
                files_mode = True
            elif name in ("max-depth", "maxdepth"):
                depth = val
        elif a.startswith("-") and a != "-":
            j = 1
            while j < len(a):
                c = a[j]
                if c in RG_SHORT_VALUE:
                    val = a[j + 1:]
                    if not val:
                        val = argv[i + 1] if i + 1 < n else ""
                        i += 1
                    if c in "ef":
                        patterns_given = True
                    elif c == "d":
                        depth = val
                    break
                j += 1
        else:
            positional.append(a)
        i += 1
    if depth is not None and _depth_ok(depth):
        return None
    paths = positional if (patterns_given or files_mode) else positional[1:]
    if not paths:
        if stdin_is_data and not files_mode:
            return None
        paths = ["."]
    return _first_broad("rg", paths, argv, cwd, home, roots, expand)


FIND_EXPR_START = re.compile(r"^[-(!,)]")


def classify_find(argv, cwd, home, roots, expand):
    i, n = 1, len(argv)
    # Global options: -H -L -P, -D debugopts, -O<level>, and a `--` before the paths.
    while i < n:
        a = argv[i]
        if a == "--":
            i += 1
            break
        if a in ("-H", "-L", "-P"):
            i += 1
        elif a == "-D":
            if i + 1 < n and argv[i + 1] == "help":
                return None     # prints the debug options and exits
            i += 2
        elif a.startswith("-O") and a[2:].isdigit():
            i += 1
        else:
            break
    # GNU find honours --help/--version where a path could start (after any
    # global options); later (`-name --help`) it is an operand.
    # GNU find prints its usage and walks nothing even after `--`
    # (`find -- --help /`, verified with GNU findutils 4.9.0).
    if i < n and argv[i] in INFO_FLAGS:
        return None
    paths = []
    while i < n and not FIND_EXPR_START.match(argv[i]):
        paths.append(argv[i])
        i += 1
    expr = argv[i:]
    depth = None
    for k, a in enumerate(expr):
        if a == "-maxdepth" and k + 1 < len(expr):
            depth = expr[k + 1]
    if depth is not None and _depth_ok(depth):
        return None
    return _first_broad("find", paths or ["."], argv, cwd, home, roots, expand)


GREP_SHORT_VALUE = set("efmABCdD")
GREP_LONG_VALUE = {
    "regexp", "file", "max-count", "after-context", "before-context",
    "context", "directories", "devices", "include", "exclude", "exclude-dir",
    "exclude-from", "label", "group-separator",
}


def classify_grep(argv, cwd, home, roots, expand):
    recursive = posixpath.basename(argv[0]) == "rgrep"
    positional, patterns_given = [], False
    i, n = 1, len(argv)
    while i < n:
        a = argv[i]
        if a == "--":
            positional.extend(argv[i + 1:])
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in ("help", "version"):
                return None     # in option position; `-e --help` was consumed as a value
            if name in GREP_LONG_VALUE and not eq:
                val = argv[i + 1] if i + 1 < n else ""
                i += 1
            if name in ("recursive", "dereference-recursive"):
                recursive = True
            elif name == "directories" and val == "recurse":
                recursive = True
            elif name in ("regexp", "file"):
                patterns_given = True
        elif a.startswith("-") and a != "-":
            j = 1
            while j < len(a):
                c = a[j]
                if c == "V":
                    return None
                if c in "rR":
                    recursive = True
                elif c in GREP_SHORT_VALUE:
                    val = a[j + 1:]
                    if not val:
                        val = argv[i + 1] if i + 1 < n else ""
                        i += 1
                    if c in "ef":
                        patterns_given = True
                    elif c == "d" and val == "recurse":
                        recursive = True
                    break
                j += 1
        else:
            positional.append(a)
        i += 1
    if not recursive:
        return None
    paths = positional if patterns_given else positional[1:]
    return _first_broad("grep", paths or ["."], argv, cwd, home, roots, expand)


def _first_broad(tool, paths, argv, cwd, home, roots, expand):
    for p in paths:
        root = broad_root_of(p, cwd, home, roots, expand)
        if root:
            return Verdict(tool, root, list(argv))
    return None


def classify_argv(argv, cwd, home=None, stdin_is_data=False, expand=False):
    """Verdict if argv is an unbounded search of a broad root, else None.
    expand=False (the default) treats argv as already expanded by a shell."""
    if not argv:
        return None
    home = home or home_dir()
    roots = broad_roots(home)
    name = posixpath.basename(argv[0])
    if name == "rg":
        return classify_rg(argv, cwd, home, roots, stdin_is_data, expand)
    if name == "find":
        return classify_find(argv, cwd, home, roots, expand)
    if name in GREP_NAMES:
        return classify_grep(argv, cwd, home, roots, expand)
    return None


# --------------------------------------------------------------------------
# command text

class Word(str):
    """A shell word with its quotes removed. `literal` is True when any part of
    it was quoted, which turns off tilde expansion; `noexpand` when a `$` sat
    inside single quotes, which turns off parameter expansion. `stdin` is set
    only on the pseudo-words the lexer emits for a stdin redirection: the
    source file, or STDIN_DATA for a here-document, here-string or dup."""
    literal = False
    noexpand = False
    stdin = None


STDIN_DATA = "<data>"


CHAR_DEVICES = {"/dev/null", "/dev/zero", "/dev/full", "/dev/random",
                "/dev/urandom", "/dev/console", "/dev/tty"}


def _stdin_is_data(source, current):
    """Whether a stdin redirected from `source` gives rg something to read.
    rg reads stdin only when it is a file, pipe or socket: a character device
    (null, tty, zero, a pty) is not. Only known device names count as devices
    -- /dev/shm/x is an ordinary file. /dev/stdin and /dev/fd/0 keep stdin as
    it was; anything else counts as data (fail open)."""
    if source.startswith("/"):
        parts = [p for p in source.split("/") if p not in ("", ".")]
        if ".." in parts:
            # What `..` reaches depends on symlinks before it, which text
            # cannot know: unknown is data (fail open).
            return True
        source = "/" + "/".join(parts)        # //dev//./null is /dev/null
    if source in ("/dev/stdin", "/dev/fd/0"):
        return current
    if source in CHAR_DEVICES or source.startswith(("/dev/pts/", "/dev/tty")):
        return False
    return True


def _stdin_mark(source):
    w = Word("")
    w.stdin = source
    return w


# Stands for a substitution's output inside a word: opaque (it has a `$`),
# so a path made from one is never judged.
SUBST = "$(...)"
# Bracket a substitution's commands in the token stream.
SUB_OPEN, SUB_CLOSE = "$(", ")$"


def _matching_paren(text, i):
    """Index of the ')' closing the '(' at text[i-1], or len(text)."""
    depth, n = 1, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def lex(text):
    """Split shell text into words and operators without evaluating it.

    Returns Words, and for each operator a plain str from
    {';', '&', '&&', '||', '|', '(', ')'}. A newline is ';'. A redirection and
    its target are dropped (so `2>/dev/null` neither becomes an argument nor
    eats the word before it). A here-document body is skipped.

    A substitution -- `$( )`, backticks, `<( )`, `>( )`, quoted or not --
    leaves the opaque placeholder SUBST in the word it sits in, so the outer
    command keeps its shape (`rg foo "$(pwd)"` still has a path argument). The
    commands inside it run first, so they are emitted BEFORE the outer command,
    between the markers SUB_OPEN and SUB_CLOSE, which the classifier treats as
    transparent: the outer command still sees the operator before it."""
    i, n = 0, len(text)
    word, quoted, noexpand, in_word = [], False, False, False
    heredocs, pending_redirect = [], False
    out, deferred = [], []
    seg_start = 0       # where the current simple command's tokens begin

    def end_word():
        nonlocal word, quoted, noexpand, in_word, pending_redirect
        if in_word:
            w = Word("".join(word))
            w.literal, w.noexpand = quoted, noexpand
            if pending_redirect == "heredoc":
                heredocs.append(w)
            elif pending_redirect == "stdin":
                out.append(_stdin_mark(str(w)))
            elif not pending_redirect:
                out.append(w)
            pending_redirect = False
        word, quoted, noexpand, in_word = [], False, False, False

    def emit(op):
        """End the word, put this command's substitutions before it, add op."""
        nonlocal seg_start
        end_word()
        if deferred:
            groups = []
            for d in deferred:
                groups += [SUB_OPEN] + d + [SUB_CLOSE]
            deferred.clear()
            out[seg_start:seg_start] = groups
        if op:
            out.append(op)
        seg_start = len(out)

    def subst(inner):
        nonlocal in_word
        deferred.append(lex(inner))
        word.append(SUBST)
        in_word = True

    def nested(start):
        """Defer text[start:] up to its matching ')'; return the index after it."""
        end = _matching_paren(text, start)
        subst(text[start:end])
        return end + 1

    def backtick(start):
        """Defer text[start:] up to the closing backtick; return the index after it."""
        k = text.find("`", start)
        k = n if k < 0 else k
        subst(text[start:k])
        return k + 1

    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            if text[i + 1] != "\n":
                word.append(text[i + 1])
                in_word = True
            i += 2
            continue
        if c == "$" and i + 1 < n and text[i + 1] == "'":
            # ANSI-C quoting: backslash escapes, ends at an unescaped quote.
            j = i + 2
            buf = []
            while j < n and text[j] != "'":
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            word.append("".join(buf))
            quoted = in_word = True
            i = j + 1
            continue
        if c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            part = text[i + 1:j]
            word.append(part)
            quoted = in_word = True
            noexpand = noexpand or "$" in part
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n and text[j + 1] in '"\\$`\n':
                    if text[j + 1] != "\n":
                        buf.append(text[j + 1])
                    j += 2
                    continue
                if text[j] == "$" and j + 1 < n and text[j + 1] == "(":
                    word.append("".join(buf))
                    buf = []
                    j = nested(j + 2)
                    continue
                if text[j] == "`":
                    word.append("".join(buf))
                    buf = []
                    j = backtick(j + 1)
                    continue
                buf.append(text[j])
                j += 1
            word.append("".join(buf))
            quoted = in_word = True
            i = j + 1
            continue
        if c == "#" and not in_word:
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in " \t\r":
            end_word()
            i += 1
            continue
        if c == "\n":
            emit(";")
            i += 1
            # Skip each pending here-document body, in order.
            while heredocs:
                delim = heredocs.pop(0)
                while i < n:
                    j = text.find("\n", i)
                    j = n if j < 0 else j
                    line = text[i:j]
                    i = j + 1
                    if line.strip("\t") == delim:
                        break
            continue
        if c == "$" and i + 1 < n and text[i + 1] == "(":
            i = nested(i + 2)
            continue
        if c == "`":
            i = backtick(i + 1)
            continue
        if c in "<>" and i + 1 < n and text[i + 1] == "(":
            # Process substitution, not a redirection: an argument of its own.
            end_word()
            i = nested(i + 2)
            continue
        if c in "<>":
            # A word made only of digits right before the operator is its fd.
            fd = ""
            if in_word and not quoted and "".join(word).isdigit():
                fd = "".join(word)
                word, in_word = [], False
            else:
                end_word()
            j = i
            while j < n and text[j] in "<>&|-":
                j += 1
            op = text[i:j]
            i = j
            to_stdin = op.startswith("<") and fd in ("", "0")
            if op.startswith("<<") and not op.startswith("<<<"):
                pending_redirect = "heredoc"
                if to_stdin:
                    out.append(_stdin_mark(STDIN_DATA))
            elif op.endswith("&") or op.endswith("&-"):
                # >&2, 2>&1, <&- : the target is the fd digits that follow.
                k = i
                while i < n and text[i].isdigit():
                    i += 1
                # <&- closes stdin; <&0 keeps it as it was; <&N is another file.
                if to_stdin and text[k:i] != "0":
                    out.append(_stdin_mark("/dev/null" if op.endswith("-") else STDIN_DATA))
            elif op.startswith("<<<"):
                pending_redirect = True
                if to_stdin:
                    out.append(_stdin_mark(STDIN_DATA))
            else:
                pending_redirect = "stdin" if to_stdin else True
            continue
        if c == "&" and i + 1 < n and text[i + 1] == ">":
            end_word()
            i += 2
            if i < n and text[i] == ">":
                i += 1
            pending_redirect = True
            continue
        if c in ";&|()":
            two = text[i:i + 2]
            if two in ("&&", "||", ";;", "|&"):
                emit({"|&": "|", ";;": ";"}.get(two, two))
                i += 2
            else:
                emit(c)
                i += 1
            continue
        word.append(c)
        in_word = True
        i += 1
    emit(None)
    return out


_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SSH_VALUE = set("BbcDEeFIiJLlmOoPpQRSWw")
# Reserved words and grouping that can precede a command in the same segment.
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}",
            "fi", "done", "esac"}


def strip_prefix(words):
    """Drop assignments, reserved words and transparent wrappers.
    Returns (words, override); words is empty when the segment cannot search
    (e.g. `command -v find`)."""
    override = False
    i = 0
    while i < len(words):
        w = words[i]
        if w in KEYWORDS and not w.literal:
            i += 1
            continue
        if _ASSIGN.match(w):
            if w == f"{OVERRIDE_ENV}=1":
                override = True
            i += 1
            continue
        name = posixpath.basename(w)
        if name in ("command", "builtin"):
            i += 1
            while i < len(words) and words[i].startswith("-"):
                if any(f in words[i] for f in "vV"):
                    return [], override  # a lookup, not a run
                i += 1
        elif name in ("exec", "nohup"):
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 1
        elif name in ("env", "sudo", "time", "nice", "ionice", "stdbuf", "chrt"):
            takes_value = {"env": "uSC", "sudo": "ugpChDRT", "nice": "n",
                           "ionice": "cnp", "chrt": "p", "stdbuf": "ioe"}.get(name, "")
            i += 1
            while i < len(words):
                a = words[i]
                if _ASSIGN.match(a):
                    if a == f"{OVERRIDE_ENV}=1":
                        override = True
                    i += 1
                elif a.startswith("-") and len(a) > 1:
                    i += 2 if (len(a) == 2 and a[1] in takes_value) else 1
                else:
                    break
        elif name == "timeout":
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in ("-s", "-k", "--signal", "--kill-after") else 1
            i += 1  # the duration
        else:
            break
    return words[i:], override


def classify_command(text, cwd, home=None, _depth=0):
    """Verdicts for every unbounded broad search in a shell command string.

    `cd` moves the cwd for what follows, but only where it certainly runs and
    certainly stays: a `cd` inside ( ) or a substitution is undone at the
    closing paren, a `cd` in a pipeline runs in a subshell and changes
    nothing, and a `cd` after && or || may not have run at all, so the cwd
    after it is unknown -- and an unknown cwd judges nothing (fail open)."""
    home = home or home_dir()
    if _depth > 4 or not text:
        return []
    found = []
    state = {"cwd": cwd, "override": False}
    stack = []

    def run(words, piped, prev_op, next_op):
        # An explicit stdin redirection decides what stdin is: a file, a
        # here-document or a here-string is data; /dev/null is not.
        marks = [w for w in words if w.stdin is not None]
        if marks:
            words = [w for w in words if w.stdin is None]
            # Redirections apply left to right; each sees the one before.
            for m in marks:
                piped = _stdin_is_data(m.stdin, piped)
        in_pipeline = prev_op == "|" or next_op == "|"
        words, seg_override = strip_prefix(words)
        if not words:
            return
        skip = state["override"] or seg_override
        name = posixpath.basename(words[0])
        if name == "export":
            if f"{OVERRIDE_ENV}=1" in words[1:]:
                state["override"] = True
            return
        if name == "cd":
            if in_pipeline:
                return
            if prev_op in ("&&", "||"):
                state["cwd"] = None
                return
            args = [w for w in words[1:] if not w.startswith("-")] or ["~"]
            state["cwd"] = normalize(args[0], state["cwd"], home) if args[0] != "-" else None
            return
        if name in SHELLS:
            script = _shell_script(words)
            if script is not None and not skip:
                found.extend(classify_command(script, state["cwd"], home, _depth + 1))
            return
        if name == "ssh":
            remote = _ssh_command(words)
            if remote and not skip:
                found.extend(classify_command(remote, home, home, _depth + 1))
            return
        if name not in TOOLS or skip:
            return
        argv = []
        for w in words:
            if w.literal and w.startswith("~"):
                w = "./" + w          # a quoted ~ is a file named ~
            elif w.noexpand:
                w = "./" + w          # '$HOME' in single quotes is literal
            argv.append(str(w))
        v = classify_argv(argv, state["cwd"], home, stdin_is_data=piped, expand=True)
        if v:
            found.append(v)

    # Group words into simple commands, keeping the operators around them.
    items, seg = [], []
    for t in lex(text):
        if isinstance(t, Word):
            seg.append(t)
            continue
        if seg:
            items.append(seg)
        seg = []
        items.append(t)
    if seg:
        items.append(seg)

    # `inherited`: every command inside a ( ) or substitution that belongs to
    # a pipeline element reads that element's stdin, whatever its own
    # control flow. It is tracked apart from `prev`, which stays the
    # operator before the command within its own group (for cd).
    prev, inherited = None, False
    for k, it in enumerate(items):
        if isinstance(it, str):
            if it in ("(", SUB_OPEN):
                stack.append((dict(state), prev, inherited))
                inherited = inherited or prev == "|"
                prev = None
            elif it in (")", SUB_CLOSE) and stack:
                saved, before, inherited = stack.pop()
                state.update(saved)
                # A substitution is transparent: the command after it still
                # follows whatever operator preceded the substitution.
                prev = before if it == SUB_CLOSE else it
            else:
                prev = it
            continue
        nxt = items[k + 1] if k + 1 < len(items) and isinstance(items[k + 1], str) else None
        if nxt == SUB_OPEN:
            nxt = None
        run(it, prev == "|" or inherited, prev, nxt)
    return found


def _shell_script(words):
    """The -c script of a shell invocation, or None. Options may come before
    or after -c (`bash -euo pipefail -c`, `bash -c -l`); the script is the
    first operand."""
    seen_c, k = False, 1
    while k < len(words):
        a = words[k]
        if a == "--":
            k += 1
            break
        if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            k += 2
            continue
        if a.startswith("--"):
            k += 1
            continue
        if a[:1] in ("-", "+") and len(a) > 1:
            if a[0] == "-" and "c" in a[1:]:
                seen_c = True
            if "o" in a[1:] or "O" in a[1:]:
                k += 1          # -euo pipefail: the bundle's o takes the next word
            k += 1
            continue
        break
    if seen_c and k < len(words):
        return words[k]
    return None


def _ssh_command(words):
    i = 1
    while i < len(words):
        a = words[i]
        if a.startswith("-") and len(a) > 1:
            i += 2 if (len(a) == 2 and a[1] in SSH_VALUE) else 1
            continue
        rest = words[i + 1:]
        return " ".join(rest) if rest else None
    return None


# --------------------------------------------------------------------------
# Claude Grep / Glob tool inputs

def classify_tool_input(tool, inp, cwd, home=None):
    """Verdict for a Claude Grep or Glob call that walks a broad root.
    As for the shell tools, a glob or type filter does not shorten the walk."""
    home = home or home_dir()
    roots = broad_roots(home)
    path = inp.get("path") or cwd or ""
    if tool == "Grep":
        root = broad_root_of(path, cwd, home, roots)
        return Verdict("Grep", root, [json.dumps(inp, sort_keys=True)]) if root else None
    if tool == "Glob":
        pattern = inp.get("pattern") or ""
        if pattern.startswith("/"):
            path, pattern = "/", pattern.lstrip("/")
        elif pattern.startswith("~/"):
            path, pattern = home, pattern[2:]
        # The walk starts at the literal directories before the first glob.
        parts = pattern.split("/")
        literal = []
        for part in parts[:-1]:
            if _GLOB.search(part):
                break
            literal.append(part)
        base = posixpath.join(path, *literal) if literal else path
        rest = parts[len(literal):]
        if "**" not in rest[:-1] and not (len(rest) > 1 and _GLOB.search(rest[0])):
            # One level of glob below the base is a directory listing, not a walk.
            return None
        root = broad_root_of(base, cwd, home, roots)
        return Verdict("Glob", root, [json.dumps(inp, sort_keys=True)]) if root else None
    return None


# --------------------------------------------------------------------------
# wrapper support

# Harness processes by /proc/<pid>/comm (15 characters at most).
HARNESS_COMMS = {"claude", "codex", "opencode", "agy", "antigravity", "gemini"}
# Harnesses that run under a JavaScript runtime are recognised by the package
# their entry script lives in -- never by a bare name, which any directory an
# agent works in (~/Projects/codex-foo, /tmp/claude-1000) could contain.
RUNTIMES = {"node", "bun", "deno"}
RUNTIME_FLAGS = {"--no-warnings", "--no-deprecation", "--enable-source-maps",
                 "--trace-warnings", "--expose-gc", "--preserve-symlinks"}
HARNESS_PACKAGES = re.compile(
    r"/node_modules/(?:@anthropic-ai/claude-code|@openai/codex|@google/gemini-cli|opencode-ai)/")


def _proc(pid):
    """(comm, argv, ppid, exe) of a process, or None."""
    try:
        with open(f"/proc/{pid}/comm", "rb") as f:
            comm = f.read().decode(errors="replace").strip()
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        with open(f"/proc/{pid}/stat", "rb") as f:
            stat = f.read().decode(errors="replace")
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return None
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = ""
    return comm, argv, ppid, exe


def _is_harness(comm, argv, exe=""):
    if comm in HARNESS_COMMS or comm.startswith("codex"):
        return True
    # Node 24 names its main thread "MainThread", so the runtime is read from
    # the executable, not from comm.
    runtime = posixpath.basename(exe) in RUNTIMES or comm in RUNTIMES
    if not runtime:
        return False
    # The entry script is the first operand, but only options known to take
    # no separate value may come before it: `node -r hook.js build.js` would
    # otherwise read hook.js as the entry. Anything else -- an option that may
    # take a value, inline source (-e, -p, -eCODE) -- leaves the entry script
    # uncertain, and uncertain is not the harness (fail open).
    for a in argv[1:]:
        if not a.startswith("-"):
            return bool(HARNESS_PACKAGES.search(a))
        if a in RUNTIME_FLAGS or (a.startswith("--") and "=" in a
                                   and not a.startswith(("--eval=", "--print="))):
            continue
        return False
    return False


def _is_command_shell(argv):
    return bool(argv) and posixpath.basename(argv[0]).lstrip("-") in SHELLS \
        and _shell_script(argv) is not None


def parent_is_agent_command(pid, max_shells=6):
    """True when pid is what ran an agent's tool call.

    Walk up from pid over shells running a -c string (the tool call's own
    shell, and forked subshells of it, which share its argv); the first process
    that is not one must be the harness. pid may be the harness itself, because
    bash execs the last simple command of a -c string in place, so
    `bash -lc 'find ~'` leaves find with the harness as its parent.

    Anything else in between -- a script (`bash deploy`), make, npm, python,
    xargs, git, an MCP server -- means the agent ran a program and the program
    ran the search, and that passes."""
    for _ in range(max_shells + 1):
        info = _proc(pid)
        if info is None:
            return False
        comm, argv, ppid, exe = info
        if _is_harness(comm, argv, exe):
            return True
        if not _is_command_shell(argv):
            return False
        pid = ppid
    return False


def session_hint():
    env = os.environ
    for key in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID"):
        if env.get(key):
            return {"session": env[key], "harness": "claude" if key.startswith("CLAUDE") else "codex"}
    for key in ("GEMINI_CLI", "OPENCODE"):
        if env.get(key):
            return {"session": None, "harness": key.lower()}
    return {"session": None, "harness": None}


def log_event(verdict, cwd, source, decision="refused", session=None):
    """Append one JSON line. Returns whether it was written; never raises."""
    try:
        d = state_dir()
        os.makedirs(d, exist_ok=True)
        path = posixpath.join(d, "log")
        try:
            if os.path.getsize(path) > LOG_MAX_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        rec = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "host": socket.gethostname(),
            "source": source,
            "decision": decision,
            "cwd": cwd,
            "tool": verdict.tool,
            "root": verdict.root,
            "argv": verdict.argv,
            "pane": os.environ.get("TMUX_PANE"),
            "tmux_socket": os.environ.get("TMUX", "").partition(",")[0] or None,
        }
        rec.update(session or session_hint())
        line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            return os.write(fd, line) == len(line)
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 - see docstring
        return False


def _log_or_warn(verdict, cwd, source, session=None):
    """Best-effort log of a refusal already decided. Never changes the
    decision: on failure (a full disk, an unwritable XDG_STATE_HOME) it only
    notes on stderr that this event goes uncounted by the tripwire. The note
    itself is best-effort too -- the same full disk can take stderr down
    with the log (e.g. stderr piped to a file on it), and a write failure
    here must not raise back into the caller and undo a decision already
    made: for cmd_hook especially, that would stop the deny from ever being
    printed."""
    if not log_event(verdict, cwd, source, session=session):
        try:
            print("search-guard: could not write the log; this refusal goes uncounted.",
                  file=sys.stderr)
        except Exception:  # noqa: BLE001 - see docstring
            pass


def stdin_is_data():
    """rg's own rule: with no path, it searches stdin when stdin is a file or a
    pipe. Anything else (a tty, /dev/null, closed) means it walks the cwd."""
    import stat
    try:
        mode = os.fstat(0).st_mode
    except OSError:
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode) or stat.S_ISSOCK(mode)


def cmd_wrap(args):
    """Exit REFUSE_EXIT (hint on stderr) to refuse, 0 to run. The caller has
    already checked the markers, the TTY and the override.

    The refusal does not depend on whether it can be logged: a full disk must
    not turn a refusal into free rein. A refusal that cannot be logged still
    refuses, with an extra line on stderr saying the log was skipped."""
    if not parent_is_agent_command(args.ppid):
        return 0
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = os.environ.get("PWD")
    v = classify_argv(args.argv, cwd, stdin_is_data=stdin_is_data())
    if not v:
        return 0
    try:
        print(v.hint(), file=sys.stderr)
    except Exception:  # noqa: BLE001 - a failed hint must not undo REFUSE_EXIT
        pass
    _log_or_warn(v, cwd, "wrapper")
    return REFUSE_EXIT


def cmd_check(args):
    """Command text on stdin; prints one JSON line per verdict. Exit 2 when any."""
    text = sys.stdin.read()
    vs = classify_command(text, args.cwd)
    for v in vs:
        print(json.dumps({**v.as_dict(), "hint": v.hint()}))
    return 2 if vs else 0


def cmd_hook(args):
    """Claude Code PreToolUse hook: hook JSON on stdin; on a broad search,
    print a deny decision. Prints nothing (allow) for anything else, including
    input it cannot read.

    The deny does not depend on whether the refusal can be logged: a full
    disk must not turn a refusal into an allow. A refusal that cannot be
    logged still denies, with an extra line on stderr saying the log was
    skipped."""
    try:
        event = json.loads(sys.stdin.read())
        tool = event.get("tool_name")
        inp = event.get("tool_input") or {}
        cwd = event.get("cwd") or None
    except (ValueError, AttributeError):
        return 0
    if tool == "Bash":
        vs = classify_command(inp.get("command") or "", cwd)
    elif tool in ("Grep", "Glob"):
        v = classify_tool_input(tool, inp, cwd)
        vs = [v] if v else []
    else:
        return 0
    if not vs:
        return 0
    v = vs[0]
    # The hook input names the session; the environment may belong to
    # whatever launched the hook process.
    session = {"session": event.get("session_id"), "harness": "claude"} if event.get("session_id") else None
    _log_or_warn(v, cwd, "claude-hook", session=session)
    reason = (v.hint() + " With the Grep or Glob tool, set path to the directory you "
              "mean (your worktree), not a broad root.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    return 0


# --------------------------------------------------------------------------
# measurement

_EXEC_CMD = re.compile(r'exec_command\(\s*\{\s*cmd\s*:\s*("(?:[^"\\]|\\.)*")')
_EXEC_WORKDIR = re.compile(r'workdir\s*:\s*("(?:[^"\\]|\\.)*")')


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def iter_claude(root, since, until):
    """(ts, session, cwd, kind, payload) for every Bash/Grep/Glob call."""
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath[len(root):].count("/") >= 3:
            dirnames[:] = []
        for fn in filenames:
            if not fn.endswith(".jsonl"):
                continue
            path = posixpath.join(dirpath, fn)
            try:
                if os.path.getmtime(path) < since:
                    continue
                f = open(path, encoding="utf-8", errors="replace")
            except OSError:
                continue
            with f:
                for line in f:
                    if '"tool_use"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    ts = _parse_ts(rec.get("timestamp"))
                    if ts is None or not (since <= ts < until):
                        continue
                    content = (rec.get("message") or {}).get("content")
                    if not isinstance(content, list):
                        continue
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "tool_use":
                            continue
                        name = item.get("name")
                        if name not in ("Bash", "Grep", "Glob") or item.get("id") in seen:
                            continue
                        seen.add(item.get("id"))
                        yield ts, rec.get("sessionId"), rec.get("cwd"), name, item.get("input") or {}


def iter_codex(root, since, until):
    """(ts, session, cwd, 'Bash', {'command': text}) for every shell call."""
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".jsonl"):
                continue
            path = posixpath.join(dirpath, fn)
            try:
                if os.path.getmtime(path) < since:
                    continue
                f = open(path, encoding="utf-8", errors="replace")
            except OSError:
                continue
            session, cwd = fn, None
            with f:
                for line in f:
                    if '"session_meta"' in line or '"turn_context"' in line:
                        try:
                            p = json.loads(line).get("payload") or {}
                        except ValueError:
                            continue
                        session = p.get("id") or p.get("session_id") or session
                        cwd = p.get("cwd") or cwd
                        continue
                    if "exec_command" not in line and '"shell"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    ts = _parse_ts(rec.get("timestamp"))
                    if ts is None or not (since <= ts < until):
                        continue
                    p = rec.get("payload") or {}
                    call = p.get("call_id") or p.get("id")
                    if call in seen:
                        continue
                    seen.add(call)
                    for text, wd in _codex_commands(p):
                        yield ts, session, wd or cwd, "Bash", {"command": text}


def _codex_commands(p):
    kind = p.get("type")
    if kind == "custom_tool_call":
        src = p.get("input") or ""
        wd = _EXEC_WORKDIR.search(src)
        wd = _js_string(wd.group(1)) if wd else None
        for m in _EXEC_CMD.finditer(src):
            text = _js_string(m.group(1))
            if text is not None:
                yield text, wd
    elif kind == "function_call" and p.get("name") in ("exec_command", "shell", "local_shell"):
        try:
            a = json.loads(p.get("arguments") or "{}")
        except ValueError:
            return
        cmd = a.get("cmd") or a.get("command")
        if isinstance(cmd, list):
            # ["bash", "-lc", script] is how the shell tool spells it.
            cmd = cmd[-1] if len(cmd) >= 3 and "c" in cmd[1] else " ".join(cmd)
        if isinstance(cmd, str):
            yield cmd, a.get("workdir")


def _js_string(lit):
    try:
        return json.loads(lit)
    except ValueError:
        return None


_SEARCHY = re.compile(r"\b(?:rg|find|[ef]?grep|rgrep)\b")


def cmd_measure(args):
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc).timestamp() \
        if args.since else time.time() - 7 * 86400
    until = datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc).timestamp() \
        if args.until else time.time() + 60
    home = home_dir()
    sources = []
    if args.provider in ("all", "claude"):
        sources.append(("claude", iter_claude(args.claude_root or posixpath.join(home, ".claude", "projects"), since, until)))
    if args.provider in ("all", "codex"):
        sources.append(("codex", iter_codex(args.codex_root or posixpath.join(home, ".codex", "sessions"), since, until)))
    stats, examples, per_session = {}, [], {}
    for provider, it in sources:
        s = stats.setdefault(provider, {"commands": 0, "searches": 0, "tool_searches": 0, "broad": 0})
        for ts, session, cwd, kind, inp in it:
            if kind == "Bash":
                text = inp.get("command") or ""
                s["commands"] += 1
                if not _SEARCHY.search(text):
                    continue
                s["searches"] += 1
                try:
                    vs = classify_command(text, cwd, home)
                except Exception:  # noqa: BLE001 - a lexer bug must not stop a measurement
                    vs = []
                shown = text
            else:
                s["tool_searches"] += 1
                v = classify_tool_input(kind, inp, cwd, home)
                vs = [v] if v else []
                shown = f"{kind} {json.dumps(inp, sort_keys=True)}"
            if not vs:
                continue
            s["broad"] += 1
            key = (provider, session)
            per_session[key] = per_session.get(key, 0) + 1
            examples.append({"provider": provider, "session": session, "cwd": cwd,
                             "ts": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "root": vs[0].root, "tool": vs[0].tool,
                             "command": shown[:args.width]})
    if args.json:
        print(json.dumps({"stats": stats, "sessions": [
            {"provider": p, "session": s, "broad": c} for (p, s), c in
            sorted(per_session.items(), key=lambda kv: -kv[1])], "examples": examples}, indent=1))
        return 0
    for provider, s in stats.items():
        print(f"{provider}: {s['commands']} shell commands, {s['searches']} search commands, "
              f"{s['tool_searches']} Grep/Glob calls, {s['broad']} broad")
    if per_session:
        print("\nbroad searches per session:")
        for (p, sess), c in sorted(per_session.items(), key=lambda kv: -kv[1])[:args.top]:
            print(f"  {c:4d}  {p:6s} {sess}")
    if examples:
        print("\nexamples:")
        for e in examples[-args.top:]:
            print(f"  {e['ts']} {e['provider']:6s} [{e['tool']} {e['root']}] {e['command']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="search-guard", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wrap", help="decide for a PATH wrapper (internal)")
    w.add_argument("ppid", type=int)
    w.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("hook", help="Claude Code PreToolUse hook (JSON on stdin)")
    c = sub.add_parser("check", help="classify command text read from stdin")
    c.add_argument("--cwd", default=os.getcwd())
    m = sub.add_parser("measure", help="count broad searches in Claude/Codex logs")
    m.add_argument("--since", help="UTC date or datetime (default: 7 days ago)")
    m.add_argument("--until", help="UTC date or datetime (default: now)")
    m.add_argument("--provider", choices=("all", "claude", "codex"), default="all")
    m.add_argument("--claude-root")
    m.add_argument("--codex-root")
    m.add_argument("--top", type=int, default=20)
    m.add_argument("--width", type=int, default=160)
    m.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "wrap":
        if args.argv and args.argv[0] == "--":
            args.argv = args.argv[1:]
        return cmd_wrap(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "hook":
        return cmd_hook(args)
    return cmd_measure(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BrokenPipeError:
        # `search-guard measure | head`: the reader left; nothing to report.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
    except Exception as e:  # noqa: BLE001 - every failure is an allow
        print(f"search-guard: internal error, allowing: {e}", file=sys.stderr)
        sys.exit(0)
