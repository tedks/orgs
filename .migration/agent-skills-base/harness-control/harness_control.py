"""Bounded self-control via the published tmux-message transport.

Assumptions: Linux process identity and session/transcript binding are supplied
by the server, never tool callers. JSONL is an observed, unsupported harness
format; rotation/truncation/unreadability is unknown, not completion. A compact
witness proves a NEW boundary, not that every instruction survived. Same-user
processes are trusted; mode 0700/0600 protects receipts from other users.

request returns before dispatch. Call compact/exit last, then end the turn.
A detached observer records delivery separately from completion. No automatic
retry, peer termination, transcript content logging or composer manipulation.
"""
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import threading
import uuid
import unicodedata

sys.dont_write_bytecode = True  # Shared installed readers remain read-only.

from harness_identity import Identity, IdentityError, same_process, verify_pane
from _skills_native import spawn_transport_path

TRANSPORT = spawn_transport_path()
# Reserve all configured waits and slow tmux calls before any input. The shared
# sender bounds each tmux call at 5s: resolve/lock/readiness 15s, final
# sample + paste 30s, confirmation 26s + at most 20.25s loop overrun.
# 95s covers that 91.25s path plus overhead; stalls get SIGTERM receipt grace.
SEND_TIMEOUT = 95
SEND_GRACE = 3
SEND_DRAIN = 2
SEND_BUDGET = SEND_TIMEOUT + SEND_GRACE + SEND_DRAIN
COMPACT_WATCH = 30  # reserve completion observation after dispatch
PREFLIGHT_BUDGET = 15  # pane/session/tail checks and private receipt/payload writes
TERMINAL = {'completed', 'completed_by_other', 'delivered', 'deferred', 'ambiguous', 'failed', 'cancelled', 'unconfirmed', 'timed_out', 'continuation_failed'}
_ID = re.compile(r'[0-9a-f]{32}')
MAX_FILE = 8 * 1024 * 1024
# Measured on Claude Code 2.1.283/2.1.301 and Codex CLI 0.157.1/0.163.0.
# Changed UI fails closed.
_COMPACT_MARKERS = {'claude': 'Compacted (ctrl+o to see full summary)', 'codex': '• Context compacted'}
_CLAUDE_COMPACT_ROW = re.compile(r'^[ \t]*⎿[ \t]+Compacted(?: \(ctrl\+o to see full summary\))?[ \t]*$', re.MULTILINE)
_CLAUDE_COMPACTING = re.compile(r'^\s*[✢✽✻·✶*] Compacting conversation… \([0-9][^()\n]*\)\s*$', re.MULTILINE)
SAMPLE_JOIN = 7  # verify_pane <=5s plus public read <=1s, then shutdown margin


class ControlError(RuntimeError):
    pass


class OperationInProgress(ControlError):
    def __init__(self, operation_id, state, next_action):
        self.operation_id = operation_id
        self.state = state
        self.next_action = next_action
        super().__init__(f'operation_in_progress:{operation_id}:{state}; {next_action}')


class _SenderNotStarted(ControlError):
    pass


def _private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ControlError('state_directory_not_private')


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ControlError('record_not_private')
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ControlError('record_too_large')
    return json.loads(data)


def _write(path, value):
    if value.get('action') in ('compact', 'exit', 'send'):
        fields = ('state', 'reason', 'deadline', 'turns_seen')
        nested = ('idle', 'focus_idle', 'focus_delivery', 'delivery', 'completion',
                  'continuation', 'failure_notice')
        snapshot = {key: value.get(key) for key in fields}
        snapshot.update({key: value.get(key, {}).get('state') if isinstance(value.get(key), dict) else None for key in nested})
        previous = _read(path) if path.exists() else None
        old = None if previous is None else {**{key: previous.get(key) for key in fields},
                                              **{key: previous.get(key, {}).get('state') if isinstance(previous.get(key), dict) else None for key in nested}}
        value['transitions'] = list(value.get('transitions', previous.get('transitions', []) if previous else []))
        if snapshot != old:
            value['transitions'].append({'at': time.time(), **snapshot})
    temporary = path.with_name('.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _guard(directory):
    fd = os.open(directory / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _git(repo, *args):
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                                check=True, timeout=10)
        return result.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ControlError('checkpoint_git_evidence_unavailable') from exc


def verify_checkpoint(evidence):
    """Verify shard bytes/commit; explicitly label all unverified attestations.

    A fresh master fetch establishes the shard commit and bytes on the
    configured remote. Privacy, durability, and disposition remain attestations.
    """
    if not isinstance(evidence, dict):
        raise ControlError('checkpoint_evidence_required')
    for key in ('private_storage_attested', 'obligations_preserved', 'pause_state_preserved'):
        if evidence.get(key) is not True:
            raise ControlError('checkpoint_attestation_required:' + key)
    if evidence.get('resources_disposition') not in ('released', 'handed_off', 'active_recorded'):
        raise ControlError('resources_disposition_required')
    if evidence.get('authority') not in ('exit_authorized', 'compact_authorized'):
        raise ControlError('explicit_authority_required')
    for key in ('pause_state_reference', 'active_inventory_reference'):
        if not isinstance(evidence.get(key), str) or not evidence[key].strip():
            raise ControlError('checkpoint_reference_required:' + key)
    push = evidence.get('push_attestation')
    if push not in ('pushed_private_remote', 'no_remote_configured'):
        raise ControlError('checkpoint_push_attestation_required')
    digest, commit = evidence.get('sha256'), evidence.get('commit')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ControlError('invalid_shard_hash')
    if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise ControlError('exact_commit_required')
    try:
        repo, path = Path(evidence['repo_path']).resolve(), Path(evidence['shard_path']).resolve()
        relative = path.relative_to(repo)
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise ControlError('invalid_shard_file')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ControlError('invalid_shard_path') from exc
    if actual != digest:
        raise ControlError('shard_hash_mismatch')
    if _git(repo, 'cat-file', '-t', commit).strip() != b'commit':
        raise ControlError('exact_commit_required')
    if hashlib.sha256(_git(repo, 'show', f'{commit}:{relative.as_posix()}')).hexdigest() != digest:
        raise ControlError('shard_not_in_commit')
    remotes = _git(repo, 'remote').decode().splitlines()
    if push == 'no_remote_configured' and remotes:
        raise ControlError('repository_has_remote')
    if push == 'pushed_private_remote' and not remotes:
        raise ControlError('repository_has_no_remote')
    verified = ['shard_sha256', 'shard_bytes_in_exact_commit']
    if push == 'pushed_private_remote':
        fetched_ref = 'refs/harness-control/checkpoint-' + uuid.uuid4().hex
        try:
            _git(repo, 'fetch', 'origin', '+refs/heads/master:' + fetched_ref)
            remote_head = _git(repo, 'rev-parse', '--verify', fetched_ref).strip().decode()
            try:
                present = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', commit, remote_head],
                                         capture_output=True, timeout=10).returncode == 0
            except (OSError, subprocess.SubprocessError) as exc:
                raise ControlError('checkpoint_git_evidence_unavailable') from exc
            if not present:
                raise ControlError('shard_not_on_origin_master')
            try:
                remote_bytes = _git(repo, 'show', f'{remote_head}:{relative.as_posix()}')
            except ControlError as exc:
                raise ControlError('shard_not_on_origin_master') from exc
        finally:
            subprocess.run(['git', '-C', str(repo), 'update-ref', '-d', fetched_ref], capture_output=True, timeout=10)
        if hashlib.sha256(remote_bytes).hexdigest() != digest:
            raise ControlError('shard_not_on_origin_master')
        verified.append('remote_presence')
    return {'verified': verified,
            'attested_not_verified': ['private_storage', 'remote_privacy', 'authority',
                                      'resources_disposition', 'obligations', 'pause_state'],
            'evidence': evidence}


