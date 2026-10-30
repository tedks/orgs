"""Linux self identity. No active-window fallback and no caller-chosen targets."""
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import subprocess


class IdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Identity:
    harness: str
    pid: int
    starttime: str
    boot_id: str
    socket: str
    pane: str
    cwd: str

    def public(self):
        return asdict(self)


def process(pid, proc=Path('/proc')):
    """Read parent and start time without splitting the parenthesized comm."""
    raw = (proc / str(pid) / 'stat').read_text()
    end = raw.rfind(')')
    if end < 0:
        raise IdentityError('malformed process stat')
    fields = raw[end + 2:].split()
    try:
        parent, start = int(fields[1]), fields[19]
        if not start.isdigit():
            raise ValueError()
        return parent, start
    except (ValueError, IndexError) as exc:
        raise IdentityError('malformed process stat') from exc


def _harness(comm):
    return next((name for name in ('claude', 'codex')
                 if comm == name or re.fullmatch(name + r'-[0-9].*', comm)), None)


def discover(pid=None, proc=Path('/proc')):
    """Nearest harness owns the MCP. Stop there even when it has no tmux."""
    pid = os.getpid() if pid is None else pid
    seen = set()
    try:
        boot = (proc / 'sys/kernel/random/boot_id').read_text().strip()
        if not boot:
            raise IdentityError('boot identity unavailable')
        for _ in range(64):
            if pid <= 1 or pid in seen:
                break
            seen.add(pid)
            base = proc / str(pid)
            parent, start = process(pid, proc)
            comm = (base / 'comm').read_text().strip()
            # Linux comm truncates at 15 bytes; support the native binary and
            # known version suffixes, not arbitrary names beginning "codex".
            harness = _harness(comm)
            if harness:
                env = dict(item.split('=', 1) for item in
                           (base / 'environ').read_bytes().decode('utf-8', 'surrogateescape').split('\0')
                           if '=' in item)
                pane = env.get('TMUX_PANE', '')
                tmux = env.get('TMUX', '').rsplit(',', 2)
                if (not re.fullmatch(r'%[0-9]+', pane) or len(tmux) != 3
                        or not tmux[0].startswith('/') or not all(x.isdigit() for x in tmux[1:])):
                    raise IdentityError('nearest harness is outside tmux or lacks a valid tmux identity')
                cwd = os.readlink(base / 'cwd')
                if process(pid, proc)[1] != start:
                    raise IdentityError('harness changed during discovery')
                return Identity(harness, pid, start, boot, tmux[0], pane, cwd)
            pid = parent
    except (OSError, UnicodeError) as exc:
        raise IdentityError('cannot read own harness ancestry') from exc
    raise IdentityError('no supported harness in process ancestry')


def same_process(identity, proc=Path('/proc')):
    """False only for demonstrable process end/reuse; unreadable is unknown."""
    try:
        boot = (proc / 'sys/kernel/random/boot_id').read_text().strip()
        if not boot:
            raise IdentityError('boot identity unavailable')
        return boot == identity.boot_id and process(identity.pid, proc)[1] == identity.starttime
    except FileNotFoundError:
        # Missing boot metadata is not proof that this process exited.
        if not (proc / str(identity.pid)).exists():
            return False
        raise IdentityError('cannot verify process identity')
    except OSError as exc:
        raise IdentityError('cannot verify process identity') from exc


def verify_pane(identity, proc=Path('/proc')):
    """Exact inventory match plus harness ancestry under the pane root PID."""
    if not same_process(identity, proc):
        raise IdentityError('own harness process ended or changed')
    try:
        result = subprocess.run(
            ['tmux', '-S', identity.socket, 'list-panes', '-a', '-F', '#{pane_id}\t#{pane_pid}\t#{pane_dead}'],
            capture_output=True, text=True, check=True, timeout=5)
        matches = list({tuple(row.split('\t')) for row in result.stdout.splitlines()
                        if row.split('\t')[0] == identity.pane})
        if len(matches) != 1 or len(matches[0]) != 3 or matches[0][2] != '0':
            raise IdentityError('pinned pane missing, ambiguous or dead')
        root = int(matches[0][1])
        pid = identity.pid
        seen = set()
        for _ in range(64):
            # A nested headless harness inherits tmux environment from its
            # outer harness. That pane belongs to the outer interactive one.
            if pid != identity.pid and _harness((proc / str(pid) / 'comm').read_text().strip()):
                raise IdentityError('nested harness does not own an interactive pane')
            if pid == root:
                return
            if pid <= 1 or pid in seen:
                break
            seen.add(pid)
            pid = process(pid, proc)[0]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise IdentityError('cannot verify own tmux pane') from exc
    raise IdentityError('pinned pane does not own this harness')
