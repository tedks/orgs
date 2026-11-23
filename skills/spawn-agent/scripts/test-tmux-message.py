#!/usr/bin/env python3
"""Behavior tests with a virtual clock and a simulated terminal, no model calls."""
import importlib.util
import io
import json
import os
import re
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


def screen(text='', history='', harness='codex', footer='  Any model · branch', prefix='', width=0):
    if harness == 'claude':
        raw = prefix + '──────────────\n❯\u00a0' + text + '\n──────────────\n'
        y = len(prefix.splitlines()) + 1 + text.count('\n')
    else:
        raw = prefix + '› ' + text + '\n\n' + footer + '\n'
        y = len(prefix.splitlines()) + text.count('\n')
    return m.Frame(raw, 2 + m.styles.cell_width(text.rsplit('\n', 1)[-1]),
                   y, history + raw, width=width)


CO_SUBMIT_FIXTURES = Path(__file__).with_name('fixtures') / 'claude-send'


def fixture_frame(name, marker='❯'):
    raw = (CO_SUBMIT_FIXTURES / name).read_text()
    rows = m.styles.strip_ansi(raw).splitlines()
    y = next(i for i, row in enumerate(rows) if marker in row)
    return m.Frame(raw, 2, y)


def codex_fixture_frame(name):
    x, y = map(int, (CO_SUBMIT_FIXTURES / (name + '.cursor')).read_text().split(':'))
    return m.Frame((CO_SUBMIT_FIXTURES / (name + '.ansi')).read_text(), x, y)


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
        self.identity = '100:%1'
        self.pane_pid = '200'
        self.frames = 0
        self.submitted = None
        self.harness = 'codex'
        self.home = False

    def receiver_identity(self):
        return {"pid": "100", "pane_id": self.pane, "socket_path": "/synthetic/tmux",
                "start_time": "300", "pane_pid": self.pane_pid, "pane_tty": "/dev/pts/1"}

    def sleep(self, n): self.now += n
    def clock(self): return self.now

    def frame(self):
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
        if keys == ('Enter',):
            self.enters += 1
            if self.enters > self.dropped:
                self.accepted_at = self.now
                self.submitted = self.draft
                self.draft = ''



# Synthetic renderings from Codex's info and error cells. The transport
# reference pins the renderer source and supported duration formats.
COMPACT_COMPLETE = '\x1b[2m• \x1b[0mContext compacted'
COMPACT_REFUSAL = "\x1b[31m■ '/compact' is disabled while a task is in progress.\x1b[0m"