def _baseline(path):
    with Path(path).open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ControlError('invalid_transcript')
        end = info.st_size
        if end:
            stream.seek(end - 1)
        complete = not end or stream.read(1) == b'\n'
    return {'device': info.st_dev, 'inode': info.st_ino, 'offset': end, 'skip_fragment': not complete}


def _compact_event(path, baseline, harness, session_id):
    """Read only newly appended complete records; never a historical boundary."""
    with Path(path).open('rb') as stream:
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != (baseline['device'], baseline['inode']) or info.st_size < baseline['offset']:
            raise ControlError('transcript_replaced_or_truncated')
        stream.seek(baseline['offset'])
        remaining = info.st_size - baseline['offset']
        if remaining > MAX_FILE:
            raise ControlError('transcript_observation_limit')
        data = stream.read(remaining)
    lines = data.splitlines(keepends=True)
    if baseline['skip_fragment'] and lines:
        lines = lines[1:]
    for line in lines:
        if not line.endswith(b'\n'):
            continue
        try:
            row = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise ControlError('malformed_transcript_record') from exc
        if not isinstance(row, dict):
            raise ControlError('malformed_transcript_record')
        if harness == 'claude':
            found = (row.get('type') == 'system' and row.get('subtype') == 'compact_boundary' and
                     row.get('sessionId') == session_id and row.get('isSidechain') is not True)
        else:
            found = row.get('type') == 'compacted' and isinstance(row.get('payload'), dict)
        if found:
            return {'source': 'transcript', 'event': 'compact_boundary' if harness == 'claude' else 'compacted',
                    'observed_at': time.time(),
                    'event_timestamp': row.get('timestamp') if isinstance(row.get('timestamp'), str) else None, 'causality': 'new_event_after_baseline_not_command_attribution'}
    return None


def _native_idle(record, focus_after=None):
    """Measured Claude Code 2.1.283 / Codex CLI 0.157.1 root-turn markers.

    Read a bounded tail; never persist message content. Completion is evidence
    of observed idle, not an atomic reservation against later human input.
    """
    path, baseline = record['transcript_path'], record['idle_baseline']
    cursor = record.get('_idle_cursor')
    key = [baseline['offset'], focus_after]
    fresh = not cursor or cursor['key'] != key
    cancel_on_turn = record.get('action') == 'compact' and focus_after is None
    with Path(path).open('rb') as stream:
        info = os.fstat(stream.fileno())
        if ((info.st_dev, info.st_ino) != (baseline['device'], baseline['inode']) or
                info.st_size < baseline['offset'] or not stat.S_ISREG(info.st_mode)):
            raise ControlError('idle_transcript_replaced_or_truncated')
        if fresh:
            start = max(0, baseline['offset'] - MAX_FILE)
            cursor = {'key': key, 'offset': start, 'idle': False, 'turn': None, 'turn_offset': -1,
                      'parent': None, 'focus_seen': focus_after is None, 'final_assistant': False,
                      'focus_input_seen': False, 'focus_turn_seen': False,
                      'turns_seen': 0, 'user_turns_seen': 0, 'queued_input_seen': False,
                      'children': []}
        else:
            start = cursor['offset']
        if info.st_size < start:
            raise ControlError('idle_transcript_replaced_or_truncated')
        if info.st_size - max(start, baseline['offset']) > MAX_FILE:
            raise ControlError('idle_observation_limit')
        stream.seek(start)
        data = stream.read(info.st_size - start)
    if cursor.get('error'):
        raise ControlError(cursor['error'])
    lines = data.splitlines(keepends=True)
    if fresh and start and lines:
        start += len(lines.pop(0))
    incomplete = bool(lines and not lines[-1].endswith(b'\n'))
    if incomplete:
        lines.pop()  # retain partial bytes at cursor.offset for the next poll
    idle, turn, turn_offset = cursor['idle'], cursor['turn'], cursor['turn_offset']
    parent, focus_seen, final_assistant = cursor['parent'], cursor['focus_seen'], cursor['final_assistant']
    focus_input_seen, focus_turn_seen, children = cursor['focus_input_seen'], cursor['focus_turn_seen'], cursor['children']
    turns_seen = cursor.get('turns_seen', 0)
    user_turns_seen = cursor.get('user_turns_seen', 0)
    queued_input_seen = cursor.get('queued_input_seen', False)
    for line in lines:
        offset = start
        start += len(line)
        try:
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise ControlError('idle_transcript_malformed') from exc
            if not isinstance(row, dict):
                raise ControlError('idle_transcript_malformed')
            kind = row.get('type')
            if record['identity']['harness'] == 'codex':
                payload = row.get('payload')
                if kind == 'event_msg':
                    if not isinstance(payload, dict):
                        raise ControlError('idle_event_malformed')
                    event = payload.get('type')
                    if event == 'task_started':
                        candidate = payload.get('turn_id')
                        if isinstance(candidate, str) and payload.get('root_turn_id') not in (None, candidate):
                            children.append(candidate)
                            continue
                        if offset >= baseline['offset']:
                            if not cancel_on_turn and (focus_after is None or offset < focus_after or focus_turn_seen):
                                raise ControlError('superseded_by_new_input')
                            if cancel_on_turn:
                                turns_seen += 1
                            else:
                                focus_turn_seen = True
                        turn = payload.get('turn_id')
                        turn_offset = offset
                        if not isinstance(turn, str) or not turn or payload.get('root_turn_id') != turn:
                            raise ControlError('idle_root_turn_unavailable')
                        idle = False
                        focus_seen = focus_after is None
                    elif event == 'task_complete':
                        if payload.get('turn_id') in children:
                            continue
                        candidate = payload.get('turn_id')
                        # A long root turn can start more than MAX_FILE before
                        # the checkpoint. Its own completion is still a native
                        # root-turn witness when both IDs agree and no newer
                        # input has appeared since the baseline.
                        if (turn is None and offset >= baseline['offset'] and
                                isinstance(candidate, str) and candidate and
                                payload.get('root_turn_id') == candidate):
                            turn, turn_offset = candidate, offset
                        idle = bool(turn and candidate == turn and focus_seen)
                    elif event != 'token_count':
                        idle = False
                elif kind == 'response_item':
                    idle = False
                    if not isinstance(payload, dict):
                        raise ControlError('idle_response_malformed')
                    if payload.get('type') == 'message' and payload.get('role') == 'user' and offset >= baseline['offset']:
                        content = payload.get('content')
                        exact = (isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict) and
                                 content[0].get('type') == 'input_text' and content[0].get('text') == record.get('focus'))
                        if not cancel_on_turn and (focus_after is None or offset < focus_after or focus_input_seen or not focus_turn_seen or not exact):
                            raise ControlError('superseded_by_new_input')
                        if not cancel_on_turn:
                            focus_input_seen = True
                    if (focus_after is not None and offset >= focus_after and turn_offset >= focus_after and turn and
                            payload.get('type') == 'message' and payload.get('role') == 'user'):
                        content = payload.get('content')
                        focus_seen = (isinstance(content, list) and len(content) == 1 and
                                      isinstance(content[0], dict) and content[0].get('type') == 'input_text' and
                                      content[0].get('text') == record['focus'])
                elif kind in ('turn_context', 'compacted'):
                    idle = False
                elif kind not in ('session_meta', 'token_usage_record', 'world_state'):
                    raise ControlError('idle_record_shape_unknown')
            else:
                if kind in ('api-request-shape', 'api-request-blob', 'api-request'):
                    if row.get('isSidechain') is True:
                        continue
                    if row.get('sessionId') != record['session_id']:
                        raise ControlError('idle_metadata_malformed')
                    if kind == 'api-request':
                        idle = False
                    continue
                if kind == 'queue-operation' and offset >= baseline['offset']:
                    if row.get('isSidechain') is True:
                        continue
                    if row.get('sessionId') != record['session_id']:
                        raise ControlError('idle_metadata_malformed')
                    # Queue ops can precede the current turn's duration and
                    # describe several pending inputs. Native rows do not
                    # establish that the whole queue drained before dispatch.
                    if cancel_on_turn:
                        queued_input_seen = True
                        turns_seen = max(user_turns_seen, 1)
                    else:
                        raise ControlError('superseded_by_new_input')
                metadata = {'mode': 'mode', 'permission-mode': 'permissionMode', 'atis-latch': 'atis',
                            'ai-title': 'aiTitle', 'last-prompt': 'lastPrompt'}
                if kind in metadata:
                    if row.get('sessionId') != record['session_id'] or not isinstance(row.get(metadata[kind]), str):
                        raise ControlError('idle_metadata_malformed')
                    continue
                if kind == 'system' and row.get('subtype') == 'compact_boundary':
                    if row.get('sessionId') != record['session_id'] or row.get('isSidechain') is True:
                        raise ControlError('idle_metadata_malformed')
                    if record['action'] != 'compact' and offset >= baseline['offset']:
                        raise ControlError('native_compaction_boundary')
                    idle = False
                    final_assistant = False
                    if isinstance(row.get('uuid'), str) and row['uuid']:
                        parent = row['uuid']
                    continue
                if kind not in ('user', 'assistant', 'tool', 'attachment', 'system'):
                    if kind not in ('file-history-snapshot', 'queue-operation', 'progress'):
                        raise ControlError('idle_record_shape_unknown')
                    if kind != 'file-history-snapshot':
                        idle = False
                    continue
                if row.get('isSidechain') is True:
                    continue
                if row.get('sessionId') != record['session_id'] or row.get('isSidechain') is not False:
                    raise ControlError('idle_root_session_unavailable')
                if (kind == 'attachment' and offset >= baseline['offset'] and
                        isinstance(row.get('attachment'), dict) and row['attachment'].get('type') == 'queued_command'):
                    if cancel_on_turn:
                        queued_input_seen = True
                        turns_seen = max(user_turns_seen, 1)
                    else:
                        raise ControlError('superseded_by_new_input')
                identifier = row.get('uuid')
                if not isinstance(identifier, str) or not identifier:
                    raise ControlError('idle_row_identity_unavailable')
                linked = parent is not None and row.get('parentUuid') == parent
                if kind in ('user', 'assistant', 'tool'):
                    idle = False
                    message = row.get('message')
                    if not isinstance(message, dict):
                        raise ControlError('idle_message_malformed')
                    content = message.get('content')
                    user_input = not (isinstance(content, list) and bool(content) and
                                      all(isinstance(c, dict) and c.get('type') == 'tool_result' for c in content))
                    if (kind == 'user' and user_input and row.get('isMeta') is not True and
                            row.get('isCompactSummary') is not True and offset >= baseline['offset']):
                        exact = content == record.get('focus') or (isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict) and content[0].get('text') == record.get('focus'))
                        if not cancel_on_turn and (focus_after is None or offset < focus_after or focus_input_seen or not exact):
                            raise ControlError('superseded_by_new_input')
                        if cancel_on_turn:
                            user_turns_seen += 1
                            turns_seen = max(user_turns_seen, int(queued_input_seen))
                        else:
                            focus_input_seen = True
                    if kind == 'user' and focus_after is not None and offset >= focus_after:
                        # Tool-result rows do not begin a new user input generation.
                        if isinstance(content, str):
                            focus_seen = content == record['focus']
                        elif isinstance(content, list) and any(isinstance(c, dict) and c.get('type') == 'text' for c in content):
                            focus_seen = len(content) == 1 and content[0].get('text') == record['focus']
                    final_assistant = (kind == 'assistant' and message.get('stop_reason') == 'end_turn' and
                                       isinstance(content, list) and any(isinstance(c, dict) and c.get('type') == 'text' for c in content))
                elif kind == 'system' and row.get('subtype') == 'turn_duration':
                    idle = (linked and final_assistant and focus_seen and
                            type(row.get('durationMs')) in (int, float) and row['durationMs'] >= 0 and
                            type(row.get('messageCount')) is int and row['messageCount'] > 0)
                    turn = identifier
                elif kind == 'system' and row.get('subtype') == 'compact_boundary':
                    idle = False
                    final_assistant = False
                    focus_seen = focus_after is None
                if not linked and parent is not None:
                    idle = False
                    final_assistant = False
                parent = identifier
        except ControlError as exc:
            if start > baseline['offset']:
                cursor['error'] = str(exc)
                record['_idle_cursor'] = cursor
                raise
            idle, turn, turn_offset, parent, final_assistant = False, None, -1, None, False
            focus_seen = focus_after is None
    cursor.update(offset=start, idle=idle, turn=turn, turn_offset=turn_offset, parent=parent,
                  focus_seen=focus_seen, final_assistant=final_assistant,
                  focus_input_seen=focus_input_seen, focus_turn_seen=focus_turn_seen,
                  turns_seen=turns_seen, user_turns_seen=user_turns_seen,
                  queued_input_seen=queued_input_seen, children=children)
    record['_idle_cursor'] = cursor
    if incomplete:
        return {'state': 'unknown', 'reason': 'idle_transcript_incomplete'}
    return {'state': 'idle' if idle else 'busy_or_unknown', 'source': 'native_root_turn',
            'observed_at': time.time(), 'turn_id': turn, 'offset': start,
            'focus_observed': focus_seen if focus_after is not None else None,
            'turns_seen': turns_seen}


