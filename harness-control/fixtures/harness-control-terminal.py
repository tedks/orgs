#!/usr/bin/env python3
"""Disposable deterministic TUI; never launches an AI harness or reads its data."""
import ctypes
import json
import os
from pathlib import Path
import select
import sys
import termios
import time
import tty

root = Path(sys.argv[1])
ctypes.CDLL(None).prctl(15, b'claude', 0, 0, 0)
old = termios.tcgetattr(0)
tty.setraw(0)
draft = b''
pending = b''
pasting = False
accepted = []
pastes = 0
exit_at = None
compact_at = None
compacted_at = time.time()  # existing marker will be replaced at equal visible count
continuation_at = None
turn_at = None
parent_uuid = None
native_index = 0


def native_row(kind, **fields):
    global parent_uuid, native_index
    native_index += 1
    uid = 'fixture-' + str(native_index)
    row = {'type': kind, 'uuid': uid, 'parentUuid': parent_uuid,
           'sessionId': '12345678-1234-1234-1234-123456789abc', 'isSidechain': False, **fields}
    with (root / 'transcript.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row) + '\n')
    parent_uuid = uid


def finish_turn():
    native_row('assistant', message={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'fixture done'}]})
    native_row('system', subtype='turn_duration', durationMs=1000, messageCount=2)


def draw():
    history = ''.join('› ' + (text if len(text) < 60 else f'[Pasted Content {len(text)} chars]') + '\r\n\r\n' for text in accepted)
    if compacted_at is not None:
        history += '  ⎿  Compacted (ctrl+o to see full summary)\r\n'
    if compact_at is not None:
        history += '✢ Compacting conversation… (0s)\r\n'
    value = draft.decode('utf-8', errors='replace')
    if len(value) >= 60:
        value = f'[Pasted Content {len(value)} chars]'
    sys.stdout.write('\x1b[?2004h\x1b[2J\x1b[H' + history + '› ' + value + '\r\n\r\n  Fixture · branch\r\n')
    row = history.count('\n') + 1
    sys.stdout.write(f'\x1b[{row};{3 + len(value)}H')
    sys.stdout.flush()
    temporary = root / 'terminal.tmp'
    temporary.write_text(json.dumps({'pid': os.getpid(), 'accepted': accepted, 'pastes': pastes, 'compacted_at': compacted_at, 'continuation_at': continuation_at}))
    temporary.replace(root / 'terminal.json')


try:
    sys.stdout.write('\x1b[?1049h')  # match Claude's zero-history alternate screen
    sys.stdout.flush()
    native_row('user', message={'content': 'fixture startup'})
    finish_turn()
    draw()
    while exit_at is None or time.monotonic() < exit_at:
        if turn_at is not None and time.monotonic() >= turn_at:
            turn_at = None
            finish_turn()
        if compact_at is not None and time.monotonic() >= compact_at:
            compact_at = None
            compacted_at = time.time()
            native_row('system', subtype='compact_boundary')
            draw()
        if not select.select([0], [], [], .05)[0]:
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
                    text = draft.decode()
                    accepted.append(text)
                    draft = b''
                    if text == '/compact':
                        compact_at = time.monotonic() + 3
                    if not text.startswith('/'):
                        native_row('user', message={'content': text})
                        turn_at = time.monotonic() + 1
                    if text.startswith('CONTINUE:'):
                        continuation_at = time.time()
                    if text == '/exit':
                        exit_at = time.monotonic() + .75
                else:
                    draft += char
            draw()
finally:
    sys.stdout.write('\x1b[?1049l')
    sys.stdout.flush()
    termios.tcsetattr(0, termios.TCSADRAIN, old)
