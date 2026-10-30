#!/usr/bin/env python3
"""Self identity tests use synthetic /proc plus exact tmux inventories."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
MODULE = Path(os.environ.get('HARNESS_IDENTITY_TEST_MODULE',
    Path(__file__).resolve().parents[1] / 'harness_identity.py'))
spec = importlib.util.spec_from_file_location('harness_identity', MODULE)
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proc = Path(self.tmp.name)
        boot = self.proc / 'sys/kernel/random'
        boot.mkdir(parents=True)
        (boot / 'boot_id').write_text('test-boot')
        self.make(30, 20, 'python3')
        self.make(20, 10, 'claude', 'TMUX=/tmp/socket,123,0\0TMUX_PANE=%9\0')
        self.make(10, 1, 'bash')

    def make(self, pid, parent, comm, env='', start='777'):
        d = self.proc / str(pid)
        d.mkdir(exist_ok=True)
        (d / 'stat').write_text(f'{pid} (odd ) process) S {parent} ' + '0 ' * 17 + start)
        (d / 'comm').write_text(comm)
        (d / 'environ').write_text(env)
        if not (d / 'cwd').is_symlink():
            (d / 'cwd').symlink_to('/work/tree')

    def identity(self):
        return h.discover(30, self.proc)

    def inventory(self, output):
        return patch.object(h.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output))

    def test_nearest_and_socket(self):
        got = self.identity()
        self.assertEqual((got.pid, got.harness, got.socket, got.pane, got.cwd, got.starttime),
                         (20, 'claude', '/tmp/socket', '%9', '/work/tree', '777'))
        with self.inventory('%9\t10\t0\n') as run:
            h.verify_pane(got, self.proc)
            self.assertEqual(run.call_args.args[0][1:3], ['-S', '/tmp/socket'])

    def test_codex_version_name(self):
        self.make(20, 10, 'codex-0.157', 'TMUX=/tmp/socket,1,0\0TMUX_PANE=%9\0')
        self.assertEqual(self.identity().harness, 'codex')

    def test_nearest_without_tmux_does_not_climb(self):
        self.make(30, 20, 'codex')
        with self.assertRaisesRegex(h.IdentityError, 'outside tmux'):
            self.identity()

    def test_missing_and_malformed_ancestry(self):
        with self.assertRaises(h.IdentityError):
            h.discover(99, self.proc)
        (self.proc / '30/stat').write_text('bad')
        with self.assertRaises(h.IdentityError):
            self.identity()

    def test_cycles_and_lookalike_fail_closed(self):
        self.make(20, 30, 'claude-other')
        with self.assertRaisesRegex(h.IdentityError, 'no supported'):
            self.identity()

    def test_tmux_values_rejected(self):
        for env in ('TMUX=/tmp/x,1,0\0TMUX_PANE=active\0', 'TMUX=x,1,0\0TMUX_PANE=%9\0'):
            with self.subTest(env=env):
                self.make(20, 10, 'claude', env)
                with self.assertRaises(h.IdentityError):
                    self.identity()

    def test_reuse_and_boot_change(self):
        got = self.identity()
        self.assertTrue(h.same_process(got, self.proc))
        self.make(20, 10, 'claude', start='778')
        self.assertFalse(h.same_process(got, self.proc))
        self.make(20, 10, 'claude')
        (self.proc / 'sys/kernel/random/boot_id').write_text('other-boot')
        self.assertFalse(h.same_process(got, self.proc))

    def test_unknown_is_not_exited(self):
        got = self.identity()
        (self.proc / '20/stat').unlink()
        with self.assertRaises(h.IdentityError):
            h.same_process(got, self.proc)
        with patch.object(h, 'process', side_effect=PermissionError):
            with self.assertRaises(h.IdentityError):
                h.same_process(got, self.proc)

    def test_exited_process(self):
        got = self.identity()
        gone = h.Identity(got.harness, 99, got.starttime, got.boot_id, got.socket, got.pane, got.cwd)
        self.assertFalse(h.same_process(gone, self.proc))

    def test_inventory_identity_fail_closed(self):
        got = self.identity()
        for output in ('%8\t10\t0\n', '%9\t10\t1\n', '%9\t99\t0\n', '%9\t10\t0\n%9\t11\t0\n'):
            with self.subTest(output=output), self.inventory(output):
                with self.assertRaises(h.IdentityError):
                    h.verify_pane(got, self.proc)
        with self.inventory('%9\t10\t0\n'):
            h.verify_pane(got, self.proc)

    def test_linked_pane_identical_rows(self):
        with self.inventory('%9\t10\t0\n%9\t10\t0\n'):
            try:
                h.verify_pane(self.identity(), self.proc)
            except h.IdentityError as exc:
                self.fail(f'identical linked-pane rows must be accepted: {exc}')

    def test_nested_harness_rejected(self):
        for comm in ('codex', 'claude-2.1'):
            self.make(10, 1, comm)
            with self.inventory('%9\t10\t0\n'), self.assertRaisesRegex(h.IdentityError, 'nested harness'):
                h.verify_pane(self.identity(), self.proc)



# One independent, syntactically valid production mutant for each pinned behavior.
MUTANTS = {
    'test_linked_pane_identical_rows': ("matches = list({tuple(row.split('\\t')) for row in result.stdout.splitlines()\n                        if row.split('\\t')[0] == identity.pane})", "matches = [tuple(row.split('\\t')) for row in result.stdout.splitlines() if row.split('\\t')[0] == identity.pane]"),
    'test_nested_harness_rejected': ("if pid != identity.pid and _harness", "if False and _harness"),
    'test_nearest_and_socket': ("cwd = os.readlink(base / 'cwd')", "cwd = '/wrong'"),
    'test_codex_version_name': ("return Identity(harness, pid,", "return Identity('claude', pid,"),
    'test_nearest_without_tmux_does_not_climb': ("if harness:", "if harness and (base / 'environ').read_bytes():"),
    'test_missing_and_malformed_ancestry': ("raise IdentityError('malformed process stat')", "return 20, '777'"),
    'test_cycles_and_lookalike_fail_closed': ("comm == name or re.fullmatch(name + r'-[0-9].*', comm)", "comm.startswith(name)"),
    'test_tmux_values_rejected': ("not re.fullmatch(r'%[0-9]+', pane)", "not pane"),
    'test_reuse_and_boot_change': ("boot == identity.boot_id and process(identity.pid, proc)[1] == identity.starttime", "process(identity.pid, proc)[1] == identity.starttime"),
    'test_unknown_is_not_exited': ("raise IdentityError('cannot verify process identity')", "return False"),
    'test_exited_process': ("if not (proc / str(identity.pid)).exists():\n            return False", "if not (proc / str(identity.pid)).exists():\n            return True"),
    'test_inventory_identity_fail_closed': (" or matches[0][2] != '0'", ""),
}


def mutation_check():
    subprocess.run([sys.executable, __file__], check=True, timeout=90)
    if set(unittest.defaultTestLoader.getTestCaseNames(IdentityTests)) != set(MUTANTS):
        raise RuntimeError('Every behavior test needs a mutation check')
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        for test, (old, new) in MUTANTS.items():
            source = MODULE.read_text()
            # Two error handlers share a message: mutate only the first.
            if old not in source:
                raise RuntimeError(f'Mutation anchor drift: {test}')
            target = Path(directory) / f'{test}.py'
            changed = source.replace(old, new, 1)
            compile(changed, str(target), 'exec')
            target.write_text(changed)
            env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                   'HARNESS_IDENTITY_TEST_MODULE': str(target)}
            result = subprocess.run([sys.executable, __file__, f'IdentityTests.{test}'],
                                    env=env, text=True, capture_output=True, timeout=15)
            killed = result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr
            print(f"{'KILLED' if killed else 'SURVIVED'} IdentityTests.{test}")
            if not killed:
                failures.append(test)
                print(result.stdout + result.stderr)
    return bool(failures)


if __name__ == '__main__':
    if sys.argv[1:] == ['--mutation-check']:
        raise SystemExit(mutation_check())
    unittest.main()
