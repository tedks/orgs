#!/usr/bin/env python3
"""Self-only MCP lifecycle binding tests; no terminal or harness is controlled."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
MODULE = Path(os.environ.get('HARNESS_LIFECYCLE_TEST_MODULE', Path(__file__).with_name('server.py')))
spec = importlib.util.spec_from_file_location('server', MODULE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from harness_control import ControlError, OperationInProgress
from harness_identity import Identity, IdentityError

SID = '11111111-1111-1111-1111-111111111111'
OTHER = '22222222-2222-2222-2222-222222222222'


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.identity = Identity('claude', 123, '777', 'boot', '/fixture/socket', '%9', '/work')
        self.snapshot = {'schema_version': 1, 'session_id': SID, 'observed_at': 100,
                         'transcript_path': str(self.root / (SID + '.jsonl'))}
        self.write_snapshot()
        self.control = Mock()
        for method in ('request', 'record_checkpoint', 'operation', 'cancel', 'read_own_pane'):
            getattr(self.control, method).return_value = {'state': 'test_result', 'method': method}
        self.addCleanup(patch.stopall)
        patch.object(server, '_own_identity', return_value=self.identity).start()
        self.binding = patch('session_binding.observe_native_session', return_value={
            'state': 'observed', 'session_id': SID,
            'pointer_paths': [str(self.root / 'current.123')], 'status_dir': str(self.root)}).start()
        self.verify = patch('harness_identity.verify_pane').start()
        self.constructor = patch('harness_control.HarnessControl', return_value=self.control).start()

    def write_snapshot(self):
        (self.root / (SID + '.status.json')).write_text(json.dumps(self.snapshot))

    async def test_mcp_schema_self_only(self):
        schemas = {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}
        expected = {'record_checkpoint', 'self_compact', 'self_exit', 'send_to_self',
                    'read_own_pane', 'get_operation', 'cancel_operation'}
        self.assertTrue(expected.issubset(schemas))
        for name in expected:
            self.assertFalse({'identity', 'pid', 'pane', 'socket', 'session_id', 'transcript_path'} & set(schemas[name].get('properties', {})))
        self.assertEqual({'checkpoint_path', 'checkpoint_receipt'}, set(schemas['self_compact']['required']))
        self.assertEqual({'checkpoint_receipt'}, set(schemas['self_exit']['required']))

    async def test_default_budget_leaves_time_for_turn_completion(self):
        await server.self_compact('/private/shard', 'receipt')
        self.assertEqual(self.control.request.call_args.kwargs['timeout_seconds'], 3600)
        await server.self_exit('receipt')
        self.assertEqual(self.control.request.call_args.kwargs['timeout_seconds'], 300)
        await server.send_to_self('ordinary follow-up')
        self.assertEqual(self.control.request.call_args.kwargs['timeout_seconds'], 300)

    async def test_claude_pointer_and_snapshot_bind_ignoring_override(self):
        with patch.dict(os.environ, {'CLAUDE_SESSION_ID': OTHER}):
            result = server._control_call('read_own_pane', require_transcript=True)
        self.assertEqual('test_result', result['state'])
        self.constructor.assert_called_once_with(self.identity, SID, self.snapshot['transcript_path'])
        self.assertEqual(2, self.binding.call_count)
        self.binding.assert_called_with('claude', self.identity)
        self.verify.assert_called_once_with(self.identity)

    async def test_mismatched_snapshot_refuses_compaction(self):
        for change in ({'session_id': OTHER}, {'schema_version': 99}, {'observed_at': None}):
            self.snapshot.update(change)
            self.write_snapshot()
            result = await server.self_compact('/private/shard', 'receipt')
            self.assertEqual('unavailable', result['state'])
        self.constructor.assert_not_called()

    async def test_exit_requires_transcript_for_native_idle_gate(self):
        self.snapshot.pop('transcript_path')
        self.write_snapshot()
        result = await server.self_exit('receipt')
        self.assertEqual(result['state'], 'unavailable')
        self.constructor.assert_not_called()

    async def test_transcript_path_bound_to_session(self):
        for path in ('relative.jsonl', '/private/' + OTHER + '.jsonl', None):
            self.snapshot['transcript_path'] = path
            self.write_snapshot()
            result = await server.self_compact('/private/shard', 'receipt')
            self.assertEqual('bound_transcript_path_unavailable', result.get('reason'))
        self.constructor.assert_not_called()

    async def test_pointer_change_refuses_before_dispatch(self):
        self.binding.side_effect = [
            {'state': 'observed', 'session_id': SID, 'pointer_paths': [str(self.root / 'current.123')], 'status_dir': str(self.root)},
            {'state': 'observed', 'session_id': OTHER, 'pointer_paths': [str(self.root / 'current.123')], 'status_dir': str(self.root)}]
        result = await server.self_exit('receipt')
        self.assertEqual({'state': 'unavailable', 'reason': 'own_session_changed_during_binding'}, result)
        self.constructor.assert_not_called()

    async def test_noncompact_needs_session_but_not_transcript(self):
        (self.root / (SID + '.status.json')).unlink()
        result = await server.send_to_self('hello')
        self.assertEqual('test_result', result['state'])
        self.constructor.assert_called_once_with(self.identity, SID, None)
        self.binding.return_value = {'state': 'unavailable', 'reason': 'missing'}
        result = await server.self_exit('receipt')
        self.assertEqual({'state': 'unavailable', 'reason': 'own_session_unavailable'}, result)

    async def test_codex_unique_live_rollout_binding(self):
        identity = Identity('codex', 456, '888', 'boot', '/fixture/socket', '%10', '/work')
        proof = {'state': 'observed', 'session_id': SID, 'transcript_path': '/private/rollout.jsonl'}
        with patch.object(server, '_own_identity', return_value=identity), patch('session_binding.observe_native_session', return_value=proof) as reader:
            server._own_control(require_transcript=True)
        reader.assert_called_once_with('codex', identity)
        self.constructor.assert_called_once_with(identity, SID, '/private/rollout.jsonl')

    async def test_codex_unknown_rollout_never_dispatches(self):
        identity = Identity('codex', 456, '888', 'boot', '/fixture/socket', '%10', '/work')
        for observation in ({'state': 'unavailable', 'reason': 'rollout'}, {'state': 'observed', 'session_id': SID}, {'state': 'observed', 'session_id': SID, 'transcript_path': None}):
            with patch.object(server, '_own_identity', return_value=identity), patch('session_binding.observe_native_session', return_value=observation):
                result = await server.self_compact('/shard', 'receipt')
            self.assertEqual('unavailable', result['state'])
        self.constructor.assert_not_called()

    async def test_errors_are_typed_and_private_details_omitted(self):
        for error, state, reason in ((ControlError('recorded_checkpoint_required'), 'refused', 'recorded_checkpoint_required'),
                                     (IdentityError('outside tmux'), 'unavailable', 'outside tmux'),
                                     (OSError('/private/secret contents'), 'unavailable', 'control_evidence_unavailable_or_invalid'),
                                     (ValueError('private corrupt JSON'), 'unavailable', 'control_evidence_unavailable_or_invalid')):
            with patch.object(server, '_own_control', side_effect=error):
                self.assertEqual({'state': state, 'reason': reason}, await server.self_exit('receipt'))

    async def test_in_progress_result_names_blocker_and_clearance(self):
        self.control.request.side_effect = OperationInProgress(
            'a' * 32, 'warning_dispatching', 'cancel_operation(' + 'a' * 32 + ') then retry')
        result = await server.self_compact('/private/shard', 'receipt')
        self.assertEqual('refused', result['state'])
        self.assertEqual('operation_in_progress', result['reason'])
        self.assertEqual('a' * 32, result['blocking_operation_id'])
        self.assertEqual('warning_dispatching', result['blocking_state'])
        self.assertIn('cancel_operation', result['next_action'])

    async def test_compact_forwards_recovery_and_continuation(self):
        result = await server.self_compact('/private/shard', 'receipt', continuation='Resume bounded work.', focus='Preserve pauses.', timeout_seconds=90)
        self.assertEqual({'state': 'test_result', 'method': 'request'}, result)
        self.control.request.assert_called_once_with('compact', checkpoint_receipt='receipt', checkpoint_path='/private/shard', continuation='Resume bounded work.', focus='Preserve pauses.', timeout_seconds=90)
        self.constructor.assert_called_once_with(self.identity, SID, self.snapshot['transcript_path'])

    async def test_exit_and_send_forward_exact_controls(self):
        await server.self_exit('receipt', timeout_seconds=80)
        self.control.request.assert_called_with('exit', checkpoint_receipt='receipt', timeout_seconds=80)
        await server.send_to_self('/status', timeout_seconds=70)
        self.control.request.assert_called_with('send', text='/status', timeout_seconds=70)
        self.assertEqual(2, self.control.request.call_count)

    async def test_receipt_operation_cancel_and_read_forward(self):
        evidence = {'shard_path': '/private/shard'}
        await server.record_checkpoint(evidence)
        self.control.record_checkpoint.assert_called_once_with(evidence)
        await server.get_operation('operation-id')
        self.control.operation.assert_called_once_with('operation-id')
        await server.cancel_operation('operation-id')
        self.control.cancel.assert_called_once_with('operation-id')
        result = await server.read_own_pane()
        self.control.read_own_pane.assert_called_once_with()
        self.assertEqual({'state': 'test_result', 'method': 'read_own_pane'}, result)


MUTANTS = {
    'test_exit_requires_transcript_for_native_idle_gate': ('checkpoint_receipt=checkpoint_receipt, timeout_seconds=timeout_seconds,\n        require_transcript=True)', 'checkpoint_receipt=checkpoint_receipt, timeout_seconds=timeout_seconds,\n        require_transcript=False)'),
    'test_default_budget_leaves_time_for_turn_completion': ('timeout_seconds: int = 3600) -> dict:', 'timeout_seconds: int = 300) -> dict:'),
    'test_mcp_schema_self_only': ('async def self_exit(checkpoint_receipt: str, timeout_seconds: int = 300)', 'async def self_exit(checkpoint_receipt: str, timeout_seconds: int = 300, pane: str = "")'),
    'test_claude_pointer_and_snapshot_bind_ignoring_override': ('binding = _native_observation(identity)', "binding = {'state': 'observed', 'session_id': os.environ.get('CLAUDE_SESSION_ID'), 'pointer_paths': ['/tmp/nope']}"),
    'test_mismatched_snapshot_refuses_compaction': ("if parse_claude_status(snapshot, sid)['state'] != 'available':", 'if False:'),
    'test_transcript_path_bound_to_session': ("or Path(transcript).name != sid + '.jsonl'", ''),
    'test_pointer_change_refuses_before_dispatch': ("if _own_binding(identity)['session_id'] != sid:", 'if False:'),
    'test_noncompact_needs_session_but_not_transcript': ("if binding['state'] != 'observed':", 'if False:'),
    'test_codex_unique_live_rollout_binding': ("transcript = binding.get('transcript_path')", "transcript = '/wrong/rollout.jsonl'"),
    'test_codex_unknown_rollout_never_dispatches': ("if not isinstance(transcript, str) or not Path(transcript).is_absolute():", 'if False:'),
    'test_errors_are_typed_and_private_details_omitted': ("return {'state': 'refused', 'reason': str(exc)}", "return {'state': 'unavailable', 'reason': str(exc)}"),
    'test_in_progress_result_names_blocker_and_clearance': ("'blocking_state': exc.state, 'next_action': exc.next_action", "'blocking_state': exc.state, 'next_action': 'wait'"),
    'test_compact_forwards_recovery_and_continuation': ('continuation=continuation, focus=focus, timeout_seconds=timeout_seconds,', 'continuation=None, focus=focus, timeout_seconds=timeout_seconds,'),
    'test_exit_and_send_forward_exact_controls': ("_control_call, 'request', 'exit',", "_control_call, 'request', 'send',"),
    'test_receipt_operation_cancel_and_read_forward': ("_control_call, 'cancel', operation_id", "_control_call, 'operation', operation_id"),
}


def mutation_check():
    baseline = subprocess.run([sys.executable, __file__], env={**os.environ, 'HARNESS_LIFECYCLE_TEST_MODULE': str(MODULE)}, capture_output=True, text=True, timeout=60)
    if baseline.returncode != 0:
        raise RuntimeError('Baseline failed before mutation checks:\n' + baseline.stdout + baseline.stderr)
    print('PASS: baseline', flush=True)
    if set(unittest.defaultTestLoader.getTestCaseNames(LifecycleTests)) != set(MUTANTS):
        raise RuntimeError('Every behavior test needs a mutation check')
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        for test, (before, after) in MUTANTS.items():
            source = MODULE.read_text()
            if before not in source:
                raise RuntimeError('Mutation anchor drift: ' + test)
            changed = source.replace(before, after, 1)
            target = Path(directory) / (test + '.py')
            compile(changed, str(target), 'exec')
            target.write_text(changed)
            result = subprocess.run([sys.executable, __file__, 'LifecycleTests.' + test], env={**os.environ, 'HARNESS_LIFECYCLE_TEST_MODULE': str(target)}, capture_output=True, text=True, timeout=30)
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
