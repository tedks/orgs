#!/usr/bin/env python3
"""Disposable tmux + real /proc + MCP stdio status gates. No model is run.

Run inside the repository Nix check.
Requires Linux, tmux, and the locally cached MCP dependency. Each test uses a
private HOME/socket and a Python process named claude/codex as the stand-in.
This pins transport/identity integration, not compatibility with a real CLI.
"""
import asyncio
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

MODULES = Path(__file__).resolve().parent
SERVER = Path(os.environ.get('HARNESS_LIVE_TEST_SERVER', MODULES / 'server.py'))
SID = '11111111-1111-1111-1111-111111111111'
SECRET = 'synthetic-private-conversation'


async def observe(harness, home):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # The name and environment belong to THIS ancestor, not an arbitrary sibling.
    if ctypes.CDLL(None, use_errno=True).prctl(15, harness.encode(), 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'prctl(PR_SET_NAME)')
    pid = os.getpid()
    now = time.time()
    held_rollout = None
    if harness == 'claude':
        state = home / '.claude/session-state'
        state.mkdir(parents=True)
        start = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        (state / f'current.{pid}').write_text(f'{SID} {start} {boot}')
        (state / f'{SID}.status.json').write_text(json.dumps({
            'schema_version': 1, 'session_id': SID, 'observed_at': now,
            'cwd': str(home), 'transcript_path': SECRET,
            'model': {'id': 'synthetic-model'},
            'context_window': {'remaining_percentage': 42},
            'rate_limits': {'five_hour': {'used_percentage': 25, 'resets_at': now + 3600}},
        }))
    else:
        sessions = home / '.codex/sessions'
        sessions.mkdir(parents=True)
        path = sessions / f'rollout-synthetic-{SID}.jsonl'
        stamp = datetime.now(timezone.utc).isoformat()
        records = [
            ('session_meta', {'id': SID, 'source': 'cli', 'cwd': str(home), 'model_provider': 'synthetic'}),
            ('turn_context', {'model': 'synthetic-model', 'cwd': str(home)}),
            ('event_msg', {'type': 'token_count', 'info': {'total_token_usage': {'total_tokens': 123}},
                           'rate_limits': {'limit_id': 'synthetic-quota', 'primary': {
                               'used_percent': 25, 'window_minutes': 300, 'resets_at': int(now) + 3600}}}),
            ('response_item', {'type': 'message', 'content': SECRET}),
        ]
        path.write_text(''.join(json.dumps({'timestamp': stamp, 'type': kind, 'payload': payload}) + '\n'
                                for kind, payload in records))
        held_rollout = path.open('ab')
    # Codex passes only its standard environment allowlist to MCP children.
    # Ancestry must recover TMUX/TMUX_PANE and home from the pinned harness.
    inherited = {key: value for key, value in os.environ.items()
                 if key in ('HOME', 'LOGNAME', 'PATH', 'SHELL', 'USER', 'LANG', 'LC_ALL', 'TERM', 'TMPDIR', 'TZ')}
    env = {**inherited, 'PYTHONPATH': str(MODULES), 'PYTHONDONTWRITEBYTECODE': '1',
           'AGENT_SKILLS_ROOT': os.environ['AGENT_SKILLS_ROOT'],
           'CLAUDE_SESSION_ID': 'wrong-inherited-id', 'CODEX_THREAD_ID': 'wrong-inherited-id'}
    try:
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert {'get_status', 'get_usage'} <= names, names
                async def call(name):
                    result = await client.call_tool(name, {})
                    assert not result.isError, result
                    return json.loads(next(item.text for item in result.content if item.type == 'text'))
                status = await call('get_status')
                usage = await call('get_usage')
                again = await call('get_status')
        return {'status': status, 'usage': usage, 'again': again,
                'expected': {'pid': pid, 'pane': os.environ['TMUX_PANE'],
                             'socket': os.environ['TMUX'].rsplit(',', 2)[0], 'cwd': str(home)}}
    finally:
        if held_rollout:
            held_rollout.close()


