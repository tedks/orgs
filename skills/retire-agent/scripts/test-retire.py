#!/usr/bin/env python3
"""Behavioral tests; isolated tmux server, local bare private Git, no models/network."""
import json
import importlib.util
import os
from pathlib import Path
import re
import signal
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import tty
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import uuid

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
SHARED = Path(os.environ.get('RETIRE_TEST_SHARED_SCRIPTS', str(HERE.parents[1] / 'spawn-agent' / 'scripts')))


def shard_data(event, identity):
    return {'event': event, 'identity': identity, 'author': 'agent',
            'date': '2026-09-26', 'session_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'harness': identity['process']['agent'],
            'model': 'test-model', 'working_directory': identity['directory'], 'tmux_window': 'private-test:0',
            'role': 'Utility', 'landed_work': 'none', 'lessons': 'Record receipts before exit.', 'provenance': 'fixture-agent',
            'recovery': {'mission': 'Mission authorized', 'authorization': 'fixture caller', 'pauses': 'none',
                         'worktree': identity['directory'], 'branch': 'master', 'heads': 'fixture seed',
                         'tested_vs_merged': 'none', 'evidence': 'local records', 'limits': 'fixture only',
                         'failures': 'none', 'open_decisions': [], 'outstanding_sends': 'none', 'next_action': 'read artifacts'},
            'resources': []}


