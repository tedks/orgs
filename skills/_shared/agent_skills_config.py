#!/usr/bin/env python3
"""Load the portable skills configuration. Python 3.11+, standard library only."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import stat
import tomllib

KEYS = {
    'projects_root': str,
    'operator.name': str,
    'off_duty.path': str,
    'off_duty.remote': str,
    'doctrine.roles_path': str,
    'tmux.socket': str,
    'fleet.hosts': list,
    'harness.codex_bin': str,
    'github.owner': str,
}
EMPTY = {'off_duty.remote', 'doctrine.roles_path', 'tmux.socket', 'github.owner'}
PATHS = {'projects_root', 'off_duty.path', 'doctrine.roles_path'}


def _validate(key, value):
    if type(value) is not KEYS[key]:
        raise ValueError(f'{key}: expected {KEYS[key].__name__}')
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, str) or any(ord(c) < 32 or ord(c) == 127 for c in item):
            raise ValueError(f'{key}: expected text without control characters')
        if not item.strip() and not (item == '' and key in EMPTY):
            raise ValueError(f'{key}: must not be blank')
    if key == 'fleet.hosts' and any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9@._-]*', host) for host in value):
        raise ValueError('fleet.hosts: invalid SSH host')
    if key == 'github.owner' and value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', value):
        raise ValueError('github.owner: expected GitHub user or organization')
    if key in PATHS and value and not Path(value).expanduser().is_absolute():
        raise ValueError(f'{key}: expected absolute path or ~/path')
    if key == 'harness.codex_bin' and '/' in value and not Path(value).expanduser().is_absolute():
        raise ValueError('harness.codex_bin: expected absolute path or executable name')
    if key == 'tmux.socket' and '/' in value and not Path(value).expanduser().is_absolute():
        raise ValueError('tmux.socket: expected label or absolute socket path')
    return value


def load_config():
    """Validate file first, then overrides; return fresh nested values each call."""
    if 'AGENT_SKILLS_CONFIG' in os.environ:
        location = os.environ['AGENT_SKILLS_CONFIG']
        if not location or not Path(location).expanduser().is_absolute():
            raise ValueError('AGENT_SKILLS_CONFIG: expected nonempty absolute file path')
        path = Path(location).expanduser()
    else:
        location = os.environ.get('XDG_CONFIG_HOME') or '~/.config'
        if not Path(location).expanduser().is_absolute():
            raise ValueError('XDG_CONFIG_HOME: expected absolute directory path')
        path = Path(location).expanduser() / 'agent-skills/config.toml'
    try:
        with path.open('rb') as stream:
            raw = tomllib.load(stream)
    except FileNotFoundError:
        if 'AGENT_SKILLS_CONFIG' in os.environ:
            raise ValueError(f'explicit configuration file does not exist: {path}')
        raw = {}
    flat = {}
    for section, value in raw.items():
        if section in KEYS:
            flat[section] = _validate(section, value)
        elif section in {key.split('.')[0] for key in KEYS if '.' in key} and isinstance(value, dict):
            for name, item in value.items():
                key = section + '.' + name
                if key not in KEYS:
                    raise ValueError(f'unknown key: {key}')
                flat[key] = _validate(key, item)
        else:
            raise ValueError(f'unknown key or invalid table: {section}')
    for key in KEYS:
        name = 'AGENT_SKILLS_' + key.upper().replace('.', '_')
        if name in os.environ:
            value = os.environ[name]
            if KEYS[key] is list:
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(f'{name}: expected JSON string array') from exc
            flat[key] = _validate(key, value)
    projects = flat.get('projects_root', '~/Projects')
    defaults = {'projects_root': projects, 'operator.name': 'the operator',
                'off_duty.path': str(Path(projects).expanduser() / 'agent-handoffs'),
                'off_duty.remote': '', 'doctrine.roles_path': '', 'tmux.socket': '',
                'fleet.hosts': [], 'harness.codex_bin': 'codex', 'github.owner': ''}
    values = defaults | flat
    for key in PATHS | {'harness.codex_bin', 'tmux.socket'}:
        if values[key] and (key in PATHS or '/' in values[key]):
            values[key] = os.path.expanduser(values[key])
    result = {}
    for key, value in values.items():
        if '.' in key:
            section, name = key.split('.')
            result.setdefault(section, {})[name] = value
        else:
            result[key] = value
    return result


def tmux_command(config=None):
    """Explicit overrides > valid current tmux > configured fallback > default."""
    config = load_config() if config is None else config
    if os.environ.get('SPAWN_TMUX_SOCKET'):
        return ['tmux', '-S', os.environ['SPAWN_TMUX_SOCKET']]
    if os.environ.get('SPAWN_TMUX_LABEL'):
        return ['tmux', '-L', os.environ['SPAWN_TMUX_LABEL']]
    socket = config['tmux']['socket']
    if os.environ.get('AGENT_SKILLS_TMUX_SOCKET'):
        return ['tmux', '-S' if '/' in socket else '-L', socket]
    if os.environ.get('TMUX'):
        active = os.environ['TMUX'].split(',')[0]
        try:
            if stat.S_ISSOCK(Path(active).stat().st_mode):
                return ['tmux', '-S', active]
        except OSError:
            pass
        raise ValueError('active TMUX socket unavailable; supply an explicit socket override')
    if socket:
        return ['tmux', '-S' if '/' in socket else '-L', socket]
    return ['tmux']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('get', 'validate'))
    parser.add_argument('key', nargs='?', choices=tuple(KEYS))
    args = parser.parse_args()
    if args.action == 'get' and args.key is None:
        parser.error('get requires a key')
    try:
        config = load_config()
        if args.action == 'get':
            value = config
            for part in args.key.split('.'):
                value = value[part]
            print(json.dumps(value) if isinstance(value, list) else value)
        elif args.action != 'validate':
            print(json.dumps(config))
    except (OSError, ValueError) as exc:
        print(f'agent-skills config: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
