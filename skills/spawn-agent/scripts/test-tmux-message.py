#!/usr/bin/env python3
"""Behavior tests with a virtual clock and a simulated terminal, no model calls."""
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout, nullcontext
from unittest.mock import patch
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('delivery', Path(__file__).with_name('tmux-message.py'))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def screen(text='', history='', harness='codex', footer='  Any model · branch', prefix=''):
    if harness == 'claude':
        raw = prefix + '──────────────\n❯\u00a0' + text + '\n──────────────\n'
        y = len(prefix.splitlines()) + 1 + text.count('\n')
    else:
        raw = prefix + '› ' + text + '\n\n' + footer + '\n'
        y = len(prefix.splitlines()) + text.count('\n')
    return m.Frame(raw, 2 + m.styles.cell_width(text.rsplit('\n', 1)[-1]), y, history + raw)


CO_SUBMIT_FIXTURES = Path(__file__).with_name('fixtures') / 'claude-send'


def fixture_frame(name, marker='❯'):
    raw = (CO_SUBMIT_FIXTURES / name).read_text()
    rows = m.styles.strip_ansi(raw).splitlines()
    y = next(i for i, row in enumerate(rows) if marker in row)
    return m.Frame(raw, 2, y)


def claude_co_submit_frame(text='', receipt=True):
    rows = (CO_SUBMIT_FIXTURES / 'claude-co-submit-receipt.ansi').read_text().splitlines()
    if not receipt:
        start = next(i for i, row in enumerate(rows)
                     if row == '❯ Disposable retirement rehearsal reminder.')
        end = next(i for i, row in enumerate(rows[start:], start)
                   if row == '● ACK-QUEUE-3155db7fcc5e')
        del rows[start:end + 1]
    prompt = next(i for i, row in enumerate(rows) if row == '❯\u00a0')
    rows[prompt] = '❯\u00a0' + text
    raw = '\n'.join(rows) + '\n'
    return m.Frame(raw, 2 + m.styles.cell_width(text.rsplit('\n', 1)[-1]),
                   prompt + text.count('\n'), raw)


class Terminal:
    def __init__(self, payload='hello', dropped=0, collapsed=False, queued=False, delayed=0, draft='', mutate=False):
        self.payload, self.dropped, self.collapsed, self.queued = payload, dropped, collapsed, queued
        self.delayed, self.draft, self.mutate = delayed, draft, mutate
        self.now = 0
        self.pastes = 0
        self.enters = 0
        self.accepted_at = None
        self.history = ''
        self.actions = []
        self.pane = '%1'
        self.frames = 0
        self.submitted = None
        self.harness = 'codex'
        self.home = False
        self.end_moves = True
        self.end_paint_delay = 0
        self.end_requested_at = None
        self.end_unknown_frames = 0
        self.clear_mode = 'empty'
        self.clear_unknown_frames = 0
        self.clear_requested = False

    def sleep(self, n): self.now += n
    def clock(self): return self.now

    def frame(self):
        if self.clear_requested and self.clear_unknown_frames:
            self.clear_unknown_frames -= 1
            return m.Frame('', -1, -1)
        if self.end_requested_at is not None and self.end_unknown_frames:
            self.end_unknown_frames -= 1
            self.frames += 1
            return m.Frame("", -1, -1)
        if self.end_moves and self.end_requested_at is not None and self.now >= self.end_requested_at + self.end_paint_delay:
            self.home = False
        self.frames += 1
        history = self.history
        if self.accepted_at is not None and self.now >= self.accepted_at + self.delayed:
            glyph = '❯ ' if self.harness == 'claude' else '› '
            history += ('• Messages to be submitted after next tool call\n  ↳ ' if self.queued else glyph) + (self.submitted or self.payload).replace('\n', '\n  ') + '\n\n'
        text = self.draft
        if self.mutate and self.pastes:
            text += ' human'
        frame = screen(text, history, harness=self.harness, prefix='• output ' + str(self.frames) + '\n\n')
        if self.home:
            frame.x = 2
        return frame

    def paste(self, path):
        self.actions.append('paste')
        self.paste_at = self.now
        self.pastes += 1
        content = path.read_text()
        self.draft += (('\n' if self.draft and content.startswith('\n') else '') + '[Pasted text #1 +20 lines]') if self.collapsed else content

    def type_command(self, text):
        self.actions.append("typed:" + text)
        self.draft += text

    def keys(self, *keys):
        self.actions.extend(keys)
        if keys == ('End',) and self.end_moves:
            self.end_requested_at = self.now
            if not self.end_paint_delay:
                self.home = False
        if keys == ('C-u',):
            self.clear_requested = True
            if self.clear_mode == 'empty':
                self.draft = ''
            elif self.clear_mode == 'changed':
                self.draft = 'new human text'
        if keys == ('Enter',):
            self.enters += 1
            if self.enters > self.dropped:
                self.accepted_at = self.now
                self.submitted = self.draft
                self.draft = ''


class ClaudeExitTerminal(Terminal):
    session = '11111111-2222-3333-4444-555555555555'

    def __init__(self, **kw):
        super().__init__(payload='/exit', **kw)
        self.typed = 0

    def frame(self):
        self.frames += 1
        if self.accepted_at is not None and self.now >= self.accepted_at + self.delayed:
            history = self.history + 'Resume this session with:\nclaude --resume ' + self.session + '\nuser@host:~$ \n'
            return m.Frame(history, 14, len(history.splitlines()) - 1, history)
        text = self.draft + (' human' if self.mutate and self.typed else '')
        return screen(text, self.history, harness='claude')

    def keys(self, *keys):
        if keys == ('-l', '/exit'):
            self.typed += 1
            self.draft += '/exit'
            self.actions.extend(keys)
        else:
            super().keys(*keys)


def deliver(t, **kw):
    o = dict(max_wait=8, stable_wait=3, poll_interval=.25, backoff=False,
             submit_delay=1, render_wait=3, receipt_wait=8, retry_wait=3)
    o.update(kw)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'message'
        path.write_text(t.payload)
        return m.Sender(t, SimpleNamespace(**o), t.payload, path, t.clock, t.sleep).deliver()


