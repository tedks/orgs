#!/usr/bin/env python3
"""Keep setup details out of the public skill and harness source.

The protocol's historical planning and lesson documents are outside this guard:
they contain existing machine paths. Keep new public tooling under the scanned
paths, and review documentation separately before publishing it. See ditz
orgs-public-docs-leak-guard for a documented broader docs policy.
"""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TOOLING_PATHS = ('skills', 'harness-control', 'tests', 'flake.nix', 'flake.lock')
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

    def test_public_tooling_has_no_personal_setup(self):
        result = subprocess.run(
            ['git', '-C', str(ROOT), 'ls-files', '-z', '--', *PUBLIC_TOOLING_PATHS],
            check=True, capture_output=True,
        )
        names = result.stdout.decode().split('\0')
        self.assertIn('skills/spawn-agent/SKILL.md', names)
        self.assertIn('harness-control/harness_control.py', names)
        failures = []
        for name in names:
            path = ROOT / name
            if not name or path.is_symlink() or not path.is_file():
                continue
            content = path.read_bytes().decode('utf-8', errors='replace')
            for number, line in enumerate(content.splitlines(), 1):
                if leaks(line):
                    failures.append(f'{name}:{number}: {line}')
        self.assertEqual(failures, [], '\n'.join(failures))

    def test_invalid_utf8_cannot_hide_setup_details(self):
        payload = b'\xff/ho' + b'me/alice'
        self.assertTrue(leaks(payload.decode('utf-8', errors='replace')))


if __name__ == '__main__':
    unittest.main()