class CompactTerminal(Terminal):
    identity = '0:%1'
    width = 100

    def __init__(self, outcome=lambda elapsed: '', **kwargs):
        super().__init__(payload='/compact', **kwargs)
        self.outcome = outcome
        self.visible_history = ''

    def frame(self):
        if self.accepted_at is not None:
            rows = self.outcome(self.now - self.accepted_at)
        elif self.draft == '/compact':
            # The exact match menu sits above the editable command.
            rows = '\x1b[1;7m› /compact  summarize conversation to prevent hitting the context limit\x1b[0m\n\n'
        else:
            frame = super().frame()
            frame.width = self.width
            return frame
        return screen(self.draft, self.history, harness=self.harness,
                      prefix=self.visible_history + rows, width=self.width)


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

    def test_claude_image_placeholder_fixture_defers_before_any_input(self):
        frame = codex_fixture_frame('SYNTHETIC-claude-image-placeholder')
        self.assertEqual((m.composer(frame).harness, m.composer(frame).text),
                         ('claude', '[Image #1]'))
        t = Terminal(draft='[Image #1]')
        t.harness = 'claude'
        original_frame = t.frame
        t.frame = lambda: frame if not t.pastes else original_frame()
        with self.assertRaisesRegex(m.DeliveryError, 'image-placeholder'):
            deliver(t)
        self.assertEqual(t.actions, [])
        self.assertEqual((t.pastes, t.enters), (0, 0))

    def test_claude_image_placeholder_amid_text_also_defers(self):
        t = Terminal(draft='notes [Image #2] and more')
        t.harness = 'claude'
        with self.assertRaisesRegex(m.DeliveryError, 'image-placeholder'):
            deliver(t)
        self.assertEqual(t.actions, [])
        self.assertEqual((t.pastes, t.enters), (0, 0))

    def test_claude_wrapped_image_placeholder_defers_before_any_input(self):
        frame = codex_fixture_frame('SYNTHETIC-claude-image-placeholder-wrapped')
        self.assertEqual((m.composer(frame).harness, m.composer(frame).text),
                         ('claude', 'notes [Image #\n4] and more'))
        t = Terminal(draft='notes [Image #\n4] and more')
        t.harness = 'claude'
        original_frame = t.frame
        t.frame = lambda: frame if not t.pastes else original_frame()
        with self.assertRaisesRegex(m.DeliveryError, 'image-placeholder'):
            deliver(t)
        self.assertEqual(t.actions, [])

    def test_claude_image_placeholder_sample_at_readiness_deadline(self):
        t = Terminal(draft='[Image #5]')
        t.harness = 'claude'
        original_frame = t.frame
        def delayed_sample():
            # Deliberately land one sample exactly on the readiness boundary.
            t.now = 8
            return original_frame()
        t.frame = delayed_sample
        with self.assertRaisesRegex(m.DeliveryError, 'image-placeholder'):
            deliver(t, max_wait=8)
        self.assertEqual(t.actions, [])

    def test_claude_image_placeholder_in_transcript_is_not_live_input(self):
        t = Terminal()
        t.harness = 'claude'
        t.history = '❯ [Image #3] mentioned in prior transcript\n'
        self.assertEqual(deliver(t)['status'], 'delivered')
        self.assertEqual((t.pastes, t.enters), (1, 1))

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
                t.draft = ''
            return original()
        t.frame = changing_once
        o = SimpleNamespace(max_wait=1, stable_wait=0, poll_interval=.25, backoff=True)
        sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
        self.assertEqual(sender.ready()[1].kind, 'empty')
        self.assertGreaterEqual(t.frames, 3)
        self.assertEqual(t.actions, [])

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

    def test_stable_unproven_drafts_defer_with_no_keys(self):
        for harness in ('codex', 'claude'):
            for draft in ('foreign ' + 'x' * 581, 'part of hello', '/compact', '!command',
                          'first line\n  second line', '   ', '\n  '):
                for home in (False, True):
                    with self.subTest(harness=harness, draft=draft, home=home):
                        t = Terminal(draft=draft)
                        t.harness, t.home = harness, home
                        with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
                            deliver(t)
                        self.assertEqual(t.actions, [])
                        self.assertEqual(t.draft, draft)

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

    def test_claude_cto_live_scrubbed_layouts_and_dim_suggestion(self):
        saved = codex_fixture_frame('claude-cto-321-saved-live-scrubbed')
        fresh = codex_fixture_frame('claude-cto-321-fresh-live-scrubbed')
        self.assertEqual(m.composer(saved).kind, 'empty')
        self.assertEqual(m.composer(fresh).kind, 'suggestion')
        self.assertEqual(m.composer(fresh).cursor, (2, 0))
        self.assertFalse(m.styles.dialog_active(fresh.raw, fresh.y))
        # The panel was reported with this footer but absent from both
        # captures. This appended variant is synthetic, not live evidence.
        panel = codex_fixture_frame('SYNTHETIC-claude-cto-321-agents-panel')
        self.assertEqual(m.composer(panel).kind, 'empty')
        self.assertEqual((len(panel.raw.splitlines()), panel.y), (88, 82))

    def test_claude_dim_suggestion_requires_start_single_row_and_full_style(self):
        fresh = codex_fixture_frame('claude-cto-321-fresh-live-scrubbed')
        self.assertEqual(m.composer(m.Frame(fresh.raw, 3, fresh.y)).kind, 'text')
        rows = fresh.raw.splitlines()
        rows.insert(fresh.y + 1, '  continuation')
        self.assertEqual(m.composer(m.Frame('\n'.join(rows) + '\n', 2, fresh.y)).kind, 'text')
        rows = fresh.raw.splitlines()
        rows[fresh.y] = '❯\u00a0typed\x1b[2m completion\x1b[0m'
        self.assertEqual(m.composer(m.Frame('\n'.join(rows) + '\n', 2, fresh.y)).kind, 'text')
        with patch.object(m.styles, 'dim_span', return_value=False):
            self.assertEqual(m.composer(fresh).kind, 'text')

    def test_claude_cto_dim_suggestion_probe_clears_before_paste(self):
        fixture = codex_fixture_frame('claude-cto-321-fresh-live-scrubbed')
        t = Terminal()
        t.harness = 'claude'
        t.probed = False
        original_frame, original_keys = t.frame, t.keys
        empty = codex_fixture_frame('claude-cto-321-saved-live-scrubbed')
        t.frame = lambda: (original_frame() if t.pastes else empty) if t.probed else fixture
        def keys(*pressed):
            if pressed == ('Space', 'BSpace'):
                t.probed = True
            original_keys(*pressed)
        t.keys = keys
        self.assertEqual(deliver(t, stable_wait=8, max_wait=10)['status'], 'delivered')
        self.assertEqual(t.actions, ['Space', 'BSpace', 'paste', 'Enter'])
        self.assertEqual(t.submitted, t.payload)

    def test_claude_cto_dim_text_that_survives_probe_is_preserved(self):
        fixture = codex_fixture_frame('claude-cto-321-fresh-live-scrubbed')
        t = Terminal()
        t.frame = lambda: fixture
        with self.assertRaisesRegex(m.DeliveryError, 'existing-input'):
            deliver(t, stable_wait=0, max_wait=2)
        self.assertEqual(t.actions, ['Space', 'BSpace'])
        self.assertEqual((t.pastes, t.enters), (0, 0))

    def test_post_probe_human_activity_cancels_short_stability_credit(self):
        fixture = codex_fixture_frame('claude-cto-321-fresh-live-scrubbed')
        empty = codex_fixture_frame('claude-cto-321-saved-live-scrubbed')
        t = Terminal()
        t.harness = 'claude'
        t.probed = False
        post_probe_samples = 0
        original_keys = t.keys
        def frame():
            nonlocal post_probe_samples
            if not t.probed:
                return fixture
            post_probe_samples += 1
            return screen('human', harness='claude') if post_probe_samples == 2 else empty
        def keys(*pressed):
            if pressed == ('Space', 'BSpace'):
                t.probed = True
            original_keys(*pressed)
        t.frame, t.keys = frame, keys
        with self.assertRaisesRegex(m.DeliveryError, 'human-typing'):
            deliver(t, stable_wait=8, max_wait=10, backoff=True)
        self.assertEqual((t.pastes, t.enters), (0, 0))

    def test_codex_idle_live_captures_and_synthetic_footer(self):
        # These two live captures were made AFTER the reported 38%-context
        # incidents. They prove real 272x54 layouts, not the incident failure.
        for name in ('codex-2026-10-18-live-current-748-scrubbed',
                     'codex-2026-10-18-live-current-749-scrubbed',
                     'SYNTHETIC-codex-idle-unrecognized-footer'):
            with self.subTest(name=name):
                frame = codex_fixture_frame(name)
                self.assertIn('Ask Codex to do anything', frame.raw)
                result = m.composer(frame)
                self.assertEqual((result.kind, result.harness, result.cursor),
                                 ('empty', 'codex', (2, 0)))
                t = Terminal()
                t.frame = lambda: frame
                o = SimpleNamespace(max_wait=5, stable_wait=3, poll_interval=.25,
                                    backoff=True)
                sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
                self.assertEqual(sender.ready()[1].kind, 'empty')
                self.assertEqual(t.actions, [])

    def test_codex_unknown_footer_fallback_rejects_choice_and_bad_cursor(self):
        frame = codex_fixture_frame('SYNTHETIC-codex-idle-unrecognized-footer')
        self.assertEqual(m.composer(m.Frame(frame.raw, 2, frame.y + 2)).kind, 'unknown')
        self.assertEqual(m.composer(m.Frame(frame.raw, 3, frame.y)).kind, 'unknown')
        plain = frame.raw.replace('\x1b[2mAsk Codex to do anything', 'Ask Codex to do anything')
        self.assertNotEqual(m.composer(m.Frame(plain, 2, frame.y)).kind, 'empty')
        unstyled_prompt = frame.raw.replace('\x1b[1m›\x1b[0m', '›')
        self.assertEqual(m.composer(m.Frame(unstyled_prompt, 2, frame.y)).kind, 'unknown')
        choice = frame.raw.replace('Ask Codex to do anything', '1. Allow')
        self.assertEqual(m.composer(m.Frame(choice, 2, frame.y)).kind, 'unknown')
        pasted = frame.raw.replace('\x1b[2mAsk Codex to do anything\x1b[0m', 'short payload')
        pasted_frame = m.Frame(pasted, 2 + len('short payload'), frame.y)
        self.assertEqual(m.composer(pasted_frame).kind, 'unknown')
        self.assertEqual(m.composer(pasted_frame, 'short payload',
                                    '  GPT-6.1-Sol | main | active').kind, 'text')
        self.assertEqual(m.composer(pasted_frame, 'short payload',
                                    '  GPT-6.1-Sol | changed').kind, 'unknown')

    def test_codex_unknown_footer_delivers_only_its_observed_paste(self):
        base = codex_fixture_frame('SYNTHETIC-codex-idle-unrecognized-footer')
        t = Terminal(payload='MODAL-M2 short receipt probe')
        def frame():
            if t.draft:
                raw = base.raw.replace('\x1b[2mAsk Codex to do anything\x1b[0m', t.draft)
            else:
                raw = base.raw
            submitted = ''
            if t.accepted_at is not None:
                submitted = '› ' + t.submitted + '\n\n'
            return m.Frame(raw, 2 + m.styles.cell_width(t.draft), base.y, submitted + raw)
        t.frame = frame
        result = deliver(t, max_wait=5, stable_wait=3, submit_delay=1)
        self.assertEqual((result['status'], result['receipt']), ('delivered', 'submitted'))
        self.assertEqual((t.pastes, t.enters, t.submitted), (1, 1, t.payload))

    def test_codex_unknown_footer_dropped_enter_redraw_is_not_receipt(self):
        base = codex_fixture_frame('SYNTHETIC-codex-idle-unrecognized-footer')
        for payload, footer_changes in (('short payload', 0),
                                        ('short payload', 1),
                                        ('short payload', 2),
                                        ('short payload', 3),
                                        ('first line\nsecond line', 0),
                                        ('first line\nsecond line', 2)):
            with self.subTest(payload=payload, footer_changes=footer_changes):
                t = Terminal(payload=payload, dropped=99)
                def frame():
                    parts = t.draft.split('\n')
                    raw = (base.raw.replace('\x1b[2mAsk Codex to do anything\x1b[0m',
                                            parts[0] + ''.join('\n  ' + row for row in parts[1:]))
                           if t.draft else base.raw)
                    # A full-screen redraw can archive the still-unsent
                    # composer; the live footer may also change afterwards.
                    archived = raw if t.enters else ''
                    if t.enters and footer_changes in (2, 3):
                        archived = archived.replace('GPT-6.1-Sol | main | active',
                                                    'GPT-6.1-Sol | main | intermediate')
                    if t.enters and footer_changes in (1, 2):
                        raw = raw.replace('GPT-6.1-Sol | main | active',
                                          'GPT-6.1-Sol | main | updated')
                    return m.Frame(raw, 2 + m.styles.cell_width(parts[-1]),
                                   base.y + len(parts) - 1, archived + raw)
                t.frame = frame
                with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
                    deliver(t, max_wait=5, stable_wait=3, submit_delay=1,
                            receipt_wait=5, retry_wait=1)
                self.assertEqual(t.accepted_at, None)
                self.assertEqual(t.pastes, 1)

    def test_osc8_url_delivers_with_a_fresh_receipt(self):
        url = 'https://example.org/relay?q=one&next=two'
        for end, dropped in (('\x1b\\', 0), ('\x07', 0), ('\x1b\\', 2)):
            with self.subTest(terminator=end, dropped_enters=dropped):
                t = Terminal(payload=f'Read {url} please', dropped=dropped)
                decorated = f'\x1b]8;id=relay;{url}{end}{url}\x1b]8;;{end}'
                t.history = f'› Read {decorated} please\n\n'
                original = t.frame

                def styled():
                    frame = original()
                    frame.raw = frame.raw.replace(url, decorated)
                    history = frame.history[len(t.history):].replace(url, decorated)
                    frame.history = t.history + history
                    return frame

                t.frame = styled
                if dropped:
                    with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
                        deliver(t)
                    self.assertEqual(t.actions, ['paste', 'Enter', 'Enter'])
                    continue
                self.assertEqual(deliver(t)['receipt'], 'submitted')
                self.assertEqual(t.submitted, t.payload)
                self.assertEqual(t.actions, ['paste', 'Enter'])

    def test_wrapped_osc8_url_delivers_with_row_local_pairs(self):
        url = 'https://example.org/' + 'segment-' * 28 + 'end?q=one'
        t = Terminal(payload=f'Read {url}')
        # tmux capture -e reopens and closes the same hyperlink on each row.
        pieces = (url[:153], url[153:])
        rows = [f'  \x1b]8;;{url}\x1b\\{part}\x1b]8;;\x1b\\' for part in pieces]
        rendered = 'Read\n' + '\n'.join(rows)
        original = t.frame

        def wrapped():
            frame = original()
            if t.draft:
                frame.y += len(rows)
                frame.x = 2 + len(pieces[-1])
            frame.raw = frame.raw.replace(t.payload, rendered)
            frame.history = frame.history.replace(t.payload, rendered)
            return frame

        t.frame = wrapped
        self.assertEqual(deliver(t)['receipt'], 'submitted')
        self.assertEqual(t.submitted, t.payload)
        self.assertEqual(t.actions, ['paste', 'Enter'])

    def test_osc8_rejects_malformed_and_mixed_visible_input(self):
        url = 'https://example.org/link'
        open_link = f'\x1b]8;;{url}\x1b\\'
        close_link = '\x1b]8;;\x1b\\'
        for rendered in (open_link + url, url + close_link, open_link + open_link + url + close_link,
                         '\x1b]8;' + url + close_link,
                         '\x1b]0;title\x07' + open_link + url + close_link,
                         open_link + url + close_link + ' extra text'):
            with self.subTest(rendered=rendered):
                t = Terminal(payload=url)
                original = t.frame

                def styled():
                    frame = original()
                    frame.raw = frame.raw.replace(url, rendered)
                    return frame

                t.frame = styled
                with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'):
                    deliver(t)
                self.assertEqual(t.actions, ['paste'])

    def test_codex_unknown_footer_ambiguous_bold_receipt_fails_closed(self):
        base = codex_fixture_frame('SYNTHETIC-codex-idle-unrecognized-footer')
        submitted = '\x1b[1m›\x1b[0m short payload\n\n  I received your message.\n'
        frame = m.Frame(base.raw, base.x, base.y, submitted + base.raw)
        inp = m.composer(frame)
        self.assertEqual(inp.kind, 'empty')
        self.assertEqual(m.records(frame, inp,
                                   archived_codex_status='  GPT-6.1-Sol | main | active')
                         [('submitted', 'shortpayload')], 0)

    def test_codex_unknown_footer_ambiguous_bold_receipt_times_out(self):
        base = codex_fixture_frame('SYNTHETIC-codex-idle-unrecognized-footer')
        t = Terminal(payload='short payload')
        def frame():
            raw = (base.raw.replace('\x1b[2mAsk Codex to do anything\x1b[0m',
                                    t.draft) if t.draft else base.raw)
            submitted = ('\x1b[1m›\x1b[0m short payload\n\n'
                         '  I received your message.\n' if t.accepted_at is not None else '')
            return m.Frame(raw, 2 + m.styles.cell_width(t.draft), base.y,
                           submitted + raw)
        t.frame = frame
        with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
            deliver(t, max_wait=5, stable_wait=3, submit_delay=1, receipt_wait=5)
        self.assertEqual((t.pastes, t.enters, t.accepted_at is not None),
                         (1, 1, True))

    def test_codex_unknown_footer_outside_clear_cannot_turn_archive_into_receipt(self):
        base = codex_fixture_frame('SYNTHETIC-codex-idle-unrecognized-footer')
        for archived_status in ('GPT-6.1-Sol | main | intermediate',
                                'GPT-6.2-Sol | main | intermediate',
                                'GPT-6.2-Sol (main)'):
            with self.subTest(archived_status=archived_status):
                t = Terminal(payload='short payload', dropped=99)
                def frame():
                    visible_text = '' if t.enters else t.draft
                    raw = (base.raw.replace('\x1b[2mAsk Codex to do anything\x1b[0m',
                                            visible_text) if visible_text else base.raw)
                    archived = ''
                    if t.enters:
                        archived = base.raw.replace('\x1b[2mAsk Codex to do anything\x1b[0m',
                                                    t.payload).replace(
                            'GPT-6.1-Sol | main | active', archived_status)
                    return m.Frame(raw, 2 + m.styles.cell_width(visible_text), base.y,
                                   archived + raw)
                t.frame = frame
                with self.assertRaisesRegex(m.DeliveryError, 'receipt-timeout'):
                    deliver(t, max_wait=5, stable_wait=3, submit_delay=1,
                            receipt_wait=5, retry_wait=1)
                self.assertIsNone(t.accepted_at)
                self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_codex_unknown_footer_delivers_multiline_and_collapsed_pastes(self):
        base = codex_fixture_frame('SYNTHETIC-codex-idle-unrecognized-footer')
        for collapsed in (False, True):
            with self.subTest(collapsed=collapsed):
                t = Terminal(payload='first line\nsecond line', collapsed=collapsed)
                def frame():
                    visible = (f'[Pasted Content {len(t.payload)} chars]'
                               if collapsed and t.draft else t.draft)
                    parts = visible.split('\n')
                    raw = base.raw.replace(
                        '\x1b[2mAsk Codex to do anything\x1b[0m',
                        parts[0] + ''.join('\n  ' + part for part in parts[1:])) if visible else base.raw
                    submitted = ('› ' + t.payload.replace('\n', '\n  ') + '\n\n'
                                 if t.accepted_at is not None else '')
                    return m.Frame(raw, 2 + m.styles.cell_width(parts[-1]),
                                   base.y + len(parts) - 1, submitted + raw)
                t.frame = frame
                result = deliver(t, max_wait=5, stable_wait=3, submit_delay=1)
                self.assertEqual((result['status'], result['receipt']),
                                 ('delivered', 'submitted'))
                self.assertEqual((t.pastes, t.enters, t.accepted_at is not None),
                                 (1, 1, True))

    def test_readiness_distinguishes_unknown_from_never_stable(self):
        frame = codex_fixture_frame('codex-2026-10-18-live-current-748-scrubbed')
        for alternating, expected in ((False, 'unsupported-layout'),
                                      (True, 'unstable-composer')):
            with self.subTest(alternating=alternating):
                t = Terminal()
                samples = 0
                def sample():
                    nonlocal samples
                    samples += 1
                    return frame if alternating and samples % 2 == 0 else m.Frame('', -1, -1)
                t.frame = sample
                o = SimpleNamespace(max_wait=1, stable_wait=.75, poll_interval=.25,
                                    backoff=True)
                sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
                with self.assertRaisesRegex(m.DeliveryError, expected):
                    sender.ready()
                self.assertEqual(t.actions, [])

    def test_codex_idle_survives_interleaved_unreadable_snapshots(self):
        # A moving output frame can make a coordinate/capture sample unreadable
        # while the same empty composer remains visible before and after it.
        frame = codex_fixture_frame('codex-2026-10-18-live-current-749-scrubbed')
        t = Terminal()
        samples = 0
        def sample():
            nonlocal samples
            samples += 1
            return m.Frame('', -1, -1) if samples % 4 == 0 else frame
        t.frame = sample
        o = SimpleNamespace(max_wait=5, stable_wait=3, poll_interval=.25,
                            backoff=True)
        sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
        self.assertEqual(sender.ready()[1].kind, 'empty')
        self.assertEqual(t.actions, [])

    def test_unknown_gap_does_not_hide_changed_draft(self):
        t = Terminal()
        samples = iter((screen('alpha'), m.Frame('', -1, -1), screen('beta')))
        t.frame = lambda: next(samples, screen('beta'))
        o = SimpleNamespace(max_wait=5, stable_wait=1, poll_interval=.25,
                            backoff=False)
        sender = m.Sender(t, o, t.payload, Path('/unused'), t.clock, t.sleep)
        with self.assertRaisesRegex(m.DeliveryError, 'human-typing'):
            sender.ready()
        self.assertEqual(t.actions, [])

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

    def test_claude_send_now_queue_remains_ambiguous_without_provenance(self):
        payload = 'SYNTHETIC-QUEUE-ACK full message'
        t = Terminal(payload=payload)
        t.harness = 'claude'
        original = t.frame
        def frame():
            if t.accepted_at is None:
                return original()
            raw = ('● Bash\n\n❯ ' + payload + '\n'
                   '  ctrl+x ctrl+s to send now\n\n'
                   '✶ Improvising…\n──────────────\n'
                   '❯\u00a0\x1b[2mPress up to edit queued messages\x1b[0m\n'
                   '──────────────\nuser@host:repo\n'
                   '⏵⏵ bypass permissions on · ← 1 agent\n\n'
                   '  ● main\n  ◯ worker idle\n')
            return m.Frame(raw, 2, 7, raw)
        t.frame = frame
        with self.assertRaisesRegex(m.DeliveryError, 'mixed-input-after-paste'):
            deliver(t)
        self.assertEqual((t.pastes, t.enters), (1, 1))

    def test_claude_send_now_lookalikes_are_not_receipts(self):
        # These document the nearby prose and altered-hint shapes; the busy
        # frame above is the regression that pins one-Enter ambiguity.
        payload = 'SYNTHETIC-QUEUE-ACK full message'
        for history in ('● assistant: ❯ ' + payload + '\n  ctrl+x ctrl+s to send now\n',
                        '❯ other message\n  ctrl+x ctrl+s to send now\n',
                        '❯ ' + payload + '\n  unrelated hint\n'):
            with self.subTest(history=history):
                f = screen('', history=history, harness='claude')
                records = m.records(f, m.composer(f))
                self.assertEqual(records[('queued', m.normalized(payload))], 0)
                self.assertEqual(records[('submitted', m.normalized(payload))], 0)

    def test_main_rejects_bare_carriage_return_before_tmux_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / 'payload'
            payload.write_bytes(b'one\rtwo')
            o = m.options(['%1', '--prompt-file', str(payload)])
            err = io.StringIO()
            with patch.object(m, 'options', return_value=o), patch.object(m, 'Tmux') as tmux, redirect_stderr(err):
                self.assertEqual(m.main(), 1)
            tmux.assert_not_called()
            self.assertIn('without control characters', err.getvalue())

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


class PasteJournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        environment = patch.dict(os.environ, XDG_STATE_HOME=temp.name,
                                 CLAUDE_SEND_LOCK_DIR=str(self.root / 'locks'))
        environment.start()
        self.addCleanup(environment.stop)
        pending = patch.object(m.tempfile, 'tempdir', temp.name)
        pending.start()
        self.addCleanup(pending.stop)

    def send(self, terminal):
        sender_type = m.Sender

        def sender(*args, **kwargs):
            return sender_type(*args, clock=terminal.clock, sleep=terminal.sleep, **kwargs)

        args = ['tmux-message.py', '%1', '--stable-window', '0', '--submit-delay', '0', terminal.payload]
        out, err = io.StringIO(), io.StringIO()
        with (patch.object(sys, 'argv', args), patch.object(m, 'Tmux', return_value=terminal),
              patch.object(m, 'Sender', side_effect=sender), patch.object(m.signal, 'signal'),
              redirect_stdout(out), redirect_stderr(err)):
            code = m.main()
        return code, json.loads((out if code == 0 else err).getvalue())

    def command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with (patch.object(m, 'Tmux') as tmux, redirect_stdout(out), redirect_stderr(err)):
            code = m.journal_command(args)
        tmux.assert_not_called()
        return code, json.loads((out if code == 0 else err).getvalue())

    def test_zero_enter_record_survives_retry_reuse_and_explicit_resolution(self):
        t = Terminal(payload='Synthetic stranded payload', mutate=True)
        paste = t.paste

        def inspect_then_paste(path):
            attempts = self.command('--unresolved')[1]
            self.assertEqual(len(attempts), 1)
            self.assertIsNone(attempts[0]['outcome'])
            self.assertEqual(Path(attempts[0]['pending_file']), path)
            paste(path)

        t.paste = inspect_then_paste
        code, result = self.send(t)
        self.assertEqual((code, t.actions), (3, ['paste']))
        attempt_id = result['attempt_id']
        pending = Path(result['pending_file'])
        self.assertTrue(result['submit_not_attempted'])
        self.assertEqual((pending.stat().st_mode & 0o777, pending.parent.stat().st_mode & 0o777), (0o600, 0o700))
        self.assertEqual(pending.read_text(), t.payload)
        record, = self.command('--unresolved')[1]
        self.assertEqual(record['receiver'], t.receiver_identity())
        self.assertEqual(record['sender']['pid'], os.getpid())
        self.assertEqual(record['outcome'], {'status': 'ambiguous', 'reason': 'mixed-input-after-paste',
                                             'enters': 0, 'submit_not_attempted': True, 'enter_confirmed': False})

        retry = Terminal(payload='Different outgoing payload')
        code, deferred = self.send(retry)
        self.assertEqual((code, retry.actions, retry.frames), (2, [], 0))
        self.assertEqual(deferred['blocking_attempt_id'], attempt_id)
        self.assertFalse(deferred['paste_attempted'])
        self.assertEqual(self.command('--unresolved')[1], [record])

        retry.pane_pid = '201'  # Same tmux pane ID following respawn.
        self.assertEqual(self.send(retry)[0], 0)
        self.assertEqual(self.command('--unresolved')[1], [record])

        code, _ = self.command('--resolve', attempt_id, '--disposition', 'receiver-replaced')
        self.assertEqual(code, 0)
        self.assertEqual(self.command('--unresolved')[1], [])
        self.assertFalse(pending.exists())
        self.assertEqual(self.command('--resolve', attempt_id, '--disposition', 'receiver-replaced')[0], 0)
        self.assertEqual(self.command('--resolve', attempt_id, '--disposition', 'draft-removed')[0], 2)
        disposition = json.loads((pending.parent / 'resolution.json').read_text())
        self.assertEqual(disposition['disposition'], 'receiver-replaced')

    def test_attempt_state_failure_prevents_paste(self):
        t = Terminal()
        with patch.object(m, 'write_private', side_effect=OSError('synthetic disk fault')):
            code, result = self.send(t)
        self.assertEqual((code, result['reason'], t.actions), (2, 'attempt-state-unavailable', []))
        self.assertFalse(result['input_attempted'])
        self.assertEqual(self.command('--unresolved')[1], [])

    def test_enter_failure_records_attempt_instead_of_zero_enter(self):
        t = Terminal()
        with patch.object(t, 'keys', side_effect=OSError('uncertain Enter')):
            code, result = self.send(t)
        self.assertEqual((code, result['enters'], result['submit_not_attempted']), (3, 1, False))
        self.assertEqual(self.command('--unresolved')[1][0]['outcome']['enters'], 1)

    def test_confirmed_enter_timeout_does_not_block_new_send(self):
        t = Terminal(dropped=2)
        code, result = self.send(t)
        self.assertEqual((code, result['reason'], result['enters']), (3, 'receipt-timeout', 2))
        self.assertFalse(result['submit_not_attempted'])
        self.assertNotIn('attempt_id', result)
        self.assertEqual(Path(result['pending_file']).read_text(), t.payload)
        self.assertEqual(self.command('--unresolved')[1], [])
        replacement = Terminal(payload='A new message to the same empty receiver')
        self.assertEqual(self.send(replacement)[0], 0)
        self.assertEqual(replacement.submitted, replacement.payload)

    def test_crash_leaves_unknown_enter_state_and_payload(self):
        t = Terminal()
        with patch.object(t, 'keys', side_effect=SystemExit(99)), self.assertRaises(SystemExit):
            self.send(t)
        record, = self.command('--unresolved')[1]
        self.assertIsNone(record['outcome'])
        self.assertEqual(Path(record['pending_file']).read_text(), t.payload)
        retry = Terminal(payload='Fresh payload after interrupted send')
        code, result = self.send(retry)
        self.assertEqual((code, result['blocking_attempt_id'], retry.actions), (2, record['id'], []))

    def test_crash_during_completed_cleanup_does_not_strand_payload(self):
        t = Terminal()
        with patch.object(m.PasteJournal, 'cleanup_completed', side_effect=SystemExit(99)):
            with self.assertRaises(SystemExit):
                self.send(t)
        root = self.root / 'tmux-message'
        completed, = root.iterdir()
        self.assertTrue(completed.name.startswith('.'))
        self.assertTrue((completed / 'message').exists())
        self.assertEqual(self.command('--unresolved')[1], [])
        self.assertFalse(completed.exists())


