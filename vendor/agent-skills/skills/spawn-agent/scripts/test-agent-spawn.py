#!/usr/bin/env python3
"""Exercise launch routing without touching live agent input."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent
PARENT = '01a0702a-7b5e-71e0-bb62-287d55a7f9ba'
CHILD = '01a07050-1111-7222-8333-444444444444'

class SpawnDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / 'skills/spawn-agent/scripts'
        self.bin = self.root / 'bin'
        self.scripts.mkdir(parents=True); self.bin.mkdir()
        shutil.copytree(SCRIPTS.parents[1] / '_shared', self.root / 'skills/_shared')
        for name in ['agent-spawn.sh', 'tmux-ctx.sh', 'codex-fork-task.py', 'codex-jsonl-watch.py']:
            shutil.copy2(SCRIPTS / name, self.scripts / name)
        self.task = self.root / 'task'
        self.task.write_bytes('Actual λ task\nwith $literal bytes\n'.encode())
        self.policy = self.root / 'policy'
        self.policy.write_text('Keep durable decisions.')
        self.rollout = self.root / 'rollout.jsonl'
        self.metadata = {'type':'session_meta','payload':{'id':CHILD,'forked_from_id':PARENT}}
        self.rollout.write_text(json.dumps(self.metadata)+'\n')
        self.log = self.root / 'messages.jsonl'
        self.addCleanup(self.remove_compact_snapshot)
        self.env = dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'],
                        TEST_ROOT=str(self.root), TEST_ROLLOUT=str(self.rollout),
                        XDG_CONFIG_HOME=str(self.root / 'config'))
        for key in list(self.env):
            if key.startswith('AGENT_SKILLS_'):
                self.env.pop(key)
        for key in ['TMUX','SPAWN_TMUX_SOCKET','SPAWN_TMUX_LABEL','SPAWN_CODEX_BIN','SPAWN_CODEX_MODEL']:
            self.env.pop(key, None)
        # Only --help may run (the --no-daemon probe); a native queue never may.
        # Help fixtures are option excerpts: 0.160.0 lists --no-daemon (style
        # new), 0.146.0 does not (old). TOP_HELP/FORK_HELP pick each style.
        self.write(self.bin/'codex', '''#!/bin/bash
if [[ "${@: -1}" == --help ]]; then
    style=${TOP_HELP:-new}; [[ "$1" == fork ]] && style=${FORK_HELP:-$style}
    printf '%s\\n' "      --remote <ADDR>" "          Connect the TUI to a remote app server endpoint."
    case "$style" in
        new) printf '%s\\n' "      --no-daemon" "          Run without the shared background server, even if it is already running";;
        alias) printf '%s\\n' "  -n, --no-daemon" "          Run without the shared background server";;
        prose) printf '%s\\n' "      --remote-only" "          Incompatible with --no-daemon, which this build lacks";;
    esac
    exit 0
fi
exit 99
''')
        self.write(self.bin/'tmux', '''#!/usr/bin/env python3
import os,sys,json,shlex
from pathlib import Path
root=Path(os.environ['TEST_ROOT'])
with (root/'tmux.jsonl').open('a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1]=='new-window':
    (root/'launch').write_text(sys.argv[-1])
    for arg in shlex.split(sys.argv[-1]):
        if arg.startswith('experimental_compact_prompt_file='):
            (root/'compact-copy').write_bytes(Path(json.loads(arg.split('=',1)[1])).read_bytes())
    if os.environ.get('MUTATE_TASK'): (root/'task').write_text('changed caller task')
    print('%88')
''')
        self.write(self.scripts/'codex-rollout-path.sh', '#!/bin/bash\nprintf "%s\\n" "$TEST_ROLLOUT"\n')
        self.write(self.scripts/'tmux-message.sh', '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
root=Path(os.environ['TEST_ROOT']);args=sys.argv[1:]
text=Path(args[args.index('--prompt-file')+1]).read_text() if '--prompt-file' in args else args[-1]
with (root/'messages.jsonl').open('a') as out: out.write(json.dumps({'args':args,'text':text})+'\\n')
status=int(os.environ.get('SEND_STATUS','0'))
if text=='/compact' and not status and not os.environ.get('NO_COMPACTION'):
    with Path(os.environ['TEST_ROLLOUT']).open('a') as out:
        out.write(json.dumps({'type':'event_msg','payload':{'type':'context_compacted'}})+'\\n')
sys.exit(status)
''')

    def remove_compact_snapshot(self):
        launch = self.root / 'launch'
        if launch.exists():
            for arg in shlex.split(launch.read_text()):
                if arg.startswith('experimental_compact_prompt_file='):
                    path = Path(json.loads(arg.split('=', 1)[1]))
                    if str(path).startswith('/tmp/spawn-agent-compact.'):
                        path.unlink(missing_ok=True)

    def write(self, path, text):
        path.write_text(text); path.chmod(0o755)

    def launch(self, agent='codex', extra=(), env=None, task=True):
        args=[str(self.scripts/'agent-spawn.sh'),'test:worker',agent,str(self.root)]
        if task: args+=['--prompt-file',str(self.task)]
        return subprocess.run(args+list(extra), env=self.env | (env or {}), capture_output=True,text=True)

    def messages(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_every_harness_routes_task_once_to_spawned_pane(self):
        for agent in ['codex','claude']:
            with self.subTest(agent=agent):
                self.log.unlink(missing_ok=True)
                result=self.launch(agent)
                self.assertEqual(result.returncode,0,result.stderr)
                messages=self.messages(); self.assertEqual(len(messages),1)
                self.assertEqual(messages[0]['args'][:4],['send','%88','--max-wait','30'])
                self.assertEqual(messages[0]['text'],self.task.read_text())
                self.assertIn('task delivery confirmed',result.stdout)
                if agent=='codex':
                    self.assertIn('check_for_update_on_startup=false',(self.root/'launch').read_text())
                    self.assertIn('--no-alt-screen',shlex.split((self.root/'launch').read_text()))
                    self.assertIn('--no-daemon',shlex.split((self.root/'launch').read_text()))
                commands=[json.loads(line)[0] for line in (self.root/'tmux.jsonl').read_text().splitlines()]
                self.assertFalse(set(commands)&{'load-buffer','paste-buffer','send-keys'})

    def test_unsupported_agy_task_rejected_before_window(self):
        result=self.launch('agy')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('launch without a prompt',result.stderr)
        self.assertFalse((self.root/'tmux.jsonl').exists())
        self.assertEqual(self.messages(),[])

    def test_no_prompt_needs_no_message_or_transcript(self):
        self.assertEqual(self.launch('agy',task=False).returncode,0)
        self.assertEqual(self.messages(),[])

    def test_transport_failure_preserved_without_retry(self):
        for status in [2,3,1]:
            self.log.unlink(missing_ok=True)
            result=self.launch(env={'SEND_STATUS':str(status)})
            self.assertEqual(result.returncode,status,result.stderr)
            self.assertEqual(len(self.messages()),1)
            self.assertNotIn('task transport sent',result.stdout)

    def test_fork_snapshot_and_compaction_before_task(self):
        original=self.task.read_text()
        result=self.launch(extra=['--fork-session',PARENT,'--compact-prompt-file',str(self.policy),
                                  '--rollout-path-file',str(self.root/'rollout-out'),
                                  '--recap-cursor-file',str(self.root/'cursor-out'),
                                  '--startup-cursor-file',str(self.root/'startup-out'),'--compact-timeout','900'],env={'MUTATE_TASK':'1'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([item['text'] for item in self.messages()],['/compact',original])
        self.assertIn('--no-alt-screen',shlex.split((self.root/'launch').read_text()))
        self.assertIn('--no-daemon',shlex.split((self.root/'launch').read_text()))
        self.assertEqual(self.messages()[0]['args'][4:6], ['--receipt-wait','900'])
        self.assertIn(original,(self.root/'compact-copy').read_text())
        self.assertEqual((self.root/'rollout-out').read_text().strip(),str(self.rollout))
        self.assertEqual(int((self.root/'cursor-out').read_text()),self.rollout.stat().st_size)
        self.assertLess(int((self.root/'startup-out').read_text()),int((self.root/'cursor-out').read_text()))

    def test_no_daemon_follows_the_launched_subcommands_help(self):
        fork=['--fork-session',PARENT,'--compact-prompt-file',str(self.policy)]
        cases=[((),{'TOP_HELP':'new'},True),((),{'TOP_HELP':'old'},False),
               ((),{'TOP_HELP':'alias'},True),((),{'TOP_HELP':'prose'},False),
               ((),{'TOP_HELP':'new','FORK_HELP':'old'},True),
               (fork,{'TOP_HELP':'new'},True),(fork,{'TOP_HELP':'old'},False),
               (fork,{'TOP_HELP':'alias'},True),(fork,{'TOP_HELP':'prose'},False),
               # A fork that probed top-level help would get these wrong.
               (fork,{'TOP_HELP':'new','FORK_HELP':'old'},False),
               (fork,{'TOP_HELP':'old','FORK_HELP':'new'},True)]
        for extra,env,expected in cases:
            with self.subTest(fork=bool(extra),**env):
                self.log.unlink(missing_ok=True)
                result=self.launch(extra=extra,env=env)
                self.assertEqual(result.returncode,0,result.stderr)
                argv=shlex.split((self.root/'launch').read_text())
                self.assertEqual('--no-daemon' in argv,expected)
                self.assertIn('--no-alt-screen',argv)

    def test_failed_compaction_never_sends_task(self):
        result=self.launch(extra=['--fork-session',PARENT,'--compact-prompt-file',str(self.policy),
                                  '--compact-timeout','1'],env={'NO_COMPACTION':'1'})
        self.assertNotEqual(result.returncode,0)
        self.assertEqual([item['text'] for item in self.messages()],['/compact'])

    def test_compact_transport_failure_never_sends_task(self):
        result=self.launch(extra=['--fork-session',PARENT,'--compact-prompt-file',str(self.policy)],
                           env={'SEND_STATUS':'3'})
        self.assertEqual(result.returncode,3)
        self.assertEqual([item['text'] for item in self.messages()],['/compact'])

    def test_model_selection_and_invalid_options_before_launch(self):
        result=self.launch(extra=['--model','chosen-model'])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('-m chosen-model',(self.root/'launch').read_text())
        (self.root/'tmux.jsonl').unlink()
        for agent,extra in [('claude',['--codex-bin','codex']),('agy',['--model','bad']),('codex',['--trust']),
                            ('claude',['--fork-session',PARENT])]:
            with self.subTest(agent=agent,extra=extra):
                self.assertNotEqual(self.launch(agent,extra,task=agent != 'agy').returncode,0)
                self.assertFalse((self.root/'tmux.jsonl').exists())

    def test_claude_model_is_explicit_and_shell_escaped(self):
        chosen='opus; $(touch injected)'
        result=self.launch('claude',extra=['--model',chosen],env={'SPAWN_CODEX_MODEL':'codex-only'})
        self.assertEqual(result.returncode,0,result.stderr)
        command=shlex.split((self.root/'launch').read_text())
        self.assertEqual(command[:3],['claude','--model',chosen])
        self.assertFalse((self.root/'injected').exists())
        result=self.launch('claude',env={'SPAWN_CODEX_MODEL':'codex-only'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('--model',shlex.split((self.root/'launch').read_text()))

    def test_environment_model_binary_and_shell_escaping(self):
        binary=self.bin/'chosen codex'
        shutil.copy2(self.bin/'codex',binary)
        result=self.launch(env={'SPAWN_CODEX_BIN':str(binary),'SPAWN_CODEX_MODEL':'env model'})
        self.assertEqual(result.returncode,0,result.stderr)
        command=shlex.split((self.root/'launch').read_text())
        self.assertEqual(command[0],str(binary))
        self.assertEqual(command[command.index('-m')+1],'env model')
        self.assertIn('check_for_update_on_startup=false',command)
        result=self.launch(extra=['--model','cli-model'],env={'SPAWN_CODEX_MODEL':'env-model'})
        self.assertEqual(result.returncode,0,result.stderr)
        command=shlex.split((self.root/'launch').read_text())
        self.assertEqual(command[command.index('-m')+1],'cli-model')

    def test_shared_config_binary_and_explicit_overrides(self):
        binary = self.bin / 'configured codex'
        shutil.copy2(self.bin / 'codex', binary)
        config = self.root / 'config/agent-skills/config.toml'
        config.parent.mkdir(parents=True)
        config.write_text('[harness]\ncodex_bin = ' + json.dumps(str(binary)) + '\n')
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split((self.root / 'launch').read_text())[0], str(binary))
        result = self.launch(env={'SPAWN_CODEX_BIN': 'codex'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split((self.root / 'launch').read_text())[0], str(self.bin / 'codex'))
        result = self.launch(extra=['--codex-bin', str(binary)], env={'SPAWN_CODEX_BIN': 'missing'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split((self.root / 'launch').read_text())[0], str(binary))

    def test_launch_pins_child_helpers_across_configuration_change(self):
        config = self.root / 'config/agent-skills/config.toml'
        config.parent.mkdir(parents=True)
        self.write(self.bin / 'tmux', '#!/usr/bin/env python3\n' +
                   'import os,sys,json\nfrom pathlib import Path\n' +
                   'root=Path(os.environ["TEST_ROOT"]); args=sys.argv[1:]\n' +
                   'with (root/"selection.jsonl").open("a") as out: out.write(json.dumps(args)+"\\n")\n' +
                   'if "new-window" in args:\n' +
                   ' (root/"config/agent-skills/config.toml").write_text(' + repr('[tmux]\nsocket = "beta"\n') + ')\n' +
                   ' print("%88")\n')
        selection = 'source "$(dirname -- "$0")/tmux-ctx.sh"\nprintf "%s\\n" "${TMUX_CMD[@]}"'
        self.write(self.scripts / 'tmux-message.sh', '#!/bin/bash\nset -e\n' + selection + ' > "$TEST_ROOT/message-selection"\n')
        self.write(self.scripts / 'codex-rollout-path.sh', '#!/bin/bash\nset -e\n' + selection +
                   ' > "$TEST_ROOT/rollout-selection"\nprintf "%s\\n" "$TEST_ROLLOUT"\n')
        cases = [('alpha', {}, ['-L', 'alpha']), ('/tmp/alpha.sock', {}, ['-S', '/tmp/alpha.sock']),
                 ('', {}, []), ('alpha', {'SPAWN_TMUX_LABEL': 'legacy'}, ['-L', 'legacy']),
                 ('alpha', {'SPAWN_TMUX_SOCKET': '/tmp/legacy.sock'}, ['-S', '/tmp/legacy.sock'])]
        for initial, env, selector in cases:
            with self.subTest(initial=initial, env=env):
                config.write_text('[tmux]\nsocket = ' + json.dumps(initial) + '\n')
                (self.root / 'selection.jsonl').write_text('')
                result = self.launch(extra=['--fork-session', PARENT], env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = [json.loads(line) for line in (self.root / 'selection.jsonl').read_text().splitlines()]
                self.assertEqual(calls[-1][:len(selector) + 1], selector + ['new-window'])
                self.assertEqual((self.root / 'message-selection').read_text().splitlines(), ['tmux', *selector])
                self.assertEqual((self.root / 'rollout-selection').read_text().splitlines(), ['tmux', *selector])

    def test_parent_identity_and_partial_metadata_never_send(self):
        for metadata in [json.dumps({'type':'session_meta','payload':{'id':PARENT,'forked_from_id':PARENT}})+'\n',
                         '{"type":"session_meta"']:
            self.rollout.write_text(metadata)
            result=self.launch(extra=['--fork-session',PARENT])
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(self.messages(),[])

    def test_wrong_fork_ancestry_never_sends(self):
        self.metadata['payload']['forked_from_id']='00000000-0000-0000-0000-000000000000'
        self.rollout.write_text(json.dumps(self.metadata)+'\n')
        result=self.launch(extra=['--fork-session',PARENT])
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.messages(),[])

if __name__=='__main__':
    unittest.main()
