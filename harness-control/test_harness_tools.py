#!/usr/bin/env python3
"""MCP wiring tests: verified self identity, allowlisted results and unavailable data."""
import asyncio
import importlib.util
import os
import subprocess
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
MODULE = Path(os.environ.get('HARNESS_TOOLS_TEST_MODULE', Path(__file__).with_name('server.py')))
spec = importlib.util.spec_from_file_location('server', MODULE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from harness_identity import Identity, IdentityError

SID = '11111111-1111-1111-1111-111111111111'

class ToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.identity = Identity('claude', 123, '777', 'boot', '/tmp/socket', '%9', '/work')
        self.old = server._self_identity
        server._self_identity = None
        self.addCleanup(setattr, server, '_self_identity', self.old)
        self.posture = {'provider': 'openai', 'scores': {'openai': 1.2, 'anthropic': 0.8},
                        'used_percent': {'openai': 60, 'anthropic': 40},
                        'resets_at': {'openai': '2026-10-30T00:00:00Z', 'anthropic': '2026-10-31T00:00:00Z'},
                        'stale': {'openai': False, 'anthropic': False},
                        'staleness': {'stale': False, 'newest_observed': '2026-10-29T00:00:00Z', 'age_seconds': 0},
                        'gated': {'openai': False, 'anthropic': False}, 'reason': 'test posture'}
        self.posture_reader = patch.object(server, '_read_usage_posture', return_value=self.posture)
        self.posture_reader.start()
        self.addCleanup(self.posture_reader.stop)

    async def test_pinned_identity_verified_every_time(self):
        with patch('harness_identity.discover', return_value=self.identity) as discover, patch('harness_identity.verify_pane') as verify:
            self.assertEqual(server._own_identity(), self.identity)
            self.assertEqual(server._own_identity(), self.identity)
            discover.assert_called_once()
            self.assertEqual(verify.call_count, 2)

    async def test_no_tmux_returns_typed_unavailable(self):
        with patch('harness_identity.discover', side_effect=IdentityError('outside tmux')):
            for tool in (server.get_status, server.get_usage):
                got = await tool()
                expected = {'state':'unavailable','reason':'outside tmux'}
                if tool is server.get_usage:
                    expected['posture'] = self.posture
                self.assertEqual(got, expected)

    async def test_posture_is_attached_to_claude_usage(self):
        snapshot={'schema_version':1,'session_id':SID,'observed_at':100}
        (self.path/f'{SID}.status.json').write_text(json.dumps(snapshot))
        claude_binding = {'state': 'observed', 'session_id': SID,
                          'pointer_paths': [str(self.path / 'current.123')], 'status_dir': str(self.path)}
        with patch.object(server, '_own_identity', return_value=self.identity), \
                patch('session_binding.observe_native_session', return_value=claude_binding):
            result = await server.get_usage()
        self.assertEqual(result.get('posture'), self.posture)

    async def test_posture_is_attached_to_codex_usage(self):
        identity = Identity('codex', 123, '777', 'boot', '/tmp/socket', '%9', '/work')
        data = {'state': 'observed', 'source': 'codex_rollout', 'session_id': SID,
                'quota_buckets': {'test': {}}}
        with patch.object(server, '_own_identity', return_value=identity), \
                patch('session_binding.observe_native_session', return_value={
                    'state': 'observed', 'session_id': SID, 'observation': data}), \
                patch.object(server.codex_status, 'codex_home_for', return_value=None):
            result = await server.get_usage()
        self.assertEqual(result.get('posture'), self.posture)

    async def test_posture_cli_failure_is_named_and_does_not_raise(self):
        self.posture_reader.stop()
        self.addCleanup(self.posture_reader.start)
        with patch('shutil.which', return_value=None):
            self.assertEqual(server._read_usage_posture(), {
                'state': 'unavailable', 'reason': 'token_usage_cli_unavailable'})
        with patch('shutil.which', return_value='/bin/token-usage'), \
                patch.object(server.subprocess, 'run', side_effect=subprocess.TimeoutExpired('token-usage', 5)):
            self.assertEqual(server._read_usage_posture(), {
                'state': 'unavailable', 'reason': 'token_usage_posture_timeout'})
        posture = {'provider': 'anthropic', 'scores': {'openai': 1.2, 'anthropic': 0.8},
                   'used_percent': {'openai': 60, 'anthropic': 40},
                   'resets_at': {'openai': '2026-10-30T00:00:00Z', 'anthropic': '2026-10-31T00:00:00Z'},
                   'stale': {'openai': False, 'anthropic': False},
                   'staleness': {'stale': False, 'newest_observed': '2026-10-29T00:00:00Z', 'age_seconds': 0},
                   'gated': {'openai': False, 'anthropic': False}, 'reason': 'Anthropic is behind pace'}
        with patch('shutil.which', return_value='/bin/token-usage'), \
                patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    args=['token-usage'], returncode=0, stdout=json.dumps(posture), stderr='')) as run:
            self.assertEqual(server._read_usage_posture(), posture)
            run.assert_called_once_with(
                ['/bin/token-usage', 'posture', '--no-scan', '--json'], capture_output=True,
                text=True, encoding='utf-8', errors='strict', timeout=5, check=False)
        # The current producer adds `expired` even when empty. After a weekly
        # reset it emits null scores and usage for that expired meter.
        current = {**posture, 'staleness': {**posture['staleness'], 'expired': {}}}
        expired = {**current, 'scores': {'openai': None, 'anthropic': 0.8},
                   'used_percent': {'openai': None, 'anthropic': 40},
                   'staleness': {**current['staleness'], 'stale': True,
                                 'expired': {'openai': 3600, 'anthropic.five_hour': 60}}}
        anthropic_expired = {**current, 'scores': {'openai': 1.2, 'anthropic': None},
                             'used_percent': {'openai': 60, 'anthropic': None},
                             'staleness': {**current['staleness'], 'stale': True,
                                           'expired': {'anthropic.seven_day': 120}}}
        for item in (current, expired, anthropic_expired):
            with patch('shutil.which', return_value='/bin/token-usage'), \
                    patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess(
                        args=['token-usage'], returncode=0, stdout=json.dumps(item), stderr='')):
                self.assertEqual(server._read_usage_posture(), item)
        for stdout in ('not json', '[]', '{"reason":"missing provider"}',
                       '{"provider":"Mars"}', '{"provider":"openai"}'):
            with patch('shutil.which', return_value='/bin/token-usage'), \
                    patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess(
                        args=['token-usage'], returncode=0, stdout=stdout, stderr='')):
                self.assertEqual(server._read_usage_posture(), {
                    'state': 'unavailable', 'reason': 'token_usage_posture_malformed'})
        with patch('shutil.which', return_value='/bin/token-usage'), \
                patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    args=['token-usage'], returncode=1, stdout='', stderr='meter unavailable')):
            self.assertEqual(server._read_usage_posture(), {
                'state': 'unavailable', 'reason': 'token_usage_posture_failed'})
        with patch('shutil.which', return_value='/bin/token-usage'), \
                patch.object(server.subprocess, 'run', side_effect=UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid')):
            self.assertEqual(server._read_usage_posture(), {
                'state': 'unavailable', 'reason': 'token_usage_posture_malformed'})
        with patch('shutil.which', return_value='/bin/token-usage'), \
                patch.object(server.subprocess, 'run', side_effect=OSError('exec failed')):
            self.assertEqual(server._read_usage_posture(), {
                'state': 'unavailable', 'reason': 'token_usage_posture_exec_failed'})
        malformed = [
            {**posture, 'secret': 'unexpected'},
            {**posture, 'scores': {'openai': 1.2}},
            {**posture, 'scores': {'openai': 'bad', 'anthropic': 0.8}},
            {**posture, 'scores': {'openai': 10 ** 400, 'anthropic': 0.8}},
            {**posture, 'scores': {'openai': float('nan'), 'anthropic': 0.8}},
            {**posture, 'used_percent': {'openai': float('inf'), 'anthropic': 40}},
            {**posture, 'staleness': None},
            {**posture, 'staleness': {**posture['staleness'], 'path': '/private'}},
            {**current, 'staleness': {**current['staleness'], 'expired': {'unknown': 1}}},
            {**current, 'staleness': {**current['staleness'], 'expired': {'openai': True}}},
            {**current, 'staleness': {**current['staleness'], 'expired': {'openai': -1}}},
            {**current, 'staleness': {**current['staleness'], 'expired': {'openai': 1.5}}},
            {**current, 'scores': {'openai': None, 'anthropic': 0.8}},
            {**expired, 'scores': {'openai': 1.2, 'anthropic': 0.8}},
            {**expired, 'used_percent': {'openai': 60, 'anthropic': 40}},
            {**posture, 'staleness': {**posture['staleness'], 'age_seconds': -1}},
            {**posture, 'staleness': {**posture['staleness'], 'age_seconds': True}},
            {**posture, 'staleness': {**posture['staleness'], 'age_seconds': 0.5}},
            {**posture, 'staleness': {**posture['staleness'], 'newest_observed': None}},
            {**posture, 'reason': None},
            {**posture, 'gated': {'openai': 0, 'anthropic': False}},
            {**posture, 'stale': {'openai': None, 'anthropic': False}},
        ]
        for item in malformed:
            with patch('shutil.which', return_value='/bin/token-usage'), \
                    patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess(
                        args=['token-usage'], returncode=0, stdout=json.dumps(item), stderr='')):
                self.assertEqual(server._read_usage_posture(), {
                    'state': 'unavailable', 'reason': 'token_usage_posture_malformed'})

    async def test_claude_binding_ignores_env_override(self):
        snapshot={'schema_version':1,'session_id':SID,'observed_at':100,'model':{'id':'test'},'context_window':{'remaining_percentage':42}, 'transcript_path':'private'}
        (self.path/f'{SID}.status.json').write_text(json.dumps(snapshot))
        binding = {'state': 'observed', 'session_id': SID, 'pointer_paths': [str(self.path / 'current.123')], 'status_dir': str(self.path)}
        with patch.object(server,'_own_identity',return_value=self.identity), patch('session_binding.observe_native_session',return_value=binding) as reader, patch.dict('os.environ',{'CLAUDE_SESSION_ID':'wrong'}):
            got=await server.get_status()
            self.assertEqual(got['observation'].get('session_id'),SID)
            self.assertEqual(got['observation']['context_window']['remaining_percentage'],42)
            self.assertNotIn('transcript_path',got['observation'])
            reader.assert_called_with('claude', self.identity)

    async def test_missing_or_invalid_snapshot_unavailable(self):
        binding = {'state': 'observed', 'session_id': SID, 'pointer_paths': [str(self.path / 'current.123')], 'status_dir': str(self.path)}
        with patch.object(server,'_own_identity',return_value=self.identity), patch('session_binding.observe_native_session',return_value=binding):
            for raw in (None, '{', 'x'*(1024*1024+1)):
                if raw is not None:
                    (self.path/f'{SID}.status.json').write_text(raw)
                self.assertEqual((await server.get_status())['observation']['state'],'unavailable')
        with patch.object(server,'_own_identity',return_value=self.identity), patch('session_binding.observe_native_session',return_value={'state':'unavailable','reason':'invalid'}):
            self.assertEqual((await server.get_status())['observation']['state'], 'unavailable')

    async def test_codex_allowlist(self):
        identity=Identity('codex',123,'777','boot','/tmp/socket','%9','/work')
        data={'state':'observed','source':'codex_rollout','session_id':SID,'quota_buckets':{'test':{}},'rollout_path':'private','model':'test'}
        with patch.object(server,'_own_identity',return_value=identity), patch('session_binding.observe_native_session',return_value={'state':'observed','session_id':SID,'observation':data}):
            status=await server.get_status()
            with patch.object(server.codex_status,'codex_home_for',return_value=None):
                usage=await server.get_usage()
            self.assertNotIn('rollout_path',status['observation'])
            self.assertNotIn('rollout_path',usage)
            self.assertNotIn('model',usage)
            self.assertEqual(usage['quota_buckets'],{'test':{'superseded':None}})

    def _bucket(self, stamp, used):
        return {'limit_id': 'codex', 'observed_at': stamp, 'primary': {'used_percent': used}}

    async def _codex_usage(self, session, account, home='home'):
        identity = Identity('codex', 123, '777', 'boot', '/tmp/socket', '%9', '/work')
        data = {'state': 'observed', 'source': 'codex_rollout', 'session_id': SID,
                'quota_buckets': session, 'rollout_path': 'private'}
        binding = {'state': 'observed', 'session_id': SID, 'observation': data}
        with patch.object(server, '_own_identity', return_value=identity), \
                patch('session_binding.observe_native_session', return_value=binding), \
                patch.object(server.codex_status, 'codex_home_for', return_value=Path(self.tmp.name) if home else None) as locate, \
                patch.object(server.codex_status, 'newest_account_quota', return_value=account) as newest:
            result = await server.get_usage()
        locate.assert_called_once_with(123)
        if home:
            newest.assert_called_once_with(Path(self.tmp.name), expected_buckets=list(session) or None)
        else:
            newest.assert_not_called()
        return result

    async def test_codex_account_latest_and_superseded(self):
        old, new = '2026-10-14T00:00:00Z', '2026-10-15T06:00:00Z'
        account = {'state': 'observed', 'source': 'codex_rollouts_newest', 'scope': 'account',
                   'quota_buckets': {'codex': self._bucket(new, 1), 'same': self._bucket(old, 5),
                                     'older': self._bucket(old, 5)}, 'files_scanned': 2}
        session = {'codex': self._bucket(old, 99), 'same': self._bucket(old, 5),
                   'older': self._bucket(new, 7), 'absent': self._bucket(old, 3), 'bad': {'observed_at': 'x'}}
        usage = await self._codex_usage(session, account)
        self.assertEqual(usage['account_latest'], account)
        flags = {key: bucket['superseded'] for key, bucket in usage['quota_buckets'].items()}
        self.assertEqual(flags, {'codex': True, 'same': False, 'older': False, 'absent': None, 'bad': None})
        self.assertEqual(usage['quota_buckets']['codex']['primary'], {'used_percent': 99})
        self.assertNotIn('rollout_path', usage)
        self.assertNotIn('superseded', session['codex'])  # the binding's own data is not mutated

    async def test_codex_account_latest_unavailable_without_home(self):
        usage = await self._codex_usage({'codex': self._bucket('2026-10-14T00:00:00Z', 9)}, None, home=None)
        self.assertEqual(usage['account_latest'], {'state': 'unavailable', 'source': 'codex_rollouts_newest',
                                                   'reason': 'codex_home_unavailable'})
        self.assertIsNone(usage['quota_buckets']['codex']['superseded'])  # unknown, not False

    async def test_superseded_reflects_account_uncertainty(self):
        old, new = '2026-10-14T00:00:00Z', '2026-10-15T06:00:00Z'
        session = {'newer': self._bucket(old, 9), 'same': self._bucket(old, 9), 'absent': self._bucket(old, 9)}
        def account(**extra):
            return {'state': 'observed', 'source': 'codex_rollouts_newest', 'scope': 'account',
                    'quota_buckets': {'newer': self._bucket(new, 1), 'same': self._bucket(old, 9)}, **extra}
        flags = lambda usage: {k: v['superseded'] for k, v in usage['quota_buckets'].items()}
        self.assertEqual(flags(await self._codex_usage(session, account())),
                         {'newer': True, 'same': False, 'absent': None})
        # Incomplete: True is still a real newer observation; False degrades to unknown.
        self.assertEqual(flags(await self._codex_usage(session, account(incomplete=True))),
                         {'newer': True, 'same': None, 'absent': None})

    async def test_codex_account_reader_failure_keeps_session_result(self):
        identity = Identity('codex', 123, '777', 'boot', '/tmp/socket', '%9', '/work')
        data = {'state': 'observed', 'session_id': SID, 'quota_buckets': {'codex': self._bucket('2026-10-14T00:00:00Z', 9)}}
        binding = {'state': 'observed', 'session_id': SID, 'observation': data}
        with patch.object(server, '_own_identity', return_value=identity), \
                patch('session_binding.observe_native_session', return_value=binding), \
                patch.object(server.codex_status, 'codex_home_for', return_value=self.path), \
                patch.object(server.codex_status, 'newest_account_quota', side_effect=RecursionError('deep')):
            try:
                usage = await server.get_usage()
            except Exception as exc:
                self.fail('account reader failure escaped: ' + type(exc).__name__)
        self.assertEqual(usage['account_latest'], {'state': 'unavailable', 'source': 'codex_rollouts_newest',
                                                   'reason': 'reader_failed'})
        self.assertEqual(usage['session_id'], SID)
        self.assertIsNone(usage['quota_buckets']['codex']['superseded'])

    async def test_codex_partial_observation_limits(self):
        identity = Identity('codex', 123, '777', 'boot', '/tmp/socket', '%9', '/work')
        data = {'state': 'observed', 'session_id': SID, 'history_complete': False,
                'read_window': {'tail_bytes': 100}, 'rollout_path': 'private'}
        with patch.object(server, '_own_identity', return_value=identity), patch('session_binding.observe_native_session',return_value={'state':'observed','session_id':SID,'observation':data}):
            result = await server.get_usage()
        self.assertIs(result.get('history_complete'), False)
        self.assertEqual(result.get('read_window'), {'tail_bytes': 100})
        self.assertNotIn('rollout_path', result)

    async def test_codex_unsupported_result_compatibility(self):
        identity = Identity('codex', 123, '777', 'boot', '/tmp/socket', '%9', '/work')
        old = {'state': 'unsupported', 'source': 'codex_rollout', 'reason': 'ambiguous_or_missing_live_rollout'}
        binding = {'state': 'unavailable', 'reason': 'codex_rollout_unavailable', 'observation': old}
        with patch.object(server, '_own_identity', return_value=identity), patch('session_binding.observe_native_session', return_value=binding):
            status = await server.get_status()
            with patch.object(server.codex_status, 'codex_home_for', return_value=self.path / 'absent'):
                usage = await server.get_usage()
        self.assertEqual(status['observation'], old)
        # The daemon case stays "unsupported" with its reason, plus the account meter.
        self.assertEqual({k: v for k, v in usage.items() if k not in ('account_latest', 'posture')}, old)
        self.assertIs(usage['posture'], self.posture)
        self.assertEqual(usage['account_latest'], {'state': 'unavailable', 'source': 'codex_rollouts_newest',
                                                   'reason': 'sessions_unreadable'})

    async def test_configured_pointer_snapshot_uses_default_directory(self):
        sid = 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'
        snapshot = {'schema_version': 1, 'session_id': sid, 'observed_at': 100}
        (self.path / f'{sid}.status.json').write_text(json.dumps(snapshot))
        binding = {'state': 'observed', 'session_id': sid,
                   'pointer_paths': ['/configured/session-state/current.123'], 'status_dir': str(self.path)}
        with patch.object(server, '_own_identity', return_value=self.identity), patch('session_binding.observe_native_session', return_value=binding):
            result = await server.get_status()
        self.assertEqual(result['observation']['state'], 'available')
        self.assertEqual(result['observation']['session_id'], sid)


