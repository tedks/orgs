#!/usr/bin/env python3
"""Real tmux + a deterministic tiny TUI: bracketed paste, lost Enter, queue receipt.

No agent/model calls or installed changes. A unique private server is removed
in finally. Run this file directly; --terminal is only used inside that server.
"""
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys
import tempfile
import termios
import time
import tty
import uuid


def terminal(state):
    old = termios.tcgetattr(0)
    tty.setraw(0)
    draft = b''
    pending = b''
    pasting = False
    pastes = enters = 0
    history = ''
    def draw():
        collapsed = f'[Pasted Content {len(draft.decode(errors="replace"))} chars]' if draft else ''
        sys.stdout.write('\x1b[?2004h\x1b[2J\x1b[H' + history + '\r\n› ' + collapsed + '\r\n\r\n  Test model · branch\r\n')
        row = history.count('\n') + 2
        sys.stdout.write(f'\x1b[{row};{3 + len(collapsed)}H')
        sys.stdout.flush()
        Path(state).write_text(json.dumps({'pastes': pastes, 'enters': enters, 'accepted': bool(history)}))
    try:
        draw()
        while True:
            if not select.select([0], [], [], 5)[0]:
                continue
            pending += os.read(0, 65536)
            while pending:
                if pending.startswith(b'\x1b[200~'):
                    pastes += 1
                    pasting = True
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
                        if enters == 2:
                            text = draft.decode().replace('\n', '\r\n    ')
                            history = '• Messages to be submitted after next tool call\r\n  ↳ ' + text + '\r\n'
                            draft = b''
                    else:
                        draft += char
                draw()
    finally:
        termios.tcsetattr(0, termios.TCSADRAIN, old)


def test():
    label = 'message-test-' + uuid.uuid4().hex
    tmux = ['tmux', '-L', label]
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / 'state'
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), '--terminal', str(state)])
        try:
            pane = subprocess.check_output(tmux + ['new-session', '-d', '-P', '-F', '#{pane_id}', '-x', '90', '-y', '24', command], text=True).strip()
            deadline = time.monotonic() + 5
            while not state.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            env = dict(os.environ, SPAWN_TMUX_LABEL=label)
            env.pop('SPAWN_TMUX_SOCKET', None)
            result = subprocess.run([str(Path(__file__).with_name('tmux-message.sh')), 'send', pane,
                                     'Real tmux test\nActual message\nUnicode λ'], env=env,
                                    text=True, capture_output=True, timeout=35)
            assert result.returncode == 0, result.stderr
            report = json.loads(result.stdout)
            assert report['receipt'] == 'queued', (report, result.stderr)
            observed = json.loads(state.read_text())
            assert observed == {'pastes': 1, 'enters': 2, 'accepted': True}, observed
            print('PASS: private real tmux, collapsed paste, swallowed Enter, queued receipt, one paste/two Enters')
        finally:
            subprocess.run(tmux + ['kill-server'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--terminal': terminal(sys.argv[2])
    else: test()