class DiagnosticTests(unittest.TestCase):
    """Owned terminal frames only; no live pane or private incident content."""

    def invoke(self, terminal, diagnostic_file=None, extra=()):
        args = ['tmux-message.py', '%1', '--stable-window', '0', '--submit-delay', '0',
                '--max-wait', '1', '--render-wait', '.03', '--receipt-wait', '.03',
                '--poll-interval', '.01']
        if diagnostic_file is not None:
            args += ['--diagnostic-file', str(diagnostic_file)]
        args += list(extra)
        args += [terminal.payload]
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, XDG_STATE_HOME=tmp), \
                patch.object(m.tempfile, 'tempdir', tmp), \
                patch.object(sys, 'argv', args), patch.object(m, 'Tmux', return_value=terminal), \
                patch.object(m, 'pane_lock', return_value=nullcontext()), \
                redirect_stdout(out), redirect_stderr(err):
            rc = m.main()
        result = json.loads((out if rc == 0 else err).getvalue())
        return rc, result

    def test_opt_in_mixed_capture_is_useful_and_text_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            artifact = private / 'one-attempt.json'
            t = Terminal(payload='OUTGOING_SECRET_秘密🙂')
            original_paste = t.paste
            def paste(path):
                original_paste(path)
                t.draft += ' HUMAN_SECRET_é'
            t.paste = paste
            original_frame = t.frame
            def frame():
                result = original_frame()
                result.width, result.height = 80, 24
                return result
            t.frame = frame
            rc, result = self.invoke(t, artifact)
            self.assertEqual((rc, result['status'], result['reason']), (3, 'ambiguous', 'mixed-input-after-paste'))
            self.assertEqual(t.actions, ['paste'])
            self.assertTrue(artifact.is_file())
            self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
            data = json.loads(artifact.read_text())
            self.assertEqual(data['schema'], 'tmux-message-structure-v1')
            self.assertEqual(data['enters'], 0)
            self.assertEqual(data['post_paste'][-1]['kind'], 'text')
            self.assertEqual(data['post_paste'][-1]['dimensions'], [80, 24])
            self.assertTrue(data['post_paste'][-1]['rows'])
            self.assertEqual(data['post_paste'][-1]['structure'], 'available')
            self.assertTrue(data['post_paste'][-1]['rows'][0]['layout'].startswith('# '))
            encoded = artifact.read_text()
            self.assertNotIn('Any model', encoded)
            for secret in ('OUTGOING_SECRET', 'HUMAN_SECRET', '秘密', '🙂', 'é'):
                self.assertNotIn(secret, encoded)
            self.assertEqual(set(data), {'schema', 'outcome', 'reason', 'input_method', 'enters',
                                         'pre_paste', 'post_paste', 'events', 'truncated'})
            for sample in [data['pre_paste']] + data['post_paste']:
                self.assertEqual(set(sample), {'phase', 'elapsed_ms', 'dimensions', 'cursor',
                                               'kind', 'harness', 'structure', 'rows',
                                               'markers', 'predicates'})
                self.assertIn(sample['phase'], {'readiness', 'post_paste'})
                self.assertIn(sample['kind'], {'empty', 'text', 'suggestion', 'modal', 'unknown'})
                self.assertIn(sample['harness'], {'codex', 'claude', 'unknown'})
                self.assertTrue(all(re.fullmatch(r'[ #\t]*', row['layout']) for row in sample['rows']))
                for row in sample['rows']:
                    self.assertEqual(set(row), {'layout', 'styles'})
                    for span in row['styles']:
                        self.assertEqual(set(span), {'start', 'end', 'flags'})
                        self.assertTrue(set(span['flags']) <= {'bold', 'dim', 'italic', 'underline', 'inverse', 'fg', 'bg'})
                self.assertTrue(all(set(marker) == {'type', 'count'} for marker in sample['markers']))
            self.assertTrue(any(sample['predicates'].get('input_evidence') is False for sample in data['post_paste']))

    def test_opt_out_and_unsafe_symlink_do_not_create_artifact_or_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            with patch.object(m, 'StructuralDiagnostic', wraps=m.StructuralDiagnostic) as constructor, \
                    patch.object(m, 'structural_sample', wraps=m.structural_sample) as sampler, \
                    patch.object(m.DiagnosticFile, 'reserve', side_effect=AssertionError('opt-out wrote diagnostic')) as reserve:
                rc, result = self.invoke(Terminal(payload='synthetic'))
                constructor.assert_not_called()
                sampler.assert_not_called()
                reserve.assert_not_called()
            self.assertEqual((rc, result['status']), (0, 'delivered'))
            self.assertNotIn('diagnostic_status', result)
            link = Path(tmp) / 'link'
            link.symlink_to(private, target_is_directory=True)
            t = Terminal(payload='synthetic')
            rc, result = self.invoke(t, link / 'unsafe.json')
            self.assertEqual(rc, 1)
            self.assertEqual(t.actions, [])
            self.assertFalse((private / 'unsafe.json').exists())

    def test_sgr_unicode_control_and_unknown_structure_are_safe(self):
        raw = '\x1b[1m›\x1b[0m e\u0301 界\n\n  footer\n'
        frame = m.Frame(raw, 6, 0, width=80, height=24)
        inp = m.Input('text', 'e\u0301 界', 0, 1, (6, 0), 'codex')
        sample = m.structural_sample(frame, inp, 'post_paste', 30)
        self.assertEqual(sample['structure'], 'available')
        self.assertEqual(sample['rows'][0]['layout'], '# # ##')
        self.assertEqual(sample['rows'][0]['styles'], [{'start': 0, 'end': 1, 'flags': ['bold']}])
        self.assertNotIn('footer', json.dumps(sample))
        for poison in ('\x1b]8;;https://OSC_SECRET\x07', '\x1b]0;OSC_SECRET\x1b\\',
                       '\x1bPPRIVATE_CONTROL\x1b\\', '\x1b[1;MALFORMED_SECRETm',
                       '\u202eBIDI_SECRET', '\x1b[38;5m', '\x1b[38;2;1;2m'):
            bad = m.Frame('› ' + poison + ' HUMAN_SECRET\n\n  footer\n', 3, 0, width=80, height=24)
            result = m.structural_sample(bad, m.Input('text', poison + ' HUMAN_SECRET', 0, 1, (3, 0), 'codex'), 'post_paste', 30)
            self.assertEqual(result['structure'], 'unavailable')
            self.assertEqual(result['rows'], [])
            for secret in ('OSC_SECRET', 'PRIVATE_CONTROL', 'MALFORMED_SECRET', 'BIDI_SECRET', 'HUMAN_SECRET'):
                self.assertNotIn(secret, json.dumps(result))
        result = m.structural_sample(frame, m.Input('unknown'), 'post_paste', 30)
        self.assertEqual(result['rows'], [])
        marked = m.structural_sample(m.Frame('› [Pasted Content 17 chars]\n', 2, 0),
                                     m.Input('text', '[Pasted Content 17 chars]', 0, 1, (2, 0), 'codex'),
                                     'post_paste', 30)
        self.assertEqual(marked['markers'], [{'type': 'codex_prompt', 'count': 1},
                                             {'type': 'pasted_content', 'count': 17}])
        for escape in ('\x1b[38;5;1m', '\x1b[38;2;1;2;3m', '\x1b[48;5;2m'):
            colored = m.structural_sample(m.Frame('› ' + escape + 'x\n', 2, 0),
                                          m.Input('text', 'x', 0, 1, (2, 0), 'codex'),
                                          'post_paste', 30)
            flags = colored['rows'][0]['styles'][-1]['flags']
            self.assertTrue(set(flags) <= {'fg', 'bg'})
            self.assertTrue(flags)

    def test_structure_bounds(self):
        rows = ['› ' + 'x' * 1000] + ['  ' + 'y' * 1000 for _ in range(30)]
        frame = m.Frame('\n'.join(rows) + '\n', 3, 0, width=5000, height=5000)
        inp = m.Input('text', 'x' * 1000, 0, len(rows), (3, 0), 'codex')
        sample = m.structural_sample(frame, inp, 'post_paste', 99999999)
        self.assertEqual(sample['structure'], 'truncated')
        self.assertLessEqual(len(sample['rows']), 12)
        self.assertTrue(all(len(row['layout']) <= 160 for row in sample['rows']))
        self.assertEqual(sample['dimensions'], [0, 0])
        self.assertEqual(sample['elapsed_ms'], 99999999)
        self.assertEqual(m.structural_sample(frame, inp, 'post_paste', 9999999999)['elapsed_ms'], 2147483647)
        alternating = ''.join(('\x1b[1m' if i % 2 else '\x1b[0m') + 'x' for i in range(120))
        many_styles = m.structural_sample(m.Frame('› ' + alternating + '\n', 2, 0),
                                          m.Input('text', 'x' * 120, 0, 1, (2, 0), 'codex'),
                                          'post_paste', 30)
        self.assertEqual(many_styles['structure'], 'truncated')
        self.assertLessEqual(len(many_styles['rows'][0]['styles']), 32)
        self.assertGreater(len(many_styles['rows'][0]['layout']), 2)
        recorder = m.StructuralDiagnostic(clock=lambda: 0)
        for _ in range(30):
            recorder.observe(frame, inp, 'post_paste')
        self.assertEqual(len(recorder.post_paste), 16)
        self.assertTrue(recorder.truncated)
        self.assertLessEqual(len(recorder.to_bytes('ambiguous', 'mixed-input-after-paste', 'paste', 0)), 65536)

    def test_on_off_send_actions_and_transport_results_match(self):
        def terminal(case):
            t = ClaudeExitTerminal() if case == 'literal' else Terminal(payload='/status' if case == 'typed' else 'synthetic')
            if case == 'mixed':
                original = t.paste
                def paste(path):
                    original(path)
                    t.draft += ' human'
                t.paste = paste
            elif case == 'typing':
                original = t.frame
                calls = 0
                def frame():
                    nonlocal calls
                    calls += 1
                    if calls >= 2:
                        t.draft = 'human'
                    return original()
                t.frame = frame
            elif case == 'modal':
                t.frame = lambda: m.Frame('Quick safety check\n', 0, 0)
            return t
        for case in ('delivered', 'mixed', 'typing', 'modal', 'typed', 'literal'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                private = Path(tmp) / 'private'
                private.mkdir(mode=0o700)
                off, on = terminal(case), terminal(case)
                extra = ('--typed-command',) if case == 'typed' else ('--literal-exit',) if case == 'literal' else ()
                off_rc, off_result = self.invoke(off, extra=extra)
                on_rc, on_result = self.invoke(on, private / 'record.json', extra=extra)
                self.assertEqual(on_rc, off_rc)
                self.assertEqual(on.actions, off.actions)
                self.assertEqual({k: v for k, v in on_result.items() if k not in {'diagnostic_status', 'pending_file', 'attempt_id'}},
                                 {k: v for k, v in off_result.items() if k not in {'pending_file', 'attempt_id'}})
                self.assertEqual(on_result['diagnostic_status'], 'written')
                self.assertTrue((private / 'record.json').exists())
                artifact = (private / 'record.json').read_text()
                self.assertNotIn(ClaudeExitTerminal.session, artifact)
                if case == 'literal':
                    self.assertTrue(json.loads(artifact)['post_paste'][-1]['predicates']['command_completion'])

    def test_late_write_and_serialization_failure_preserve_transport(self):
        for failure in ('write', 'serialize', 'replace'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                private = Path(tmp) / 'private'
                private.mkdir(mode=0o700)
                artifact = private / 'record.json'
                t = Terminal(payload='synthetic')
                if failure == 'serialize':
                    patcher = patch.object(m.StructuralDiagnostic, 'to_bytes', side_effect=ValueError('PRIVATE_EXCEPTION'))
                else:
                    def fail_write(_fd, _data):
                        if failure == 'replace':
                            artifact.rename(private / 'original-moved')
                            artifact.write_text('UNRELATED_FILE')
                        raise OSError('PRIVATE_EXCEPTION')
                    patcher = patch.object(m.os, 'write', side_effect=fail_write)
                with patcher:
                    rc, result = self.invoke(t, artifact)
                self.assertEqual((rc, result['status'], result['receipt'], result['enters']), (0, 'delivered', 'submitted', 1))
                self.assertEqual(result['diagnostic_status'], 'write-failed')
                self.assertEqual(t.actions, ['paste', 'Enter'])
                if failure == 'replace':
                    self.assertEqual(artifact.read_text(), 'UNRELATED_FILE')
                else:
                    self.assertFalse(artifact.exists())
                self.assertNotIn('PRIVATE_EXCEPTION', json.dumps(result))

    def test_replaced_reserved_name_is_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            artifact = private / 'record.json'
            reserved = m.DiagnosticFile.reserve(artifact)
            artifact.rename(private / 'original-moved')
            artifact.write_text('UNRELATED_FILE')
            reserved.abort()
            self.assertEqual(artifact.read_text(), 'UNRELATED_FILE')
            self.assertTrue((private / 'original-moved').exists())

    def test_replacement_before_write_reports_safe_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            artifact = private / 'record.json'
            original = m.StructuralDiagnostic.to_bytes
            def replaced(diag, *args):
                data = original(diag, *args)
                artifact.rename(private / 'original-moved')
                artifact.write_text('UNRELATED_FILE')
                return data
            t = Terminal(payload='synthetic')
            with patch.object(m.StructuralDiagnostic, 'to_bytes', replaced):
                rc, result = self.invoke(t, artifact)
            self.assertEqual((rc, result['status'], result['receipt'], result['enters']), (0, 'delivered', 'submitted', 1))
            self.assertEqual(result['diagnostic_status'], 'write-failed')
            self.assertEqual(t.actions, ['paste', 'Enter'])
            self.assertEqual(artifact.read_text(), 'UNRELATED_FILE')
            self.assertEqual((private / 'original-moved').read_bytes(), b'')

    def test_unsafe_parent_mode_and_existing_file_stop_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            private.chmod(0o770)
            t = Terminal(payload='synthetic')
            rc, result = self.invoke(t, private / 'record.json')
            self.assertEqual((rc, result['reason'], t.actions), (1, 'unsafe-diagnostic-path', []))
            private.chmod(0o700)
            (private / 'record.json').write_text('UNRELATED_FILE')
            t = Terminal(payload='synthetic')
            rc, result = self.invoke(t, private / 'record.json')
            self.assertEqual((rc, result['reason'], t.actions), (1, 'unsafe-diagnostic-path', []))
            self.assertEqual((private / 'record.json').read_text(), 'UNRELATED_FILE')

    def test_tmux_frame_width_metadata_is_defensive(self):
        tmux = m.Tmux.__new__(m.Tmux)
        tmux.pane = '%1'
        for width in ('80', 'unavailable'):
            with self.subTest(width=width):
                def run(*args):
                    if args[0] == 'display-message':
                        return '2:0:' + width + ':3:0\n'
                    return '› synthetic\n\n  Any model · branch\n'
                tmux.run = run
                frame = tmux.frame()
                self.assertEqual(frame.width, 80 if width == '80' else 0)
                self.assertEqual((frame.x, frame.y), (2, 0))

    def test_ambiguous_write_failure_preserves_original_result_and_actions(self):
        def terminal():
            t = Terminal(payload='synthetic')
            original = t.paste
            def paste(path):
                original(path)
                t.draft += ' human'
            t.paste = paste
            return t
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            off, on = terminal(), terminal()
            off_rc, off_result = self.invoke(off)
            with patch.object(m.StructuralDiagnostic, 'to_bytes', side_effect=OSError('PRIVATE_EXCEPTION')):
                on_rc, on_result = self.invoke(on, private / 'record.json')
            self.assertEqual((on_rc, on.actions), (off_rc, off.actions))
            self.assertEqual({k: v for k, v in on_result.items() if k not in {'pending_file', 'diagnostic_status', 'attempt_id'}},
                             {k: v for k, v in off_result.items() if k not in {'pending_file', 'attempt_id'}})
            self.assertEqual(on_result['diagnostic_status'], 'write-failed')
            self.assertFalse((private / 'record.json').exists())

    def test_interruption_during_sample_keeps_transport_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            off, on = Terminal(payload='synthetic'), Terminal(payload='synthetic')
            original_frame = off.frame
            def interrupted_frame():
                if 'paste' in off.actions:
                    raise m.DeliveryError('signal-15', 143)
                return original_frame()
            off.frame = interrupted_frame
            off_rc, off_result = self.invoke(off)
            original_sample = m.structural_sample
            def interrupted_sample(frame, inp, phase, elapsed):
                if phase == 'post_paste':
                    raise m.DeliveryError('signal-15', 143)
                return original_sample(frame, inp, phase, elapsed)
            with patch.object(m, 'structural_sample', side_effect=interrupted_sample):
                on_rc, on_result = self.invoke(on, private / 'record.json')
            self.assertEqual((off_rc, on_rc), (143, 143))
            self.assertEqual(off.actions, on.actions)
            self.assertEqual({k: v for k, v in on_result.items() if k not in {'pending_file', 'diagnostic_status', 'attempt_id'}},
                             {k: v for k, v in off_result.items() if k not in {'pending_file', 'attempt_id'}})
            self.assertTrue((private / 'record.json').exists())

    def test_unsafe_path_components_and_owner_stop_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir(mode=0o700)
            nested = private / 'nested'
            nested.mkdir(mode=0o700)
            middle = Path(tmp) / 'middle'
            middle.symlink_to(private, target_is_directory=True)
            paths = (Path('relative.json'), private / '..' / 'private' / 'dotdot.json',
                     middle / 'nested' / 'symlink.json')
            for path in paths:
                with self.subTest(path=path):
                    t = Terminal(payload='synthetic')
                    rc, result = self.invoke(t, path)
                    self.assertEqual((rc, result['reason'], t.actions), (1, 'unsafe-diagnostic-path', []))
            original_fstat = m.os.fstat
            def wrong_owner(fd):
                state = original_fstat(fd)
                if fd != 0 and state.st_ino == private.stat().st_ino:
                    return SimpleNamespace(st_uid=os.getuid() + 1, st_mode=state.st_mode)
                return state
            with patch.object(m.os, 'fstat', side_effect=wrong_owner):
                t = Terminal(payload='synthetic')
                rc, result = self.invoke(t, private / 'owner.json')
            self.assertEqual((rc, result['reason'], t.actions), (1, 'unsafe-diagnostic-path', []))


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
        ('claude_dim_suggestion_guard', '(end == idx + 1 and styles.dim_span(raw[idx], first))',
         '(end == idx + 1)'),
        ('diagnostic_opt_in', 'diagnostic=StructuralDiagnostic() if diagnostic_file is not None else None',
         'diagnostic=StructuralDiagnostic()'),
        ('diagnostic_redaction', 'replacement = "#" * width', 'replacement = char * width'),
        ('diagnostic_useful_structure', 'sample["rows"].append(row)',
         'sample["rows"].append({"layout": "", "styles": []})'),
        ('diagnostic_signal', 'except DeliveryError:\n            raise\n        except Exception:',
         'except DeliveryError:\n            return\n        except Exception:'),
    ]
    with tempfile.TemporaryDirectory(prefix='tmux-message-mutations-') as tmp:
        target = Path(tmp)
        scripts = target / 'skills' / 'spawn-agent' / 'scripts'
        scripts.mkdir(parents=True)
        for name in ('test-tmux-message.py', 'claude-send-screen.py'):
            shutil.copy2(root / name, scripts / name)
        shared = target / 'skills' / '_shared'
        shared.mkdir()
        shutil.copy2(root.parents[1] / '_shared' / 'agent_skills_config.py', shared)
        shutil.copytree(root / 'fixtures', scripts / 'fixtures')
        for name, before, after in cases:
            assert original.count(before) == 1, name
            code = original.replace(before, after)
            compile(code, name, 'exec')
            (scripts / 'tmux-message.py').write_text(code)
            command = [sys.executable, str(scripts / 'test-tmux-message.py')]
            if name == 'claude_dim_suggestion_guard':
                command += ['-k', 'claude_dim_suggestion_requires_start_single_row_and_full_style']
            result = subprocess.run(command,
                                    capture_output=True, text=True, timeout=30)
            assert result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr, (name, result.stderr)
            print('killed:', name)



class VerifyCompactTests(unittest.TestCase):
    def send(self, terminal, *arguments):
        out, err = io.StringIO(), io.StringIO()
        argv = ['tmux-message.py', '%1', '--verify-compact', '--stable-window', '.25',
                '--submit-delay', '.5', '--render-wait', '1', '--receipt-wait', '2',
                '--max-wait', '2', '--poll-interval', '.25', *arguments]
        sender_type = m.Sender

        def sender(*args, **kwargs):
            return sender_type(*args, clock=terminal.clock, sleep=terminal.sleep, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / 'pending'
            pending.mkdir(mode=0o700)
            with (patch.dict(os.environ, XDG_STATE_HOME=tmp),
                  patch.object(sys, 'argv', argv),
                  patch.object(m, 'Tmux', return_value=terminal) as resolve,
                  patch.object(m, 'Sender', side_effect=sender),
                  patch.object(m, 'pane_lock', return_value=nullcontext()),
                  patch.object(m.signal, 'signal'),
                  patch.object(m.tempfile, 'mkdtemp', return_value=str(pending)),
                  redirect_stdout(out), redirect_stderr(err)):
                try:
                    code = m.main()
                except SystemExit as exit:
                    code = exit.code
            result = json.loads(out.getvalue() if code == 0 else err.getvalue())
            if code == 1:
                resolve.assert_not_called()
                self.assertFalse((pending / 'message').exists())
            elif code == 0:
                self.assertFalse(pending.exists())
            else:
                payload = Path(result['pending_file'])
                self.assertEqual(payload.read_text(), '/compact')
                self.assertEqual(payload.stat().st_mode & 0o777, 0o600)
            return code, result

    def compact(self, terminal):
        return self.send(terminal, '--typed-command', '/compact')

    def assert_unknown(self, terminal, enters):
        code, result = self.compact(terminal)
        self.assertEqual(code, 3, result)
        self.assertEqual(result['command_outcome'], 'unknown')
        self.assertEqual(result['status'], 'ambiguous')
        self.assertTrue(result['input_attempted'])
        self.assertFalse(result['paste_attempted'])
        self.assertTrue(result['needs_review'])
        self.assertEqual(result['enters'], enters)
        self.assertEqual(terminal.actions, ['typed:/compact'] + ['Enter'] * enters)
        return result

    def test_fresh_completion_with_and_without_elapsed_time(self):
        for duration in ('', ' · 14s', ' · 1m 04s', ' · 2h 01m 04s'):
            with self.subTest(duration=duration):
                terminal = CompactTerminal(lambda elapsed: COMPACT_COMPLETE + duration + '\n')
                # Both copies of an identical row must be visibly present.
                terminal.visible_history = COMPACT_COMPLETE + '\n'
                code, result = self.compact(terminal)
                self.assertEqual(code, 0, result)
                self.assertEqual(result['command_outcome'], 'completed')
                self.assertEqual(result['receipt'], 'command')
                self.assertEqual(terminal.actions, ['typed:/compact', 'Enter'])

    def test_fresh_busy_refusal_is_distinct_even_when_command_remains(self):
        class BusyTerminal(CompactTerminal):
            def keys(self, *keys):
                super().keys(*keys)
                self.draft = '/compact'

        terminal = BusyTerminal(lambda elapsed: COMPACT_REFUSAL + '\n')
        terminal.history = COMPACT_COMPLETE + '\n'
        code, result = self.compact(terminal)
        self.assertEqual(code, 3, result)
        self.assertEqual(result['command_outcome'], 'refused')
        self.assertEqual(result['status'], 'refused')
        self.assertEqual(result['reason'], 'compact-refused')
        self.assertEqual(terminal.draft, '/compact')
        self.assertEqual(terminal.actions, ['typed:/compact', 'Enter'])

    def test_pre_enter_notice_is_stale(self):
        for notice in (COMPACT_COMPLETE, COMPACT_REFUSAL):
            with self.subTest(notice=notice):
                terminal = CompactTerminal()
                type_command = terminal.type_command

                def render_before_enter(text):
                    type_command(text)
                    terminal.visible_history += notice + '\n'

                terminal.type_command = render_before_enter
                self.assert_unknown(terminal, enters=1)

    def test_redrawn_notice_with_duplicate_scrollback_stays_unknown(self):
        for notice in (COMPACT_COMPLETE, COMPACT_REFUSAL):
            for copies in (1, 3):
                with self.subTest(notice=notice, total_copies=copies):
                    terminal = CompactTerminal()
                    terminal.visible_history = notice + '\n'
                    frame = terminal.frame

                    def capture():
                        if terminal.enters:
                            # Repeated full-screen erase archives the old screen
                            # while repainting a single copy in the live frame.
                            terminal.history = terminal.visible_history * (copies - 1)
                        return frame()

                    terminal.frame = capture
                    self.assert_unknown(terminal, enters=1)

    def test_non_positive_width_cannot_verify_compact(self):
        for phase in ('baseline', 'receipt'):
            for width in (0, -1):
                with self.subTest(phase=phase, width=width):
                    terminal = CompactTerminal(lambda elapsed: COMPACT_COMPLETE + '\n')
                    frame = terminal.frame

                    def capture():
                        current = frame()
                        if phase == 'baseline' and terminal.draft and not terminal.enters:
                            current.width = width
                        if phase == 'receipt' and terminal.enters:
                            current.width = width
                        return current

                    terminal.frame = capture
                    enters = 0 if phase == 'baseline' else 1
                    result = self.assert_unknown(terminal, enters=enters)
                    self.assertEqual(result['reason'], 'unsupported-layout')
                    if phase == 'baseline':
                        self.assertEqual(terminal.draft, '/compact')

    def test_widening_cannot_make_wrapped_old_refusal_fresh(self):
        terminal = CompactTerminal()
        refusal = m.styles.strip_ansi(COMPACT_REFUSAL)

        def capture():
            if terminal.enters:
                prefix, width = refusal + '\n', 80
            else:
                width = 40
                prefix = refusal[:width] + '\n' + refusal[width:] + '\n'
            frame = screen(terminal.draft, prefix=prefix)
            frame.width = width
            return frame

        terminal.frame = capture
        self.assert_unknown(terminal, enters=1)

    def test_distinct_fresh_notice_can_confirm_despite_repaint(self):
        terminal = CompactTerminal()
        old_notice = COMPACT_COMPLETE + '\n'
        terminal.visible_history = old_notice
        frame = terminal.frame

        def capture():
            if terminal.enters:
                # The new timed notice has already scrolled off the screen.
                terminal.history = old_notice * 3 + COMPACT_COMPLETE + ' · 14s\n'
            return frame()

        terminal.frame = capture
        code, result = self.compact(terminal)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['command_outcome'], 'completed')
        self.assertEqual(terminal.actions, ['typed:/compact', 'Enter'])

    def test_quiet_progress_ordinary_receipts_and_other_text_are_unknown(self):
        for rows in ('', '• Compacting context (8s)\n', '› /compact\n',
                     '• Messages to be submitted\n  ↳ /compact\n',
                     '• Context compacted but the task is still running\n',
                     '• Context compacted · 1m 2s\n',
                     '• The log contains: • Context compacted\n',
                     "  ■ '/compact' is disabled while a task is in progress.\n"):
            with self.subTest(rows=rows):
                terminal = CompactTerminal(lambda elapsed: rows)
                terminal.history = COMPACT_COMPLETE + '\n' + COMPACT_REFUSAL + '\n'
                self.assert_unknown(terminal, enters=1)

    def test_conflict_within_the_receipt_window_is_unknown(self):
        terminal = CompactTerminal(lambda elapsed: (
            COMPACT_COMPLETE if elapsed < 1 else COMPACT_REFUSAL) + '\n')
        code, result = self.compact(terminal)
        self.assertEqual(code, 3, result)
        self.assertEqual(result['command_outcome'], 'unknown')
        self.assertEqual(result['reason'], 'conflicting-command-evidence')
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual(terminal.actions, ['typed:/compact', 'Enter'])

    def test_evidence_at_or_after_deadline_is_outside_attempt(self):
        self.assert_unknown(CompactTerminal(
            lambda elapsed: COMPACT_COMPLETE + '\n' if elapsed >= 2 else ''), enters=1)

    def test_receipt_window_starts_after_slow_enter_returns(self):
        class SlowEnter(CompactTerminal):
            def keys(self, *keys):
                self.sleep(3)
                super().keys(*keys)

        terminal = SlowEnter(lambda elapsed: COMPACT_COMPLETE + '\n' if elapsed >= 1.75 else '')
        code, result = self.compact(terminal)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['command_outcome'], 'completed')
        self.assertEqual(terminal.now, terminal.accepted_at + 2)
        self.assertEqual(terminal.actions, ['typed:/compact', 'Enter'])

    def test_late_capture_cannot_prove_completion(self):
        terminal = CompactTerminal(lambda elapsed: COMPACT_COMPLETE + '\n')
        frame = terminal.frame

        def capture():
            if terminal.enters:
                terminal.sleep(2)
            return frame()

        terminal.frame = capture
        self.assert_unknown(terminal, enters=1)

    def test_unsupported_or_modal_frame_after_enter_cannot_prove_completion(self):
        for layout in ('unknown', 'modal', 'claude'):
            with self.subTest(layout=layout):
                terminal = CompactTerminal(lambda elapsed: COMPACT_COMPLETE + '\n')
                frame = terminal.frame

                def capture():
                    if not terminal.enters:
                        return frame()
                    if layout == 'modal':
                        if terminal.now - terminal.accepted_at < .5:
                            return frame()
                        return screen(prefix=COMPACT_COMPLETE + '\nWould you like to proceed?\n',
                                      width=terminal.width)
                    if layout == 'claude':
                        return screen(harness='claude', prefix=COMPACT_COMPLETE + '\n',
                                      width=terminal.width)
                    captured = frame()
                    captured.x = captured.y = -1
                    return captured

                terminal.frame = capture
                self.assert_unknown(terminal, enters=1)

    def test_look_at_enter_rejects_lost_ownership(self):
        for changed in ('cursor', 'mixed', 'unknown', 'empty', 'claude'):
            with self.subTest(changed=changed):
                terminal = CompactTerminal()
                frame = terminal.frame
                last_poll = None

                def capture():
                    nonlocal last_poll
                    current = frame()
                    # The final capture immediately follows a regular poll.
                    if not terminal.draft or last_poll != terminal.now:
                        last_poll = terminal.now
                        return current
                    if changed == 'cursor':
                        current.x = 2
                        return current
                    if changed == 'mixed':
                        return screen('/compact human', width=terminal.width)
                    if changed == 'unknown':
                        return m.Frame('', -1, -1, width=terminal.width)
                    if changed == 'empty':
                        return screen(width=terminal.width)
                    return screen('/compact', harness='claude', width=terminal.width)

                terminal.frame = capture
                self.assert_unknown(terminal, enters=0)

    def test_raw_whitespace_after_typing_is_preserved(self):
        cases = (
            ('blank continuation', '\n', ''),
            ('trailing space', ' ', ''),
            ('space in separator', '', ' '),
        )
        for phase in ('post-type', 'pre-enter'):
            for shape, suffix, separator in cases:
                with self.subTest(phase=phase, shape=shape):
                    terminal = CompactTerminal()
                    frame = terminal.frame
                    last_poll = None
                    changed = None

                    def capture():
                        nonlocal last_poll, changed
                        if not terminal.draft or terminal.enters:
                            return frame()
                        if changed is not None:
                            return changed
                        current = frame()
                        final_capture = terminal.now == last_poll
                        last_poll = terminal.now
                        if phase == 'post-type' or final_capture:
                            terminal.draft += suffix
                            changed = screen(terminal.draft, width=terminal.width)
                            changed.x, changed.y = current.x, 0
                            if separator:
                                changed.raw = changed.raw.replace('\n\n', f'\n{separator}\n')
                                changed.history = changed.raw
                            self.assertEqual(m.composer(changed).fingerprint(),
                                             m.composer(current).fingerprint())
                            return changed
                        return current

                    terminal.frame = capture
                    result = self.assert_unknown(terminal, enters=0)
                    reason = ('input-changed-after-paste' if phase == 'post-type'
                              else 'input-changed-before-enter')
                    self.assertEqual(result['reason'], reason)
                    self.assertEqual(terminal.draft, '/compact' + suffix)

    def test_dropped_enter_is_never_retried(self):
        terminal = CompactTerminal(dropped=1)
        self.assert_unknown(terminal, enters=1)
        self.assertEqual(terminal.draft, '/compact')

    def test_typing_or_enter_transport_failure_is_unknown(self):
        for phase, enters in (('type_command', 0), ('keys', 1)):
            with self.subTest(phase=phase):
                terminal = CompactTerminal()
                action = getattr(terminal, phase)

                def fail(*args):
                    action(*args)
                    raise OSError('synthetic tmux operation failed')

                setattr(terminal, phase, fail)
                self.assert_unknown(terminal, enters=enters)

    def test_interruption_after_typing_reports_unknown(self):
        terminal = CompactTerminal()
        type_command = terminal.type_command

        def interrupt(text):
            type_command(text)
            raise m.DeliveryError('signal-15', 143)

        terminal.type_command = interrupt
        self.assert_unknown(terminal, enters=0)

    def test_ineligible_route_or_argument_never_resolves_a_pane(self):
        for arguments in (('/compact',), ('--typed-command', '/compact now'),
                          ('--typed-command', '/compact', 'now'),
                          ('--typed-command', '/compact '), ('--typed-command', ' /compact'),
                          ('--typed-command', '/compact\n'), ('--typed-command', '/status'),
                          ('--typed-command', '--literal-exit', '/compact'),
                          ('--typed-command', '--prompt-file', '/unknown'),
                          ('--typed-command', '--prompt-file', '/unknown', '/compact'),
                          ('--typed-command',)):
            with self.subTest(arguments=arguments):
                terminal = CompactTerminal()
                code, result = self.send(terminal, *arguments)
                self.assertEqual(code, 1, result)
                self.assertNotIn('command_outcome', result)
                self.assertEqual(terminal.actions, [])

    def test_only_a_verified_empty_codex_composer_can_be_typed_into(self):
        for draft, harness, reason in (('human draft', 'codex', 'existing-input'),
                                        ('/status', 'codex', 'existing-input'),
                                        ('/compact', 'codex', 'existing-input'),
                                        ('', 'claude', 'compact-requires-codex'),
                                        ('Try "draft"', 'claude', 'compact-requires-codex'),
                                        ('', 'unknown', 'unsupported-layout'),
                                        ('', 'modal', 'modal')):
            with self.subTest(draft=draft, harness=harness):
                terminal = CompactTerminal(draft=draft)
                terminal.harness = harness
                if harness == 'unknown':
                    terminal.frame = lambda: m.Frame('shell $', 7, 0)
                elif harness == 'modal':
                    terminal.frame = lambda: m.Frame('Would you like to proceed?\n› yes\n', 2, 1)
                elif draft.startswith('Try '):
                    terminal.frame = lambda: m.Frame(screen(draft, harness='claude').raw, 2, 1)
                code, result = self.compact(terminal)
                self.assertEqual(code, 2, result)
                self.assertEqual(result['reason'], reason)
                self.assertNotIn('command_outcome', result)
                self.assertFalse(result['input_attempted'])
                self.assertEqual(terminal.actions, [])
                self.assertEqual(terminal.draft, draft)

    def test_observable_blank_drafts_are_preserved(self):
        cases = (
            ('   ', '', (5, 0), ''),
            ('   ', '   ', (2, 0), ''),
            ('\n', '\n', (2, 1), ''),
            ('\n', '\n', (2, 0), ''),
            ('\n  ', '', (2, 0), '  '),
        )
        for draft, visible, cursor, separator in cases:
            with self.subTest(draft=draft, visible=visible, cursor=cursor):
                terminal = CompactTerminal(draft=draft)

                def capture():
                    current = screen(visible)
                    if separator:
                        current.raw = current.raw.replace('\n\n', f'\n{separator}\n')
                        current.history = current.raw
                    current.x, current.y = cursor
                    return current

                terminal.frame = capture
                self.assertEqual(m.composer(capture()).kind, 'empty')
                code, result = self.compact(terminal)
                self.assertEqual(code, 2, result)
                self.assertEqual(result['reason'], 'existing-input')
                self.assertFalse(result['input_attempted'])
                self.assertEqual(terminal.actions, [])
                self.assertEqual(terminal.draft, draft)

    def test_blank_row_added_at_final_check_is_preserved_at_home(self):
        terminal = CompactTerminal()
        frame = terminal.frame

        def capture():
            current = frame()
            if terminal.frames == 3:
                terminal.draft = '\n'
                new_draft = screen(terminal.draft)
                new_draft.y = 0
                self.assertEqual(m.composer(new_draft).fingerprint(),
                                 m.composer(current).fingerprint())
                return new_draft
            return current

        terminal.frame = capture
        code, result = self.compact(terminal)
        self.assertEqual(code, 2, result)
        self.assertEqual(result['reason'], 'input-changed-before-paste')
        self.assertFalse(result['input_attempted'])
        self.assertEqual(terminal.actions, [])
        self.assertEqual(terminal.draft, '\n')

    def test_measured_dim_codex_placeholder_classifies_as_empty(self):
        idle = codex_fixture_frame('codex-fork-empty')
        inp = m.composer(idle)
        self.assertEqual((inp.harness, inp.kind, inp.text, inp.cursor),
                         ('codex', 'empty', '', (2, 0)))
        self.assertTrue(m.styles.dim_span(idle.raw.splitlines()[inp.start],
                                          'Ask Codex to do anything'))
        typed = codex_fixture_frame('codex-fork-compact')
        terminal = CompactTerminal(lambda elapsed: COMPACT_COMPLETE + '\n')
        idle.width = typed.width = terminal.width
        frame = terminal.frame

        def capture():
            if not terminal.actions:
                return idle
            if not terminal.enters:
                return typed
            return frame()

        terminal.frame = capture
        code, result = self.compact(terminal)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['command_outcome'], 'completed')
        self.assertEqual(terminal.actions, ['typed:/compact', 'Enter'])

    def test_new_draft_during_final_readiness_check_is_preserved(self):
        terminal = CompactTerminal()
        frame = terminal.frame

        def capture():
            if terminal.frames == 2:
                terminal.draft = '/status'
            return frame()

        terminal.frame = capture
        code, result = self.compact(terminal)
        self.assertEqual(code, 2, result)
        self.assertEqual(result['reason'], 'input-changed-before-paste')
        self.assertEqual(terminal.actions, [])
        self.assertEqual(terminal.draft, '/status')

    def test_unselected_compact_still_uses_ordinary_receipt_and_route(self):
        for typed in (True, False):
            for harness in ('codex', 'claude'):
                with self.subTest(typed=typed, harness=harness):
                    terminal = Terminal(payload='/compact', dropped=1)
                    terminal.harness = harness
                    result = deliver(terminal, typed_command=typed)
                    self.assertEqual(result['receipt'], 'submitted')
                    self.assertNotIn('command_outcome', result)
                    input_action = 'typed:/compact' if typed else 'paste'
                    self.assertEqual(terminal.actions, [input_action, 'Enter', 'Enter'])


if __name__ == '__main__':
    if '--mutation-check' in sys.argv:
        typed_mutations()
    else:
        unittest.main()
