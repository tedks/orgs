#!/usr/bin/env python3
"""Kill a recorded mutant with EACH deletion case through the real hook.

Temporary files contain hook fixtures only. Command strings are JSON data;
no rm or other deletion command in the cases is executed.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

here = Path(__file__).resolve().parent
source = (here / 'block-destructive.sh').read_text()
test = here / 'test-block-destructive.sh'
cases = re.findall(r'^deletion_case (\w+) (ALLOW|BLOCK) ', test.read_text(), re.M)
assert cases and len(cases) == len(set(name for name, _ in cases))


def change(old, new):
    assert source.count(old) == 1, f'mutation target changed: {old!r}'
    return source.replace(old, new)


# Reconstruct the original raw-text deletion guard, leaving other guards intact.
legacy = source[:source.index('# Deletion guard:')] + source[source.index('DANGEROUS_PATTERNS=('):]
legacy = legacy.replace('DANGEROUS_PATTERNS=(', "DANGEROUS_PATTERNS=(\n  'rm -rf'\n  'rm -fr'", 1)
mutants = {
    'original-broad': legacy,
    'preserve-double-slash': change("directory = '/' + directory.lstrip('/')",
                                    'directory = directory'),
    'remove-runtime-fallback': change(
        '  DELETION_REASON="Deletion check unavailable (requires Python 3). Restore the hook runtime before retrying."',
        '  : # runtime failure silently allowed'),
    'invert-runtime-status': change('if ! DELETION_REASON=$(python3', 'if DELETION_REASON=$(python3'),
    'absent-deletion-check': change('if recursive:', 'if False:'),
    'broad-recursive': change('def unsafe(word):', "def unsafe(word):\n    return 'all recursive deletion'"),
    'force-recursive': change('if recursive:', 'if True:'),
    'ignore-double-dash': change("options = False\n        elif", "recursive = True\n        elif"),
    'merge-separators': change('yield None', 'pass  # lose command boundary'),
    'ignore-redirection': change("if token in ('<', '>'):", 'if False:'),
    'unmatched-bracket-glob': change('def token(text, globs, home):', 'def token(text, globs, home):\n    return text, globs, home'),
    'ignore-home': change('if home:', 'if False:'),
    'ignore-else': change("'do', 'then', 'else', 'elif'", "'do', 'then', 'elif'"),
    'ignore-braces': change("c in ';|&()<>{}'", "c in ';|&()<>'"),
    'ignore-bang': change("'until', '!', 'time'", "'until', 'time'"),
    'ignore-time': change("'until', '!', 'time'", "'until', '!'"),
    'ignore-timeout': change("elif name == 'timeout' and i + 1 < len(segment):", "elif False:"),
}
# Additional ALLOW cases whose purpose is a parsing boundary use that boundary's
# targeted mutant rather than borrowing a failure on their safe literal operand.
focused = {
    'double_slash_tmp': 'preserve-double-slash',
    'double_slash_var_tmp': 'preserve-double-slash',
    'double_slash_shm': 'preserve-double-slash',
    'runtime_enabled': 'invert-runtime-status',
    'runtime_failure': 'remove-runtime-fallback',
    'nonrecursive': 'force-recursive',
    'option_boundary': 'ignore-double-dash',
    'separator': 'merge-separators',
    'newline_separator': 'merge-separators',
    'redirection_target': 'ignore-redirection',
    'unmatched_bracket': 'unmatched-bracket-glob',
    'bracket_other_word': 'unmatched-bracket-glob',
    'bracket_quoted_close': 'unmatched-bracket-glob',
    'home_expansion': 'ignore-home',
    'home_glob': 'ignore-home',
    'home_user': 'ignore-home',
    'else_rm': 'ignore-else',
    'brace_rm': 'ignore-braces',
    'bang_rm': 'ignore-bang',
    'time_rm': 'ignore-time',
    'timeout_rm': 'ignore-timeout',
}
failures = 0
with tempfile.TemporaryDirectory(prefix='deletion-hook-mutants-') as scratch:
    paths = {}
    for name, code in mutants.items():
        path = Path(scratch) / (name + '.sh')
        path.write_text(code)
        paths[name] = path

    def run(case, mutant):
        env = dict(os.environ, HOOK_UNDER_TEST=str(paths[mutant]), DELETION_CASE_ONLY=case)
        return subprocess.run(['bash', str(test)], env=env, text=True, capture_output=True)

    for case, expected in cases:
        if case == 'runtime_failure':
            names = [focused[case]]
        elif expected == 'BLOCK':
            names = ['absent-deletion-check']
            if case in focused:
                names.append(focused[case])
        elif case in focused:
            # Also prove the original's false positive where its spelling matches.
            names = [focused[case]]
            if run(case, 'original-broad').returncode == 1:
                names.insert(0, 'original-broad')
        else:
            # Separate/long flags were missed by the original; broaden its same
            # policy at the parsed recursive-command boundary for those cases.
            result = run(case, 'original-broad')
            names = ['original-broad' if result.returncode == 1 else 'broad-recursive']
        for name in names:
            result = run(case, name)
            # A nonzero subprocess or syntax failure doesn't count as a kill:
            # require the exact named assertion to report the intended mismatch.
            mismatch = f'case {case}: FAIL  want={expected}'
            if result.returncode == 1 and mismatch in result.stdout and not result.stderr:
                evidence = next(line for line in result.stdout.splitlines() if line.startswith(f'case {case}:'))
                print(f'KILLED {name}: {evidence}')
            else:
                failures += 1
                print(f'SURVIVED/INVALID {name}: {case}\n{result.stdout}{result.stderr}')
if failures:
    raise SystemExit(f'{failures} cases failed mutation verification')
print(f'Mutation verification passed: every one of {len(cases)} deletion cases killed its assigned mutant.')