class LiveTests(unittest.TestCase):
    def run_harness(self, harness):
        self.assertTrue(sys.platform.startswith('linux'), 'Linux /proc required')
        self.assertIsNotNone(shutil.which('tmux'), 'tmux required')
        with tempfile.TemporaryDirectory(prefix='harness-status-') as directory:
            home = Path(directory)
            socket = str(home / 'tmux.sock')
            env = {key: value for key, value in os.environ.items() if key not in ('TMUX', 'TMUX_PANE', 'CODEX_HOME')}
            command = shlex.join(['env', f'HOME={home}', sys.executable, str(Path(__file__).resolve()),
                                  '--stand-in', harness, str(home)])
            tmux = ['tmux', '-S', socket, '-f', '/dev/null']
            try:
                subprocess.run([*tmux, 'new-session', '-d', '-s', 'synthetic', '-c', str(home), command],
                               env=env, capture_output=True, text=True, check=True, timeout=10)
                deadline = time.monotonic() + 25
                result = home / 'result.json'
                while not result.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(result.exists(), 'stand-in produced no result within 25 seconds')
                data = json.loads(result.read_text())
                self.assertNotIn('error', data, data)
            finally:
                subprocess.run([*tmux, 'kill-server'], env=env, capture_output=True, timeout=10)
            status, usage = data['status'], data['usage']
            self.assertIn('identity', status, status)
            identity = status['identity']
            self.assertEqual(identity['harness'], harness)
            for key, value in data['expected'].items():
                self.assertEqual(identity[key], value)
            self.assertEqual(data['again']['identity'], identity)
            self.assertTrue(identity['starttime'].isdigit())
            self.assertTrue(identity['boot_id'])
            self.assertNotIn(SECRET, json.dumps(data))
            self.assertNotIn('rollout_path', status['observation'])
            self.assertNotIn('rollout_path', usage)
            self.assertEqual(status['observation'].get('session_id'), SID)
            if harness == 'codex':
                self.assertEqual(usage.get('session_id'), SID)
            return status['observation'], usage

    def test_claude(self):
        status, usage = self.run_harness('claude')
        self.assertEqual(status['model']['id'], 'synthetic-model')
        self.assertEqual(status['context_window']['remaining_percentage'], 42)
        self.assertEqual(usage['state'], 'available')
        self.assertEqual(usage['windows'][0]['remaining_percentage'], 75)

    def test_codex(self):
        status, usage = self.run_harness('codex')
        self.assertEqual(status['model'], 'synthetic-model')
        self.assertEqual(status['token_usage']['total']['total_tokens'], 123)
        self.assertIsNone(status['context_remaining'])
        self.assertEqual(status['context_remaining_state'], 'unsupported')
        self.assertEqual(usage['quota_buckets']['synthetic-quota']['primary']['remaining_percent'], 75)


MUTANTS = {
    'test_claude': ('state = parse_claude_status(snapshot, sid)',
                    'state = parse_claude_status(snapshot, sid); state["context_window"]["remaining_percentage"] = 0'),
    'test_codex': ("state.pop('rollout_path', None)", 'pass'),
}


def mutation_check():
    subprocess.run([sys.executable, __file__], check=True, timeout=90)
    if set(unittest.defaultTestLoader.getTestCaseNames(LiveTests)) != set(MUTANTS):
        raise RuntimeError('Every behavior test needs a mutation check')
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        for test, (old, new) in MUTANTS.items():
            source = SERVER.read_text()
            if source.count(old) != 1:
                raise RuntimeError(f'Mutation anchor drift: {test}')
            target = Path(directory) / f'{test}.py'
            changed = source.replace(old, new)
            compile(changed, str(target), 'exec')
            target.write_text(changed)
            env = {**os.environ, 'HARNESS_LIVE_TEST_SERVER': str(target), 'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, __file__, f'LiveTests.{test}'],
                                    env=env, text=True, capture_output=True, timeout=40)
            killed = result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr
            print(f"{'KILLED' if killed else 'SURVIVED'} LiveTests.{test}")
            if not killed:
                failures.append(test)
                print(result.stdout + result.stderr)
    return bool(failures)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--stand-in']:
        home = Path(sys.argv[3])
        try:
            data = asyncio.run(asyncio.wait_for(observe(sys.argv[2], home), timeout=20))
        except BaseException as exc:
            data = {'error': f'{type(exc).__name__}: {exc}'}
        pending = home / 'result.tmp'
        pending.write_text(json.dumps(data))
        pending.replace(home / 'result.json')
    elif sys.argv[1:] == ['--mutation-check']:
        raise SystemExit(mutation_check())
    else:
        unittest.main()
