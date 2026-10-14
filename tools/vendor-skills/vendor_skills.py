#!/usr/bin/env python3
"""Pin a bounded agent-skills snapshot from local Git objects; never fetch or delete."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ('ask-agent', 'initialize-repo', 'spawn-agent', 'stacked-prs')
SHARED = ('skills/_shared/agent_skills_config.py', 'skills/_shared/config.sh', 'skills/_shared/configuration.md')
REPOSITORY = 'https://github.com/tedks/agent-skills'
VENDOR = Path('vendor/agent-skills')
LOCK = Path('vendor/agent-skills.lock.json')
LINKS = {f'.claude/skills/{name}': f'../../vendor/agent-skills/skills/{name}' for name in (*SKILLS, '_shared')}
LINKS['.agents/skills'] = '../.claude/skills'


def fail(message):
    raise ValueError(message)


def contained_path(name):
    """Accept only the published source subset, including its component license."""
    if not isinstance(name, str) or any(ord(c) < 32 for c in name) or '\\' in name:
        fail(f'Invalid snapshot path: {name!r}')
    parts = PurePosixPath(name).parts
    if name != str(PurePosixPath(name)) or '..' in parts or name.startswith('/'):
        fail(f'Invalid snapshot path: {name!r}')
    if name != 'LICENSE' and name not in SHARED and not (len(parts) >= 3 and parts[0] == 'skills' and parts[1] in SKILLS):
        fail(f'Path outside snapshot scope: {name}')
    return name


def regular_parents(path):
    """Refuse symlinked destinations, including an ancestor redirected outside ROOT."""
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        if parent.is_symlink():
            fail(f'Refusing symlinked destination: {parent.relative_to(ROOT)}')
        if parent.exists() and parent != path and not parent.is_dir():
            fail(f'Parent is not a directory: {parent.relative_to(ROOT)}')


def git(checkout, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_NO_LAZY_FETCH='1', GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0',
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    result = subprocess.run(['git', '-C', str(checkout), *args], capture_output=True, env=env)
    if result.returncode:
        fail(f'Local Git read failed: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def source_snapshot(checkout, commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        fail('--commit must be a full, lowercase 40-character Git commit ID')
    if git(checkout, 'cat-file', '-t', commit).strip() != b'commit':
        fail('--commit must identify a commit object')
    raw = git(checkout, 'ls-tree', '-rz', commit, '--', 'LICENSE', *(f'skills/{name}' for name in SKILLS), *SHARED)
    files, content = {}, {}
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        metadata, encoded = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode('ascii').split()
        name = contained_path(encoded.decode('utf-8'))
        if mode not in ('100644', '100755') or kind != 'blob':
            fail(f'Unsupported source entry (only regular files allowed): {name}')
        data = git(checkout, 'cat-file', 'blob', oid)
        content[name] = data
        files[name] = {'mode': mode, 'sha256': hashlib.sha256(data).hexdigest()}
    required = ['LICENSE', *(f'skills/{name}/SKILL.md' for name in SKILLS), *SHARED]
    if any(name not in files for name in required):
        fail('Source commit lacks LICENSE, one of the four skills, or _shared')
    if b'GNU AFFERO GENERAL PUBLIC LICENSE' not in content['LICENSE'] or b'Version 3' not in content['LICENSE']:
        fail('Source LICENSE is not the expected AGPLv3 license')
    return {'version': 1, 'repository': REPOSITORY, 'commit': commit, 'files': files}, content


def read_lock():
    regular_parents(ROOT / LOCK)
    data = json.loads((ROOT / LOCK).read_text())
    if (set(data) != {'version', 'repository', 'commit', 'files'} or data['version'] != 1
            or data['repository'] != REPOSITORY or not isinstance(data['commit'], str)
            or not re.fullmatch(r'[0-9a-f]{40}', data['commit']) or not isinstance(data['files'], dict)):
        fail('Invalid snapshot lock metadata')
    for name, entry in data['files'].items():
        contained_path(name)
        if (not isinstance(entry, dict) or set(entry) != {'mode', 'sha256'}
                or entry['mode'] not in ('100644', '100755') or not isinstance(entry['sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])):
            fail(f'Invalid manifest entry: {name}')
    required = ['LICENSE', *(f'skills/{name}/SKILL.md' for name in SKILLS), *SHARED]
    if any(name not in data['files'] for name in required):
        fail('Incomplete snapshot manifest')
    return data


def inventory():
    base = ROOT / VENDOR
    regular_parents(base)
    if not base.is_dir():
        fail('Missing vendor snapshot')
    files, directories = set(), set()
    for directory, children, leaves in os.walk(base, followlinks=False):
        for name in children + leaves:
            path = Path(directory) / name
            relative = path.relative_to(base).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode):
                files.add(relative)
            elif stat.S_ISDIR(mode):
                directories.add(relative)
            else:
                fail(f'Unexpected non-regular vendor entry: {relative}')
    return files, directories


def check_links(allow_missing=False):
    for name, target in LINKS.items():
        path = ROOT / name
        regular_parents(path.parent)
        if not path.exists() and not path.is_symlink() and allow_missing:
            continue
        if not path.is_symlink() or os.readlink(path) != target:
            fail(f'Unexpected skill discovery entry: {name}; expected symlink to {target}')
        if not allow_missing and not path.is_dir():
            fail(f'Broken skill discovery entry: {name}')


def verify():
    data = read_lock()
    actual, directories = inventory()
    expected = set(data['files'])
    if actual != expected:
        fail(f'Vendor file drift; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}')
    expected_dirs = {str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) != '.'}
    if directories != expected_dirs:
        fail(f'Vendor directory drift: {sorted(directories ^ expected_dirs)}')
    for name, entry in data['files'].items():
        path = ROOT / VENDOR / name
        mode = '100755' if path.stat().st_mode & 0o111 else '100644'
        if mode != entry['mode'] or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            fail(f'Vendor content/mode drift: {name}')
    check_links()
    return data


def sync(checkout, commit):
    data, content = source_snapshot(checkout, commit)
    regular_parents(ROOT / LOCK)
    regular_parents(ROOT / VENDOR)
    if (ROOT / LOCK).exists():
        old = verify()
        removed = set(old['files']) - set(data['files'])
        if removed:
            fail('Source removes files; no changes made. Regenerate only after separately reviewed snapshot cleanup:\n'
                 + '\n'.join(str(ROOT / VENDOR / name) for name in sorted(removed)))
    elif (ROOT / VENDOR).exists():
        fail('Refusing an existing vendor directory without its lock')
    check_links(allow_missing=True)
    # Preflight every destination before writing any snapshot file.
    for name in content:
        path = ROOT / VENDOR / name
        regular_parents(path)
        if path.exists() and not path.is_file():
            fail(f'Expected regular destination: {path.relative_to(ROOT)}')
    for name in sorted(content):
        path = ROOT / VENDOR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content[name])
        path.chmod(int(data['files'][name]['mode'][-3:], 8))
    for name, target in LINKS.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_symlink():
            path.symlink_to(target)
    (ROOT / LOCK).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    verify()
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify', help='Check all vendor contents, modes, and local discovery links offline')
    update = commands.add_parser('sync', help='Read only committed files from an explicit local Git checkout')
    update.add_argument('--checkout', required=True, type=Path)
    update.add_argument('--commit', required=True)
    args = parser.parse_args()
    try:
        data = verify() if args.command == 'verify' else sync(args.checkout, args.commit)
    except (ValueError, OSError, UnicodeError, TypeError, AttributeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    print(f'OK: {len(data["files"])} vendored files at {data["commit"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
