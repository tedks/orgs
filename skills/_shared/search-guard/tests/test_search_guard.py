#!/usr/bin/env python3
"""Tests for the search-guard classifier.
Run: python3 skills/_shared/search-guard/tests/test_search_guard.py
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import search_guard as sg  # noqa: E402

HOME = "/home/u"
CWD = "/home/u/Projects/repo"


class _ExplodingStream(io.StringIO):
    """A stderr stand-in whose write() raises, the way a full disk would if
    stderr is itself redirected to a file on it."""

    def write(self, s):
        raise OSError(28, "No space left on device")


def broad(text, cwd=CWD):
    return [(v.tool, v.root) for v in sg.classify_command(text, cwd, HOME)]


class MeasuredShapes(unittest.TestCase):
    """The shapes the 2026-10-09..16 measurement found, each refused."""

    def test_rg_files_over_projects(self):
        self.assertEqual(broad("rg --files /home/u/Projects | rg '/ditz/.*md$' | head"),
                         [("rg", "/home/u/Projects")])

    def test_find_home_by_name(self):
        self.assertEqual(broad("find /home/u -type f -name apksigner"), [("find", "/home/u")])

    def test_find_tilde_deep_maxdepth(self):
        self.assertEqual(broad("find ~ -maxdepth 6 -type d -path '*node_modules/@vendor/pkg'"),
                         [("find", "/home/u")])

    def test_find_root_with_prune(self):
        self.assertEqual(broad("find / -path /proc -prune -o -name kiosk.move -print 2>/dev/null"),
                         [("find", "/")])

    def test_rg_nix_store(self):
        self.assertEqual(broad("rg --files /nix/store | rg gofmt"), [("rg", "/nix/store")])

    def test_grep_recursive_root(self):
        self.assertEqual(broad("grep -rn foo / 2>/dev/null"), [("grep", "/")])


class Bounds(unittest.TestCase):
    def test_maxdepth_boundary(self):
        self.assertEqual(broad(f"find ~ -maxdepth {sg.MAX_DEPTH} -name x"), [])
        self.assertEqual(broad(f"find ~ -maxdepth {sg.MAX_DEPTH + 1} -name x"), [("find", "/home/u")])

    def test_rg_max_depth_boundary(self):
        self.assertEqual(broad(f"rg --max-depth {sg.MAX_DEPTH} foo ~"), [])
        self.assertEqual(broad(f"rg --max-depth={sg.MAX_DEPTH} foo ~"), [])
        self.assertEqual(broad(f"rg -d{sg.MAX_DEPTH + 1} foo ~"), [("rg", "/home/u")])

    def test_filters_are_not_bounds(self):
        # A glob, type or include filters what a full walk finds; the walk is
        # the cost. `rg --files -g '**/ditz/*.md' ~/Projects` IS the measured
        # `rg --files ~/Projects | rg ditz` shape.
        for cmd in ("rg -g '*.py' foo ~/Projects", "rg --glob=*.md foo ~", "rg -tpy foo ~",
                    "rg --type py foo ~", "rg --files -g '**/ditz/*.md' ~/Projects",
                    "rg --iglob x foo /", "rg --type-not js foo ~", "rg foo -g '!node_modules' ~",
                    "grep -rn --include=*.md kupfer ~/Projects"):
            self.assertNotEqual(broad(cmd), [], cmd)

    def test_last_depth_wins(self):
        self.assertNotEqual(broad("find ~ -maxdepth 2 -maxdepth 9 -name x"), [])
        self.assertEqual(broad("find ~ -maxdepth 9 -maxdepth 2 -name x"), [])
        self.assertNotEqual(broad("rg --max-depth 2 --max-depth 50 foo ~"), [])

    def test_name_is_not_a_bound(self):
        self.assertEqual(broad("find ~/Projects -name '*.md'"), [("find", "/home/u/Projects")])

    def test_maxdepth_value_survives_redirect(self):
        # `2 2>/dev/null`: the first 2 is -maxdepth's value, the second an fd.
        self.assertEqual(broad("find ~ -maxdepth 2 2>/dev/null -name x"), [])


class NotBroad(unittest.TestCase):
    def test_scoped_paths(self):
        for cmd in ("rg foo ~/Projects/example", "find . -name x", "find /tmp/run-123 -name x",
                    "grep -rn foo src", "rg --files", "find /home/u/Projects/repo/..x -name y"):
            self.assertEqual(broad(cmd), [], cmd)

    def test_grep_not_recursive(self):
        self.assertEqual(broad("grep foo /tmp/x.log ~/notes.txt"), [])

    def test_rg_reading_a_pipe(self):
        self.assertEqual(broad("ls | rg foo", cwd=HOME), [])

    def test_rg_no_path_from_home_walks_home(self):
        self.assertEqual(broad("rg foo", cwd=HOME), [("rg", "/home/u")])

    def test_text_mentioning_a_search(self):
        for cmd in ('echo "find ~ -name x"', "git commit -m 'stop find / -name x'",
                    "printf '%s\\n' 'rg --files ~'"):
            self.assertEqual(broad(cmd), [], cmd)

    def test_heredoc_body_is_not_a_command(self):
        self.assertEqual(broad("cat <<'EOF'\nfind ~ -name x\nEOF\nls"), [])
        self.assertEqual(broad("cat <<-EOF\n\tfind ~ -name x\n\tEOF\nfind ~ -name y"),
                         [("find", "/home/u")])

    def test_quoted_tilde_is_literal(self):
        self.assertEqual(broad("find '~' -name x"), [])
        self.assertEqual(broad("find '$HOME' -name x"), [])

    def test_wrapper_argv_is_already_expanded(self):
        # The shell expanded `~` already; a `~` reaching argv is a file name.
        for arg in ("~", "$HOME", "~/Projects"):
            self.assertIsNone(sg.classify_argv(["find", arg, "-name", "x"], HOME, HOME), arg)
        self.assertIsNotNone(sg.classify_argv(["find", HOME, "-name", "x"], CWD, HOME))

    def test_narrow_glob(self):
        self.assertEqual(broad("find /tmp/run-* -name x"), [])
        self.assertEqual(broad("find ~/Projects/*/node_modules -name x"), [])

    def test_unknown_variable_is_opaque(self):
        self.assertEqual(broad("find $DIR -name x"), [])

    def test_info_modes(self):
        self.assertEqual(broad("rg --type-list"), [])
        self.assertEqual(broad("rg --version", cwd="/"), [])
        for cmd in ("find --version", "find --help", "find -help", "grep --version", "grep -r --help",
                    "grep -rV", "find -L --help", "find -H -O2 --version"):
            self.assertEqual(broad(cmd, cwd=HOME), [], cmd)

    def test_info_flag_as_operand_is_not_info(self):
        self.assertEqual(broad("find / -name --help"), [("find", "/")])
        self.assertEqual(broad("grep -r -e --help /"), [("grep", "/")])
        self.assertEqual(broad("grep -r --regexp --version /"), [("grep", "/")])

    def test_command_lookup(self):
        self.assertEqual(broad("command -v find", cwd=HOME), [])
        self.assertEqual(broad("command -v rg && rg --version", cwd=HOME), [])
        self.assertEqual(broad("command find ~ -name x"), [("find", "/home/u")])

    def test_find_double_dash(self):
        self.assertEqual(broad("find -- ~ -name x"), [("find", "/home/u")])
        # GNU find prints usage here and walks nothing (checked against findutils).
        self.assertEqual(broad("find -- --help / -name x"), [])

    def test_find_debug_help(self):
        self.assertEqual(broad("find -D help", cwd=HOME), [])


class Resolution(unittest.TestCase):
    def test_cd_in_a_subshell_does_not_leak(self):
        self.assertEqual(broad("(cd ~); rg foo"), [])
        self.assertEqual(broad("x=$(cd ~ && pwd); rg foo ."), [])
        self.assertEqual(broad("(cd ~ && rg foo)"), [("rg", "/home/u")])

    def test_cd_that_may_not_run(self):
        self.assertEqual(broad("false && cd ~; rg foo"), [])
        self.assertEqual(broad("cd ~ | cat; rg foo"), [])
        self.assertEqual(broad("cd ~ && rg foo"), [("rg", "/home/u")])
        self.assertEqual(broad("cd /tmp/x || exit 1; rg foo ."), [])

    def test_substitution_runs_before_its_command(self):
        # Round 3: the inner find runs before cd changes anything.
        self.assertEqual(broad('cd "$(find . -name x)"', cwd=HOME), [("find", "/home/u")])
        # A cd in a pipeline is still a pipeline member with a substitution in it.
        self.assertEqual(broad('cd "$(printf /tmp)" | cat; rg foo', cwd=HOME), [("rg", "/home/u")])
        # A piped rg keeps reading stdin when its pattern is a substitution.
        self.assertEqual(broad('echo x | rg "$(cat pat)"', cwd=HOME), [])

    def test_control_flow_inside_a_piped_substitution(self):
        # Round 5: the pipe is inherited, but cd inside still runs.
        self.assertEqual(broad('printf x | echo "$(cd ~; find . -name x)"'), [("find", "/home/u")])
        self.assertEqual(broad('true && echo "$(cd ~; find . -name x)"'), [("find", "/home/u")])
        self.assertEqual(broad('echo x | (cd ~ && rg foo)'), [])

    def test_stdin_redirections(self):
        self.assertEqual(broad('printf x | echo "$(rg foo </dev/null)"', cwd=HOME), [("rg", "/home/u")])
        self.assertEqual(broad("rg foo </dev/null", cwd=HOME), [("rg", "/home/u")])
        self.assertEqual(broad("rg foo 0</dev/null", cwd=HOME), [("rg", "/home/u")])
        self.assertEqual(broad("rg foo <&-", cwd=HOME), [("rg", "/home/u")])
        for cmd in ("rg foo < notes.txt", 'rg foo <<<"$x"', "rg foo <<EOF\nbar\nEOF", "rg foo <&3"):
            self.assertEqual(broad(cmd, cwd=HOME), [], cmd)
        # <&0 and /dev/stdin keep stdin as it was; devices are not data.
        self.assertEqual(broad("rg foo <&0", cwd=HOME), [("rg", "/home/u")])
        self.assertEqual(broad("echo x | rg foo <&0", cwd=HOME), [])
        self.assertEqual(broad("rg foo </dev/stdin", cwd=HOME), [("rg", "/home/u")])
        self.assertEqual(broad("rg foo </dev/tty", cwd=HOME), [("rg", "/home/u")])
        self.assertEqual(broad("rg foo </dev/fd/3", cwd=HOME), [])
        self.assertEqual(broad("rg foo </dev/shm/query", cwd=HOME), [])
        self.assertEqual(broad("rg foo </dev/tcp/h/80", cwd=HOME), [])
        self.assertEqual(broad("rg foo </dev/pts/../shm/query", cwd=HOME), [])
        self.assertEqual(broad("rg foo <//dev//null", cwd=HOME), [("rg", "/home/u")])
        self.assertEqual(broad("rg foo </dev/./null", cwd=HOME), [("rg", "/home/u")])
        # `..` after a possible symlink: unknown, so data.
        self.assertEqual(broad("rg foo </dev/shm/alias/../../null", cwd=HOME), [])
        self.assertEqual(broad("rg foo </dev/pts/3", cwd=HOME), [("rg", "/home/u")])
        # Left to right: /dev/stdin is whatever the previous redirection made it.
        self.assertEqual(broad("rg foo <notes.txt </dev/stdin", cwd=HOME), [])
        self.assertEqual(broad("printf x | rg foo </dev/null </dev/stdin", cwd=HOME), [("rg", "/home/u")])
        # Other fds do not touch stdin.
        self.assertEqual(broad("echo x | rg foo 3</dev/null", cwd=HOME), [])

    def test_substitution_in_a_pipeline_reads_the_pipe(self):
        self.assertEqual(broad('printf foo | rg "$(rg foo)"', cwd=HOME), [])
        self.assertEqual(broad('ls | echo "$(rg foo)"', cwd=HOME), [])
        self.assertEqual(broad('echo "$(rg foo)"', cwd=HOME), [("rg", "/home/u")])

    def test_escaped_quote_inside_a_substitution(self):
        self.assertEqual(broad('echo $(printf "a\\")"; find / -name x)'), [("find", "/")])

    def test_cd_to_a_substitution(self):
        # Round 2: the common "cd to the repo root" shape.
        for cmd, cwd in (('cd "$(git rev-parse --show-toplevel)" && rg foo', CWD),
                         ('cd "$(git rev-parse --show-toplevel)/scripts" && rg foo', HOME),
                         ('cd $(git rev-parse --show-toplevel) && find . -name x', HOME),
                         ('find "$(git rev-parse --show-toplevel)/src" -name x', HOME)):
            self.assertEqual(broad(cmd, cwd=cwd), [], cmd)

    def test_paren_inside_quotes_in_a_substitution(self):
        self.assertEqual(broad('echo "$(echo ")")"; find ~ -name x'), [("find", "/home/u")])

    def test_substitution_keeps_the_outer_argument(self):
        self.assertEqual(broad('rg foo "$(printf /tmp/run)"', cwd=HOME), [])
        self.assertEqual(broad("rg foo $(git rev-parse --show-toplevel)", cwd=HOME), [])
        self.assertEqual(broad("find <(printf x) -name y", cwd=HOME), [])
        self.assertEqual(broad('cat "$(find ~ -name x)"'), [("find", "/home/u")])

    def test_cd_then_search(self):
        self.assertEqual(broad("cd ~ && rg foo"), [("rg", "/home/u")])
        self.assertEqual(broad("cd ~/Projects/repo && rg foo ."), [])

    def test_bare_cd(self):
        self.assertEqual(broad("cd; find . -name x"), [("find", "/home/u")])

    def test_dotdot_from_a_project(self):
        self.assertEqual(broad("find .. -name x"), [("find", "/home/u/Projects")])

    def test_home_variable(self):
        self.assertEqual(broad('find "$HOME" -name x'), [("find", "/home/u")])
        self.assertEqual(broad("find ${HOME}/Projects -name x"), [("find", "/home/u/Projects")])

    def test_trailing_slash_and_dot(self):
        self.assertEqual(broad("rg foo /home/u/"), [("rg", "/home/u")])
        self.assertEqual(broad("rg foo /home/u/Projects/."), [("rg", "/home/u/Projects")])

    def test_every_child_glob(self):
        self.assertEqual(broad("rg foo ~/Projects/*"), [("rg", "/home/u/Projects")])
        self.assertEqual(broad("find /tmp/* -name x"), [("find", "/tmp")])

    def test_command_substitution(self):
        self.assertEqual(broad("f=$(find / -name libfoo.so | head -1)"), [("find", "/")])
        self.assertEqual(broad("ls `find ~ -name x`"), [("find", "/home/u")])

    def test_nested_shell(self):
        self.assertEqual(broad("bash -lc 'find $HOME -name x'"), [("find", "/home/u")])
        self.assertEqual(broad("sh -c \"rg --files ~\""), [("rg", "/home/u")])
        self.assertEqual(broad("bash -euo pipefail -c 'find ~ -name x'"), [("find", "/home/u")])
        self.assertEqual(broad("bash --noprofile -o errexit -c 'find ~ -name x'"), [("find", "/home/u")])

    def test_substitution_in_double_quotes(self):
        self.assertEqual(broad('echo "$(find ~ -name x)"'), [("find", "/home/u")])
        self.assertEqual(broad('x="$(rg --files ~)"'), [("rg", "/home/u")])
        self.assertEqual(broad('echo "`find / -name x`"'), [("find", "/")])

    def test_process_substitution(self):
        self.assertEqual(broad("diff <(find ~ -name x) y"), [("find", "/home/u")])
        self.assertEqual(broad("while read l; do :; done < <(find / -name x)"), [("find", "/")])

    def test_ansi_c_quoting(self):
        self.assertEqual(broad("echo $'a\\'b'; find / -name x"), [("find", "/")])

    def test_keywords_and_groups(self):
        for cmd in ("if true; then find ~ -name x; fi", "for f in a; do find ~ -name x; done",
                    "{ find ~ -name x; }", "! find ~ -name x", "f() { find ~ -name x; }"):
            self.assertEqual(broad(cmd), [("find", "/home/u")], cmd)

    def test_ssh_remote_command(self):
        self.assertEqual(broad("ssh -p 22 remote.example 'rg --files ~/Projects'"), [("rg", "/home/u/Projects")])
        self.assertEqual(broad("ssh remote.example"), [])

    def test_wrappers(self):
        for cmd in ("timeout 60 find / -xdev -name x", "sudo find / -name x", "env -i find / -name x",
                    "nice -n 5 find / -name x", "command find / -name x"):
            self.assertEqual(broad(cmd), [("find", "/")], cmd)

    def test_absolute_binary(self):
        self.assertEqual(broad("/usr/bin/find ~ -name x"), [("find", "/home/u")])

    def test_rgrep_is_recursive(self):
        self.assertEqual(broad("rgrep foo ~"), [("grep", "/home/u")])


class Override(unittest.TestCase):
    def test_assignment_prefix(self):
        self.assertEqual(broad(f"{sg.OVERRIDE_ENV}=1 find ~ -name x"), [])

    def test_env_prefix(self):
        self.assertEqual(broad(f"env {sg.OVERRIDE_ENV}=1 rg --files /"), [])

    def test_export_covers_the_rest(self):
        self.assertEqual(broad(f"export {sg.OVERRIDE_ENV}=1; find ~ -name x; rg foo /"), [])

    def test_override_is_per_command(self):
        self.assertEqual(broad(f"{sg.OVERRIDE_ENV}=1 find ~ -name x; rg foo /"), [("rg", "/")])

    def test_other_values_do_not_override(self):
        self.assertEqual(broad(f"{sg.OVERRIDE_ENV}=0 find ~ -name x"), [("find", "/home/u")])


class ToolInputs(unittest.TestCase):
    def v(self, tool, inp, cwd=CWD):
        r = sg.classify_tool_input(tool, inp, cwd, HOME)
        return (r.tool, r.root) if r else None

    def test_grep(self):
        self.assertEqual(self.v("Grep", {"pattern": "x", "path": "/home/u"}), ("Grep", "/home/u"))
        self.assertEqual(self.v("Grep", {"pattern": "x", "path": "/home/u", "glob": "*.py"}), ("Grep", "/home/u"))
        self.assertIsNone(self.v("Grep", {"pattern": "x", "path": "/home/u/Projects/repo"}))
        self.assertEqual(self.v("Grep", {"pattern": "x"}, cwd="/home/u/Projects"), ("Grep", "/home/u/Projects"))

    def test_glob(self):
        self.assertEqual(self.v("Glob", {"pattern": "**/apksigner", "path": "/home/u"}), ("Glob", "/home/u"))
        self.assertEqual(self.v("Glob", {"pattern": "/home/u/Projects/**/*.md"}), ("Glob", "/home/u/Projects"))
        self.assertIsNone(self.v("Glob", {"pattern": "example/**/*.sh", "path": "/home/u/Projects"}))
        self.assertIsNone(self.v("Glob", {"pattern": "*.md", "path": "/home/u"}))
        self.assertEqual(self.v("Glob", {"pattern": "*/docs/**/x.md", "path": "/home/u/Projects"}),
                         ("Glob", "/home/u/Projects"))


class Hints(unittest.TestCase):
    def test_grep_hint_has_no_depth_option(self):
        h = sg.Verdict("grep", "/home/u", ["grep"]).hint()
        self.assertNotIn("max-depth", h)
        self.assertNotIn("maxdepth", h)
        self.assertIn("-maxdepth", sg.Verdict("find", "/", ["find"]).hint())
        self.assertIn("--max-depth", sg.Verdict("rg", "/", ["rg"]).hint())


class Lexer(unittest.TestCase):
    def test_operators(self):
        toks = sg.lex("a && b || c | d; e & f\ng")
        self.assertEqual([t for t in toks if not isinstance(t, sg.Word)],
                         ["&&", "||", "|", ";", "&", ";"])

    def test_redirections_dropped(self):
        toks = sg.lex("find ~ -name x 2>/dev/null >out &>all 2>&1 <in")
        self.assertEqual([t for t in toks if isinstance(t, sg.Word) and t.stdin is None],
                         ["find", "~", "-name", "x"])
        self.assertEqual([t.stdin for t in toks if isinstance(t, sg.Word) and t.stdin is not None], ["in"])

    def test_quotes_and_escapes(self):
        words = [t for t in sg.lex("a 'b c' \"d \\\"e\\\"\" f\\ g") if isinstance(t, sg.Word)]
        self.assertEqual(words, ["a", "b c", 'd "e"', "f g"])

    def test_unterminated_quote_does_not_raise(self):
        sg.lex("find ~ -name 'x")
        sg.classify_command('rg "foo ~', CWD, HOME)


def _children(pid):
    try:
        with open(f"/proc/{pid}/task/{pid}/children") as f:
            return [int(x) for x in f.read().split()]
    except OSError:
        return []


class ParentShell(unittest.TestCase):
    """parent_is_agent_command, against real process trees under a stand-in
    harness. /proc/<pid>/comm of a script is its file name, so a script named
    `codex` looks like Codex."""

    def tree(self, script):
        """Run `codex` -> bash -c SCRIPT; return the pid of the deepest
        descendant (the one that would be running the search)."""
        d = tempfile.mkdtemp()
        fake = os.path.join(d, "codex")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\n/bin/bash -c "$1"\nexit $?\n')
        os.chmod(fake, 0o755)
        p = subprocess.Popen([fake, script], stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        self.addCleanup(lambda: subprocess.run(["pkill", "-P", str(p.pid)]))
        deadline = time.time() + 3
        pid = p.pid
        while time.time() < deadline:
            time.sleep(0.05)
            pid, kids = p.pid, _children(p.pid)
            while kids:
                pid = kids[-1]
                kids = _children(pid)
            if posixpath_basename_of(pid) == "sleep":
                break
        return pid

    def parent_of(self, pid):
        return sg._proc(pid)[2]

    def test_command_shell_under_harness(self):
        sleep = self.tree("sleep 5; :")
        self.assertTrue(sg.parent_is_agent_command(self.parent_of(sleep)))

    def test_harness_itself(self):
        # bash execs a lone command in place: sleep's parent is the harness.
        sleep = self.tree("sleep 5")
        self.assertTrue(sg.parent_is_agent_command(self.parent_of(sleep)))

    def test_nested_command_shells(self):
        sleep = self.tree('sh -c "sleep 5; :"; :')
        self.assertTrue(sg.parent_is_agent_command(self.parent_of(sleep)))

    def test_program_in_between(self):
        # python running shell=True (likewise npm, make, xargs, git aliases).
        sleep = self.tree('python3 -c "import subprocess; subprocess.run(\'sleep 5; :\', shell=True)"; :')
        self.assertFalse(sg.parent_is_agent_command(self.parent_of(sleep)))

    def test_script_in_between(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write("sleep 5\n:\n")
        self.addCleanup(os.unlink, f.name)
        sleep = self.tree(f"bash {f.name}; :")
        self.assertFalse(sg.parent_is_agent_command(self.parent_of(sleep)))

    def test_no_harness_above(self):
        p = subprocess.Popen(["bash", "-c", "sleep 5; :"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        time.sleep(0.2)
        self.assertFalse(sg.parent_is_agent_command(p.pid))

    def test_generic_runtime(self):
        gem = ["node", "/usr/lib/node_modules/@google/gemini-cli/dist/index.js"]
        self.assertTrue(sg._is_harness("node", gem))
        # Node 24 reports comm "MainThread": the exe says it is node.
        self.assertTrue(sg._is_harness("MainThread", gem, "/nix/store/x-nodejs-24/bin/node"))
        self.assertFalse(sg._is_harness("node", ["node", "/usr/bin/npm", "run", "build"]))
        self.assertFalse(sg._is_harness("node", ["node", "goals-mcp"]))
        # A script that merely lives in a directory with a harness-like name.
        for path in ("/tmp/claude-1000/x/build.js", "/home/u/Projects/codex-tools/run.js",
                     "/home/u/Projects/claude-desktop/main.js"):
            self.assertFalse(sg._is_harness("MainThread", ["node", path], "/usr/bin/node"), path)
        # Inline source that merely mentions a harness package is not the harness.
        src = "require('/x/node_modules/@google/gemini-cli/dist/a.js'); execSync('find /')"
        for flag in ("-e", "-p", "--eval"):
            self.assertFalse(sg._is_harness("node", ["node", flag, src], "/usr/bin/node"), flag)
        self.assertTrue(sg._is_harness("node", ["node", "--no-warnings", gem[1]], "/usr/bin/node"))
        self.assertTrue(sg._is_harness("node", ["node", "--no-warnings=DEP0040", gem[1]], "/usr/bin/node"))
        # An option that may take a value leaves the entry script uncertain.
        for argv in (["node", "-r", "/x/node_modules/@google/gemini-cli/register.js", "/tmp/build.js"],
                     ["node", "--require", gem[1], "/tmp/build.js"],
                     ["node", "-eCODE", gem[1]]):
            self.assertFalse(sg._is_harness("node", argv, "/usr/bin/node"), argv)

    def test_missing_pid(self):
        self.assertFalse(sg.parent_is_agent_command(2 ** 22 + 12345))


def posixpath_basename_of(pid):
    info = sg._proc(pid)
    return info[0] if info else None


class Wrap(unittest.TestCase):
    def test_unloggable_refusal_still_refuses(self):
        old_parent, old_state = sg.parent_is_agent_command, os.environ.get("XDG_STATE_HOME")
        sg.parent_is_agent_command = lambda pid: True
        os.environ["XDG_STATE_HOME"] = "/proc/nonexistent"
        try:
            args = type("A", (), {"ppid": 1, "argv": ["find", "/", "-name", "x"]})
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(sg.cmd_wrap(args), sg.REFUSE_EXIT)
                out = err.getvalue()
                self.assertIn("search-guard: refused", out)
                self.assertIn("could not write the log", out)
                with tempfile.TemporaryDirectory() as d:
                    os.environ["XDG_STATE_HOME"] = d
                    err.truncate(0)
                    err.seek(0)
                    self.assertEqual(sg.cmd_wrap(args), sg.REFUSE_EXIT)
                self.assertIn("search-guard: refused", err.getvalue())
                self.assertNotIn("could not write the log", err.getvalue())
        finally:
            sg.parent_is_agent_command = old_parent
            if old_state is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old_state

    def test_refuse_exit_is_not_pythons_own(self):
        self.assertNotIn(sg.REFUSE_EXIT, (0, 1, 2))

    def test_unprintable_stderr_still_refuses(self):
        old_parent, old_state = sg.parent_is_agent_command, os.environ.get("XDG_STATE_HOME")
        sg.parent_is_agent_command = lambda pid: True
        os.environ["XDG_STATE_HOME"] = "/proc/nonexistent"
        try:
            args = type("A", (), {"ppid": 1, "argv": ["find", "/", "-name", "x"]})
            with contextlib.redirect_stderr(_ExplodingStream()):
                self.assertEqual(sg.cmd_wrap(args), sg.REFUSE_EXIT)
        finally:
            sg.parent_is_agent_command = old_parent
            if old_state is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old_state


class Hook(unittest.TestCase):
    def test_unloggable_deny_still_denies(self):
        old_stdin, old_state = sys.stdin, os.environ.get("XDG_STATE_HOME")
        event = {"tool_name": "Bash", "tool_input": {"command": 'find / -name x'},
                 "cwd": "/home/u/nonexistent-test-cwd", "session_id": "sess-test"}
        os.environ["XDG_STATE_HOME"] = "/proc/nonexistent"
        try:
            sys.stdin = io.StringIO(json.dumps(event))
            with contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(sg.cmd_hook(type("A", (), {})()), 0)
            decision = json.loads(out.getvalue())
            self.assertEqual(
                decision["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("could not write the log", err.getvalue())
        finally:
            sys.stdin = old_stdin
            if old_state is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old_state

    def test_unprintable_stderr_still_denies(self):
        old_stdin, old_state = sys.stdin, os.environ.get("XDG_STATE_HOME")
        event = {"tool_name": "Bash", "tool_input": {"command": 'find / -name x'},
                 "cwd": "/home/u/nonexistent-test-cwd", "session_id": "sess-test"}
        os.environ["XDG_STATE_HOME"] = "/proc/nonexistent"
        try:
            sys.stdin = io.StringIO(json.dumps(event))
            with contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(_ExplodingStream()):
                self.assertEqual(sg.cmd_hook(type("A", (), {})()), 0)
            decision = json.loads(out.getvalue())
            self.assertEqual(
                decision["hookSpecificOutput"]["permissionDecision"], "deny")
        finally:
            sys.stdin = old_stdin
            if old_state is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old_state


class Log(unittest.TestCase):
    def test_log_line_and_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = d
            try:
                v = sg.Verdict("find", "/home/u", ["find", "/home/u"])
                tmux_env = {"TMUX": "/tmp/tmux-1234/default,1234,0", "TMUX_PANE": "%12"}
                with mock.patch.dict(os.environ, tmux_env):
                    sg.log_event(v, "/home/u", "wrapper")
                path = os.path.join(d, "search-guard", "log")
                with open(path) as f:
                    rec = json.loads(f.read())
                self.assertEqual((rec["tool"], rec["root"], rec["decision"], rec["source"]),
                                 ("find", "/home/u", "refused", "wrapper"))
                for key in ("ts", "host", "cwd", "argv", "session", "harness", "pane", "tmux_socket"):
                    self.assertIn(key, rec)
                self.assertEqual(rec["tmux_socket"], "/tmp/tmux-1234/default")
                self.assertEqual(rec["pane"], "%12")
                with open(path, "a") as f:
                    f.write("x" * (sg.LOG_MAX_BYTES + 1))
                with mock.patch.dict(os.environ, tmux_env):
                    sg.log_event(v, "/home/u", "wrapper")
                self.assertTrue(os.path.exists(path + ".1"))
                with open(path) as f:
                    self.assertEqual(len(f.read().splitlines()), 1)
            finally:
                if old is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old

    def test_tmux_socket_is_null_without_tmux_environment(self):
        with tempfile.TemporaryDirectory() as d:
            v = sg.Verdict("find", "/home/u", ["find", "/home/u"])
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": d}, clear=False):
                os.environ.pop("TMUX", None)
                os.environ.pop("TMUX_PANE", None)
                sg.log_event(v, "/home/u", "wrapper")
                os.environ["TMUX"] = ""
                sg.log_event(v, "/home/u", "wrapper")
            path = os.path.join(d, "search-guard", "log")
            with open(path, encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream]
            self.assertEqual([record["tmux_socket"] for record in records], [None, None])
            self.assertEqual([record["pane"] for record in records], [None, None])

    def test_unwritable_log_is_silent(self):
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = "/proc/nonexistent"
        try:
            self.assertFalse(sg.log_event(sg.Verdict("rg", "/", ["rg"]), "/", "wrapper"))
        finally:
            if old is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old


class Measure(unittest.TestCase):
    def test_counts_claude_and_codex(self):
        with tempfile.TemporaryDirectory() as d:
            cl = os.path.join(d, "claude", "-proj")
            cx = os.path.join(d, "codex", "2026", "10", "16")
            os.makedirs(cl)
            os.makedirs(cx)
            ts = "2026-10-16T12:00:00Z"

            def claude(i, cmd):
                return json.dumps({"timestamp": ts, "sessionId": "s1", "cwd": "/home/u",
                                   "message": {"content": [{"type": "tool_use", "id": f"t{i}",
                                                            "name": "Bash", "input": {"command": cmd}}]}})
            with open(os.path.join(cl, "s1.jsonl"), "w") as f:
                f.write(claude(1, "find ~ -name x") + "\n")
                f.write(claude(1, "find ~ -name x") + "\n")  # same tool_use id: counted once
                f.write(claude(2, "rg foo src") + "\n")
                f.write(claude(3, "/usr/bin/find / -name x") + "\n")
            js = 'text(await tools.exec_command({cmd:"rg --files /home/u/Projects | rg x",workdir:"/home/u"}));'
            with open(os.path.join(cx, "r.jsonl"), "w") as f:
                f.write(json.dumps({"timestamp": ts, "type": "session_meta", "payload": {"id": "c1", "cwd": "/home/u"}}) + "\n")
                f.write(json.dumps({"timestamp": ts, "type": "response_item", "payload": {
                    "type": "custom_tool_call", "call_id": "k1", "name": "exec", "input": js}}) + "\n")
            out = subprocess.run(
                [sys.executable, os.path.join(os.path.dirname(HERE), "search_guard.py"), "measure",
                 "--since", "2026-10-15", "--until", "2026-10-17", "--json",
                 "--claude-root", os.path.join(d, "claude"), "--codex-root", os.path.join(d, "codex")],
                capture_output=True, text=True, env={**os.environ, "HOME": "/home/u"}, check=True)
            stats = json.loads(out.stdout)["stats"]
            self.assertEqual(stats["claude"]["commands"], 3)
            self.assertEqual(stats["claude"]["broad"], 2)
            self.assertEqual(stats["codex"]["commands"], 1)
            self.assertEqual(stats["codex"]["broad"], 1)


if __name__ == "__main__":
    unittest.main()
