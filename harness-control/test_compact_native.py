#!/usr/bin/env python3
"""Opt-in compaction rehearsal on an owned tmux server with real harnesses.

Uses model tokens. The disposable Git repository has no remote. The test retains
its private report and kills only the tmux server it created, even on failure.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
import harness_control
from harness_control import HarnessControl, TERMINAL
from harness_identity import discover
from session_binding import observe_native_session

HERE = Path(__file__).resolve().parent
SPAWN = HERE.parent / 'skills/spawn-agent/scripts/agent-spawn.sh'
MESSAGE = HERE.parent / 'skills/spawn-agent/scripts/tmux-message.sh'


def run(command, *, env=None, timeout=120, check=True):
    result = subprocess.run([str(arg) for arg in command], env=env, text=True,
                            capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{command[0]} failed ({result.returncode}): {result.stderr[-1000:]}')
    return result


def harness_pid(root):
    """Find one native harness in the descendants of this owned pane process."""
    root_comm = Path(f'/proc/{root}/comm').read_text().strip()
    if root_comm in ('claude', 'codex') or re.fullmatch(r'(?:claude|codex)-[0-9].*', root_comm):
        return root
    rows = run(['ps', '-eo', 'pid=,ppid=,comm=']).stdout.splitlines()
    processes = [line.strip().split(None, 2) for line in rows]
    children = {}
    for pid, parent, comm in processes:
        children.setdefault(int(parent), []).append((int(pid), comm))
    found, pending = [], [root]
    while pending:
        for pid, comm in children.get(pending.pop(), []):
            pending.append(pid)
            if comm in ('claude', 'codex') or re.fullmatch(r'(?:claude|codex)-[0-9].*', comm):
                found.append(pid)
    if len(found) != 1:
        raise RuntimeError(f'expected one native process under owned pane, found {len(found)}')
    return found[0]


def wait_until(predicate, seconds, label):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.5)
    raise RuntimeError('timed out waiting for ' + label)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', choices=('both', 'claude', 'codex'), default='both')
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='hcompact-native-', dir=Path.home() / '.local/state'))
    root.chmod(0o700)
    socket = root / 'tmux.sock'
    tmux = ['tmux', '-S', socket, '-f', '/dev/null']
    repo = root / 'repo'
    repo.mkdir()
    run(['git', '-C', repo, 'init', '-qb', 'master'])
    run(['git', '-C', repo, 'config', 'user.name', 'Compact native test'])
    run(['git', '-C', repo, 'config', 'user.email', 'test@example.invalid'])
    shard = repo / 'handoff.md'
    shard.write_text('Disposable compaction checkpoint. No product work.\n')
    run(['git', '-C', repo, 'add', 'handoff.md'])
    run(['git', '-C', repo, 'commit', '-qm', 'Disposable checkpoint'])
    commit = run(['git', '-C', repo, 'rev-parse', 'HEAD']).stdout.strip()
    report = {'root': str(root), 'results': [], 'server_released': False}
    environment = {**os.environ, 'SPAWN_TMUX_SOCKET': str(socket)}
    real_popen = subprocess.Popen
    def hold_observer(command, *args, **kwargs):
        if '--observe' in command:
            return SimpleNamespace(pid=os.getpid())
        return real_popen(command, *args, **kwargs)
    created = False
    try:
        run([*tmux, 'new-session', '-d', '-s', 'compact-native', '-x', '240', '-y', '60'])
        created = True
        run([*tmux, 'set-option', '-g', 'history-limit', '10000'])
        for harness, model in (('claude', 'haiku'), ('codex', 'gpt-6-luna')):
            if args.harness not in ('both', harness):
                continue
            prompt = ('Disposable harness compaction test. Make no file changes, run no commands, '
                      'and control no other pane. Reply exactly NATIVE-COMPACT-READY. '
                      'For a later focus or continuation message, reply briefly and make no changes.')
            prompt_file = root / (harness + '-prompt.txt')
            prompt_file.write_text(prompt)
            if harness == 'codex':
                trust = 'projects={' + json.dumps(str(repo)) + '={trust_level="trusted"}}'
                command = 'exec ' + shlex.join([shutil.which('codex'), '--no-alt-screen',
                    '-c', 'check_for_update_on_startup=false', '-c', trust, '-m', model])
                pane = run([*tmux, 'new-window', '-d', '-P', '-F', '#{pane_id}',
                            '-t', 'compact-native', '-n', harness, '-c', repo, command]).stdout.strip()
                launch = None
                time.sleep(5)
            else:
                launch_args = [SPAWN, f'compact-native:{harness}', harness, repo,
                               '--model', model, '--trust', '--prompt-file', prompt_file]
                launch = run(launch_args, env=environment, timeout=120, check=False)
                pane = run([*tmux, 'list-panes', '-t', f'compact-native:{harness}', '-F', '#{pane_id}']).stdout.strip()
            if not re.fullmatch(r'%[0-9]+', pane):
                raise RuntimeError('owned pane was not unique')
            if launch is None:
                run([MESSAGE, 'send', pane, '--prompt-file', prompt_file,
                     '--backoff', '--max-wait', '60'], env=environment, timeout=120)
            elif launch.returncode:
                try:
                    receipt = json.loads(launch.stderr.splitlines()[0])
                except (ValueError, IndexError):
                    raise RuntimeError('launcher failed without a parseable transport result')
                if (receipt.get('status') != 'deferred' or receipt.get('input_attempted') is not False or
                        receipt.get('pane') != pane):
                    raise RuntimeError('launcher delivery needs review; retained native pane was not retried')
                time.sleep(5)
                run([MESSAGE, 'send', pane, '--prompt-file', prompt_file,
                     '--backoff', '--max-wait', '60'], env=environment, timeout=120)
            def screen():
                return run([*tmux, 'capture-pane', '-p', '-J', '-t', pane]).stdout
            wait_until(lambda: re.search(r'[●•] NATIVE-COMPACT-READY\b', screen()),
                       180, harness + ' ready reply')
            pane_pid = int(run([*tmux, 'display-message', '-p', '-t', pane, '#{pane_pid}']).stdout)
            identity = discover(harness_pid(pane_pid))
            if identity.harness != harness or identity.pane != pane or identity.socket != str(socket):
                raise RuntimeError('native identity does not belong to disposable pane')
            if harness == 'codex':
                proof = wait_until(lambda: (candidate if candidate.get('state') == 'observed' else None)
                                   if (candidate := observe_native_session(harness, identity)) else None,
                                   30, harness + ' session binding')
                sid = proof['session_id']
                transcript = Path(proof['transcript_path'])
                pointer_dir = None
            else:
                env = dict(item.split(b'=', 1) for item in Path(f'/proc/{identity.pid}/environ').read_bytes().split(b'\0') if b'=' in item)
                config = Path(env.get(b'CLAUDE_CONFIG_DIR', env[b'HOME'] + b'/.claude').decode())
                key = re.sub(r'[^a-zA-Z0-9]', '-', str(repo))
                project = config / 'projects' / key
                def native_transcript():
                    candidates = list(project.glob('*.jsonl')) if project.is_dir() else []
                    return candidates[0] if len(candidates) == 1 else None
                transcript = wait_until(native_transcript, 30, 'unique Claude transcript')
                with transcript.open() as stream:
                    rows = [json.loads(line) for line in stream if line.endswith('\n')]
                sessions = {row.get('sessionId') for row in rows if row.get('cwd') == str(repo) and row.get('sessionId')}
                if len(sessions) != 1 or transcript.stem not in sessions:
                    raise RuntimeError('Claude transcript session/cwd identity is not unique')
                sid = transcript.stem
                pointer_dir = root / 'claude-state'
                pointer_dir.mkdir()
                (pointer_dir / f'current.{identity.pid}').write_text(f'{sid} {identity.starttime} {identity.boot_id}')
            if not transcript.is_file():
                raise RuntimeError('native transcript unavailable')
            control = HarnessControl(identity, sid, transcript, root / (harness + '-control-records'),
                                     claude_state_dir=pointer_dir)
            receipt = control.record_checkpoint({
                'shard_path': str(shard), 'repo_path': str(repo),
                'sha256': hashlib.sha256(shard.read_bytes()).hexdigest(), 'commit': commit,
                'private_storage_attested': True, 'push_attestation': 'no_remote_configured',
                'authority': 'compact_authorized', 'resources_disposition': 'active_recorded',
                'obligations_preserved': True, 'pause_state_preserved': True,
                'pause_state_reference': 'handoff.md', 'active_inventory_reference': 'handoff.md',
            })['receipt_id']
            operation = control.request('compact', receipt, timeout_seconds=180,
                focus='Disposable focus: please finish this turn without file changes.',
                continuation='Disposable continuation: reply NATIVE-COMPACT-CONTINUED without file changes.')
            if operation['state'] != 'scheduled' or not isinstance(operation.get('watcher_pid'), int):
                raise RuntimeError('watcher was not scheduled with a PID')
            result = wait_until(lambda: (current if current['state'] in TERMINAL else None)
                                if (current := control.operation(operation['operation_id'])) else None,
                                300, harness + ' compact operation')
            report['results'].append({'harness': harness, 'pane': pane, 'operation_id': operation['operation_id'],
                                      'state': result['state'], 'delivery': result['delivery']['state'],
                                      'completion': result['completion']['state'],
                                      'continuation': result['continuation']['state'],
                                      'failure_notice': (result.get('failure_notice') or {}).get('state'),
                                      'watcher_pid': operation['watcher_pid']})
            if (result['state'] != 'completed' or result['delivery']['state'] != 'delivered' or
                    result['completion']['state'] != 'confirmed' or result['continuation']['state'] != 'delivered'):
                raise RuntimeError(harness + ' compact did not complete; inspect retained report and operation')
            wait_until(lambda: re.search(r'[●•] NATIVE-COMPACT-CONTINUED\b', screen()), 120,
                       harness + ' continuation reply')
            print(harness + ': native compact and continuation confirmed', flush=True)
            # Hold only the second observer launch. The first operation above
            # exercised the real detached watcher; this barrier makes a native
            # intervening message deterministic without touching another pane.
            with patch.object(harness_control.subprocess, 'Popen', side_effect=hold_observer):
                interrupted = control.request('compact', receipt, timeout_seconds=180)
            if interrupted['state'] != 'scheduled':
                raise RuntimeError(harness + ' intervening operation was not scheduled')
            intervening_file = root / (harness + '-intervening.txt')
            intervening_file.write_text('Disposable operator update: reply NATIVE-INTERVENING-READY. Make no file changes.')
            run([MESSAGE, 'send', pane, '--prompt-file', intervening_file,
                 '--backoff', '--max-wait', '60'], env=environment, timeout=120)
            wait_until(lambda: re.search(r'[●•] NATIVE-INTERVENING-READY\b', screen()), 180,
                       harness + ' intervening reply')
            harness_control.observe(control.directory, interrupted['operation_id'])
            cancelled = control.operation(interrupted['operation_id'])
            if (cancelled['state'] != 'cancelled' or cancelled['reason'] != 'intervening_turn' or
                    cancelled['delivery']['state'] != 'not_dispatched' or
                    (cancelled.get('failure_notice') or {}).get('state') != 'delivered'):
                raise RuntimeError(harness + ' intervening message did not settle cancellation')
            with patch.object(harness_control.subprocess, 'Popen', side_effect=hold_observer):
                replacement = control.request('compact', receipt, timeout_seconds=180)
            if replacement['state'] != 'scheduled' or control.cancel(replacement['operation_id'])['state'] != 'cancelled':
                raise RuntimeError(harness + ' refused a new compact after cancellation')
            report['results'].append({'harness': harness, 'intervening_state': cancelled['state'],
                                      'notice': cancelled['failure_notice']['state'],
                                      'replacement_state': replacement['state']})
            print(harness + ': intervening message cancelled; replacement accepted', flush=True)
    finally:
        if created:
            listed = run([*tmux, 'list-panes', '-a', '-F', '#{pane_id} #{pane_pid} #{pane_current_command}'], check=False)
            (root / 'panes.txt').write_text(listed.stdout + listed.stderr)
            for item in listed.stdout.splitlines():
                pane_id = item.split()[0]
                if re.fullmatch(r'%[0-9]+', pane_id):
                    capture = run([*tmux, 'capture-pane', '-p', '-e', '-J', '-S', '-', '-t', pane_id], check=False)
                    (root / ('pane-' + pane_id[1:] + '.txt')).write_text(capture.stdout + capture.stderr)
            run([*tmux, 'kill-server'], check=False)
        report['server_released'] = run([*tmux, 'list-sessions'], check=False).returncode != 0
        report['repo_status'] = run(['git', '-C', repo, 'status', '--porcelain=v1']).stdout
        (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print('Native evidence: ' + str(root / 'report.json'), flush=True)
        if not report['server_released'] or report['repo_status']:
            raise RuntimeError('disposable resource or repository cleanup failed')


if __name__ == '__main__':
    main()