def _wait_idle(record, identity, observer_deadline, focus_after=None, sends=1, operation_path=None):
    """Compact waits for the whole idle bound; dispatch has a fresh budget."""
    last = {'state': 'unknown', 'reason': 'idle_not_observed'}
    reserve = 0 if record.get('action') == 'compact' else sends * (SEND_BUDGET + PREFLIGHT_BUDGET)
    while time.monotonic() <= observer_deadline - reserve:
        if operation_path is not None and _read(operation_path)['state'] == 'cancelled':
            return {'state': 'cancelled', 'reason': 'cancelled_before_dispatch'}
        verify_pane(identity)
        _verify_session(identity, record['session_id'], record.get('claude_state_dir'), record.get('codex_home'))
        try:
            last = _native_idle(record, focus_after)
        except ControlError as exc:
            if record.get('action') == 'compact':
                try:
                    other_event = _compact_event(record['transcript_path'], record['baseline'], identity.harness,
                                                 record['session_id'])
                except (OSError, ValueError, KeyError, TypeError, ControlError):
                    other_event = None
                if other_event:
                    return {'state': 'completed_by_other', 'witness': other_event}
            if str(exc) == 'superseded_by_new_input':
                if record.get('action') == 'compact':
                    return {'state': 'cancelled', 'reason': 'intervening_turn', 'turns_seen': 1}
                return {'state': 'deferred', 'reason': str(exc)}
            if ((record.get('_idle_cursor') or {}).get('error') == str(exc) or
                    str(exc) in ('idle_record_shape_unknown', 'idle_root_session_unavailable',
                                 'idle_metadata_malformed', 'idle_transcript_replaced_or_truncated',
                                 'idle_observation_limit', 'native_compaction_boundary')):
                return {'state': 'deferred', 'reason': str(exc), 'evidence_reason': str(exc)}
            last = {'state': 'unknown', 'reason': str(exc)}
        except (OSError, ValueError, KeyError, TypeError):
            last = {'state': 'unknown', 'reason': 'native_idle_evidence_unavailable'}
        if record.get('action') == 'compact':
            try:
                other_event = _compact_event(record['transcript_path'], record['baseline'], identity.harness,
                                             record['session_id'])
            except (OSError, ValueError, KeyError, TypeError, ControlError):
                other_event = None
            if other_event:
                return {'state': 'completed_by_other', 'witness': other_event}
        if record.get('action') == 'compact' and focus_after is None and last.get('turns_seen', 0):
            return {'state': 'cancelled', 'reason': 'intervening_turn', 'turns_seen': last['turns_seen']}
        if last['state'] == 'idle':
            return last
        remaining = observer_deadline - reserve - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(.5, remaining))
    return {**last, 'state': 'deferred', 'evidence_reason': last.get('reason', last['state']),
            'reason': 'native_idle_not_observed_within_bound' if record.get('action') == 'compact' else 'native_idle_not_observed_with_sender_budget'}


