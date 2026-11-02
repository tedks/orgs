#!/usr/bin/env python3
"""Offline fixtures are synthetic; never read actual session content."""
from datetime import datetime, timezone
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import time

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(os.environ.get('CODEX_STATUS_MODULE', ROOT / 'codex_status.py'))
spec = importlib.util.spec_from_file_location('codex_status', MODULE)
status = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(status)
SID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
STAMP = '2026-01-01T00:00:00Z'
NOW = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)

def parse(lines, expected_session_id=None, **kwargs):
    kwargs.setdefault('now', NOW)
    return status.parse_rollout(lines, expected_session_id, **kwargs)

def event(kind, payload, stamp=STAMP):
    return json.dumps({'type': kind, 'timestamp': stamp, 'payload': payload}) + '\n'

def meta(sid=SID, source='cli'):
    return event('session_meta', {'id': sid, 'source': source, 'cwd': '/synthetic', 'model_provider': 'openai'})

def tokens(bucket='codex', used=25):
    return event('event_msg', {'type': 'token_count', 'info': {
        'total_token_usage': {'total_tokens': 9000},
        'last_token_usage': {'input_tokens': 100, 'total_tokens': 120},
        'model_context_window': 200000}, 'rate_limits': {
        'limit_id': bucket, 'primary': {'used_percent': used, 'window_minutes': 300, 'resets_at': 2000000000},
        'secondary': None, 'plan_type': 'pro',
        'credits': {'has_credits': True, 'unlimited': False, 'balance': 'PRIVATE'}}})

