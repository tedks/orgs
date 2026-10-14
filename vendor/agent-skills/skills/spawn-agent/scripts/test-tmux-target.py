#!/usr/bin/env python3
"""Fail-closed target tests on a private tmux server, never a live agent pane."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parent


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.label = 'target-test-' + uuid.uuid4().hex
        self.tmux = [shutil.which('tmux'), '-L', self.label]
        self.env = dict(os.environ, SPAWN_TMUX_LABEL=self.label, XDG_STATE_HOME=str(self.root / 'state'))
        self.env.pop('SPAWN_TMUX_SOCKET', None)
        self.sentinel = self.command('new-session', '-d', '-P', '-F', '#{pane_id}', '-s', 'probe', '-n', 'sentinel', 'cat').strip()
        self.command('send-keys', '-t', self.sentinel, '-l', 'UNRELATED-PANE')

    def tearDown(self):
        subprocess.run(self.tmux + ['kill-server'], capture_output=True)
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.check_output(self.tmux + list(args), text=True)

    def resolve(self, target):
        return subprocess.run([str(SCRIPTS / 'tmux-resolve.sh'), target], env=self.env, capture_output=True, text=True)

    def request(self, operation, target):
        args = [str(SCRIPTS / 'tmux-message.sh'), operation, target]
        if operation == 'send':
            args += ['--max-wait', '1', 'MUST-NOT-ARRIVE']
        return subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=15)

    def assert_missing(self, target):
        self.assertNotEqual(self.resolve(target).returncode, 0, target)
        for operation in ('read', 'send'):
            result = self.request(operation, target)
            self.assertNotEqual(result.returncode, 0, (operation, target, result))
            self.assertNotIn('UNRELATED-PANE', result.stdout)
        content = self.command('capture-pane', '-p', '-t', self.sentinel)
        self.assertNotIn('MUST-NOT-ARRIVE', content)

    def test_absent_and_prefix_targets(self):
        self.command('new-window', '-d', '-t', 'probe', '-n', 'worker-long', 'cat')
        for target in ('probe:missing', 'probe:worker', 'pro:sentinel', '%99999', '@99999', 'probe:', ':sentinel', 'sentinel'):
            self.assert_missing(target)

    def test_retired_window_and_pane(self):
        pane = self.command('new-window', '-d', '-P', '-F', '#{pane_id}', '-t', 'probe', '-n', 'retired', 'cat').strip()
        self.command('kill-pane', '-t', pane)
        self.assert_missing('probe:retired')
        self.assert_missing(pane)

    def test_exact_name_and_inactive_pane(self):
        pane = self.command('split-window', '-d', '-P', '-F', '#{pane_id}', '-t', self.sentinel, 'cat').strip()
        result = self.resolve(pane)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().endswith(':' + pane))
        self.assertTrue(self.resolve('probe:sentinel').stdout.strip().endswith(':' + self.sentinel))
        self.assertIn('UNRELATED-PANE', self.request('read', 'probe:sentinel').stdout)

    def test_dotted_name_and_duplicate_names(self):
        pane = self.command('new-window', '-d', '-P', '-F', '#{pane_id}', '-t', 'probe', '-n', 'with.dot', 'cat').strip()
        self.assertTrue(self.resolve('probe:with.dot').stdout.strip().endswith(':' + pane))
        self.command('new-window', '-d', '-t', 'probe', '-n', 'with.dot', 'cat')
        self.assert_missing('probe:with.dot')

    def test_deleted_after_resolution_never_uses_active_pane(self):
        # The wrapper deletes only this test's selected pane after list-panes
        # returns it. Later capture/send operations must fail on its stable ID.
        wrapper = self.root / 'tmux'
        wrapper.write_text('''#!/usr/bin/env python3
import os, subprocess, sys
args = sys.argv[1:]
p = subprocess.run([os.environ['TARGET_REAL_TMUX']] + args, capture_output=True)
if 'list-panes' in args and p.returncode == 0:
    subprocess.run([os.environ['TARGET_REAL_TMUX'], '-L', os.environ['SPAWN_TMUX_LABEL'], 'kill-pane', '-t', os.environ['TARGET_DELETE_PANE']], capture_output=True)
sys.stdout.buffer.write(p.stdout)
sys.stderr.buffer.write(p.stderr)
sys.exit(p.returncode)
''')
        wrapper.chmod(0o700)
        self.env['PATH'] = str(self.root) + os.pathsep + self.env['PATH']
        self.env['TARGET_REAL_TMUX'] = self.tmux[0]
        for operation in ('read', 'send'):
            pane = self.command('new-window', '-d', '-P', '-F', '#{pane_id}', '-t', 'probe', '-n', 'retired', 'cat').strip()
            self.env['TARGET_DELETE_PANE'] = pane
            result = self.request(operation, 'probe:retired')
            self.assertNotEqual(result.returncode, 0, result)
            self.assertNotIn('UNRELATED-PANE', result.stdout)
        self.assertNotIn('MUST-NOT-ARRIVE', self.command('capture-pane', '-p', '-t', self.sentinel))


if __name__ == '__main__':
    unittest.main()