class DeliveryTests(unittest.TestCase):
    def test_command_draft_cleared_without_execution_both_harnesses(self):
        for harness in ('codex', 'claude'):
            for command in ('/compact old context', '!echo old context'):
                for home in (False, True):
                    with self.subTest(harness=harness, command=command, home=home):
                        t = Terminal(draft=command)
                        t.harness, t.home = harness, home
                        result = deliver(t)
                        self.assertEqual(t.actions, (['End'] if home else []) + ['C-u', 'paste', 'Enter'])
                        self.assertEqual(t.submitted, t.payload)
                        self.assertEqual(result['cleared_command_draft_length'], len(command))
                        self.assertTrue(result['clear_attempted'])
                        self.assertNotIn('stale_draft_length', result)

    def test_command_clear_allows_typed_outgoing(self):
        t = Terminal(payload='/status', draft='/compact old context')
        result = deliver(t, typed_command=True)
        self.assertEqual(t.actions, ['C-u', 'typed:/status', 'Enter'])
        self.assertEqual(t.submitted, '/status')
        self.assertTrue(result['clear_attempted'])

    def test_command_like_invalid_or_replay_drafts_never_mutate(self):
        for draft in (' /compact', '/tmp/path', '/compact;', '/compact ' + 'x' * 200,
                      '/compact\ncontext', '!', '!echo\ncontext', '/compact hello',
                      '/compact [Pasted text #1 +2 lines]'):
            for harness in ('codex', 'claude'):
                with self.subTest(draft=draft, harness=harness):
                    t = Terminal(draft=draft)
                    t.harness = harness
                    with self.assertRaises(m.DeliveryError): deliver(t)
                    self.assertEqual(t.actions, [])

    def test_command_clear_unknown_repaint_then_empty(self):
        for harness in ('codex', 'claude'):
            t = Terminal(draft='/compact old context')
            t.harness, t.clear_unknown_frames = harness, 2
            deliver(t)
            self.assertEqual(t.actions, ['C-u', 'paste', 'Enter'])
            self.assertEqual(t.submitted, 'hello')

    def test_command_clear_failure_never_sends_or_claims_cleared(self):
        for mode, unknown in (('unchanged', 0), ('changed', 0), ('empty', 100)):
            for harness in ('codex', 'claude'):
                t = Terminal(draft='/compact old context')
                t.harness, t.clear_mode, t.clear_unknown_frames = harness, mode, unknown
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / 'message'
                    path.write_text('hello')
                    o = SimpleNamespace(max_wait=5, stable_wait=3, poll_interval=.25, backoff=False,
                                        typed_command=False, submit_delay=1, render_wait=3, receipt_wait=8, retry_wait=3)
                    sender = m.Sender(t, o, 'hello', path, t.clock, t.sleep)
                    with self.assertRaisesRegex(m.DeliveryError, 'command-clear-unverified'):
                        sender.deliver()
                    self.assertEqual(t.actions, ['C-u'])
                    self.assertTrue(sender.clear_attempted)
                    self.assertFalse(sender.pasted)
                    self.assertEqual(sender.cleared_command_draft_length, 0)

    def test_command_clear_failure_main_metadata_keeps_only_outgoing(self):
        for verified in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                pending = Path(tmp) / 'pending'
                pending.mkdir()
                t = Terminal(draft='/compact old context')
                t.identity = '0:%1'
                t.clear_mode = 'changed' if not verified else 'empty'
                original = t.frame
                count = 0
                def frame():
                    nonlocal count
                    if t.clear_requested:
                        count += 1
                        if verified and count == 2: t.draft = 'new human text'
                    return original()
                t.frame = frame
                o = m.options(['%1', '--stable-window', '0', '--submit-delay', '0', '--poll-interval', '.01', 'hello'])
                err = io.StringIO()
                with patch.object(m, 'options', return_value=o), patch.object(m, 'Tmux', return_value=t), patch.object(m, 'pane_lock', return_value=nullcontext()), patch.object(m.tempfile, 'mkdtemp', return_value=str(pending)), redirect_stderr(err):
                    self.assertEqual(m.main(), 3)
                result = json.loads(err.getvalue())
                self.assertEqual(result['status'], 'ambiguous')
                self.assertTrue(result['clear_attempted'])
                self.assertFalse(result['input_attempted'])
                self.assertFalse(result['paste_attempted'])
                self.assertTrue(result['needs_review'])
                self.assertEqual(result.get('cleared_command_draft_length', 0), 20 if verified else 0)
                self.assertNotIn('old context', err.getvalue())
                self.assertEqual((pending / 'message').read_bytes(), b'hello')

    def test_command_clear_known_modal_harness_or_cursor_change_stops(self):
        for kind in ('modal', 'harness', 'cursor'):
            t = Terminal(draft='/compact old context')
            old_frame = t.frame
            def frame():
                f = old_frame()
                if t.clear_requested:
                    if kind == 'modal': return m.Frame('Would you like to proceed?\n› yes\n', 2, 1)
                    if kind == 'harness': return screen('', harness='claude')
                    f.x = 3
                return f
            t.frame = frame
            with self.assertRaisesRegex(m.DeliveryError, 'command-clear-unverified'): deliver(t)
            self.assertEqual(t.actions, ['C-u'])

    def test_command_draft_changing_or_final_preclear_race_no_keys(self):
        for continuous in (False, True):
            t = Terminal(draft='/compact old context')
            old_frame = t.frame
            def frame():
                if continuous or t.frames == 2: t.draft += 'x'
                return old_frame()
            t.frame = frame
            with self.assertRaises(m.DeliveryError): deliver(t, stable_wait=0)
            self.assertEqual(t.actions, [])

    def test_command_trailing_blank_rows_at_home_never_clear(self):
        for harness in ('codex', 'claude'):
            t = Terminal(draft='/compact\n')
            t.harness, t.home = harness, True
            old_frame = t.frame
            def frame():
                f = old_frame()
                f.y -= 1
                return f
            t.frame = frame
            with self.assertRaises(m.DeliveryError): deliver(t)
            self.assertEqual(t.actions, [])

    def test_command_clear_tmux_failure_main_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / 'pending'
            pending.mkdir()
            t = Terminal(draft='/compact old context')
            t.identity = '0:%1'
            def keys(*keys):
                t.actions.extend(keys)
                raise OSError('private tmux detail')
            t.keys = keys
            o = m.options(['%1', '--stable-window', '0', '--poll-interval', '.01', 'hello'])
            err = io.StringIO()
            with patch.object(m, 'options', return_value=o), patch.object(m, 'Tmux', return_value=t), patch.object(m, 'pane_lock', return_value=nullcontext()), patch.object(m.tempfile, 'mkdtemp', return_value=str(pending)), redirect_stderr(err):
                self.assertEqual(m.main(), 3)
            result = json.loads(err.getvalue())
            self.assertEqual(result['status'], 'ambiguous')
            self.assertTrue(result['clear_attempted'])
            self.assertTrue(result['needs_review'])
            self.assertFalse(result['input_attempted'])
            self.assertFalse(result['paste_attempted'])
            self.assertNotIn('cleared_command_draft_length', result)
            self.assertEqual(t.actions, ['C-u'])

    def test_command_clear_final_empty_recheck_protects_new_text(self):
        t = Terminal(draft='/compact old context')
        old_frame = t.frame
        count = 0
        def frame():
            nonlocal count
            if t.clear_requested:
                count += 1
                if count == 2: t.draft = 'new human text'
            return old_frame()
        t.frame = frame
        with self.assertRaisesRegex(m.DeliveryError, 'input-changed-after-clear'):
            deliver(t)
        self.assertEqual(t.actions, ['C-u'])

    def test_literal_and_typed_modes_conflict_before_input(self):
        t = ClaudeExitTerminal()
        with self.assertRaisesRegex(m.DeliveryError, 'conflicting-input-modes'):
            deliver(t, literal_exit=True, typed_command=True)
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 0, 0))

    def test_response_rows_exclude_live_composer_and_archive(self):
        for harness in ('codex', 'claude'):
            f = screen('● RETIRE-DONE-in-draft', history='● archived marker\n',
                       prefix='● visible response\n\n', harness=harness)
            with patch.object(m, 'Tmux') as t:
                t.return_value.frame.return_value = f
                self.assertEqual(m.read_response_rows('%1', '/tmp/test-socket'),
                                 ['● visible response', ''] if harness == 'codex' else ['● visible response', '', '──────────────'])
                t.assert_called_once_with('%1', socket='/tmp/test-socket')
                t.return_value.keys.assert_not_called()
                t.return_value.paste.assert_not_called()

    def test_response_rows_unknown_modal_and_failed_read(self):
        for f in (m.Frame('', -1, -1), fixture_frame('claude-2.1.302-permission-modal.ansi')):
            with patch.object(m, 'Tmux') as t:
                t.return_value.frame.return_value = f
                self.assertIsNone(m.read_response_rows('%1', '/tmp/test-socket'))
        with patch.object(m, 'Tmux', side_effect=OSError('private detail')):
            with self.assertRaisesRegex(m.DeliveryError, 'observation-read-failed'):
                m.read_response_rows('%1', '/tmp/test-socket')
        for error in (TypeError, IndexError, KeyError):
            with self.subTest(error=error), patch.object(m, 'Tmux'), patch.object(m, 'composer', side_effect=error('private frame detail')):
                with self.assertRaisesRegex(m.DeliveryError, 'observation-read-failed'):
                    m.read_response_rows('%1', '/tmp/test-socket')
        with self.assertRaisesRegex(m.DeliveryError, 'invalid-observation-target'):
            m.read_response_rows('session:window', 'relative')

    def test_observation_socket_is_explicit_without_global_env_change(self):
        import os
        before = dict(os.environ)
        with patch.dict(os.environ, {'SPAWN_TMUX_LABEL': 'stale-server'}), patch.object(m.subprocess, 'run') as run:
            run.return_value.stdout = '123:%1'
            t = m.Tmux('%1', socket='/tmp/pinned-socket')
            self.assertEqual(t.base, ['tmux', '-S', '/tmp/pinned-socket'])
            self.assertEqual(run.call_args.kwargs['env']['SPAWN_TMUX_SOCKET'], '/tmp/pinned-socket')
            self.assertNotIn('SPAWN_TMUX_LABEL', run.call_args.kwargs['env'])
        self.assertEqual(dict(os.environ), before)

    def test_success_input_method_matches_actual_transport(self):
        for t, options, method in ((Terminal(), {}, 'paste'),
                                   (Terminal(payload='/status'), {'typed_command': True}, 'typed'),
                                   (ClaudeExitTerminal(), {'literal_exit': True}, 'typed')):
            with self.subTest(method=method, options=options):
                result = deliver(t, **options)
                self.assertEqual(result['status'], 'delivered')
                self.assertEqual(result['input_method'], method)
                if options.get('literal_exit'):
                    self.assertEqual(result['transport'], 'literal')
                    self.assertEqual(result['receipt'], 'command')
                    self.assertEqual(t.typed, 1)
                elif method == 'typed':
                    self.assertIn('typed:/status', t.actions)
                    self.assertEqual(t.pastes, 0)
                else:
                    self.assertEqual(t.pastes, 1)
                self.assertEqual(t.enters, 1)

    def test_literal_claude_exit_fresh_resume_receipt(self):
        t = ClaudeExitTerminal(delayed=2)
        t.history = 'Resume this session with:\nclaude --resume ' + t.session + '\n'
        result = deliver(t, literal_exit=True)
        self.assertEqual(result['receipt'], 'command')
        self.assertEqual(result['resume_session_id'], t.session)
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 1, 1))

    def test_literal_exit_canonical_idle_placeholder(self):
        class Ghost(ClaudeExitTerminal):
            def frame(self):
                if not self.typed:
                    f = screen('Try "summarize this work"', harness='claude')
                    f.x = 2
                    return f
                return super().frame()
        t = Ghost()
        self.assertEqual(deliver(t, literal_exit=True)['receipt'], 'command')
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 1, 1))
        self.assertNotIn('Space', t.actions)

    def test_literal_exit_suggestion_shaped_actual_draft(self):
        t = ClaudeExitTerminal(draft='Try "my draft"')
        with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 0, 0))

    def test_literal_exit_noncanonical_suggestion_stays_protected(self):
        t = ClaudeExitTerminal()
        f = screen('Try unquoted draft', harness='claude')
        f.x = 2
        t.frame = lambda: f
        with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 0, 0))

    def test_literal_exit_swallowed_enter_never_retries(self):
        t = ClaudeExitTerminal(dropped=99)
        t.history = 'Resume this session with:\nclaude --resume ' + t.session + '\n'
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 1, 1))

    def test_literal_exit_old_resume_in_shell_cannot_confirm(self):
        class NoNewNotice(ClaudeExitTerminal):
            def frame(self):
                if self.accepted_at is not None:
                    history = self.history + 'user@host:~$ \n'
                    return m.Frame(history, 14, len(history.splitlines()) - 1, history)
                return super().frame()
        t = NoNewNotice()
        t.history = 'Resume this session with:\nclaude --resume ' + t.session + '\n'
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 1, 1))

    def test_literal_exit_protects_draft_and_mixed_input(self):
        t = ClaudeExitTerminal(draft='human draft')
        with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.typed, t.enters), (0, 0))
        t = ClaudeExitTerminal(mutate=True)
        with self.assertRaisesRegex(m.DeliveryError, 'mixed-input'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.typed, t.enters), (1, 0))

    def test_literal_exit_rejects_other_harness_and_payload(self):
        t = Terminal(payload='/exit')
        with self.assertRaisesRegex(m.DeliveryError, 'requires-claude-exit'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.pastes, t.enters), (0, 0))
        t = ClaudeExitTerminal()
        t.payload = 'ordinary task'
        with self.assertRaisesRegex(m.DeliveryError, 'requires-claude-exit'):
            deliver(t, literal_exit=True)
        self.assertEqual((t.pastes, t.typed, t.enters), (0, 0, 0))
    def test_typed_commands_never_paste(self):
        for command in ('/compact', '/exit', '/status', '/model example'):
            t = Terminal(payload=command)
            self.assertEqual(deliver(t, typed_command=True)['status'], 'delivered')
            self.assertEqual(t.pastes, 0)
            self.assertEqual(t.actions, ['typed:' + command, 'Enter'])

    def test_typed_command_rejects_multiline_and_noncommands(self):
        for command in (' /exit', '/compact\n', 'hello', '/x\targument', '/x\n/exit'):
            t = Terminal(payload=command)
            with self.assertRaisesRegex(m.DeliveryError, 'unsupported-typed-command'):
                deliver(t, typed_command=True)
            self.assertEqual(t.actions, [])

    def test_typed_command_rejects_unrenderable_tail_and_length(self):
        for command in ('/model x ', '/model x;', '/model x\u3000', '/model x\u2003', '/model ' + 'x' * 194):
            t = Terminal(payload=command)
            with self.assertRaisesRegex(m.DeliveryError, 'unsupported-typed-command'):
                deliver(t, typed_command=True)
            self.assertEqual(t.actions, [])

    def test_typed_validation_failure_reports_no_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / 'pending'
            pending.mkdir()
            err = io.StringIO()
            with patch.object(m, 'options', return_value=m.options(['%1', '--typed-command', '/x '])), patch.object(m, 'Tmux', return_value=SimpleNamespace(identity='0:%1', pane='%1')), patch.object(m, 'pane_lock', return_value=nullcontext()), patch.object(m.Sender, 'deliver', return_value={'status': 'delivered'}), redirect_stdout(io.StringIO()), patch.object(m.tempfile, 'mkdtemp', return_value=str(pending)), redirect_stderr(err):
                self.assertEqual(m.main(), 2)
            result = json.loads(err.getvalue())
            self.assertEqual(result['input_method'], 'typed')
            self.assertFalse(result['input_attempted'])
            self.assertFalse(result['paste_attempted'])
            self.assertEqual(result['status'], 'deferred')

    def test_typed_command_preserves_draft_and_modal(self):
        for modal in (False, True):
            t = Terminal(payload='/exit', draft='human draft')
            if modal:
                t.frame = lambda: m.Frame('Would you like to proceed?\n› yes\n', 2, 1)
            with self.assertRaises(m.DeliveryError):
                deliver(t, typed_command=True)
            self.assertEqual(t.actions, [])

    def test_typed_command_rejects_mixed_or_collapsed_input(self):
        for content in ('/exit human', '[Pasted text #1 +2 lines]'):
            t = Terminal(payload='/exit')
            def type_command(text):
                t.actions.append('typed:' + text)
                t.draft = content
            t.type_command = type_command
            with self.assertRaises(m.DeliveryError):
                deliver(t, typed_command=True)
            self.assertEqual(t.enters, 0)

    def test_literal_tmux_command_argv(self):
        t = object.__new__(m.Tmux)
        t.pane = '%9'
        calls = []
        t.run = lambda *args: calls.append(args)
        t.type_command('/compact')
        self.assertEqual(calls, [('send-keys', '-t', '%9', '-l', '--', '/compact')])
        self.assertTrue(m.options(['%1', '--typed-command', '/exit']).typed_command)

    def test_blocks_until_delayed_receipt_without_extra_enter(self):
        t = Terminal(delayed=5)
        self.assertEqual(deliver(t)['status'], 'delivered')
        self.assertGreaterEqual(t.now, t.accepted_at + 5)
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_swallowed_enter_recovers_once(self):
        t = Terminal(dropped=1)
        self.assertEqual(deliver(t)['enters'], 2)
        self.assertEqual(t.pastes, 1)

    def test_collapsed_paste_recovers_and_confirms_queue(self):
        t = Terminal(payload='long\nactual message', dropped=1, collapsed=True, queued=True)
        self.assertEqual(deliver(t)['receipt'], 'queued')
        self.assertEqual((t.pastes, t.enters), (1, 2))

    def test_retry_bounded(self):
        t = Terminal(dropped=99)
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 2))

    def test_old_receipt_cannot_confirm(self):
        t = Terminal(dropped=99)
        t.history = '› hello\n\n'
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t)

    def test_new_identical_receipt_counts(self):
        t = Terminal()
        t.history = '› hello\n\n'
        self.assertEqual(deliver(t)['status'], 'delivered')

    def test_mixed_input_stops_before_enter(self):
        t = Terminal(mutate=True)
        with self.assertRaisesRegex(m.DeliveryError, 'mixed-input'):
            deliver(t)
        self.assertEqual(t.enters, 0)

    def test_stable_draft_cosubmitted_codex_and_claude(self):
        for harness in ('codex', 'claude'):
            with self.subTest(harness=harness):
                t = Terminal(draft='stale TICK')
                t.harness = harness
                original = t.frame
                fixtures = Path(__file__).with_name('fixtures') / 'claude-send'
                def initial():
                    if not t.pastes:
                        x, y = map(int, (fixtures / (harness + '-stable-draft.cursor')).read_text().split(':'))
                        return m.Frame((fixtures / (harness + '-stable-draft.ansi')).read_text(), x, y)
                    return original()
                t.frame = initial
                try:
                    result = deliver(t)
                except m.DeliveryError as error:
                    self.fail("stable draft deferred: " + error.reason)
                self.assertEqual(t.submitted, 'stale TICK\nhello')
                self.assertEqual((t.pastes, t.enters), (1, 1))
                self.assertEqual(result['stale_draft_length'], len('stale TICK'))
                self.assertNotIn('stale TICK', json.dumps(result))

    def test_stable_home_draft_navigates_then_appends_both_harnesses(self):
        for harness in ('codex', 'claude'):
            with self.subTest(harness=harness):
                t = Terminal(draft='stale TICK')
                t.home, t.harness = True, harness
                try:
                    result = deliver(t)
                except m.DeliveryError as error:
                    self.fail('Home draft deferred: ' + error.reason)
                self.assertEqual(result['status'], 'delivered')
                self.assertEqual(t.actions, ['End', 'paste', 'Enter'])
                self.assertEqual(t.submitted, 'stale TICK\nhello')

    def test_home_end_delayed_repaint_waits_without_more_keys(self):
        for harness in ('codex', 'claude'):
            with self.subTest(harness=harness):
                t = Terminal(draft='stale TICK')
                t.home, t.harness, t.end_paint_delay = True, harness, .5
                try:
                    result = deliver(t, stable_wait=0, max_wait=1)
                except m.DeliveryError as error:
                    self.fail('unchanged Home repaint deferred: ' + error.reason)
                self.assertEqual(result['status'], 'delivered')
                self.assertEqual(t.actions, ['End', 'paste', 'Enter'])
                self.assertGreaterEqual(t.paste_at, t.end_requested_at + .5)
                self.assertEqual(t.submitted, 'stale TICK\nhello')

    def test_home_end_unknown_repaint_then_known_end(self):
        for harness in ('codex', 'claude'):
            with self.subTest(harness=harness):
                t = Terminal(draft='stale TICK')
                t.home, t.harness, t.end_unknown_frames = True, harness, 2
                try:
                    result = deliver(t, stable_wait=0, max_wait=1)
                except m.DeliveryError as error:
                    self.fail('unknown repaint deferred before budget: ' + error.reason)
                self.assertEqual(result['status'], 'delivered')
                self.assertEqual(t.actions, ['End', 'paste', 'Enter'])
                self.assertEqual(t.submitted, 'stale TICK\nhello')

    def test_home_end_persistent_unknown_times_out_without_input(self):
        t = Terminal(draft='stale TICK')
        t.home, t.end_unknown_frames = True, 99
        o = SimpleNamespace(max_wait=1, stable_wait=0, poll_interval=.25, backoff=False)
        sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
        with self.assertRaisesRegex(m.DeliveryError, 'cursor-navigation-unverified'):
            sender.deliver()
        self.assertEqual(t.now, 1)
        self.assertFalse(sender.pasted)
        self.assertEqual(t.actions, ['End'])

    def test_home_end_known_changed_frames_fail_without_wait_or_input(self):
        for kind in ('text', 'harness', 'modal', 'middle', 'empty'):
            with self.subTest(kind=kind):
                t = Terminal(draft='stale TICK')
                t.home = True
                original = t.frame
                def changed_frame():
                    if t.end_requested_at is not None:
                        if kind == 'modal':
                            return m.Frame('Would you like to proceed?\n› yes\n', 2, 1)
                        if kind == 'text':
                            t.draft = 'human changed text'
                        if kind == 'harness':
                            t.harness = 'claude'
                        if kind == 'empty':
                            t.draft = ''
                    frame = original()
                    if t.end_requested_at is not None and kind == 'middle':
                        frame.x = 4
                    return frame
                t.frame = changed_frame
                o = SimpleNamespace(max_wait=1, stable_wait=0, poll_interval=.25, backoff=False)
                sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
                with self.assertRaisesRegex(m.DeliveryError, 'cursor-navigation-unverified'):
                    sender.deliver()
                self.assertEqual(t.now, t.end_requested_at)
                self.assertFalse(sender.pasted)
                self.assertEqual(t.actions, ['End'])

    def test_home_end_not_moving_or_text_changes_defers_without_paste(self):
        for harness in ('codex', 'claude'):
            for change in (False, True):
                with self.subTest(harness=harness, change=change):
                    t = Terminal(draft='stale TICK')
                    t.home, t.harness, t.end_moves = True, harness, change
                    original = t.keys
                    def keys(*keys):
                        original(*keys)
                        if change and keys == ('End',):
                            t.draft = 'human changed text'
                    t.keys = keys
                    with self.assertRaisesRegex(m.DeliveryError, 'cursor-navigation-unverified'):
                        deliver(t)
                    self.assertEqual(t.actions, ['End'])
                    self.assertEqual((t.pastes, t.enters), (0, 0))

    def test_stable_draft_requires_cursor_at_end(self):
        t = Terminal(draft='stale TICK')
        original = t.frame
        def midtext():
            frame = original()
            frame.x = 4
            return frame
        t.frame = midtext
        with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
            deliver(t)
        self.assertEqual(t.actions, [])

    def test_zero_window_still_observes_twice(self):
        t = Terminal(draft='stale TICK')
        original = t.frame
        def second():
            if t.frames == 1:
                t.draft = 'human changed this'
            return original()
        t.frame = second
        with self.assertRaisesRegex(m.DeliveryError, 'human-typing'):
            deliver(t, stable_wait=0)
        self.assertEqual(t.actions, [])

    def test_stable_window_defaults_and_alias(self):
        for delay in ('0', '8', '12'):
            self.assertEqual(m.options(['%1', '--submit-delay', delay, 'hello']).stable_window, float(delay))
        for flag in ('--stable-window', '--stable-wait'):
            self.assertEqual(m.options(['%1', flag, '2', 'hello']).stable_window, 2)

    def test_zero_window_backoff_requires_unchanged_pair(self):
        t = Terminal(draft='typing')
        original = t.frame
        def changing():
            t.draft = 'typing ' + str(t.frames)
            return original()
        t.frame = changing
        o = SimpleNamespace(max_wait=1, stable_wait=0, poll_interval=.25, backoff=True)
        sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
        with self.assertRaisesRegex(m.DeliveryError, 'human-typing'):
            sender.ready()
        self.assertEqual(t.now, 1)
        self.assertEqual(t.actions, [])

    def test_zero_window_one_change_waits_for_repeated_sample(self):
        t = Terminal(draft='first')
        original = t.frame
        def changing_once():
            if t.frames == 1:
                t.draft = 'second'
            return original()
        t.frame = changing_once
        o = SimpleNamespace(max_wait=1, stable_wait=0, poll_interval=.25, backoff=True)
        sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
        self.assertEqual(sender.ready()[1].text, 'second')
        self.assertGreaterEqual(t.frames, 3)
        self.assertEqual(t.actions, [])

    def test_append_failure_metadata_and_allocation_not_attempted(self):
        for allocation_failure in (True, False):
            with self.subTest(allocation_failure=allocation_failure), tempfile.TemporaryDirectory() as tmp:
                pending = Path(tmp) / 'pending'
                pending.mkdir()
                t = Terminal(draft='stale TICK', mutate=not allocation_failure)
                t.identity = '0:%1'
                o = m.options(['%1', '--stable-window', '0', '--submit-delay', '0', '--poll-interval', '.01', 'hello'])
                err = io.StringIO()
                allocation = patch.object(m.tempfile, 'NamedTemporaryFile', side_effect=OSError('private detail')) if allocation_failure else nullcontext()
                with patch.object(m, 'options', return_value=o), patch.object(m, 'Tmux', return_value=t), patch.object(m, 'pane_lock', return_value=nullcontext()), patch.object(m.tempfile, 'mkdtemp', return_value=str(pending)), allocation, redirect_stderr(err):
                    self.assertEqual(m.main(), 2 if allocation_failure else 3)
                result = json.loads(err.getvalue())
                self.assertEqual(result['stale_draft_length'], 10)
                self.assertEqual(result['input_attempted'], not allocation_failure)
                self.assertEqual(result['paste_attempted'], not allocation_failure)
                self.assertNotIn('stale TICK', err.getvalue())
                self.assertEqual((pending / 'message').read_bytes(), b'hello')

    def test_collapsed_append_stops_and_cannot_replay(self):
        for harness in ('codex', 'claude'):
            t = Terminal(draft='stale TICK', collapsed=True)
            t.harness = harness
            with self.assertRaisesRegex(m.DeliveryError, 'mixed-input'):
                deliver(t)
            self.assertEqual((t.pastes, t.enters), (1, 0))
            first_actions = list(t.actions)
            with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
                deliver(t)
            self.assertEqual(t.actions, first_actions)

    def test_stale_draft_combined_enter_recovery(self):
        t = Terminal(draft='stale TICK', dropped=1)
        self.assertEqual(deliver(t)['enters'], 2)
        self.assertEqual((t.pastes, t.submitted), (1, 'stale TICK\nhello'))

    def test_stale_draft_failure_keeps_only_outgoing_pending(self):
        t = Terminal(draft='stale TICK', mutate=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'message'
            path.write_text(t.payload)
            o = SimpleNamespace(max_wait=8, stable_wait=3, poll_interval=.25,
                                backoff=False, submit_delay=1, render_wait=3,
                                receipt_wait=8, retry_wait=3)
            sender = m.Sender(t, o, t.payload, path, t.clock, t.sleep)
            with self.assertRaisesRegex(m.DeliveryError, 'mixed-input'):
                sender.deliver()
            self.assertEqual(path.read_text(), 'hello')
            self.assertEqual(list(Path(tmp).iterdir()), [path])
            self.assertEqual(t.enters, 0)

    def test_combined_residue_two_attempts_never_repastes(self):
        for harness in ('codex', 'claude'):
            with self.subTest(harness=harness):
                t = Terminal(draft='stale TICK', dropped=99)
                t.harness = harness
                with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
                    deliver(t)
                self.assertEqual(t.draft, 'stale TICK\nhello')
                first_actions = list(t.actions)
                try:
                    deliver(t)
                except m.DeliveryError:
                    pass
                self.assertEqual(t.actions, first_actions, 'retained combined input was replayed')
                self.assertEqual(t.pastes, 1)

    def test_mixed_own_payload_residue_both_harnesses(self):
        for harness in ('codex', 'claude'):
            for draft in ('hello human', 'human hello', 'human he\nllo'):
                with self.subTest(harness=harness, draft=draft):
                    t = Terminal(draft=draft)
                    t.harness = harness
                    try:
                        deliver(t)
                    except m.DeliveryError:
                        pass
                    self.assertEqual(t.actions, [], 'recognizable outgoing content was replayed')

    def test_observe_private_draft_file_utf8_in_ascii_locale(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'draft'
            child = r"""
import importlib.util, locale, pathlib, sys
sys.dont_write_bytecode = True
assert sys.flags.utf8_mode == 0
assert locale.getpreferredencoding(False).lower() in {'ascii', 'ansi_x3.4-1968'}
spec = importlib.util.spec_from_file_location('screen', sys.argv[1])
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)
draft = 'caf\u00e9'
frame = '\u2500' * 40 + '\n\u276f\u00a0' + draft + '\n' + '\u2500' * 40 + '\n'
assert screen.observe(frame, 'outgoing', 6, 1, pathlib.Path(sys.argv[2])) == 'draft'
"""
            env = dict(os.environ, LC_ALL='C', PYTHONUTF8='0', PYTHONCOERCECLOCALE='0')
            result = subprocess.run([sys.executable, '-c', child,
                                     str(Path(__file__).with_name('claude-send-screen.py')), str(path)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_bytes(), 'caf\u00e9'.encode('utf-8'))

    def test_partial_outgoing_overlap_is_still_a_stale_draft(self):
        for draft in ('he human', 'world hell', 'ello'):
            t = Terminal(draft=draft)
            self.assertEqual(deliver(t)['status'], 'delivered')
            self.assertEqual(t.submitted, draft + '\nhello')
            self.assertEqual(t.pastes, 1)

    def test_existing_ambiguous_payload_never_reappended(self):
        for draft in ('hello', '[Pasted text #1 +20 lines]', '[Pasted Content 5 chars]'):
            t = Terminal(draft=draft)
            with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
                deliver(t)
            self.assertEqual(t.actions, [])

    def test_change_only_at_second_observation_defers(self):
        t = Terminal(draft='stale TICK')
        original = t.frame
        def second():
            if t.now >= 3:
                t.draft = 'new human text'
            return original()
        t.frame = second
        with self.assertRaisesRegex(m.DeliveryError, 'human-typing'):
            deliver(t)
        self.assertEqual(t.actions, [])

    def test_typing_exits_without_paste(self):
        t = Terminal(draft='draft')
        original = t.frame
        def changing():
            t.draft = 'draft ' + str(int(t.now))
            return original()
        t.frame = changing
        with self.assertRaisesRegex(m.DeliveryError, 'human-typing'):
            deliver(t)
        self.assertEqual(t.pastes, 0)

    def test_backoff_waits_until_human_submits(self):
        t = Terminal(draft='draft')
        original = t.frame
        def changing():
            if not t.pastes:
                t.draft = 'draft' if t.now < 2 else ''
            return original()
        t.frame = changing
        self.assertEqual(deliver(t, backoff=True)['status'], 'delivered')
        self.assertGreaterEqual(t.accepted_at, 6)

    def test_modal_no_keys(self):
        t = Terminal()
        t.frame = lambda: m.Frame('Would you like to proceed?\n› yes\n', 2, 1)
        with self.assertRaisesRegex(m.DeliveryError, 'modal'):
            deliver(t)
        self.assertEqual(t.actions, [])

    def test_claude_status_footers_are_not_modals(self):
        # Text from the incident report supplements the labeled ANSI captures.
        footers = (
            'Usage limit reached · continuing automatically at 12pm · esc to cancel',
            '✘ Auto-update failed: no write permission to npm prefix · Run claude doctor',
            'new task? /clear to save 319.9k tokens · globalVersion: 2.1.301 · latestVersion: 2.1.302',
            '1 feedback draft',
            '12 feedback drafts',
        )
        for footer in footers:
            with self.subTest(footer=footer):
                frame = screen(harness='claude', prefix=footer + '\n')
                self.assertEqual(m.composer(frame).kind, 'empty')
                self.assertEqual(m.composer(frame).harness, 'claude')

    def test_claude_dialogs_and_footers_by_fixture(self):
        fixtures = (
            ('claude-2.1.302-login-modal.ansi', 'modal'),
            ('claude-2.1.302-trust-modal.ansi', 'modal'),
            ('claude-2.1.302-permission-modal.ansi', 'modal'),
            ('claude-2.1.302-exit-background-modal.ansi', 'modal'),
            ('SYNTHETIC-UNVERIFIED-claude-unsent-feedback-exit-dialog.ansi', 'modal'),
            ('claude-2.1.302-auto-update-footer-live-scrubbed.ansi', 'empty'),
            ('claude-2.1.299-feedback-count-footer-live-scrubbed.ansi', 'empty'),
            ('SYNTHETIC-claude-2.1.302-usage-limit-footer.ansi', 'empty'),
            ('SYNTHETIC-claude-2.1.302-new-task-footer.ansi', 'empty'),
        )
        for name, expected in fixtures:
            with self.subTest(name=name):
                frame = fixture_frame(name)
                result = m.composer(frame)
                self.assertEqual(result.kind, expected)
                if expected == 'empty':
                    self.assertEqual(result.harness, 'claude')

    def test_synthetic_update_dialog_defers(self):
        raw = (CO_SUBMIT_FIXTURES / 'SYNTHETIC-claude-update-dialog.ansi').read_text()
        frame = m.Frame(raw, 0, 3)
        self.assertEqual(m.composer(frame).kind, 'modal')
        t = Terminal()
        t.frame = lambda: frame
        with self.assertRaisesRegex(m.DeliveryError, 'modal'):
            deliver(t)
        self.assertEqual(t.actions, [])

    def test_yes_draft_with_usage_footer_is_not_modal_without_cursor(self):
        raw = (CO_SUBMIT_FIXTURES / 'SYNTHETIC-claude-yes-draft-usage-footer.ansi').read_text()
        self.assertIn('❯\u00a0', raw)
        self.assertIsNotNone(m.styles.claude_composer_frame(raw))
        self.assertFalse(m.styles.dialog_active(raw))
        self.assertEqual(m.composer(m.Frame(raw, 2 + len('Yes, please continue the work.'), 2)).kind, 'text')

    def test_bare_cancel_text_is_not_a_dialog(self):
        frame = screen(harness='claude', prefix='Esc to cancel\n')
        self.assertEqual(m.composer(frame).kind, 'empty')

    def test_framed_choice_still_defers_without_a_known_title(self):
        raw = '────────────────\n❯ No, exit\n  Yes, I accept\nEnter to confirm · Esc to cancel\n'
        self.assertEqual(m.composer(m.Frame(raw, 2, 1)).kind, 'modal')
        self.assertFalse(m.styles.dialog_active('No, exit\nEsc to cancel\n'))
        boxed = '────────────────\nDo you want to proceed?\n❯ 1. Yes\n────────────────\n'
        self.assertEqual(m.composer(m.Frame(boxed, 2, 2)).kind, 'modal')
        quoted = m.Frame('Quick safety check\n❯ No, exit\n──────────────\n❯\u00a0\n──────────────\n', 2, 3)
        self.assertEqual(m.composer(quoted).kind, 'empty')

    def test_wrapped_update_prompt_is_modal(self):
        raw = 'Update available!\nPress enter to\ncontinue\n'
        self.assertEqual(m.composer(m.Frame(raw, 0, 2)).kind, 'modal')

    def test_unfamiliar_framed_choice_is_not_writable(self):
        for title, selected in (('Choose an account:\n', '❯ 1. Foo'),
                                ('', '❯ 1. Foo'),
                                ('Choose an account:\n', '❯\u00a0')):
            raw = '────────────────\n' + title + selected + '\n  2. Bar\n────────────────\n'
            frame = m.Frame(raw, 2, 1 + bool(title))
            self.assertEqual(m.composer(frame).kind, 'unknown')
            t = Terminal()
            t.frame = lambda: frame
            with self.assertRaises(m.DeliveryError):
                deliver(t)
            self.assertEqual(t.actions, [])

    def test_synthetic_codex_approval_choice_still_defers(self):
        raw = ('Would you like to run this command?\n'
               '› 1. Yes, proceed\n'
               '  2. No\n'
               'Press enter to confirm · Esc to cancel\n'
               '  Any model · Context 50% left\n')
        frame = m.Frame(raw, 2, 1)
        self.assertEqual(m.composer(frame).kind, 'modal')
        t = Terminal()
        t.frame = lambda: frame
        with self.assertRaisesRegex(m.DeliveryError, 'modal'):
            deliver(t)
        self.assertEqual(t.actions, [])

    def test_synthetic_codex_approval_with_unfamiliar_title_still_defers(self):
        raw = ('Edit approval required?\n'
               '› 1. Yes, proceed\n'
               '  2. No\n\n'
               'Press enter to confirm · Esc to cancel\n'
               '  Any model · Context 50% left\n')
        frame = m.Frame(raw, 2, 1)
        self.assertEqual(m.composer(frame).kind, 'modal')
        t = Terminal()
        t.frame = lambda: frame
        with self.assertRaisesRegex(m.DeliveryError, 'modal'):
            deliver(t)
        self.assertEqual(t.actions, [])

    def test_ordinary_codex_choice_words_and_numbered_drafts_remain_writable(self):
        for payload in ('Yes, proceed', 'No.', '1. Fix X\n  2. Verify Y'):
            with self.subTest(payload=payload):
                frame = screen(payload, footer='  Any model · Context 50% left')
                self.assertEqual(m.composer(frame).kind, 'text')
                t = Terminal(payload=payload)
                result = deliver(t)
                self.assertEqual(result['status'], 'delivered')
                self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_wrapped_and_multiline_composers(self):
        for harness in ['codex', 'claude']:
            f = screen('A long message\n  with another line', harness=harness)
            inp = m.composer(f)
            self.assertEqual(inp.kind, 'text')
            self.assertTrue(m.paste_evidence(inp, 'A long message with another line'))

    def test_assistant_echo_not_receipt(self):
        f = screen(history='• The message was hello\n\n')
        self.assertEqual(m.records(f, m.composer(f))[('submitted', 'hello')], 0)

    def test_collapsed_history_does_not_prove_receipt(self):
        f = screen(history='› [Pasted text #1 +20 lines]\n\n')
        self.assertEqual(m.records(f, m.composer(f))[('submitted', 'hello')], 0)

    def test_long_compaction_receipt_budget_is_supported(self):
        self.assertEqual(m.options(['%1', '--receipt-wait', '900', '/compact']).receipt_wait, 900)

    def test_partial_paste_render_settles_before_enter(self):
        t = Terminal(payload='hello long message')
        original = t.frame
        def frame():
            if t.pastes and t.now < 4:
                return screen('hello')
            return original()
        t.frame = frame
        self.assertEqual(deliver(t)['status'], 'delivered')
        self.assertGreaterEqual(t.accepted_at, 4.25)
        self.assertEqual(t.enters, 1)

    def test_collapsed_marker_render_updates_before_enter(self):
        t = Terminal(collapsed=True)
        original = t.frame
        def frame():
            if t.pastes and t.now < 3.5:
                return screen('[Pasted text #1 +2 lines]')
            return original()
        t.frame = frame
        self.assertEqual(deliver(t)['status'], 'delivered')
        self.assertEqual(t.enters, 1)

    def test_new_receipt_wins_over_stale_composer(self):
        t = Terminal(queued=True)
        original = t.keys
        def keys(*keys):
            original(*keys)
            if t.accepted_at is not None:
                t.draft = t.payload
        t.keys = keys
        self.assertEqual(deliver(t)['receipt'], 'queued')
        self.assertEqual(t.enters, 1)

    def test_measured_codex_stale_append_content_marker_submits(self):
        draft = 'MSG-STABLE-OFFER: no tools for this smoke'
        t = Terminal(payload='x' * 1515, draft=draft)
        raw = (Path(__file__).parent / 'fixtures/claude-send/codex-stale-append-content.ansi').read_text()
        row = next(i for i, line in enumerate(m.styles.strip_ansi(raw).splitlines()) if line.startswith('› '))
        original_frame, original_paste = t.frame, t.paste
        def paste(path):
            original_paste(path)
            self.assertEqual(path.read_text(), '\n' + t.payload)
            t.draft = draft + '[Pasted Content 1516 chars]'
        def frame():
            if t.pastes and t.accepted_at is None: return m.Frame(raw, 70, row, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        result = deliver(t)
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual(result['stale_draft_length'], 41)
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_measured_claude_stale_append_marker_submits_once_with_or_without_hint(self):
        draft = 'Disposable retirement rehearsal reminder.'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        raw = (Path(__file__).parent / 'fixtures/claude-send/claude-stale-append-pasted-text.ansi').read_text()
        x, y = map(int, (Path(__file__).parent / 'fixtures/claude-send/claude-stale-append-pasted-text.cursor').read_text().split())
        for with_hint in (False, True):
            with self.subTest(with_hint=with_hint):
                terminal = Terminal(payload='x' * 1368, draft=draft)
                terminal.harness = 'claude'
                original_frame, original_paste = terminal.frame, terminal.paste
                def paste(path):
                    original_paste(path)
                    self.assertEqual(path.read_text(), '\n' + terminal.payload)
                    terminal.draft = draft + '[Pasted text #1 +1 lines]'
                def frame():
                    if terminal.pastes and terminal.accepted_at is None:
                        measured = (raw + '  paste again to expand\n') if with_hint else raw
                        return m.Frame(measured, x, y, measured)
                    return original_frame()
                terminal.paste, terminal.frame = paste, frame
                result = deliver(terminal)
                self.assertEqual(result['status'], 'delivered')
                self.assertEqual(result['stale_draft_length'], len(draft))
                self.assertEqual((terminal.pastes, terminal.enters), (1, 1))

    def test_measured_claude_multiline_append_preserves_exact_separator(self):
        draft = 'Disposable retirement rehearsal reminder.'
        payload = 'First logical row.\nSecond row 世界 😀'
        t = Terminal(payload=payload, draft=draft)
        t.harness = 'claude'
        raw = (Path(__file__).parent / 'fixtures/claude-send/claude-stale-append-multiline.ansi').read_text()
        x, y = map(int, (Path(__file__).parent / 'fixtures/claude-send/claude-stale-append-multiline.cursor').read_text().split())
        original_frame = t.frame
        def frame():
            if t.pastes and t.accepted_at is None:
                return m.Frame(raw, x, y, raw)
            return original_frame()
        t.frame = frame
        result = deliver(t)
        self.assertEqual(result['receipt'], 'submitted')
        self.assertEqual(t.submitted, draft + '\n' + payload)
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_multiline_original_draft_plus_collapsed_append_submits(self):
        draft = 'First stable row\nSecond stable row 世界'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #1 +1 lines]'
        def frame():
            if t.pastes and t.accepted_at is None:
                first, second = draft.split('\n')
                suffix = '[Pasted text #1 +1 lines]'
                raw = '──────────────\n❯\u00a0' + first + '\n  ' + second + suffix + '\n──────────────\n'
                return m.Frame(raw, 2 + m.styles.cell_width(second + suffix), 2, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        result = deliver(t)
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual(result['stale_draft_length'], len(draft))
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_exact_claude_append_requires_same_harness_and_end_cursor(self):
        for failure in ('harness', 'cursor'):
            with self.subTest(failure=failure):
                t = Terminal(payload='a short payload', draft='stable draft')
                t.harness = 'claude'
                original_frame = t.frame
                def frame():
                    if t.pastes and t.accepted_at is None:
                        f = screen(t.draft, t.history, harness='codex' if failure == 'harness' else 'claude')
                        if failure == 'cursor':
                            f.x -= 1
                        return f
                    return original_frame()
                t.frame = frame
                with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'):
                    deliver(t)
                self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_exact_claude_append_is_single_enter(self):
        t = Terminal(payload='a short payload', draft='stable draft')
        t.harness = 'claude'
        result = deliver(t)
        self.assertEqual(result['receipt'], 'submitted')
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_combined_receipt_matches_captured_blank_separator_block(self):
        draft = 'Disposable retirement rehearsal reminder.'
        payload = (CO_SUBMIT_FIXTURES / 'claude-co-submit-payload.txt').read_text()
        frame = claude_co_submit_frame()
        inp = m.composer(frame)
        self.assertEqual((inp.kind, inp.harness), ('empty', 'claude'))
        self.assertEqual(m.records(frame, inp)[('submitted', m.normalized(draft))], 1)
        self.assertEqual(m.claude_combined_receipts(frame, inp, draft, payload), 1)
        padded = frame.raw.replace(
            f'❯ {draft}\n\n  After the current task completes,',
            f'❯ {draft}\n   \n  After the current task completes,', 1)
        padded_frame = m.Frame(padded, frame.x, frame.y, padded)
        self.assertEqual(m.claude_combined_receipts(
            padded_frame, m.composer(padded_frame), draft, payload), 1)

    def test_claude_combined_receipt_requires_one_complete_owned_block(self):
        draft = 'Disposable retirement rehearsal reminder.'
        payload = (CO_SUBMIT_FIXTURES / 'claude-co-submit-payload.txt').read_text()
        fixture = (CO_SUBMIT_FIXTURES / 'claude-co-submit-receipt.ansi').read_text()
        cases = (
            ('wrong draft prefix', fixture.replace('❯ Disposable retirement rehearsal reminder.',
                                                    '❯ Different ordinary draft.', 1)),
            ('wrong payload', fixture.replace('ACK-QUEUE-3155db7fcc5e', 'ACK-QUEUE-wrong')),
            ('assistant prose', fixture.replace('❯ Disposable retirement rehearsal reminder.',
                                                '● Disposable retirement rehearsal reminder.', 1)),
            ('indented assistant prompt glyph', fixture.replace(
                '❯ Disposable retirement rehearsal reminder.',
                '  ❯ Disposable retirement rehearsal reminder.', 1)),
            ('cropped header', fixture.replace('❯ Disposable retirement rehearsal reminder.',
                                               '  Disposable retirement rehearsal reminder.', 1)),
            ('archived composer', fixture.replace('❯ Disposable retirement rehearsal reminder.',
                                                  '──────────────\n❯ Disposable retirement rehearsal reminder.', 1)),
            ('archived composer with cropped opening rule', fixture.replace(
                '\n\n● ACK-QUEUE-', '\n\n────────────────────────────────────────────────────────────────────────────────\n● ACK-QUEUE-', 1)),
            ('mixed continuation', fixture.replace('preserve this line as message bod\n\n● ACK-',
                                                   'preserve this line as message bod\n  unrelated row\n\n● ACK-', 1)),
            ('extra blank paragraph', fixture.replace(
                '❯ Disposable retirement rehearsal reminder.\n\n  After the current task',
                '❯ Disposable retirement rehearsal reminder.\n\n\n  After the current task', 1)),
        )
        for reason, raw in cases:
            with self.subTest(reason=reason):
                lines = raw.splitlines()
                prompt = next(i for i, row in enumerate(lines) if row == '❯\u00a0')
                frame = m.Frame(raw, 2, prompt, raw)
                inp = m.composer(frame)
                self.assertEqual(m.claude_combined_receipts(frame, inp, draft, payload), 0)
        blank_terminal = claude_co_submit_frame(receipt=False)
        self.assertEqual(m.claude_combined_receipts(
            blank_terminal, m.composer(blank_terminal), draft, payload), 0)
        frame = claude_co_submit_frame()
        inp = m.composer(frame)
        for unsupported in (m.Input('unknown', harness='claude'),
                            m.Input('modal', harness='claude'),
                            m.Input(inp.kind, inp.text, inp.start, inp.end, inp.cursor, 'codex')):
            with self.subTest(kind=unsupported.kind, harness=unsupported.harness):
                self.assertEqual(m.claude_combined_receipts(frame, unsupported, draft, payload), 0)

    def test_claude_combined_receipt_is_new_relative_to_same_parser_baseline(self):
        draft = 'Disposable retirement rehearsal reminder.'
        payload = (CO_SUBMIT_FIXTURES / 'claude-co-submit-payload.txt').read_text()
        old = claude_co_submit_frame()
        old_history = ('Tool output before\n  ❯ ' + draft +
                       '\nTool output after\n' + old.history)
        old_with_quote = m.Frame(old.raw, old.x, old.y, old_history)
        old_input = m.composer(old_with_quote)
        expected_form = ('submitted', m.normalized(draft))
        self.assertEqual(m.records(old_with_quote, old_input)[expected_form], 2)
        self.assertEqual(m.records(old_with_quote, old_input,
                                   strict_claude_submitted=True)[expected_form], 1)
        baseline = m.claude_combined_receipts(old_with_quote, old_input, draft, payload)
        self.assertEqual(baseline, 1)
        rows = old.raw.splitlines()
        start = next(i for i, row in enumerate(rows)
                     if row == '❯ Disposable retirement rehearsal reminder.')
        end = next(i for i, row in enumerate(rows[start:], start)
                   if row == '● ACK-QUEUE-3155db7fcc5e')
        rows[end + 1:end + 1] = [''] + rows[start:end + 1]
        raw = '\n'.join(rows) + '\n'
        prompt = next(i for i, row in enumerate(rows) if row == '❯\u00a0')
        frame = m.Frame(raw, 2, prompt, raw)
        current = m.claude_combined_receipts(frame, m.composer(frame), draft, payload)
        self.assertEqual(current, 2)
        self.assertGreater(current, baseline)

    def test_new_combined_block_before_first_enter_does_not_authorize_an_enter(self):
        draft = 'Disposable retirement rehearsal reminder.'
        payload = (CO_SUBMIT_FIXTURES / 'claude-co-submit-payload.txt').read_text()

        class AlreadySubmitted(Terminal):
            def frame(self):
                if self.pastes:
                    return claude_co_submit_frame()
                return super().frame()

        t = AlreadySubmitted(payload=payload, draft=draft)
        t.harness = 'claude'
        frame = claude_co_submit_frame()
        self.assertEqual(m.claude_combined_receipts(
            frame, m.composer(frame), draft, payload), 1)
        with self.assertRaisesRegex(m.DeliveryError, 'paste-not-observed'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_claude_co_submit_accepts_new_measured_full_user_receipt(self):
        draft = 'Disposable retirement rehearsal reminder.'
        payload = (CO_SUBMIT_FIXTURES / 'claude-co-submit-payload.txt').read_text()
        t = Terminal(payload=payload, draft=draft)
        t.harness = 'claude'
        original_paste = t.paste
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #3 +2 lines]'
        def frame():
            if t.accepted_at is not None:
                return claude_co_submit_frame()
            return screen(t.draft, harness='claude')
        t.paste, t.frame = paste, frame
        result = deliver(t)
        self.assertEqual((result['status'], result['receipt'], result['enters']),
                         ('delivered', 'submitted', 1))
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_co_submit_does_not_reuse_old_identical_receipt(self):
        draft = 'Disposable retirement rehearsal reminder.'
        payload = (CO_SUBMIT_FIXTURES / 'claude-co-submit-payload.txt').read_text()
        t = Terminal(payload=payload, draft=draft, dropped=1)
        t.harness = 'claude'
        original_paste = t.paste
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #3 +2 lines]'
        def frame():
            return claude_co_submit_frame(t.draft)
        t.paste, t.frame = paste, frame
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_cosubmit_ignores_indented_quote_receipts_after_dropped_enter(self):
        draft, payload = 'Stable ordinary draft.', 'hello'
        for suffix in ('[Pasted text #3 +1 lines]', '\n' + payload):
            with self.subTest(suffix=suffix):
                t = Terminal(payload=payload, draft=draft, dropped=1)
                t.harness = 'claude'
                original_paste = t.paste

                def paste(path):
                    original_paste(path)
                    t.draft = draft + suffix

                original_frame = t.frame

                def frame():
                    if t.pastes and t.enters:
                        if suffix.startswith('\n'):
                            quote_body = '  ❯ ' + draft + '\n  ' + payload
                            expected_form = m.normalized(draft + suffix)
                        else:
                            quote_body = '  ❯ ' + draft + suffix
                            expected_form = m.normalized(draft + suffix)
                        quote = 'Tool output before\n' + quote_body + '\nTool output after\n'
                        receipt_frame = screen(t.draft, history=quote, harness='claude')
                        receipt_input = m.composer(receipt_frame)
                        # The unfiltered generic parser sees these deliberate
                        # quote-shaped rows; only the scoped co-submit filter
                        # rejects the indented non-user prompt.
                        self.assertEqual(m.records(receipt_frame, receipt_input)
                                         [('submitted', expected_form)], 1)
                        self.assertEqual(m.records(receipt_frame, receipt_input,
                                                   strict_claude_submitted=True)
                                         [('submitted', expected_form)], 0)
                        return screen(t.draft, history=quote, harness='claude')
                    return original_frame()

                t.paste, t.frame = paste, frame
                with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
                    deliver(t)
                self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_cosubmit_ignores_old_indented_full_body_in_sender_baseline(self):
        draft, payload = 'Stable ordinary draft.', 'hello'
        old_quote = ('Tool output before\n  ❯ ' + draft + '\n  ' + payload +
                     '\nTool output after\n')
        t = Terminal(payload=payload, draft=draft)
        t.harness = 'claude'
        t.history = old_quote
        result = deliver(t)
        self.assertEqual((result['status'], result['receipt']), ('delivered', 'submitted'))
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_measured_claude_marker_rejects_unowned_shapes(self):
        draft = 'Disposable retirement rehearsal reminder.'
        marker = '[Pasted text #1 +1 lines]'
        cases = (
            ('Other stable draft.' + marker, 'paste again to expand', 'claude', 0),
            (draft + '[Pasted text #1 +2 lines]', 'paste again to expand', 'claude', 0),
            (draft + '[Pasted text #1 +20 lines]', 'paste again to expand', 'claude', 0),
            (draft + '[Pasted text #1]', 'paste again to expand', 'claude', 0),
            (draft + marker + ' extra composer text', '', 'claude', 0),
            (draft + marker + marker, '', 'claude', 0),
            (draft + 'x' + marker, '', 'claude', 0),
            (draft + marker, 'paste again to expand', 'claude', -1),
            (draft + marker, 'paste again to expand', 'codex', 0),
            ('Disposable retirement rehearsal\nreminder.' + marker, 'paste again to expand', 'claude', 0),
        )
        for text, hint, harness, cursor_delta in cases:
            with self.subTest(text=text, hint=hint, harness=harness, cursor_delta=cursor_delta):
                t = Terminal(payload='x' * 1368, draft=draft)
                t.harness = 'claude'
                original_frame, original_paste = t.frame, t.paste
                def paste(path):
                    original_paste(path)
                    t.draft, t.harness = text, harness
                def frame():
                    if t.pastes and t.accepted_at is None:
                        if harness == 'claude':
                            prompt = '❯\u00a0' + text
                            raw = '──────────────\n' + prompt + '\n──────────────\n'
                            if hint:
                                raw += '  ' + hint + '\n'
                            cursor = 2 + m.styles.cell_width(text) + cursor_delta
                            row = 1
                        else:
                            raw = '› ' + text + '\n\n  Any model · branch\n'
                            cursor = 2 + m.styles.cell_width(text) + cursor_delta
                            row = 0
                        return m.Frame(raw, cursor, row, raw)
                    return original_frame()
                t.paste, t.frame = paste, frame
                with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'):
                    deliver(t)
                self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_claude_collapsed_append_draft_with_unicode_cursor_width(self):
        draft = 'Cue 世界 cafe\u0301 😀'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #2 +1 lines]'
        def frame():
            if t.pastes and t.accepted_at is None:
                text = draft + '[Pasted text #2 +1 lines]'
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n  paste again to expand\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        self.assertEqual(deliver(t)['receipt'], 'submitted')
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_collapsed_append_line_count_includes_separator(self):
        draft = 'stale 世界'
        payload = 'x' * 683 + '\n' + 'y' * 684
        t = Terminal(payload=payload, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #2 +2 lines]'
        def frame():
            if t.pastes and t.accepted_at is None:
                text = draft + '[Pasted text #2 +2 lines]'
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n  paste again to expand\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        self.assertEqual(deliver(t)['receipt'], 'submitted')
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_collapsed_append_lost_enter_is_not_retried(self):
        draft = 'Disposable retirement rehearsal reminder.'
        t = Terminal(payload='x' * 1368, draft=draft, dropped=1)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #3 +1 lines]'
        def frame():
            if t.pastes and t.accepted_at is None:
                text = draft + '[Pasted text #3 +1 lines]'
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n  paste again to expand\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_collapsed_append_modal_and_unknown_never_enter(self):
        draft = 'Disposable retirement rehearsal reminder.'
        for kind in ('modal', 'unknown'):
            with self.subTest(kind=kind):
                t = Terminal(payload='x' * 1368, draft=draft)
                t.harness = 'claude'
                original_frame, original_paste = t.frame, t.paste
                def paste(path):
                    original_paste(path)
                    t.draft = draft + '[Pasted text #4 +1 lines]'
                def frame():
                    if t.pastes and t.accepted_at is None:
                        if kind == 'modal':
                            return m.Frame('Would you like to proceed?\n❯ yes\n', 2, 1)
                        return m.Frame('', -1, -1)
                    return original_frame()
                t.paste, t.frame = paste, frame
                with self.assertRaises(m.DeliveryError):
                    deliver(t)
                self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_claude_collapsed_append_change_after_evidence_defers(self):
        draft = 'Disposable retirement rehearsal reminder.'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        samples = 0
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #5 +1 lines]'
        def frame():
            nonlocal samples
            if t.pastes and t.accepted_at is None:
                samples += 1
                text = draft + ('[Pasted text #5 +1 lines]' if samples <= 1 else '[Pasted text #5 +1 lines] changed')
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n  paste again to expand\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_claude_collapsed_append_marker_ordinal_change_before_enter_defers(self):
        draft = 'Disposable retirement rehearsal reminder.'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        samples = 0
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #1 +1 lines]'
        def frame():
            nonlocal samples
            if t.pastes and t.accepted_at is None:
                samples += 1
                text = draft + f'[Pasted text #{1 if samples == 1 else 2} +1 lines]'
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        with self.assertRaisesRegex(m.DeliveryError, 'input-changed-after-paste'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_claude_collapsed_append_marker_change_at_enter_revalidation_defers(self):
        draft = 'Disposable retirement rehearsal reminder.'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        samples = 0
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #1 +1 lines]'
        def frame():
            nonlocal samples
            if t.pastes and t.accepted_at is None:
                samples += 1
                ordinal = 1 if samples <= 5 else 2
                text = draft + f'[Pasted text #{ordinal} +1 lines]'
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        with self.assertRaisesRegex(m.DeliveryError, 'input-changed-before-enter'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_claude_collapsed_append_unknown_then_new_marker_defers(self):
        draft = 'Disposable retirement rehearsal reminder.'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        samples = 0
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #1 +1 lines]'
        def frame():
            nonlocal samples
            if t.pastes and t.accepted_at is None:
                samples += 1
                if samples == 2:
                    return m.Frame('', -1, -1)
                ordinal = 1 if samples == 1 else 2
                text = draft + f'[Pasted text #{ordinal} +1 lines]'
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        with self.assertRaisesRegex(m.DeliveryError, 'input-changed-after-paste'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_claude_collapsed_append_bare_draft_change_defers(self):
        draft = 'Disposable retirement rehearsal reminder.'
        t = Terminal(payload='x' * 1368, draft=draft)
        t.harness = 'claude'
        original_frame, original_paste = t.frame, t.paste
        samples = 0
        def paste(path):
            original_paste(path)
            t.draft = draft + '[Pasted text #1 +1 lines]'
        def frame():
            nonlocal samples
            if t.pastes and t.accepted_at is None:
                samples += 1
                if samples == 2:
                    return screen(draft, harness='claude')
                ordinal = 1 if samples == 1 else 2
                text = draft + f'[Pasted text #{ordinal} +1 lines]'
                raw = '──────────────\n❯\u00a0' + text + '\n──────────────\n'
                return m.Frame(raw, 2 + m.styles.cell_width(text), 1, raw)
            return original_frame()
        t.paste, t.frame = paste, frame
        with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_main_rejects_bare_carriage_return_before_tmux_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / 'payload'
            payload.write_bytes(b'one\rtwo')
            o = SimpleNamespace(prompt_file=payload, message=None, literal_exit=False)
            err = io.StringIO()
            with patch.object(m, 'options', return_value=o), patch.object(m, 'Tmux') as tmux, redirect_stderr(err):
                self.assertEqual(m.main(), 1)
            tmux.assert_not_called()
            self.assertIn('without control characters', err.getvalue())

    def test_stale_append_content_unicode_counts_recover_once(self):
        payload = 'emoji 😀 context'
        for count in {len('\n' + payload), len(('\n' + payload).encode('utf-16-le')) // 2}:
            t = Terminal(payload=payload, draft='stale TICK', dropped=1)
            original = t.paste
            def paste(path):
                original(path)
                t.draft = 'stale TICK' + f'[Pasted Content {count} chars]'
            t.paste = paste
            self.assertEqual(deliver(t)['status'], 'delivered')
            self.assertEqual((t.pastes, t.enters), (1, 2))

    def test_stale_append_content_rejects_every_mixed_shape(self):
        marker = '[Pasted Content 6 chars]'
        for text, harness in (
                ('stale TICK[Pasted Content 5 chars]', 'codex'),
                ('stale TICK' + marker + ' human', 'codex'),
                ('human stale TICK' + marker, 'codex'),
                ('stale TIC' + marker, 'codex'), (marker, 'codex'),
                ('stale TICK\n' + marker, 'codex'),
                ('stale TICK[Pasted text #1 +20 lines]', 'codex'),
                ('stale TICK' + marker + marker, 'codex'),
                ('stale TICK' + marker, 'claude')):
            with self.subTest(text=text, harness=harness):
                t = Terminal(draft='stale TICK')
                original = t.paste
                def paste(path):
                    original(path)
                    t.draft, t.harness = text, harness
                t.paste = paste
                with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'): deliver(t)
                self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_stale_append_content_old_marker_or_replay_never_repastes(self):
        for draft in ('stale TICK[Pasted Content 6 chars]', 'stale TICK[pasted content 6 chars]',
                      'stale TICK[PASTED CONTENT 6 CHARS]', 'stale TICK[pasted text #1 +2 lines]', 'stale TICK hello'):
            t = Terminal(draft=draft)
            with self.assertRaises(m.DeliveryError): deliver(t)
            self.assertEqual(t.actions, [])

    def test_stale_append_content_cannot_change_harness_or_cursor(self):
        for initial_harness, wrong_cursor in (('claude', False), ('codex', True)):
            t = Terminal(draft='stale TICK')
            t.harness = initial_harness
            original_paste, original_frame = t.paste, t.frame
            def paste(path):
                original_paste(path)
                t.draft, t.harness = 'stale TICK[Pasted Content 6 chars]', 'codex'
            def frame():
                f = original_frame()
                if t.pastes and wrong_cursor: f.x -= 1
                return f
            t.paste, t.frame = paste, frame
            with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'): deliver(t)
            self.assertEqual((t.pastes, t.enters), (1, 0))

    def test_stale_append_content_two_attempts_never_repastes(self):
        t = Terminal(draft='stale TICK', dropped=99)
        original = t.paste
        def paste(path):
            original(path)
            t.draft = 'stale TICK[Pasted Content 6 chars]'
        t.paste = paste
        with self.assertRaises(m.DeliveryError): deliver(t)
        actions = list(t.actions)
        with self.assertRaises(m.DeliveryError): deliver(t)
        self.assertEqual(t.actions, actions)
        self.assertEqual((t.pastes, t.enters), (1, 2))

    def test_stale_append_content_cannot_use_old_receipt(self):
        t = Terminal(draft='stale TICK', dropped=99)
        t.history = '› stale TICK[Pasted Content 6 chars]\n\n'
        original = t.paste
        def paste(path):
            original(path)
            t.draft = 'stale TICK[Pasted Content 6 chars]'
        t.paste = paste
        with self.assertRaises(m.DeliveryError): deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 2))

    def test_content_character_count_marker(self):
        for payload in ['x' * 1034, 'hello\nworld', 'emoji 😀']:
            for count in {len(payload), len(payload.encode('utf-16-le')) // 2}:
                marker = f'[Pasted Content {count} chars]'
                self.assertTrue(m.paste_evidence(m.Input('text', marker), payload))
                self.assertFalse(m.paste_evidence(m.Input('text', marker + ' human'), payload))
                self.assertFalse(m.paste_evidence(m.Input('text', 'human ' + marker), payload))
                self.assertFalse(m.paste_evidence(m.Input('text', ' ' + marker), payload))
        self.assertFalse(m.paste_evidence(m.Input('text', '[Pasted Content 1034 chars]'), 'short'))

    def test_content_marker_drop_enter_recovers_and_confirms(self):
        t = Terminal(payload='x' * 1034, dropped=1)
        original = t.paste
        def paste(path):
            original(path)
            t.draft = '[Pasted Content 1034 chars]'
        t.paste = paste
        self.assertEqual(deliver(t)['status'], 'delivered')
        self.assertEqual((t.pastes, t.enters), (1, 2))

    def test_collapsed_marker_cannot_duplicate_visible_payload(self):
        for text in ['[Pasted text #1 +20 lines]hello', 'hello[Pasted text]hello']:
            self.assertFalse(m.paste_evidence(m.Input('text', text), 'hello'))

    def test_archived_input_box_is_not_receipt(self):
        for harness in ['codex', 'claude']:
            archived = screen('hello', harness=harness).raw
            f = screen(history=archived)
            self.assertEqual(m.records(f, m.composer(f))[('submitted', 'hello')], 0)

    def test_collapsed_history_matches_observed_paste(self):
        t = Terminal(collapsed=True)
        original = t.frame
        def frame():
            f = original()
            if t.accepted_at is not None:
                f.history = f.history.replace('› hello', '› [Pasted text #1 +20 lines]')
            return f
        t.frame = frame
        self.assertEqual(deliver(t)['status'], 'delivered')

    def test_compact_command_completion(self):
        t = Terminal(payload='/compact')
        original = t.frame
        def frame():
            f = original()
            if t.accepted_at is not None:
                f.history = f.history.replace('› /compact', '• Context compacted · 14s')
            return f
        t.frame = frame
        self.assertEqual(deliver(t)['receipt'], 'command')

    def test_empty_then_old_input_reappears_never_reenters(self):
        t = Terminal(dropped=99)
        original = t.frame
        def frame():
            if t.enters == 1 and 4.25 <= t.now < 4.75:
                return screen()
            return original()
        t.frame = frame
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t)
        self.assertEqual(t.enters, 1)

    def test_recorded_composers_without_model_specific_positions(self):
        fixtures = Path(__file__).with_name('fixtures') / 'claude-send'
        for name in ['codex-fork-empty', 'codex-generating-queue', 'codex-context-queue']:
            x, y = map(int, (fixtures / (name + '.cursor')).read_text().strip().split(':'))
            f = m.Frame((fixtures / (name + '.ansi')).read_text(), x, y)
            self.assertEqual(m.composer(f).kind, 'empty' if name == 'codex-fork-empty' else 'text', name)

    def test_suggestion_probe_empty(self):
        t = Terminal()
        original_frame, original_keys = t.frame, t.keys
        t.ghost = True
        def frame():
            if t.ghost:
                f = screen('Try "hello"', harness='claude')
                f.x = 2
                return f
            return original_frame()
        def keys(*keys):
            if keys == ('Space', 'BSpace'):
                t.ghost = False
            original_keys(*keys)
        t.frame, t.keys = frame, keys
        self.assertEqual(deliver(t)['status'], 'delivered')
        self.assertEqual(t.actions.count('Space'), 1)

    def test_suggestion_shaped_human_draft_preserved(self):
        t = Terminal()
        f = screen('Try "my own draft"', harness='claude')
        f.x = 2
        t.frame = lambda: f
        with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
            deliver(t)
        self.assertEqual(t.actions, ['Space', 'BSpace'])


def typed_mutations():
    """Compile-valid changes must fail assertions, not merely fail to import."""
    subprocess.run([sys.executable, __file__], check=True, timeout=30)
    root = Path(__file__).parent
    original = (root / 'tmux-message.py').read_text()
    cases = [
        ('conflicting_modes', 'if self.typed and getattr(options, "literal_exit", False):', 'if False:'),
        ('typed_length_tail', 'if self.typed and (len(payload.encode("utf-8")) > 200 or payload != payload.rstrip() or payload.endswith(";")):', 'if False:'),
        ('typed_failure_method', '"typed" if o.typed_command or o.literal_exit else "paste"', '"typed" if sender and sender.typed else "paste"'),
        ('typed_dispatch', 'self.tmux.type_command(self.payload)', 'self.tmux.paste(self.path)'),
        ('typed_scope', 'if self.typed and not styles.slash_command_syntax(payload):', 'if False:'),
        ('literal', 'self.pane, "-l", "--", text', 'self.pane, "--", text'),
        ('typed_evidence', 'return inp.kind == "text" and inp.text == self.payload',
         'return paste_evidence(inp, self.payload)'),
    ]
    with tempfile.TemporaryDirectory(prefix='typed-command-mutations-') as tmp:
        target = Path(tmp)
        for name in ('test-tmux-message.py', 'claude-send-screen.py'):
            shutil.copy2(root / name, target / name)
        shutil.copytree(root / 'fixtures', target / 'fixtures')
        for name, before, after in cases:
            assert original.count(before) == 1, name
            code = original.replace(before, after)
            compile(code, name, 'exec')
            (target / 'tmux-message.py').write_text(code)
            result = subprocess.run([sys.executable, str(target / 'test-tmux-message.py')],
                                    capture_output=True, text=True, timeout=30)
            assert result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr, (name, result.stderr)
            print('killed:', name)


if __name__ == '__main__':
    if '--mutation-check' in sys.argv:
        typed_mutations()
    else:
        unittest.main()