class ParserTests(unittest.TestCase):
    def test_projection(self):
        result = parse([meta(), event('turn_context', {'model': 'example-model', 'cwd': '/next', 'user_instructions': 'PRIVATE'}), tokens()], SID)
        self.assertEqual(result['state'], 'observed')
        self.assertEqual((result['session_id'], result['model'], result['cwd']), (SID, 'example-model', '/next'))
        self.assertEqual(result['model_observed_at'], STAMP)
        self.assertEqual(result['token_usage']['last']['total_tokens'], 120)
        self.assertEqual(result['token_usage']['total']['total_tokens'], 9000)
        self.assertEqual(result['token_usage']['context_window'], 200000)
        self.assertIsNone(result['context_remaining'])
        quota = result['quota_buckets']['codex']
        self.assertEqual((quota['scope'], quota['provider'], quota['observed_at']), ('account', 'openai', STAMP))
        self.assertEqual(quota['primary'], {'state': 'observed', 'historical_used_percent': 25, 'used_percent': 25, 'remaining_percent': 75, 'window_minutes': 300, 'resets_at': 2000000000})
        self.assertIsNone(quota['secondary'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(quota['plan_type'], 'pro')
        self.assertEqual(quota['credits'], {'has_credits': True, 'unlimited': False})

    def test_plan_and_credits_validated(self):
        for plan, credits in [({}, 'x'), ('x' * 100, {'has_credits': 1, 'unlimited': 'no'}), ('bad plan!', None)]:
            record = json.loads(tokens())
            record['payload']['rate_limits'].update(plan_type=plan, credits=credits)
            quota = parse([meta(), json.dumps(record) + '\n'])['quota_buckets']['codex']
            self.assertIsNone(quota['plan_type'])
            self.assertEqual(quota['credits'], {'has_credits': None, 'unlimited': None})

    def test_missing_and_bad_identity(self):
        for lines, expected in [([], SID), ([meta()], OTHER), ([meta('bad')], None), ([tokens()], None), ([meta()], '../bad')]:
            with self.subTest(lines=lines, expected=expected):
                result = parse(lines, expected)
                self.assertEqual(result['state'], 'unsupported')
                self.assertNotIn('session_id', result)
        self.assertEqual(parse([meta()], SID)['session_id'], SID)

    def test_inherited_metadata_keeps_cli_root(self):
        result = parse([meta(), meta(OTHER, 'exec'), tokens()], SID, expected_source='cli')
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['session_id'], SID)
        self.assertEqual(result['token_usage']['last']['total_tokens'], 120)
        self.assertEqual(parse([meta(SID, 'exec'), meta(OTHER)])['state'], 'unsupported')

    def test_incomplete_and_malformed(self):
        self.assertEqual(parse([meta(), '{unfinished'])['state'], 'observed')
        for tail in [['{broken\n'], ['{}\n'], ['[]\n'], ['{unfinished', tokens()]]:
            self.assertEqual(parse([meta()] + tail)['state'], 'unsupported')

    def test_compaction(self):
        compact = event('compacted', {'message': 'PRIVATE', 'replacement_history': ['PRIVATE']})
        result = parse([meta(), tokens(), compact])
        self.assertEqual(result['compaction'], {'event_count': 1, 'last_timestamp': STAMP})
        self.assertIsNone(result['token_usage'])
        self.assertIn('codex', result['quota_buckets'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(parse([meta(), compact, tokens()])['token_usage']['last']['total_tokens'], 120)

    def test_quota_updates_and_unknowns(self):
        result = parse([meta(), tokens(), tokens('other', 80), event('event_msg', {'type': 'token_count', 'info': None, 'rate_limits': None})])
        self.assertEqual(set(result['quota_buckets']), {'codex', 'other'})
        self.assertEqual(result['quota_buckets']['other']['primary']['remaining_percent'], 20)
        self.assertEqual(result['token_usage']['total']['total_tokens'], 9000)
        self.assertEqual(parse([meta()])['quota_buckets'], {})
        for invalid in [True, -1, 101, float('nan'), '25']:
            self.assertIsNone(parse([meta(), tokens(used=invalid)])['quota_buckets']['codex']['primary']['remaining_percent'])

    def test_adversarial_numbers_and_expected_id(self):
        self.assertEqual(parse([meta()], SID)['state'], 'observed')
        for expected in [1, True, [], {}, b'bytes']:
            try:
                result = parse([meta()], expected)
            except Exception as exc:
                self.fail('Malformed expected identity raised instead of failing closed: ' + type(exc).__name__)
            self.assertEqual(result['reason'], 'invalid_expected_session_id')
        try:
            result = parse([meta(), tokens(used=10**1000)])
        except Exception as exc:
            self.fail('JSON integer raised instead of becoming unavailable: ' + type(exc).__name__)
        window = result['quota_buckets']['codex']['primary']
        self.assertEqual(window['state'], 'unavailable')
        self.assertIsNone(window['remaining_percent'])

    def test_expired_quota_is_historical(self):
        reset_time = datetime.fromtimestamp(2000000000, timezone.utc)
        for now in [reset_time, datetime(2034, 1, 1, tzinfo=timezone.utc)]:
            result = parse([meta(), tokens()], now=now)
            window = result['quota_buckets']['codex']['primary']
            self.assertEqual(window['state'], 'expired')
            self.assertEqual(window['historical_used_percent'], 25)
            self.assertIsNone(window['remaining_percent'])
            self.assertIsNone(window['used_percent'])
            self.assertEqual(result['quota_buckets']['codex']['evaluated_at'], now.isoformat())
        self.assertEqual(parse([meta(), tokens()])['quota_buckets']['codex']['primary']['remaining_percent'], 75)

    def test_unknown_quota_metadata(self):
        for key, value in [('resets_at', None), ('resets_at', True), ('resets_at', 10**1000),
                           ('window_minutes', None), ('window_minutes', 0), ('window_minutes', True)]:
            record = json.loads(tokens())
            record['payload']['rate_limits']['primary'][key] = value
            window = parse([meta(), json.dumps(record)+'\n'])['quota_buckets']['codex']['primary']
            self.assertEqual(window['state'], 'unavailable')
            self.assertIsNone(window['remaining_percent'])
        for stamp in [None, 'invalid', '2026-01-01', '2027-01-01T00:00:00Z']:
            record = json.loads(tokens())
            record['timestamp'] = stamp
            window = parse([meta(), json.dumps(record)+'\n'])['quota_buckets']['codex']['primary']
            self.assertEqual(window['state'], 'unavailable')
            self.assertIsNone(window['remaining_percent'])
        self.assertEqual(parse([meta(), tokens()])['quota_buckets']['codex']['primary']['state'], 'observed')

    def test_invalid_typed_values(self):
        result = parse([meta(), event('turn_context', {'model': {}, 'cwd': []}, 'no-time'), event('event_msg', {'type': 'token_count', 'info': {'model_context_window': True, 'last_token_usage': {'total_tokens': -1}}})])
        self.assertIsNone(result['model'])
        self.assertIsNone(result['model_observed_at'])
        self.assertIsNone(result['token_usage']['context_window'])
        self.assertIsNone(result['token_usage']['last'])

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sessions = self.root / 'home/.codex/sessions'
        self.fds = self.root / 'proc/123/fd'
        self.sessions.mkdir(parents=True)
        self.fds.mkdir(parents=True)
        (self.fds.parent / 'fdinfo').mkdir()
        (self.fds.parent / 'environ').write_bytes(b'')

    def add(self, number, content):
        path = self.sessions / f'rollout-{number}.jsonl'
        path.write_text(content)
        (self.fds / str(number)).symlink_to(path)
        (self.fds.parent / 'fdinfo' / str(number)).write_text('flags:\t0102001\n')
        return path

    def read(self, **kwargs):
        return status.read_codex_status(123, self.root / 'home', proc=self.root / 'proc', **kwargs)

    def test_unique_cli_ignores_subagent(self):
        path = self.add(1, meta() + tokens())
        self.add(2, meta(OTHER, {'subagent': {}}))
        result = self.read()
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['session_id'], SID)
        self.assertEqual(result['rollout_path'], str(path))
        (self.fds / '3').symlink_to(path)
        (self.fds.parent / 'fdinfo/3').write_text('flags:\t0102001\n')
        self.assertEqual(self.read()['session_id'], SID)  # duplicate descriptor, same inode

    def test_balance_never_exposed(self):
        self.add(1, meta() + tokens())
        result = self.read()
        self.assertEqual(result['quota_buckets']['codex']['credits'], {'has_credits': True, 'unlimited': False})
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_recycled_descriptor_rejected(self):
        self.add(1, meta() + tokens())
        replacement = self.sessions / 'replacement.jsonl'
        replacement.write_text(meta() + tokens())  # identical ID, source and size
        self.assertEqual(self.read()['state'], 'observed')
        original_open = Path.open
        opens = 0
        def swap(path, *args, **kwargs):
            nonlocal opens
            if path == self.fds / '1':
                opens += 1
                if opens == 2:
                    path.unlink()
                    path.symlink_to(replacement)
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', swap):
            self.assertEqual(self.read().get('reason'), 'rollout_descriptor_changed')

    def test_source_rechecked_in_opened_stream(self):
        rollout = self.add(1, meta() + tokens())
        self.assertEqual(self.read()['state'], 'observed')
        original_open = Path.open
        opens = 0
        def rewrite(path, *args, **kwargs):
            nonlocal opens
            if path == self.fds / '1':
                opens += 1
                if opens == 2:
                    rollout.write_text(meta(source='api') + tokens())  # same inode and size
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', rewrite):
            self.assertEqual(self.read().get('reason'), 'session_source_mismatch')

    def test_ambiguity_and_missing(self):
        self.assertEqual(self.read()['state'], 'unsupported')
        self.add(1, meta())
        self.assertEqual(self.read()['state'], 'observed')
        self.add(2, meta(OTHER))
        self.assertEqual(self.read()['state'], 'unsupported')

    def test_bounds(self):
        self.add(1, meta() + tokens())
        self.assertEqual(self.read()['state'], 'observed')
        bounded = self.read(max_bytes=10)
        self.assertEqual(bounded['state'], 'observed')
        self.assertIsNone(bounded['token_usage'])
        self.assertFalse(bounded['history_complete'])
        self.assertEqual(bounded['compaction']['count_scope'], 'scanned_window')
        self.assertEqual(self.read(max_line_bytes=10)['state'], 'unsupported')

    def test_partial_utf8_is_not_a_record(self):
        path = self.add(1, meta() + tokens())
        with path.open('ab') as stream:
            stream.write(b'{"incomplete":"\xe2\x82')
        result = self.read()
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['token_usage']['last']['total_tokens'], 120)
        with path.open('ab') as stream:
            stream.write(b'\n')
        self.assertEqual(self.read()['state'], 'unsupported')

    def test_pinned_codex_home(self):
        self.sessions = self.root / 'custom-codex/sessions'
        self.sessions.mkdir(parents=True)
        path = self.add(1, meta() + tokens())
        (self.fds.parent / 'environ').write_bytes(
            b'CODEX_HOME=' + os.fsencode(self.sessions.parent) + b'\0')
        with patch.dict(os.environ, CODEX_HOME='/unrelated-caller-home'):
            result = self.read()
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['rollout_path'], str(path))
        (self.fds.parent / 'environ').write_bytes(b'CODEX_HOME=relative\0')
        self.assertEqual(self.read()['reason'], 'relative_codex_home_unsupported')

    def test_default_home_is_resolved_at_call_time(self):
        self.add(1, meta())
        with patch.dict(os.environ, HOME=str(self.root / 'home')):
            result = status.read_codex_status(123, proc=self.root / 'proc')
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['session_id'], SID)

    def test_pinned_home_fallback(self):
        self.sessions = self.root / 'harness-home/.codex/sessions'
        self.sessions.mkdir(parents=True)
        self.add(1, meta())
        (self.fds.parent / 'environ').write_bytes(
            b'HOME=' + os.fsencode(self.root / 'harness-home') + b'\0')
        with patch.object(Path, 'home', side_effect=RuntimeError('caller home unavailable')):
            result = self.read()
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['session_id'], SID)

    def test_unavailable_home_is_typed(self):
        self.add(1, meta())
        with patch.object(Path, 'home', side_effect=RuntimeError('caller home unavailable')):
            try:
                result = status.read_codex_status(123, proc=self.root / 'proc')
            except RuntimeError:
                self.fail('Path.home failure escaped instead of returning unsupported')
        self.assertEqual(result['state'], 'unsupported')
        self.assertEqual(self.read()['state'], 'observed')

    def test_closed_descriptor_does_not_poison_live_root(self):
        self.add(1, meta())
        self.add(2, meta(OTHER, {'subagent': {}}))
        self.assertEqual(self.read()['state'], 'observed')
        for method, target in [('read_text', self.fds.parent / 'fdinfo/2'),
                               ('stat', self.fds / '2'), ('open', self.fds / '2')]:
            original = getattr(Path, method)
            def closed(path, *args, **kwargs):
                if path == target:
                    raise FileNotFoundError('descriptor closed')
                return original(path, *args, **kwargs)
            with self.subTest(method=method), patch.object(Path, method, closed):
                result = self.read()
            self.assertEqual(result['state'], 'observed')
            self.assertEqual(result['session_id'], SID)
        original = Path.read_text
        def denied(path, *args, **kwargs):
            if path == self.fds.parent / 'fdinfo/2':
                raise PermissionError('unknown access failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', denied):
            self.assertEqual(self.read()['state'], 'unsupported')

    def test_readonly_picker_is_not_owner(self):
        self.add(1, meta())
        self.add(2, meta(OTHER))
        (self.fds.parent / 'fdinfo/2').write_text('flags:\t0100000\n')
        result = self.read()
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['session_id'], SID)
        (self.fds.parent / 'fdinfo/1').write_text('flags:\t0100000\n')
        self.assertEqual(self.read()['state'], 'unsupported')

    def test_empty_writer_is_temporarily_unclassified(self):
        self.add(1, meta())
        child = self.add(2, '')
        self.assertEqual(self.read().get('reason'), 'unclassified_empty_writable_rollout')
        child.write_text(meta(OTHER, {'subagent': {}}))
        self.assertEqual(self.read()['state'], 'observed')

    def test_large_history_uses_bounded_tail(self):
        latest = (event('turn_context', {'model': 'latest-model', 'cwd': '/last'})
                  + tokens()
                  + event('event_msg', {'type': 'token_count', 'info': None,
                      'rate_limits': {'limit_id': 'other', 'primary': {
                          'used_percent': 50, 'window_minutes': 60, 'resets_at': 2000000000}}}))
        large = event('response_item', {'type': 'message', 'content': 'x' * 5000})
        self.add(1, meta() + event('compacted', {}) + large + latest)
        result = self.read(max_bytes=len(latest.encode()) + 100, max_line_bytes=700)
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['model'], 'latest-model')
        self.assertEqual(result['token_usage']['last']['total_tokens'], 120)
        self.assertEqual(set(result['quota_buckets']), {'codex', 'other'})
        self.assertFalse(result['history_complete'])
        self.assertEqual(result['compaction']['event_count'], 0)
        self.assertEqual(result['compaction']['count_scope'], 'scanned_window')
        self.assertLessEqual(result['read_window']['tail_bytes'], len(latest.encode()) + 100)
        # Even within budget, a huge unrelated record must not poison later fields.
        full = self.read(max_line_bytes=700)
        self.assertEqual(full['state'], 'observed')
        self.assertEqual(full['model'], 'latest-model')
        self.assertFalse(full['history_complete'])
        self.assertEqual(full['compaction']['event_count'], 1)

    def test_skipped_record_invalidates_token_accounting(self):
        large = event('compacted', {'replacement_history': 'x' * 5000})
        path = self.add(1, meta() + tokens() + large)
        result = self.read(max_line_bytes=700)
        self.assertEqual(result['state'], 'observed')
        self.assertIsNone(result['token_usage'])
        self.assertEqual(result['compaction']['event_count'], 0)
        self.assertIsNone(result['compaction']['last_timestamp'])
        self.assertFalse(result['history_complete'])
        with path.open('a') as stream:
            stream.write(tokens())
        restored = self.read(max_line_bytes=700)
        self.assertEqual(restored['state'], 'observed')
        self.assertEqual(restored['token_usage']['last']['total_tokens'], 120)
        self.assertEqual(restored['compaction']['event_count'], 0)

    def test_invalid_metadata(self):
        path = self.add(1, meta())
        self.assertEqual(self.read()['state'], 'observed')
        for content in ['{broken\n', meta('bad'), tokens(), '[]\n', meta().rstrip()]:
            path.write_text(content)
            self.assertEqual(self.read()['state'], 'unsupported')

    def test_nonregular_rollout(self):
        path = self.sessions / 'rollout-directory.jsonl'
        path.mkdir()
        (self.fds / '1').symlink_to(path)
        (self.fds.parent / 'fdinfo/1').write_text('flags:\t0102001\n')
        self.assertEqual(self.read()['reason'], 'invalid_rollout_file')

    def test_outside_home_and_pid(self):
        path = self.root / 'rollout-outside.jsonl'
        path.write_text(meta())
        (self.fds / '1').symlink_to(path)
        (self.fds.parent / 'fdinfo/1').write_text('flags:\t0102001\n')
        self.assertEqual(self.read()['state'], 'unsupported')
        self.add(2, meta())
        self.assertEqual(self.read()['state'], 'observed')
        self.assertEqual(status.read_codex_status(True)['state'], 'unsupported')

