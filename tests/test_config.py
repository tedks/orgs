#!/usr/bin/env python3
"""Configuration and real entrypoint contract, isolated from the operator's setup."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOADER = ROOT / 'skills/_shared/agent_skills_config.py'


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skills-config-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('AGENT_SKILLS_', 'SPAWN_', 'RETIRE_')) and k != 'TMUX'}
        self.env.update(HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / 'config'))
        self.config = self.root / 'config/agent-skills/config.toml'
        self.config.parent.mkdir(parents=True)

    def cli(self, *args, extra=None):
        return subprocess.run([sys.executable, str(LOADER), *args],
                              env=self.env | (extra or {}), text=True, capture_output=True)

    def load(self, **extra):
        result = self.cli(extra=extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_missing_file_generic_defaults(self):
        data = self.load()
        self.assertEqual(data['projects_root'], str(self.root / 'Projects'))
        self.assertEqual(data['operator']['name'], 'the operator')
        self.assertEqual(data['off_duty']['remote'], '')
        self.assertEqual(data['github']['owner'], '')
        self.assertEqual(data['tmux']['socket'], '')
        self.assertEqual(data['harness']['codex_bin'], 'codex')

    def test_toml_and_environment_precedence(self):
        self.config.write_text('projects_root = "~/work"\n[operator]\nname = "Ada"\n[fleet]\nhosts = ["build.local"]\n')
        data = self.load(AGENT_SKILLS_OPERATOR_NAME='Grace', AGENT_SKILLS_FLEET_HOSTS='["test.local"]')
        self.assertEqual(data['projects_root'], str(self.root / 'work'))
        self.assertEqual(data['off_duty']['path'], str(self.root / 'work/agent-handoffs'))
        self.assertEqual(data['operator']['name'], 'Grace')
        self.assertEqual(data['fleet']['hosts'], ['test.local'])

    def test_explicit_config_path_and_literal_values(self):
        alternate = self.root / 'other.toml'
        alternate.write_text('[operator]\nname = "$(touch NEVER) `false`"\n')
        data = self.load(AGENT_SKILLS_CONFIG=str(alternate))
        self.assertEqual(data['operator']['name'], '$(touch NEVER) `false`')
        self.assertFalse((self.root / 'NEVER').exists())
        result = self.cli('get', 'operator.name', extra={'AGENT_SKILLS_CONFIG': str(alternate)})
        self.assertEqual(result.stdout.strip(), data['operator']['name'])

    def test_invalid_file_fails_closed_even_with_override(self):
        for source in ['[broken', '[operator]\nname = 42', '[fleet]\nhosts = "build"',
                       '[tmux]\nsocket = "bad\\nlabel"', '[unknown]\nx = 1',
                       'projects_root = "relative"', '[github]\nowner = "-bad"']:
            with self.subTest(source=source):
                self.config.write_text(source)
                result = self.cli(extra={'AGENT_SKILLS_OPERATOR_NAME': 'override'})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('agent-skills config:', result.stderr)

    def test_config_locations_must_be_explicit_absolute_paths(self):
        for extra in ({'XDG_CONFIG_HOME': 'relative'}, {'AGENT_SKILLS_CONFIG': ''},
                      {'AGENT_SKILLS_CONFIG': 'relative.toml'}):
            with self.subTest(extra=extra):
                result = self.cli(extra=extra)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('agent-skills config:', result.stderr)

    def test_invalid_environment_rejected(self):
        for key, value in [('AGENT_SKILLS_FLEET_HOSTS', 'not-json'),
                           ('AGENT_SKILLS_FLEET_HOSTS', '[1]'),
                           ('AGENT_SKILLS_HARNESS_CODEX_BIN', ''),
                           ('AGENT_SKILLS_TMUX_SOCKET', 'bad\nlabel')]:
            with self.subTest(key=key, value=value):
                self.assertNotEqual(self.cli(extra={key: value}).returncode, 0)

    def test_shell_tmux_config_and_legacy_override(self):
        helper = ROOT / 'skills/spawn-agent/scripts/tmux-ctx.sh'
        command = ['bash', '-c', 'source "$1"; printf "%s\\n" "${TMUX_CMD[@]}"', 'test', str(helper)]
        self.config.write_text('[tmux]\nsocket = "configured"\n')
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['tmux', '-L', 'configured'])
        result = subprocess.run(command, env=self.env | {'SPAWN_TMUX_SOCKET': '/tmp/explicit.sock'}, capture_output=True, text=True)
        self.assertEqual(result.stdout.splitlines(), ['tmux', '-S', '/tmp/explicit.sock'])
        result = subprocess.run(command, env=self.env | {'AGENT_SKILLS_TMUX_SOCKET': '/tmp/config.sock'}, capture_output=True, text=True)
        self.assertEqual(result.stdout.splitlines(), ['tmux', '-S', '/tmp/config.sock'])

    def test_active_tmux_socket_wins_over_seeded_config(self):
        self.config.write_text('[tmux]\nsocket = "configured"\n')
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        socket_path = str(self.root / 'active.sock')
        sock.bind(socket_path)
        env = self.env | {'TMUX': socket_path + ',123,0'}
        shell = ['bash', '-c', 'set -e; source "$1"; printf "%s\\n" "${TMUX_CMD[@]}"',
                 'test', str(ROOT / 'skills/spawn-agent/scripts/tmux-ctx.sh')]
        python = [sys.executable, '-c',
                  'import sys;sys.path.insert(0,' + repr(str(LOADER.parent)) + ');'
                  'from agent_skills_config import tmux_command;print("\\n".join(tmux_command()))']
        for command in (shell, python):
            result = subprocess.run(command, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['tmux', '-S', socket_path])
            result = subprocess.run(command, env=env | {'AGENT_SKILLS_TMUX_SOCKET': 'explicit'}, text=True, capture_output=True)
            self.assertEqual(result.stdout.splitlines(), ['tmux', '-L', 'explicit'])
            result = subprocess.run(command, env=self.env | {'TMUX': '/missing/socket,123,0'}, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('active TMUX socket unavailable', result.stderr)
            self.assertEqual(result.stdout, '')

    def test_delivery_resolution_pins_server_across_config_change(self):
        script = ROOT / 'skills/spawn-agent/scripts/tmux-message.py'
        spec = importlib.util.spec_from_file_location('config_race_delivery', script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        log = self.root / 'tmux.jsonl'
        stub = bin_dir / 'tmux'
        stub.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                        'with open(os.environ["TMUX_LOG"], "a") as out: out.write(json.dumps(sys.argv[1:])+"\\n")\n'
                        'if "list-panes" in sys.argv: print(("202" if "beta" in sys.argv else "101") + ":%7:1:target")\n')
        stub.chmod(0o700)
        original_command = module.tmux_command
        def change_after_selection():
            selected = original_command()
            self.config.write_text('[tmux]\nsocket = "beta"\n')
            return selected
        for initial in ('alpha', '/tmp/selected.sock', ''):
            with self.subTest(initial=initial):
                self.config.write_text('[tmux]\nsocket = ' + json.dumps(initial) + '\n')
                log.write_text('')
                env = self.env | {'PATH': str(bin_dir) + ':' + self.env['PATH'], 'TMUX_LOG': str(log)}
                with patch.dict(os.environ, env, clear=True), patch.object(module, 'tmux_command', side_effect=change_after_selection):
                    delivery = module.Tmux('%7')
                    delivery.keys('Enter')
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual(delivery.identity, '101:%7')
                selector = ['-S' if '/' in initial else '-L', initial] if initial else []
                self.assertEqual(calls[0][:len(selector) + 1], selector + ['list-panes'])
                self.assertEqual(calls[-1][:len(selector) + 1], selector + ['send-keys'])

    def test_explicit_observation_socket_wins_over_stale_tmux(self):
        spec = importlib.util.spec_from_file_location('explicit_socket_delivery', ROOT / 'skills/spawn-agent/scripts/tmux-message.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, self.env | {'TMUX': '/missing/socket,123,0'}, clear=True), patch.object(module.subprocess, 'run') as run:
            run.return_value.stdout = '101:%7'
            delivery = module.Tmux('%7', socket='/tmp/pinned.sock')
            self.assertEqual(delivery.base, ['tmux', '-S', '/tmp/pinned.sock'])
            self.assertEqual(run.call_args.kwargs['env']['SPAWN_TMUX_SOCKET'], '/tmp/pinned.sock')
            self.assertNotIn('TMUX', run.call_args.kwargs['env'])

    def test_tmux_info_reports_only_supplied_legacy_overrides(self):
        stub = self.root / 'tmux'
        stub.write_text('#!/bin/sh\nexit 0\n')
        stub.chmod(0o700)
        self.config.write_text('[tmux]\nsocket = "configured"\n')
        script = ROOT / 'skills/spawn-agent/scripts/tmux-info.sh'
        env = self.env | {'PATH': str(self.root) + ':' + self.env['PATH']}
        result = subprocess.run([str(script)], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Override:', result.stdout)
        self.assertIn('Selected command: tmux -L configured', result.stdout)
        for key, value, selector in [('SPAWN_TMUX_LABEL', 'legacy', '-L legacy'),
                                     ('SPAWN_TMUX_SOCKET', '/tmp/explicit.sock', '-S /tmp/explicit.sock')]:
            result = subprocess.run([str(script)], env=env | {key: value}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Override: ' + key + '=' + value, result.stdout)
            self.assertIn('Selected command: tmux ' + selector, result.stdout)

    def test_tmux_selection_error_reports_unavailable_context(self):
        spec = importlib.util.spec_from_file_location('context_error_delivery', ROOT / 'skills/spawn-agent/scripts/tmux-message.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, self.env | {'TMUX': '/missing/controller.sock,123,0'}, clear=True), patch.object(module.subprocess, 'run') as run:
            with self.assertRaisesRegex(module.DeliveryError, 'tmux-context-unavailable'):
                module.Tmux('%7')
            run.assert_not_called()

    def test_retirement_config_and_legacy_repo(self):
        script = ROOT / 'skills/retire-agent/scripts/retire.py'
        source = ('import importlib.util,json; from types import SimpleNamespace; '
                  f's=importlib.util.spec_from_file_location("retire",{str(script)!r}); '
                  'm=importlib.util.module_from_spec(s);s.loader.exec_module(m); '
                  'r=m.Retirement(SimpleNamespace());print(json.dumps([str(r.repo),r.tmux]))')
        self.config.write_text('[off_duty]\npath = "~/private-handoffs"\n[tmux]\nsocket = "configured"\n')
        result = subprocess.run([sys.executable, '-c', source], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [str(self.root / 'private-handoffs'), ['tmux', '-L', 'configured']])
        result = subprocess.run([sys.executable, '-c', source], env=self.env | {'RETIRE_REPO': str(self.root / 'legacy')}, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)[0], str(self.root / 'legacy'))

    def test_retirement_expected_remote_supplements_privacy_check(self):
        spec = importlib.util.spec_from_file_location('retire_config_test', ROOT / 'skills/retire-agent/scripts/retire.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.config.write_text('[off_duty]\nremote = "https://github.com/example/private"\n')
        with patch.dict(os.environ, self.env, clear=True):
            retirement = module.Retirement(object())
            retirement.git = lambda *args: 'https://github.com/example/other'
            with patch.object(module, 'checked') as checked:
                with self.assertRaisesRegex(module.Stop, 'does not match'):
                    retirement.private()
                checked.assert_not_called()
            retirement.git = lambda *args: 'https://github.com/example/private'
            with patch.object(module, 'checked', return_value='false'):
                with self.assertRaisesRegex(module.Stop, 'not private'):
                    retirement.private()
            with patch.object(module, 'checked', return_value='true') as checked:
                retirement.private()
                self.assertEqual(checked.call_args.args[0][0:3], ['gh', 'repo', 'view'])

    def test_retirement_roles_default_and_explicit_flag(self):
        spec = importlib.util.spec_from_file_location('retire_roles_test', ROOT / 'skills/retire-agent/scripts/retire.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        roles = self.root / 'roles.md'
        roles.write_text('roles')
        explicit = self.root / 'explicit.md'
        explicit.write_text('explicit roles')
        self.config.write_text('[doctrine]\nroles_path = ' + json.dumps(str(roles)) + '\n')
        for suffix, expected in [([], roles), (['--roles', str(explicit)], explicit)]:
            with patch.dict(os.environ, self.env, clear=True), patch.object(sys, 'argv', ['retire', '%1', '--handoff', 'codex', 'fixture-model', *suffix]), patch.object(module, 'Retirement') as cls:
                self.assertEqual(module.main(), 0)
                self.assertEqual(cls.call_args.args[0].roles, str(expected))
                cls.return_value.execute.assert_called_once()

    def test_query_uses_configured_codex_binary(self):
        fallback = self.root / 'codex'
        fallback.write_text('#!/bin/sh\nexit 19\n')
        fallback.chmod(0o700)
        binary = self.root / 'custom codex'
        binary.write_text('#!/bin/sh\nprintf "configured: %s\\n" "$*"\ncat\n')
        binary.chmod(0o700)
        script = ROOT / 'skills/ask-agent/scripts/agent-query.sh'
        result = subprocess.run([str(script), 'codex', 'fixture prompt'],
                                env=self.env | {'AGENT_SKILLS_HARNESS_CODEX_BIN': str(binary),
                                                'PATH': str(self.root) + ':' + self.env['PATH']},
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'configured: exec -\nfixture prompt')

    def test_hygiene_requires_explicit_remote_projects_root(self):
        binary_dir = self.root / 'bin'
        binary_dir.mkdir()
        ssh = binary_dir / 'ssh'
        capture = self.root / 'request.json'
        ssh.write_text('#!' + sys.executable + '\nimport os,sys,json\n'
                       'from pathlib import Path\n'
                       'Path(os.environ["CAPTURE"]).write_text(sys.stdin.read())\n'
                       'print(json.dumps({"entries": [], "diagnostics": []}))\n')
        ssh.chmod(0o700)
        policy = self.root / 'policy.json'
        script = ROOT / 'skills/host-hygiene/scripts/hygiene.py'
        values = [{}, {'projects_root': ''}, {'projects_root': '~/Projects'},
                  {'projects_root': 1}, {'projects_root': '/remote/projects'}]
        for index, value in enumerate(values):
            with self.subTest(policy=value):
                policy.write_text(json.dumps(value))
                result = subprocess.run([sys.executable, str(script), 'plan', 'build.local',
                                         str(self.root / f'plan-{index}.json'), '--policy', str(policy)],
                                        env=self.env | {'PATH': str(binary_dir) + ':' + self.env['PATH'],
                                                        'CAPTURE': str(capture),
                                                        'AGENT_SKILLS_PROJECTS_ROOT': '/local/projects'},
                                        text=True, capture_output=True)
                if value.get('projects_root') == '/remote/projects':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(capture.read_text())['policy']['projects_root'], '/remote/projects')
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('policy requires an absolute remote projects_root', result.stderr)
                    self.assertFalse(capture.exists())

    def test_executable_paths_and_tmux_labels_preserve_intent(self):
        self.config.write_text('[harness]\ncodex_bin = "./codex"\n')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('absolute path or executable name', result.stderr)
        self.config.write_text('[tmux]\nsocket = "~root"\n')
        self.assertEqual(self.load()['tmux']['socket'], '~root')

    def test_retirement_help_does_not_read_config_and_execution_reads_once(self):
        script = ROOT / 'skills/retire-agent/scripts/retire.py'
        self.config.write_text('[broken')
        result = subprocess.run([sys.executable, str(script), '--help'], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = importlib.util.spec_from_file_location('retire_snapshot_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.config.write_text('')
        with patch.dict(os.environ, self.env, clear=True), patch.object(sys, 'argv', ['retire', '%1']), patch.object(module.Retirement, 'execute'), patch.object(module, 'load_config', wraps=module.load_config) as load:
            self.assertEqual(module.main(), 0)
            self.assertEqual(load.call_count, 1)

    def test_retirement_resume_uses_validated_recorded_socket_with_stale_tmux(self):
        spec = importlib.util.spec_from_file_location('retire_resume_test', ROOT / 'skills/retire-agent/scripts/retire.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        repo = self.root / 'repo'
        common = repo / '.git'
        directory = common / 'retirements'
        directory.mkdir(parents=True)
        event = 'a' * 32
        path = directory / (event + '.json')
        state = {'id': event, 'pane': '%7', 'mode': 'retire', 'status': 'requesting',
                 'socket': '/tmp/recorded.sock',
                 'identity': {'pane_pid': '42', 'session': 'fixture', 'directory': '/fixture',
                              'process': {'pid': 43, 'start': 'start', 'boot': 'boot', 'agent': 'codex'}}}
        env = self.env | {'RETIRE_REPO': str(repo), 'TMUX': '/missing/old-controller.sock,123,0'}
        cases = [('valid', path, state, 'fixture reached publication'),
                 ('bad socket', path, state | {'socket': 'relative'}, 'socket identity'),
                 ('wrong pane', path, state | {'pane': '%8'}, 'pane/mode differs'),
                 ('outside repo', self.root / (event + '.json'), state, 'private state path')]
        for label, requested, record, reason in cases:
            with self.subTest(label=label):
                requested.write_text(json.dumps(record))
                args = SimpleNamespace(pane='%7', mode='retire', resume=str(requested), caller_shard=False)
                with patch.dict(os.environ, env, clear=True), patch.object(module, 'checked') as checked:
                    retirement = module.Retirement(args)
                    retirement.private = lambda: None
                    retirement.load_screen_helper = lambda: None
                    retirement.git = lambda *args: str(common)
                    with patch.object(retirement, 'publish', side_effect=module.Stop('fixture reached publication')), patch.object(module.os, 'access', return_value=True):
                        try:
                            with self.assertRaisesRegex(module.Stop, reason):
                                retirement.execute()
                            if label == 'valid':
                                self.assertEqual(retirement.tmux, ['tmux', '-S', '/tmp/recorded.sock'])
                            else:
                                self.assertIsNone(retirement.tmux)
                            checked.assert_not_called()
                        finally:
                            if hasattr(retirement, 'event_lock'):
                                retirement.event_lock.close()
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, 'active TMUX socket unavailable'):
                module.Retirement(SimpleNamespace(resume=None))

    def test_hygiene_remote_source_stays_standalone(self):
        # Exercise --remote using source only: no checkout or import path remotely.
        source = (ROOT / 'skills/host-hygiene/scripts/hygiene.py').read_text()
        instrumented = source.replace('result = inventory(policy, request["record_text"], request["record_errors"])',
                                      'result = {"policy": policy}')
        self.assertNotEqual(source, instrumented)
        result = subprocess.run([sys.executable, '-I', '-c', instrumented, '--remote'],
                                input=json.dumps({'mode': 'plan', 'policy': {'tmp_owner': 'lane', 'projects_root': '/remote/projects'},
                                                  'record_text': '', 'record_errors': []}),
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['policy']['tmp_owner'], 'lane')
        rejected = subprocess.run([sys.executable, '-I', '-c', instrumented, '--remote'],
                                  input=json.dumps({'mode': 'plan', 'policy': {},
                                                    'record_text': '', 'record_errors': []}),
                                  env=self.env, text=True, capture_output=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('policy requires an absolute remote projects_root', rejected.stderr)


if __name__ == '__main__':
    unittest.main()
