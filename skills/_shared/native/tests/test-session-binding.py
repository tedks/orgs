#!/usr/bin/env python3
"""Pinned native binding fixtures; no live harness is contacted."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.environ.get('SESSION_BINDING_TEST_MODULE'):
    sys.path.insert(0, str(Path(os.environ['SESSION_BINDING_TEST_MODULE']).parent))
from session_binding import ProcessPin, observe_native_session

SID = '11111111-1111-1111-1111-111111111111'
OTHER = '22222222-2222-2222-2222-222222222222'


class BindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.proc = self.root / 'proc'
        process = self.proc / '123'
        process.mkdir(parents=True)
        (self.proc / 'sys/kernel/random').mkdir(parents=True)
        (self.proc / 'sys/kernel/random/boot_id').write_text('boot\n')
        self.stat('777')
        (process / 'environ').write_bytes(f'HOME={self.root}\0'.encode())
        self.pointer = self.root / '.claude/session-state/current.123'
        self.pointer.parent.mkdir(parents=True)
        self.pointer.write_text(f'{SID} 777 boot\n')
        self.pin = ProcessPin(123, '777', 'boot')

    def stat(self, start):
        (self.proc / '123/stat').write_text('123 (codex worker) S 1 ' + '0 '*17 + start + '\n')

    def observe(self, harness='claude'):
        return observe_native_session(harness, self.pin, proc=self.proc)

    def test_claude_pinned_pair_and_pointer(self):
        proof = self.observe()
        self.assertEqual((proof['state'], proof['session_id']), ('observed', SID))
        self.assertEqual(proof['pointer_paths'], [str(self.pointer)])
        for content in (f'{SID} 999 boot', f'{SID} 777 oldboot', f'{OTHER} 777 boot extra',
                        'not-a-uuid 777 boot'):
            self.pointer.write_text(content)
            self.assertEqual(self.observe()['state'], 'unavailable')

    def test_missing_conflicting_and_switched_pointer(self):
        second = self.root / 'custom/session-state/current.123'
        second.parent.mkdir(parents=True)
        (self.proc / '123/environ').write_bytes(
            f'HOME={self.root}\0CLAUDE_CONFIG_DIR={self.root / "custom"}\0'.encode())
        second.write_text(f'{SID} 777 boot')
        self.assertEqual(self.observe()['state'], 'observed')
        second.write_text(f'{OTHER} 777 boot')
        self.assertEqual(self.observe().get('reason'), 'conflicting_claude_pointers')
        second.unlink()
        self.pointer.unlink()
        self.assertEqual(self.observe().get('reason'), 'claude_pointer_unavailable')

    def test_configured_pointer_preserves_default_snapshot_identity(self):
        uppercase = 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'
        mixed = uppercase.lower()
        custom = self.root / 'custom/session-state/current.123'
        custom.parent.mkdir(parents=True)
        (self.proc / '123/environ').write_bytes(
            f'HOME={self.root}\0CLAUDE_CONFIG_DIR={self.root / "custom"}\0'.encode())
        custom.write_text(f'{mixed} 777 boot')
        self.pointer.write_text(f'{uppercase} 777 boot')
        proof = self.observe()
        self.assertEqual(proof['session_id'], uppercase)
        self.assertEqual(proof['status_dir'], str(self.pointer.parent))
        self.assertEqual(proof['pointer_paths'][0], str(custom))

    def test_uppercase_pointer_preserved(self):
        uppercase = 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'
        self.pointer.write_text(f'{uppercase} 777 boot')
        self.assertEqual(self.observe()['session_id'], uppercase)

    def test_reused_process_and_missing_environment(self):
        self.stat('888')
        with patch('session_binding._claude_directories') as directories:
            self.assertEqual(self.observe().get('reason'), 'pinned_process_changed')
        directories.assert_not_called()
        self.stat('777')
        (self.proc / '123/environ').write_bytes(b'')
        self.assertEqual(self.observe()['reason'], 'native_binding_unreadable')

    def test_process_changes_during_observation(self):
        with patch('session_binding.same_process', side_effect=[True, False]):
            self.assertEqual(self.observe().get('reason'), 'pinned_process_changed')

    def test_codex_reader_observed_or_unknown(self):
        observation = {'state': 'observed', 'session_id': SID, 'rollout_path': '/private/rollout.jsonl'}
        with patch('codex_status.read_codex_status', return_value=observation) as reader:
            proof = self.observe('codex')
        self.assertEqual(proof['session_id'], SID)
        self.assertEqual(proof['transcript_path'], '/private/rollout.jsonl')
        reader.assert_called_once_with(123, proc=self.proc)
        for state in ({'state': 'unsupported', 'reason': 'missing'},
                      {'state': 'observed', 'session_id': 'not-a-uuid'}):
            with patch('codex_status.read_codex_status', return_value=state):
                self.assertEqual(self.observe('codex')['state'], 'unavailable')

    def test_codex_requires_pinned_home(self):
        (self.proc / '123/environ').write_bytes(b'')
        with patch('codex_status.read_codex_status') as reader:
            self.assertEqual(self.observe('codex')['reason'], 'pinned_codex_home_unavailable')
        reader.assert_not_called()

    def test_bounded_pointer(self):
        self.pointer.write_bytes(b'x' * 257)
        self.assertEqual(self.observe().get('reason'), 'invalid_claude_pointer_size')

    def test_bounded_environment(self):
        (self.proc / '123/environ').write_bytes(f'HOME={self.root}\0'.encode() + b'x' * (1024 * 1024))
        self.assertEqual(self.observe().get('reason'), 'native_binding_unreadable')


MUTANTS = {
    'test_claude_pinned_pair_and_pointer': ('fields[1:] != [pin.starttime, pin.boot_id]', 'False'),
    'test_missing_conflicting_and_switched_pointer': ("elif len({sid.lower() for sid, _ in found}) != 1:", 'elif False:'),
    'test_configured_pointer_preserves_default_snapshot_identity': ("'status_dir': str(directories[-1])", "'status_dir': str(directories[0])"),
    'test_uppercase_pointer_preserved': ("found.append((fields[0], str(pointer)))", "found.append((fields[0].lower(), str(pointer)))"),
    'test_reused_process_and_missing_environment': ("if not same_process(pin, proc):\n            return unavailable('pinned_process_changed')", "if False:\n            return unavailable('pinned_process_changed')"),
    'test_process_changes_during_observation': ("if not same_process(pin, proc):\n            return unavailable('pinned_process_changed')\n        return result", "if False:\n            return unavailable('pinned_process_changed')\n        return result"),
    'test_codex_reader_observed_or_unknown': ('or not _UUID.fullmatch(sid)):', 'or False):'),
    'test_codex_requires_pinned_home': ("if codex_home is None and not _has_pinned_codex_home(pin, proc):", 'if False:'),
    'test_bounded_pointer': ("if len(raw) > MAX_POINTER_BYTES:\n                    return unavailable('invalid_claude_pointer_size')", "if False:\n                    return unavailable('invalid_claude_pointer_size')"),
    'test_bounded_environment': ("if len(raw) > MAX_ENV_BYTES:\n        raise ValueError('pinned_environment_too_large')", "if False:\n        raise ValueError('pinned_environment_too_large')"),
}


def mutation_check():
    source_path = Path(__file__).resolve().parents[1] / 'session_binding.py'
    source = source_path.read_text()
    if set(unittest.defaultTestLoader.getTestCaseNames(BindingTests)) != set(MUTANTS):
        raise RuntimeError('Every binding test needs a mutant')
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        for test, (before, after) in MUTANTS.items():
            if before not in source:
                raise RuntimeError('Mutation anchor drift: ' + test)
            changed = source.replace(before, after, 1)
            target = directory / 'session_binding.py'
            target.write_text(changed)
            result = subprocess.run([sys.executable, __file__, 'BindingTests.' + test],
                                    env={**os.environ, 'SESSION_BINDING_TEST_MODULE': str(target)},
                                    text=True, capture_output=True, timeout=30)
            killed = result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr
            print(('KILLED ' if killed else 'SURVIVED ') + test)
            if not killed:
                failures.append(test)
                print(result.stdout + result.stderr)
    return bool(failures)


if __name__ == '__main__':
    if sys.argv[1:] == ['--mutation-check']:
        raise SystemExit(mutation_check())
    unittest.main()