def rollout_text(records, provider='openai', header=True):
    head = event('session_meta', {'id': SID, 'source': 'cli', 'cwd': '/synthetic-cwd',
                                  'model_provider': provider}) if header else ''
    return head + ''.join(records)

def quota_event(stamp, used, bucket='codex', resets=2000000000, minutes=10080):
    return event('event_msg', {'type': 'token_count', 'info': None, 'rate_limits': {
        'limit_id': bucket, 'primary': {'used_percent': used, 'window_minutes': minutes, 'resets_at': resets},
        'secondary': None, 'plan_type': 'pro',
        'credits': {'has_credits': True, 'unlimited': False, 'balance': 'PRIVATE'}}}, stamp)

ACCOUNT_NOW = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
def at(day, hour=0):
    return f'2026-01-{day:02d}T{hour:02d}:00:00Z'

class AccountQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'codex'
        self.sessions = self.home / 'sessions/2026/01/10'
        self.sessions.mkdir(parents=True)
        self.age = 0

    def add(self, name, content, age_hours=1, directory=None):
        path = (directory or self.sessions) / name
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        mtime = ACCOUNT_NOW.timestamp() - age_hours * 3600
        os.utime(path, (mtime, mtime))
        return path

    def newest(self, **kwargs):
        kwargs.setdefault('now', ACCOUNT_NOW)
        return status.newest_account_quota(self.home, **kwargs)

    def primary(self, result, bucket='codex'):
        return result['quota_buckets'][bucket]['primary']['used_percent']

    def test_newest_timestamp_wins_over_newest_mtime(self):
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 9), 1)]), age_hours=5)
        # The most recently modified file holds an older record.
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(9, 9), 99)]), age_hours=1)
        result = self.newest()
        self.assertEqual(result['state'], 'observed')
        self.assertEqual((result['source'], result['scope'], result['files_scanned']),
                         ('codex_rollouts_newest', 'account', 2))
        self.assertEqual(result['evaluated_at'], ACCOUNT_NOW.isoformat())
        bucket = result['quota_buckets']['codex']
        self.assertEqual((self.primary(result), bucket['observed_at']), (1, at(10, 9)))
        self.assertEqual(bucket['provider'], 'openai')
        self.assertEqual(bucket['plan_type'], 'pro')
        self.assertEqual(bucket['credits'], {'has_credits': True, 'unlimited': False})

    def test_within_file_newest_record_and_per_bucket(self):
        self.add('rollout-a.jsonl', rollout_text([
            quota_event(at(10, 1), 5), quota_event(at(10, 3), 7), quota_event(at(10, 2), 6),
            quota_event(at(10, 4), 40, bucket='other')]))
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 5), 50, bucket='other')]))
        result = self.newest()
        self.assertEqual(set(result['quota_buckets']), {'codex', 'other'})
        self.assertEqual(self.primary(result), 7)
        self.assertEqual(self.primary(result, 'other'), 50)

    def test_missing_bucket_id_is_unknown_and_invalid_timestamps_skipped(self):
        legacy = json.loads(quota_event(at(10, 1), 3))
        del legacy['payload']['rate_limits']['limit_id']
        self.add('rollout-a.jsonl', rollout_text([
            json.dumps(legacy) + '\n', quota_event('garbage', 90), quota_event('2026-01-10T05:00:00', 91)]))
        result = self.newest()
        self.assertEqual(set(result['quota_buckets']), {'unknown'})
        self.assertEqual(self.primary(result, 'unknown'), 3)

    def test_skips_unusable_files_and_lines(self):
        good = rollout_text([quota_event(at(10, 1), 11)])
        self.add('rollout-good.jsonl', good, age_hours=3)
        self.add('rollout-malformed.jsonl', rollout_text(['{"rate_limits": broken\n', quota_event(at(10, 2), 12)]), age_hours=4)
        self.add('notes.jsonl', rollout_text([quota_event(at(10, 9), 80)]))
        self.add('rollout-x.txt', rollout_text([quota_event(at(10, 9), 81)]))
        self.add('rollout-old.jsonl', rollout_text([quota_event(at(10, 9), 82)]), age_hours=8 * 24 + 1)
        real = self.add('elsewhere.jsonl', rollout_text([quota_event(at(10, 9), 83)]), directory=self.home)
        (self.sessions / 'rollout-link.jsonl').symlink_to(real)
        (self.sessions / 'rollout-inner-link.jsonl').symlink_to(self.sessions / 'rollout-good.jsonl')
        other_dir = Path(self.tmp.name) / 'outside'
        other_dir.mkdir()
        self.add('rollout-outside.jsonl', rollout_text([quota_event(at(10, 9), 84)]), directory=other_dir)
        (self.sessions.parent / 'linked').symlink_to(other_dir)
        result = self.newest()
        self.assertEqual(result['files_scanned'], 2)
        self.assertEqual(self.primary(result), 12)

    def test_symlink_not_opened(self):
        target = self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 1), 13)]))
        link = self.sessions / 'rollout-link.jsonl'
        link.symlink_to(target)
        self.assertEqual(status._file_quota(target, 1024, 1024)[1].keys(), {'codex'})
        with self.assertRaises(OSError):
            status._file_quota(link, 1024, 1024)
        self.assertEqual(status._rollout_candidates((self.home / 'sessions').resolve(), ACCOUNT_NOW, 10),
                         ([(target.stat().st_mtime, target.resolve())], False))

    def test_resolved_path_must_stay_under_sessions(self):
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        self.add('rollout-outside.jsonl', rollout_text([quota_event(at(10, 9), 84)]), directory=outside)
        with patch.object(status, '_day_files', return_value=[(outside, 'rollout-outside.jsonl')]):
            self.assertEqual(self.newest().get('reason'), 'no_recent_rate_limits')

    def test_leading_partial_line_dropped(self):
        record = quota_event(at(10, 9), 85)
        content = rollout_text([event('response_item', {'type': 'message'}), 'JUNK' + record])
        self.add('rollout-a.jsonl', content)
        tail = len(record.encode()) - 1  # the tail read starts at the record's own brace, inside the JUNK line
        self.assertEqual(self.newest(tail_bytes=tail).get('reason'), 'no_recent_rate_limits')
        self.assertEqual(self.newest().get('reason'), 'no_recent_rate_limits')  # whole line is malformed

    def test_stops_early_when_bound_reached(self):
        # Newest-mtime file's record is at/after the next file's mtime: the older
        # file (which holds an even newer record) is never read.
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 11), 1)]), age_hours=1)
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 11).replace('11:00', '11:30'), 2)]), age_hours=2)
        result = self.newest()
        self.assertEqual((result['files_scanned'], result['stopped_early'], self.primary(result)), (1, True, 1))
        # Normal case: the older file's mtime is after the record, so it is read.
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 10), 2)]), age_hours=0.5)
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 1), 1)]), age_hours=1)
        result = self.newest()
        self.assertEqual((result['files_scanned'], result['stopped_early']), (2, False))

    def test_multi_bucket_bound_uses_oldest_bucket(self):
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(9, 9), 1)]), age_hours=1)
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 9), 2, bucket='other')]), age_hours=2)
        result = self.newest()
        self.assertEqual((result['files_scanned'], result['stopped_early']), (2, False))
        self.assertEqual(set(result['quota_buckets']), {'codex', 'other'})
        # Once both buckets are at/after the next mtime, the scan stops.
        self.add('rollout-c.jsonl', rollout_text([quota_event(at(10, 9), 3, bucket='other')]), age_hours=2.5)
        self.add('rollout-d.jsonl', rollout_text([quota_event(at(10, 11), 4, bucket='other')]), age_hours=40)
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 9), 2, bucket='other')]), age_hours=1.5)
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 10), 1)]), age_hours=1)
        result = self.newest()
        self.assertEqual((result['files_scanned'], result['stopped_early']), (3, True))

    def test_meterless_tail_searches_backwards(self):
        filler = event('response_item', {'type': 'message', 'content': 'x' * 3000})
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 1), 14), filler, filler]))
        result = self.newest(tail_bytes=1000)
        self.assertEqual(result.get('state'), 'observed')
        self.assertEqual((self.primary(result), result['incomplete']), (14, False))
        self.assertNotIn('reason_incomplete', result)

    def test_meterless_window_is_incomplete_not_stale(self):
        filler = event('response_item', {'type': 'message', 'content': 'x' * 3000})
        self.add('rollout-old.jsonl', rollout_text([quota_event(at(9, 1), 99)]), age_hours=5)
        self.add('rollout-new.jsonl', rollout_text([quota_event(at(10, 1), 15), filler, filler]), age_hours=1)
        result = self.newest(tail_bytes=1000, search_bytes=2000)
        self.assertEqual(result['state'], 'observed')
        self.assertEqual((result.get('incomplete'), result.get('reason_incomplete')), (True, 'file_without_meter_in_window'))
        # Only the new file is meterless; with nothing else observed the reader says so.
        (self.sessions / 'rollout-old.jsonl').unlink()
        result = self.newest(tail_bytes=1000, search_bytes=2000)
        self.assertEqual((result['state'], result['reason']), ('unavailable', 'file_without_meter_in_window'))
        # A file read in full that simply has no meter is complete.
        self.add('rollout-new.jsonl', rollout_text([event('response_item', {'type': 'message', 'content': 'x' * 300})]))
        self.add('rollout-old.jsonl', rollout_text([quota_event(at(9, 1), 99)]), age_hours=5)
        self.assertFalse(self.newest(tail_bytes=1000, search_bytes=2000)['incomplete'])

    def test_expected_bucket_only_in_older_file(self):
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 11), 1)]), age_hours=1)
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 9), 2, bucket='other')]), age_hours=2)
        result = self.newest()
        self.assertEqual((set(result['quota_buckets']), result['stopped_early']), ({'codex'}, True))
        result = self.newest(expected_buckets=['codex', 'other'])
        self.assertEqual((set(result['quota_buckets']), result['stopped_early']), ({'codex', 'other'}, False))
        self.assertEqual(self.newest(expected_buckets=['codex'])['files_scanned'], 1)
        self.assertEqual(self.newest(expected_buckets=7)['reason'], 'invalid_expected_buckets')

    def test_early_stop_skew_margin(self):
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 11), 1)]), age_hours=1)
        for margin, scanned in [(119, 2), (120, 1)]:
            # b's mtime is `margin` seconds before the best record's timestamp.
            self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 9), 2)]),
                     age_hours=(3600 + margin) / 3600)
            self.assertEqual(self.newest()['files_scanned'], scanned, margin)

    def test_deeply_nested_line_is_skipped(self):
        deep = '[' * 200000 + ' rate_limits\n'
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 1), 16), deep]))
        try:
            result = self.newest()
        except RecursionError:
            self.fail('RecursionError escaped the reader')
        self.assertEqual(result.get('state'), 'observed')
        self.assertEqual(self.primary(result), 16)

    def test_only_valid_day_directories_are_listed(self):
        for name, valid in {'2026/01/09': True, '2026/13/01': False, '2026/02/30': False, '2026/1/05': False,
                            '20x6/01/01': False}.items():
            (self.home / 'sessions' / name).mkdir(parents=True)
        listed = []
        original = os.scandir
        def spy(path):
            listed.append(str(path))
            return original(path)
        with patch.object(os, 'scandir', spy):
            self.newest()
        for name, expected in {'2026/01/09': True, '2026/13/01': False, '2026/02/30': False,
                               '2026/1/05': False, '20x6/01/01': False}.items():
            self.assertEqual(str(self.home / 'sessions' / name) in listed, expected, name)

    def test_entry_cap_marks_incomplete(self):
        for number in range(5):
            self.add(f'rollout-{number}.jsonl', rollout_text([quota_event(at(10, number), number)]))
        full = self.newest()
        self.assertFalse(full['incomplete'])
        with patch.object(status, '_MAX_ENTRIES', 6):
            result = self.newest()
        self.assertEqual((result.get('incomplete'), result.get('reason_incomplete')), (True, 'too_many_rollouts'))
        with patch.object(status, '_MAX_ENTRIES', 0):
            self.assertEqual(self.newest().get('reason'), 'too_many_rollouts')

    def test_huge_directory_is_pulled_lazily_up_to_the_cap(self):
        for number in range(60):
            (self.sessions / f'rollout-{number}.jsonl').write_text('')
        pulled = []
        original = os.scandir
        class Spy:
            def __init__(self, inner):
                self.inner = inner
            def __enter__(self):
                self.inner.__enter__()
                return self
            def __exit__(self, *exc):
                return self.inner.__exit__(*exc)
            def __iter__(self):
                return self
            def __next__(self):
                entry = next(self.inner)
                pulled.append(entry.name)
                return entry
        with patch.object(status, '_MAX_ENTRIES', 10), patch.object(os, 'scandir', lambda p: Spy(original(p))):
            result = self.newest()
        self.assertEqual(result.get('reason'), 'too_many_rollouts')
        self.assertLessEqual(len(pulled), 11)
        self.assertGreaterEqual(len(pulled), 10)

    def test_old_dirs_budget(self):
        for number in range(40):
            (self.home / 'sessions' / f'junk-{number}').write_text('')
        pulled = []
        original = os.scandir
        def spy(path):
            inner = original(path)
            class Wrapped:
                def __enter__(self_):
                    inner.__enter__()
                    return self_
                def __exit__(self_, *exc):
                    return inner.__exit__(*exc)
                def __iter__(self_):
                    return self_
                def __next__(self_):
                    entry = next(inner)
                    pulled.append(entry.name)
                    return entry
            return Wrapped()
        with patch.object(status, '_MAX_ENTRIES', 10), patch.object(os, 'scandir', spy):
            result = self.newest()
        self.assertLessEqual(len(pulled), 11)
        self.assertEqual(result.get('reason'), 'too_many_rollouts')

    def test_long_lived_session_in_old_day_directory_is_found(self):
        old_day = self.home / 'sessions/2025/11/11'  # 60 days before ACCOUNT_NOW
        old_day.mkdir(parents=True)
        self.add('rollout-long.jsonl', rollout_text([quota_event(at(10, 9), 19)]), directory=old_day, age_hours=1)
        self.add('rollout-today.jsonl', rollout_text([quota_event(at(10, 1), 20)]), age_hours=2)
        self.assertEqual(self.primary(self.newest()), 19)

    def test_expected_bucket_beyond_search_cap_is_uncertain(self):
        filler = event('response_item', {'type': 'message', 'content': 'x' * 3000})
        self.add('rollout-new.jsonl', rollout_text([
            quota_event(at(10, 5), 21, bucket='B'), filler, filler, filler, quota_event(at(10, 6), 22, bucket='A')]), age_hours=1)
        self.add('rollout-old.jsonl', rollout_text([quota_event(at(9, 5), 99, bucket='B')]), age_hours=40)
        result = self.newest(tail_bytes=1000, search_bytes=4000, expected_buckets=['A', 'B'])
        self.assertEqual((self.primary(result, 'A'), self.primary(result, 'B')), (22, 99))
        self.assertEqual((result.get('incomplete'), result.get('reason_incomplete')),
                         (True, 'file_without_meter_in_window'))

    def test_partial_bucket_coverage_continues_backwards_in_file(self):
        filler = event('response_item', {'type': 'message', 'content': 'x' * 3000})
        self.add('rollout-new.jsonl', rollout_text([
            quota_event(at(10, 5), 21, bucket='B'), filler, filler, quota_event(at(10, 6), 22, bucket='A')]), age_hours=1)
        self.add('rollout-old.jsonl', rollout_text([quota_event(at(9, 5), 99, bucket='B')]), age_hours=40)
        result = self.newest(tail_bytes=1000, expected_buckets=['A', 'B'])
        self.assertEqual((self.primary(result, 'A'), self.primary(result, 'B')), (22, 21))
        self.assertFalse(result['incomplete'])
        self.assertNotIn('missing_buckets', result)

    def test_backward_search_reads_each_byte_once(self):
        filler = event('response_item', {'type': 'message', 'content': 'x' * 3000})
        content = rollout_text([quota_event(at(10, 1), 24)] + [filler] * 20)
        self.add('rollout-a.jsonl', content)
        counted = []
        original = os.fdopen
        class Counting:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                self.stream.close()
            def read(self, *args):
                data = self.stream.read(*args)
                counted.append(len(data))
                return data
            def __getattr__(self, name):
                return getattr(self.stream, name)
        with patch.object(os, 'fdopen', lambda *a, **k: Counting(original(*a, **k))):
            result = self.newest(tail_bytes=1000)
        self.assertEqual(self.primary(result), 24)
        self.assertLessEqual(sum(counted), len(content.encode()) + 16)

    def test_missing_expected_bucket_marks_incomplete(self):
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 1), 23)]))
        result = self.newest(expected_buckets=['codex', 'ghost'])
        self.assertEqual((result.get('missing_buckets'), result.get('incomplete'), result.get('reason_incomplete')),
                         (['ghost'], True, 'expected_buckets_missing'))
        self.assertEqual(set(result['quota_buckets']), {'codex'})

    def test_header_over_64k_has_no_provider(self):
        big = event('session_meta', {'id': SID, 'source': 'cli', 'cwd': 'c' * 70000, 'model_provider': 'openai'})
        self.add('rollout-a.jsonl', big + quota_event(at(10, 1), 18))
        bucket = self.newest()['quota_buckets']['codex']
        self.assertEqual((bucket['provider'], bucket['primary']['used_percent']), (None, 18))

    def test_age_cutoff_boundary(self):
        self.add('rollout-edge.jsonl', rollout_text([quota_event(at(10, 1), 21)]), age_hours=8 * 24 - 1)
        self.assertEqual(self.newest()['state'], 'observed')
        self.add('rollout-edge.jsonl', rollout_text([quota_event(at(10, 1), 21)]), age_hours=8 * 24 + 1)
        self.assertEqual(self.newest().get('reason'), 'no_recent_rate_limits')

    def test_max_files_limits_candidates_by_mtime(self):
        self.add('rollout-new.jsonl', rollout_text([quota_event(at(10, 1), 31)]), age_hours=1)
        self.add('rollout-older.jsonl', rollout_text([quota_event(at(10, 9), 32)]), age_hours=2)
        result = self.newest(max_files=1)
        self.assertEqual((result['files_scanned'], self.primary(result)), (1, 31))
        self.assertEqual(self.primary(self.newest(max_files=2)), 32)

    def test_tail_bytes_bound_and_partial_lines(self):
        old = quota_event(at(10, 1), 41)
        filler = event('response_item', {'type': 'message', 'content': 'x' * 3000})
        recent = quota_event(at(10, 2), 42, bucket='other')
        self.add('rollout-a.jsonl', rollout_text([old, filler, recent]))
        result = self.newest(tail_bytes=len(recent.encode()) + 50)
        self.assertEqual(set(result['quota_buckets']), {'other'})  # the older record is beyond the tail
        self.assertEqual(set(self.newest()['quota_buckets']), {'codex', 'other'})
        # A tail beginning mid-record never parses the fragment.
        cut = rollout_text([old, filler, recent]).encode()
        self.add('rollout-a.jsonl', cut)
        tail = len(recent.encode()) + len(filler.encode()) // 2
        self.assertEqual(set(self.newest(tail_bytes=tail)['quota_buckets']), {'other'})

    def test_unfinished_trailing_line_ignored(self):
        self.add('rollout-a.jsonl', rollout_text([quota_event(at(10, 1), 51)])
                 + quota_event(at(10, 5), 52).rstrip('\n'))
        self.assertEqual(self.primary(self.newest()), 51)
        self.add('rollout-b.jsonl', rollout_text([quota_event(at(10, 2), 53)]).encode()
                 + quota_event(at(10, 6), 54).encode()[:-30])
        self.assertEqual(self.primary(self.newest()), 53)

    def test_oversized_line_skipped(self):
        small = quota_event(at(10, 1), 62)
        padded = json.loads(quota_event(at(10, 9), 61))
        padded['payload']['rate_limits']['limit_name'] = 'n' * 500
        self.add('rollout-a.jsonl', rollout_text([small, json.dumps(padded) + '\n']))
        self.assertEqual(self.primary(self.newest(max_line_bytes=len(small.encode()) + 100)), 62)
        self.assertEqual(self.primary(self.newest()), 61)

    def test_unavailable_states(self):
        self.assertEqual(self.newest(), {'state': 'unavailable', 'source': 'codex_rollouts_newest',
                                         'reason': 'no_recent_rate_limits'})
        self.add('rollout-a.jsonl', rollout_text([]))
        self.assertEqual(self.newest()['reason'], 'no_recent_rate_limits')
        missing = status.newest_account_quota(Path(self.tmp.name) / 'absent', now=ACCOUNT_NOW)
        self.assertEqual((missing['state'], missing['reason']), ('unavailable', 'sessions_unreadable'))
        self.assertEqual(self.newest(now=datetime(2026, 1, 10))['reason'], 'invalid_observation_time')

    def test_expiry_matches_parse_rollout(self):
        stamp = at(10, 1)
        resets = int(datetime(2026, 1, 10, 6, tzinfo=timezone.utc).timestamp())
        content = rollout_text([quota_event(stamp, 33, resets=resets)])
        self.add('rollout-a.jsonl', content)
        for now in [datetime(2026, 1, 10, 5, tzinfo=timezone.utc), datetime(2026, 1, 10, 6, tzinfo=timezone.utc),
                    datetime(2026, 1, 10, 7, tzinfo=timezone.utc)]:
            expected = parse(content.splitlines(True), now=now)['quota_buckets']['codex']
            got = self.newest(now=now)['quota_buckets']['codex']
            self.assertEqual(got, expected)
        self.assertEqual(self.newest(now=datetime(2026, 1, 10, 6, tzinfo=timezone.utc))
                         ['quota_buckets']['codex']['primary']['state'], 'expired')

    def test_output_is_content_free(self):
        self.add('rollout-secret-name.jsonl', rollout_text([quota_event(at(10, 1), 71)], provider='openai'))
        text = json.dumps(self.newest())
        for forbidden in ('PRIVATE', 'synthetic-cwd', 'rollout-', SID, self.tmp.name, 'balance'):
            self.assertNotIn(forbidden, text)

class CodexHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'proc/5').mkdir(parents=True)

    def home_for(self, environ, home=None):
        (self.root / 'proc/5/environ').write_bytes(environ)
        return status.codex_home_for(5, home, proc=self.root / 'proc')

    def test_resolution_order(self):
        self.assertEqual(self.home_for(b'CODEX_HOME=/pinned\0HOME=/h\0'), Path('/pinned'))
        self.assertEqual(self.home_for(b'HOME=/h\0'), Path('/h/.codex'))
        self.assertEqual(self.home_for(b'', Path('/fallback')), Path('/fallback/.codex'))
        self.assertIsNone(self.home_for(b'CODEX_HOME=relative\0'))
        self.assertIsNone(status.codex_home_for(99, proc=self.root / 'proc'))
        self.assertIsNone(status.codex_home_for(True, proc=self.root / 'proc'))


def mutation_check():
    """Baseline first; every mutant must be valid Python and fail assertions.

    Only temporary module copies are changed. An ERROR, crash, timeout, import
    failure or surviving mutant fails the checker instead of counting as a kill.
    """
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    if not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful():
        return 1
    mutations = [
        ('remaining', '100 - used if state == "observed" else None',
         'used if state == "observed" else None', 'ParserTests.test_projection'),
        ('huge-integer', 'or not 0 <= used <= 100 or not math.isfinite(used)',
         'or not math.isfinite(used) or not 0 <= used <= 100', 'ParserTests.test_adversarial_numbers_and_expected_id'),
        ('id-type', 'not isinstance(expected_session_id, str) or not _ID.fullmatch(expected_session_id)',
         'not _ID.fullmatch(expected_session_id)', 'ParserTests.test_adversarial_numbers_and_expected_id'),
        ('identity', 'sid.lower() != expected_session_id.lower()', 'False', 'ParserTests.test_missing_and_bad_identity'),
        ('fork-metadata', 'if initial_source != "cli":', 'if True:', 'ParserTests.test_inherited_metadata_keeps_cli_root'),
        ('partial-json', 'return failure("incomplete_nonfinal_record")', 'break', 'ParserTests.test_incomplete_and_malformed'),
        ('compaction', 'result["compaction"]["event_count"] += 1',
         'result["compaction"]["event_count"] += 0', 'ParserTests.test_compaction'),
        ('typed-numbers', 'type(value) is int and value >= 0',
         'isinstance(value, int) and value >= 0', 'ParserTests.test_invalid_typed_values'),
        ('expiry', 'state = "expired" if reset <= now else "observed"',
         'state = "observed"', 'ParserTests.test_expired_quota_is_historical'),
        ('expiry-boundary', 'reset <= now', 'reset < now', 'ParserTests.test_expired_quota_is_historical'),
        ('unknown-window', 'minutes is not None', 'True', 'ParserTests.test_unknown_quota_metadata'),
        ('future-observation', 'observed <= now', 'True', 'ParserTests.test_unknown_quota_metadata'),
        ('unknown-observation', 'if observed_at is not None else None',
         'if observed_at is not None else now', 'ParserTests.test_unknown_quota_metadata'),
        ('fd-recycling', 'if (opened.st_dev, opened.st_ino) != selected_identity:',
         'if False:', 'ReaderTests.test_recycled_descriptor_rejected'),
        ('source-recheck', 'expected_source="cli"', 'expected_source=None', 'ReaderTests.test_source_rechecked_in_opened_stream'),
        ('root-only', 'if payload.get("source") != "cli":', 'if False:', 'ReaderTests.test_unique_cli_ignores_subagent'),
        ('ambiguity', 'if len(candidates) != 1:', 'if not candidates:', 'ReaderTests.test_ambiguity_and_missing'),
        ('partial-utf8', 'break  # partial trailing UTF-8 is not yet a JSONL record',
         'pass  # mutation: decode uncommitted bytes', 'ReaderTests.test_partial_utf8_is_not_a_record'),
        ('pinned-home', 'configured = environment.get(b"CODEX_HOME")', 'configured = None', 'ReaderTests.test_pinned_codex_home'),
        ('default-home', 'home = Path.home() if home is None else home',
         'home = Path("/nonexistent") if home is None else home', 'ReaderTests.test_default_home_is_resolved_at_call_time'),
        ('pinned-fallback-home', 'pinned_home = environment.get(b"HOME")',
         'pinned_home = None', 'ReaderTests.test_pinned_home_fallback'),
        ('unavailable-home', 'except (OSError, ValueError, UnicodeError, KeyError, RuntimeError):',
         'except (OSError, ValueError, UnicodeError, KeyError):', 'ReaderTests.test_unavailable_home_is_typed'),
        ('closed-fd', 'continue  # this descriptor demonstrably closed during discovery',
         'return failure("descriptor_closed")', 'ReaderTests.test_closed_descriptor_does_not_poison_live_root'),
        ('picker', 'if flags & os.O_ACCMODE == os.O_RDONLY:', 'if False:', 'ReaderTests.test_readonly_picker_is_not_owner'),
        ('empty-writer', 'return failure("unclassified_empty_writable_rollout")',
         'continue', 'ReaderTests.test_empty_writer_is_temporarily_unclassified'),
        ('tail-budget', 'start = max(len(header), initial_size - max_bytes)',
         'start = len(header)', 'ReaderTests.test_large_history_uses_bounded_tail'),
        ('oversized-row', 'if skipping or len(raw) > max_line_bytes:',
         'if skipping:', 'ReaderTests.test_large_history_uses_bounded_tail'),
        ('skipped-compaction', 'yield None  # the skipped record may have been compaction',
         'pass  # mutation: retain stale precompaction tokens', 'ReaderTests.test_skipped_record_invalidates_token_accounting'),
        ('history-scope', 'result["history_complete"] = complete_history and not skipped_records',
         'result["history_complete"] = True', 'ReaderTests.test_large_history_uses_bounded_tail'),
        ('home-boundary', 'if not path.resolve().is_relative_to(sessions):',
         'if False:', 'ReaderTests.test_outside_home_and_pid'),
        ('plan-type', 'return value if isinstance(value, str) and _PLAN.fullmatch(value) else None',
         'return value if isinstance(value, str) else None', 'ParserTests.test_plan_and_credits_validated'),
        ('balance-exclusion', 'for key in ("has_credits", "unlimited")}',
         'for key in ("has_credits", "unlimited", "balance")}', 'ParserTests.test_projection'),
        ('balance-exclusion-reader', 'for key in ("has_credits", "unlimited")}',
         'for key in ("has_credits", "unlimited", "balance")}', 'ReaderTests.test_balance_never_exposed'),
        ('balance-exclusion-account', 'for key in ("has_credits", "unlimited")}',
         'for key in ("has_credits", "unlimited", "balance")}', 'AccountQuotaTests.test_output_is_content_free'),
        ('newest-timestamp', 'if key not in best or when > best[key][0]:',
         'if key not in best:', 'AccountQuotaTests.test_newest_timestamp_wins_over_newest_mtime'),
        ('newest-in-file', 'if key not in newest or when >= newest[key][0]:',
         'if True:', 'AccountQuotaTests.test_within_file_newest_record_and_per_bucket'),
        ('age-cutoff', 'or info.st_mtime < cutoff:', 'or False:', 'AccountQuotaTests.test_age_cutoff_boundary'),
        ('age-cutoff-boundary', 'cutoff = (now - _MAX_AGE).timestamp()',
         'cutoff = (now - _MAX_AGE * 2).timestamp()', 'AccountQuotaTests.test_age_cutoff_boundary'),
        ('symlink-rejection', 'if not stat.S_ISREG(info.st_mode) or info.st_mtime < cutoff:',
         'if info.st_mtime < cutoff:', 'AccountQuotaTests.test_symlink_not_opened'),
        ('no-follow', 'getattr(os, "O_NOFOLLOW", 0) | ', '', 'AccountQuotaTests.test_symlink_not_opened'),
        ('sessions-boundary', 'path.resolve().relative_to(sessions)  # ValueError when it escapes', 'pass', 'AccountQuotaTests.test_resolved_path_must_stay_under_sessions'),
        ('max-files', 'found[:max_files]', 'found', 'AccountQuotaTests.test_max_files_limits_candidates_by_mtime'),
        ('mtime-order', 'found.sort(key=lambda item: item[0], reverse=True)',
         'found.sort(key=lambda item: item[0])', 'AccountQuotaTests.test_max_files_limits_candidates_by_mtime'),
        ('tail-bound', 'start = max(0, size - window)', 'start = 0', 'AccountQuotaTests.test_tail_bytes_bound_and_partial_lines'),
        ('leading-partial', 'data = data[1:] if data[:1] == b"\\n" else data[data.find(b"\\n") + 1:] if b"\\n" in data else b""',
         'pass', 'AccountQuotaTests.test_leading_partial_line_dropped'),
        ('trailing-partial', 'data = data[:data.rfind(b"\\n") + 1]', 'pass', 'AccountQuotaTests.test_unfinished_trailing_line_ignored'),
        ('malformed-line', 'except (ValueError, RuntimeError):  # RecursionError on deeply nested input\n            continue',
         'except (ValueError, RuntimeError):  # RecursionError on deeply nested input\n            raise', 'AccountQuotaTests.test_skips_unusable_files_and_lines'),
        ('oversized-line', 'len(line) > max_line_bytes', 'False', 'AccountQuotaTests.test_oversized_line_skipped'),
        ('valid-timestamp', 'if stamp else None', 'if stamp else datetime.min.replace(tzinfo=timezone.utc)', 'AccountQuotaTests.test_missing_bucket_id_is_unknown_and_invalid_timestamps_skipped'),
        ('codex-home-relative', 'return codex_home if codex_home.is_absolute() else None',
         'return codex_home', 'CodexHomeTests.test_resolution_order'),
        ('no-recent', 'else "no_recent_rate_limits")', 'else "no_recent_rate_limits") and {"state": "observed"}', 'AccountQuotaTests.test_unavailable_states'),
        ('stop-comparison', '.timestamp() >= mtime + _SKEW_SECONDS)', '.timestamp() > mtime + 86400 * 365)', 'AccountQuotaTests.test_stops_early_when_bound_reached'),
        ('stop-removed', 'if (best and expected', 'if (False and expected', 'AccountQuotaTests.test_stops_early_when_bound_reached'),
        ('stop-bound-min', 'min(entry[0] for entry in best.values())', 'max(entry[0] for entry in best.values())', 'AccountQuotaTests.test_multi_bucket_bound_uses_oldest_bucket'),
        ('skew-margin', '>= mtime + _SKEW_SECONDS)', '>= mtime)', 'AccountQuotaTests.test_early_stop_skew_margin'),
        ('expected-buckets', 'expected <= best.keys()', 'True', 'AccountQuotaTests.test_expected_bucket_only_in_older_file'),
        ('backward-search', 'if window >= limit:', 'if True:', 'AccountQuotaTests.test_meterless_tail_searches_backwards'),
        ('search-cap', 'limit = max(tail_bytes, search_bytes)', 'limit = 10**12', 'AccountQuotaTests.test_meterless_window_is_incomplete_not_stale'),
        ('incomplete-flag', 'return provider, newest, False  # expected buckets may lie in unread bytes', 'return provider, newest, True', 'AccountQuotaTests.test_meterless_window_is_incomplete_not_stale'),
        ('incomplete-full-read', 'if start == 0 or (newest and expected <= newest.keys()):', 'if newest and expected <= newest.keys():', 'AccountQuotaTests.test_meterless_window_is_incomplete_not_stale'),
        ('recursion-line', 'except (ValueError, RuntimeError):  # RecursionError on deeply nested input', 'except ValueError:', 'AccountQuotaTests.test_deeply_nested_line_is_skipped'),
        ('header-cap', '_HEADER_BYTES = 64 * 1024', '_HEADER_BYTES = 640 * 1024', 'AccountQuotaTests.test_header_over_64k_has_no_provider'),
        ('bucket-coverage', 'if start == 0 or (newest and expected <= newest.keys()):', 'if start == 0 or newest:', 'AccountQuotaTests.test_partial_bucket_coverage_continues_backwards_in_file'),
        ('missing-buckets', 'missing = sorted(expected - best.keys())', 'missing = []', 'AccountQuotaTests.test_missing_expected_bucket_marks_incomplete'),
        ('read-new-chunk-only', 'raw = stream.read(hi - lo) + raw', 'raw = stream.read(size - lo)', 'AccountQuotaTests.test_backward_search_reads_each_byte_once'),
        ('entry-cap', 'if self.examined >= _MAX_ENTRIES:', 'if False:', 'AccountQuotaTests.test_entry_cap_marks_incomplete'),
        ('day-listing-budget', 'if not budget.spend():\n                                return', 'if False:\n                                return', 'AccountQuotaTests.test_huge_directory_is_pulled_lazily_up_to_the_cap'),
        ('dir-listing-budget', 'if not budget.spend():\n                    break', 'if False:\n                    break', 'AccountQuotaTests.test_old_dirs_budget'),
        ('day-validation', 'date(year, month, day)\n                except ValueError:\n                    continue', 'date(year, 1, 1)\n                except ValueError:\n                    continue', 'AccountQuotaTests.test_only_valid_day_directories_are_listed'),
        ('cap-uncertain', 'return provider, newest, False  # expected buckets may lie in unread bytes', 'return provider, newest, bool(newest)', 'AccountQuotaTests.test_expected_bucket_beyond_search_cap_is_uncertain'),
    ]
    source = MODULE.read_text()
    failed = []
    with tempfile.TemporaryDirectory(prefix='codex-status-mutations-') as temp:
        for name, old, new, test in mutations:
            if source.count(old) != 1:
                raise AssertionError('Mutation anchor drift: ' + name)
            changed = source.replace(old, new, 1)
            ast.parse(changed)  # syntax errors never count as a kill
            path = Path(temp) / (name + '.py')
            path.write_text(changed)
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), test],
                                 env=dict(os.environ, CODEX_STATUS_MODULE=str(path)),
                                 capture_output=True, text=True, timeout=30)
            output = run.stdout + run.stderr
            killed = run.returncode == 1 and re.search(r'FAILED \(failures=[1-9][0-9]*\)', output) and 'ERROR:' not in output
            print(name + ': ' + ('assertion failed as expected' if killed else 'INVALID OR SURVIVED'))
            if not killed:
                failed.append(name)
                print(output)
    print(f'{len(mutations) - len(failed)}/{len(mutations)} valid mutants caught by assertions')
    return int(bool(failed))


if __name__ == '__main__':
    if sys.argv[1:] == ['--mutation-check']:
        raise SystemExit(mutation_check())
    unittest.main()