def _pane_marker(identity, timeout=10):
    """Count measured completion rows via public read; never retain pane text."""
    verify_pane(identity)
    try:
        run = subprocess.run([str(TRANSPORT), 'read', identity.pane], env=_environment(identity),
                             capture_output=True, text=True, encoding='utf-8', errors='strict', timeout=timeout, check=True)
        plain = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', run.stdout)
        count = len(_CLAUDE_COMPACT_ROW.findall(plain)) if identity.harness == 'claude' else plain.count(_COMPACT_MARKERS[identity.harness])
        return {'count': count,
                'progress': identity.harness == 'claude' and bool(_CLAUDE_COMPACTING.search(plain)),
                'observed_at': time.time(),
                'source': 'own_pane_marker', 'marker': _COMPACT_MARKERS[identity.harness]}
    except (OSError, subprocess.SubprocessError, KeyError, UnicodeError) as exc:
        raise ControlError('pane_compaction_marker_unavailable') from exc


def _track_progress(result, marker):
    if not marker['progress']:
        result['progress_armed'] = True
    elif result['progress_armed'] and result['progress_started_at'] is None:
        result['progress_started_at'] = marker['observed_at']
    result['samples'] += 1


@contextmanager
def _watch_compaction(identity, baseline):
    """Observe progress while the sole shared sender blocks awaiting receipt.

    A Claude alternate-screen redraw may replace an old success marker at the
    same count. Keep only a NEW native-progress observation, never pane text.
    The final progress->absent+marker check is made after the transcript event.
    """
    stop = threading.Event()
    result = {'available': True, 'progress_started_at': None,
              'progress_armed': not baseline.get('progress', False), 'samples': 0}
    def sample():
        while not stop.is_set():
            try:
                marker = _pane_marker(identity, timeout=1)
                if not stop.is_set():
                    _track_progress(result, marker)
            except (OSError, ValueError, KeyError, TypeError, IdentityError, ControlError):
                pass  # unknown samples confer no authority
            stop.wait(.5)
    thread = threading.Thread(target=sample, daemon=True, name='own-compaction-marker')
    thread.start()
    try:
        yield result
    finally:
        stop.set()
        thread.join(timeout=SAMPLE_JOIN)
        if thread.is_alive():
            result['available'] = False  # stalled final read cannot authorize continuation


def _same_owner(left, right):
    return all(left.get(key) == right.get(key) for key in ('harness', 'pid', 'starttime', 'boot_id', 'socket', 'pane'))


def _public(record, path):
    fields = ('operation_id', 'action', 'state', 'delivery', 'completion', 'reason',
              'created_at', 'updated_at', 'deadline', 'checkpoint_receipt', 'session_id',
              'focus_delivery', 'continuation', 'idle', 'focus_idle', 'failure_notice',
              'watcher_pid', 'idle_bound_seconds', 'turns_seen', 'confirmation_bound_seconds')
    return {**{key: record.get(key) for key in fields}, 'result_path': str(path)}


