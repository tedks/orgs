#!/usr/bin/env python3
"""Offline lifecycle contract tests. Never addresses a real agent pane.

--mutation-check proves the guards/witness tests reject intentionally broken
variants loaded from private temporary modules, without editing the worktree.
"""
from contextlib import nullcontext
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True

MODULE = Path(__file__).resolve().with_name('harness_control.py')
sys.path.insert(0, str(MODULE.parent))
spec = importlib.util.spec_from_file_location('harness_control', os.environ.get('HARNESS_CONTROL_TEST_MODULE', MODULE))
h = importlib.util.module_from_spec(spec)
sys.modules['harness_control'] = h
spec.loader.exec_module(h)
REAL_RUN = subprocess.run
REAL_POPEN = subprocess.Popen
SID = '12345678-1234-1234-1234-123456789abc'


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.shard = self.repo / 'handoff.md'
        self.shard.write_text('private checkpoint\n')
        self.git('add', 'handoff.md')
        self.git('commit', '-qm', 'fixture')
        self.evidence = {'shard_path': str(self.shard), 'repo_path': str(self.repo),
                         'sha256': hashlib.sha256(self.shard.read_bytes()).hexdigest(),
                         'commit': self.git('rev-parse', 'HEAD').strip(),
                         'private_storage_attested': True, 'push_attestation': 'no_remote_configured',
                         'authority': 'exit_authorized', 'resources_disposition': 'released',
                         'obligations_preserved': True, 'pause_state_preserved': True,
                         'pause_state_reference': 'handoff.md#pause', 'active_inventory_reference': 'handoff.md#inventory'}
        self.transcript = self.root / 'transcript.jsonl'
        self.transcript.write_text('')
        self.identity = h.Identity('claude', 99999, '123', 'boot', '/fixture/socket', '%999', '/fixture')
        self.control = h.HarnessControl(self.identity, SID, self.transcript, self.root / 'state')
        self.receipt = self.control.record_checkpoint(self.evidence)['receipt_id']
        self.verify = patch.object(h, 'verify_pane').start()
        self.real_verify_session = h._verify_session
        self.session_verify = patch.object(h, '_verify_session').start()
        self.real_native_idle = h._native_idle
        self.native_idle = patch.object(h, '_native_idle', return_value={'state': 'idle'}).start()
        self.real_watch = h._watch_compaction
        self.watch = patch.object(h, '_watch_compaction', side_effect=lambda *args: nullcontext({'available': False})).start()
        self.addCleanup(patch.stopall)
        self.spawn = Mock()
        def popen(args, **kw):
            if '--observe' in args:
                self.spawn(args, **kw)
                return SimpleNamespace(pid=12345)
            return REAL_POPEN(args, **kw)
        patch.object(h.subprocess, 'Popen', side_effect=popen).start()
        self.clock = time.time()
        self.sent = []
        self.commands = []
        self.marker_count = 0
        self.marker_enabled = True

    def git(self, *args):
        return REAL_RUN(['git', '-C', str(self.repo), *args], capture_output=True, text=True, check=True).stdout

    def request(self, action='compact', **kwargs):
        return self.control.request(action, checkpoint_receipt=self.receipt, **kwargs)['operation_id']

    def event(self, harness='claude', **extra):
        if self.marker_enabled:
            self.marker_count += 1
        row = {'type': 'system', 'subtype': 'compact_boundary', 'sessionId': SID} if harness == 'claude' else {'type': 'compacted', 'payload': {}}
        row.update(extra)
        with self.transcript.open('a') as stream:
            stream.write(json.dumps(row) + '\n')

    def observe(self, oid, send=None, alive=True):
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record['deadline'] = self.clock + (2 if record.get('focus') else 1) * (h.SEND_BUDGET + h.PREFLIGHT_BUDGET) + (h.COMPACT_WATCH if record['action'] == 'compact' else 0) + 1
        h._write(path, record)
        def run(args, **kwargs):
            if args[0] == 'git':
                return REAL_RUN(args, **kwargs)
            if args[1] == 'read':
                marker = h._COMPACT_MARKERS[self.identity.harness]
                row = ('  ⎿  ' if self.identity.harness == 'claude' else '') + marker + '\n'
                return subprocess.CompletedProcess(args, 0, row * self.marker_count, '')
            self.sent.append(Path(args[-1]).read_text())
            self.commands.append(args)
            if send:
                return send(args)
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'queued', 'pane': '%999'}), '')
        def sleep(seconds):
            self.clock += seconds
        with patch.object(h, '_transport_run', side_effect=lambda args, identity: run(args)), patch.object(h.subprocess, 'run', side_effect=run), patch.object(h, 'time', SimpleNamespace(time=lambda: self.clock, monotonic=lambda: self.clock, sleep=sleep, strftime=time.strftime, gmtime=time.gmtime)), patch.object(h, 'same_process', side_effect=alive if callable(alive) else lambda _: alive):
            h.observe(self.control.directory, oid)
        return self.control.operation(oid)

    def test_virtual_clock_does_not_change_subprocess_clock(self):
        original = (time.time, time.monotonic, time.sleep)
        oid = self.request('send', text='fixture')
        def send(args):
            self.assertIsNot(h.time, time)
            self.assertEqual(original, (time.time, time.monotonic, time.sleep))
            return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
        self.assertEqual('delivered', self.observe(oid, send)['state'])

    def idle_record(self, harness='claude', focus=None):
        return {'transcript_path': str(self.transcript), 'idle_baseline': h._baseline(self.transcript),
                'session_id': SID, 'identity': {**self.identity.public(), 'harness': harness}, 'focus': focus}

    def native_idle_result(self, *args):
        try:
            return self.real_native_idle(*args)
        except h.ControlError as exc:
            self.fail('Expected classified idle evidence, got rejection: ' + str(exc))

    def rows(self, *rows):
        with self.transcript.open('a', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row) + '\n')

    def claude_row(self, kind, uid, parent=None, **fields):
        return {'type': kind, 'uuid': uid, 'parentUuid': parent, 'sessionId': SID, 'isSidechain': False, **fields}

    def claude_idle_rows(self, prefix='one', focus='hello'):
        return [self.claude_row('user', prefix + '-u', message={'content': focus}),
                self.claude_row('assistant', prefix + '-a', prefix + '-u', message={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'done'}]}),
                self.claude_row('attachment', prefix + '-x', prefix + '-a'),
                self.claude_row('system', prefix + '-d', prefix + '-x', subtype='turn_duration', durationMs=12, messageCount=2)]

    def codex_idle_rows(self, turn='one', focus='hello'):
        return [{'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': turn, 'root_turn_id': turn}},
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': focus}]}},
                {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': turn}}]

    def test_native_idle_requires_matching_complete_root_turn(self):
        for harness in ('claude', 'codex'):
            self.transcript.write_text('')
            rows = self.claude_idle_rows() if harness == 'claude' else self.codex_idle_rows()
            self.rows(*rows[:-1])
            record = self.idle_record(harness)
            self.assertNotEqual('idle', self.native_idle_result(record)['state'])
            self.rows(rows[-1])
            self.assertEqual('idle', self.native_idle_result(record)['state'])
            newer = self.claude_row('user', 'new', 'one-d', message={'content': 'wait'}) if harness == 'claude' else self.codex_idle_rows('two')[0]
            self.rows(newer)
            with self.assertRaisesRegex(h.ControlError, 'superseded_by_new_input'):
                self.real_native_idle(record)
        for harness in ('claude', 'codex'):
            self.transcript.write_text('')
            rows = self.claude_idle_rows() if harness == 'claude' else self.codex_idle_rows()
            if harness == 'claude':
                rows[-1]['parentUuid'] = 'wrong'
            else:
                rows[-1]['payload']['turn_id'] = 'wrong'
            self.rows(*rows)
            self.assertNotEqual('idle', self.native_idle_result(self.idle_record(harness))['state'])

    def test_incident_records_root_completion_after_baseline_without_start_in_tail(self):
        fixtures = json.loads((MODULE.parent / 'fixtures/compact-stalled-records.json').read_text())
        for incident in fixtures:
            with self.subTest(operation_id=incident['operation_id']):
                self.transcript.write_text('')
                record = self.idle_record('codex')
                turn = incident['root_turn_id']
                self.rows(incident['native_completion_row'])
                result = self.native_idle_result(record)
                self.assertEqual('idle', result['state'])
                self.assertEqual(turn, result['turn_id'])
                self.assertEqual(turn, incident['native_completion_row']['payload']['root_turn_id'])

    def test_compact_idle_parser_follows_new_root_turns(self):
        for harness in ('codex', 'claude'):
            with self.subTest(harness=harness):
                self.transcript.write_text('')
                record = self.idle_record(harness)
                record['action'] = 'compact'
                rows = (self.codex_idle_rows('one') + self.codex_idle_rows('two') if harness == 'codex'
                        else self.claude_idle_rows('one') + self.claude_idle_rows('two'))
                self.rows(*rows)
                result = self.native_idle_result(record)
                self.assertEqual('idle', result['state'])
                self.assertEqual(2, result['turns_seen'])

    def test_claude_request_metadata_before_focus_turn(self):
        record = self.idle_record('claude', focus='focus')
        self.rows(*[{'type': kind, 'sessionId': SID} for kind in
                    ('api-request-shape', 'api-request-blob', 'api-request')],
                  *self.claude_idle_rows(focus='focus'))
        result = self.native_idle_result(record, 0)
        self.assertEqual('idle', result['state'])

    def test_claude_post_duration_request_stays_busy_until_next_turn(self):
        record = self.idle_record()
        record['action'] = 'compact'
        self.rows(*self.claude_idle_rows(),
                  {'type': 'api-request', 'sessionId': SID, 'querySource': 'repl_main_thread'})
        self.assertNotEqual('idle', self.native_idle_result(record)['state'])
        self.rows(*self.claude_idle_rows('next'))
        self.assertEqual('idle', self.native_idle_result(record)['state'])

    def test_sidechain_api_request_does_not_clear_root_idle(self):
        record = self.idle_record()
        record['action'] = 'compact'
        self.rows(*self.claude_idle_rows(),
                  {'type': 'api-request', 'sessionId': SID, 'isSidechain': True})
        self.assertEqual('idle', self.native_idle_result(record)['state'])

    def test_native_idle_tail_bounds_partial_and_rotation(self):
        self.rows(*self.claude_idle_rows())
        record = self.idle_record()
        original = self.transcript.read_bytes()
        with self.transcript.open('ab') as stream:
            stream.write(json.dumps({'type': 'mode', 'sessionId': SID, 'mode': 'fixture'}).encode())
        self.assertNotEqual('idle', self.native_idle_result(record)['state'])
        self.transcript.write_bytes(original)
        record.pop('_idle_cursor', None)
        with patch.object(h, 'MAX_FILE', 80):
            self.assertNotEqual('idle', self.native_idle_result(record)['state'])
        self.transcript.write_bytes(b'')
        with self.assertRaises(h.ControlError):
            self.real_native_idle(record)
        self.transcript.rename(self.root / 'old-transcript')
        self.transcript.write_text('')
        with self.assertRaises(h.ControlError):
            self.real_native_idle(record)

    def test_native_idle_focus_requires_new_exact_input_generation(self):
        for harness in ('claude', 'codex'):
            make = self.claude_idle_rows if harness == 'claude' else self.codex_idle_rows
            self.transcript.write_text('')
            self.rows(*make('old', 'focus'))
            record = self.idle_record(harness, 'focus')
            after = self.transcript.stat().st_size
            self.assertNotEqual('idle', self.native_idle_result(record, after)['state'])
            self.rows(*make('new', 'focus'))
            self.assertEqual('idle', self.native_idle_result(record, after)['state'])
            self.rows(*make('duplicate', 'focus'))
            with self.assertRaisesRegex(h.ControlError, 'superseded'):
                self.real_native_idle(record, after)
            self.transcript.write_text('')
            record = self.idle_record(harness, 'focus')
            self.rows(*make('wrong', 'other'))
            with self.assertRaisesRegex(h.ControlError, 'superseded'):
                self.real_native_idle(record, 0)
        self.transcript.write_text('')
        rows = self.codex_idle_rows('old', 'focus')
        self.rows(rows[0])
        record = self.idle_record('codex', 'focus')
        after = self.transcript.stat().st_size
        self.rows(*rows[1:])
        with self.assertRaisesRegex(h.ControlError, 'superseded'):
            self.real_native_idle(record, after)

    def test_historical_odd_rows_do_not_poison_current_bound_chain(self):
        for harness in ('claude', 'codex'):
            self.transcript.write_text('not json\n')
            self.rows({'type': 'legacy_summary', 'sessionId': 'old'})
            make = self.claude_idle_rows if harness == 'claude' else self.codex_idle_rows
            self.rows(*make())
            record = self.idle_record(harness)
            try:
                result = self.real_native_idle(record)
            except h.ControlError as exc:
                self.fail('Historical odd row poisoned later valid evidence: ' + str(exc))
            self.assertEqual('idle', result['state'])
            with patch.object(h.json, 'loads', side_effect=AssertionError('history reparsed')):
                self.assertEqual('idle', self.native_idle_result(record)['state'])
            self.rows({'type': 'new_unknown'})
            with self.assertRaisesRegex(h.ControlError, 'idle_record_shape_unknown'):
                self.real_native_idle(record)
        self.transcript.write_text('bad history\n')
        self.rows(self.claude_idle_rows()[-1])
        self.assertNotEqual('idle', self.native_idle_result(self.idle_record())['state'])

    def test_native_idle_unknown_partial_malformed_and_sidechain_fail_closed(self):
        for bad in (b'{', b'not json\n', b'[]\n', b'{"type":"new_unknown"}\n'):
            self.transcript.write_text('')
            self.rows(*self.claude_idle_rows())
            record = self.idle_record()
            with self.transcript.open('ab') as stream:
                stream.write(bad)
            try:
                state = self.real_native_idle(record)['state']
            except h.ControlError:
                state = 'unknown'
            self.assertNotEqual('idle', state)
        for update in ({'sessionId': 'wrong'}, {'isSidechain': True}, {'isSidechain': None}):
            self.transcript.write_text('')
            rows = self.claude_idle_rows()
            rows[-1].update(update)
            self.rows(*rows)
            self.assertNotEqual('idle', self.native_idle_result(self.idle_record())['state'])
        self.transcript.write_text('')
        rows = self.claude_idle_rows()
        rows[1]['message']['content'] = [{'type': 'thinking', 'thinking': 'not final'}]
        self.rows(*rows)
        self.assertNotEqual('idle', self.native_idle_result(self.idle_record())['state'])
        self.transcript.write_text('')
        self.rows(*self.codex_idle_rows(), {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'child', 'root_turn_id': 'one'}}, {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'child'}})
        self.assertEqual('idle', self.native_idle_result(self.idle_record('codex'))['state'])

    def test_idle_wait_busy_then_new_idle_and_timeout_no_send(self):
        oid = self.request('exit')
        self.native_idle.side_effect = [{'state': 'busy_or_unknown'}, {'state': 'idle'}, {'state': 'idle'}]
        result = self.observe(oid, alive=False)
        self.assertEqual('completed', result['state'])
        self.assertEqual(['/exit'], self.sent)
        self.assertEqual('not_applicable', result['continuation']['state'])
        self.sent.clear()
        self.native_idle.side_effect = None
        self.native_idle.return_value = {'state': 'unknown'}
        oid = self.request('exit')
        result = self.observe(oid, alive=False)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('not_dispatched', result['delivery']['state'])
        self.assertEqual([], self.sent)
        h.observe(self.control.directory, oid)
        self.assertEqual([], self.sent)

    def test_compact_idle_bound_warns_once_and_records_transitions(self):
        oid = self.request(timeout_seconds=30)
        self.native_idle.return_value = {'state': 'busy_or_unknown', 'reason': 'busy_or_unknown'}
        def notice_in_flight(args):
            current = self.control.operation(oid)
            self.assertEqual('warning_dispatching', current['state'])
            return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
        result = self.observe(oid, notice_in_flight)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('native_idle_not_observed_within_bound', result['reason'])
        self.assertEqual('delivered', (result.get('failure_notice') or {}).get('state'))
        self.assertEqual(1, len(self.sent))
        self.assertEqual('COMPACTION NOT DISPATCHED: native_idle_not_observed_within_bound; '
                         'run /compact yourself or ask a peer', self.sent[0])
        record = h._read(self.control.directory / (oid + '.json'))
        states = [step['state'] for step in record['transitions']]
        self.assertEqual('scheduled', states[0])
        self.assertIn('waiting_idle', states)
        self.assertEqual('deferred', states[-1])
        self.assertEqual('delivered', record['transitions'][-1]['failure_notice'])
        before = len(record['transitions'])
        h.observe(self.control.directory, oid)
        self.assertEqual(before, len(h._read(self.control.directory / (oid + '.json'))['transitions']))
        self.assertEqual(1, len(self.sent))

    def test_intervening_root_turn_cancels_compact_with_one_notice(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        self.rows(*self.claude_idle_rows('after'))
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual('intervening_turn', result['reason'])
        self.assertEqual('not_dispatched', result['delivery']['state'])
        self.assertNotIn('/compact', self.sent)
        notices = [message for message in self.sent if message.startswith('COMPACTION CANCELLED:')]
        self.assertEqual(1, len(notices))
        self.assertEqual('COMPACTION CANCELLED: 1 turn(s) since your checkpoint; re-checkpoint and request again', notices[0])

    def test_permanent_native_shape_error_defers_immediately(self):
        oid = self.request(timeout_seconds=30)
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record['state'] = 'waiting_idle'
        h._write(path, record)
        for reason in ('idle_record_shape_unknown', 'idle_root_session_unavailable',
                       'idle_metadata_malformed', 'idle_transcript_replaced_or_truncated',
                       'idle_observation_limit'):
            with self.subTest(reason=reason):
                self.native_idle.side_effect = h.ControlError(reason)
                result = h._wait_idle(record, self.identity, time.monotonic() + 30, operation_path=path)
                self.assertEqual({'state': 'deferred', 'reason': reason, 'evidence_reason': reason}, result)

    def test_persisted_native_parse_error_defers_immediately(self):
        record = self.idle_record('codex')
        record['action'] = 'compact'
        self.rows({'type': 'event_msg', 'payload': []})
        self.native_idle.side_effect = self.real_native_idle
        result = h._wait_idle(record, self.identity, time.monotonic() + 30)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('idle_event_malformed', result['reason'])

    def test_queued_claude_input_supersedes_before_current_turn_finishes(self):
        for queued in ({'type': 'queue-operation', 'sessionId': SID},
                       self.claude_row('attachment', 'queued', 'one-x', attachment={'type': 'queued_command'})):
            with self.subTest(kind=queued['type']):
                self.transcript.write_text('')
                record = self.idle_record()
                record['action'] = 'compact'
                rows = self.claude_idle_rows()
                if queued['type'] == 'attachment':
                    rows[-1]['parentUuid'] = 'queued'
                self.rows(*rows[:-1], queued, rows[-1])
                result = self.native_idle_result(record)
                self.assertGreaterEqual(result.get('turns_seen', 0), 1)

    def test_queued_input_cancels_compact_with_one_notice(self):
        rows = self.claude_idle_rows()
        self.rows(*rows[:-1])
        oid = self.request(timeout_seconds=30)
        self.rows({'type': 'queue-operation', 'sessionId': SID, 'operation': 'enqueue'}, rows[-1])
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual('intervening_turn', result['reason'])
        self.assertEqual('not_dispatched', result['delivery']['state'])
        self.assertNotIn('/compact', self.sent)
        self.assertEqual(1, sum(message.startswith('COMPACTION CANCELLED:') for message in self.sent))

    def test_codex_root_start_without_user_message_cancels_compact(self):
        self.rows(*self.codex_idle_rows('before'))
        record = self.idle_record('codex')
        record['action'] = 'compact'
        self.rows(self.codex_idle_rows('after')[0])
        result = self.native_idle_result(record)
        self.assertEqual(1, result['turns_seen'])

    def test_generated_user_rows_do_not_count_as_operator_turns(self):
        self.rows(*self.claude_idle_rows('before'))
        record = self.idle_record()
        record['action'] = 'compact'
        self.rows(self.claude_row('user', 'meta', 'before-d', isMeta=True,
                                  message={'content': 'system reminder'}))
        self.assertEqual(0, self.native_idle_result(record)['turns_seen'])
        self.transcript.write_text('')
        self.rows(*self.codex_idle_rows('before'))
        record = self.idle_record('codex')
        record['action'] = 'compact'
        self.rows({'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                  'content': [{'type': 'input_text', 'text': '<environment_context>generated</environment_context>'}]}})
        self.assertEqual(0, self.native_idle_result(record)['turns_seen'])

    def test_cancellation_during_idle_wait_cannot_restore_waiting_state(self):
        oid = self.request(timeout_seconds=30)
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record['state'] = 'waiting_idle'
        h._write(path, record)
        def cancel_then_report_turn(*args):
            self.control.cancel(oid)
            return {'state': 'busy_or_unknown', 'turns_seen': 1}
        self.native_idle.side_effect = cancel_then_report_turn
        result = h._wait_idle(record, self.identity, time.monotonic() + 30, operation_path=path)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual('cancelled', h._read(path)['state'])

    def test_cancellation_before_sender_reservation_prevents_dispatch(self):
        oid = self.request(timeout_seconds=30)
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record['state'] = 'waiting_idle'
        h._write(path, record)
        self.control.cancel(oid)
        self.assertIsNone(h._reserve_compact_dispatch(path, record, command=True))
        self.assertEqual('cancelled', h._read(path)['state'])

    def test_cancellation_before_failure_notice_sends_nothing(self):
        oid = self.request(timeout_seconds=30)
        def cancel_during_wait(*args, **kwargs):
            self.control.cancel(oid)
            return {'state': 'deferred', 'reason': 'native_idle_not_observed_within_bound'}
        with patch.object(h, '_wait_idle', side_effect=cancel_during_wait):
            result = self.observe(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual([], self.sent)
        self.assertIsNone(result.get('failure_notice'))

    def test_failure_notice_exception_restores_terminal_state(self):
        oid = self.request(timeout_seconds=30)
        with patch.object(h, '_wait_idle', return_value={'state': 'deferred', 'reason': 'idle_record_shape_unknown'}), \
             patch.object(h, '_send', side_effect=RuntimeError('transport failed')):
            result = self.observe(oid)
        self.assertEqual('deferred', result['state'])
        self.assertIsNotNone(result.get('failure_notice'))
        self.assertEqual('ambiguous', result['failure_notice']['state'])
        self.assertTrue(result['failure_notice']['needs_review'])

    def test_interrupted_failure_notice_is_settled_on_read(self):
        oid = self.request(timeout_seconds=30)
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='warning_dispatching', pending_final_state='deferred',
                      failure_notice={'state': 'dispatching'})
        h._write(path, record)
        result = self.control.operation(oid)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('ambiguous', result['failure_notice']['state'])
        self.assertTrue(result['failure_notice']['needs_review'])

    def test_final_notice_receipt_wins_reconciler_race(self):
        oid = self.request(timeout_seconds=30)
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='warning_dispatching', pending_final_state='deferred',
                      failure_notice={'state': 'dispatching'})
        h._write(path, record)
        real_flock = h.fcntl.flock
        def finish_before_lease(fd, mode):
            if mode == (h.fcntl.LOCK_EX | h.fcntl.LOCK_NB):
                final = h._read(path)
                final['failure_notice'] = {'state': 'delivered'}
                final['state'] = final.pop('pending_final_state')
                h._write(path, final)
            return real_flock(fd, mode)
        with patch.object(h.fcntl, 'flock', side_effect=finish_before_lease):
            result = self.control.operation(oid)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('delivered', result['failure_notice']['state'])

    def test_focus_waits_for_new_completed_turn(self):
        oid = self.request(focus='focus')
        calls = []
        def idle(record, after=None):
            calls.append(after)
            if after is None:
                return {'state': 'idle'}
            return {'state': 'busy_or_unknown'}
        self.native_idle.side_effect = idle
        result = self.observe(oid)
        self.assertEqual('focus', self.sent[0])
        self.assertEqual(1, sum(message.startswith('COMPACTION NOT DISPATCHED:') for message in self.sent))
        self.assertEqual('deferred', result['state'])
        self.assertEqual('native_idle_not_observed_within_bound', result['reason'])
        self.assertTrue(any(value is not None for value in calls))

    def test_idle_rechecked_before_focus_transport(self):
        oid = self.request(focus='focus')
        self.native_idle.side_effect = lambda *args: {'state': 'idle' if self.native_idle.call_count == 1 else 'busy_or_unknown'}
        result = self.observe(oid)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('native_idle_changed_before_focus', result['focus_delivery'].get('reason'))
        self.assertEqual(1, len(self.sent))
        self.assertTrue(self.sent[0].startswith('COMPACTION NOT DISPATCHED:'))

    def test_queue_activity_supersedes_original_turn_without_dispatch(self):
        for operation in ('enqueue', 'dequeue', 'remove', 'unknown'):
            with self.subTest(operation=operation):
                rows = self.claude_idle_rows(operation)
                self.rows(*rows[:-1])
                oid = self.request('exit')
                self.rows({'type': 'queue-operation', 'operation': operation, 'sessionId': SID}, rows[-1])
                self.native_idle.side_effect = self.real_native_idle
                result = self.observe(oid, alive=False)
                self.assertEqual('deferred', result['state'])
                self.assertEqual('superseded_by_new_input', result.get('reason'))
                self.assertEqual([], self.sent)

    def test_queued_command_attachment_supersedes_without_queue_row(self):
        self.rows(self.claude_row('user', 'u', message={'content': 'original'}),
                  self.claude_row('assistant', 'tool', 'u', message={'content': [
                      {'type': 'tool_use', 'id': 'call', 'name': 'Bash'}], 'stop_reason': 'tool_use'}))
        oid = self.request('exit')
        self.rows(self.claude_row('attachment', 'queued', 'tool', attachment={
                      'type': 'queued_command', 'prompt': 'new obligation', 'humanTurn': True}),
                  self.claude_row('assistant', 'answer', 'queued', message={'content': [
                      {'type': 'text', 'text': 'acknowledged'}], 'stop_reason': 'end_turn'}),
                  self.claude_row('system', 'duration', 'answer', subtype='turn_duration', durationMs=12, messageCount=3))
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid, alive=False)
        self.assertEqual('superseded_by_new_input', result.get('reason'))
        self.assertEqual('deferred', result['state'])
        self.assertEqual([], self.sent)

    def test_new_input_before_focus_rearms_then_waits_for_focus_completion(self):
        self.rows(*self.claude_idle_rows())
        oid = self.request(focus='focus')
        injected = False
        def idle(record, after=None):
            nonlocal injected
            result = self.real_native_idle(record, after)
            if not injected:
                self.rows(*self.claude_idle_rows('new', 'wait'))
                injected = True
            return result
        self.native_idle.side_effect = idle
        result = self.observe(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual('intervening_turn', result['reason'])
        self.assertIsNotNone(result['focus_delivery'])
        self.assertEqual('deferred', result['focus_delivery']['state'])
        self.assertNotIn('focus', self.sent)
        self.assertNotIn('/compact', self.sent)
        self.assertEqual(1, sum(message.startswith('COMPACTION CANCELLED:') for message in self.sent))

    def test_idle_rechecked_before_lifecycle_transport(self):
        oid = self.request('exit')
        self.native_idle.side_effect = [{'state': 'idle'}, {'state': 'busy_or_unknown'}]
        result = self.observe(oid, alive=False)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('native_idle_changed_before_dispatch', result['delivery'].get('reason'))
        self.assertEqual([], self.sent)

    def test_continuation_preflight_has_separate_budget(self):
        oid = self.request()
        def verify(*args):
            if len(self.sent) == 1:
                self.clock += 1.1
        self.session_verify.side_effect = verify
        def send(args):
            if len(self.sent) == 1:
                self.event()
            return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
        result = self.observe(oid, send)
        self.assertEqual('completed', result['state'])
        self.assertEqual('delivered', result['continuation']['state'])
        self.assertEqual(2, len(self.sent))

    def test_default_operation_budget_leaves_idle_wait(self):
        oid = self.request()
        record = h._read(self.control.directory / (oid + '.json'))
        self.assertEqual(3600, record['deadline'] - record['created_at'])
        self.assertEqual(3600, record['idle_bound_seconds'])
        self.assertEqual(12345, record['watcher_pid'])
        self.assertEqual('scheduled', record['state'])

    def test_request_minimum_budget_is_synchronous(self):
        for action, kwargs, minimum in (('send', {'text': 'hello'}, 120), ('compact', {}, 30), ('compact', {'focus': 'focus'}, 30)):
            with self.subTest(action=action, kwargs=kwargs), self.assertRaisesRegex(h.ControlError, f'timeout_must_be_{minimum}'):
                self.request(action, timeout_seconds=minimum - 1, **kwargs)
        self.spawn.assert_not_called()
        self.assertFalse((self.control.directory / 'active.json').exists())

    def test_exact_minimum_allows_idle_and_dispatch_after_queue_overhead(self):
        for action, kwargs, minimum in (('exit', {}, 120), ('compact', {'focus': 'focus'}, 30)):
            oid = self.request(action, timeout_seconds=minimum, **kwargs)
            path = self.control.directory / (oid + '.json')
            record = h._read(path)
            now = record['created_at'] + 1
            self.native_idle.return_value = {'state': 'idle'}
            with patch.object(h, 'time', SimpleNamespace(time=lambda: now, monotonic=lambda: now, sleep=time.sleep)):
                result = h._wait_idle(record, self.identity, record['deadline'], sends=2 if kwargs else 1)
            self.assertEqual('idle', result['state'])
            self.control.cancel(oid)

    def test_focus_pair_rearms_idle_bound_after_focus(self):
        oid = self.request(focus='focus')
        deadlines = []
        def wait(*args, **kwargs):
            deadlines.append(args[2])
            self.clock += 2
            return {'state': 'idle'}
        with patch.object(h, '_wait_idle', side_effect=wait):
            result = self.observe(oid)
        self.assertEqual(2, len(deadlines))
        self.assertGreater(deadlines[1], deadlines[0])
        self.assertEqual(['focus', '/compact'], self.sent[:2])
        self.assertEqual(1, sum(message.startswith('COMPACTION UNCONFIRMED:') for message in self.sent))

    def test_typed_limits_and_ordinary_meta_prefixes(self):
        for value in ('/model x ', '/model x\u3000', '/model x;', '/model ' + 'a' * 194):
            with self.subTest(value=value), self.assertRaises(h.ControlError):
                self.request('send', text=value)
        for value in ('!echo hello', '#memory', '\ufeff/exit', '\u200b!echo hello', '\ufeff#instruction'):
            for key in ('focus', 'continuation'):
                with self.subTest(value=value, key=key), self.assertRaises(h.ControlError):
                    self.request(**{key: value})
        h._message('!echo hello')  # broad raw policy remains explicitly authorized
        h._message('#memory')

    def test_interrupted_receipt_preserves_input_and_pending_path(self):
        for attempted, expected in ((False, 'deferred'), (True, 'ambiguous')):
            oid = self.request('send', text='hello')
            record = h._read(self.control.directory / (oid + '.json'))
            receipt = {'status': expected, 'input_attempted': attempted, 'pending_file': '/private/pending', 'reason': 'signal-15'}
            with patch.object(h, '_transport_run', return_value=subprocess.CompletedProcess([], 143, '', json.dumps(receipt))):
                result = h._send(self.control.directory, record, self.identity, 'hello', '.signal')
            self.assertEqual(expected, result['state'])
            self.assertEqual(attempted, result['input_attempted'])
            self.assertEqual('/private/pending', result['pending_file'])
            self.control.cancel(oid)
        record['session_id'] = None
        self.session_verify.side_effect = TypeError('fixture')
        self.assertEqual('not_dispatched', h._send(self.control.directory, record, self.identity, 'hello', '.bad')['state'])

    def test_sender_unclosed_descendant_pipes_are_bounded(self):
        process = Mock(pid=12345)
        process.communicate.side_effect = subprocess.TimeoutExpired('sender', 1)
        with patch.object(h.subprocess, 'Popen', return_value=process), patch.object(h.os, 'killpg') as killpg:
            with self.assertRaisesRegex(h.ControlError, 'sender_pipes'):
                h._transport_run(['sender'], self.identity)
        self.assertEqual([h.SEND_TIMEOUT, h.SEND_GRACE, h.SEND_DRAIN], [call.kwargs.get('timeout') for call in process.communicate.call_args_list])
        self.assertEqual([h.signal.SIGTERM, h.signal.SIGKILL], [call.args[1] for call in killpg.call_args_list])
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

    def test_known_passive_metadata_preserves_observed_idle(self):
        self.transcript.write_text('')
        record = self.idle_record()
        self.rows(*self.claude_idle_rows())
        for kind, field in (('mode', 'mode'), ('permission-mode', 'permissionMode'), ('atis-latch', 'atis'), ('ai-title', 'aiTitle'), ('last-prompt', 'lastPrompt')):
            self.rows({'type': kind, 'sessionId': SID, field: 'fixture'})
        record['idle_baseline'] = h._baseline(self.transcript)
        self.assertEqual('idle', self.native_idle_result(record)['state'])
        self.transcript.write_text('')
        record = self.idle_record('codex')
        self.rows(*self.codex_idle_rows(), {'type': 'world_state', 'payload': {'full': True, 'state': {}}})
        record['idle_baseline'] = h._baseline(self.transcript)
        self.assertEqual('idle', self.native_idle_result(record)['state'])

    def test_same_count_requires_new_native_progress_and_transcript(self):
        self.marker_count = 1
        for watched, started, event, expected in ((False, False, True, 'unconfirmed'), (True, False, True, 'unconfirmed'), (True, True, False, 'unconfirmed'), (True, True, True, 'completed')):
            oid = self.request()
            self.watch.side_effect = lambda *args: nullcontext({'available': watched, 'progress_started_at': self.clock if started else None, 'progress_armed': True, 'samples': 0})
            def send(args):
                if len(self.sent) == 1 and event:
                    self.event()
                    self.marker_count = 1  # redraw replaced the old success marker
                return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
            result = self.observe(oid, send)
            self.assertEqual(expected, result['state'])
            if expected == 'completed':
                self.assertEqual('native_progress_then_completed_marker', result['completion']['witness']['pane_marker']['method'])
                self.assertEqual(2, len(self.sent))
            else:
                self.assertEqual('not_dispatched', result['continuation']['state'])
                self.assertEqual(1, sum(message == '/compact' for message in self.sent))
                self.assertEqual(1, sum(message.startswith('COMPACTION UNCONFIRMED:') for message in self.sent))
            self.sent.clear()

    def test_progress_must_end_before_same_count_completion(self):
        oid = self.request()
        self.watch.side_effect = lambda *args: nullcontext({'available': True, 'progress_started_at': self.clock, 'progress_armed': True, 'samples': 0})
        def marker(*args, **kwargs):
            return {'count': 1, 'progress': bool(self.sent), 'observed_at': self.clock}
        def send(args):
            self.event()
            self.clock += h.SEND_BUDGET + h.PREFLIGHT_BUDGET + h.COMPACT_WATCH + 2
            return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
        with patch.object(h, '_pane_marker', side_effect=marker):
            result = self.observe(oid, send)
        self.assertEqual('unconfirmed', result['state'])
        self.assertEqual('unconfirmed', result['completion']['state'])
        self.assertEqual('not_dispatched', result['continuation']['state'])

    def test_sampler_shutdown_is_bounded_and_stall_has_no_authority(self):
        thread = Mock()
        thread.is_alive.return_value = True
        with patch.object(h.threading, 'Thread', return_value=thread):
            with self.real_watch(self.identity, {'progress': False}) as result:
                pass
        self.assertEqual(h.SAMPLE_JOIN, thread.join.call_args.kwargs.get('timeout'))
        self.assertFalse(result['available'])

    def test_sampler_requires_new_progress_transition_not_baseline_progress(self):
        observed = threading.Event()
        def marker(*args, **kwargs):
            observed.set()
            return {'progress': True, 'count': 1, 'observed_at': 123}
        for initial, expected in ((True, None), (False, 123)):
            observed.clear()
            with patch.object(h, '_pane_marker', side_effect=marker):
                with self.real_watch(self.identity, {'progress': initial}) as result:
                    self.assertTrue(observed.wait(1))
                    deadline = time.monotonic() + 1
                    while result['samples'] == 0 and time.monotonic() < deadline:
                        time.sleep(.001)
                    self.assertGreater(result['samples'], 0)
            self.assertTrue(result['available'])
            self.assertEqual(expected, result['progress_started_at'])

    def test_sampler_progress_is_native_line_shape(self):
        for line, expected in (('✢ Compacting conversation… (0s)', True),
                               ('* Compacting conversation… (4s · ↓ 286 tokens)', True),
                               ('assistant said Compacting conversation… (0s)', False),
                               ('✢ Compacting conversation... (0s)', False)):
            with patch.object(h.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, line, '')):
                marker = h._pane_marker(self.identity)
            self.assertEqual(expected, marker['progress'])
            self.assertNotIn(line, json.dumps(marker))

    def test_claude_current_compaction_row_is_counted(self):
        for line, expected in (('  ⎿  Compacted', 1),
                               ('  ⎿  Compacted (ctrl+o to see full summary)', 1),
                               ('assistant said Compacted', 0)):
            with patch.object(h.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, line, '')):
                marker = h._pane_marker(self.identity)
            self.assertEqual(expected, marker['count'])

    def test_new_input_supersedes_without_dispatch(self):
        self.rows(*self.claude_idle_rows())
        oid = self.request('exit')
        self.rows(*self.claude_idle_rows('human', 'wait, do not exit'))
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid, alive=False)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('superseded_by_new_input', result['reason'])
        self.assertEqual('not_dispatched', result['delivery']['state'])
        self.assertEqual([], self.sent)

    def test_current_tool_result_can_finish_original_calling_turn(self):
        self.rows(self.claude_row('user', 'u', message={'content': 'original task'}),
                  self.claude_row('assistant', 'tool', 'u', message={'stop_reason': 'tool_use',
                      'content': [{'type': 'tool_use', 'id': 'call', 'name': 'Bash'}]}))
        record = self.idle_record()
        self.rows(self.claude_row('user', 'result', 'tool', message={'content': [
                      {'type': 'tool_result', 'tool_use_id': 'call', 'content': 'done'}]}),
                  self.claude_row('assistant', 'answer', 'result', message={'stop_reason': 'end_turn',
                      'content': [{'type': 'text', 'text': 'finished'}]}),
                  self.claude_row('system', 'duration', 'answer', subtype='turn_duration', durationMs=12, messageCount=4))
        self.assertEqual('idle', self.native_idle_result(record)['state'])

    def test_nontext_user_input_supersedes_without_dispatch(self):
        for content in ([{'type': 'image', 'source': {'type': 'base64', 'data': 'fixture'}}],
                        [{'type': 'document'}], [], None,
                        [{'type': 'tool_result'}, {'type': 'image'}]):
            with self.subTest(content=content):
                self.rows(*self.claude_idle_rows())
                oid = self.request('exit')
                rows = self.claude_idle_rows('human', 'new input')
                rows[0]['message']['content'] = content
                self.rows(*rows)
                self.native_idle.side_effect = self.real_native_idle
                result = self.observe(oid, alive=False)
                self.assertEqual('deferred', result['state'])
                self.assertEqual('superseded_by_new_input', result['reason'])
                self.assertEqual([], self.sent)

    def test_cancel_leased_waiting_observer_blocks_replacement_until_release(self):
        oid = self.request('exit')
        entered, release = threading.Event(), threading.Event()
        errors = []
        def idle(*args):
            entered.set()
            if not release.wait(3):
                return {'state': 'unknown'}
            return {'state': 'idle'}
        def observe():
            try:
                h.observe(self.control.directory, oid)
            except Exception as exc:
                errors.append(exc)
        self.native_idle.side_effect = idle
        with patch.object(h, '_send') as send:
            thread = threading.Thread(target=observe)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual('waiting_idle', self.control.operation(oid)['state'])
                self.assertEqual('cancelled', self.control.cancel(oid)['state'])
                with self.assertRaisesRegex(h.ControlError, 'observer_still_running'):
                    self.request('send', text='replacement')
                self.assertEqual(oid, h._read(self.control.directory / 'active.json')['operation_id'])
            finally:
                release.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual([], errors)
            send.assert_not_called()
        self.assertEqual('cancelled', self.control.operation(oid)['state'])
        self.request('send', text='replacement')

    def test_current_idle_evidence_reason_is_preserved(self):
        oid = self.request('exit')
        self.native_idle.side_effect = h.ControlError('idle_record_shape_unknown')
        result = self.observe(oid)
        self.assertEqual('idle_record_shape_unknown', result['idle'].get('evidence_reason'))
        self.assertEqual([], self.sent)

    def test_compaction_reserves_observation_time_before_input(self):
        oid = self.request()
        record = h._read(self.control.directory / (oid + '.json'))
        record['deadline'] = time.time() + h.SEND_BUDGET + h.COMPACT_WATCH - 1
        with patch.object(h, '_transport_run', return_value=subprocess.CompletedProcess([], 0, '{}', '')) as send:
            result = h._send(self.control.directory, record, self.identity, '/compact', '.low-watch')
        self.assertEqual('deferred', result['state'])
        send.assert_not_called()

    def test_focus_whitespace_and_raw_bom_lifecycle_are_refused(self):
        for text in (' focus', 'focus\n', '\nfocus', 'focus '):
            with self.subTest(text=text), self.assertRaisesRegex(h.ControlError, 'focus_surrounding'):
                self.request(focus=text)
        for text in ('\ufeff/exit', '\u200b/compa', '/e\ufeffxi', '\ufeff/QUIT arg'):
            with self.subTest(text=text), self.assertRaises(h.ControlError):
                self.request('send', text=text)
        h._message('Notes\n# Heading\n!literal prose', ordinary=True)
        h._message('CONTINUE: checkpoint\n# Next step', ordinary=True)
        h._message('/mpa')  # fuzzy matching remains unverified, not invented policy

    def test_transport_tracks_checkout_and_utf8(self):
        root = Path(os.environ.get('AGENT_SKILLS_ROOT', Path.home() / '.claude/skills')).resolve()
        self.assertEqual((root / 'spawn-agent/scripts/tmux-message.sh').resolve(), h.TRANSPORT)
        self.assertTrue(h.TRANSPORT.is_file())
        oid = self.request('send', text='a café')
        record = h._read(self.control.directory / (oid + '.json'))
        real_fdopen = os.fdopen
        encodings = []
        def fdopen(fd, mode, **kwargs):
            if mode == 'w':
                encodings.append(kwargs.get('encoding'))
            return real_fdopen(fd, mode, **kwargs)
        with patch.object(h.os, 'fdopen', side_effect=fdopen), patch.object(h, '_transport_run', return_value=subprocess.CompletedProcess([], 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')):
            result = h._send(self.control.directory, record, self.identity, 'a café', '.utf8')
        self.assertEqual('delivered', result['state'])
        self.assertEqual(['utf-8'], encodings)
        self.assertEqual('a café'.encode('utf-8'), (self.control.directory / (oid + '.utf8')).read_bytes())

    def test_tree_is_not_a_committed_checkpoint(self):
        self.shard.write_text('staged only')
        self.git('add', 'handoff.md')
        tree = self.git('write-tree').strip()
        with self.assertRaisesRegex(h.ControlError, 'exact_commit_required'):
            self.control.record_checkpoint({**self.evidence, 'commit': tree,
                'sha256': hashlib.sha256(self.shard.read_bytes()).hexdigest()})

    def test_sender_budget_and_pretransport_errors(self):
        oid = self.request('send', text='hello')
        record = h._read(self.control.directory / (oid + '.json'))
        record['deadline'] = time.time() + h.SEND_BUDGET - 1
        with patch.object(h, '_transport_run', return_value=subprocess.CompletedProcess([], 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')) as transport:
            result = h._send(self.control.directory, record, self.identity, 'hello', '.short')
            self.assertEqual('deferred', result['state'])
            self.assertEqual('insufficient_sender_budget', result['reason'])
            transport.assert_not_called()
        self.assertFalse((self.control.directory / (oid + '.short')).exists())
        record['deadline'] = time.time() + h.SEND_BUDGET + 1
        with patch.object(h, '_transport_run', return_value=subprocess.CompletedProcess([], 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')) as transport, patch.object(h.os, 'open', side_effect=OSError('fixture')):
            result = h._send(self.control.directory, record, self.identity, 'hello', '.failed')
            self.assertEqual('not_dispatched', result['state'])
            transport.assert_not_called()
        with patch.object(h, '_transport_run', return_value=subprocess.CompletedProcess([], 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')) as transport, patch.object(h, 'time', SimpleNamespace(time=Mock(side_effect=[record['deadline'] - h.SEND_BUDGET - 1, record['deadline'] - 1]), monotonic=time.monotonic, sleep=time.sleep)):
            result = h._send(self.control.directory, record, self.identity, 'hello', '.slow_file')
            self.assertEqual('deferred', result['state'])
            transport.assert_not_called()

    def test_sender_start_failure_has_no_dispatch(self):
        oid = self.request('send', text='hello')
        record = h._read(self.control.directory / (oid + '.json'))
        with patch.object(h.subprocess, 'Popen', side_effect=OSError('fixture')):
            result = h._send(self.control.directory, record, self.identity, 'hello', '.nostart')
        self.assertEqual('not_dispatched', result['state'])
        self.assertEqual('sender_start_failed', result['reason'])

    def test_sender_explicit_bounds_and_graceful_timeout(self):
        oid = self.request('send', text='hello')
        self.observe(oid)
        command = self.commands[0]
        for option, value in (('--max-wait', '5'), ('--stable-wait', '3'), ('--render-wait', '3'), ('--submit-delay', '8'), ('--receipt-wait', '15'), ('--retry-wait', '3'), ('--poll-interval', '0.25')):
            self.assertIn(option, command)
            self.assertEqual(value, command[command.index(option) + 1])
        option = lambda name: float(command[command.index(name) + 1])
        worst = 5 + 2 * option('--max-wait') + 30 + option('--render-wait') + option('--submit-delay') + option('--receipt-wait') + 20 + option('--poll-interval')
        self.assertGreaterEqual(h.SEND_TIMEOUT, worst)
        self.assertEqual(h.SEND_BUDGET, h.SEND_TIMEOUT + h.SEND_GRACE + h.SEND_DRAIN)
        for stuck in (False, True):
            process = Mock(returncode=143, pid=12345)
            responses = [subprocess.TimeoutExpired('sender', h.SEND_TIMEOUT)]
            if stuck:
                responses.append(subprocess.TimeoutExpired('sender', h.SEND_GRACE))
            responses.append(('', 'interrupted'))
            process.communicate.side_effect = responses
            with patch.object(h.subprocess, 'Popen', return_value=process) as spawn, patch.object(h.os, 'killpg') as killpg:
                result = h._transport_run(['sender'], self.identity)
            self.assertEqual('interrupted', result.stderr)
            self.assertEqual([h.signal.SIGTERM] + ([h.signal.SIGKILL] if stuck else []), [call.args[1] for call in killpg.call_args_list])
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual('utf-8', spawn.call_args.kwargs['encoding'])
            self.assertEqual('strict', spawn.call_args.kwargs['errors'])
            calls = [call[0] for call in process.method_calls]
            self.assertEqual(['communicate', 'communicate'] + (['communicate'] if stuck else []), calls)
            if stuck:
                self.assertEqual(h.SEND_DRAIN, process.communicate.call_args_list[2].kwargs.get('timeout'))
            self.assertEqual(h.SEND_TIMEOUT, process.communicate.call_args_list[0].kwargs['timeout'])
            self.assertEqual(h.SEND_GRACE, process.communicate.call_args_list[1].kwargs['timeout'])

    def test_final_observation_after_sender_crosses_deadline(self):
        oid = self.request()
        def send(args):
            if len(self.sent) == 1:
                self.event()
                self.clock += h.SEND_BUDGET + h.PREFLIGHT_BUDGET + h.COMPACT_WATCH + 2
            return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
        result = self.observe(oid, send)
        self.assertEqual('completed', result['state'])
        self.assertEqual('confirmed', result['completion']['state'])
        self.assertEqual(2, len(self.sent))

    def test_invalid_pane_encoding_preserves_transcript_witness(self):
        oid = self.request()
        def send(args):
            self.event()
            return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
        original = h._pane_marker
        def marker(identity):
            if self.sent:
                with patch.object(h.subprocess, 'run', side_effect=UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'fixture')):
                    return original(identity)
            return original(identity)
        with patch.object(h, '_pane_marker', side_effect=marker):
            result = self.observe(oid, send)
        self.assertEqual('unconfirmed', result['state'])
        self.assertEqual('unconfirmed', result['completion']['state'])
        self.assertEqual('not_dispatched', result['continuation']['state'])

    def test_pane_marker_classifies_invalid_encoding(self):
        failure = UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'fixture')
        with patch.object(h.subprocess, 'run', side_effect=failure):
            try:
                h._pane_marker(self.identity)
            except Exception as caught:
                self.assertIsInstance(caught, h.ControlError)
                self.assertEqual('pane_compaction_marker_unavailable', str(caught))
                self.assertIs(caught.__cause__, failure)
            else:
                self.fail('pane marker accepted invalid UTF-8')

    def test_reaper_settles_abandoned_dispatch_intents(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='continuing', deadline=0, completion={'state': 'confirmed', 'witness': {'source': 'fixture'}})
        for key in ('delivery', 'focus_delivery', 'continuation'):
            record[key] = {'state': 'dispatching'}
        h._write(path, record)
        result = self.control.operation(oid)
        self.assertEqual('continuation_failed', result['state'])
        self.assertEqual('confirmed', result['completion']['state'])
        for key in ('delivery', 'focus_delivery', 'continuation'):
            self.assertEqual('ambiguous', result[key]['state'])

    def test_receipt_explicit_evidence(self):
        result = self.control.record_checkpoint(self.evidence)
        self.assertIn('shard_bytes_in_exact_commit', result['verified'])
        self.assertIn('remote_privacy', result['attested_not_verified'])
        self.assertEqual(0o600, (self.control.directory / ('checkpoint-' + result['receipt_id'] + '.json')).stat().st_mode & 0o777)
        for key in ('private_storage_attested', 'obligations_preserved', 'pause_state_preserved', 'active_inventory_reference', 'pause_state_reference', 'authority', 'resources_disposition'):
            bad = dict(self.evidence)
            bad.pop(key)
            with self.subTest(key=key), self.assertRaises(h.ControlError):
                self.control.record_checkpoint(bad)

    def test_hash_commit_and_remote_gate(self):
        for update in ({'sha256': '0' * 64}, {'commit': '0' * 40}, {'push_attestation': 'pushed_private_remote'}):
            with self.subTest(update=update), self.assertRaises(h.ControlError):
                self.control.record_checkpoint({**self.evidence, **update})
        self.shard.write_text('uncommitted\n')
        with self.assertRaisesRegex(h.ControlError, 'shard_not_in_commit'):
            self.control.record_checkpoint({**self.evidence, 'sha256': hashlib.sha256(self.shard.read_bytes()).hexdigest()})
        self.shard.write_text('private checkpoint\n')
        self.git('remote', 'add', 'origin', 'https://example.invalid/private.git')
        with self.assertRaises(h.ControlError):
            h.verify_checkpoint(self.evidence)

    def test_remote_presence_requires_fetched_origin_master(self):
        remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', 'origin', 'HEAD:master')
        self.shard.write_text('new local-only checkpoint\n')
        self.git('add', 'handoff.md')
        self.git('commit', '-qm', 'local-only shard')
        evidence = {**self.evidence, 'sha256': hashlib.sha256(self.shard.read_bytes()).hexdigest(),
                    'commit': self.git('rev-parse', 'HEAD').strip(),
                    'push_attestation': 'pushed_private_remote'}
        with self.assertRaisesRegex(h.ControlError, 'shard_not_on_origin_master'):
            h.verify_checkpoint(evidence)
        self.git('push', 'origin', 'HEAD:master')
        self.assertIn('remote_presence', h.verify_checkpoint(evidence)['verified'])

    def test_remote_presence_rejects_stale_tracking_ref_and_changed_bytes(self):
        remote = self.root / 'remote.git'
        racer = self.root / 'racer'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', 'origin', 'HEAD:master')
        evidence = {**self.evidence, 'push_attestation': 'pushed_private_remote'}
        self.assertIn('remote_presence', h.verify_checkpoint(evidence)['verified'])
        subprocess.run(['git', 'clone', str(remote), str(racer)], check=True, capture_output=True)
        self.git('config', '--replace-all', 'remote.origin.fetch',
                 '+refs/heads/other:refs/remotes/origin/other')
        (racer / 'handoff.md').write_text('different remote bytes\n')
        subprocess.run(['git', '-C', str(racer), 'add', 'handoff.md'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(racer), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'change shard'],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(racer), 'push', 'origin', 'HEAD:master'],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(h.ControlError, 'shard_not_on_origin_master'):
            h.verify_checkpoint(evidence)

    def test_exit_requires_receipt_and_unchanged_shard(self):
        with self.assertRaises(h.ControlError):
            self.control.request('exit')
        self.shard.write_text('changed')
        with self.assertRaises(h.ControlError):
            self.request('exit')
        self.spawn.assert_not_called()

    def test_compact_allows_active_but_exit_refuses(self):
        self.receipt = self.control.record_checkpoint({**self.evidence, 'resources_disposition': 'active_recorded', 'authority': 'compact_authorized'})['receipt_id']
        with self.assertRaisesRegex(h.ControlError, 'exit_authority'):
            self.request('exit')
        oid = self.request()
        self.assertEqual('scheduled', self.control.operation(oid)['state'])

    def test_prompt_return_serialization_cancellation(self):
        oid = self.request()
        self.assertEqual('scheduled', self.control.operation(oid)['state'])
        self.assertTrue(self.spawn.call_args.kwargs['start_new_session'])
        self.assertTrue(self.spawn.call_args.kwargs['close_fds'])
        with self.assertRaisesRegex(h.ControlError, 'operation_in_progress'):
            self.request('send', text='hello')
        self.control.cancel(oid)
        result = self.observe(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual([], self.sent)
        self.request('send', text='hello')

    def test_no_cancel_after_dispatch(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        row = h._read(path)
        row['state'] = 'dispatching'
        h._write(path, row)
        self.assertEqual('refused', self.control.cancel(oid)['state'])
        with self.assertRaisesRegex(h.OperationInProgress, f'operation_in_progress:{oid}:dispatching; get_operation'):
            self.request('send', text='next')

    def test_incident_warning_can_be_cancelled_and_replaced(self):
        incident = json.loads((MODULE.parent / 'fixtures/compact-stale-cancel.json').read_text())
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update({key: value for key, value in incident.items() if key != 'operation_id'})
        h._write(path, record)
        lease = os.open(self.control.directory / '.worker', os.O_RDWR)
        try:
            h.fcntl.flock(lease, h.fcntl.LOCK_EX)
            with self.assertRaisesRegex(h.OperationInProgress, f'operation_in_progress:{oid}:warning_dispatching; cancel_operation'):
                self.request('send', text='next')
            cancelled = self.control.cancel(oid)
            self.assertEqual('cancelled', cancelled['state'])
            self.assertEqual('explicit_cancel', cancelled['reason'])
            self.assertEqual('not_dispatched', cancelled['delivery']['state'])
        finally:
            os.close(lease)
        self.assertEqual('cancelled', self.control.operation(oid)['state'])
        self.request('send', text='next')

    def test_incident_warning_without_observer_settles_and_releases_session(self):
        incident = json.loads((MODULE.parent / 'fixtures/compact-stale-cancel.json').read_text())
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update({key: value for key, value in incident.items() if key != 'operation_id'})
        h._write(path, record)
        settled = self.control.operation(oid)
        self.assertEqual('cancelled', settled['state'])
        self.assertEqual('intervening_turn', settled['reason'])
        self.assertIsInstance(settled.get('failure_notice'), dict)
        self.assertEqual('unavailable', settled['failure_notice']['state'])
        self.assertEqual('cancelled', self.control.cancel(oid)['state'])
        self.request('send', text='next')

    def test_watching_other_can_be_cancelled_before_dispatch(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='watching_other', reason='intervening_turn',
                      completion={'state': 'not_started'})
        h._write(path, record)
        lease = os.open(self.control.directory / '.worker', os.O_RDWR)
        try:
            h.fcntl.flock(lease, h.fcntl.LOCK_EX)
            self.assertEqual('cancelled', self.control.cancel(oid)['state'])
        finally:
            os.close(lease)
        self.request('send', text='next')

    def test_explicit_cancel_during_notice_preserves_reason_and_notice_receipt(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='warning_dispatching', pending_final_state='cancelled',
                      reason='intervening_turn', turns_seen=1,
                      completion={'state': 'not_started'})
        h._write(path, record)
        def send(*_args):
            self.assertEqual('cancelled', self.control.cancel(oid)['state'])
            return {'state': 'delivered', 'receipt': 'queued'}
        lease = os.open(self.control.directory / '.worker', os.O_RDWR)
        try:
            h.fcntl.flock(lease, h.fcntl.LOCK_EX)
            with patch.object(h, '_send', side_effect=send):
                h._failure_notice(self.control.directory, path, record, self.identity)
        finally:
            os.close(lease)
        settled = self.control.operation(oid)
        self.assertEqual('cancelled', settled['state'])
        self.assertEqual('explicit_cancel', settled['reason'])
        self.assertEqual('delivered', settled['failure_notice']['state'])
        self.assertEqual('cancelled', self.control.cancel(oid)['state'])
        self.request('send', text='next')

    def test_explicit_cancel_before_notice_intent_is_not_overwritten(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='warning_dispatching', pending_final_state='cancelled',
                      reason='intervening_turn', turns_seen=1,
                      completion={'state': 'not_started'})
        h._write(path, record)
        lease = os.open(self.control.directory / '.worker', os.O_RDWR)
        try:
            h.fcntl.flock(lease, h.fcntl.LOCK_EX)
            self.assertEqual('cancelled', self.control.cancel(oid)['state'])
            with patch.object(h, '_send', return_value={'state': 'delivered', 'receipt': 'queued'}) as send:
                h._failure_notice(self.control.directory, path, record, self.identity)
            send.assert_not_called()
        finally:
            os.close(lease)
        settled = self.control.operation(oid)
        self.assertEqual('cancelled', settled['state'])
        self.assertEqual('explicit_cancel', settled['reason'])
        self.request('send', text='next')

    def test_cancelled_operation_with_lost_observer_marks_notice_unavailable(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='cancelled', reason='intervening_turn',
                      completion={'state': 'not_started'})
        h._write(path, record)
        result = self.control.operation(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertIsInstance(result.get('failure_notice'), dict)
        self.assertEqual('unavailable', result['failure_notice']['state'])
        self.assertEqual('observer_disappeared_before_notice', result['failure_notice']['reason'])
        self.request('send', text='next')

    def test_cancelled_operation_with_lost_observer_marks_notice_ambiguous(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        record = h._read(path)
        record.update(state='cancelled', reason='explicit_cancel',
                      completion={'state': 'cancelled'},
                      failure_notice={'state': 'dispatching'})
        h._write(path, record)
        result = self.control.operation(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual('explicit_cancel', result['reason'])
        self.assertEqual('ambiguous', result['failure_notice']['state'])
        self.assertTrue(result['failure_notice']['needs_review'])
        self.request('send', text='next')

    def test_aliases_and_other_commands(self):
        for text in ('/compact', '/compa', '/c', '/COM arg', '/exi', '/e', '/qui', '/qu reason', '/exit reason', ' \n /QUIT', '/q', 'hello\n/exit', '/ｅｘｉｔ', 'hello\r/exit', '\x1bexit'):
            with self.subTest(text=text), self.assertRaises(h.ControlError):
                self.request('send', text=text)
            # A broken guard may accept the request. Dispose that fixture-only
            # operation so later subtests do not fail through serialization.
            active = self.control.directory / 'active.json'
            if active.exists():
                self.control.cancel(h._read(active)['operation_id'])
        self.request('send', text='/status')

    def test_delivered_compact_without_confirmation_is_unconfirmed_and_not_retried(self):
        oid = self.request()
        result = self.observe(oid)
        self.assertEqual('delivered', result['delivery']['state'])
        self.assertEqual('queued', result['delivery']['receipt'])
        self.assertEqual('unconfirmed', result['state'])
        self.assertEqual('unconfirmed', result['completion']['state'])
        self.assertEqual(['/compact'], self.sent[:1])
        self.assertEqual(1, sum(message == '/compact' for message in self.sent))
        self.assertEqual(1, sum(message.startswith('COMPACTION UNCONFIRMED:') for message in self.sent))
        self.assertEqual('not_dispatched', result['continuation']['state'])

    def test_delivered_compact_with_unreadable_completion_evidence_is_unconfirmed(self):
        oid = self.request()
        def send(args):
            if self.sent[-1] == '/compact':
                with self.transcript.open('a') as stream:
                    stream.write('invalid\n')
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'queued', 'pane': '%999'}), '')
        result = self.observe(oid, send)
        self.assertEqual('unconfirmed', result['state'])
        self.assertEqual('queued', result['delivery']['receipt'])
        self.assertEqual('not_dispatched', result['continuation']['state'])
        self.assertEqual(1, sum(message.startswith('COMPACTION UNCONFIRMED:') for message in self.sent))

    def test_intervening_turn_with_compaction_event_continues_by_other(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        self.rows(*self.claude_idle_rows('after'))
        self.event()
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid)
        self.assertEqual('completed_by_other', result['state'])
        self.assertTrue(result['completion']['by_other'])
        self.assertEqual('delivered', result['continuation']['state'])
        self.assertEqual(0, sum(message.startswith('COMPACTION CANCELLED:') for message in self.sent))
        self.assertEqual(1, sum(message.startswith('CONTINUE:') for message in self.sent))
        self.assertNotIn('/compact', self.sent)

    def test_compaction_event_after_cancellation_notice_does_not_reopen_cancel(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        self.rows(*self.claude_idle_rows('after'))
        self.native_idle.side_effect = self.real_native_idle
        def send(args):
            if self.sent[-1].startswith('COMPACTION CANCELLED:'):
                self.event()
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'queued', 'pane': '%999'}), '')
        result = self.observe(oid, send)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual('delivered', result['failure_notice']['state'])
        self.assertEqual(0, sum(message.startswith('CONTINUE:') for message in self.sent))
        self.assertNotIn('/compact', self.sent)
        self.request('send', text='next')

    def test_intervening_cancel_reaches_terminal_after_notice(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        self.rows(*self.claude_idle_rows('after'))
        self.native_idle.side_effect = self.real_native_idle
        def send(args):
            if self.sent[-1].startswith('COMPACTION CANCELLED:'):
                self.assertEqual('cancelled', self.control.operation(oid)['state'])
                with self.assertRaisesRegex(h.ControlError, 'observer_still_running'):
                    self.request('send', text='next')
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'queued', 'pane': '%999'}), '')
        result = self.observe(oid, send)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual('delivered', result['failure_notice']['state'])
        states = [row['state'] for row in h._read(self.control.directory / (oid + '.json'))['transitions']]
        self.assertNotIn('watching_other', states)
        self.assertNotIn('warning_dispatching', states)
        self.request('send', text='hello')

    def test_explicit_cancel_wins_over_intervening_turn_and_peer_event(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        self.rows(*self.claude_idle_rows('after'))
        self.event()
        self.native_idle.side_effect = self.real_native_idle
        def wait(*args, **kwargs):
            self.control.cancel(oid)
            return {'state': 'cancelled', 'reason': 'intervening_turn', 'turns_seen': 1}
        with patch.object(h, '_wait_idle', side_effect=wait):
            result = self.observe(oid)
        self.assertEqual('cancelled', result['state'])
        self.assertEqual([], self.sent)

    def test_peer_compaction_event_before_dispatch_continues_by_other(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        self.event()
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid)
        self.assertEqual('completed_by_other', result['state'])
        self.assertTrue(result['completion']['by_other'])
        self.assertEqual('delivered', result['continuation']['state'])
        self.assertEqual(1, sum(message.startswith('CONTINUE:') for message in self.sent))
        self.assertNotIn('/compact', self.sent)

    def test_codex_peer_compaction_event_is_detected(self):
        self.rows(*self.codex_idle_rows('before'))
        record = self.idle_record('codex')
        record['action'] = 'compact'
        record['baseline'] = h._baseline(self.transcript)
        self.event('codex')
        codex_identity = h.Identity(**{**self.identity.public(), 'harness': 'codex'})
        with patch.object(h, '_native_idle', side_effect=self.real_native_idle):
            result = h._wait_idle(record, codex_identity, time.monotonic() + 30)
        self.assertEqual('completed_by_other', result['state'])
        self.assertEqual('compacted', result['witness']['event'])

    def test_focus_compaction_event_prevents_second_compact(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(focus='focus')
        def send(args):
            if self.sent[-1] == 'focus':
                self.event()
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'queued', 'pane': '%999'}), '')
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid, send)
        self.assertEqual('completed_by_other', result['state'])
        self.assertEqual('delivered', result['focus_delivery']['state'])
        self.assertNotIn('/compact', self.sent)
        self.assertEqual(1, sum(message.startswith('CONTINUE:') for message in self.sent))

    def test_focus_supersession_with_peer_compaction_continues_by_other(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(focus='focus')
        def send(args):
            if self.sent[-1] == 'focus':
                self.rows(self.claude_row('user', 'after-u', 'before-d', message={'content': 'new work'}))
                self.event()
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'queued', 'pane': '%999'}), '')
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid, send)
        self.assertEqual('completed_by_other', result['state'])
        self.assertEqual('confirmed', result['completion']['state'])
        self.assertEqual('delivered', result['continuation']['state'])
        self.assertNotIn('/compact', self.sent)
        self.assertFalse(any(message.startswith('COMPACTION CANCELLED:') for message in self.sent))

    def test_real_claude_boundary_and_summary_are_not_operator_turns(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        self.rows(self.claude_row('system', 'boundary', subtype='compact_boundary',
                                  compactMetadata={'trigger': 'manual'}),
                  self.claude_row('user', 'summary', 'boundary', isCompactSummary=True,
                                  message={'content': 'generated summary'}))
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid)
        self.assertEqual('completed_by_other', result['state'])
        self.assertEqual(0, sum(message.startswith('COMPACTION CANCELLED:') for message in self.sent))
        self.assertEqual(1, sum(message.startswith('CONTINUE:') for message in self.sent))

    def test_peer_boundary_between_idle_and_send_continues_by_other(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        injected = False
        def idle(record, after=None):
            nonlocal injected
            if not injected:
                self.rows(self.claude_row('system', 'boundary', subtype='compact_boundary'))
                injected = True
            return self.real_native_idle(record, after)
        self.native_idle.side_effect = idle
        with patch.object(h, '_wait_idle', return_value={'state': 'idle'}):
            result = self.observe(oid)
        self.assertEqual('completed_by_other', result['state'])
        self.assertEqual('compacted_by_other', result['delivery']['reason'])
        self.assertNotIn('/compact', self.sent)
        self.assertEqual(1, sum(message.startswith('CONTINUE:') for message in self.sent))

    def test_peer_boundary_and_turn_between_idle_and_send_continues_by_other(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        injected = False
        def idle(record, after=None):
            nonlocal injected
            if not injected:
                self.rows(*self.claude_idle_rows('after'))
                self.event()
                injected = True
            return self.real_native_idle(record, after)
        self.native_idle.side_effect = idle
        with patch.object(h, '_wait_idle', return_value={'state': 'idle'}):
            result = self.observe(oid)
        self.assertEqual('completed_by_other', result['state'])
        self.assertEqual('compacted_by_other', result['delivery']['reason'])
        self.assertEqual('delivered', result['continuation']['state'])
        self.assertNotIn('/compact', self.sent)
        self.assertFalse(any(message.startswith('COMPACTION CANCELLED:') for message in self.sent))

    def test_peer_boundary_on_send_parser_error_continues_by_other(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request(timeout_seconds=30)
        def idle(*args):
            self.rows(self.claude_row('system', 'boundary', subtype='compact_boundary'))
            raise h.ControlError('idle_record_shape_unknown')
        self.native_idle.side_effect = idle
        with patch.object(h, '_wait_idle', return_value={'state': 'idle'}):
            result = self.observe(oid)
        self.assertEqual('completed_by_other', result['state'])
        self.assertEqual('compacted_by_other', result['delivery']['reason'])
        self.assertNotIn('/compact', self.sent)
        self.assertEqual(1, sum(message.startswith('CONTINUE:') for message in self.sent))

    def test_new_claude_event_confirms(self):
        oid = self.request()
        def send(args):
            self.event()
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'command', 'pane': '%999'}), '')
        result = self.observe(oid, send)
        self.assertEqual('completed', result['state'])
        self.assertEqual('compact_boundary', result['completion']['witness']['event'])
        self.assertEqual('refused', self.control.cancel(oid)['state'])
        h.observe(self.control.directory, oid)
        self.assertEqual(['/compact', 'CONTINUE: compaction done; resume from ' + str(self.shard)], self.sent)
        self.assertEqual('delivered', result['continuation']['state'])
        self.assertIn('--typed-command', self.commands[0])
        self.assertNotIn('--typed-command', self.commands[1])

    def test_continuation_path_and_failed_receipt_never_retried(self):
        with self.assertRaisesRegex(h.ControlError, 'checkpoint_path_mismatch'):
            self.request(checkpoint_path='/wrong')
        with self.assertRaisesRegex(h.ControlError, 'continuation_only_for_compact'):
            self.request('exit', continuation='continue')
        oid = self.request(checkpoint_path=str(self.shard), continuation='Keep the pause in force.')
        def send(args):
            if self.sent[-1] == '/compact':
                self.event()
                return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'command', 'pane': '%999'}), '')
            return subprocess.CompletedProcess(args, 2, '', json.dumps({'status': 'deferred', 'paste_attempted': False, 'input_attempted': False, 'reason': 'existing-input'}))
        result = self.observe(oid, send)
        self.assertEqual('continuation_failed', result['state'])
        self.assertEqual('confirmed', result['completion']['state'])
        self.assertEqual('deferred', result['continuation']['state'])
        self.assertEqual('CONTINUE: compaction done; resume from ' + str(self.shard) + '\nKeep the pause in force.', self.sent[-1])
        h.observe(self.control.directory, oid)
        self.assertEqual(2, len(self.sent))

    def test_new_transcript_without_new_ui_marker_never_continues(self):
        self.marker_enabled = False
        oid = self.request()
        def send(args):
            self.event()
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'command', 'pane': '%999'}), '')
        result = self.observe(oid, send)
        self.assertEqual('unconfirmed', result['state'])
        self.assertEqual('unconfirmed', result['completion']['state'])
        self.assertEqual('not_dispatched', result['continuation']['state'])
        self.assertEqual(['/compact'], self.sent[:1])
        self.assertEqual(1, sum(message.startswith('COMPACTION UNCONFIRMED:') for message in self.sent))
        self.assertEqual('transcript_compacted_but_new_pane_marker_not_observed', result['reason'])

    def test_session_switch_before_dispatch_and_continuation(self):
        oid = self.request()
        self.session_verify.side_effect = h.ControlError('changed')
        result = self.observe(oid)
        self.assertEqual('failed', result['state'])
        self.assertEqual([], self.sent)
        self.session_verify.side_effect = None
        oid = self.request()
        def send(args):
            self.event()
            self.session_verify.side_effect = h.ControlError('changed')
            return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'command', 'pane': '%999'}), '')
        result = self.observe(oid, send)
        self.assertEqual('continuation_failed', result['state'])
        self.assertEqual('not_dispatched', result['continuation']['state'])
        self.assertEqual('confirmed', result['completion']['state'])
        self.assertEqual(['/compact'], self.sent)

    def test_live_session_binding_checks_exact_process_and_session(self):
        pointer = self.root / ('current.' + str(self.identity.pid))
        pointer.write_text(SID + ' 123 boot')
        with patch('session_binding.same_process', return_value=True), patch('session_binding._has_pinned_codex_home', return_value=True):
            self.real_verify_session(self.identity, SID, self.root)
            for value in (SID + ' 999 boot', SID + ' 123 other', SID + ' extra 123 boot', 'other 123 boot'):
                pointer.write_text(value)
                with self.assertRaises(h.ControlError):
                    self.real_verify_session(self.identity, SID, self.root)
            identity = h.Identity(**{**self.identity.public(), 'harness': 'codex'})
            with patch('codex_status.read_codex_status', return_value={'state': 'observed', 'session_id': SID}):
                self.real_verify_session(identity, SID)
            with patch('codex_status.read_codex_status', return_value={'state': 'observed', 'session_id': '22222222-2222-2222-2222-222222222222'}):
                with self.assertRaises(h.ControlError):
                    self.real_verify_session(identity, SID)

    def test_historical_event_not_completion(self):
        self.event()
        oid = self.request()
        result = self.observe(oid)
        self.assertEqual('unconfirmed', result['state'])

    def test_wrong_session_and_event_shapes_ignored(self):
        baseline = h._baseline(self.transcript)
        self.event(sessionId='other')
        self.event(type='assistant')
        self.assertIsNone(h._compact_event(self.transcript, baseline, 'claude', SID))
        self.transcript.write_text('')
        baseline = h._baseline(self.transcript)
        self.event('codex', type='event_msg', payload={'type': 'context_compacted'})
        self.assertIsNone(h._compact_event(self.transcript, baseline, 'codex', SID))
        self.event('codex')
        self.assertEqual('compacted', h._compact_event(self.transcript, baseline, 'codex', SID)['event'])

    def test_truncation_replacement_partial_and_malformed(self):
        self.transcript.write_text('{"type":"system"')
        baseline = h._baseline(self.transcript)
        with self.transcript.open('a') as f:
            f.write(',"subtype":"compact_boundary","sessionId":"' + SID + '"}\n')
        try:
            result = h._compact_event(self.transcript, baseline, 'claude', SID)
        except h.ControlError as exc:
            self.fail('An incomplete baseline fragment must be skipped: ' + str(exc))
        self.assertIsNone(result)
        self.transcript.write_text('')
        try:
            with self.assertRaises(h.ControlError):
                h._compact_event(self.transcript, baseline, 'claude', SID)
        except ValueError as exc:
            self.fail('Truncation must produce the typed control error: ' + str(exc))
        baseline = h._baseline(self.transcript)
        replacement = self.root / 'replacement'
        replacement.write_text('{}\n')
        replacement.replace(self.transcript)
        with self.assertRaises(h.ControlError):
            h._compact_event(self.transcript, baseline, 'claude', SID)
        baseline = h._baseline(self.transcript)
        with self.transcript.open('a') as f:
            f.write('invalid\n')
        with self.assertRaises(h.ControlError):
            h._compact_event(self.transcript, baseline, 'claude', SID)

    def test_exit_process_witness_and_unknown(self):
        oid = self.request('exit')
        result = self.observe(oid, alive=False)
        self.assertEqual('completed', result['state'])
        self.assertEqual('123', result['completion']['witness']['starttime'])
        oid = self.request('exit')
        result = self.observe(oid, alive=True)
        self.assertEqual('timed_out', result['state'])
        oid = self.request('exit')
        def unknown(_):
            raise h.IdentityError('unreadable')
        result = self.observe(oid, alive=unknown)
        self.assertEqual('unknown', result['completion']['state'])
        self.assertNotEqual('completed', result['state'])

    def test_exit_defers_on_new_native_compaction_boundary(self):
        self.rows(*self.claude_idle_rows('before'))
        oid = self.request('exit')
        self.rows(self.claude_row('system', 'boundary', subtype='compact_boundary'))
        self.native_idle.side_effect = self.real_native_idle
        result = self.observe(oid, alive=False)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('native_compaction_boundary', result['reason'])
        self.assertEqual([], self.sent)

    def test_deferred_stderr_and_ambiguous_never_replayed(self):
        oid = self.request()
        def deferred(args):
            if self.sent[-1].startswith('COMPACTION NOT DISPATCHED:'):
                return subprocess.CompletedProcess(args, 0, json.dumps({'status': 'delivered', 'receipt': 'queued', 'pane': '%999'}), '')
            return subprocess.CompletedProcess(args, 2, '', json.dumps({'status': 'deferred', 'paste_attempted': False, 'input_attempted': False, 'reason': 'existing-input'}))
        result = self.observe(oid, deferred)
        self.assertEqual('deferred', result['state'])
        self.assertEqual('not_started', result['completion']['state'])
        self.assertIsNotNone(result.get('failure_notice'))
        self.assertEqual('delivered', result['failure_notice']['state'])
        self.assertEqual(1, sum(message.startswith('COMPACTION NOT DISPATCHED:') for message in self.sent))
        self.sent.clear()
        oid = self.request()
        def ambiguous(args):
            return subprocess.CompletedProcess(args, 3, '', json.dumps({'status': 'ambiguous', 'paste_attempted': True, 'pending_file': '/private/pending'}))
        result = self.observe(oid, ambiguous)
        self.assertEqual('ambiguous', result['delivery']['state'])
        self.assertEqual('/private/pending', result['delivery']['pending_file'])
        self.assertEqual(['/compact'], self.sent)
        self.assertIsNone(result['failure_notice'])

    def test_plain_exit_zero_and_wrong_pane_not_delivery(self):
        for response in ({'status': 'delivered', 'receipt': 'queued', 'pane': '%1'}, {'status': 'delivered'}):
            oid = self.request('send', text='hello')
            result = self.observe(oid, lambda args: subprocess.CompletedProcess(args, 0, json.dumps(response), ''))
            self.assertEqual('ambiguous', result['state'])

    def test_focus_sent_first_and_failure_stops(self):
        oid = self.request(focus='Preserve checkpoint obligations.')
        def send(args):
            if len(self.sent) == 1:
                record = h._read(self.control.directory / (oid + '.json'))
                self.assertEqual('dispatching', record.get('focus_delivery', {}).get('state'))
            return subprocess.CompletedProcess(args, 0, '{"status":"delivered","receipt":"queued","pane":"%999"}', '')
        self.observe(oid, send)
        self.assertEqual(['Preserve checkpoint obligations.', '/compact'], self.sent[:2])
        self.assertEqual(1, sum(message.startswith('COMPACTION UNCONFIRMED:') for message in self.sent))
        self.sent.clear()
        oid = self.request(focus='focus')
        result = self.observe(oid, lambda args: subprocess.CompletedProcess(args, 2, '', json.dumps({'status': 'deferred', 'paste_attempted': False, 'input_attempted': False})))
        self.assertEqual('focus', self.sent[0])
        self.assertEqual(1, sum(message.startswith('COMPACTION NOT DISPATCHED:') for message in self.sent))
        self.assertEqual('focus_not_delivered', result['reason'])
        self.assertEqual('not_dispatched', result['delivery']['state'])

    def test_identity_rechecked_and_socket_pinned(self):
        with patch.dict(os.environ, {'SPAWN_TMUX_LABEL': 'wrong', 'SPAWN_TMUX_SOCKET': '/wrong'}):
            env = h._environment(self.identity)
        self.assertEqual('/fixture/socket', env['SPAWN_TMUX_SOCKET'])
        self.assertNotIn('SPAWN_TMUX_LABEL', env)
        oid = self.request()
        self.verify.side_effect = h.IdentityError('replaced')
        result = self.observe(oid)
        self.assertEqual('failed', result['state'])
        self.assertEqual([], self.sent)

    def test_receipt_session_scope_and_permissions(self):
        other = h.HarnessControl(self.identity, '22345678-1234-1234-1234-123456789abc', self.transcript, self.root / 'state')
        with self.assertRaises(OSError):
            other.request('exit', self.receipt)
        self.assertEqual(0o700, self.control.directory.stat().st_mode & 0o777)
        unsafe = self.root / 'unsafe'
        unsafe.mkdir(mode=0o755)
        with self.assertRaises(h.ControlError):
            h.HarnessControl(self.identity, SID, self.transcript, unsafe)
        draft = self.root / 'draft'
        draft.write_text('human unfinished text')
        symlink = self.control.directory / 'symlink.json'
        symlink.symlink_to(draft)
        with self.assertRaises(OSError):
            h._read(symlink)

    def test_cwd_change_cannot_bypass_serialization(self):
        self.request()
        changed = h.Identity(**{**self.identity.public(), 'cwd': '/different'})
        other = h.HarnessControl(changed, SID, self.transcript, self.root / 'state')
        with self.assertRaisesRegex(h.ControlError, 'operation_in_progress'):
            other.request('send', text='hello')

    def test_read_own_pane_is_untrusted_and_not_persisted(self):
        before = set(self.control.directory.iterdir())
        with patch.object(h.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'unfinished draft', '')) as run:
            result = self.control.read_own_pane()
        self.assertEqual('observed', result['state'])
        self.assertEqual('unfinished draft', result['pane_text'])
        self.assertTrue(result['read_only'])
        self.assertTrue(result['untrusted'])
        self.assertEqual(before, set(self.control.directory.iterdir()))
        self.assertEqual([str(h.TRANSPORT), 'read', '%999'], run.call_args.args[0])

    def test_worker_revalidates_changed_checkpoint(self):
        oid = self.request('exit')
        self.shard.write_text('changed after acceptance')
        result = self.observe(oid, alive=False)
        self.assertEqual('failed', result['state'])
        self.assertEqual([], self.sent)

    def test_lease_blocks_dispatch_after_operation_deadline(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        row = h._read(path)
        row.update(deadline=0, state='dispatching')
        h._write(path, row)
        fd = os.open(self.control.directory / '.worker', os.O_RDWR)
        try:
            h.fcntl.flock(fd, h.fcntl.LOCK_EX | h.fcntl.LOCK_NB)
            self.assertEqual('dispatching', self.control.operation(oid)['state'])
            with self.assertRaisesRegex(h.ControlError, 'operation_in_progress'):
                self.request('send', text='hello')
        finally:
            os.close(fd)
        self.request('send', text='hello')

    def test_cancelled_observer_cannot_strand_new_operation(self):
        old = self.request('send', text='obsolete')
        self.control.cancel(old)
        current = self.request('send', text='current')
        old_progress = threading.Event()
        release_old = threading.Event()
        errors = []
        original_flock = h.fcntl.flock

        def flock(fd, operation):
            original_flock(fd, operation)
            if (threading.current_thread().name == 'obsolete-observer'
                    and operation == h.fcntl.LOCK_EX | h.fcntl.LOCK_NB
                    and Path(os.readlink(f'/proc/self/fd/{fd}')).name == '.worker'):
                # Reproduce the old ordering deterministically: pause A after
                # its worker lease, run B, and only then let A inspect cancellation.
                old_progress.set()
                if not release_old.wait(5):
                    raise RuntimeError('obsolete observer was not released')

        def run(operation_id):
            try:
                h.observe(self.control.directory, operation_id)
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                if operation_id == old:
                    old_progress.set()  # fixed A returns without taking a lease

        obsolete = threading.Thread(target=run, args=(old,), name='obsolete-observer')
        replacement = threading.Thread(target=run, args=(current,), name='current-observer')
        with patch.object(h.fcntl, 'flock', side_effect=flock), patch.object(h, '_send', return_value={'state': 'delivered', 'receipt': 'queued'}) as send:
            try:
                obsolete.start()
                self.assertTrue(old_progress.wait(5), 'obsolete observer did not reach the controlled point')
                replacement.start()
                replacement.join(5)
                self.assertFalse(replacement.is_alive(), 'replacement observer blocked')
            finally:
                release_old.set()
                obsolete.join(5)
                if replacement.ident is not None:
                    replacement.join(5)
            self.assertFalse(obsolete.is_alive(), 'obsolete observer leaked')
            self.assertEqual([], errors, 'observer raised instead of settling its operation')
            self.assertEqual('delivered', self.control.operation(current)['state'],
                             'obsolete observer stranded the newly accepted operation')
            self.assertEqual('cancelled', self.control.operation(old)['state'])
            self.assertEqual(['current'], [call.args[3] for call in send.call_args_list])

    def test_expired_pending_recovered_without_dispatch(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        row = h._read(path)
        row['deadline'] = 0
        h._write(path, row)
        self.assertEqual('timed_out', self.control.operation(oid)['state'])
        h.observe(self.control.directory, oid)
        self.assertEqual([], self.sent)
        self.request('send', text='hello')

    def test_expired_delivered_compact_keeps_receipt_and_becomes_unconfirmed(self):
        oid = self.request()
        path = self.control.directory / (oid + '.json')
        row = h._read(path)
        row.update(state='observing', deadline=0,
                   delivery={'state': 'delivered', 'receipt': 'queued', 'delivered_at': self.clock})
        h._write(path, row)
        result = self.control.operation(oid)
        self.assertEqual('unconfirmed', result['state'])
        self.assertEqual('queued', result['delivery']['receipt'])
        self.assertEqual('unavailable', result['failure_notice']['state'])
        self.assertEqual([], self.sent)


def live_integration():
    """Real private tmux + real detached worker + public transport, stand-in TUI."""
    if not shutil.which('tmux'):
        raise RuntimeError('tmux required for --live-integration')
    with tempfile.TemporaryDirectory(prefix='harness-control-live-') as temporary:
        root = Path(temporary)
        socket = root / 'tmux.sock'
        tmux = ['tmux', '-S', str(socket), '-f', '/dev/null']
        repo = root / 'repo'
        repo.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()
        git('init', '-q')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        shard = repo / 'handoff.md'
        shard.write_text('fixture private checkpoint\n')
        git('add', 'handoff.md')
        git('commit', '-qm', 'fixture')
        transcript = root / 'transcript.jsonl'
        transcript.write_text('')
        fixture = Path(__file__).with_name('fixtures') / 'harness-control-terminal.py'
        try:
            command = 'exec ' + shlex.join([sys.executable, str(fixture), str(root)])
            pane = subprocess.check_output(
                tmux + ['new-session', '-d', '-P', '-F', '#{pane_id}', '-x', '90', '-y', '24', command],
                text=True,
                timeout=10,
            ).strip()
            ready = root / 'terminal.json'
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            assert ready.exists(), 'stand-in terminal did not become ready within 5 seconds'
            from harness_identity import discover
            identity = discover(json.loads(ready.read_text())['pid'])
            assert identity.pane == pane and identity.socket == str(socket)
            # The private observer copy uses the same installed/staged transport.
            copied = root / 'harness_control.py'
            shutil.copyfile(MODULE, copied)
            shutil.copyfile(MODULE.with_name('_skills_native.py'), root / '_skills_native.py')
            shutil.copyfile(MODULE.with_name('harness_identity.py'), root / 'harness_identity.py')
            shutil.copyfile(MODULE.with_name('session_binding.py'), root / 'session_binding.py')
            shutil.copyfile(MODULE.with_name('codex_status.py'), root / 'codex_status.py')
            live_spec = importlib.util.spec_from_file_location('live_control', copied)
            live = importlib.util.module_from_spec(live_spec)
            live_spec.loader.exec_module(live)
            pointers = root / 'claude-state'
            pointers.mkdir()
            (pointers / f'current.{identity.pid}').write_text(f'{SID} {identity.starttime} {identity.boot_id}')
            control = live.HarnessControl(identity, SID, transcript, root / 'receipts', claude_state_dir=pointers)
            receipt = control.record_checkpoint({'shard_path': str(shard), 'repo_path': str(repo),
                'sha256': hashlib.sha256(shard.read_bytes()).hexdigest(), 'commit': git('rev-parse', 'HEAD'),
                'private_storage_attested': True, 'push_attestation': 'no_remote_configured',
                'authority': 'exit_authorized', 'resources_disposition': 'released',
                'obligations_preserved': True, 'pause_state_preserved': True,
                'pause_state_reference': 'handoff.md', 'active_inventory_reference': 'handoff.md'})['receipt_id']
            for action in ('compact', 'exit'):
                before = time.monotonic()
                operation = control.request(action, receipt, timeout_seconds=300)
                assert time.monotonic() - before < 2, 'request blocked for delivery'
                assert operation['state'] == ('scheduled' if action == 'compact' else 'accepted')
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    result = control.operation(operation['operation_id'])
                    if result['state'] in h.TERMINAL:
                        break
                    time.sleep(.1)
                assert result['state'] == 'completed', result
                assert result['completion']['state'] == 'confirmed', result
                if action == 'compact':
                    assert result['completion']['witness']['pane_marker']['method'] == 'native_progress_then_completed_marker', result
                assert result['delivery']['state'] == 'delivered', result
                assert Path(result['result_path']).is_file()
                print('PASS: detached', action, 'receipt and independent completion witness', flush=True)
            terminal = json.loads(ready.read_text())
            assert terminal['accepted'] == ['/compact', 'CONTINUE: compaction done; resume from ' + str(shard), '/exit'], terminal
            assert terminal['pastes'] == 1, terminal
            assert terminal['compacted_at'] < terminal['continuation_at'], terminal
            assert not h.same_process(identity)
            print('PASS: real private tmux, typed lifecycle, delayed event+marker before one pasted continuation, durable result after exit')
        finally:
            subprocess.run(tmux + ['kill-server'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def mutations():
    baseline_env = dict(os.environ)
    baseline_env.pop('HARNESS_CONTROL_TEST_MODULE', None)
    baseline = REAL_RUN([sys.executable, __file__], env=baseline_env, capture_output=True, text=True, timeout=60)
    if baseline.returncode != 0:
        raise AssertionError('Baseline failed before mutation checks:\n' + baseline.stdout + baseline.stderr)
    print('PASS: baseline', flush=True)
    source = MODULE.read_text()
    atomic_claim = """        with _guard(directory):
            record = _read(path)
            if record['state'] not in ('accepted', 'scheduled') or _read(directory / 'active.json')['operation_id'] != operation_id:
                return
            fd = os.open(directory / '.worker', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            record.update(state='waiting_idle', updated_at=time.time())
            _write(path, record)  # lease claimed; cancellation remains safe before input
"""
    obsolete_lease_first = """        fd = os.open(directory / '.worker', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with _guard(directory):
            record = _read(path)
            if record['state'] not in ('accepted', 'scheduled'):
                return
            record.update(state='waiting_idle', updated_at=time.time())
            _write(path, record)  # lease claimed; cancellation remains safe before input
"""
    cases = [
        ('queued_attachment', "row['attachment'].get('type') == 'queued_command'", 'False'),
        ('queue_supersession', "if kind == 'queue-operation' and offset >= baseline['offset']:", 'if False:'),
        ('focus_idle_recheck', "if suffix == '.focus' or text in ('/compact', '/exit'):", 'if False:'),
        ('focus_original_generation', "record.get('focus_after') if suffix != '.focus' else None", "record.get('focus_after')"),
        ('nontext_supersession', "user_input = not (isinstance(content, list) and bool(content) and\n                                      all(isinstance(c, dict) and c.get('type') == 'tool_result' for c in content))", "user_input = isinstance(content, str) or (isinstance(content, list) and any(isinstance(c, dict) and c.get('type') == 'text' for c in content))"),
        ('waiting_cancel', "('accepted', 'scheduled', 'waiting_idle',\n                                      'warning_dispatching', 'watching_other') or", "('accepted', 'scheduled',\n                                      'warning_dispatching', 'watching_other') or"),
        ('cancel_preserved', "if _read(path)['state'] != 'cancelled':", 'if True:'),
        ('historical_leniency', "if start > baseline['offset']:", 'if True:'),
        ('incremental_cursor', "fresh = not cursor or cursor['key'] != key", 'fresh = True'),
        ('superseding_claude', "if (kind == 'user' and user_input and row.get('isMeta') is not True and\n                            row.get('isCompactSummary') is not True and offset >= baseline['offset']):", 'if False:'),
        ('superseding_codex', "if offset >= baseline['offset']:", 'if False:'),
        ('focus_whitespace', 'if focus != focus.strip():', 'if False:'),
        ('raw_zero_width', "if unicodedata.category(c) != 'Cf'", 'if True', 2),
        ('watch_reserve', " + (COMPACT_WATCH if text == '/compact' else 0)", '', 2),
        ('progress_ended', " and marker.get('progress') is False", ''),
        ('sampler_join_bound', 'thread.join(timeout=SAMPLE_JOIN)', 'thread.join()'),
        ('progress_required', "record['pane_sampling'].get('progress_started_at') is not None", 'True'),
        ('progress_baseline', "'progress_armed': not baseline.get('progress', False)", "'progress_armed': True"),
        ('progress_parser', "bool(_CLAUDE_COMPACTING.search(plain))", 'False'),
        ('idle_partial_tail', "incomplete = bool(lines and not lines[-1].endswith(b'\\n'))", 'incomplete = False'),
        ('minimum_request_budget', "minimum = 30 if action == 'compact' else SEND_BUDGET + PREFLIGHT_BUDGET + 5", "minimum = 0 if action == 'compact' else SEND_BUDGET + PREFLIGHT_BUDGET + 5"),
        ('focus_pair_rearm', "if record['action'] == 'compact':\n                record['deadline'] = time.time() + record['idle_bound_seconds']\n                observer_deadline = time.monotonic() + record['idle_bound_seconds']\n                _write(path, record)", "if record['action'] == 'compact':\n                record['deadline'] = time.time() + record['idle_bound_seconds']\n                observer_deadline = time.monotonic()\n                _write(path, record)"),
        ('typed_request_limit', "if slash_lines and (len(text.encode('utf-8')) > 200 or text != text.rstrip() or text.endswith(';')):", 'if False:'),
        ('ordinary_meta_prefix', "if ordinary and (normalized.startswith('/') or (index == 0 and normalized.startswith(('!', '#')))):", 'if False:'),
        ('input_attempted_receipt', "result.get('input_attempted') is False", "result.get('paste_attempted') is False"),
        ('final_drain_bound', 'process.communicate(timeout=SEND_DRAIN)', 'process.communicate()'),
        ('default_idle_budget', "timeout_seconds = 3600 if action == 'compact' else 300", "timeout_seconds = 300"),
        ('compact_idle_bound', "reserve = 0 if record.get('action') == 'compact' else sends * (SEND_BUDGET + PREFLIGHT_BUDGET)", "reserve = sends * (SEND_BUDGET + PREFLIGHT_BUDGET)"),
        ('root_complete_without_start', "if (turn is None and offset >= baseline['offset'] and", "if (False and offset >= baseline['offset'] and"),
        ('new_codex_turn_cancellation', '                                turns_seen += 1\n', '                                turns_seen += 0\n'),
        ('new_claude_turn_cancellation', '                            user_turns_seen += 1\n', '                            user_turns_seen += 0\n'),
        ('supersession_peer_event', "                if other_event:\n                    return {'state': 'completed_by_other', 'witness': other_event}\n            if str(exc)", "                if False:\n                    return {'state': 'completed_by_other', 'witness': other_event}\n            if str(exc)"),
        ('claude_api_metadata', "if kind in ('api-request-shape', 'api-request-blob', 'api-request'):", 'if False:'),
        ('claude_current_marker', 'len(_CLAUDE_COMPACT_ROW.findall(plain))', '0'),
        ('continuation_preflight', 'deadline=time.time() + SEND_BUDGET + PREFLIGHT_BUDGET,', 'deadline=time.time() + SEND_BUDGET + 1,', 2),
        ('idle_dispatch', "if idle['state'] != 'idle':", 'if False:'),
        ('idle_wait', "if last['state'] == 'idle':", 'if True:'),
        ('idle_codex_match', "candidate == turn and focus_seen", 'focus_seen'),
        ('idle_claude_parent', "linked = parent is not None and row.get('parentUuid') == parent", 'linked = True'),
        ('idle_focus_generation', ' or not focus_turn_seen', ''),
        ('idle_focus_text', ' or not exact', '', 2),
        ('idle_thinking', "isinstance(content, list) and any(isinstance(c, dict) and c.get('type') == 'text' for c in content))", 'True)'),
        ('sender_location', "TRANSPORT = spawn_transport_path()", "TRANSPORT = Path.home() / '.claude/skills/spawn-agent/scripts/tmux-message.sh'"),
        ('commit_object', "if _git(repo, 'cat-file', '-t', commit).strip() != b'commit':", 'if False:'),
        ('sender_budget', "if record['deadline'] - time.time() < SEND_BUDGET + (COMPACT_WATCH if text == '/compact' else 0):", 'if False:', 2),
        ('sender_start', "except _SenderNotStarted:\n        return {'state': 'not_dispatched'", "except _SenderNotStarted:\n        return {'state': 'ambiguous'"),
        ('sender_grace', 'os.killpg(process.pid, signal.SIGTERM)', 'os.killpg(process.pid, signal.SIGKILL)'),
        ('focus_intent', "            record['focus_delivery'] = {'state': 'dispatching'}", '            pass'),
        ('terminal_dispatch', "if record.get(key, {}).get('state') == 'dispatching':", 'if False:'),
        ('final_observation', 'while True:  # Include one final observation even if dispatch crossed the deadline.', "if time.monotonic() >= observer_deadline:\n                record.update(state='timed_out', completion={'state': 'unknown'})\n                return\n            while True:"),
        ('pane_unicode', 'subprocess.SubprocessError, KeyError, UnicodeError)', 'subprocess.SubprocessError, KeyError)'),
        ('payload_utf8', "with os.fdopen(fd, 'w', encoding='utf-8') as stream:", "with os.fdopen(fd, 'w') as stream:", 2),
        ('hash', 'if actual != digest:', 'if False:'),
        ('commit', "if hashlib.sha256(_git(repo, 'show', f'{commit}:{relative.as_posix()}')).hexdigest() != digest:", 'if False:'),
        ('checkpoint', "            checkpoint = self._checkpoint(checkpoint_receipt, action)", "            checkpoint = {'evidence': {'shard_path': '/wrong'}}"),
        ('alias', "if ((ordinary and normalized.startswith('/')) or lifecycle):", "if (ordinary and normalized.startswith('/')):"),
        ('alias_prefix', "lifecycle = (normalized.startswith('/') and any(name.startswith(normalized.split()[0][1:])\n                     for name in ('compact', 'exit', 'quit', 'q')))", "lifecycle = re.match(r'^/(?:compact|exit|quit|q)(?:\\s|$)', normalized)"),
        ('serialization', "if prior['state'] not in TERMINAL:", 'if False:'),
        ('old_event', "'offset': end,", "'offset': 0,"),
        ('wrong_session', "row.get('sessionId') == session_id and row.get('isSidechain') is not True", "row.get('isSidechain') is not True"),
        ('codex_event', "row.get('type') == 'compacted'", "row.get('type') == 'event_msg'"),
        ('process', 'None if same_process(identity) else', 'None if not same_process(identity) else'),
        ('stderr', 'run.stdout if run.returncode == 0 else run.stderr', 'run.stdout'),
        ('pane', "and result.get('pane') == identity.pane", ''),
        ('cancel', "if (record['state'] not in ('accepted', 'scheduled', 'waiting_idle',\n                                      'warning_dispatching', 'watching_other') or\n                    not _definitely_not_dispatched(record.get('delivery', {}))):", "if False:"),
        ('warning_cancel', "'warning_dispatching', 'watching_other') or", "'watching_other',) or"),
        ('notice_cancel_race', "if current['state'] == 'cancelled' and current.get('reason') == 'explicit_cancel':", "if False:"),
        ('notice_cancel_preserved', "if current['state'] == 'cancelled':", "if False:"),
        ('terminal_intervening_cancel', "record['pending_final_state'] = record['state']", "record['pending_final_state'] = 'watching_other'"),
        ('cancel_terminal_before_notice', "if record['state'] != 'cancelled':\n                        record['state'] = 'warning_dispatching'", "record['state'] = 'warning_dispatching'"),
        ('lost_cancel_notice', "record['failure_notice'] = {'state': 'unavailable',\n                                                    'reason': 'observer_disappeared_before_notice'}", "pass", 2),
        ('lost_dispatching_notice', "notice_state == 'dispatching' or", 'False or', 2),
        ('failure_notice', "            _failure_notice(directory, path, record, identity)", "            pass"),
        ('warning_before_terminal', "record['state'] = 'warning_dispatching'", "record['state'] = 'deferred'"),
        ('focus', "if record['focus_delivery']['state'] != 'delivered':", 'if False:'),
        ('socket', "env['SPAWN_TMUX_SOCKET'] = identity.socket", "env['SPAWN_TMUX_SOCKET'] = '/wrong'"),
        ('attestation', "if evidence.get(key) is not True:", 'if False:'),
        ('remote', "if push == 'no_remote_configured' and remotes:", 'if False:'),
        ('authority', "if action == 'exit' and (record['evidence']['authority']", "if False and (record['evidence']['authority']"),
        ('worker_recheck', "            verify_checkpoint(receipt['evidence'])", '            pass'),
        ('partial_record', "if baseline['skip_fragment'] and lines:", 'if False:'),
        ('replaced', "if (info.st_dev, info.st_ino) != (baseline['device'], baseline['inode']) or info.st_size < baseline['offset']:", 'if False:'),
        ('private_directory', "info.st_mode & 0o077:\n        raise ControlError('state_directory_not_private')", "False:\n        raise ControlError('state_directory_not_private')"),
        ('no_event_no_continue', 'if witness:', 'if True:'),
        ('preflight_peer_event', "            if text == '/compact':\n                other_event = _compact_event", "            if False:\n                other_event = _compact_event"),
        ('session_before_send', "        _verify_session(identity, record['session_id'], record.get('claude_state_dir'), record.get('codex_home'))\n        if suffix == '.focus' or", "        if suffix == '.focus' or"),
        ('session_fields', "if binding['state'] != 'observed' or binding['session_id'] != session_id:", 'if False:'),
        ('both_witnesses', "if marker and marker['count'] > record['pane_baseline']['count']:", 'if marker:'),
        ('typed_command', "command.append('--typed-command')", 'pass'),
        ('live_worker_receipt', 'return record  # live observer owns the final receipt, including continuation', 'pass  # broken: overwrites live observer receipt'),
        ('cancelled_observer_lease_race', atomic_claim, obsolete_lease_first),
        ('scope', "[identity.boot_id, identity.pid, identity.starttime, session_id]", "[identity.boot_id, identity.pid, identity.starttime, session_id, identity.cwd]"),
    ]
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        for case in cases:
            name, before, after, *count = case
            if source.count(before) != (count[0] if count else 1):
                raise AssertionError(f'mutation anchor {name}: {source.count(before)}')
            mutated = Path(directory) / (name + '.py')
            changed = source.replace(before, after)
            compile(changed, str(mutated), 'exec')
            mutated.write_text(changed)
            result = REAL_RUN([sys.executable, __file__], env={**os.environ, 'HARNESS_CONTROL_TEST_MODULE': str(mutated)}, capture_output=True, text=True, timeout=60)
            # Other tests may also error after a mutant corrupts shared state.
            # Require at least one failed assertion so a crash alone is not a kill.
            killed = result.returncode != 0 and 'FAIL:' in result.stderr
            print(('KILLED: ' if killed else 'INVALID OR SURVIVED: ') + name, flush=True)
            if not killed:
                failures.append(name)
                print(result.stdout + result.stderr)
    if failures:
        raise AssertionError('Mutations not killed by assertions: ' + ', '.join(failures))


if __name__ == '__main__':
    if '--live-integration' in sys.argv:
        live_integration()
    elif '--mutation-check' in sys.argv:
        mutations()
    else:
        unittest.main()
