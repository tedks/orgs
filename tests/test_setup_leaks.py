#!/usr/bin/env python3
"""Keep setup details out of the current portable source (history is retained)."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Split literals so this guard does not itself contain setup leaks.
FORBIDDEN = re.compile('|'.join(re.escape(word) for word in (
    '/ho' + 'me/', 'frame' + 'work0', 'to' + 'wer0', 'dry' + 'nwyn',
    'splin' + 'ter0', 'splin' + 'ter1', 'homes' + '-imac', 'te' + 'dks',
    '~/Projects/' + 'dotfiles', '~/Projects/' + 'orgs', 'chaos-speech-p-' + 'ted',
)))
PUBLIC_TOOL = re.compile(r'(?:(?:https://github\.com/)|(?:github:))' + 'te' + r'dks/ditz(?=[/#\s`.]|$)')


def leaks(text):
    return FORBIDDEN.findall(PUBLIC_TOOL.sub('PUBLIC_TOOL', text))


class SetupLeaks(unittest.TestCase):
    def test_guard_detects_fixture_and_preserves_public_tool(self):
        self.assertTrue(leaks('/ho' + 'me/alice'))
        self.assertTrue(leaks('frame' + 'work0.local'))
        self.assertEqual(leaks('https://github.com/' + 'te' + 'dks/ditz/blob/master/README.md'), [])
        self.assertTrue(leaks('https://github.com/' + 'te' + 'dks/private'))

    def test_tracked_tree_has_no_personal_setup(self):
        result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], check=True, capture_output=True)
        failures = []
        for name in result.stdout.decode().split('\0'):
            path = ROOT / name
            if not name or path.is_symlink() or not path.is_file():
                continue
            try:
                content = path.read_text()
            except UnicodeError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if leaks(line):
                    failures.append(f'{name}:{number}: {line}')
        self.assertEqual(failures, [], '\n'.join(failures))


if __name__ == '__main__':
    unittest.main()
