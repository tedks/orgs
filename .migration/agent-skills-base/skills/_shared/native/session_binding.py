"""Observed native session for a pinned process; no target selection or action.

Callers choose the process: self tools use their own verified ancestry, while
retirement pins an explicitly selected peer. A missing observation is never a
session ID. The provider readers own their formats and read limits.
"""

from dataclasses import dataclass
from pathlib import Path
import re

from harness_identity import IdentityError, same_process


_UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
MAX_ENV_BYTES = 1024 * 1024
MAX_POINTER_BYTES = 256


@dataclass(frozen=True)
class ProcessPin:
    pid: int
    starttime: str
    boot_id: str


def _environment(pin, proc):
    with (proc / str(pin.pid) / 'environ').open('rb') as stream:
        raw = stream.read(MAX_ENV_BYTES + 1)
    if len(raw) > MAX_ENV_BYTES:
        raise ValueError('pinned_environment_too_large')
    return dict(item.split(b'=', 1) for item in raw.split(b'\0') if b'=' in item)


def _claude_directories(pin, proc):
    """Use only directories named by the pinned process environment."""
    environment = _environment(pin, proc)
    home = environment.get(b'HOME')
    if not home:
        raise ValueError('pinned_home_unavailable')
    home = Path(home.decode('utf-8', 'surrogateescape'))
    if not home.is_absolute():
        raise ValueError('relative_pinned_home')
    directories = [home / '.claude/session-state']
    configured = environment.get(b'CLAUDE_CONFIG_DIR')
    if configured:
        configured = Path(configured.decode('utf-8', 'surrogateescape'))
        if not configured.is_absolute():
            raise ValueError('relative_claude_config')
        directories.insert(0, configured / 'session-state')
    return list(dict.fromkeys(directories))


def _has_pinned_codex_home(pin, proc):
    environment = _environment(pin, proc)
    return bool(environment.get(b'CODEX_HOME') or environment.get(b'HOME'))


def observe_native_session(harness, pin, *, proc=Path('/proc'), claude_state_dirs=None,
                           codex_home=None):
    """Return observed/unavailable with one native UUID and private evidence.

    ``claude_state_dirs`` and ``codex_home`` are test/installed-path overrides;
    production callers normally use the pinned process environment. Every
    present Claude pointer must agree. Verify the process on both sides of the
    read so a reused PID cannot lend another session its binding.
    """
    def unavailable(reason):
        return {'state': 'unavailable', 'reason': reason}

    if (type(pin.pid) is not int or pin.pid <= 0 or not pin.starttime or not pin.boot_id
            or harness not in ('claude', 'codex')):
        return unavailable('invalid_process_pin')
    try:
        if not same_process(pin, proc):
            return unavailable('pinned_process_changed')
        if harness == 'claude':
            directories = (list(claude_state_dirs) if claude_state_dirs is not None
                           else _claude_directories(pin, proc))
            if not directories or any(not Path(item).is_absolute() for item in directories):
                return unavailable('claude_pointer_directory_unavailable')
            found = []
            for directory in dict.fromkeys(Path(item) for item in directories):
                pointer = directory / f'current.{pin.pid}'
                try:
                    with pointer.open('rb') as stream:
                        raw = stream.read(MAX_POINTER_BYTES + 1)
                except FileNotFoundError:
                    continue
                if len(raw) > MAX_POINTER_BYTES:
                    return unavailable('invalid_claude_pointer_size')
                fields = raw.decode('utf-8').split()
                if (len(fields) != 3 or not _UUID.fullmatch(fields[0])
                        or fields[1:] != [pin.starttime, pin.boot_id]):
                    return unavailable('stale_or_invalid_claude_pointer')
                found.append((fields[0], str(pointer)))
            if not found:
                result = unavailable('claude_pointer_unavailable')
            elif len({sid.lower() for sid, _ in found}) != 1:
                result = unavailable('conflicting_claude_pointers')
            else:
                # The installed statusline writes under HOME/.claude, the last
                # directory. Use that pointer's original spelling when present:
                # its UUID is also the snapshot filename and JSON value.
                sid = next((value for value, path in found if Path(path).parent == Path(directories[-1])),
                           found[0][0])
                result = {'state': 'observed', 'session_id': sid,
                          'source': 'claude_pointer', 'pointer_paths': [path for _, path in found],
                          'status_dir': str(directories[-1])}
        else:
            from codex_status import read_codex_status
            if codex_home is None and not _has_pinned_codex_home(pin, proc):
                return unavailable('pinned_codex_home_unavailable')
            options = {'proc': proc}
            if codex_home is not None:
                options['home'] = Path(codex_home)
            observation = read_codex_status(pin.pid, **options)
            sid = observation.get('session_id') if isinstance(observation, dict) else None
            if (not isinstance(observation, dict) or observation.get('state') != 'observed'
                    or not isinstance(sid, str) or not _UUID.fullmatch(sid)):
                result = unavailable('codex_rollout_unavailable')
                if isinstance(observation, dict):
                    result['observation'] = observation
            else:
                result = {'state': 'observed', 'session_id': sid.lower(),
                          'source': 'codex_rollout', 'transcript_path': observation.get('rollout_path'),
                          'observation': observation}
        if not same_process(pin, proc):
            return unavailable('pinned_process_changed')
        return result
    except (IdentityError, OSError, UnicodeError, ValueError, TypeError):
        return unavailable('native_binding_unreadable')
