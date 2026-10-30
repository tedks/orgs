#!/usr/bin/env python3
"""Offline publication tests against an isolated bare repository."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).with_name('offduty-push.sh')
INDEX_BUILDER = Path(__file__).resolve().parents[1] / 'retire-agent/scripts/build-index.py'
REAL_GIT = shutil.which('git')


class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offduty-push-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.shared = self.root / 'shared'
        self.racer = self.root / 'racer'
        self.source = self.root / 'source'
        self.source.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null',
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid',
                        TMPDIR=str(self.root))
        self.env.pop('XDG_RUNTIME_DIR', None)
        self.git('init', '--bare', '-b', 'master', self.remote)
        seed = self.root / 'seed'
        self.git('clone', self.remote, seed)
        (seed / 'README').write_text('seed\n')
        self.git('-C', seed, 'add', 'README')
        self.git('-C', seed, 'commit', '-m', 'seed')
        self.git('-C', seed, 'push', 'origin', 'HEAD:master')
        self.git('clone', self.remote, self.shared)
        self.git('clone', self.remote, self.racer)

    def git(self, *args):
        return subprocess.run([REAL_GIT, *map(str, args)], env=self.env, text=True,
                              capture_output=True, check=True).stdout.strip()

    def publish(self, *paths, env=None, extra=()):
        return subprocess.run([str(HELPER), '--repo', str(self.shared), '--source-root',
                               str(self.source), *extra, *paths, '-m', 'Preserve fixture'],
                              env=env or self.env, text=True, capture_output=True)

    def test_pushes_bytes_without_modifying_shared_checkout(self):
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'agent.md').write_bytes(b'private shard\n')
        (self.shared / 'README').write_text('uncommitted shared edit\n')
        (self.shared / 'untracked').write_text('leave me alone\n')
        (self.shared / 'stray').write_text('local commit\n')
        self.git('-C', self.shared, 'add', 'stray')
        self.git('-C', self.shared, 'commit', '-m', 'stray local commit')
        before = self.git('-C', self.shared, 'status', '--porcelain=v1')
        head = self.git('-C', self.shared, 'rev-parse', 'HEAD')
        result = self.publish('waiting/agent.md')
        self.assertEqual(result.returncode, 0, result.stderr)
        pushed = result.stdout.strip()
        self.assertEqual(pushed, self.git('--git-dir', self.remote, 'rev-parse', 'master'))
        self.assertEqual(self.git('--git-dir', self.remote, 'show', 'master:waiting/agent.md'), 'private shard')
        self.assertEqual(self.git('-C', self.shared, 'rev-parse', 'HEAD'), head)
        self.assertEqual(self.git('-C', self.shared, 'status', '--porcelain=v1'), before)
        self.assertFalse((self.shared / 'waiting' / 'agent.md').exists())
        self.assertEqual((self.shared / 'README').read_text(), 'uncommitted shared edit\n')
        self.assertEqual((self.shared / 'untracked').read_text(), 'leave me alone\n')

    def test_rejects_unapproved_and_escaping_paths(self):
        (self.source / 'other').mkdir()
        (self.source / 'other' / 'a').write_text('must stay local\n')
        (self.root / 'waiting').mkdir()
        (self.root / 'waiting' / 'a').write_text('outside source\n')
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / '.x').write_text('dot file\n')
        (self.source / 'waiting' / '.git').mkdir()
        (self.source / 'waiting' / '.git' / 'config').write_text('unsafe metadata\n')
        for path in ('other/a', '../waiting/a', 'waiting/../other/a', 'waiting/.x',
                     'waiting/.git/config', '/waiting/a'):
            with self.subTest(path=path):
                result = self.publish(path)
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('--git-dir', self.remote, 'rev-list', '--count', 'master'), '1')

    def test_stale_tracking_ref_cannot_claim_remote_presence(self):
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'agent.md').write_text('preserved bytes\n')
        first = self.publish('waiting/agent.md')
        self.assertEqual(first.returncode, 0, first.stderr)
        old_head = first.stdout.strip()
        self.git('-C', self.shared, 'config', '--replace-all', 'remote.origin.fetch',
                 '+refs/heads/other:refs/remotes/origin/other')
        self.git('-C', self.racer, 'fetch', 'origin', 'master')
        self.git('-C', self.racer, 'reset', '--hard', 'FETCH_HEAD')
        self.git('-C', self.racer, 'rm', 'waiting/agent.md')
        self.git('-C', self.racer, 'commit', '-m', 'remove shard')
        self.git('-C', self.racer, 'push', 'origin', 'HEAD:master')
        self.assertEqual(self.git('-C', self.shared, 'rev-parse', 'origin/master'), old_head)
        result = self.publish('waiting/agent.md')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(result.stdout.strip(), old_head)
        self.assertEqual(self.git('--git-dir', self.remote, 'show', 'master:waiting/agent.md'), 'preserved bytes')

    def test_idempotent_publication_returns_remote_head(self):
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'agent.md').write_text('same bytes\n')
        first = self.publish('waiting/agent.md')
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.publish('waiting/agent.md')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(self.git('--git-dir', self.remote, 'rev-list', '--count', 'master'), '2')

    def test_push_failure_without_advance_cleans_owned_worktree(self):
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'agent.md').write_text('new bytes\n')
        wrapper = self.root / 'bin'
        wrapper.mkdir()
        git_script = wrapper / 'git'
        git_script.write_text('#!/bin/sh\n'
                              'for arg in "$@"; do [ "$arg" = push ] && exit 1; done\n'
                              'exec "$REAL_GIT" "$@"\n')
        git_script.chmod(0o755)
        env = dict(self.env, PATH=str(wrapper) + os.pathsep + self.env['PATH'], REAL_GIT=REAL_GIT)
        before = self.git('-C', self.shared, 'worktree', 'list', '--porcelain')
        result = self.publish('waiting/agent.md', env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('push failed without a remote advance', result.stderr)
        self.assertEqual(self.git('-C', self.shared, 'worktree', 'list', '--porcelain'), before)
        self.assertEqual(list(self.root.glob('offduty-push.*')), [])
        self.assertEqual(self.git('--git-dir', self.remote, 'rev-list', '--count', 'master'), '1')

    def test_allow_path_is_explicit_and_source_symlink_is_rejected(self):
        (self.source / 'other').mkdir()
        (self.source / 'other' / 'note').write_text('approved exception\n')
        self.assertNotEqual(self.publish('other/note').returncode, 0)
        self.assertEqual(self.publish('other/note', extra=('--allow-path',)).returncode, 0)
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'link').symlink_to(self.source / 'other' / 'note')
        self.assertNotEqual(self.publish('waiting/link').returncode, 0)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'note').write_text('outside source\n')
        (self.source / 'lane-notes').symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.publish('lane-notes/note').returncode, 0)

    def test_existing_remote_symlink_does_not_redirect_copy(self):
        outside = self.root / 'outside'
        outside.write_text('untouched\n')
        (self.shared / 'waiting').mkdir()
        (self.shared / 'waiting' / 'agent.md').symlink_to(outside)
        self.git('-C', self.shared, 'add', 'waiting/agent.md')
        self.git('-C', self.shared, 'commit', '-m', 'remote link')
        self.git('-C', self.shared, 'push', 'origin', 'HEAD:master')
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'agent.md').write_text('new bytes\n')
        self.assertNotEqual(self.publish('waiting/agent.md').returncode, 0)
        self.assertEqual(outside.read_text(), 'untouched\n')

    def test_existing_remote_directory_symlink_does_not_redirect_copy(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.shared / 'waiting').symlink_to(outside, target_is_directory=True)
        self.git('-C', self.shared, 'add', 'waiting')
        self.git('-C', self.shared, 'commit', '-m', 'remote directory link')
        self.git('-C', self.shared, 'push', 'origin', 'HEAD:master')
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'agent.md').write_text('new bytes\n')
        result = self.publish('waiting/agent.md')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((outside / 'agent.md').exists())

    def test_three_remote_advances_stop_with_stage_preserved(self):
        (self.source / 'waiting').mkdir()
        shard = self.source / 'waiting' / 'agent.md'
        shard.write_text('staged bytes\n')
        wrapper = self.root / 'bin'
        wrapper.mkdir()
        counter = self.root / 'race-count'
        git_script = wrapper / 'git'
        git_script.write_text('#!/bin/sh\n'
                              'for arg in "$@"; do [ "$arg" = push ] && is_push=1; done\n'
                              'if [ "${is_push:-}" = 1 ]; then\n'
                              '  n=0; [ ! -e "$RACE_COUNT" ] || n=$(cat "$RACE_COUNT")\n'
                              '  n=$((n + 1)); printf "%s\\n" "$n" > "$RACE_COUNT"\n'
                              '  "$REAL_GIT" -C "$RACE_CLONE" fetch origin master >&2 || exit $?\n'
                              '  "$REAL_GIT" -C "$RACE_CLONE" reset --hard FETCH_HEAD >&2 || exit $?\n'
                              '  printf "race %s\\n" "$n" > "$RACE_CLONE/race$n"\n'
                              '  "$REAL_GIT" -C "$RACE_CLONE" add "race$n" || exit $?\n'
                              '  "$REAL_GIT" -C "$RACE_CLONE" commit -m "race $n" >&2 || exit $?\n'
                              '  "$REAL_GIT" -C "$RACE_CLONE" push origin HEAD:master >&2 || exit $?\n'
                              'fi\n'
                              'exec "$REAL_GIT" "$@"\n')
        git_script.chmod(0o755)
        env = dict(self.env, PATH=str(wrapper) + os.pathsep + self.env['PATH'],
                   REAL_GIT=REAL_GIT, RACE_COUNT=str(counter), RACE_CLONE=str(self.racer))
        before = self.git('-C', self.shared, 'worktree', 'list', '--porcelain')
        result = self.publish('waiting/agent.md', env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('push failed after three remote advances', result.stderr)
        self.assertEqual(counter.read_text().strip(), '3')
        self.assertEqual(shard.read_text(), 'staged bytes\n')
        self.assertEqual(self.git('-C', self.shared, 'worktree', 'list', '--porcelain'), before)
        self.assertEqual(list(self.root.glob('offduty-push.*')), [])

    def test_retries_non_fast_forward_on_latest_remote_commit(self):
        (self.source / 'receipts').mkdir()
        (self.source / 'waiting').mkdir()
        (self.source / 'waiting' / 'agent.md').write_text('{"event":"' + 'a' * 32 + '","session_id":"agent"}\n')
        (self.source / 'receipts' / ('a' * 32 + '.json')).write_text('{"event":"' + 'a' * 32 + '","shard":"waiting/agent.md","status":"retired"}\n')
        (self.racer / 'racer.txt').write_text('other writer\n')
        (self.racer / 'waiting').mkdir()
        (self.racer / 'receipts').mkdir()
        (self.racer / 'waiting' / 'other.md').write_text('{"event":"' + 'b' * 32 + '","session_id":"other"}\n')
        (self.racer / 'receipts' / ('b' * 32 + '.json')).write_text('{"event":"' + 'b' * 32 + '","shard":"waiting/other.md","status":"retired"}\n')
        self.git('-C', self.racer, 'add', 'racer.txt', 'waiting', 'receipts')
        self.git('-C', self.racer, 'commit', '-m', 'race')
        wrapper = self.root / 'bin'
        wrapper.mkdir()
        marker = self.root / 'raced'
        git_script = wrapper / 'git'
        git_script.write_text('#!/bin/sh\n'
                              'for arg in "$@"; do [ "$arg" = push ] && is_push=1; done\n'
                              'if [ "${is_push:-}" = 1 ] && [ ! -e "$RACE_MARKER" ]; then\n'
                              '  : > "$RACE_MARKER"\n'
                              '  "$REAL_GIT" -C "$RACE_CLONE" push origin HEAD:master >&2 || exit $?\n'
                              'fi\n'
                              'exec "$REAL_GIT" "$@"\n')
        git_script.chmod(0o755)
        env = dict(self.env, PATH=str(wrapper) + os.pathsep + self.env['PATH'],
                   REAL_GIT=REAL_GIT, RACE_MARKER=str(marker), RACE_CLONE=str(self.racer))
        result = self.publish('receipts/' + 'a' * 32 + '.json', 'waiting/agent.md', env=env,
                              extra=('--build-index', str(INDEX_BUILDER)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.exists())
        self.assertEqual(self.git('--git-dir', self.remote, 'show', 'master:racer.txt'), 'other writer')
        index = self.git('--git-dir', self.remote, 'show', 'master:waiting/INDEX.md')
        self.assertIn('[agent.md]', index)
        self.assertIn('[other.md]', index)
        self.assertEqual(self.git('--git-dir', self.remote, 'rev-list', '--count', 'master'), '3')

    def test_retry_rechecks_duplicate_session_on_new_remote_tip(self):
        event = 'a' * 32
        (self.source / 'waiting').mkdir()
        (self.source / 'receipts').mkdir()
        (self.source / 'waiting' / 'agent.md').write_text(
            '{"event":"' + event + '","session_id":"same-session"}\n')
        (self.source / 'receipts' / (event + '.json')).write_text(
            '{"event":"' + event + '","shard":"waiting/agent.md","status":"retired"}\n')
        (self.racer / 'waiting').mkdir()
        (self.racer / 'waiting' / 'other.md').write_text(
            '{"event":"' + 'b' * 32 + '","session_id":"same-session"}\n')
        self.git('-C', self.racer, 'add', 'waiting/other.md')
        self.git('-C', self.racer, 'commit', '-m', 'racing duplicate')
        wrapper = self.root / 'bin'
        wrapper.mkdir()
        git_script = wrapper / 'git'
        git_script.write_text('#!/bin/sh\n'
                              'for arg in "$@"; do [ "$arg" = push ] && is_push=1; done\n'
                              'if [ "${is_push:-}" = 1 ] && [ ! -e "$RACE_MARKER" ]; then\n'
                              '  : > "$RACE_MARKER"\n'
                              '  "$REAL_GIT" -C "$RACE_CLONE" push origin HEAD:master >&2 || exit $?\n'
                              'fi\n'
                              'exec "$REAL_GIT" "$@"\n')
        git_script.chmod(0o755)
        marker = self.root / 'raced'
        env = dict(self.env, PATH=str(wrapper) + os.pathsep + self.env['PATH'],
                   REAL_GIT=REAL_GIT, RACE_MARKER=str(marker), RACE_CLONE=str(self.racer))
        result = self.publish('receipts/' + event + '.json', 'waiting/agent.md', env=env,
                              extra=('--build-index', str(INDEX_BUILDER),
                                     '--session-id', 'same-session', '--event-id', event))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('session already has a preserved shard', result.stderr)
        self.assertTrue(marker.exists())
        self.assertEqual(self.git('--git-dir', self.remote, 'rev-list', '--count', 'master'), '2')

    def test_distinct_caller_events_may_share_unknown_session(self):
        (self.source / 'waiting').mkdir()
        (self.source / 'receipts').mkdir()
        for event, name in (('a' * 32, 'first.md'), ('b' * 32, 'second.md')):
            (self.source / 'waiting' / name).write_text(
                '{"event":"' + event + '","session_id":"unknown"}\n')
            (self.source / 'receipts' / (event + '.json')).write_text(
                '{"event":"' + event + '","shard":"waiting/' + name + '","status":"retired"}\n')
            result = self.publish('waiting/' + name, 'receipts/' + event + '.json',
                                  extra=('--build-index', str(INDEX_BUILDER),
                                         '--session-id', 'unknown', '--event-id', event))
            self.assertEqual(result.returncode, 0, result.stderr)
        index = self.git('--git-dir', self.remote, 'show', 'master:waiting/INDEX.md')
        self.assertIn('[first.md]', index)
        self.assertIn('[second.md]', index)


if __name__ == '__main__':
    unittest.main()
