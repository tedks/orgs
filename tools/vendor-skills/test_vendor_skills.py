#!/usr/bin/env python3
"""Offline integration checks against disposable source and consumer repositories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('vendor_skills.py')
NAMES = ('ask-agent', 'initialize-repo', 'spawn-agent', 'stacked-prs', '_shared')


class VendorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orgs-vendor-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source with spaces'
        self.root = self.base / 'orgs'
        self.source.mkdir()
        self.root.mkdir()
        self.git(self.source, 'init', '-q')
        self.git(self.source, 'config', 'user.name', 'Test')
        self.git(self.source, 'config', 'user.email', 'test@example.invalid')
        (self.source / 'LICENSE').write_text('GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3\n')
        for name in NAMES:
            directory = self.source / 'skills' / name
            directory.mkdir(parents=True)
            if name != '_shared':
                (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Test skill\n---\nLocal skill\n')
        helper = self.source / 'skills/_shared/config.sh'
        helper.write_text('#!/bin/sh\nprintf "local helper\\n"\n')
        helper.chmod(0o755)
        (self.source / 'skills/_shared/agent_skills_config.py').write_text('# fixture\n')
        (self.source / 'skills/_shared/configuration.md').write_text('Fixture config\n')
        (self.source / 'skills/ask-agent/obsolete.txt').write_text('old helper\n')
        self.commit = self.source_commit('initial')
        (self.root / 'tools/vendor-skills').mkdir(parents=True)
        shutil.copy2(SCRIPT, self.root / 'tools/vendor-skills/vendor_skills.py')
        self.command = ['python3', str(self.root / 'tools/vendor-skills/vendor_skills.py')]

    def git(self, cwd, *args):
        return subprocess.check_output(['git', '-C', str(cwd), *args], stderr=subprocess.STDOUT, text=True).strip()

    def source_commit(self, message):
        self.git(self.source, 'add', '.')
        self.git(self.source, 'commit', '-qm', message)
        return self.git(self.source, 'rev-parse', 'HEAD')

    def run_tool(self, *args, ok=True):
        result = subprocess.run(self.command + list(args), text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def sync(self, commit=None, ok=True):
        return self.run_tool('sync', '--checkout', str(self.source), '--commit', commit or self.commit, ok=ok)

    def test_deterministic_pinned_content_ignores_source_working_tree(self):
        (self.source / 'skills/ask-agent/SKILL.md').write_text('dirty source')
        (self.source / 'skills/ask-agent/untracked').write_text('not vendored')
        self.sync()
        lock = (self.root / 'vendor/agent-skills.lock.json').read_bytes()
        self.sync()
        self.assertEqual(lock, (self.root / 'vendor/agent-skills.lock.json').read_bytes())
        self.assertNotEqual((self.root / '.claude/skills/ask-agent/SKILL.md').read_text(), 'dirty source')
        self.assertFalse((self.root / 'vendor/agent-skills/skills/ask-agent/untracked').exists())
        self.run_tool('verify')

    def test_content_missing_mode_and_untracked_drift_block_verify_and_sync(self):
        self.sync()
        file = self.root / 'vendor/agent-skills/skills/_shared/config.sh'
        original = file.read_bytes()
        file.write_text('edited')
        self.run_tool('verify', ok=False)
        self.sync(ok=False)
        file.write_bytes(original)
        file.chmod(0o644)
        self.run_tool('verify', ok=False)
        file.chmod(0o755)
        file.unlink()
        self.run_tool('verify', ok=False)
        file.write_bytes(original)
        file.chmod(0o755)
        extra = file.with_name('.untracked')
        extra.write_text('extra')
        self.run_tool('verify', ok=False)
        self.sync(ok=False)

    def test_repin_and_refuse_source_removals_without_partial_write(self):
        self.sync()
        (self.source / 'skills/ask-agent/SKILL.md').write_text('changed upstream\n')
        next_commit = self.source_commit('update')
        self.sync(next_commit)
        lock = self.root / 'vendor/agent-skills.lock.json'
        before = lock.read_bytes()
        self.assertEqual(json.loads(before)['commit'], next_commit)
        (self.source / 'skills/ask-agent/obsolete.txt').unlink()
        removed_commit = self.source_commit('remove helper')
        result = self.sync(removed_commit, ok=False)
        self.assertIn('Source removes files', result.stderr)
        self.assertEqual(lock.read_bytes(), before)
        self.assertTrue((self.root / 'vendor/agent-skills/skills/ask-agent/obsolete.txt').exists())
        self.run_tool('verify')

    def test_refuses_symbolic_source_and_destination_escape(self):
        (self.source / 'skills/ask-agent/escape').symlink_to('/etc/passwd')
        commit = self.source_commit('unsupported symlink')
        self.sync(commit, ok=False)
        self.assertFalse((self.root / 'vendor').exists())
        (self.root / 'vendor').symlink_to(self.base)
        self.sync(ok=False)
        self.assertFalse((self.base / 'agent-skills').exists())

    def test_refuses_wrong_links_and_corrupt_manifest(self):
        self.sync()
        link = self.root / '.claude/skills/ask-agent'
        link.unlink()
        link.symlink_to('/missing-global-skill')
        self.run_tool('verify', ok=False)
        self.sync(ok=False)
        link.unlink()
        link.symlink_to('../../vendor/agent-skills/skills/ask-agent')
        lock = self.root / 'vendor/agent-skills.lock.json'
        data = json.loads(lock.read_text())
        data['files']['../escape'] = data['files']['LICENSE']
        lock.write_text(json.dumps(data))
        self.run_tool('verify', ok=False)

    def test_unrelated_shared_helpers_are_excluded(self):
        extra = self.source / 'skills/_shared/native/retirement.sh'
        extra.parent.mkdir()
        extra.write_text('unrelated retirement helper\n')
        commit = self.source_commit('unrelated shared helper')
        self.sync(commit)
        self.assertFalse((self.root / 'vendor/agent-skills/skills/_shared/native').exists())
        self.run_tool('verify')

    def test_requires_full_existing_commit_and_license(self):
        self.sync('HEAD', ok=False)
        self.sync('0' * 40, ok=False)
        (self.source / 'LICENSE').unlink()
        commit = self.source_commit('missing license')
        self.sync(commit, ok=False)

    def test_fresh_clone_discovers_local_skills_without_home_install(self):
        self.sync()
        self.git(self.root, 'init', '-q')
        self.git(self.root, 'config', 'user.name', 'Test')
        self.git(self.root, 'config', 'user.email', 'test@example.invalid')
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-qm', 'snapshot')
        clone = self.base / 'fresh clone'
        self.git(self.base, 'clone', '-q', '--no-local', str(self.root), str(clone))
        empty_home = self.base / 'empty home'
        empty_home.mkdir()
        env = dict(os.environ, HOME=str(empty_home), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run(['python3', str(clone / 'tools/vendor-skills/vendor_skills.py'), 'verify'], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for entry in ('.claude/skills', '.agents/skills'):
            for name in NAMES[:-1]:
                path = clone / entry / name / 'SKILL.md'
                self.assertTrue(path.is_file())
                self.assertTrue(path.resolve().is_relative_to(clone / 'vendor/agent-skills'))
            helper = clone / entry / '_shared/config.sh'
            result = subprocess.check_output([str(helper)], env=env, text=True)
            self.assertEqual(result, 'local helper\n')


if __name__ == '__main__':
    unittest.main()