def process_token(pid):
    try:
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    if stat[0] == 'Z':
        return None
    # Other read/parse failures are not proof of process end. Cleanup retains
    # its directory on such an error because its finalizer is already detached.
    return {'pid': int(pid), 'start': stat[19],
            'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def register_fixture(directory, pid, role, argv0=None):
    if role == 'pane-root':
        try:
            if str(directory).encode() not in Path(f'/proc/{pid}/cmdline').read_bytes():
                return  # A reparented actor must not claim init or an unrelated parent.
        except OSError:
            return
    token = process_token(pid)
    if token:
        with (directory / 'owned-processes.jsonl').open('a') as ledger:
            ledger.write(json.dumps(dict(token, role=role, argv0=argv0)) + '\n')


def fixture_records(directory):
    ledger = directory / 'owned-processes.jsonl'
    if not ledger.exists():
        return []
    # Append writers may not have flushed the trailing newline yet. Re-read
    # later rather than treating an incomplete record as ownership authority.
    return [json.loads(line) for line in ledger.read_text().splitlines(keepends=True)
            if line.endswith('\n')]


def fixture_command(directory, inner):
    # The surviving shell also owns a fixture HOME, rather than the host's
    # interactive history/config paths after the actor exits.
    environment = {'RETIRE_TEST_PYTHON': sys.executable, 'HOME': str(directory / 'actor-home'),
                   'HISTFILE': str(directory / 'actor-home/history'),
                   'CODEX_HOME': str(directory / 'codex-config'),
                   'CLAUDE_CONFIG_DIR': str(directory / 'claude-config')}
    exports = ' '.join(key + '=' + shlex.quote(value) for key, value in environment.items())
    return 'export ' + exports + '; ' + shlex.join(['bash', '-c', inner]) + '; exec bash --norc'


def terminal(directory, mode):
    directory = Path(directory)
    register_fixture(directory, os.getpid(), 'terminal')
    register_fixture(directory, os.getppid(), 'pane-root')
    session = ('AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA' if mode == 'claude-uppercase'
               else 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    rollout = Path(os.environ['CODEX_HOME']) / 'sessions/rollout-fixture-' / ('rollout-' + session + '.jsonl')
    rollout.parent.mkdir(parents=True, exist_ok=True)
    if not rollout.exists():
        rollout.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': session, 'source': 'cli', 'cwd': os.getcwd()}}) + '\n')
    extra_fd = None
    if mode == 'ambiguous-native-fd':
        second = rollout.with_name('rollout-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.jsonl')
        second.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'source': 'cli', 'cwd': os.getcwd()}}) + '\n')
        extra_fd = second.open('a')
    native_fd = rollout.open('a')  # Provider reader requires a writable CLI rollout fd.
    if mode == 'missing-native-fd':
        native_fd.close()
    if mode.startswith('claude'):
        state_dir = Path(os.environ['HOME']) / '.claude/session-state'
        state_dir.mkdir(parents=True, exist_ok=True)
        start = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        (state_dir / ('current.' + str(os.getpid()))).write_text(session + ' ' + start + ' ' + boot + '\n')
    old = termios.tcgetattr(0)
    tty.setraw(0)
    draft = b'human unfinished draft' if mode in ('draft', 'stable-draft') else b''
    pending = b''
    pasting = False
    pasted_payload = False
    paste_prefix = b''
    pastes = enters = exit_enters = 0
    history = ''
    event = None
    due = None
    children = []
    typing_tick = 0
    def record_codex_completion(message, later_started=False):
        native_fd.write(json.dumps({'type': 'event_msg', 'payload': {
            'type': 'task_complete', 'turn_id': 'fixture-turn',
            'last_agent_message': message}}) + '\n')
        if later_started:
            native_fd.write(json.dumps({'type': 'event_msg', 'payload': {
                'type': 'task_started', 'turn_id': 'later-fixture-turn'}}) + '\n')
        native_fd.flush()
    if mode in ('node-core', 'extra-core', 'linger-core'):
        core = str(directory / '@openai/codex/node_modules/@openai/codex-linux-x64/vendor/test/bin/codex')
        names = (core,) if mode == 'linger-core' else (core, core if mode == 'extra-core' else 'node')
        for name in names:
            if mode == 'linger-core':
                body = 'import signal,time; signal.signal(signal.SIGHUP,signal.SIG_IGN); fd=open(' + repr(str(rollout)) + ',"a"); time.sleep(360)'
                command = 'exec -a ' + shlex.quote(name) + ' ' + shlex.join([os.environ['RETIRE_TEST_PYTHON'], '-c', body])
                children.append(subprocess.Popen(['bash', '-c', command], start_new_session=True))
                register_fixture(directory, children[-1].pid, 'linger-core', name)
            else:
                body = 'import time; fd=open(' + repr(str(rollout)) + ',"a"); time.sleep(360)'
                children.append(subprocess.Popen(['bash', '-c', 'exec -a ' + shlex.quote(name) + ' ' + shlex.join([os.environ['RETIRE_TEST_PYTHON'], '-c', body])]))
                register_fixture(directory, children[-1].pid, 'child', name)
    if mode == 'cleanup-writer':
        parent = process_token(os.getpid())
        body = ("import time\nfrom pathlib import Path\n"
                + "target=Path(" + repr(str(directory / 'late-writer')) + ")\n"
                + "def parent_live():\n"
                + " try:\n  fields=Path('/proc/" + str(parent['pid']) + "/stat').read_text().rsplit(')',1)[1].split()\n"
                + " except OSError: return False\n"
                + " return fields[0]!='Z' and fields[19]==" + repr(parent['start']) + "\n"
                + "def write(message):\n try: target.write_text(message)\n except FileNotFoundError: pass\n"
                + "while parent_live():\n write('owned fixture writer')\n time.sleep(.01)\n"
                + "deadline=time.monotonic()+.25\n"
                + "while time.monotonic()<deadline:\n write('owned fixture shutdown tail')\n time.sleep(.01)\n")
        children.append(subprocess.Popen([os.environ['RETIRE_TEST_PYTHON'], '-c', body], start_new_session=True))
        register_fixture(directory, children[-1].pid, 'writer')
    def draw():
        plain_draft = not pasted_payload
        collapsed = f'[Pasted Content {len(draft.decode(errors="replace"))} chars]' if draft and not plain_draft else draft.decode(errors='replace')
        if mode == 'stable-draft' and pasted_payload and paste_prefix:
            collapsed = paste_prefix.decode(errors='replace') + f"[Pasted Content {len(draft[len(paste_prefix):].decode(errors='replace'))} chars]"
        body = history + '\r\n› ' + collapsed + '\r\n\r\n  Test model · branch\r\n'
        if mode.startswith('claude'):
            if mode == 'claude-ghost' and event and not draft:
                collapsed = 'Try "summarize the work"'
            body = history + '\r\n' + '─' * 80 + '\r\n❯\u00a0' + collapsed + '\r\n' + '─' * 80 + '\r\n'
        visible_marker = mode in ('composer', 'claude-composer') and draft.startswith('● RETIRE-DONE-'.encode())
        if visible_marker:
            body = history + '\r\n› \r\n' + draft.decode(errors='replace') + '\r\n\r\n  Test model · branch\r\n'
            if mode == 'claude-composer':
                body = history + '\r\n' + '─' * 80 + '\r\n❯\u00a0\r\n' + draft.decode(errors='replace') + '\r\n' + '─' * 80 + '\r\n'
        if mode == 'modal':
            body = 'Do you trust the contents of this directory?\r\n  1. Yes\r\n  2. No\r\n'
        sys.stdout.write('\x1b[?2004h\x1b[2J\x1b[H' + body)
        row = history.count('\n') + (3 if mode.startswith('claude') else 2)
        if mode == 'claude-real-reply-row-status-late' and 'globalVersion:' in history and os.get_terminal_size().columns < 125:
            row += 1  # The synthetic status line occupies two display rows.
        if visible_marker:
            row += 1
        cursor = 3 if mode == 'claude-ghost' and event and not draft else 3 + len(collapsed)
        sys.stdout.write(f'\x1b[{row};{cursor}H')
        sys.stdout.flush()
        (directory / 'terminal.json').write_text(json.dumps({'pastes': pastes, 'enters': enters, 'event': event}))
    try:
        draw()
        while True:
            if mode == 'draft' and not (directory / 'human-cleared-draft').exists():
                # Active human input changes faster than the sender stability window.
                typing_tick += 1
                draft = b'human unfinished draft ' + str(typing_tick).encode()
                draw()
            if due is not None and time.monotonic() >= due:
                if mode in ('claude-real-reply-row-late', 'claude-real-reply-row-status-late'):
                    history += '● RETIRE-DONE-' + event + '\r\n✻ Baked for 37s · done 6:25 PM\r\n'
                    if mode == 'claude-real-reply-row-status-late':
                        history += '  globalVersion: 2.1.288 · latestVersion: 2.1.289 ✘ Auto-update failed: no write permission to npm prefix · Run claude doctor\r\n'
                elif mode == 'codex-real-reply-row-late':
                    history += '• RETIRE-DONE-' + event + '\r\n• Worked for 19s • 19:35\r\n'
                    record_codex_completion('RETIRE-DONE-' + event)
                else:
                    history += '● RETIRE-DONE-' + event + '\r\n'
                due = None
                draw()
            cleared = directory / 'human-cleared-history'
            if cleared.exists():
                history = '• Assistant output cleared.\r\n'
                cleared.unlink()
                draw()
            fresh_decline = directory / 'human-fresh-decline'
            if fresh_decline.exists():
                history = '● RETIRE-DECLINED-' + event + '\r\n'
                fresh_decline.unlink()
                draw()
            new_draft = directory / 'human-typed-draft'
            if new_draft.exists():
                draft = b'human new draft'
                new_draft.unlink()
                draw()
            if (directory / 'human-independent-exit').exists():
                if exit_enters:
                    sys.stdout.write('\r\n\x1b[JToken usage: total=42\r\nTo continue this session, run:\r\n  codex resume aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\r\n')
                    sys.stdout.flush()
                return
            if mode == 'draft' and (directory / 'human-cleared-draft').exists():
                draft = b''
                mode = 'done'
                draw()
            if not select.select([0], [], [], .01 if mode == 'draft' else .1)[0]:
                continue
            pending += os.read(0, 65536)
            while pending:
                if pending.startswith(b'\x1b[200~'):
                    pastes += 1
                    paste_prefix = draft
                    pasting = True
                    pasted_payload = True
                    pending = pending[6:]
                elif pending.startswith(b'\x1b[201~'):
                    pasting = False
                    pending = pending[6:]
                elif pending.startswith(b'\x1b') and len(pending) < 6:
                    break
                else:
                    char, pending = pending[:1], pending[1:]
                    if not pasting and char == b'\r':
                        enters += 1
                        payload = draft.decode(errors='replace')
                        if payload == '/exit':
                            exit_enters += 1
                            # Independently prove order from the remote, before exit.
                            remote = directory / 'remote.git'
                            receipt = subprocess.run(['git', '--git-dir', str(remote), 'show', 'master:receipts/' + event + '.json'], capture_output=True, text=True)
                            verified = False
                            if receipt.returncode == 0:
                                record = json.loads(receipt.stdout)
                                source = directory / 'repo' / '.git' / 'retirements' / (event + '.shard')
                                data = json.loads(source.read_text())
                                expected = 'waiting/' + data['date'] + '-' + data['session_id'][:12] + '-retire-' + event + '.md'
                                remote_hash = subprocess.run(['git', '--git-dir', str(remote), 'rev-parse', 'master:' + expected], capture_output=True, text=True)
                                verified_hash = subprocess.run(['git', '--git-dir', str(remote), 'rev-parse', record.get('commit', 'missing') + ':' + expected], capture_output=True, text=True)
                                recorded_blob = subprocess.run(['git', '--git-dir', str(remote), 'show', record.get('commit', 'missing') + ':' + expected], capture_output=True)
                                master_blob = subprocess.run(['git', '--git-dir', str(remote), 'show', 'master:' + expected], capture_output=True)
                                verified = (record.get('status') in ('handoff-verified', 'pending-exit') and record.get('event') == event
                                            and record.get('shard') == expected and remote_hash.returncode == 0
                                            and verified_hash.returncode == 0 and remote_hash.stdout == verified_hash.stdout
                                            and recorded_blob.returncode == 0 and master_blob.returncode == 0
                                            and recorded_blob.stdout == master_blob.stdout
                                            and json.loads(recorded_blob.stdout)['event'] == event
                                            and json.loads(recorded_blob.stdout)['identity'] == identity)
                            (directory / 'exit-order.json').write_text(json.dumps({'receipt_before_exit': verified}))
                            if mode.startswith('claude') and pasted_payload:
                                # Real regression: Claude treats pasted /exit as prose.
                                history = '❯ /exit\r\n● Pasted text is an ordinary message.\r\n'
                                draft = b''
                                pasted_payload = False
                                draw()
                                continue
                            if mode == 'hold-notice':
                                history = 'Token usage: total=42\r\nTo continue this session, run:\r\n  codex resume aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\r\n'
                                draft = b''
                                draw()
                            if mode not in ('hold', 'hold-notice'):
                                (directory / 'terminal.json').write_text(json.dumps({'pastes': pastes, 'enters': enters, 'event': event, 'exit_pasted': pasted_payload, 'exit_enters': exit_enters}))
                                if mode != 'no-exit-notice':
                                    session = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' if mode.endswith('wrong-exit-notice') else 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                                    notice = ('Resume this session with:\r\nclaude --resume ' if mode.startswith('claude') else ('Token usage: total=42 input=100000 (+ 90000 cached) output=10000 (reasoning 9000)\r\nTo continue this session, run:\r\n  codex resume ' if mode == 'narrow-notice' else 'Token usage: total=42\r\nTo continue this session, run:\r\n  codex resume ')) + session.lower() + '\r\n'
                                    sys.stdout.write('\r\n\x1b[J' + notice)
                                    sys.stdout.flush()
                                return
                        else:
                            match = re.search(r'Event ([0-9a-f]{32})\.', payload)
                            event = match[1]
                            if mode == 'initial-receipt':
                                result = subprocess.run(['git', '--git-dir', str(directory / 'remote.git'), 'show', 'master:receipts/' + event + '.json'], text=True, capture_output=True)
                                (directory / 'pre-offer-receipt.json').write_text(json.dumps({'verified': result.returncode == 0 and json.loads(result.stdout).get('event') == event}))
                            identity = json.JSONDecoder().raw_decode(payload.split(', identity ', 1)[1])[0]
                            shard = directory / 'repo' / '.git' / 'retirements' / (event + '.shard')
                            data = shard_data(event, identity)
                            if mode == 'claude-uppercase':
                                data['session_id'] = session
                            if mode == 'codex-real-reply-row-invalid-shard':
                                data['session_id'] = 'unknown'
                            if mode.endswith('wrong-shard-id'):
                                data['session_id'] = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
                            if mode == 'claude-switched-wrong-shard-id':
                                pointer = Path(os.environ['HOME']) / '.claude/session-state' / ('current.' + str(os.getpid()))
                                fields = pointer.read_text().split()
                                pointer.write_text(data['session_id'] + ' ' + ' '.join(fields[1:]) + '\n')
                            if mode != 'waiting-bad':
                                data['waiting'] = {'decision': 'Choose scope', 'owner': 'Operator'}
                            if mode == 'resource':
                                data['resources'] = [{'name': 'lease', 'status': 'pending'}]
                            if mode == 'path':
                                target = directory / 'outside.json'
                                target.write_text(json.dumps(data))
                                shard.symlink_to(target)
                            elif mode not in ('decline', 'ambiguous-decline'):
                                shard.write_text(json.dumps(data))
                            if mode == 'push-reject':
                                hook = directory / 'remote.git' / 'hooks' / 'pre-receive'
                                hook.write_text('#!/bin/sh\nexit 1\n')
                                hook.chmod(0o700)
                            if mode == 'commit-reject':
                                hook = directory / 'repo' / '.git' / 'hooks' / 'pre-commit'
                                hook.write_text('#!/bin/sh\nexit 1\n')
                                hook.chmod(0o700)
                        history = ('❯' if mode.startswith('claude') else '›') + ' [Pasted Content ' + str(len(payload)) + ' chars]\r\n'
                        if mode == 'stable-draft' and paste_prefix:
                            history = '› ' + paste_prefix.decode(errors='replace') + '[Pasted Content ' + str(len(payload) - len(paste_prefix.decode(errors='replace'))) + ' chars]\r\n'
                        if mode.startswith('claude'):
                            history = '• Messages to be submitted after next tool call\r\n  ↳ [Pasted Content ' + str(len(payload)) + ' chars]\r\n'
                        if mode.startswith('ambiguous'):
                            history = 'Assistant continues without acceptance evidence.\r\n'
                            if mode != 'ambiguous':
                                marker_event = '0' * 32 if mode == 'ambiguous-done-wrong' else event
                                disposition = 'DECLINED' if mode == 'ambiguous-decline' else 'DONE'
                                history += '● RETIRE-' + disposition + '-' + marker_event + '\r\n'
                                if mode == 'ambiguous-done-suffix':
                                    history += '  Shard still needs correction.\r\n'
                                if mode == 'ambiguous-done-background':
                                    history += '  Worked for 2m 4s · 11:47\r\n'
                                    history += '1 background terminal running · /ps to view · /stop to close\r\n'
                                if mode == 'ambiguous-done-time':
                                    history += '  11:46\r\n'
                        else:
                            history += '• Accepted\r\n'
                            if payload != '/exit' and mode not in ('composer', 'claude-composer'):
                                disposition = 'DECLINED' if mode.startswith('decline') else 'DONE'
                                if mode == 'quoted':
                                    history += 'RETIRE-DONE-' + event + '\r\n'
                                elif mode == 'old':
                                    history += '● RETIRE-DONE-' + ('0' * 32) + '\r\n'
                                elif mode == 'prose-marker':
                                    history += '● Shard written.\r\n  RETIRE-DONE-' + event + '\r\n'
                                elif mode == 'late-done':
                                    due = time.monotonic() + .2
                                elif mode in ('claude-real-reply-row-late', 'claude-real-reply-row-status-late', 'codex-real-reply-row-late'):
                                    due = time.monotonic() + 1
                                else:
                                    reply_bullet = '•' if mode in ('codex-real-reply-row', 'codex-real-reply-row-invalid-shard', 'decline-codex-real-reply-row', 'codex-spoofed-footer-reply',
                                                                   'codex-bullet-footer-later-turn',
                                                                   'codex-bullet-footer-malformed-rollout') else '●'
                                    history += reply_bullet + ' RETIRE-' + disposition + '-' + event + '\r\n'
                                    if mode in ('claude-real-reply-row', 'claude-real-reply-row-status'):
                                        history += '✻ Baked for 37s · done 6:25 PM\r\n'
                                        if mode == 'claude-real-reply-row-status':
                                            history += '  globalVersion: 2.1.288 · latestVersion: 2.1.289 ✘ Auto-update failed: no write permission to npm prefix · Run claude doctor\r\n'
                                    if mode in ('codex-real-reply-row', 'codex-real-reply-row-invalid-shard', 'decline-codex-real-reply-row', 'codex-spoofed-footer-reply',
                                                'codex-bullet-footer-later-turn',
                                                'codex-bullet-footer-malformed-rollout'):
                                        history += '• Worked for 19s • 19:35\r\n'
                                        record_codex_completion(
                                            'Worked for 19s • 19:35' if mode == 'codex-spoofed-footer-reply'
                                            else 'RETIRE-' + disposition + '-' + event,
                                            later_started=(mode == 'codex-bullet-footer-later-turn'))
                                        if mode == 'codex-bullet-footer-malformed-rollout':
                                            native_fd.write('{')
                                            native_fd.flush()
                                    if mode == 'padded-marker':
                                        history = history[:-2] + '   \t\r\n'
                                    if 'codex-footer' in mode:
                                        footer = '  Worked for 1m 21s · 12:23'
                                        if 'hours' in mode:
                                            footer = '  Worked for 1h 8m 53s · 02:26'
                                        elif 'time-only' in mode:
                                            footer = '  02:55'
                                        elif 'bullet' in mode:
                                            footer = '  Worked for 19s • 19:35'
                                        history += footer + '\r\n'
                                        if mode.endswith('padded-footer'):
                                            history = history[:-2] + '   \t\r\n'
                                        if mode.endswith('extra-prose'):
                                            history += '  Recovery still needs correction.\r\n'
                                        elif mode.endswith('same-row-prose'):
                                            history = history[:-2] + ' Recovery still needs correction.\r\n'
                                    if 'claude-footer' in mode:
                                        timing = '✻ Baked for 19s · done 1:27 PM'
                                        if mode.endswith('minute'):
                                            timing = '✻ Sautéed for 1m 0s · done 12:27 AM'
                                        if mode.endswith('same-row-prose'):
                                            timing += ' Recovery still needs correction.'
                                        elif mode.endswith('unknown-verb'):
                                            timing = timing.replace('Baked', 'Invented')
                                        tokens = '50713 tokens'
                                        if mode.endswith('token-partial'):
                                            tokens = '50713 token'
                                        history += timing + '\r\n' + ' ' * 200 + tokens + '\r\n'
                                        if mode.endswith('extra-prose'):
                                            history += '  Recovery still needs correction.\r\n'
                                    if mode.endswith('suffix'):
                                        history += '  Do not retire yet; recovery still needs correction.\r\n'
                                    elif mode.endswith('later-assistant'):
                                        history += '● Recovery still needs correction.\r\n'
                        draft = ('● RETIRE-DONE-' + event).encode() if mode in ('composer', 'claude-composer') else (b'ordinary human draft' if mode in ('claude-exit-draft', 'codex-exit-draft') else b'')
                        pasted_payload = False
                    elif not pasting and char == b'\x15':
                        draft = b''
                        pasted_payload = False
                    else:
                        draft += char
            # Buffer a bracketed paste as one composer update, rather than
            # redrawing a changing collapsed-paste count for every byte. Typed
            # input still redraws after each available input chunk.
            if not pasting:
                draw()
    finally:
        for child in children:
            if mode not in ('linger-core', 'cleanup-writer'):
                child.terminate()
                child.wait()
        native_fd.close()
        if extra_fd:
            extra_fd.close()
        termios.tcsetattr(0, termios.TCSADRAIN, old)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        (self.directory / 'actor-home').mkdir()
        # The uniquely owned server and any extra default-shell panes inherit
        # fixture history/config paths, even without fixture_command.
        self.server_env = dict(os.environ, HOME=str(self.directory / 'actor-home'),
                               HISTFILE=str(self.directory / 'actor-home/history'))
        self.label = 'retire-test-' + uuid.uuid4().hex
        self.tmux = ['tmux', '-L', self.label]
        self.repo = self.directory / 'repo'
        self.command('git', 'init', '--bare', str(self.directory / 'remote.git'))
        self.command('git', 'init', '-b', 'master', str(self.repo))
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.repo / 'seed').write_text('private test\n')
        self.git('add', 'seed')
        self.git('commit', '-m', 'seed')
        self.git('remote', 'add', 'origin', str(self.directory / 'remote.git'))
        self.git('push', '-u', 'origin', 'master')
        shared = self.directory / 'shared' / 'scripts'
        shared.mkdir(parents=True)
        # Timing-only wrapper; real shared sender, real terminal, no transport stubs.
        sender = shared / 'tmux-message.sh'
        sender.write_text('#!/usr/bin/env bash\nphase=$1; pane=$2; shift 2\nexec ' + shlex.quote(str(SHARED / 'tmux-message.sh')) + ' "$phase" "$pane" "$@" --stable-wait .05 --max-wait .6 --submit-delay .05 --render-wait .5 --receipt-wait .5 --retry-wait .05 --poll-interval .02\n')
        # Options after --prompt-file are accepted by argparse in shared sender.
        sender.chmod(0o700)
        (shared / 'tmux-message.py').symlink_to(SHARED / 'tmux-message.py')
        spawn = shared / 'agent-spawn.sh'
        spawn.write_text('#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\nargs=sys.argv[1:]\nbrief=Path(args[args.index("--prompt-file")+1]).read_text()\nPath(' + repr(str(self.directory / 'spawn.json')) + ').write_text(json.dumps({"args":args,"brief":brief}))\n')
        spawn.chmod(0o700)
        checker = self.directory / 'private-check'
        checker.write_text('#!/bin/sh\n[ "$1" = ' + shlex.quote(str(self.directory / 'remote.git')) + ' ]\n')
        checker.chmod(0o700)
        self.roles = self.directory / 'ROLES.md'
        self.roles.write_text('Common to every hat: first record before action.\n')
        config = self.directory / 'config.toml'
        config.write_text('')
        self.env = dict(os.environ, AGENT_SKILLS_CONFIG=str(config), SPAWN_TMUX_LABEL=self.label, RETIRE_REPO=str(self.repo), RETIRE_PRIVATE_CHECK=str(checker), RETIRE_SPAWN_SKILL=str(shared.parent), RETIRE_TEST_PYTHON=sys.executable)
        self.env.pop('SPAWN_TMUX_SOCKET', None)
        self.env.pop('TMUX', None)

    def tearDown(self):
        self.release_fixture()

    def release_fixture(self):
        if getattr(self, 'fixture_release_attempted', False):
            return  # Never retry deletion after a retained release diagnostic.
        self.fixture_release_attempted = True
        # CPython TemporaryDirectory's private finalizer is detached so an
        # exception cannot later delete files beneath a still-writing actor.
        # cleanup() still explicitly removes the directory on Python 3.11+.
        self.temp._finalizer.detach()
        owned = {}
        signaled = set()
        def refresh_owned():
            for record in fixture_records(self.directory):
                key = tuple(record[field] for field in ('pid', 'start', 'boot', 'role'))
                owned[key] = record
                token = {field: record[field] for field in ('pid', 'start', 'boot')}
                if key not in signaled and record['role'] == 'linger-core' and process_token(record['pid']) == token:
                    try:
                        argv0 = Path(f"/proc/{record['pid']}/cmdline").read_bytes().split(b'\0')[0].decode()
                        if argv0 == record['argv0'] and argv0.startswith(str(self.directory / '@openai/codex/')):
                            os.kill(record['pid'], signal.SIGTERM)  # Original deliberate owned-core release only.
                            signaled.add(key)
                    except (ProcessLookupError, FileNotFoundError):
                        pass
        refresh_owned()
        subprocess.run(self.tmux + ['kill-server'], capture_output=True)
        deadline = time.monotonic() + 4
        while True:
            refresh_owned()  # Include actors enrolled during server shutdown.
            live = [record for record in owned.values() if process_token(record['pid']) ==
                    {key: record[key] for key in ('pid', 'start', 'boot')}]
            if not live:
                break
            if time.monotonic() >= deadline:
                diagnostic = self.directory / 'cleanup-pending.json'
                diagnostic.write_text(json.dumps({'retained': str(self.directory), 'owned_live': live,
                                                  'reason': 'owned processes still live after server release'}, indent=2) + '\n')
                self.fail('owned fixture cleanup pending; retained ' + str(diagnostic))
            time.sleep(.02)
        self.temp.cleanup()
        self.fixture_released = True

    def command(self, *args):
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, env=self.server_env).strip()

    def git(self, *args):
        return self.command('git', '-C', str(self.repo), *args)

    def actor(self, mode='done', node=False, relative=False):
        (self.directory / 'terminal.json').unlink(missing_ok=True)
        fixture = Path(__file__).resolve()
        if node:
            fixture = self.directory / '@openai' / 'codex' / 'bin' / 'codex.js'
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes(Path(__file__).read_bytes())
            link = self.directory / 'codex'
            link.symlink_to(fixture)
            fixture = link
            if relative:
                fixture = Path('codex')
        command = shlex.join([sys.executable, str(fixture), '--terminal', str(self.directory), mode])
        # argv[0] is the harness identity; outer shell survives process exit.
        inner = 'exec -a ' + ('node' if node else ('claude' if mode.startswith('claude') else 'codex')) + ' ' + command
        outer = fixture_command(self.directory, inner)
        options = ['-c', str(self.directory)] if relative else []
        pane = self.command(*self.tmux, 'new-session', '-d', '-P', '-F', '#{pane_id}', '-x', '240', '-y', '40', *options, outer)
        self.pane = pane
        self.wait_for(lambda: (self.directory / 'terminal.json').exists())
        return pane

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)

    def invoke(self, *args):
        return subprocess.run([os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh')), self.pane, '--wait', '.4', '--poll', '.02', *args], env=self.env, text=True, capture_output=True, timeout=12)

    def state(self):
        paths = list((self.repo / '.git' / 'retirements').glob('*.json'))
        self.assertEqual(len(paths), 1)
        return paths[0], json.loads(paths[0].read_text())

    def staged(self, state, relative):
        return self.repo / '.git' / 'retirements' / (state['id'] + '.publication') / relative

    def remote_editor(self):
        editor = self.directory / 'remote-editor'
        if not editor.exists():
            self.command('git', 'clone', str(self.directory / 'remote.git'), str(editor))
            self.command('git', '-C', str(editor), 'config', 'user.email', 'test@example.invalid')
            self.command('git', '-C', str(editor), 'config', 'user.name', 'Test')
        else:
            self.command('git', '-C', str(editor), 'pull', '--ff-only')
        return editor

    def editor_git(self, editor, *args):
        return self.command('git', '-C', str(editor), *args)

    def observed(self):
        return json.loads((self.directory / 'terminal.json').read_text())

    def source(self):
        entry = Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh')))
        return entry.with_name('retire.py').read_text()

    def instrument(self, before, after):
        stage = self.directory / ('instrumented-' + uuid.uuid4().hex)
        stage.mkdir()
        stage = stage / 'skills/retire-agent/scripts'
        stage.mkdir(parents=True)
        shutil.copytree(HERE.parents[1] / '_shared', stage.parents[1] / '_shared')
        source = self.source()
        if before not in source:
            self.fail('INVALID-INSTRUMENTATION: missing stable anchor')
        (stage / 'retire.py').write_text(source.replace(before, after, 1))
        shutil.copy2(HERE / 'build-index.py', stage / 'build-index.py')
        entry = stage / 'retire.sh'
        entry.write_bytes((HERE / 'retire.sh').read_bytes())
        entry.chmod(0o700)
        return entry

    def test_process_end_during_stat_read_is_ended(self):
        with patch.object(Path, 'read_text', side_effect=ProcessLookupError):
            self.assertIsNone(process_token(os.getpid()))

    def test_fixture_ledger_waits_for_complete_record(self):
        ledger = self.directory / 'owned-processes.jsonl'
        record = {'pid': os.getpid(), 'start': 'fixture', 'boot': 'fixture', 'role': 'writer'}
        ledger.write_text(json.dumps(record))
        self.assertEqual(fixture_records(self.directory), [])
        with ledger.open('a') as handle:
            handle.write('\n')
        self.assertEqual(fixture_records(self.directory), [record])
        ledger.unlink()  # This simulated record never enrolled a real actor.

    def test_failed_release_preserves_diagnostic_on_second_call(self):
        record = dict(process_token(os.getpid()), role='writer', argv0=None)
        (self.directory / 'owned-processes.jsonl').write_text(json.dumps(record) + '\n')
        with patch('time.monotonic', side_effect=[0, 5]):
            with self.assertRaises(self.failureException):
                self.release_fixture()
        diagnostic = self.directory / 'cleanup-pending.json'
        original = diagnostic.read_bytes()
        self.release_fixture()
        self.assertEqual(diagnostic.read_bytes(), original)
        # Only the test's own live controller was simulated; no actor/server
        # exists, so explicitly remove this owned negative-test directory.
        self.temp.cleanup()

    def test_cleanup_waits_for_owned_shutdown_writer(self):
        self.actor('cleanup-writer')
        self.wait_for(lambda: (self.directory / 'late-writer').exists())
        self.wait_for(lambda: any(record['role'] == 'writer' for record in fixture_records(self.directory)))
        writer = next(record for record in fixture_records(self.directory) if record['role'] == 'writer')
        self.assertIsNotNone(process_token(writer['pid']))
        directory = self.directory
        read_records = fixture_records
        reads = 0
        def late_enrollment(path):
            nonlocal reads
            reads += 1
            records = read_records(path)
            return [record for record in records if record['role'] != 'writer'] if reads == 1 else records
        with patch(__name__ + '.fixture_records', side_effect=late_enrollment):
            self.release_fixture()
        self.assertGreaterEqual(reads, 2)
        self.assertFalse(directory.exists())
        current = process_token(writer['pid'])
        self.assertNotEqual(current, {key: writer[key] for key in ('pid', 'start', 'boot')})

    def test_foreign_private_json_does_not_block_new_retirement(self):
        self.actor()
        directory = self.repo / '.git' / 'retirements'
        directory.mkdir(mode=0o700)
        foreign = {
            'lane-v-private-publication.json': '{"blob":"foreign","private_remote":true}',
            'lane-w-receipt.json': '{"status":"verified","path":"waiting/other.md"}',
            'unknown.json': '{not even valid JSON',
        }
        for name, content in foreign.items():
            (directory / name).write_text(content)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)
        for name, content in foreign.items():
            self.assertEqual((directory / name).read_text(), content)
        self.assertEqual(len(list(directory.glob('*-offer.txt'))), 1)

    def test_wrapper_preserves_pending_and_usage_failure_status(self):
        self.actor('modal')
        pending = self.invoke()
        self.assertEqual(pending.returncode, 2, pending.stderr)
        self.assertEqual(json.loads(pending.stderr)['status'], 'pending')
        usage = self.invoke('--wait', '1801')
        self.assertEqual(usage.returncode, 2, usage.stderr)
        self.assertIn('wait in (0,1800]', usage.stderr)
        self.assertNotIn('Traceback', usage.stderr)
        missing_pane = subprocess.run(
            [os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh')),
             '--resume', '/no/such/state'], env=self.env, text=True,
            capture_output=True, timeout=12)
        self.assertEqual(missing_pane.returncode, 2, missing_pane.stderr)
        self.assertIn('the following arguments are required: pane', missing_pane.stderr)

    def test_claude_real_reply_row_with_valid_shard(self):
        self.actor('claude-real-reply-row')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_codex_real_reply_row_with_valid_shard(self):
        self.actor('codex-real-reply-row')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_claude_reply_row_with_native_status_suffix(self):
        self.actor('claude-real-reply-row-status')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_claude_reply_row_with_wrapped_native_status(self):
        self.actor('claude-real-reply-row-status-late')
        first = self.invoke('--wait', '.05')
        self.assertEqual(first.returncode, 2, first.stderr)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'delivered')
        self.command(*self.tmux, 'resize-window', '-t', self.pane, '-x', '80')
        result = self.invoke('--resume', str(path), '--wait', '3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_claude_reply_row_with_space_at_wrap(self):
        self.actor('claude-real-reply-row-status-late')
        first = self.invoke('--wait', '.05')
        self.assertEqual(first.returncode, 2, first.stderr)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'delivered')
        self.command(*self.tmux, 'resize-window', '-t', self.pane, '-x', '92')
        result = self.invoke('--resume', str(path), '--wait', '3')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_declined_reply_row_with_bullet_footer(self):
        self.actor('decline-codex-real-reply-row')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        path, state = self.state()
        self.assertEqual(state['disposition'], 'DECLINED')
        shard = path.with_suffix('.shard')
        data = shard_data(state['id'], state['identity'])
        data.update(author='caller', declined=True, provenance='caller after native declined reply')
        shard.write_text(json.dumps(data))
        resumed = self.invoke('--resume', str(path), '--caller-shard')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)

    def test_codex_footer_shaped_later_reply_stays_pending(self):
        self.assert_completion_block_pending('codex-spoofed-footer-reply')

    def test_codex_new_turn_after_footer_stays_pending(self):
        self.assert_completion_block_pending('codex-bullet-footer-later-turn')

    def test_codex_partial_rollout_after_footer_stays_pending(self):
        self.assert_completion_block_pending('codex-bullet-footer-malformed-rollout')

    def test_codex_cached_footer_witness_rechecked_before_publication(self):
        self.actor('codex-real-reply-row-invalid-shard')
        first = self.invoke()
        self.assertEqual(first.returncode, 2, first.stderr)
        self.assertIn('agent must establish its own session identity', first.stderr)
        path, state = self.state()
        self.assertEqual(state['disposition'], 'DONE')
        self.assertTrue(state['native_marker_witness'])
        shard = path.with_suffix('.shard')
        data = json.loads(shard.read_text())
        data['session_id'] = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        shard.write_text(json.dumps(data))
        rollout = self.directory / 'codex-config/sessions/rollout-fixture-/rollout-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl'
        with rollout.open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'later-turn'}}) + '\n')
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native final marker no longer current before handoff publication', result.stderr)
        self.assertNotIn('handoff_receipt', self.state()[1])
        self.assertFalse((self.repo / 'waiting').exists())

    def test_codex_footer_witness_rechecked_before_exit(self):
        self.actor('codex-real-reply-row')
        before = "            self.verify_native_session(session_id)\n"
        after = ("            self.verify_native_session(session_id)\n"
                 "            with open(self.native_binding()['observation']['rollout_path'], 'a') as stream:\n"
                 "                stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'later-turn'}}) + '\\n')\n")
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('handoff verified; native final marker no longer current', result.stderr)
        self.assertTrue(self.state()[1].get('handoff_receipt'))
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_claude_real_reply_row_on_resume(self):
        self.actor('claude-real-reply-row-late')
        first = self.invoke('--wait', '.05')
        self.assertEqual(first.returncode, 2, first.stderr)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'delivered')
        result = self.invoke('--resume', str(path), '--wait', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_codex_real_reply_row_on_resume(self):
        self.actor('codex-real-reply-row-late')
        first = self.invoke('--wait', '.05')
        self.assertEqual(first.returncode, 2, first.stderr)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'delivered')
        result = self.invoke('--resume', str(path), '--wait', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_reply_row_cannot_publish_invalid_shard_on_resume(self):
        self.actor('claude-real-reply-row-late')
        self.assertEqual(self.invoke('--wait', '.05').returncode, 2)
        path, _ = self.state()
        shard = path.with_suffix('.shard')
        original = shard.read_bytes()
        data = json.loads(original)
        data['session_id'] = 'unknown'
        shard.write_text(json.dumps(data))
        bad = self.invoke('--resume', str(path), '--wait', '2')
        self.assertEqual(bad.returncode, 2, bad.stderr)
        self.assertIn('agent must establish its own session identity', bad.stderr)
        self.assertNotIn('handoff_receipt', self.state()[1])
        shard.write_bytes(original)
        good = self.invoke('--resume', str(path), '--wait', '2')
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_wait_zero_rejected_and_maximum_accepted(self):
        self.actor()
        self.assertEqual(self.invoke('--wait', '0').returncode, 2)
        result = self.invoke('--wait', '1800')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_twenty_minute_wait_is_accepted(self):
        self.actor()
        result = self.invoke('--wait', '1200')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_retire_exit_to_shell_and_path_only_commit(self):
        self.actor()
        (self.repo / 'unrelated').write_text('preserve staged content')
        self.git('add', 'unrelated')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads((self.directory / 'exit-order.json').read_text())['receipt_before_exit'])
        self.assertIn('bash', self.command(*self.tmux, 'list-panes', '-a', '-F', '#{pane_current_command}'))
        self.assertIn('A  unrelated', self.git('status', '--short'))
        self.assertNotIn('unrelated', self.git('ls-tree', '-r', '--name-only', 'origin/master'))
        path, state = self.state()
        ledger = [json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
        actions = [record['action'] for record in ledger]
        self.assertLess(actions.index('handoff-receipt'), actions.index('original-exit-confirmed'))
        exit_send = next(i for i, record in enumerate(ledger) if record['action'] == 'send-attempt' and record.get('phase') == 'exit')
        self.assertLess(actions.index('handoff-receipt'), exit_send)
        self.assertTrue(any(record.get('receipt_type') == 'submitted' for record in ledger))
        self.assertFalse(any('payload' in record for record in ledger))
        index = self.git('show', 'origin/master:waiting/INDEX.md')
        self.assertIn('Session | Provider | Role | State | Last verified', index)
        self.assertIn('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa | OpenAI | Utility | retired', index)
        self.assertFalse((self.repo / 'waiting').exists())
        self.assertFalse((self.repo / 'receipts').exists())

    def test_drifted_shared_checkout_cannot_trap_shard_or_receipt(self):
        self.actor()
        (self.repo / 'local-stray').write_text('local commit\n')
        self.git('add', 'local-stray')
        self.git('commit', '-m', 'unrelated local commit')
        (self.repo / 'seed').write_text('dirty shared file\n')
        (self.repo / 'receipts').mkdir()
        (self.repo / 'receipts' / 'unrelated.json').write_text('{"status":"local"}\n')
        head = self.git('rev-parse', 'HEAD')
        before = self.git('status', '--porcelain=v1')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.git('status', '--porcelain=v1'), before)
        self.assertFalse((self.repo / 'waiting').exists())
        path, state = self.state()
        self.assertEqual(self.git('show', 'origin/master:' + state['shard']), path.with_suffix('.publication').joinpath(state['shard']).read_text().strip())
        self.assertEqual(json.loads(self.git('show', 'origin/master:' + state['handoff_receipt']))['status'], 'retired')

    def test_stable_ordinary_offer_draft_is_co_submitted(self):
        self.actor('stable-draft')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)  # combined offer; typed Codex exit
        self.assertEqual(self.state()[1]['offer']['stale_draft_length'], len('human unfinished draft'))
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_claude_stable_ordinary_draft_defers_literal_exit(self):
        self.actor('claude-exit-draft')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('exit deferred before submission', result.stderr)
        state = self.state()[1]
        self.assertEqual(state['exit']['status'], 'deferred')
        self.assertFalse(state['exit']['input_attempted'])
        self.assertEqual(state['exit']['input_method'], 'typed')
        self.assertEqual(state['exit']['enters'], 0)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertFalse((self.directory / 'exit-order.json').exists())
        self.assertIn('ordinary human draft', self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        self.assertTrue(state.get('handoff_receipt'))
        self.assertEqual(self.git('rev-parse', 'origin/master:' + state['shard']), state['shard_hash'])

    def test_codex_stable_ordinary_draft_defers_typed_exit(self):
        self.actor('codex-exit-draft')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        state = self.state()[1]
        self.assertEqual(state['exit']['status'], 'deferred')
        self.assertFalse(state['exit']['input_attempted'])
        self.assertEqual(state['exit']['input_method'], 'typed')
        self.assertEqual(state['exit']['enters'], 0)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertIn('ordinary human draft', self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        self.assertFalse((self.directory / 'exit-order.json').exists())
        self.assertEqual(self.git('rev-parse', 'origin/master:' + state['shard']), state['shard_hash'])

    def test_native_reader_failure_is_pending_without_exit(self):
        self.actor()
        entry = self.instrument("            proof = observe_native_session(process['agent'], pin)", "            raise RuntimeError('fixture reader unavailable')")
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding reader failed for pinned PID', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('offer', self.state()[1])
        self.assertNotIn('exit', self.state()[1])

    def test_codex_offer_supplies_verified_id_and_resources(self):
        self.actor('resource')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        state = self.state()[1]
        payload = Path(state['offer']['payload']).read_text()
        self.assertEqual(state['native_session_id'], 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.assertIn('controller verified native session ID ' + state['native_session_id'], payload)
        self.assertIn('write ' + str(Path(state['offer']['payload']).with_name(state['id'] + '.shard')), payload)
        self.assertNotIn('Use exactly python3', payload)
        self.assertIn('Retain handles for any running exec calls', payload)
        self.assertIn('parent shell ending does not prove its descendants ended', payload)

    def test_missing_codex_reader_blocks_before_offer(self):
        self.actor()
        entry = self.instrument("        process = self.state['identity']['process']", "        process = self.state['identity']['process']")
        (entry.resolve().parents[2] / '_shared/native/codex_status.py').unlink()
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding reader unavailable', result.stderr)
        self.assertNotIn('offer', self.state()[1])

    def test_missing_shared_binding_blocks_before_offer(self):
        self.actor()
        entry = self.instrument("        process = self.state['identity']['process']", "        process = self.state['identity']['process']")
        (entry.resolve().parents[2] / '_shared/native/session_binding.py').unlink()
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding reader unavailable', result.stderr)
        self.assertNotIn('offer', self.state()[1])

    def test_offer_rechecks_binding_before_sender_input(self):
        self.actor('claude')
        before = "        attempt = self.state.get(phase)"
        after = ('        if phase == "offer":\n'
                 '            pointer = self.repo.parent / "actor-home/.claude/session-state" / ("current." + str(self.state["identity"]["process"]["pid"]))\n'
                 '            fields = pointer.read_text().split()\n'
                 '            pointer.write_text("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb " + " ".join(fields[1:]) + "\\n")\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding differs', result.stderr)
        self.assertNotIn('offer', self.state()[1])
        self.assertEqual(self.observed()['pastes'], 0)

    def test_wrong_native_session_shard_never_requests_exit(self):
        self.actor('wrong-shard-id')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding differs', result.stderr)
        state = self.state()[1]
        self.assertTrue(state.get('handoff_receipt'))
        self.assertNotIn('exit', state)
        self.assertNotIn('exit_notice', state)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def assert_native_fd_pending(self, mode):
        self.actor(mode)
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('pinned Codex native session binding unavailable', result.stderr)
        self.assertNotIn('offer', self.state()[1])
        self.assertNotIn('exit', self.state()[1])
        self.assertEqual(self.observed()['pastes'], 0)

    def test_codex_missing_native_fd_never_requests_exit(self):
        self.assert_native_fd_pending('missing-native-fd')

    def test_codex_ambiguous_native_fd_never_requests_exit(self):
        self.assert_native_fd_pending('ambiguous-native-fd')

    def test_claude_missing_pointer_never_requests_exit(self):
        self.actor('claude')
        next((self.directory / 'actor-home/.claude/session-state').glob('current.*')).unlink()
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('pinned Claude native session binding unavailable', result.stderr)
        self.assertNotIn('exit', self.state()[1])

    def test_claude_conflicting_present_pointers_never_request_exit(self):
        self.actor('claude')
        pointer = next((self.directory / 'actor-home/.claude/session-state').glob('current.*'))
        configured = self.directory / 'claude-config/session-state' / pointer.name
        configured.parent.mkdir(parents=True)
        fields = pointer.read_text().split()
        configured.write_text('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb ' + ' '.join(fields[1:]) + '\n')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('pinned Claude native session binding unavailable', result.stderr)
        self.assertNotIn('exit', self.state()[1])
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_send_rechecks_binding_after_notice_baseline(self):
        self.actor('claude')
        before = "        if phase == 'exit':\n            preserved = object_record"
        after = ('        if phase == "exit":\n'
                 '            pointer = self.repo.parent / "actor-home/.claude/session-state" / ("current." + str(self.state["identity"]["process"]["pid"]))\n'
                 '            fields = pointer.read_text().split()\n'
                 '            pointer.write_text("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb " + " ".join(fields[1:]) + "\\n")\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding differs', result.stderr)
        state = self.state()[1]
        self.assertIn('exit_notice', state)
        self.assertNotIn('exit', state)
        self.assertEqual(self.observed()['enters'], 1)  # offer only
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_changed_binding_retry_never_requests_exit(self):
        self.actor('claude-exit-draft')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(state['exit']['status'], 'deferred')
        pointer = next((self.directory / 'actor-home/.claude/session-state').glob('current.*'))
        fields = pointer.read_text().split()
        pointer.write_text('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb ' + ' '.join(fields[1:]) + '\n')
        self.command(*self.tmux, 'send-keys', '-t', self.pane, 'C-u')
        result = self.invoke('--resume', str(path), '--retry-deferred', 'exit')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding differs', result.stderr)
        self.assertEqual(self.observed()['enters'], 1)
        self.assertFalse((self.directory / 'exit-order.json').exists())
        self.assertNotEqual(self.state()[1]['status'], 'retired')

    def test_claude_stale_process_pointer_never_requests_exit(self):
        self.actor('claude')
        pointer = next((self.directory / 'actor-home/.claude/session-state').glob('current.*'))
        fields = pointer.read_text().split()
        pointer.write_text(fields[0] + ' 0 ' + fields[2] + '\n')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('pinned Claude native session binding unavailable', result.stderr)
        self.assertNotIn('exit', self.state()[1])
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_claude_wrong_native_session_shard_never_requests_exit(self):
        self.actor('claude-wrong-shard-id')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding differs', result.stderr)
        self.assertNotIn('exit', self.state()[1])
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_uppercase_claude_pointer_matches_native_notice(self):
        self.actor('claude-uppercase')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.state()[1]
        self.assertEqual(state['native_session_id'], 'AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA')
        self.assertEqual(state['status'], 'retired')
        self.assertTrue(json.loads((self.directory / 'exit-order.json').read_text())['receipt_before_exit'])

    def test_switched_native_session_cannot_replace_offered_id(self):
        self.actor('claude-switched-wrong-shard-id')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('shard differs from offered native session ID', result.stderr)
        state = self.state()[1]
        self.assertEqual(state['native_session_id'], 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.assertTrue(state.get('handoff_receipt'))
        self.assertNotIn('exit', state)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_narrow_pane_joined_native_exit_notice(self):
        self.actor('narrow-notice')
        self.command(*self.tmux, 'resize-window', '-t', self.pane, '-x', '60')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()[1]['status'], 'retired')

    def test_retry_deferred_exit_requires_current_pair(self):
        self.actor('codex-exit-draft')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(state['exit']['status'], 'deferred')
        self.command(*self.tmux, 'send-keys', '-t', self.pane, 'C-u')
        result = self.invoke('--resume', str(path), '--retry-deferred', 'exit')
        self.assertEqual(result.returncode, 0, result.stderr)
        current = self.state()[1]
        self.assertEqual(current['status'], 'retired')
        self.assertGreaterEqual(current['exit']['enters'], 1)
        self.assertTrue(json.loads((self.directory / 'exit-order.json').read_text())['receipt_before_exit'])

    def test_wrong_session_exit_notice_is_pending(self):
        self.actor('wrong-exit-notice')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('fresh same-session exit notice', result.stderr)
        self.assertNotEqual(self.state()[1]['status'], 'retired')
        self.assertTrue(self.state()[1].get('handoff_receipt'))

    def test_claude_wrong_session_exit_notice_is_pending(self):
        self.actor('claude-wrong-exit-notice')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('fresh same-session exit notice', result.stderr)
        self.assertNotEqual(self.state()[1]['status'], 'retired')

    def test_missing_exit_notice_is_pending(self):
        self.actor('no-exit-notice')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('fresh same-session exit notice', result.stderr)
        self.assertNotEqual(self.state()[1]['status'], 'retired')

    def test_exit_notice_requires_native_banner_and_fresh_requested_input(self):
        spec = importlib.util.spec_from_file_location('retire-notice-test', Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh'))).with_name('retire.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observer = module.Retirement(SimpleNamespace(pane='%1'))
        observer.tmux = ['tmux', '-L', 'inert-owned-unit-test']
        session = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        observer.state = {'identity': {'pane_pid': '123', 'process': {'agent': 'codex'}},
                          'exit': {'status': 'ambiguous', 'input_attempted': True, 'enters': 1},
                          'exit_notice': {'session_id': session, 'before': 0}}
        observer.pane = lambda: ['%1', '123', 'owned', '/owned']
        banner = 'Token usage: total=42\nTo continue this session, run:\n  codex resume ' + session + '\n'
        with patch.object(module, 'checked', return_value='  codex resume ' + session + '\n'):
            self.assertFalse(observer.fresh_exit_notice(session))
        with patch.object(module, 'checked', return_value=banner):
            self.assertTrue(observer.fresh_exit_notice(session))
            observer.state['exit'] = {'status': 'delivered', 'receipt': 'command', 'enters': 1}
            self.assertTrue(observer.fresh_exit_notice(session))
            observer.state['exit'] = {'status': 'ambiguous', 'input_attempted': True, 'enters': 0}
            self.assertFalse(observer.fresh_exit_notice(session))
            observer.state['exit'] = {'status': 'ambiguous', 'input_attempted': True, 'enters': 1}
            observer.state['exit_notice']['before'] = 1
            self.assertFalse(observer.fresh_exit_notice(session))  # Old full banner.
            observer.state['exit_notice']['before'] = 0
            observer.state['exit'] = {'status': 'deferred', 'input_attempted': False, 'enters': 1}
            self.assertFalse(observer.fresh_exit_notice(session))
        # A resumed missing or mismatched baseline cannot gain cached authority.
        observer.state['exit'] = {'status': 'ambiguous', 'input_attempted': True, 'enters': 1}
        observer.state['exit_notice']['session_id'] = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        with self.assertRaises(module.Stop):
            observer.fresh_exit_notice(session)

    def test_deferred_positive_enter_is_not_exit_request(self):
        spec = importlib.util.spec_from_file_location('retire-deferred-test', Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh'))).with_name('retire.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observer = module.Retirement(SimpleNamespace(pane='%1'))
        observer.tmux = ['tmux', '-L', 'inert-owned-unit-test']
        session = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        observer.state = {'identity': {'pane_pid': '123', 'process': {'agent': 'codex'}},
                          'exit': {'status': 'deferred', 'input_attempted': False, 'enters': 1},
                          'exit_notice': {'session_id': session, 'before': 0}}
        observer.pane = lambda: ['%1', '123', 'owned', '/owned']
        banner = 'Token usage: total=42\nTo continue this session, run:\n  codex resume ' + session + '\n'
        with patch.object(module, 'checked', return_value=banner):
            self.assertFalse(observer.fresh_exit_notice(session))

    def test_unknown_caller_identity_preserves_handoff_without_exit(self):
        self.actor('decline')
        self.invoke()
        path, state = self.state()
        data = shard_data(state['id'], state['identity'])
        data.update(author='caller', session_id='unknown', declined=True, provenance='caller cannot establish native identity')
        path.with_suffix('.shard').write_text(json.dumps(data))
        result = self.invoke('--resume', str(path), '--caller-shard')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('verifiable native session UUID', result.stderr)
        self.assertTrue(self.state()[1].get('handoff_receipt'))
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_native_preflight_rejects_source_common_dir_and_remotes(self):
        source = HERE.parents[2]
        candidates = [source / 'skills', self.repo]
        master = source.parent / 'master'
        if master.exists():
            candidates.append(master)
        for index, directory in enumerate(candidates):
            evidence = self.directory / ('rejected-native-' + str(index))
            result = subprocess.run([sys.executable, str(HERE / 'test-retire-native.py'), '--preflight-only',
                                     '--worktree', str(directory), '--evidence', str(evidence),
                                     '--shared-skill', str(SHARED.parent)], text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('disposable', result.stderr)
            self.assertFalse(evidence.exists(), 'unsafe cwd rejection produced native side effects')

    def test_native_preflight_is_read_only_and_checks_evidence_containment(self):
        # Even a future guard regression cannot turn this isolated test into a
        # model call: successful preflight returns before evidence or launch.
        script = HERE / 'test-retire-native.py'
        cwd = self.directory / 'dedicated-cwd'
        self.command('git', 'init', '-b', 'master', str(cwd))
        self.command('git', '-C', str(cwd), 'config', 'user.email', 'test@example.invalid')
        self.command('git', '-C', str(cwd), 'config', 'user.name', 'Test')
        self.command('git', '-C', str(cwd), 'commit', '--allow-empty', '-m', 'owned seed')
        for evidence, code in ((self.directory / 'preflight-evidence', 0), (cwd / 'evidence', 2)):
            result = subprocess.run([sys.executable, str(script), '--preflight-only',
                                     '--worktree', str(cwd), '--evidence', str(evidence),
                                     '--shared-skill', str(SHARED.parent)], text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertFalse(evidence.exists())
        fake = self.directory / 'fake-source'
        fake_scripts = fake / 'skills/retire-agent/scripts'
        fake_scripts.mkdir(parents=True)
        shutil.copytree(HERE.parents[1] / '_shared', fake_scripts.parents[1] / '_shared')
        for name in ('test-retire-native.py', 'retire.py'):
            shutil.copyfile(HERE / name, fake_scripts / name)
        nested = fake / 'owned-nested'
        self.command('git', 'init', '-b', 'master', str(nested))
        result = subprocess.run([sys.executable, str(fake_scripts / 'test-retire-native.py'), '--preflight-only',
                                 '--worktree', str(nested), '--evidence', str(self.directory / 'nested-evidence'),
                                 '--shared-skill', str(SHARED.parent)], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.directory / 'nested-evidence').exists())
        descendant_scripts = cwd / 'fake-source/skills/retire-agent/scripts'
        descendant_scripts.mkdir(parents=True)
        shutil.copytree(HERE.parents[1] / '_shared', descendant_scripts.parents[1] / '_shared')
        for name in ('test-retire-native.py', 'retire.py'):
            shutil.copyfile(HERE / name, descendant_scripts / name)
        result = subprocess.run([sys.executable, str(descendant_scripts / 'test-retire-native.py'), '--preflight-only',
                                 '--worktree', str(cwd), '--evidence', str(self.directory / 'ancestor-evidence'),
                                 '--shared-skill', str(SHARED.parent)], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('exclusively owned disposable', result.stderr)
        self.assertFalse((self.directory / 'ancestor-evidence').exists())

    def test_same_session_notice_cannot_retire_live_actor(self):
        self.actor('hold-notice')
        result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 2, result.stderr)
        state = self.state()[1]
        self.assertNotEqual(state['status'], 'retired')
        self.assertTrue(Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        self.assertFalse((self.directory / 'spawn.json').exists())
        self.assertNotEqual(json.loads(self.git('show', 'origin/master:' + state['handoff_receipt']))['status'], 'retired')

    def test_pending_exit_resume_preserves_baseline_and_never_resends(self):
        self.actor('hold-notice')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        baseline = state['exit_notice'].copy()
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()[1]['exit_notice'], baseline)
        attempts = [json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
        self.assertEqual(sum(row['action'] == 'send-attempt' and row.get('phase') == 'exit' for row in attempts), 1)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_exit_resume_malformed_baseline_is_preserved(self):
        self.actor('hold-notice')
        self.invoke()
        path, state = self.state()
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        for baseline in (None, {'session_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'before': '0'},
                         {'session_id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'before': 0}):
            state['exit_notice'] = baseline
            path.write_text(json.dumps(state))
            result = self.invoke('--resume', str(path))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('pre-request exit notice baseline', result.stderr)
            self.assertEqual(json.loads(path.read_text())['exit_notice'], baseline)

    def test_forged_retired_status_cannot_upgrade_pending_receipt(self):
        self.actor('hold')
        self.invoke()
        path, state = self.state()
        receipt_before = self.git('show', 'origin/master:' + state['handoff_receipt'])
        state['status'] = 'retired'
        path.write_text(json.dumps(state))
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.git('show', 'origin/master:' + state['handoff_receipt']), receipt_before)
        audit = [json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
        self.assertFalse(audit[-1]['exit_confirmed'])

    def test_retired_resume_lost_pane_preserves_historical_receipt(self):
        self.actor()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        path, state = self.state()
        receipt_before = self.git('show', 'origin/master:' + state['handoff_receipt'])
        self.command(*self.tmux, 'kill-pane', '-t', self.pane)
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.git('show', 'origin/master:' + state['handoff_receipt']), receipt_before)
        audit = [json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
        self.assertFalse(audit[-1]['exit_confirmed'])

    def test_native_interrupted_server_creation_releases_owned_label(self):
        spec = importlib.util.spec_from_file_location('retire-native-cleanup-test', HERE / 'test-retire-native.py')
        native = importlib.util.module_from_spec(spec)
        # Importing the native module performs no control or model launch.
        sys.path.insert(0, str(HERE))
        try:
            spec.loader.exec_module(native)
        finally:
            sys.path.pop(0)
        cwd = self.directory / 'disposable-cwd'
        cwd.mkdir()
        self.command('git', '-C', str(cwd), 'init')
        self.command('git', '-C', str(cwd), 'config', 'user.name', 'Disposable Test')
        self.command('git', '-C', str(cwd), 'config', 'user.email', 'test@example.invalid')
        self.command('git', '-C', str(cwd), 'commit', '--allow-empty', '-m', 'owned seed')
        evidence = self.directory / 'interrupted-native'
        original_run = native.run
        def interrupted_creation(command, **kwargs):
            result = original_run(command, **kwargs)
            if 'new-session' in command:
                self.assertEqual(result.returncode, 0, result.stderr)
                os.kill(os.getpid(), signal.SIGTERM)  # Signal only this owned test controller.
                raise AssertionError('installed SIGTERM handler did not interrupt creation return')
            return result
        argv = [str(HERE / 'test-retire-native.py'), '--worktree', str(cwd), '--evidence', str(evidence),
                '--shared-skill', str(SHARED.parent)]
        handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
        try:
            with patch.object(sys, 'argv', argv), patch.object(native.shutil, 'which', return_value=sys.executable), patch.object(native, 'run', side_effect=interrupted_creation):
                with self.assertRaises(SystemExit) as stopped:
                    native.main()
                self.assertEqual(stopped.exception.code, 143)
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
        report = json.loads((evidence / 'report.json').read_text())
        self.assertTrue(report['resources_released'])
        self.assertTrue(report['worktree_unchanged'])
        self.assertEqual(report['failure'], '143')
        self.assertNotEqual(subprocess.run(['tmux', '-L', report['label'], 'list-sessions'], capture_output=True).returncode, 0)

    def test_changing_draft_preserved_without_paste(self):
        self.actor('draft')
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.observed()['pastes'], 0)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'deferred')
        self.assertTrue(Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        self.assertIn('human unfinished draft', self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))

    def test_modal(self):
        self.actor('modal')
        self.assertEqual(self.invoke().returncode, 2)
        self.assertEqual(self.observed()['pastes'], 0)
        self.assertIn('trust the contents', self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        self.assertEqual(self.state()[1]['offer']['status'], 'deferred')

    def test_ambiguous_never_repastes(self):
        self.actor('ambiguous')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'ambiguous')
        count = self.observed()['pastes']
        self.assertEqual(count, 1)
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertEqual(self.invoke('--resume', str(path), '--retry-deferred', 'offer').returncode, 2)
        self.assertEqual(self.observed()['pastes'], count)

    def test_ambiguous_offer_observed_done_resumes_without_replay(self):
        self.actor('ambiguous-done')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'ambiguous')
        self.assertEqual(self.observed()['pastes'], 1)
        resumed = self.invoke('--resume', str(path))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        state = self.state()[1]
        self.assertEqual(state['offer']['status'], 'ambiguous')
        self.assertEqual(state['disposition'], 'DONE')
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertEqual(self.observed()['exit_enters'], 1)
        ledger = [json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
        self.assertTrue(any(row['action'] == 'ambiguous-offer-completion-observed'
                            and row['disposition'] == 'DONE' for row in ledger))

    def test_ambiguous_offer_uses_original_bytes_after_binding_disappears(self):
        self.actor('ambiguous-done')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'ambiguous')
        entry = self.instrument("        if not helper.is_file():", "        if True:")
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding reader unavailable', result.stderr)
        state = self.state()[1]
        self.assertEqual(state['disposition'], 'DONE')
        self.assertTrue(state.get('handoff_receipt'))
        self.assertNotIn('exit', state)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_previous_version_ambiguous_offer_is_verified_and_upgraded(self):
        self.actor('ambiguous-done')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        # Golden offer from the installed pre-change script, independent of
        # the new implementation's legacy reconstruction.
        event, shard = state['id'], path.with_suffix('.shard')
        protocol = HERE.parent / 'references/protocol.md'
        legacy = f'Thank you for your work. Every agent at every tier is offered retirement and off-duty time. Event {event}. Stop product work; preserve operational recovery separately from any personal thanks. Read {protocol} and write {shard} using its complete JSON schema, event {event}, identity {json.dumps(state["identity"])}. Include date/session_id/harness/model/working_directory/tmux_window/role/landed_work/lessons/provenance, structured recovery and resources. Do not exit. After writing your shard, your ENTIRE final reply must be RETIRE-DONE-{event}, with no preface, suffix or extra lines. You may decline; your ENTIRE final reply must then be RETIRE-DECLINED-{event}, with no extra text, and the caller will author recovery with honest attribution. Off-duty is not permission for product work.'
        state['offer'].pop('payload_bytes')
        state['offer'].pop('payload_sha256')
        path.write_text(json.dumps(state))
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertNotIn('handoff_receipt', self.state()[1])
        Path(state['offer']['payload']).write_text(legacy)
        resumed = self.invoke('--resume', str(path))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        upgraded = self.state()[1]
        self.assertEqual(upgraded['disposition'], 'DONE')
        self.assertEqual(upgraded['offer']['payload_bytes'], len(legacy.encode()))
        self.assertRegex(upgraded['offer']['payload_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(self.observed()['pastes'], 1)

    def test_ambiguous_offer_time_only_footer_is_completion(self):
        self.actor('ambiguous-done-time')
        self.assertEqual(self.invoke().returncode, 2)
        path, _ = self.state()
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 0)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_ambiguous_offer_wrong_or_extra_completion_stays_pending(self):
        self.actor('ambiguous-done-wrong')
        self.assertEqual(self.invoke().returncode, 2)
        path, _ = self.state()
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertNotIn('handoff_receipt', self.state()[1])
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertEqual(self.observed().get('exit_enters', 0), 0)

    def test_ambiguous_offer_suffix_stays_pending(self):
        self.actor('ambiguous-done-suffix')
        self.assertEqual(self.invoke().returncode, 2)
        path, _ = self.state()
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertNotIn('handoff_receipt', self.state()[1])
        self.assertEqual(self.observed().get('exit_enters', 0), 0)

    def test_ambiguous_offer_background_status_stays_pending(self):
        self.actor('ambiguous-done-background')
        self.assertEqual(self.invoke().returncode, 2)
        path, _ = self.state()
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertNotIn('handoff_receipt', self.state()[1])
        self.assertEqual(self.observed().get('exit_enters', 0), 0)

    def test_ambiguous_offer_positive_input_and_shard_gates(self):
        self.actor('ambiguous-done')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(self.invoke('--resume', str(path), '--retry-deferred', 'offer').returncode, 2)
        original = path.read_bytes()
        for key, value in (('enters', 0), ('input_attempted', False), ('paste_attempted', False),
                           ('pane', '%999'), ('input_method', 'typed'), ('payload', '/tmp/foreign')):
            with self.subTest(key=key):
                changed = json.loads(original)
                changed['offer'][key] = value
                changed['disposition'] = 'DONE'  # Cached completion cannot bypass sender evidence.
                path.write_text(json.dumps(changed))
                result = self.invoke('--resume', str(path))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('ambiguous offer lacks pinned positive input evidence', result.stderr)
                self.assertEqual(self.observed()['pastes'], 1)
                self.assertEqual(self.observed().get('exit_enters', 0), 0)
                self.assertNotIn('handoff_receipt', self.state()[1])
        path.write_bytes(original)
        shard = path.with_suffix('.shard')
        data = json.loads(shard.read_text())
        data['session_id'] = 'unknown'
        shard.write_text(json.dumps(data))
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertEqual(self.observed().get('exit_enters', 0), 0)
        self.assertNotIn('handoff_receipt', self.state()[1])

    def test_ambiguous_offer_evidence_gate_runs_on_resume(self):
        self.actor('ambiguous-done')
        self.assertEqual(self.invoke().returncode, 2)
        path, _ = self.state()
        anchor = '    def observe_ambiguous_offer(self):\n'
        entry = self.instrument(anchor, anchor + "        raise Stop('ambiguous offer evidence gate reached')\n")
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('ambiguous offer evidence gate reached', result.stderr)

    def test_ambiguous_offer_rechecks_cached_done_after_bad_shard(self):
        self.actor('ambiguous-done')
        self.assertEqual(self.invoke().returncode, 2)
        path, _ = self.state()
        shard = path.with_suffix('.shard')
        original = shard.read_bytes()
        data = json.loads(original)
        data['session_id'] = 'unknown'
        shard.write_text(json.dumps(data))
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertEqual(self.state()[1]['disposition'], 'DONE')
        shard.write_bytes(original)
        (self.directory / 'human-cleared-history').touch()
        self.wait_for(lambda: 'Assistant output cleared.' in self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn('DONE not observed', result.stderr)
        self.assertNotIn('handoff_receipt', self.state()[1])
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertEqual(self.observed().get('exit_enters', 0), 0)

    def test_ambiguous_offer_rejects_changed_missing_or_symlink_payload(self):
        self.actor('ambiguous-done')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        payload = Path(state['offer']['payload'])
        original = payload.read_bytes()
        for variant in ('fragments', 'missing', 'symlink'):
            with self.subTest(variant=variant):
                payload.unlink(missing_ok=True)
                if variant == 'fragments':
                    payload.write_text('Event ' + state['id'] + '.\nidentity '
                                       + json.dumps(state['identity']) + '\nRETIRE-DONE-' + state['id'])
                elif variant == 'symlink':
                    target = self.directory / 'foreign-offer'
                    target.write_bytes(original)
                    payload.symlink_to(target)
                result = self.invoke('--resume', str(path))
                self.assertEqual(result.returncode, 2)
                if variant == 'fragments':
                    self.assertIn('preserved ambiguous offer payload does not match pinned event', result.stderr)
                self.assertNotIn('handoff_receipt', self.state()[1])
                self.assertEqual(self.observed()['pastes'], 1)
                self.assertEqual(self.observed().get('exit_enters', 0), 0)
        payload.unlink()
        payload.write_bytes(original)

    def test_ambiguous_offer_caller_decline_requires_current_marker(self):
        self.actor('ambiguous-decline')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'ambiguous')
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.state()[1]['disposition'], 'DECLINED')
        shard = path.with_suffix('.shard')
        data = shard_data(state['id'], state['identity'])
        data.update(author='caller', declined=True, provenance='caller from committed artifacts; agent declined')
        shard.write_text(json.dumps(data))
        (self.directory / 'human-cleared-history').touch()
        self.wait_for(lambda: 'Assistant output cleared.' in self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        result = self.invoke('--resume', str(path), '--caller-shard')
        self.assertEqual(result.returncode, 2)
        self.assertIn('current observed agent decline', result.stderr)
        self.assertNotIn('handoff_receipt', self.state()[1])
        self.assertEqual(self.observed()['pastes'], 1)
        (self.directory / 'human-fresh-decline').touch()
        self.wait_for(lambda: 'RETIRE-DECLINED-' + state['id'] in self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        result = self.invoke('--resume', str(path), '--caller-shard')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_private_and_missing_remotes_before_send(self):
        self.actor()
        public = self.directory / 'public.git'
        self.command('git', 'clone', '--bare', str(self.directory / 'remote.git'), str(public))
        self.git('remote', 'set-url', 'origin', str(public))
        self.assertEqual(self.invoke().returncode, 2)
        self.assertEqual(self.observed()['pastes'], 0)
        self.git('remote', 'remove', 'origin')
        self.assertEqual(self.invoke().returncode, 2)
        self.assertEqual(self.observed()['pastes'], 0)

    def test_decline_caller_continuation(self):
        self.actor('decline')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertEqual(state['disposition'], 'DECLINED')
        shard = path.parent / (state['id'] + '.shard')
        data = shard_data(state['id'], state['identity'])
        data.update(author='caller', declined=True, provenance='caller from committed artifacts; agent declined')
        shard.write_text(json.dumps(data))
        result = self.invoke('--resume', str(path), '--caller-shard')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)  # one offer; typed exit
        self.assertEqual(json.loads(shard.read_text())['author'], 'caller')

    def test_waiting_requires_decision_owner(self):
        self.actor('waiting-bad')
        result = self.invoke('--waiting')
        self.assertEqual(result.returncode, 2)
        self.assertIn('pending decision', result.stderr)
        path, state = self.state()
        shard = path.parent / (state['id'] + '.shard')
        data = json.loads(shard.read_text())
        data['waiting'] = {'decision': 'Human scope decision', 'owner': 'Operator'}
        shard.write_text(json.dumps(data))
        self.assertEqual(self.invoke('--waiting', '--resume', str(path)).returncode, 0)

    def test_resource_pending_blocks_exit(self):
        self.actor('resource')
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn('resources', result.stderr)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_symlink_shard_blocks_exit(self):
        self.actor('path')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('missing or unsafe unique shard', result.stderr)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_handoff_brief_model_after_exit(self):
        self.actor()
        result = self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 0, result.stderr)
        spawned = json.loads((self.directory / 'spawn.json').read_text())
        self.assertIn('test-model', spawned['args'])
        self.assertIn('Cold-start audit before action', spawned['brief'])
        self.assertIn('Common to every hat', spawned['brief'])
        self.assertIn('Mission authorized', spawned['brief'])
        path, state = self.state()
        ledger = [json.loads(line) for line in path.with_suffix('.jsonl').read_text().splitlines()]
        actions = [record['action'] for record in ledger]
        self.assertLess(actions.index('original-exit-confirmed'), actions.index('successor-attempt'))
        self.assertLess(actions.index('successor-attempt'), actions.index('successor-result'))
        self.assertFalse(Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        self.assertEqual(self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles), '--resume', str(path)).returncode, 2)

    def test_no_successor_before_exit(self):
        self.actor('hold')
        result = self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 2)
        self.assertTrue((self.directory / 'exit-order.json').exists())
        self.assertFalse((self.directory / 'spawn.json').exists())

    def test_changed_identity_and_malformed_state(self):
        self.actor('decline')
        self.invoke()
        path, state = self.state()
        state['identity']['process']['start'] = 'wrong'
        path.write_text(json.dumps(state))
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn('identity changed', result.stderr)
        state['id'] = '../../escape'
        path.write_text(json.dumps(state))
        self.assertIn('invalid retirement event', self.invoke('--resume', str(path)).stderr)

    def test_push_failure_blocks_exit(self):
        self.actor()
        hook = self.directory / 'remote.git' / 'hooks' / 'pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o700)
        self.assertEqual(self.invoke().returncode, 2)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_old_done_does_not_complete(self):
        self.actor('old')
        self.assertEqual(self.invoke().returncode, 2)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_wrapped_user_done_does_not_complete(self):
        self.actor('quoted')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('DONE not observed', result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def assert_composer_marker_excluded(self, mode):
        self.actor(mode)
        self.assertEqual(self.invoke().returncode, 2)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertFalse((self.directory / 'exit-order.json').exists())
        path, state = self.state()
        self.assertIsNone(state['disposition'])
        self.assertNotIn('handoff_receipt', state)
        self.assertIn('● RETIRE-DONE-' + state['id'], self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        spec = importlib.util.spec_from_file_location('retire-composer-positive', SHARED / 'tmux-message.py')
        shared = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = shared
        spec.loader.exec_module(shared)
        rows = shared.read_response_rows(self.pane, state['socket'])
        self.assertIsNotNone(rows)  # A recognized input surface, not unknown-layout vacuity.
        self.assertIn('• Accepted', rows)
        self.assertFalse(any('RETIRE-DONE-' + state['id'] in row for row in rows))

    def test_composer_done_does_not_complete(self):
        self.assert_composer_marker_excluded('composer')

    def test_claude_composer_done_does_not_complete(self):
        self.assert_composer_marker_excluded('claude-composer')

    def test_agy_and_missing_launcher_preflight(self):
        self.actor()
        self.assertEqual(self.invoke('--handoff', 'agy', 'model', '--roles', str(self.roles)).returncode, 2)
        self.assertEqual(self.observed()['pastes'], 0)
        (self.directory / 'shared' / 'scripts' / 'agent-spawn.sh').unlink()
        self.assertEqual(self.invoke().returncode, 2)
        self.assertEqual(self.observed()['pastes'], 0)

    def test_preserved_shard_mutation_blocks_resumed_exit(self):
        self.actor('hold')
        self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles))
        path, state = self.state()
        canonical = self.staged(state, state['shard'])
        canonical.write_text(canonical.read_text() + ' ')
        before = self.observed()['pastes']
        result = self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles), '--resume', str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn('shard changed', result.stderr)
        self.assertEqual(self.observed()['pastes'], before)
        self.assertFalse((self.directory / 'spawn.json').exists())

    def test_real_node_entrypoint_and_claude_successor_model(self):
        self.actor('node-core', node=True)
        result = self.invoke('--handoff', 'claude', 'opus', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 0, result.stderr)
        spawned = json.loads((self.directory / 'spawn.json').read_text())
        self.assertIn('claude', spawned['args'])
        self.assertIn('opus', spawned['args'])

    def test_required_recovery_fields(self):
        self.actor('waiting-bad')
        self.invoke('--waiting')
        path, state = self.state()
        shard = path.parent / (state['id'] + '.shard')
        data = json.loads(shard.read_text())
        data['waiting'] = {'decision': 'Human decision', 'owner': 'Operator'}
        del data['recovery']['heads']
        shard.write_text(json.dumps(data))
        self.assertIn('recovery requires heads', self.invoke('--waiting', '--resume', str(path)).stderr)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_extra_native_core_is_not_collapsed(self):
        self.actor('extra-core', node=True)
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn('exactly one', result.stderr)
        self.assertEqual(self.observed()['pastes'], 0)

    def test_explicit_no_paste_deferral_retry(self):
        self.actor('draft')
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertFalse(state['offer']['paste_attempted'])
        (self.directory / 'human-cleared-draft').touch()  # fixture human clears its own draft
        self.wait_for(lambda: 'human unfinished draft' not in self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        result = self.invoke('--resume', str(path), '--retry-deferred', 'offer')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_legacy_index_metadata_preserved(self):
        waiting = self.repo / 'waiting'
        waiting.mkdir()
        original = '# Steward index\n\n| Session | Provider | Role | State | Last verified |\n| legacy | Anthropic | Lead | parked by the operator | yesterday |\n\nException: keep decision owner.\n'
        (waiting / 'INDEX.md').write_text(original)
        (waiting / '2026-09-25-deadbeef-lead.md').write_text('Legacy shard and its evidence.\n')
        self.git('add', 'waiting')
        self.git('commit', '-m', 'legacy records')
        self.git('push')
        self.actor()
        self.assertEqual(self.invoke().returncode, 0)
        self.assertTrue((waiting / 'INDEX.md').read_text().startswith(original))
        self.assertIn('retire-agent:begin', self.git('show', 'origin/master:waiting/INDEX.md'))

    def test_legacy_session_prefix_blocks_duplicate(self):
        waiting = self.repo / 'waiting'
        waiting.mkdir()
        (waiting / '2026-09-25-aaaaaaaa-lead.md').write_text('Existing recovery for this session.\n')
        self.git('add', 'waiting')
        self.git('commit', '-m', 'existing legacy shard')
        self.git('push')
        self.actor()
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn('legacy session shard', result.stderr)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_non_ascii_foreign_shard_does_not_block_retirement(self):
        waiting = self.repo / 'waiting'
        waiting.mkdir()
        (waiting / 'é.md').write_text('{}\n')
        self.git('add', 'waiting')
        self.git('commit', '-m', 'foreign unicode shard')
        self.git('push')
        self.actor()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_symlinked_publication_stage_stays_untouched_on_resume(self):
        self.actor('waiting-bad')
        self.assertEqual(self.invoke('--waiting').returncode, 2)
        path, state = self.state()
        stage = path.parent / (state['id'] + '.publication')
        stage.rename(self.directory / 'preserved-stage')
        outside = self.directory / 'outside-stage'
        outside.mkdir()
        (outside / 'sentinel').write_text('untouched\n')
        stage.symlink_to(outside, target_is_directory=True)
        result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('unsafe event publication directory', result.stderr)
        self.assertEqual(sorted(item.name for item in outside.iterdir()), ['sentinel'])

    def test_nonobject_shard_is_controlled_failure(self):
        self.actor('waiting-bad')
        self.invoke('--waiting')
        path, state = self.state()
        shard = path.with_suffix('.shard')
        shard.write_text('[]')
        before = self.observed()['pastes']
        result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('shard must be a JSON object', result.stderr)
        self.assertEqual(self.observed()['pastes'], before)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_index_symlink_preserves_outside_file(self):
        waiting = self.repo / 'waiting'
        waiting.mkdir()
        outside = self.directory / 'human-index'
        original = 'Unrelated human record.\n'
        outside.write_text(original)
        (waiting / 'INDEX.md').symlink_to(outside)
        self.git('add', 'waiting/INDEX.md')
        self.git('commit', '-m', 'unsafe remote index link')
        self.git('push')
        self.actor()
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('unsafe index path', result.stderr)
        self.assertEqual(outside.read_text(), original)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_gh_privacy_pins_remote_host(self):
        gh = self.directory / 'gh'
        log = self.directory / 'gh-args.json'
        gh.write_text('#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
                      + 'Path(' + repr(str(log)) + ').write_text(json.dumps(sys.argv[1:]))\n'
                      + 'repo=sys.argv[3]\n'
                      + 'print("true" if repo == "https://github.com/owner/private" or (not repo.startswith("https://github.com/") and os.environ.get("GH_HOST") == "enterprise.invalid") else "false")\n')
        gh.chmod(0o700)
        spec = importlib.util.spec_from_file_location('retirement-test', Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh'))).with_name('retire.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env = dict(self.env, PATH=str(self.directory) + ':' + os.environ['PATH'], GH_HOST='enterprise.invalid')
        env.pop('RETIRE_PRIVATE_CHECK')
        with patch.dict(os.environ, env, clear=True):
            retirement = module.Retirement(SimpleNamespace(pane='%0'))
            self.git('remote', 'set-url', 'origin', 'https://github.com/owner/public.git')
            with self.assertRaises(module.Stop):
                retirement.private()
            self.assertEqual(json.loads(log.read_text())[2], 'https://github.com/owner/public')
            self.git('remote', 'set-url', 'origin', 'git@github.com:owner/private.git')
            retirement.private()  # positive production-gh branch, still no network
            self.assertEqual(json.loads(log.read_text())[2], 'https://github.com/owner/private')

    def test_duplicate_session_transaction_race(self):
        panes = [self.actor(), self.actor()]
        barrier = ('        (self.path.parent / (self.state["id"] + ".validated")).touch()\n'
                   '        until = time.monotonic() + .5\n'
                   '        while len(list(self.path.parent.glob("*.validated"))) < 2 and time.monotonic() < until:\n'
                   '            time.sleep(.01)\n'
                   '        return data, content\n')
        entry = self.instrument('        return data, content\n', barrier)
        processes = [subprocess.Popen([str(entry), pane, '--wait', '2', '--poll', '.02'], env=self.env,
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for pane in panes]
        results = []
        for process in processes:
            out, err = process.communicate(timeout=15)
            results.append((process.returncode, out, err))
        self.assertEqual(sorted(result[0] for result in results), [0, 2], results)
        self.assertTrue(any('session already has' in result[2] for result in results), results)
        self.git('fetch', 'origin', 'master')
        shards = [name for name in self.git('ls-tree', '-r', '--name-only', 'origin/master', '--', 'waiting').splitlines()
                  if name.endswith('.md') and name != 'waiting/INDEX.md']
        self.assertEqual(len(shards), 1)
        self.assertEqual(json.loads(self.git('show', 'origin/master:' + shards[0]))['session_id'], 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.assertFalse((self.repo / 'waiting').exists())

    def test_independent_exit_after_handoff_remains_pending(self):
        self.actor()
        before = "        if not self.state.get('exit'):\n"
        after = ('        (self.repo.parent / "human-independent-exit").touch()\n'
                 '        until = time.monotonic() + 3\n'
                 '        while not self.ended() and time.monotonic() < until:\n'
                 '            time.sleep(.02)\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('ended before exit request', result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertFalse((self.directory / 'exit-order.json').exists())
        self.assertFalse((self.directory / 'spawn.json').exists())
        self.assertTrue(self.state()[1].get('handoff_receipt'))

    def test_independent_exit_with_replacement_refuses_successor(self):
        self.actor()
        inner = 'exec -a codex ' + shlex.join([sys.executable, str(Path(__file__).resolve()), '--terminal', str(self.directory), 'done'])
        outer = fixture_command(self.directory, inner)
        before = "        if not self.state.get('exit'):\n"
        after = ('        signal = self.repo.parent / "human-independent-exit"\n'
                 '        signal.touch()\n'
                 '        until = time.monotonic() + 3\n'
                 '        while not self.ended() and time.monotonic() < until:\n'
                 '            time.sleep(.02)\n'
                 '        signal.unlink()\n'
                 '        stats = self.repo.parent / "terminal.json"\n'
                 '        stats.unlink(missing_ok=True)\n'
                 '        checked(self.tmux + ["respawn-pane", "-k", "-t", self.args.pane, ' + repr(outer) + '])\n'
                 '        until = time.monotonic() + 3\n'
                 '        while not stats.exists() and time.monotonic() < until:\n'
                 '            time.sleep(.02)\n'
                 '        if not stats.exists():\n'
                 '            raise Stop("fixture replacement did not become ready")\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(result.stderr, 'replacement actor found|pane root identity changed')
        self.assertFalse((self.directory / 'spawn.json').exists())
        self.assertFalse((self.directory / 'exit-order.json').exists())
        self.assertEqual(self.observed()['pastes'], 0)  # replacement fixture is live and untouched

    def test_malformed_state_and_history_preserved(self):
        self.actor('decline')
        self.invoke()
        path, state = self.state()
        original = path.read_text()
        before = self.observed()['pastes']
        for malformed in ('[]', '{"id": 9}', json.dumps(dict(state, offer=[])), json.dumps(dict(state, identity={'process': []})), json.dumps(dict(state, shard=[]))):
            with self.subTest(malformed=malformed):
                path.write_text(malformed)
                result = self.invoke('--resume', str(path))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('malformed retirement', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(path.read_text(), malformed)
                self.assertEqual(self.observed()['pastes'], before)
        path.write_text(original)
        history = path.parent / ('f' * 32 + '.json')
        history.write_text('[]')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('malformed retirement state', result.stderr)
        self.assertEqual(history.read_text(), '[]')
        self.assertEqual(self.observed()['pastes'], before)

    def test_historical_event_filename_id_mismatch_preserved(self):
        self.actor('decline')
        self.invoke()
        path, state = self.state()
        wrong = path.parent / ('f' * 32 + '.json')
        content = json.dumps(dict(state, id='0' * 32))
        wrong.write_text(content)
        before = self.observed()['pastes']
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('malformed historical retirement event identity', result.stderr)
        self.assertEqual(wrong.read_text(), content)
        self.assertEqual(self.observed()['pastes'], before)

    def test_malformed_receipt_and_index_preserved(self):
        self.actor('hold')
        self.invoke()
        path, state = self.state()
        receipt = self.staged(state, state['handoff_receipt'])
        original = receipt.read_text()
        before = self.observed()['pastes']
        for malformed in ('[]', '{"event": []}', json.dumps({'event': state['id'], 'status': []})):
            receipt.write_text(malformed)
            result = self.invoke('--resume', str(path))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('malformed retirement receipt', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(receipt.read_text(), malformed)
        receipt.write_text(original)
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        original_index = self.git('show', 'origin/master:waiting/INDEX.md')
        editor = self.remote_editor()
        bad = editor / 'waiting' / 'malformed.md'
        claimed_receipt = editor / 'receipts' / ('e' * 32 + '.json')
        claimed_receipt.write_text(json.dumps({'event': 'e' * 32, 'shard': 'waiting/malformed.md', 'status': 'pending-exit'}))
        for malformed in (json.dumps({'event': 'e' * 32, key: []}) for key in ('harness', 'session_id', 'role')):
            bad.write_text(malformed)
            self.editor_git(editor, 'add', 'waiting/malformed.md', 'receipts/' + 'e' * 32 + '.json')
            self.editor_git(editor, 'commit', '-m', 'malformed remote metadata')
            self.editor_git(editor, 'push', 'origin', 'HEAD:master')
            result = self.invoke('--resume', str(path))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('malformed index shard', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(bad.read_text(), malformed)
            self.git('fetch', 'origin', 'master')
            self.assertEqual(self.git('show', 'origin/master:waiting/INDEX.md'), original_index)
        self.assertEqual(self.observed()['pastes'], before)

    def test_claude_literal_exit_real_terminal(self):
        self.actor('claude')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = self.observed()
        self.assertEqual(observed['pastes'], 1)  # offer only; literal exit never pasted
        self.assertFalse(observed['exit_pasted'])
        self.assertEqual(observed['exit_enters'], 1)
        self.assertEqual(observed['enters'], 2)  # offer plus one exit Enter
        self.assertTrue(json.loads((self.directory / 'exit-order.json').read_text())['receipt_before_exit'])
        path, state = self.state()
        self.assertEqual(state['exit']['receipt'], 'command')
        self.assertEqual(state['exit']['transport'], 'literal')
        self.assertEqual(state['exit']['input_method'], 'typed')

    def test_post_offer_push_failure_blocks_exit(self):
        self.actor('push-reject')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('private publication failed', result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'delivered')
        self.assertEqual(state['disposition'], 'DONE')
        self.assertNotIn('exit', state)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_validated_snapshot_ignores_later_symlink_swap(self):
        self.actor()
        before = '        return data, content\n'
        after = ('        (self.repo.parent / "validated-snapshot").write_bytes(content)\n'
                 '        changed = json.loads(content)\n'
                 '        changed["recovery"]["mission"] = "UNVALIDATED CHANGED MISSION"\n'
                 '        outside = self.repo.parent / "swapped-source"\n'
                 '        outside.write_text(json.dumps(changed))\n'
                 '        path.unlink()\n'
                 '        path.symlink_to(outside)\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        path, state = self.state()
        canonical = self.staged(state, state['shard'])
        self.assertEqual(canonical.read_bytes(), (self.directory / 'validated-snapshot').read_bytes())
        self.assertNotIn('UNVALIDATED CHANGED MISSION', self.git('show', 'origin/master:' + state['shard']))

    def test_wrapper_exit_waits_for_lingering_core(self):
        self.actor('linger-core', node=True)
        result = self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('pending original process end', result.stderr)
        path, state = self.state()
        self.assertFalse(Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        core = state['identity']['process']['cores'][0]
        self.assertTrue(Path('/proc/' + str(core['pid'])).exists())
        record = json.loads(self.git('show', 'origin/master:' + state['handoff_receipt']))
        self.assertNotEqual(record['status'], 'retired')
        self.assertFalse((self.directory / 'spawn.json').exists())
        self.assertEqual(process_token(core['pid']), {key: core[key] for key in ('pid', 'start', 'boot')})
        os.kill(core['pid'], signal.SIGTERM)  # exact test-owned lingering core
        time.sleep(.05)
        result = self.invoke('--handoff', 'codex', 'test-model', '--roles', str(self.roles), '--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.directory / 'spawn.json').exists())

    def test_resume_uses_pinned_socket(self):
        self.actor('waiting-bad')
        self.invoke('--waiting')
        path, state = self.state()
        data = json.loads(path.with_suffix('.shard').read_text())
        data['waiting'] = {'decision': 'scope', 'owner': 'Operator'}
        path.with_suffix('.shard').write_text(json.dumps(data))
        self.env['SPAWN_TMUX_LABEL'] = 'different-' + uuid.uuid4().hex
        self.env.pop('TMUX', None)
        result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_socket_failure_is_not_pane_disappearance(self):
        self.actor('hold')
        self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        path, state = self.state()
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        state['socket'] = str(self.directory / 'missing-socket')
        path.write_text(json.dumps(state))
        result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles), '--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('command failed: tmux', result.stderr)
        self.assertFalse((self.directory / 'spawn.json').exists())
        self.assertNotEqual(json.loads(self.git('show', 'origin/master:' + state['handoff_receipt']))['status'], 'retired')

        # Socket failure cannot itself establish the process-side lifecycle
        # result, even when the separate notice guard would also reject it.
        spec = importlib.util.spec_from_file_location('retire-socket-test', Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh'))).with_name('retire.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observer = module.Retirement(SimpleNamespace(pane=self.pane))
        observer.state = state
        observer.tmux = ['tmux', '-S', state['socket']]
        with self.assertRaises(module.Stop):
            observer.ended()

    def test_steward_dirty_index_stays_local_while_remote_index_updates(self):
        waiting = self.repo / 'waiting'
        waiting.mkdir()
        index = waiting / 'INDEX.md'
        original = '# Steward index\n\nDo not publish unfinished edits.\n\n'
        index.write_text(original)
        self.git('add', 'waiting')
        self.git('commit', '-m', 'steward baseline')
        self.git('push')
        edited = original + 'Unfinished human draft.\n'
        index.write_text(edited)
        self.actor()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(index.read_text(), edited)
        remote_index = self.git('show', 'origin/master:waiting/INDEX.md')
        self.assertTrue(remote_index.startswith(original))
        self.assertIn('retire-agent:begin', remote_index)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertTrue((self.directory / 'exit-order.json').exists())

    def test_unowned_local_commit_does_not_block_or_get_pushed(self):
        self.actor()
        (self.repo / 'human-work').write_text('Not authorized for publication.\n')
        self.git('add', 'human-work')
        self.git('commit', '-m', 'unfinished human work')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertNotIn('human-work', self.git('ls-tree', '-r', '--name-only', 'origin/master'))

    def test_prose_before_done_stays_pending(self):
        self.actor('prose-marker')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('DONE not observed', result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertEqual(self.state()[1]['offer']['status'], 'delivered')
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_relative_node_entrypoint_uses_target_cwd(self):
        self.actor(node=True, relative=True)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_retry_without_resume_has_no_attempt(self):
        self.actor()
        result = self.invoke('--retry-deferred', 'offer')
        self.assertEqual(result.returncode, 2)
        self.assertIn('require --resume', result.stderr)
        self.assertFalse((self.repo / '.git' / 'retirements').exists())
        self.assertEqual(self.observed()['pastes'], 0)

    def test_saved_done_survives_cleared_screen(self):
        self.actor('waiting-bad')
        self.invoke('--waiting')
        path, state = self.state()
        self.assertEqual(state['disposition'], 'DONE')
        data = json.loads(path.with_suffix('.shard').read_text())
        data['waiting'] = {'decision': 'scope', 'owner': 'Operator'}
        path.with_suffix('.shard').write_text(json.dumps(data))
        (self.directory / 'human-cleared-history').touch()
        self.wait_for(lambda: 'RETIRE-DONE' not in self.command(*self.tmux, 'capture-pane', '-p', '-t', self.pane))
        result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)

    def test_last_poll_interval_is_observed(self):
        self.actor('late-done')
        result = self.invoke('--poll', '.4')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()[1]['disposition'], 'DONE')

    def test_exit_deferral_reports_retry_without_waiting(self):
        self.actor()
        before = "        if not self.state.get('exit'):\n"
        after = ('        (self.repo.parent / "human-typed-draft").touch()\n'
                 '        time.sleep(.15)\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('--retry-deferred exit', result.stderr)
        self.assertEqual(self.state()[1]['exit']['status'], 'deferred')
        self.assertEqual(self.observed()['pastes'], 1)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_failed_initial_push_is_verified_before_resumed_offer(self):
        self.actor('initial-receipt')
        hook = self.directory / 'remote.git' / 'hooks' / 'pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o700)
        self.assertEqual(self.invoke().returncode, 2)
        path, state = self.state()
        self.assertNotIn('offer', state)
        self.assertEqual(self.observed()['pastes'], 0)
        hook.unlink()
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads((self.directory / 'pre-offer-receipt.json').read_text())['verified'])

    def test_sender_timeout_is_ambiguous_and_not_replayed(self):
        self.actor()
        before = '    return subprocess.run([str(x) for x in args], text=True, capture_output=True,\n'
        after = ('    if str(args[0]).endswith("tmux-message.sh"):\n'
                 '        raise subprocess.TimeoutExpired(args, 45)\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('timeout is ambiguous', result.stderr)
        path, state = self.state()
        self.assertEqual(state['offer']['status'], 'ambiguous')
        self.assertEqual(self.invoke('--resume', str(path)).returncode, 2)
        self.assertEqual(self.observed()['pastes'], 0)
        self.assertIn('sender-timeout', path.with_suffix('.jsonl').read_text())

    def test_launcher_timeout_is_unconfirmed_and_not_repeated(self):
        self.actor()
        before = '    return subprocess.run([str(x) for x in args], text=True, capture_output=True,\n'
        after = ('    if str(args[0]).endswith("agent-spawn.sh"):\n'
                 '        raise subprocess.TimeoutExpired(args, 45)\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('timeout is unconfirmed', result.stderr)
        path, state = self.state()
        self.assertEqual(state['spawn']['status'], 'unconfirmed')
        self.assertFalse((self.directory / 'spawn.json').exists())
        self.assertEqual(self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles), '--resume', str(path)).returncode, 2)
        self.assertFalse((self.directory / 'spawn.json').exists())
        self.assertIn('successor-timeout', path.with_suffix('.jsonl').read_text())

    def test_claude_ghost_literal_exit_real_terminal(self):
        self.actor('claude-ghost')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = self.observed()
        self.assertEqual(observed['pastes'], 1)
        self.assertFalse(observed['exit_pasted'])
        self.assertEqual(observed['exit_enters'], 1)
        self.assertEqual(observed['enters'], 2)
        self.assertEqual(self.state()[1]['exit']['transport'], 'literal')

    def test_handoff_brief_reads_verified_blob(self):
        self.actor()
        before = "            brief = directory / (event + '-brief.txt')\n"
        after = ('            (self.records / self.state["shard"]).write_text("UNVERIFIED LOCAL TEXT")\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        self.assertEqual(result.returncode, 0, result.stderr)
        brief = json.loads((self.directory / 'spawn.json').read_text())['brief']
        self.assertIn('Mission authorized', brief)
        self.assertNotIn('UNVERIFIED LOCAL TEXT', brief)

    def test_pending_fifo_swap_never_blocks(self):
        self.actor()
        before = '        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW'
        after = '        path.unlink()\n        os.mkfifo(path)\n' + before
        entry = self.instrument(before, after)
        try:
            result = subprocess.run([str(entry), self.pane, '--wait', '.4', '--poll', '.02'], env=self.env,
                                    text=True, capture_output=True, timeout=2)
        except subprocess.TimeoutExpired:
            self.fail('FIFO swap blocked the retirement controller')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('pending shard must be a regular file', result.stderr)
        self.assertFalse((self.directory / 'exit-order.json').exists())

    def test_foreign_adjacent_temp_preserved(self):
        self.actor('waiting-bad')
        self.invoke('--waiting')
        path, state = self.state()
        shard = path.with_suffix('.shard')
        data = json.loads(shard.read_text())
        data['waiting'] = {'decision': 'fixture decision', 'owner': 'Operator'}
        shard.write_text(json.dumps(data))
        foreign = self.staged(state, 'receipts/' + state['id'] + '.tmp')
        foreign.write_text('foreign unfinished data')
        result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(foreign.read_text(), 'foreign unfinished data')

    def test_mcp_support_server_is_not_second_harness(self):
        spec = importlib.util.spec_from_file_location('retirement-test', Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh'))).with_name('retire.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(Path, 'read_bytes', return_value=b'codex\0mcp-server\0'):
            self.assertEqual(module.proc(os.getpid())['agent'], 'codex-support')
        with patch.object(Path, 'read_bytes', return_value=b'codex\0'):
            self.assertEqual(module.proc(os.getpid())['agent'], 'codex')

    def test_desktop_codex_app_server_classifier_is_exact(self):
        spec = importlib.util.spec_from_file_location('retirement-desktop-test', Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh'))).with_name('retire.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        desktop = '/nix/store/kpmq44z3v3pwammvi1iff193yqim4cg2-codex-desktop-26.911.61220/lib/chatgpt/resources/codex'
        cli = '/users/actor/.npm-global/lib/node_modules/@openai/codex/vendor/bin/codex'
        cases = (
            (desktop, (b'app-server', b'--listen', b'stdio://'), desktop, True),
            (desktop, (b'resume',), desktop, False),
            (desktop, (b'app-server', b'--listen', b'tcp://'), desktop, False),
            (desktop, (b'app-server', b'--listen', b'stdio://'), cli, False),
            (cli, (b'app-server', b'--listen', b'stdio://'), cli, False),
        )
        for executable, args, actual_exe, auxiliary in cases:
            with self.subTest(executable=executable, args=args, actual_exe=actual_exe):
                argv = b'\0'.join([executable.encode(), *args, b''])
                with patch.object(Path, 'read_bytes', return_value=argv), patch.object(module.os, 'readlink', return_value=actual_exe):
                    result = module.proc(os.getpid())
                if auxiliary:
                    self.assertEqual(result['agent'], 'codex-support')
                else:
                    self.assertEqual(result['agent'], 'codex')
        argv = b'\0'.join([desktop.encode(), b'app-server', b'--listen', b'stdio://', b''])
        with patch.object(Path, 'read_bytes', return_value=argv), patch.object(module.os, 'readlink', side_effect=OSError):
            self.assertEqual(module.proc(os.getpid())['agent'], 'codex')

    def test_auxiliary_parent_does_not_hide_nested_cli_actor(self):
        spec = importlib.util.spec_from_file_location('retirement-tree-test', Path(os.environ.get('RETIRE_TEST_SCRIPT', str(HERE / 'retire.sh'))).with_name('retire.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        desktop = '/nix/store/kpmq44z3v3pwammvi1iff193yqim4cg2-codex-desktop-26.911.61220/lib/chatgpt/resources/codex'
        parents = {100: 1, 101: 100, 102: 101}
        commands = {
            100: b'/usr/bin/codex\0resume\0',
            102: b'/usr/bin/codex\0resume\0',
        }
        paths = [Path('/proc') / str(pid) for pid in parents]

        def read_text(path):
            if str(path) == '/proc/sys/kernel/random/boot_id':
                return 'fixture-boot'
            pid = int(path.parent.name)
            fields = ['S', str(parents[pid]), *(['0'] * 18)]
            fields[19] = '123'
            return f'{pid} (codex) ' + ' '.join(fields)

        def read_bytes(path):
            return commands[int(path.parent.name)]

        observer = module.Retirement.__new__(module.Retirement)
        for support_command in (desktop.encode() + b'\0app-server\0--listen\0stdio://\0',
                                b'/usr/bin/codex\0mcp-server\0'):
            with self.subTest(support_command=support_command):
                commands[101] = support_command
                with (patch.object(Path, 'iterdir', return_value=paths),
                      patch.object(Path, 'read_text', read_text),
                      patch.object(Path, 'read_bytes', read_bytes),
                      patch.object(module.os, 'readlink', return_value=desktop)):
                    self.assertEqual([actor['pid'] for actor in observer.actors(100)], [100, 102])

    def test_remote_requested_receipt_cannot_authorize_successor(self):
        self.actor('hold')
        self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        path, state = self.state()
        receipt = self.staged(state, state['handoff_receipt'])
        data = json.loads(receipt.read_text())
        data['status'] = 'retirement-requested'
        receipt.write_text(json.dumps(data))
        editor = self.remote_editor()
        (editor / state['handoff_receipt']).write_text(json.dumps(data))
        self.editor_git(editor, 'add', '--', state['handoff_receipt'])
        self.editor_git(editor, 'commit', '-m', 'fixture remote tamper')
        self.editor_git(editor, 'push', 'origin', 'HEAD:master')
        self.git('fetch', 'origin', 'master')
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        tampered = self.git('show', 'origin/master:' + state['handoff_receipt'])
        for _ in range(2):
            result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles), '--resume', str(path))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('does not establish handoff', result.stderr)
            self.assertFalse((self.directory / 'spawn.json').exists())
            self.assertEqual(self.git('show', 'origin/master:' + state['handoff_receipt']), tampered)
            self.assertEqual(receipt.read_text(), json.dumps(data))

    def test_stale_tracking_ref_cannot_authorize_exit_after_remote_removal(self):
        self.actor('hold')
        self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        path, state = self.state()
        editor = self.remote_editor()
        self.editor_git(editor, 'rm', state['shard'])
        self.editor_git(editor, 'commit', '-m', 'remove remote shard')
        self.editor_git(editor, 'push', 'origin', 'HEAD:master')
        self.git('config', '--replace-all', 'remote.origin.fetch',
                 '+refs/heads/other:refs/remotes/origin/other')
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles), '--resume', str(path))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('preserved shard changed after receipt', result.stderr)
        self.assertFalse((self.directory / 'spawn.json').exists())

    def test_dirty_shared_attributes_do_not_change_remote_byte_verification(self):
        self.actor('waiting-bad')
        self.assertEqual(self.invoke('--waiting').returncode, 2)
        path, _ = self.state()
        shard = path.with_suffix('.shard')
        data = json.loads(shard.read_text())
        data['waiting'] = {'decision': 'Choose scope', 'owner': 'Operator'}
        source = (json.dumps(data, indent=2) + '\n').replace('\n', '\r\n').encode()
        shard.write_bytes(source)
        (self.repo / '.gitattributes').write_text('waiting/*.md text eol=lf\n')
        result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.state()[1]
        remote_bytes = subprocess.check_output(['git', '--git-dir', str(self.directory / 'remote.git'),
                                                'show', 'master:' + state['shard']])
        self.assertEqual(remote_bytes, source)
        self.assertEqual((self.repo / '.gitattributes').read_text(), 'waiting/*.md text eol=lf\n')

    def test_committed_remote_attributes_preserve_exact_shard_bytes(self):
        (self.repo / '.gitattributes').write_text('waiting/*.md text eol=lf\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-m', 'remote shard attributes')
        self.git('push')
        self.actor('waiting-bad')
        self.assertEqual(self.invoke('--waiting').returncode, 2)
        path, _ = self.state()
        shard = path.with_suffix('.shard')
        data = json.loads(shard.read_text())
        data['waiting'] = {'decision': 'Choose scope', 'owner': 'Operator'}
        source = (json.dumps(data, indent=2) + '\n').replace('\n', '\r\n').encode()
        shard.write_bytes(source)
        result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.state()[1]
        remote_bytes = subprocess.check_output(['git', '--git-dir', str(self.directory / 'remote.git'),
                                                'cat-file', 'blob', 'master:' + state['shard']])
        self.assertEqual(remote_bytes, source)

    def test_resume_rereads_state_after_event_lock(self):
        self.actor('waiting-bad')
        self.invoke('--waiting')
        path, state = self.state()
        data = json.loads(path.with_suffix('.shard').read_text())
        data['waiting'] = {'decision': 'scope', 'owner': 'Operator'}
        path.with_suffix('.shard').write_text(json.dumps(data))
        before = "        self.event_lock = (directory / (self.state['id'] + '.lock')).open('a')\n"
        after = ('        if self.args.resume:\n'
                 '            disk = json.loads(self.path.read_text())\n'
                 '            disk["after_lock_fixture"] = True\n'
                 '            save(self.path, disk)\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke('--waiting', '--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.state()[1].get('after_lock_fixture'))

    def test_remote_bad_commit_receipt_never_self_heals(self):
        self.actor('hold')
        self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        path, state = self.state()
        receipt = self.staged(state, state['handoff_receipt'])
        data = json.loads(receipt.read_text())
        data['commit'] = self.git('rev-list', '--max-parents=0', 'HEAD')
        receipt.write_text(json.dumps(data))
        editor = self.remote_editor()
        (editor / state['handoff_receipt']).write_text(json.dumps(data))
        self.editor_git(editor, 'add', '--', state['handoff_receipt'])
        self.editor_git(editor, 'commit', '-m', 'fixture mismatched commit')
        self.editor_git(editor, 'push', 'origin', 'HEAD:master')
        self.git('fetch', 'origin', 'master')
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        tampered = self.git('show', 'origin/master:' + state['handoff_receipt'])
        for _ in range(2):
            result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles), '--resume', str(path))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('private receipt commit lacks preserved shard path', result.stderr)
            self.assertFalse((self.directory / 'spawn.json').exists())
            self.assertEqual(self.git('show', 'origin/master:' + state['handoff_receipt']), tampered)
            self.assertEqual(receipt.read_text(), json.dumps(data))

    def assert_completion_block_pending(self, mode):
        self.actor(mode)
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('DONE not observed', result.stderr)
        self.assertEqual(self.observed()['pastes'], 1)
        path, state = self.state()
        self.assertIsNone(state['disposition'])
        self.assertNotIn('handoff_receipt', state)
        self.assertFalse((self.directory / 'exit-order.json').exists())
        self.assertTrue(Path('/proc/' + str(state['identity']['process']['pid'])).exists())

    def test_codex_ui_footer_allows_marker_completion(self):
        self.actor('done-codex-footer')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_codex_ui_footer_with_hours_allows_marker_completion(self):
        self.actor('done-codex-footer-hours')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_ui_bullet_footer_allows_marker_completion(self):
        self.actor('done-codex-footer-bullet')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_codex_ui_bullet_footer_same_row_prose_is_pending(self):
        self.assert_completion_block_pending('done-codex-footer-bullet-same-row-prose')

    def test_codex_ui_footer_time_only_allows_marker_completion(self):
        self.actor('done-codex-footer-time-only')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_ui_footer_trailing_padding_is_allowed(self):
        self.actor('done-codex-footer-padded-footer')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_ui_footer_never_hides_additional_prose(self):
        self.assert_completion_block_pending('done-codex-footer-extra-prose')

    def test_codex_ui_footer_same_row_prose_is_pending(self):
        self.assert_completion_block_pending('done-codex-footer-same-row-prose')

    def test_claude_cannot_use_codex_ui_footer(self):
        self.assert_completion_block_pending('claude-codex-footer')

    def test_claude_native_ui_footer_allows_marker_completion(self):
        self.actor('claude-footer')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.observed()['exit_enters'], 1)

    def test_claude_verified_verb_minute_footer_allows_completion(self):
        self.actor('claude-footer-minute')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_cannot_use_claude_ui_footer(self):
        self.assert_completion_block_pending('done-claude-footer')

    def test_claude_ui_footer_extra_prose_is_pending(self):
        self.assert_completion_block_pending('claude-footer-extra-prose')

    def test_claude_ui_footer_same_row_prose_is_pending(self):
        self.assert_completion_block_pending('claude-footer-same-row-prose')

    def test_claude_ui_footer_partial_tokens_is_pending(self):
        self.assert_completion_block_pending('claude-footer-token-partial')

    def test_claude_ui_footer_unknown_verb_is_pending(self):
        self.assert_completion_block_pending('claude-footer-unknown-verb')

    def test_claude_ui_footer_later_assistant_is_pending(self):
        self.assert_completion_block_pending('claude-footer-later-assistant')

    def test_codex_marker_suffix_is_not_completion(self):
        self.assert_completion_block_pending('done-suffix')

    def test_claude_marker_suffix_is_not_completion(self):
        self.assert_completion_block_pending('claude-suffix')

    def test_codex_later_assistant_invalidates_marker(self):
        self.assert_completion_block_pending('done-later-assistant')

    def test_claude_later_assistant_invalidates_marker(self):
        self.assert_completion_block_pending('claude-later-assistant')

    def test_decline_suffix_is_not_disposition(self):
        self.assert_completion_block_pending('decline-suffix')

    def legacy_index(self):
        waiting = self.repo / 'waiting'
        waiting.mkdir(exist_ok=True)
        index = waiting / 'INDEX.md'
        text = '# Steward record\n\n| Legacy session | Anthropic | Utility | Waiting on the operator |\n'
        index.write_text(text)
        self.git('add', '--', 'waiting/INDEX.md')
        self.git('commit', '-m', 'legacy steward index')
        self.git('push')
        return index, text

    def test_index_preflight_failure_preserves_legacy_then_resumes(self):
        index, original = self.legacy_index()
        self.actor()
        before = '        result = run(command)\n'
        after = ('        if index and self.state.get("shard") and not self.args.resume:\n'
                 '            raise Stop("fixture-publication-precondition-failure")\n' + before)
        entry = self.instrument(before, after)
        with patch.dict(os.environ, {'RETIRE_TEST_SCRIPT': str(entry)}):
            result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('fixture-publication-precondition-failure', result.stderr)
        self.assertEqual(index.read_text(), original)
        path, state = self.state()
        self.assertEqual(state['disposition'], 'DONE')
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(index.read_text().startswith(original))
        self.assertIn('Steward record', self.git('show', 'origin/master:waiting/INDEX.md'))

    def test_own_legacy_index_write_recovers_after_commit_hook_failure(self):
        index, original = self.legacy_index()
        self.actor('commit-reject')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('private publication failed', result.stderr)
        self.assertEqual(index.read_text(), original)
        self.assertEqual(self.git('show', 'origin/master:waiting/INDEX.md'), original.strip())
        path, state = self.state()
        (self.repo / '.git' / 'hooks' / 'pre-commit').unlink()
        result = self.invoke('--resume', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(index.read_text(), original)
        self.assertIn('<!-- retire-agent:begin -->', self.git('show', 'origin/master:waiting/INDEX.md'))

    def test_foreign_json_metadata_is_not_claimed(self):
        index, original = self.legacy_index()
        files = {'list.md': '[]', 'foreign.md': '{"event":"foreign-owner","harness":[]}',
                 'unclaimed.md': json.dumps({'event': 'e' * 32, 'harness': []})}
        for name, content in files.items():
            (index.parent / name).write_text(content)
        other_receipt = self.repo / 'receipts' / ('e' * 32 + '.json')
        other_receipt.parent.mkdir(exist_ok=True)
        other_bytes = json.dumps({'event': 'e' * 32, 'status': 'pending-exit', 'shard': 'waiting/another-owner.md'})
        other_receipt.write_text(other_bytes)
        self.git('add', 'waiting', 'receipts')
        self.git('commit', '-m', 'foreign remote records')
        self.git('push')
        self.actor()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(index.read_text().startswith(original))
        self.assertEqual(other_receipt.read_text(), other_bytes)
        for name, content in files.items():
            self.assertEqual((index.parent / name).read_text(), content)
            self.assertNotIn('[' + name + ']', self.git('show', 'origin/master:waiting/INDEX.md'))

    def test_locally_deleted_index_is_not_recreated_in_shared_checkout(self):
        index, original = self.legacy_index()
        index.unlink()
        self.actor()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(index.exists())
        remote_index = self.git('show', 'origin/master:waiting/INDEX.md')
        self.assertTrue(remote_index.startswith(original))
        self.assertIn('retire-agent:begin', remote_index)
        self.assertTrue((self.directory / 'exit-order.json').exists())

    def test_padded_final_marker_completes(self):
        self.actor('padded-marker')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()[1]['disposition'], 'DONE')
        self.assertTrue(json.loads((self.directory / 'exit-order.json').read_text())['receipt_before_exit'])

    def test_wrong_blob_receipt_never_self_heals(self):
        self.actor('hold')
        self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        path, state = self.state()
        editor = self.remote_editor()
        canonical = editor / state['shard']
        verified = canonical.read_bytes()
        canonical.write_text('different shard bytes')
        self.editor_git(editor, 'add', '--', state['shard'])
        self.editor_git(editor, 'commit', '-m', 'fixture different shard snapshot')
        wrong_commit = self.editor_git(editor, 'rev-parse', 'HEAD')
        canonical.write_bytes(verified)
        receipt = self.staged(state, state['handoff_receipt'])
        data = json.loads(receipt.read_text())
        data['commit'] = wrong_commit
        receipt.write_text(json.dumps(data))
        (editor / state['handoff_receipt']).write_text(json.dumps(data))
        self.editor_git(editor, 'add', '--', state['shard'], state['handoff_receipt'])
        self.editor_git(editor, 'commit', '-m', 'fixture restored shard with wrong receipt')
        self.editor_git(editor, 'push', 'origin', 'HEAD:master')
        self.git('fetch', 'origin', 'master')
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        tampered = self.git('show', 'origin/master:' + state['handoff_receipt'])
        for _ in range(2):
            result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles), '--resume', str(path))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('private receipt commit contains different shard bytes', result.stderr)
            self.assertFalse((self.directory / 'spawn.json').exists())
            self.assertEqual(self.git('show', 'origin/master:' + state['handoff_receipt']), tampered)
            self.assertEqual(receipt.read_text(), json.dumps(data))

    def test_corrupt_other_receipt_preserves_generated_index(self):
        waiting = self.repo / 'waiting'
        waiting.mkdir()
        event = 'e' * 32
        shard = waiting / 'other.md'
        shard.write_text(json.dumps({'event': event, 'session_id': 'other-session', 'harness': 'claude', 'role': 'Utility'}))
        receipt = self.repo / 'receipts' / (event + '.json')
        receipt.parent.mkdir()
        receipt.write_text(json.dumps({'event': event, 'shard': 'waiting/other.md', 'status': 'pending-exit'}))
        self.git('add', '--', 'waiting', 'receipts')
        self.git('commit', '-m', 'fixture other owned record')
        self.git('push')
        self.actor('hold')
        self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles))
        path, state = self.state()
        remote_index = self.git('show', 'origin/master:waiting/INDEX.md')
        self.assertIn('[other.md]', remote_index)
        (self.directory / 'human-independent-exit').touch()
        self.wait_for(lambda: not Path('/proc/' + str(state['identity']['process']['pid'])).exists())
        editor = self.remote_editor()
        remote_receipt = editor / 'receipts' / (event + '.json')
        for malformed in ('not JSON', '[]', json.dumps({'status': 'retired'}), json.dumps({'event': [], 'status': 'retired'}), json.dumps({'event': 'f' * 32, 'status': 'retired', 'shard': 'waiting/other.md'})):
            remote_receipt.write_text(malformed)
            self.editor_git(editor, 'add', 'receipts/' + event + '.json')
            self.editor_git(editor, 'commit', '-m', 'malformed other receipt')
            self.editor_git(editor, 'push', 'origin', 'HEAD:master')
            for _ in range(2):
                result = self.invoke('--handoff', 'codex', 'model', '--roles', str(self.roles), '--resume', str(path))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('malformed retirement receipt', result.stderr)
                self.assertEqual(remote_receipt.read_text(), malformed)
                self.git('fetch', 'origin', 'master')
                self.assertEqual(self.git('show', 'origin/master:waiting/INDEX.md'), remote_index)
                self.assertFalse((self.directory / 'spawn.json').exists())


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--terminal':
        terminal(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
