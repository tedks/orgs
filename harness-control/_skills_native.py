"""Resolve installed skills and load canonical native readers, without fallback."""
import os
from pathlib import Path

_NAMES = frozenset(('harness_identity', 'session_binding', 'codex_status'))
_GUIDANCE = 'install the orgs skills before starting harness-control; set AGENT_SKILLS_ROOT to the absolute skills directory for staging'
_raw = os.environ.get('AGENT_SKILLS_ROOT')
if _raw is not None and (not _raw or not Path(_raw).is_absolute()):
    raise ImportError('invalid AGENT_SKILLS_ROOT; ' + _GUIDANCE)
_ROOT = Path(_raw).resolve() if _raw is not None else (Path.home() / '.claude/skills').resolve()


def _canonical(relative):
    native = (_ROOT / '_shared/native').resolve()
    path = (native / relative).resolve()
    if not path.is_relative_to(native):
        raise ImportError('canonical helper escapes configured skills root: ' + str(path))
    if not path.is_file():
        raise ImportError('canonical helper unavailable: ' + str(path) + '; ' + _GUIDANCE)
    return path


def load_into(name, namespace):
    if name not in _NAMES:
        raise ImportError('unsupported canonical helper: ' + name)
    path = _canonical(name + '.py')
    namespace['__agent_skills_source__'] = str(path)
    # Preserve the compatibility module's __file__ for existing identity guards.
    exec(compile(path.read_bytes(), str(path), 'exec'), namespace)


def native_test_path(name):
    if name not in _NAMES:
        raise ImportError('unsupported canonical helper test: ' + name)
    return _canonical('tests/test-' + name.replace('_', '-') + '.py')


def spawn_transport_path():
    directory = (_ROOT / 'spawn-agent').resolve()
    path = (directory / 'scripts/tmux-message.sh').resolve()
    if not path.is_relative_to(directory):
        raise ImportError('canonical transport escapes configured skills root: ' + str(path))
    if not path.is_file():
        raise ImportError('canonical transport unavailable: ' + str(path) + '; ' + _GUIDANCE)
    if not os.access(path, os.X_OK):
        raise ImportError('canonical transport is not executable: ' + str(path) + '; ' + _GUIDANCE)
    return path
