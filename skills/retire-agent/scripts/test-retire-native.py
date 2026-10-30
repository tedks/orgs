#!/usr/bin/env python3
"""Opt-in real Codex/Claude retirement, using only an owned tmux server/local Git.

Uses model tokens. Pass a clean, dedicated disposable Git directory and private
evidence directory. The controller uses only its own server/local Git; real
agents retain normal host access, so containment is an authority boundary, not
an OS sandbox. Artifacts are retained for inspection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
import retire

HERE = Path(__file__).resolve().parent


def run(command, env=None, timeout=120):
    return subprocess.run([str(item) for item in command], env=env, text=True,
                          capture_output=True, timeout=timeout)


def require(result):
    if result.returncode:
        raise RuntimeError(f'command failed ({result.returncode}): {result.stderr}')
    return result.stdout.strip()


def fingerprint(directory, owned=False):
    def git(*args):
        return require(run(['git', '-C', directory, *args]))
    diff = git('diff', '--binary', 'HEAD', '--')
    return {'head': git('rev-parse', 'HEAD'), 'status': git('status', '--porcelain=v1', '--untracked-files=all', *(['--ignored'] if owned else [])),
            'refs': git('for-each-ref', '--format=%(refname) %(objectname)') if owned else None,
            'tracked_diff_sha256': hashlib.sha256(diff.encode()).hexdigest()}


def interrupted(signum, _frame):
    raise SystemExit(128 + signum)


def main():
    if not __debug__:
        raise RuntimeError('native verification requires Python assertions enabled')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--shared-skill', type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true', help='read-only cwd/containment validation; never launch models or create evidence')
    parser.add_argument('--baseline-script', type=Path)
    parser.add_argument('--stale-offer-draft', action='store_true', help='exercise shared sender stable draft co-submission')
    parser.add_argument('--harness', choices=['both', 'codex', 'claude'], default='both', help='independent native diagnosis; acceptance defaults to both')
    parser.add_argument('--codex-model', default='gpt-6-luna')
    parser.add_argument('--claude-model', default='haiku')
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    source_root = HERE.parents[2]
    top = Path(require(run(['git', '-C', worktree, 'rev-parse', '--show-toplevel']))).resolve()
    if top == source_root or source_root in top.parents or top in source_root.parents or top != worktree:
        parser.error('--worktree must be the top of an exclusively owned disposable Git directory, separate from source')
    def common(directory):
        return Path(require(run(['git', '-C', directory, 'rev-parse', '--path-format=absolute', '--git-common-dir']))).resolve()
    if common(worktree) == common(source_root) or require(run(['git', '-C', worktree, 'remote'])):
        parser.error('disposable cwd must have a separate Git common directory and no remotes')
    worktree_before = fingerprint(worktree, owned=True)
    if worktree_before['status']:
        parser.error('disposable worktree must start clean')
    directory = args.evidence.resolve()
    if directory == worktree or worktree in directory.parents or directory == source_root or source_root in directory.parents:
        parser.error('evidence must be separate from disposable cwd and source')
    if args.preflight_only:
        return
    selected = [name for name in ('codex', 'claude') if args.harness in ('both', name)]
    binaries = {name: shutil.which(name) for name in selected}
    if not all(binaries.values()):
        parser.error('required native binary unavailable: ' + ', '.join(name for name, path in binaries.items() if not path))
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    real_codex = Path(binaries['codex']).resolve() if 'codex' in binaries else None
    trust_override = 'projects={' + json.dumps(str(worktree)) + '={trust_level="trusted"}}'
    codex_wrapper = directory / 'codex-exact-cwd'
    if real_codex:
        codex_wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(str(real_codex)) + ' -c ' + shlex.quote(trust_override) + ' "$@"\n')
        codex_wrapper.chmod(0o700)
    repo = directory / 'repo'
    remote = directory / 'remote.git'
    require(run(['git', 'init', '--bare', remote]))
    require(run(['git', 'init', '-b', 'master', repo]))
    def git(*command):
        return require(run(['git', '-C', repo, *command]))
    git('config', 'user.name', 'Retirement rehearsal')
    git('config', 'user.email', 'retirement-test@example.invalid')
    (repo / 'seed').write_text('Disposable private test only.\n')
    git('add', 'seed')
    git('commit', '-m', 'Seed disposable retirement test')
    git('remote', 'add', 'origin', str(remote))
    git('push', '-u', 'origin', 'master')
    checker = directory / 'private-check'
    checker.write_text('#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = ' + shlex.quote(str(remote)) +
                       ' ] && [ "$(git --git-dir="$1" rev-parse --is-bare-repository)" = true ]\n')
    checker.chmod(0o700)
    records = repo / '.git' / 'retirements'
    records.mkdir(mode=0o700)
    foreign = records / 'lane-v-private-publication.json'
    foreign_bytes = b'{"blob":"foreign","private_remote":true,"session_id":"unrelated"}\n'
    foreign.write_bytes(foreign_bytes)
    label = 'retire-native-' + uuid.uuid4().hex
    tmux = ['tmux', '-L', label]
    environment = dict(os.environ, SPAWN_TMUX_LABEL=label, RETIRE_REPO=str(repo),
                       RETIRE_PRIVATE_CHECK=str(checker), RETIRE_SPAWN_SKILL=str(args.shared_skill.resolve()))
    environment.pop('CODEX_SESSION_ID', None)
    environment.pop('TMUX', None)
    environment.pop('SPAWN_TMUX_SOCKET', None)
    report = {'selected_harness': args.harness, 'combined_acceptance': args.harness == 'both',
              'baseline': 'planned' if args.baseline_script and args.harness != 'claude' else 'skipped', 'label': label, 'results': [], 'resources_released': False,
              'models': {'codex': args.codex_model, 'claude': args.claude_model},
              'worktree_before': worktree_before, 'source_fidelity': fingerprint(source_root),
              'shared_fidelity': fingerprint(args.shared_skill),
              'claude_trust_planned': str(worktree),
              'codex_per_process_trust': trust_override if real_codex else None, 'real_codex': str(real_codex) if real_codex else None,
              'containment_limit': 'worktree HEAD/status/tracked diff checks do not prove absence of writes elsewhere; agents retain normal host access'}
    server_creation_attempted = False
    failed = False
    try:
        assert run([*tmux, 'list-sessions']).returncode != 0, 'unique owned server label already exists'
        server_creation_attempted = True  # Cleanup owns this unique creation even if its return is interrupted.
        require(run([*tmux, 'new-session', '-d', '-s', 'retire-native', '-x', '240', '-y', '60'], env=environment))
        require(run([*tmux, 'set-option', '-g', 'history-limit', '10000']))
        require(run([*tmux, 'set-option', '-g', 'remain-on-exit', 'on']))
        report['shared_head'] = require(run(['git', '-C', args.shared_skill, 'rev-parse', 'HEAD']))
        report['versions'] = {name: require(run([name, '--version'])) for name in selected}
        (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        for harness, model in [('codex', args.codex_model), ('claude', args.claude_model)]:
            if args.harness not in ('both', harness):
                continue
            launcher = args.shared_skill / 'scripts' / 'agent-spawn.sh'
            native_context = directory / (harness + '-native-session.json')
            prompt = (f'This is an authorized disposable retirement rehearsal, launched as {harness} with model {model}. '
                      'You own no product work or processes. No live off-duty or ditz publication, other pane control, or writes outside assigned identity/shard files are authorized. Before READY, establish your actual provider-native session ID: '
                      'Codex can inspect CODEX_SESSION_ID; Claude can use harness-control get_session_info or get_status native session metadata. '
                      f'Write a JSON object with session_id, model, and evidence_source to {native_context}. '
                      'Never use unknown or invent an ID; if unavailable, reply RETIRE-NATIVE-SETUP-BLOCKED. '
                      'On the next retirement offer, use that verified context and write only its assigned private shard; '
                      'do not change or commit this working tree. The controller alone commits and pushes the shard '
                      'to its isolated local bare remote. After setup your entire final reply must be RETIRE-NATIVE-READY.')
            launched = run([launcher, 'retire-native:' + harness, harness, args.worktree.resolve(),
                            '--model', model, *(['--trust'] if harness == 'claude' else ['--codex-bin', codex_wrapper]), prompt], env=environment)
            if harness == 'claude':
                report['claude_trust_invoked'] = str(worktree)  # Published --trust persists this exact-dir grant.
            (directory / (harness + '-launch.txt')).write_text(launched.stdout + launched.stderr)
            require(launched)
            rows = require(run([*tmux, 'list-panes', '-t', 'retire-native:' + harness, '-F', '#{pane_id}'])).splitlines()
            assert len(rows) == 1, rows
            pane = rows[0]
            # Initial assignment must finish before the marker-only retirement response.
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                screen = require(run([*tmux, 'capture-pane', '-p', '-t', pane]))
                if re.search(r'[●•] RETIRE-NATIVE-SETUP-BLOCKED', screen):
                    raise AssertionError('native harness cannot establish its real session ID')
                if re.search(r'[●•] RETIRE-NATIVE-READY', screen):
                    break
                time.sleep(1)
            else:
                raise AssertionError('initial real harness task did not finish')
            context = json.loads(native_context.read_text())
            assert re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', context['session_id'])
            assert context.get('evidence_source'), 'native session identity has no provenance'
            # Constructor/import are inert; isolate env and pin before read-only identity IO.
            with patch.dict(os.environ, environment, clear=True):
                observer = retire.Retirement(SimpleNamespace(pane=pane))
                observer.tmux = tmux
                identity = observer.identity()
            assert identity['process']['agent'] == harness, 'native harness identity not established'
            observer.state = {'identity': identity}
            proof = observer.verify_native_session(context['session_id'])
            context['controller_identity_proof'] = ((proof.get('observation') or {}).get('rollout_path')
                                                    or proof.get('pointer_paths'))
            # Native process binding, not cwd or an inherited UUID, establishes
            # identity. Transcript crosscheck reads only this exact owned file.
            pinned = (identity['process'].get('cores') or [identity['process']])[0]
            if harness == 'codex':
                assert (proof.get('observation') or {}).get('cwd') == str(worktree), 'owned rollout cwd differs'
            else:
                env = dict(item.split(b'=', 1) for item in Path(f"/proc/{pinned['pid']}/environ").read_bytes().split(b'\0') if b'=' in item)
                config = Path(env[b'CLAUDE_CONFIG_DIR'].decode()) if env.get(b'CLAUDE_CONFIG_DIR') else Path(env[b'HOME'].decode()) / '.claude'
                project_key = re.sub(r'[^a-zA-Z0-9]', '-', str(worktree))
                transcript = config / 'projects' / project_key / (context['session_id'] + '.jsonl')
                matching = False
                with transcript.open() as stream:
                    for line in stream:
                        if not line.endswith('\n'):
                            continue  # A concurrent trailing write is not committed metadata.
                        record = json.loads(line)
                        if record.get('sessionId') == context['session_id'] and record.get('cwd') == str(worktree):
                            matching = True
                            break
                assert matching, 'owned Claude transcript session/cwd metadata differs'
                context['controller_transcript_proof'] = str(transcript)
            native_context.write_text(json.dumps(context, indent=2) + '\n')
            (directory / (harness + '-identity.json')).write_text(json.dumps(identity, indent=2))
            if harness == 'codex' and args.baseline_script:
                red = run([args.baseline_script.resolve(), pane, '--retire', '--wait', '1', '--poll', '.2'], env=environment)
                (directory / 'baseline-red.json').write_text(json.dumps({'returncode': red.returncode, 'stdout': red.stdout, 'stderr': red.stderr}, indent=2))
                assert red.returncode == 2 and 'malformed retirement state field: id' in red.stderr, red.stderr
                assert foreign.read_bytes() == foreign_bytes
                assert not list(records.glob('*-offer.txt')), 'baseline sent an offer before failing'
                assert not [path for path in records.glob('*.json') if re.fullmatch(r'[0-9a-f]{32}', path.stem)], 'baseline created event state before failing'
                report['baseline'] = 'verified-original-history-failure'
            # Deliberately leave this owned ordinary draft unsent. The published
            # sender must preserve and co-submit it with the retirement offer.
            if args.stale_offer_draft:
                require(run([*tmux, 'send-keys', '-t', pane, '-l', 'Disposable retirement rehearsal reminder.']))
            notice = ('claude --resume ' if harness == 'claude' else 'codex resume ') + context['session_id']
            prefix = r'^Resume this session with:[ \t]*\n' if harness == 'claude' else r'^Token usage: [^\n]+\nTo continue this session, run:[ \t]*\n'
            pattern = prefix + r'[ \t]*' + re.escape(notice) + r'[ \t]*$'
            deadline = time.monotonic() + 1200
            command = [HERE / 'retire.sh', pane, '--retire', '--wait', '60', '--poll', '1']
            observations = []
            while True:
                result = run(command, env=environment, timeout=240)
                observations.append({'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
                (directory / (harness + '-retire.json')).write_text(json.dumps(observations, indent=2))
                if result.returncode == 0:
                    break
                # A delivered offer needs observation, never another send. All
                # other failures remain failures and require deliberate inspection.
                if result.returncode != 2:
                    require(result)
                try:
                    pending = json.loads(result.stderr)
                except ValueError as error:
                    raise RuntimeError('retirement failure lacked structured JSON; inspect retained result') from error
                if (result.returncode != 2 or not pending.get('reason', '').startswith(('DONE not observed;', 'handoff verified; retirement pending original process end and fresh same-session exit notice'))
                        or time.monotonic() >= deadline):
                    require(result)
                command = [HERE / 'retire.sh', pane, '--retire', '--resume', pending['state'], '--wait', '60', '--poll', '1']
            require(result)
            states = [json.loads(path.read_text()) for path in records.glob('*.json') if re.fullmatch(r'[0-9a-f]{32}', path.stem)]
            matching = [item for item in states if item['pane'] == pane]
            assert len(matching) == 1, f'expected exactly one state for {pane}, found {len(matching)}'
            state = matching[0]
            assert state['status'] == 'retired', state['status']
            assert state['offer']['status'] == 'delivered'
            if args.stale_offer_draft:
                assert state['offer'].get('stale_draft_length') == len('Disposable retirement rehearsal reminder.'), 'ordinary stale draft was not co-submitted'
            assert state.get('handoff_receipt') and state.get('shard_hash')
            screen = require(run([*tmux, 'capture-pane', '-p', '-J', '-S', '-', '-t', pane]))
            baseline = state['exit_notice']
            assert baseline['session_id'] == context['session_id']
            assert type(state['exit'].get('enters')) is int and state['exit']['enters'] >= 1, 'no actual submitted exit request'
            assert state['exit']['status'] == 'delivered' or state['exit'].get('input_attempted') is True
            assert len(re.findall(pattern, screen, re.MULTILINE)) > baseline['before'], f'fresh same-session {harness} native notice missing'
            pane_dead = require(run([*tmux, 'display-message', '-p', '-t', pane, '#{pane_dead}']))
            assert pane_dead == '1', 'owned launcher pane has not ended'
            actors = [state['identity']['process'], *state['identity']['process'].get('cores', [])]
            for actor in actors:
                current = retire.proc(actor['pid'])
                assert (current is None or current['start'] != actor['start'] or current['boot'] != actor['boot']), 'original actor remains live'
            assert foreign.read_bytes() == foreign_bytes
            shard = state['shard']
            assert git('rev-parse', 'origin/master:' + shard) == state['shard_hash']
            assert require(run(['git', '--git-dir', remote, 'rev-parse', 'master:' + shard])) == state['shard_hash'], 'actual local bare remote shard differs'
            preserved = json.loads(git('show', 'origin/master:' + shard))
            assert preserved['session_id'] == context['session_id'], 'retirement lost verified native session identity'
            report['results'].append({'harness': harness, 'pane': pane, 'event': state['id'],
                                      'handoff': 'remote-blob-verified', 'exit_receipt': notice, 'processes_ended': True,
                                      'pane_dead': True, 'native_session': context['session_id'], 'identity_source': context['evidence_source']})
            print(harness + ': real handoff, exit receipt, and process end verified', flush=True)
    except BaseException as error:
        failed = True
        report['failure'] = str(error)
        raise
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        # Only this uniquely named server, created above, belongs to this test.
        if server_creation_attempted:
            try:
                cleanup = run([*tmux, 'kill-server'], timeout=10)
                report['cleanup_exit'] = cleanup.returncode
            except (OSError, subprocess.TimeoutExpired) as error:
                report['cleanup_error'] = type(error).__name__
        try:
            absent = run([*tmux, 'list-sessions'], timeout=10)
            report['resources_released'] = absent.returncode != 0
        except (OSError, subprocess.TimeoutExpired) as error:
            report['cleanup_probe_error'] = type(error).__name__
            report['resources_released'] = False
        try:
            report['worktree_after'] = fingerprint(worktree, owned=True)
            report['worktree_unchanged'] = report['worktree_after'] == worktree_before
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            report['containment_check_failure'] = str(error)
            report['worktree_unchanged'] = False
        (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if not report['resources_released'] or not report['worktree_unchanged']:
            print('Native cleanup/containment verification failed; inspect private report.', file=sys.stderr)
            if not failed:
                raise AssertionError('owned resources or disposable worktree verification failed')


if __name__ == '__main__':
    main()