MUTANTS = {
    'test_codex_partial_observation_limits': (", 'history_complete', 'read_window')", ")"),
    'test_pinned_identity_verified_every_time': ('if _self_identity is None:', 'if True:'),
    'test_no_tmux_returns_typed_unavailable': ('"reason": str(exc)', '"reason": "unknown"'),
    'test_claude_binding_ignores_env_override': ('binding = await asyncio.to_thread(_native_observation, identity)', "binding = {'state': 'observed', 'session_id': os.environ.get('CLAUDE_SESSION_ID'), 'pointer_paths': ['/tmp/nope'], 'status_dir': '/tmp'}"),
    'test_missing_or_invalid_snapshot_unavailable': ('return sid, None\n\n\n@mcp.tool()', "return sid, {'schema_version': 1, 'session_id': sid, 'observed_at': 1}\n\n\n@mcp.tool()"),
    'test_codex_account_latest_and_superseded': ("flag = True if latest > mine else (False if complete else None)", "flag = True if latest >= mine else (False if complete else None)"),
    'test_superseded_reflects_account_uncertainty': ("complete = observed and account_latest.get('incomplete') is not True", "complete = observed"),
    'test_codex_account_reader_failure_keeps_session_result': ("        except Exception:  # never lose", "        except ZeroDivisionError:  # never lose"),
    'test_codex_account_latest_unavailable_without_home': ("            flag = None\n            mine = _observed(bucket)", "            flag = False\n            mine = _observed(bucket)"),
    'test_codex_allowlist': ("state.pop('rollout_path', None)", 'pass'),
    'test_codex_unsupported_result_compatibility': ("state = dict(binding.get('observation',", "state = dict({'state': 'unavailable', 'reason': 'changed'}.get('observation',"),
    'test_configured_pointer_snapshot_uses_default_directory': ("Path(binding['status_dir'])", "Path(binding['pointer_paths'][0]).parent"),
    'test_posture_is_attached_to_claude_usage': ("result['posture'] = posture", "pass"),
    'test_posture_is_attached_to_codex_usage': ("        result['posture'] = posture\n        return result\n    except IdentityError", "        result['posture'] = {'state': 'unavailable'}\n        return result\n    except IdentityError"),
    'test_posture_cli_failure_is_named_and_does_not_raise': ("'token_usage_posture_timeout'", "'unknown'"),
}


def mutation_check():
    subprocess.run([sys.executable, __file__], check=True, timeout=90)
    if set(unittest.defaultTestLoader.getTestCaseNames(ToolsTests)) != set(MUTANTS):
        raise RuntimeError('Every behavior test needs a mutation check')
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        for test, (old, new) in MUTANTS.items():
            source = MODULE.read_text()
            if old not in source:
                raise RuntimeError(f'Mutation anchor drift: {test}')
            target = Path(directory) / f'{test}.py'
            changed = source.replace(old, new, 1)
            compile(changed, str(target), 'exec')
            target.write_text(changed)
            env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                   'HARNESS_TOOLS_TEST_MODULE': str(target)}
            result = subprocess.run([sys.executable, __file__, f'ToolsTests.{test}'],
                                    env=env, text=True, capture_output=True, timeout=30)
            killed = result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr
            print(f"{'KILLED' if killed else 'SURVIVED'} ToolsTests.{test}")
            if not killed:
                failures.append(test)
                print(result.stdout + result.stderr)
    return bool(failures)


if __name__=='__main__':
    if sys.argv[1:] == ['--mutation-check']:
        raise SystemExit(mutation_check())
    unittest.main()
