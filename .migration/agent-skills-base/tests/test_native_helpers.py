#!/usr/bin/env python3
"""Retirement's native readers must work from a standalone installed skill tree."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeHelpers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-layout-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skills = self.root / 'checkout/skills'
        shutil.copytree(ROOT / 'skills', self.skills, ignore=shutil.ignore_patterns('__pycache__'))
        installed = self.root / '.claude/skills'
        installed.parent.mkdir()
        installed.symlink_to(self.skills, target_is_directory=True)
        self.script = installed / 'retire-agent/scripts/retire.py'
        if os.environ.get('NATIVE_HELPERS_TEST_RETIRE'):
            self.script.write_bytes(Path(os.environ['NATIVE_HELPERS_TEST_RETIRE']).read_bytes())
        self.native = self.skills / '_shared/native'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('AGENT_SKILLS_', 'RETIRE_', 'SPAWN_')) and k != 'TMUX'}
        self.env.update(HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / '.config'))

    def run_reader(self, setup=''):
        code = '''import importlib.util,json,sys,types
from pathlib import Path
from types import SimpleNamespace
script=Path(sys.argv[1]);native=Path(sys.argv[2]).resolve()
spec=importlib.util.spec_from_file_location('isolated_retire',script)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
r=m.Retirement(SimpleNamespace(resume=None))
r.verify_identity=lambda:None
r.state={'identity':{'process':{'pid':123,'start':'start','boot':'boot','agent':'codex'}}}
'''+setup+'''
try:
    result=r.native_binding()
    print(json.dumps(result))
except m.Stop as error:
    print(str(error),file=sys.stderr);sys.exit(2)
'''
        return subprocess.run([sys.executable, '-I', '-c', code, str(self.script), str(self.native)],
                              env=self.env, cwd=self.root, text=True, capture_output=True)

    def test_standalone_installed_layout_loads_canonical_helpers(self):
        result = self.run_reader('''sys.path.insert(0,str(native))
import session_binding,harness_identity,codex_status
assert all(Path(module.__file__).parent==native for module in (session_binding,harness_identity,codex_status))
session_binding.observe_native_session=lambda *args:{'state':'observed','session_id':'11111111-1111-1111-1111-111111111111'}
assert not (script.resolve().parents[4]/'mcp/claude-introspect').exists()
r.native_binding(); r.native_binding()
assert sys.path.count(str(native)) == 1
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'observed')
        self.assertEqual(list(self.native.rglob('*.pyc')), [])

    def test_symlinked_shared_directory_loads_canonical_helpers(self):
        shared = self.skills / '_shared'
        target = self.root / 'shared-target'
        shared.rename(target)
        shared.symlink_to(target, target_is_directory=True)
        self.native = target / 'native'
        self.test_standalone_installed_layout_loads_canonical_helpers()

    def test_missing_helper_never_falls_back(self):
        # Contract test; the positive standalone-layout test distinguishes old code.
        for name in ('session_binding', 'harness_identity', 'codex_status'):
            with self.subTest(name=name):
                path = self.native / (name + '.py')
                content = path.read_bytes()
                try:
                    path.unlink()  # Owned fixture file, exact path.
                    result = self.run_reader()
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn('native session binding reader unavailable', result.stderr)
                finally:
                    path.write_bytes(content)

    def test_escaping_helper_never_runs(self):
        helper = self.native / 'harness_identity.py'
        outside = self.root / 'outside.py'
        outside.write_text('raise AssertionError("outside helper executed")')
        helper.unlink()  # Exact owned fixture file.
        helper.symlink_to(outside)
        result = self.run_reader()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('native session binding reader path changed', result.stderr)
        self.assertNotIn('outside helper executed', result.stderr)

    def test_wrong_cached_helper_never_runs(self):
        for name in ('session_binding', 'harness_identity', 'codex_status'):
            with self.subTest(name=name):
                result = self.run_reader(f'''fake=types.ModuleType({name!r})
fake.__file__='/outside/{name}.py'
sys.modules[{name!r}]=fake
''')
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('native session binding reader path changed', result.stderr)

    def test_native_directory_is_promoted_before_import(self):
        marker = self.skills.parent / 'outside-helper-ran'
        result = self.run_reader(f'''native.joinpath('session_binding.py').write_text("class ProcessPin:\\n    def __init__(self,*args): pass\\ndef observe_native_session(*args): return {{'state':'observed','session_id':'11111111-1111-1111-1111-111111111111'}}\\n")
outside=native.parents[2]/'outside'
outside.mkdir()
outside.joinpath('session_binding.py').write_text("from pathlib import Path\\nPath({str(marker)!r}).write_text('ran')\\nraise RuntimeError('outside helper executed')\\n")
sys.path.append(str(native))
sys.path.insert(0,str(outside))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(json.loads(result.stdout)['state'], 'observed')


def mutation_check():
    source = (ROOT / 'skills/retire-agent/scripts/retire.py').read_text()
    cases = [
        ('containment', 'if not helper.resolve().is_relative_to(directory):', 'if False:',
         'test_escaping_helper_never_runs'),
        ('presence', 'if not helper.is_file():', 'if False:',
         'test_missing_helper_never_falls_back'),
        ('cached_origin', "if cached is not None and Path(getattr(cached, '__file__', '')).resolve() != helper.resolve():", 'if False:',
         'test_wrong_cached_helper_never_runs'),
        ('path_dedup', "sys.path[:] = [str(directory)] + [entry for entry in sys.path if entry != str(directory)]",
         'sys.path.insert(0, str(directory))',
         'test_standalone_installed_layout_loads_canonical_helpers'),
        ('path_priority', "sys.path[:] = [str(directory)] + [entry for entry in sys.path if entry != str(directory)]",
         "sys.path[:] = [entry for entry in sys.path if entry != str(directory)] + [str(directory)]",
         'test_native_directory_is_promoted_before_import'),
        ('symlink_base', "directory = (Path(__file__).resolve().parents[2] / '_shared/native').resolve()",
         "directory = Path(__file__).resolve().parents[2] / '_shared/native'",
         'test_symlinked_shared_directory_loads_canonical_helpers'),
    ]
    failed = []
    with tempfile.TemporaryDirectory(prefix='native-guard-mutants-') as temporary:
        target = Path(temporary) / 'retire.py'
        for name, before, after, test in cases:
            if source.count(before) != 1:
                raise AssertionError('mutation anchor drift: ' + name)
            target.write_text(source.replace(before, after, 1))
            result = subprocess.run([sys.executable, __file__, 'NativeHelpers.' + test],
                                    env=os.environ | {'NATIVE_HELPERS_TEST_RETIRE': str(target)},
                                    text=True, capture_output=True, timeout=30)
            killed = result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr
            print(('KILLED ' if killed else 'INVALID OR SURVIVED ') + name)
            if not killed:
                failed.append(name)
                print(result.stdout + result.stderr)
    return bool(failed)


if __name__ == '__main__':
    if sys.argv[1:] == ['--mutation-check']:
        raise SystemExit(mutation_check())
    unittest.main()