class HarnessControl:
    def __init__(self, identity, session_id, transcript_path=None, state_dir=None, claude_state_dir=None, codex_home=None):
        if identity.harness not in ('claude', 'codex') or not isinstance(session_id, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', session_id):
            raise ControlError('unsupported_or_missing_session_identity')
        self.identity, self.session_id = identity, session_id
        self.codex_home = str(Path(codex_home)) if codex_home is not None else None
        self.claude_state_dir = str(Path(claude_state_dir)) if claude_state_dir is not None else None
        self.transcript_path = str(transcript_path) if transcript_path else None
        scope = hashlib.sha256(json.dumps([identity.boot_id, identity.pid, identity.starttime, session_id]).encode()).hexdigest()
        root = Path(state_dir) if state_dir else Path.home() / '.local/state/harness-control'
        _private_dir(root)
        self.directory = root / scope
        _private_dir(self.directory)

    def record_checkpoint(self, evidence):
        verified = verify_checkpoint(evidence)
        receipt_id = uuid.uuid4().hex
        record = {**verified, 'receipt_id': receipt_id, 'identity': asdict(self.identity),
                  'session_id': self.session_id, 'recorded_at': time.time()}
        _write(self.directory / ('checkpoint-' + receipt_id + '.json'), record)
        return {'state': 'recorded', 'receipt_id': receipt_id, 'verified': verified['verified'],
                'attested_not_verified': verified['attested_not_verified']}

    def _checkpoint(self, receipt, action):
        if not isinstance(receipt, str) or not _ID.fullmatch(receipt):
            raise ControlError('recorded_checkpoint_required')
        record = _read(self.directory / ('checkpoint-' + receipt + '.json'))
        if not _same_owner(record['identity'], asdict(self.identity)) or record['session_id'] != self.session_id:
            raise ControlError('checkpoint_identity_mismatch')
        verify_checkpoint(record['evidence'])  # changed/uncommitted shards invalidate the receipt
        if action == 'exit' and (record['evidence']['authority'] != 'exit_authorized' or
                                 record['evidence']['resources_disposition'] not in ('released', 'handed_off')):
            raise ControlError('exit_authority_or_resource_disposition_missing')
        return record

    def request(self, action, checkpoint_receipt=None, text=None, timeout_seconds=None, focus=None, checkpoint_path=None, continuation=None):
        if action not in ('compact', 'exit', 'send'):
            raise ControlError('unsupported_action')
        if timeout_seconds is None:
            timeout_seconds = 3600 if action == 'compact' else 300
        minimum = 30 if action == 'compact' else SEND_BUDGET + PREFLIGHT_BUDGET + 5
        maximum = 7200 if action == 'compact' else 600
        if type(timeout_seconds) is not int or not minimum <= timeout_seconds <= maximum:
            raise ControlError(f'timeout_must_be_{minimum}_to_{maximum}_seconds')
        if focus is not None:
            if action != 'compact':
                raise ControlError('focus_only_for_compact')
            _message(focus, ordinary=True)
            if focus != focus.strip():
                raise ControlError('focus_surrounding_whitespace_unsupported')
        if continuation is not None:
            if action != 'compact':
                raise ControlError('continuation_only_for_compact')
            _message(continuation, ordinary=True)
        resume_message = None
        if action == 'send':
            _message(text)
        else:
            checkpoint = self._checkpoint(checkpoint_receipt, action)
            if action == 'compact':
                shard = str(Path(checkpoint['evidence']['shard_path']).resolve())
                if checkpoint_path is not None and (not isinstance(checkpoint_path, str) or str(Path(checkpoint_path).resolve()) != shard):
                    raise ControlError('checkpoint_path_mismatch')
                resume_message = f'CONTINUE: compaction done; resume from {shard}'
                if continuation is not None:
                    resume_message += '\n' + continuation
                _message(resume_message, ordinary=True)
            text = '/compact' if action == 'compact' else '/exit'
        if action in ('compact', 'exit') and not self.transcript_path:
            raise ControlError('transcript_unavailable')
        verify_pane(self.identity)
        with _guard(self.directory):
            active = self.directory / 'active.json'
            if active.exists():
                prior_id = _read(active)['operation_id']
                prior = self._operation(prior_id)
                if prior['state'] not in TERMINAL:
                    cancellable = (prior['state'] in ('accepted', 'scheduled', 'waiting_idle',
                                                      'warning_dispatching', 'watching_other') and
                                   _definitely_not_dispatched(prior.get('delivery', {})))
                    advice = (f'cancel_operation({prior_id}) then retry' if cancellable else
                              f'get_operation({prior_id}) until terminal, then retry')
                    raise OperationInProgress(prior_id, prior['state'], advice)
            worker_fd = os.open(self.directory / '.worker', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(worker_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                if active.exists():
                    prior_id = _read(active)['operation_id']
                    prior = self._operation(prior_id)
                    raise ControlError(f'observer_still_running:{prior_id}:{prior["state"]}; '
                                       f'get_operation({prior_id}) until notice and observer finish, then retry') from exc
                raise ControlError('observer_still_running') from exc
            finally:
                os.close(worker_fd)
            baseline = _baseline(self.transcript_path) if action == 'compact' else None
            operation_id = uuid.uuid4().hex
            now = time.time()
            record = {'operation_id': operation_id, 'action': action,
                      'state': 'scheduled' if action == 'compact' else 'accepted',
                      'identity': asdict(self.identity), 'session_id': self.session_id,
                      'claude_state_dir': self.claude_state_dir, 'codex_home': self.codex_home, 'transcript_path': self.transcript_path, 'baseline': baseline,
                      'idle_baseline': _baseline(self.transcript_path) if action in ('compact', 'exit') else None,
                      'checkpoint_receipt': checkpoint_receipt, 'payload': text, 'focus': focus, 'resume_message': resume_message,
                      'continuation': {'state': 'not_dispatched' if action == 'compact' else 'not_applicable'},
                      'created_at': now, 'updated_at': now, 'deadline': now + timeout_seconds,
                      'idle_bound_seconds': timeout_seconds if action == 'compact' else None,
                      'delivery': {'state': 'not_dispatched'}, 'completion': {'state': 'pending'}}
            path = self.directory / (operation_id + '.json')
            _write(path, record)
            _write(active, {'operation_id': operation_id})
            try:
                watcher = subprocess.Popen(_observer_command(self.directory, operation_id),
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True, close_fds=True)
                record['watcher_pid'] = watcher.pid
                _write(path, record)
            except OSError:
                record.update(state='failed', reason='observer_start_failed', completion={'state': 'not_started'})
                _write(path, record)
            return _public(record, path)

    def _operation(self, operation_id):
        if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
            raise ControlError('invalid_operation_id')
        record = _read(self.directory / (operation_id + '.json'))
        if not _same_owner(record['identity'], asdict(self.identity)) or record['session_id'] != self.session_id:
            raise ControlError('operation_identity_mismatch')
        notice_state = (record.get('failure_notice') or {}).get('state')
        incomplete_cancel_notice = (record['state'] == 'cancelled' and
                                    (notice_state == 'dispatching' or
                                     (record.get('reason') == 'intervening_turn' and notice_state is None)))
        if (incomplete_cancel_notice or record['state'] == 'warning_dispatching' or
                (record['state'] not in TERMINAL and time.time() >= record['deadline'])):
            fd = os.open(self.directory / '.worker', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return record  # live observer owns the final receipt, including continuation
                # The observer's final write does not take .lock. Reload after
                # acquiring its lease so a delivered receipt is not downgraded.
                record = _read(self.directory / (operation_id + '.json'))
                notice_state = (record.get('failure_notice') or {}).get('state')
                if record['state'] == 'cancelled' and (notice_state == 'dispatching' or
                                                      (record.get('reason') == 'intervening_turn' and notice_state is None)):
                    _settle_dispatches(record, 'observer_disappeared')
                    if notice_state is None:
                        record['failure_notice'] = {'state': 'unavailable',
                                                    'reason': 'observer_disappeared_before_notice'}
                    record.pop('pending_final_state', None)
                    _write(self.directory / (operation_id + '.json'), record)
                    return record
                if record['state'] in TERMINAL:
                    return record
                if record['state'] == 'warning_dispatching':
                    _settle_dispatches(record, 'observer_disappeared')
                    pending = record.pop('pending_final_state', 'failed')
                    record['state'] = 'cancelled' if pending == 'watching_other' else pending
                    if pending == 'watching_other' and (record.get('failure_notice') or {}).get('state') is None:
                        record['failure_notice'] = {'state': 'unavailable',
                                                    'reason': 'observer_disappeared_before_notice'}
                elif record['state'] == 'watching_other':
                    record.update(state='cancelled', reason='intervening_turn', completion={'state': 'not_started'})
                else:
                    delivered_compact = record['action'] == 'compact' and record.get('delivery', {}).get('state') == 'delivered'
                    record.update(state='unconfirmed' if delivered_compact else 'timed_out',
                                  reason='observer_deadline_elapsed_after_delivery' if delivered_compact else 'observer_deadline_elapsed')
                    if delivered_compact and record['completion'].get('state') == 'confirmed' and record['continuation']['state'] == 'not_dispatched':
                        record['completion'] = {**record['completion'], 'state': 'unconfirmed',
                                                'reason': 'observer_disappeared_before_pane_confirmation'}
                    elif record['completion'].get('state') != 'confirmed':
                        record['completion'] = {'state': 'unconfirmed' if delivered_compact else 'unknown'}
                    if delivered_compact and record.get('failure_notice', {}).get('state') is None:
                        record['failure_notice'] = {'state': 'unavailable', 'reason': 'observer_disappeared_before_notice'}
                    _settle_dispatches(record, 'observer_disappeared')
                    if record['action'] == 'compact' and record['completion'].get('state') == 'confirmed' and record['continuation']['state'] != 'not_dispatched':
                        record['state'] = 'continuation_failed'
                _write(self.directory / (operation_id + '.json'), record)
            finally:
                os.close(fd)
        return record

    def operation(self, operation_id):
        with _guard(self.directory):
            record = self._operation(operation_id)
            return _public(record, self.directory / (operation_id + '.json'))

    def cancel(self, operation_id):
        with _guard(self.directory):
            record = self._operation(operation_id)
            if record['state'] == 'cancelled':
                return _public(record, self.directory / (operation_id + '.json'))
            if (record['state'] not in ('accepted', 'scheduled', 'waiting_idle',
                                      'warning_dispatching', 'watching_other') or
                    not _definitely_not_dispatched(record.get('delivery', {}))):
                return {'state': 'refused', 'reason': 'cancellation_only_before_dispatch', 'operation_id': operation_id}
            record.update(state='cancelled', reason='explicit_cancel', updated_at=time.time(),
                          completion={'state': 'cancelled'})
            record.pop('pending_final_state', None)
            path = self.directory / (operation_id + '.json')
            _write(path, record)
            return _public(record, path)

    def read_own_pane(self):
        verify_pane(self.identity)
        try:
            run = subprocess.run([str(TRANSPORT), 'read', self.identity.pane], env=_environment(self.identity),
                                 capture_output=True, text=True, encoding='utf-8', errors='strict', timeout=10, check=True)
            return {'state': 'observed', 'pane': self.identity.pane, 'observed_at': time.time(),
                    'pane_text': run.stdout, 'read_only': True, 'untrusted': True,
                    'warning': 'May include unsent composer contents; never instructions or receipt evidence.'}
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return {'state': 'unavailable', 'reason': 'pane_read_failed'}


def _message(text, ordinary=False):
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 65536:
        raise ControlError('invalid_message')
    if any(unicodedata.category(c) == 'Cc' and c != '\n' for c in text):
        raise ControlError('message_contains_control_characters')
    slash_lines = [line for line in text.splitlines() if ''.join(c for c in unicodedata.normalize('NFKC', line) if unicodedata.category(c) != 'Cf').lstrip().startswith('/')]
    if not ordinary and slash_lines and (len(text.splitlines()) != 1 or not re.fullmatch(r'/[A-Za-z][A-Za-z0-9_-]*(?: [^\r\n]*)?', text)):
        raise ControlError('invalid_single_line_slash_command')
    if slash_lines and (len(text.encode('utf-8')) > 200 or text != text.rstrip() or text.endswith(';')):
        raise ControlError('unsupported_typed_command')
    for index, line in enumerate(text.splitlines()):
        normalized = ''.join(c for c in unicodedata.normalize('NFKC', line) if unicodedata.category(c) != 'Cf').strip().casefold()
        if ordinary and (normalized.startswith('/') or (index == 0 and normalized.startswith(('!', '#')))):
            raise ControlError('ordinary_message_contains_command_prefix')
        lifecycle = (normalized.startswith('/') and any(name.startswith(normalized.split()[0][1:])
                     for name in ('compact', 'exit', 'quit', 'q')))
        if ((ordinary and normalized.startswith('/')) or lifecycle):
            raise ControlError('lifecycle_commands_require_typed_control')


def _verify_session(identity, session_id, claude_state_dir=None, codex_home=None):
    """Rebind immediately before dispatch, including post-compaction continuation."""
    from session_binding import observe_native_session
    options = {}
    if identity.harness == 'claude' and claude_state_dir is not None:
        options['claude_state_dirs'] = [Path(claude_state_dir)]
    if identity.harness == 'codex' and codex_home is not None:
        options['codex_home'] = Path(codex_home)
    binding = observe_native_session(identity.harness, identity, **options)
    if binding['state'] != 'observed' or binding['session_id'] != session_id:
        raise ControlError('live_session_binding_changed_or_unavailable')


def _transport_run(command, identity):
    """Own only this sender subprocess; SIGTERM lets it preserve pending input.

    The shared shell entrypoint execs Python and handles SIGTERM. A stuck sender
    gets one grace interval before kill. Never retry an interrupted attempt.
    """
    try:
        process = subprocess.Popen(command, env=_environment(identity), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='strict', start_new_session=True)
    except OSError as exc:
        raise _SenderNotStarted('sender_start_failed') from exc
    try:
        stdout, stderr = process.communicate(timeout=SEND_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=SEND_GRACE)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = process.communicate(timeout=SEND_DRAIN)
            except subprocess.TimeoutExpired as exc:
                process.stdout.close()
                process.stderr.close()
                raise ControlError('sender_pipes_did_not_close_after_kill') from exc

    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _send(directory, record, identity, text, suffix):
    try:
        verify_pane(identity)
        _verify_session(identity, record['session_id'], record.get('claude_state_dir'), record.get('codex_home'))
        if suffix == '.focus' or text in ('/compact', '/exit'):
            idle = _native_idle(record, record.get('focus_after') if suffix != '.focus' else None)
            if text == '/compact':
                other_event = _compact_event(record['transcript_path'], record['baseline'], identity.harness,
                                             record['session_id'])
                if other_event:
                    return {'state': 'deferred', 'reason': 'compacted_by_other', 'witness': other_event,
                            'needs_review': False}
            if record['action'] == 'compact' and idle.get('turns_seen', 0):
                return {'state': 'deferred', 'reason': 'intervening_turn', 'turns_seen': idle['turns_seen'], 'needs_review': False}
            if idle['state'] != 'idle':
                reason = 'native_idle_changed_before_focus' if suffix == '.focus' else 'native_idle_changed_before_dispatch'
                return {'state': 'deferred', 'reason': reason, 'needs_review': False}
        if record['deadline'] - time.time() < SEND_BUDGET + (COMPACT_WATCH if text == '/compact' else 0):
            return {'state': 'deferred', 'reason': 'insufficient_sender_budget', 'needs_review': False}
        payload = directory / (record['operation_id'] + suffix)
        fd = os.open(payload, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        command = [str(TRANSPORT), 'send', identity.pane, '--backoff',
                   '--max-wait', '5', '--stable-wait', '3', '--render-wait', '3',
                   '--submit-delay', '8', '--receipt-wait', '15', '--retry-wait', '3',
                   '--poll-interval', '0.25']
        if text.startswith('/'):
            command.append('--typed-command')
        command += ['--prompt-file', str(payload)]
        # Filesystem work cannot consume the reserved attempt budget unnoticed.
        if record['deadline'] - time.time() < SEND_BUDGET + (COMPACT_WATCH if text == '/compact' else 0):
            return {'state': 'deferred', 'reason': 'insufficient_sender_budget', 'needs_review': False}
    except (IdentityError, ControlError) as exc:
        if record['action'] == 'compact' and text == '/compact':
            try:
                other_event = _compact_event(record['transcript_path'], record['baseline'], identity.harness,
                                             record['session_id'])
            except (OSError, ValueError, KeyError, TypeError, ControlError):
                other_event = None
            if other_event:
                return {'state': 'deferred', 'reason': 'compacted_by_other', 'witness': other_event,
                        'needs_review': False}
        reason = 'intervening_turn' if record['action'] == 'compact' and str(exc) == 'superseded_by_new_input' else str(exc)
        result = {'state': 'deferred' if str(exc) == 'superseded_by_new_input' else 'not_dispatched',
                  'reason': reason, 'needs_review': False}
        if reason == 'intervening_turn':
            result['turns_seen'] = 1
        return result
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return {'state': 'not_dispatched', 'reason': 'pretransport_evidence_or_payload_unavailable', 'needs_review': False}
    try:
        run = _transport_run(command, identity)
        result = json.loads(run.stdout if run.returncode == 0 else run.stderr)
        if not isinstance(result, dict):
            raise ValueError()
        delivered = run.returncode == 0 and result.get('status') == 'delivered' and result.get('receipt') in ('submitted', 'queued', 'command') and result.get('pane') == identity.pane
        state = 'delivered' if delivered else ('deferred' if run.returncode in (2, 128 + signal.SIGTERM) and result.get('status') == 'deferred' and result.get('input_attempted') is False else 'ambiguous')
        return {'state': state, 'receipt': result.get('receipt') if delivered else None,
                'delivered_at': time.time() if delivered else None,
                'needs_review': state == 'ambiguous' or result.get('needs_review') is True,
                'input_attempted': result.get('input_attempted'), 'pending_file': result.get('pending_file'),
                'reason': result.get('reason')}
    except _SenderNotStarted:
        return {'state': 'not_dispatched', 'needs_review': False, 'reason': 'sender_start_failed'}
    except (OSError, ValueError, subprocess.SubprocessError, ControlError):
        return {'state': 'ambiguous', 'needs_review': True, 'reason': 'sender_receipt_unavailable'}


def _settle_dispatches(record, reason):
    """An interrupted dispatch intent cannot prove whether input was delivered."""
    for key in ('delivery', 'focus_delivery', 'continuation', 'failure_notice'):
        if record.get(key, {}).get('state') == 'dispatching':
            record[key] = {'state': 'ambiguous', 'needs_review': True, 'reason': reason}


def _environment(identity):
    env = {name: value for name, value in os.environ.items()
           if not name.startswith('PYTHON') and name != 'NIX_PYTHONPATH'}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONNOUSERSITE'] = '1'
    env.pop('SPAWN_TMUX_LABEL', None)
    env['SPAWN_TMUX_SOCKET'] = identity.socket
    return env


def _observer_command(directory, operation_id):
    """Re-enter this exact module without ambient Python paths or user packages."""
    return [sys.executable, '-E', '-s', str(Path(__file__).resolve()),
            '--observe', str(directory), operation_id]


def observe(directory, operation_id):
    """Claim only the current accepted operation, atomically with its lease.

    Request/cancel share .lock. A cancelled accepted operation never takes
    .worker. A leased waiting observer remains cancellable until the first-send
    claim; requests cannot replace it until its lease is released. Nonblocking
    lease acquisition preserves the lock order while final receipts need .lock.
    """
    directory = Path(directory)
    _private_dir(directory)
    if not _ID.fullmatch(operation_id):
        raise ControlError('invalid_operation_id')
    path = directory / (operation_id + '.json')
    fd = None
    try:
        with _guard(directory):
            record = _read(path)
            if record['state'] not in ('accepted', 'scheduled') or _read(directory / 'active.json')['operation_id'] != operation_id:
                return
            fd = os.open(directory / '.worker', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            record.update(state='waiting_idle', updated_at=time.time())
            _write(path, record)  # lease claimed; cancellation remains safe before input
        _observe(directory, operation_id, record)
    finally:
        if fd is not None:
            os.close(fd)


def _claim_dispatch(directory, path, record):
    with _guard(directory):
        current = _read(path)
        if current['state'] != 'waiting_idle' or _read(directory / 'active.json')['operation_id'] != record['operation_id']:
            return False
        record.update(state='dispatching', updated_at=time.time())
        _write(path, record)
        return True


def _reserve_compact_dispatch(path, record, *, command):
    """Start sender/confirmation time only after the required native idle."""
    seconds = SEND_BUDGET + PREFLIGHT_BUDGET + (COMPACT_WATCH if command else 0)
    with _guard(path.parent):
        if _read(path)['state'] not in ('waiting_idle', 'dispatching'):
            return None
        record['deadline'] = time.time() + seconds
        _write(path, record)
    return time.monotonic() + seconds


def _definitely_not_dispatched(delivery):
    return (delivery.get('state') == 'not_dispatched' or
            (delivery.get('state') == 'deferred' and delivery.get('input_attempted') is not True and
             delivery.get('needs_review') is not True))


def _failure_notice(directory, path, record, identity):
    """One visible best-effort outcome notice; preserve its dispatch intent."""
    if (record['action'] != 'compact' or record['state'] not in ('warning_dispatching', 'cancelled') or
            record.get('failure_notice', {}).get('state') is not None):
        return
    final_state = record.get('pending_final_state')
    if final_state == 'cancelled' and record.get('reason') == 'intervening_turn':
        turns = record.get('turns_seen')
        turns = turns if type(turns) is int and turns > 0 else 1
        notice = (f"COMPACTION CANCELLED: {turns} turn(s) since your checkpoint; "
                  're-checkpoint and request again')
    elif final_state == 'unconfirmed' and record.get('delivery', {}).get('state') == 'delivered':
        delivered_at = record['delivery'].get('delivered_at')
        when = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(delivered_at)) if delivered_at else 'unknown time'
        bound = record.get('confirmation_bound_seconds', COMPACT_WATCH)
        missing = 'no pane confirmation' if record.get('completion', {}).get('witness') else 'no compaction event'
        advice = ('check /status before taking action' if record.get('completion', {}).get('witness') else
                  'check /status, then re-request or compact manually')
        notice = f'COMPACTION UNCONFIRMED: delivered at {when}, {missing} within {bound}s; {advice}'
    elif _definitely_not_dispatched(record.get('delivery', {})):
        reason = record.get('reason', 'dispatch_unavailable')
        if not isinstance(reason, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', reason):
            reason = 'dispatch_unavailable'
        notice = f'COMPACTION NOT DISPATCHED: {reason}; run /compact yourself or ask a peer'
    else:
        return
    with _guard(directory):
        current = _read(path)
        if current['state'] == 'cancelled' and current.get('reason') == 'explicit_cancel':
            record.update(current)
            return
        record['failure_notice'] = {'state': 'dispatching', 'attempted_at': time.time()}
        record['deadline'] = time.time() + SEND_BUDGET + PREFLIGHT_BUDGET
        _write(path, record)
    try:
        record['failure_notice'] = _send(directory, record, identity, notice, '.failure')
    except Exception:
        record['failure_notice'] = {'state': 'ambiguous', 'needs_review': True,
                                    'reason': 'failure_notice_receipt_unavailable'}
    finally:
        with _guard(directory):
            current = _read(path)
            if current['state'] == 'cancelled':
                current['failure_notice'] = record['failure_notice']
                current.pop('pending_final_state', None)
                current['updated_at'] = time.time()
                _write(path, current)
                record.update(current)
            else:
                record['state'] = record.pop('pending_final_state')
                _write(path, record)


def _observe(directory, operation_id, record):
    """Run a record already claimed under .lock while holding .worker."""
    path = directory / (operation_id + '.json')
    identity = Identity(**record['identity'])
    observer_deadline = time.monotonic() + max(0, record['deadline'] - time.time())
    try:
        if time.time() >= record['deadline']:
            raise ControlError('expired_before_dispatch')
        verify_pane(identity)
        _verify_session(identity, record['session_id'], record.get('claude_state_dir'), record.get('codex_home'))
        if record['action'] in ('compact', 'exit'):
            receipt = _read(directory / ('checkpoint-' + record['checkpoint_receipt'] + '.json'))
            if not _same_owner(receipt['identity'], asdict(identity)) or receipt['session_id'] != record['session_id']:
                raise ControlError('checkpoint_identity_mismatch')
            verify_checkpoint(receipt['evidence'])
        if record['action'] == 'exit' and (receipt['evidence']['authority'] != 'exit_authorized' or
                                           receipt['evidence']['resources_disposition'] not in ('released', 'handed_off')):
            raise ControlError('exit_authority_or_resource_disposition_missing')
        if record['action'] in ('compact', 'exit'):
            record['idle'] = _wait_idle(record, identity, observer_deadline, sends=2 if record.get('focus') else 1, operation_path=path)
            if record['idle']['state'] != 'idle':
                state = record['idle']['state']
                record.update(state=state if state in ('cancelled', 'completed_by_other') else 'deferred',
                              reason=record['idle'].get('reason', 'compacted_by_other'),
                              completion={'state': 'confirmed', 'witness': record['idle']['witness'], 'by_other': True}
                              if state == 'completed_by_other' else {'state': 'not_started'})
                if record['reason'] == 'intervening_turn':
                    record['turns_seen'] = record['idle'].get('turns_seen', 1)
                return
        if record.get('focus'):
            if record['action'] == 'compact':
                observer_deadline = _reserve_compact_dispatch(path, record, command=False)
                if observer_deadline is None:
                    return
            if not _claim_dispatch(directory, path, record):
                return
            record['focus_after'] = _baseline(record['transcript_path'])['offset']
            record['focus_delivery'] = {'state': 'dispatching'}
            _write(path, record)
            record['focus_delivery'] = _send(directory, record, identity, record['focus'], '.focus')
            _write(path, record)
            if record['focus_delivery']['state'] != 'delivered':
                reason = record['focus_delivery'].get('reason')
                record.update(state='cancelled' if reason == 'intervening_turn' else
                              ('failed' if record['focus_delivery']['state'] == 'not_dispatched' else record['focus_delivery']['state']),
                              reason=reason if reason == 'intervening_turn' else 'focus_not_delivered', completion={'state': 'not_started'})
                if reason == 'intervening_turn':
                    record['turns_seen'] = record['focus_delivery'].get('turns_seen') or 1
                return
            if record['action'] == 'compact':
                record['deadline'] = time.time() + record['idle_bound_seconds']
                observer_deadline = time.monotonic() + record['idle_bound_seconds']
                _write(path, record)
            record['focus_idle'] = _wait_idle(record, identity, observer_deadline, record['focus_after'])
            if record['focus_idle']['state'] != 'idle':
                if record['focus_idle']['state'] == 'completed_by_other':
                    record.update(state='completed_by_other', reason='compacted_by_other',
                                  completion={'state': 'confirmed', 'witness': record['focus_idle']['witness'], 'by_other': True})
                    return
                reason = record['focus_idle']['reason'] if record['action'] == 'compact' else 'focus_turn_not_completed_with_sender_budget'
                record.update(state='cancelled' if reason == 'intervening_turn' else 'deferred', reason=reason, completion={'state': 'not_started'})
                if reason == 'intervening_turn':
                    record['turns_seen'] = record['focus_idle'].get('turns_seen', 1)
                return
        verify_pane(identity)
        if record['action'] == 'compact':
            other_event = _compact_event(record['transcript_path'], record['baseline'], identity.harness,
                                         record['session_id'])
            if other_event:
                record.update(state='completed_by_other', reason='compacted_by_other',
                              completion={'state': 'confirmed', 'witness': other_event, 'by_other': True})
                return
            observer_deadline = _reserve_compact_dispatch(path, record, command=True)
            if observer_deadline is None:
                return
            record['baseline'] = _baseline(record['transcript_path'])
            record['pane_baseline'] = _pane_marker(identity)
        if record['state'] == 'waiting_idle' and not _claim_dispatch(directory, path, record):
            return
        record['delivery'] = {'state': 'dispatching'}
        _write(path, record)
        if record['action'] == 'compact':
            with _watch_compaction(identity, record['pane_baseline']) as samples:
                record['delivery'] = _send(directory, record, identity, record['payload'], '.payload')
            record['pane_sampling'] = dict(samples)
        else:
            record['delivery'] = _send(directory, record, identity, record['payload'], '.payload')
        record.update(updated_at=time.time(), state='observing')
        if record['action'] == 'compact' and record['delivery']['state'] == 'delivered':
            record['confirmation_bound_seconds'] = max(0, int(observer_deadline - time.monotonic()))
        _write(path, record)
        if record['action'] == 'send':
            record['state'] = 'failed' if record['delivery']['state'] == 'not_dispatched' else record['delivery']['state']
            record['completion'] = {'state': 'unsupported', 'reason': 'message_acceptance_only'}
        elif record['delivery']['state'] in ('deferred', 'not_dispatched'):
            reason = record['delivery'].get('reason')
            state = ('completed_by_other' if reason == 'compacted_by_other' else
                     'cancelled' if reason == 'intervening_turn' else
                     'deferred' if record['delivery']['state'] == 'deferred' else 'failed')
            record.update(state=state,
                          completion={'state': 'confirmed', 'witness': record['delivery']['witness'], 'by_other': True}
                          if reason == 'compacted_by_other' else {'state': 'not_started'}, reason=reason)
            if reason == 'intervening_turn':
                record['turns_seen'] = record['delivery'].get('turns_seen') or 1
        else:
            transcript_witness = None
            while True:  # Include one final observation even if dispatch crossed the deadline.
                if record['action'] == 'exit':
                    witness = None if same_process(identity) else {'source': 'process_identity', 'pid': identity.pid,
                               'boot_id': identity.boot_id, 'starttime': identity.starttime, 'observed_at': time.time()}
                else:
                    transcript_witness = transcript_witness or _compact_event(record['transcript_path'], record['baseline'], identity.harness, record['session_id'])
                    witness = None
                    try:
                        marker = _pane_marker(identity)
                    except (ControlError, IdentityError):
                        marker = None
                    if marker and record.get('pane_sampling', {}).get('available') is True:
                        _track_progress(record['pane_sampling'], marker)
                    if transcript_witness:
                        record['completion'] = {'state': 'confirmed', 'witness': transcript_witness,
                                                'pane_marker': {'state': 'not_observed'}}
                        _write(path, record)
                        if marker and marker['count'] > record['pane_baseline']['count']:
                            witness = {**transcript_witness, 'pane_marker': {**marker, 'method': 'count_increased'}}
                        elif (marker and marker['count'] > 0 and marker.get('progress') is False and
                              record.get('pane_sampling', {}).get('available') is True and
                              record['pane_sampling'].get('progress_started_at') is not None):
                            witness = {**transcript_witness, 'pane_marker': {**marker,
                                       'method': 'native_progress_then_completed_marker',
                                       'progress_started_at': record['pane_sampling']['progress_started_at']}}

                if witness:
                    record.update(state='completed', completion={'state': 'confirmed', 'witness': witness})
                    if record['action'] == 'compact':
                        # Persist intent before the one ordinary send. Restarting
                        # an interrupted observer never replays this operation.
                        record.update(state='continuing', deadline=time.time() + SEND_BUDGET + PREFLIGHT_BUDGET,
                                      continuation={'state': 'dispatching', 'attempted_at': time.time()})
                        _write(path, record)
                        record['continuation'] = _send(directory, record, identity, record['resume_message'], '.continuation')
                        record['state'] = 'completed' if record['continuation']['state'] == 'delivered' else 'continuation_failed'
                        if record['state'] == 'continuation_failed':
                            record['reason'] = 'compacted_but_continuation_not_delivered'
                    break
                if time.monotonic() >= observer_deadline:
                    record['state'] = 'unconfirmed' if record['action'] == 'compact' and record['delivery']['state'] == 'delivered' else 'timed_out'
                    if transcript_witness:
                        record['reason'] = 'transcript_compacted_but_new_pane_marker_not_observed'
                        if record['state'] == 'unconfirmed':
                            record['completion'] = {'state': 'unconfirmed', 'witness': transcript_witness,
                                                    'pane_marker': {'state': 'not_observed'}}
                    else:
                        record['completion'] = {'state': 'unconfirmed' if record['state'] == 'unconfirmed' else 'unknown',
                                                'reason': 'completion_not_observed'}
                        if record['state'] == 'unconfirmed':
                            record['reason'] = 'compaction_event_not_observed_within_bound'
                    break
                time.sleep(min(0.5, max(0, observer_deadline - time.monotonic())))
    except (OSError, ValueError, KeyError, TypeError, IdentityError, ControlError):
        continuing_failed = (record['completion'].get('state') == 'confirmed' and
                             record['continuation']['state'] != 'not_dispatched')
        delivered_compact = record['action'] == 'compact' and record.get('delivery', {}).get('state') == 'delivered'
        record.update(state='continuation_failed' if continuing_failed else
                      'unconfirmed' if delivered_compact else 'failed', reason='evidence_or_identity_unavailable')
        if delivered_compact and not continuing_failed and record['completion'].get('state') == 'confirmed':
            record['completion'] = {**record['completion'], 'state': 'unconfirmed'}
        elif record['completion'].get('state') != 'confirmed':
            record['completion'] = {'state': 'unconfirmed' if delivered_compact else 'unknown'}
    finally:
        _settle_dispatches(record, 'observer_interrupted_during_dispatch')
        record.update(updated_at=time.time())
        needs_notice = False
        owned_final = False
        with _guard(directory):
            if _read(path)['state'] != 'cancelled':
                if record['state'] == 'completed_by_other':
                    record.update(state='continuing', deadline=time.time() + SEND_BUDGET + PREFLIGHT_BUDGET,
                                  continuation={'state': 'dispatching', 'attempted_at': time.time()})
                needs_notice = (record['action'] == 'compact' and
                                ((record['state'] == 'cancelled' and record.get('reason') == 'intervening_turn') or
                                 (record['state'] == 'unconfirmed' and record['delivery']['state'] == 'delivered') or
                                 (_definitely_not_dispatched(record.get('delivery', {})) and
                                  record['state'] in ('deferred', 'failed', 'timed_out'))))
                if needs_notice:
                    record['pending_final_state'] = record['state']
                    if record['state'] != 'cancelled':
                        record['state'] = 'warning_dispatching'
                _write(path, record)
                owned_final = True
        if needs_notice:
            _failure_notice(directory, path, record, identity)
        if (owned_final and record['action'] == 'compact' and
                record['state'] == 'continuing' and record.get('completion', {}).get('by_other')):
            other_event = record.get('completion', {}).get('witness')
            if other_event:
                try:
                    record['continuation'] = _send(directory, record, identity, record['resume_message'], '.continuation')
                except Exception:
                    record['continuation'] = {'state': 'ambiguous', 'needs_review': True,
                                              'reason': 'continuation_receipt_unavailable'}
                record['state'] = 'completed_by_other' if record['continuation']['state'] == 'delivered' else 'continuation_failed'
                if record['state'] == 'continuation_failed':
                    record['reason'] = 'compacted_by_other_but_continuation_not_delivered'
                _write(path, record)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--observe':
        raise SystemExit(2)
    observe(sys.argv[2], sys.argv[3])
