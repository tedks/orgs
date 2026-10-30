#!/usr/bin/env python3
"""Harness self status/control plus legacy Claude Code introspection MCP server.

Provides tools for Claude Code to inspect its own session state:
session ID, launch directory, session history, and session branching.

The Nix package sets AGENT_SKILLS_ROOT to the immutable skills tree captured by
the same source revision. Development and tests may set it to an absolute skills
directory. Native identity readers and the spawn-agent sender are required at
startup, without a bundled fallback.

Session state is written by the PreToolUse hook:
  ~/.claude/hooks/capture-session-state.sh
which writes to:
  ~/.claude/session-state/<session-id>.json
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # Shared installed readers remain read-only.

# Refuse startup before advertising tools if canonical readers are unavailable.
import harness_identity
import codex_status
import session_binding
from _skills_native import spawn_transport_path

spawn_transport_path()  # Refuse incomplete installations before tool registration.

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("harness-control")

CLAUDE_DIR = Path.home() / ".claude"
SESSION_STATE_DIR = CLAUDE_DIR / "session-state"
PROJECTS_DIR = CLAUDE_DIR / "projects"


def _stat_fields(pid: int) -> list[str] | None:
    """Fields of /proc/<pid>/stat after "(comm)", starting at field 3 (state)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The comm field (2) can contain spaces and parens, so find the last ')'.
    return stat[stat.rfind(")") + 2 :].split()


def _get_parent_pid(pid: int) -> int | None:
    """Get the parent PID of a process by reading /proc/<pid>/stat."""
    fields = _stat_fields(pid)
    try:
        return int(fields[1])  # PPID is field 4, the 2nd after comm
    except (TypeError, ValueError, IndexError):
        return None


def _get_starttime(pid: int) -> str | None:
    """Process start time (clock ticks since boot): field 22 of /proc/<pid>/stat."""
    fields = _stat_fields(pid)
    try:
        return fields[19]
    except (TypeError, IndexError):
        return None


def _get_comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


_boot_id_cache: str | None = None


def _get_boot_id() -> str:
    """Boot id, cached ONLY on success: it's invariant for this process's whole
    lifetime once read, but a failure to read it might not be. A one-shot
    functools.lru_cache would memoize a single transient failure ("unknown")
    forever, so every future pointer's boot id -- which the hook reads fresh
    on every call and would successfully get right after that one glitch --
    would then permanently mismatch, silently reintroducing the very
    resumed-session-null bug this file exists to fix, until the server
    restarts. So: cache a real value forever; never cache "unknown".

    "unknown" (not None) matches the hook's own fallback for the case where
    /proc really is unreadable (e.g. a sandbox) rather than merely glitching:
    both sides degrade to ordinary start-time verification, without the extra
    boot-crossing check, instead of a None that can never equal anything.
    """
    global _boot_id_cache
    if _boot_id_cache is not None:
        return _boot_id_cache
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot_id = ""
    if boot_id:
        _boot_id_cache = boot_id
        return boot_id
    return "unknown"


# The session-state hook is registered "async": true, so it can land a moment
# AFTER the tool call that triggered it -- including a get_session_info that is
# the first thing a fresh or resumed session does. Retry briefly before
# reporting no session, rather than answer null for a pointer ms from existing.
POINTER_ATTEMPTS = 5
POINTER_RETRY_DELAY = 0.1
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _pointer_session(pid: int) -> str | None:
    """Session id from current.<pid>, if that pointer is really for this process.

    The pointer holds "<session_id> <start time> <boot id>". Pids wrap within
    days on this fleet, so a dead claude's pointer can sit under a pid a new
    claude has since reused; the start time (ticks since boot, so paired with
    the boot id) must match the live process or the pointer is stale, not ours.
    Anything not in exactly that form -- including the bare "<session_id>" the
    previous hook wrote, which has nothing to verify -- is refused: answering
    with a stale session is worse than answering null.
    """
    try:
        parts = (SESSION_STATE_DIR / f"current.{pid}").read_text().split()
    except OSError:
        return None
    if len(parts) != 3:
        return None
    session_id, starttime, boot_id = parts
    if not SESSION_ID.fullmatch(session_id):
        return None
    if starttime != _get_starttime(pid) or boot_id != _get_boot_id():
        return None
    return session_id


def _walk_for_pointer() -> tuple[str | None, bool]:
    """Walk up from this server. Returns (session id or None, saw a claude ancestor).

    The `saw a claude ancestor` flag is what lets _get_session_id skip its
    retry when nothing could possibly appear (no claude* process in this
    server's ancestry at all). That flag comes from _get_parent_pid returning
    None, which is also what a transient /proc read failure looks like -- so a
    genuine "there is no claude here" and a one-off glitch mid-walk are treated
    identically, and only the former is actually common (this server's own
    ancestry through its Python process and launcher is short and stable once
    it's running).
    Retrying through a spurious failure was free before this flag existed;
    now it costs the rest of the retry budget. Accepted tradeoff, not fixed.
    """
    pid = os.getpid()
    while pid is not None and pid > 1:
        session_id = _pointer_session(pid)
        if session_id:
            return session_id, True
        # The nearest claude ancestor owns this server. Do not climb past it
        # into a parent claude (a `claude -p` run from a Bash tool call is one
        # whose own pointer may not exist yet): that would answer with the
        # PARENT session's id, which is worse than answering null.
        if _get_comm(pid).startswith("claude"):
            return None, True
        pid = _get_parent_pid(pid)
    return None, False


async def _get_session_id() -> str | None:
    """Get the current session ID.

    Checks (in order):
    1. CLAUDE_SESSION_ID env var -- Claude Code itself never sets this for
       hooks or their children (confirmed against its hook docs and
       anthropics/claude-code#27299); this is a manual-override/testing
       escape hatch only, not something that fires in normal use.
    2. Per-process pointer files written by the session-state hook

    The hook writes current.<claude_pid> = "<session_id> <start time> <boot
    id>", where claude_pid is the nearest claude* ancestor of the hook (NOT its
    $PPID: Claude Code runs hooks as `/bin/sh -c <command>`). This MCP server
    walks up its own process tree to the matching pointer, so concurrent
    sessions each resolve to their own session ID
    without racing.

    Limits: after an in-process /clear or /resume the pointer still holds the
    old session id until the (async) hook rewrites it, so a call made in that
    instant can answer with the previous session's id.
    """
    from_env = os.environ.get("CLAUDE_SESSION_ID")
    if from_env:
        return from_env

    for attempt in range(POINTER_ATTEMPTS):
        session_id, saw_claude = _walk_for_pointer()
        if session_id:
            return session_id
        if not saw_claude:
            return None  # no claude ancestor at all: waiting cannot make one appear
        if attempt < POINTER_ATTEMPTS - 1:
            await asyncio.sleep(POINTER_RETRY_DELAY)
    return None


def _read_session_state(session_id: str) -> dict:
    """Read the state file for a given session ID."""
    if not SESSION_ID.fullmatch(session_id):
        return {}
    state_file = SESSION_STATE_DIR / f"{session_id}.json"
    try:
        data = json.loads(state_file.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_project_dir() -> Path | None:
    """Find the project directory for the current working directory."""
    cwd = os.getcwd()
    encoded = cwd.replace("/", "-")
    project_dir = PROJECTS_DIR / encoded
    if project_dir.exists():
        return project_dir
    # Walk up to find a matching project
    parts = Path(cwd).parts
    for i in range(len(parts), 0, -1):
        candidate = "/".join(parts[:i])
        encoded = candidate.replace("/", "-")
        project_dir = PROJECTS_DIR / encoded
        if project_dir.exists():
            return project_dir
    return None


def _read_sessions_index(project_dir: Path) -> list[dict]:
    """Read the sessions-index.json for a project."""
    index_file = project_dir / "sessions-index.json"
    try:
        data = json.loads(index_file.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        return []
    return [session for session in data["sessions"] if isinstance(session, dict)]


# Self tools intentionally ignore the legacy CLAUDE_SESSION_ID testing override:
# the nearest live harness and its verified pointer own this server instance.
_self_identity = None


def _own_identity():
    from harness_identity import discover, verify_pane
    global _self_identity
    if _self_identity is None:
        _self_identity = discover()
    verify_pane(_self_identity)
    return _self_identity


def _own_binding(identity):
    binding = _native_observation(identity)
    if binding['state'] != 'observed':
        from harness_identity import IdentityError
        raise IdentityError('own_session_unavailable')
    return binding


def _native_observation(identity):
    from session_binding import observe_native_session
    return observe_native_session(identity.harness, identity)


def _claude_snapshot(binding):
    sid = binding['session_id']
    path = Path(binding['status_dir']) / f"{sid}.status.json"
    try:
        with path.open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return sid, None
        return sid, json.loads(raw)
    except (OSError, ValueError):
        return sid, None


@mcp.tool()
async def get_status() -> dict:
    """Own pinned tmux harness, model and last-observed context; unknowns explicit.

    Linux/tmux only. No active-window fallback. Codex context remaining cannot
    be established exactly from rollout token counts and is reported unknown.
    Legacy introspection tools remain Claude-specific.
    """
    from harness_identity import IdentityError
    from harness_status import parse_claude_status
    try:
        identity = _own_identity()
        binding = await asyncio.to_thread(_native_observation, identity)
        if identity.harness == 'claude':
            sid, snapshot = _claude_snapshot(binding) if binding['state'] == 'observed' else (None, None)
            state = parse_claude_status(snapshot, sid)
        else:
            state = dict(binding.get('observation', {'state': 'unsupported', 'source': 'codex_rollout',
                                                      'reason': binding.get('reason', 'native_binding_unavailable')}))
            state.pop('rollout_path', None)
        return {"identity": identity.public(), "observation": state,
                "capabilities": {"status": True, "usage": True,
                                 "compact": True, "exit": True,
                                 "send_to_self": True, "read_own_pane": True,
                                 "checkpoint": True, "operation_receipts": True,
                                 "compact_continuation": True}}
    except IdentityError as exc:
        return {"state": "unavailable", "reason": str(exc)}


def _observed(bucket):
    """Parsed observed_at of a quota bucket, or None."""
    from datetime import datetime
    try:
        stamp = bucket['observed_at']
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except (KeyError, TypeError, AttributeError, ValueError):
        return None


def _mark_superseded(session_buckets, account_latest):
    """Flag session buckets against account_latest.

    True when account_latest holds a strictly newer observation of the bucket
    (a real observation, valid even if the account result is incomplete). False
    only when account_latest is observed and complete, holds the bucket and the
    timestamps are comparable. Otherwise None (unknown): account_latest not
    observed, incomplete, bucket absent, or unparseable timestamps.
    """
    if not isinstance(session_buckets, dict):
        return session_buckets
    observed = isinstance(account_latest, dict) and account_latest.get('state') == 'observed'
    account = account_latest.get('quota_buckets') if observed else None
    complete = observed and account_latest.get('incomplete') is not True
    marked = {}
    for key, bucket in session_buckets.items():
        if isinstance(bucket, dict):
            flag = None
            mine = _observed(bucket)
            theirs = account.get(key) if isinstance(account, dict) else None
            latest = _observed(theirs) if isinstance(theirs, dict) else None
            if mine is not None and latest is not None:
                flag = True if latest > mine else (False if complete else None)
            bucket = {**bucket, 'superseded': flag}
        marked[key] = bucket
    return marked


def _read_usage_posture() -> dict:
    """Read the shared quota decision through its stable CLI interface."""
    import math
    import shutil
    import sys
    executable = shutil.which('token-usage')
    if not executable:
        return {'state': 'unavailable', 'reason': 'token_usage_cli_unavailable'}
    try:
        completed = subprocess.run(
            [executable, 'posture', '--no-scan', '--json'],
            capture_output=True, text=True, encoding='utf-8', errors='strict', timeout=5, check=False)
    except subprocess.TimeoutExpired:
        return {'state': 'unavailable', 'reason': 'token_usage_posture_timeout'}
    except UnicodeError:
        return {'state': 'unavailable', 'reason': 'token_usage_posture_malformed'}
    except OSError:
        return {'state': 'unavailable', 'reason': 'token_usage_posture_exec_failed'}
    if completed.returncode != 0:
        return {'state': 'unavailable', 'reason': 'token_usage_posture_failed'}
    try:
        posture = json.loads(completed.stdout)
    except (TypeError, ValueError):
        return {'state': 'unavailable', 'reason': 'token_usage_posture_malformed'}
    providers = ('openai', 'anthropic')
    expected_keys = {'provider', 'scores', 'used_percent', 'resets_at', 'stale', 'staleness', 'gated', 'reason'}
    numeric_maps = ('scores', 'used_percent')
    def finite_number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if isinstance(value, int):
            return abs(value) <= sys.float_info.max
        return math.isfinite(value)

    if (not isinstance(posture, dict) or posture.keys() != expected_keys
            or posture.get('provider') not in (*providers, 'none')
            or not isinstance(posture.get('reason'), str)
            or not all(isinstance(posture.get(key), dict) and set(posture[key]) == set(providers)
                       for key in (*numeric_maps, 'resets_at', 'stale', 'gated'))
            or any(not finite_number(value)
                   for key in numeric_maps for value in posture[key].values())
            or any(not isinstance(value, (str, int, float)) or isinstance(value, bool)
                   or (not finite_number(value) if not isinstance(value, str) else False)
                   for value in posture['resets_at'].values())
            or not all(isinstance(value, bool) for value in posture['stale'].values())
            or not all(isinstance(value, bool) for value in posture['gated'].values())
            or not isinstance(posture.get('staleness'), dict)
            or posture['staleness'].keys() != {'stale', 'newest_observed', 'age_seconds'}
            or not isinstance(posture['staleness'].get('stale'), bool)
            or not isinstance(posture['staleness'].get('newest_observed'), str)
            or isinstance(posture['staleness'].get('age_seconds'), bool)
            or not isinstance(posture['staleness'].get('age_seconds'), int)
            or posture['staleness']['age_seconds'] < 0):
        return {'state': 'unavailable', 'reason': 'token_usage_posture_malformed'}
    return posture


@mcp.tool()
async def get_usage() -> dict:
    """Last observed provider quota buckets, reset times, and quota posture; never context tokens.

    Reads provider meters from local status/state and quota posture from
    ``token-usage posture --no-scan``. Missing/expired meters are unknown; the
    posture's ``staleness`` field should accompany provider decisions. Neither
    observation is a live provider query.

    Codex: the bound session's own last observation (it goes stale when the
    session is idle) plus ``account_latest``, the newest account-wide meter seen
    in any recent rollout of this CODEX_HOME (no paths or session ids). A session
    bucket carries ``superseded``: true when account_latest holds a strictly
    newer observation of the same limit_id; false only when account_latest is
    observed, complete and holds that bucket without a newer record; null
    (unknown) when it is not observed or is incomplete, lacks the bucket, or
    timestamps are unparseable. account_latest
    is returned even when the session binding failed; it assumes one OpenAI
    account per CODEX_HOME, may be ``incomplete`` (see newest_account_quota), and
    covers only the session's buckets when the session has any (else only the
    buckets seen).
    """
    import time
    from harness_identity import IdentityError
    from harness_status import parse_claude_usage
    posture_task = asyncio.create_task(asyncio.to_thread(_read_usage_posture))
    try:
        identity = _own_identity()
        binding = await asyncio.to_thread(_native_observation, identity)
        if identity.harness == 'claude':
            sid, snapshot = _claude_snapshot(binding) if binding['state'] == 'observed' else (None, None)
            result = parse_claude_usage(snapshot, sid, now=time.time())
            posture = await posture_task
            result['posture'] = posture
            return result
        state = binding.get('observation', {'state': 'unsupported', 'source': 'codex_rollout',
                                            'reason': binding.get('reason', 'native_binding_unavailable')})
        result = {key: value for key, value in state.items()
                  if key in ('state', 'reason', 'source', 'session_id', 'model_provider', 'quota_buckets', 'history_complete', 'read_window')}
        expected = list(result['quota_buckets']) if isinstance(result.get('quota_buckets'), dict) \
            and result['quota_buckets'] else None
        try:
            codex_home = await asyncio.to_thread(codex_status.codex_home_for, identity.pid)
            if codex_home is None:
                latest = {'state': 'unavailable', 'source': 'codex_rollouts_newest',
                          'reason': 'codex_home_unavailable'}
            else:
                latest = await asyncio.to_thread(
                    lambda: codex_status.newest_account_quota(codex_home, expected_buckets=expected))
        except Exception:  # never lose the session result to the account reader
            latest = {'state': 'unavailable', 'source': 'codex_rollouts_newest',
                      'reason': 'reader_failed'}
        result['account_latest'] = latest
        if 'quota_buckets' in result:
            result['quota_buckets'] = _mark_superseded(result['quota_buckets'], latest)
        posture = await posture_task
        result['posture'] = posture
        return result
    except IdentityError as exc:
        posture = await posture_task
        return {"state": "unavailable", "reason": str(exc), 'posture': posture}


# Lifecycle tools never accept target identity, session id or transcript paths.
# Checkpoint paths identify recovery artifacts, not a harness to control.
def _own_control(require_transcript=False):
    from harness_control import HarnessControl
    from harness_identity import IdentityError, verify_pane
    from harness_status import parse_claude_status
    identity = _own_identity()
    binding = _own_binding(identity)
    sid = binding['session_id']
    transcript = None
    if identity.harness == 'claude':
        _, snapshot = _claude_snapshot(binding)
        if require_transcript:
            if parse_claude_status(snapshot, sid)['state'] != 'available':
                raise IdentityError('bound_transcript_snapshot_unavailable')
            transcript = snapshot.get('transcript_path')
            if (not isinstance(transcript, str) or not Path(transcript).is_absolute()
                    or Path(transcript).name != sid + '.jsonl'):
                raise IdentityError('bound_transcript_path_unavailable')
        # Detect a hook update during binding; never use a prior session's
        # checkpoint after a detected in-process session switch.
        if _own_binding(identity)['session_id'] != sid:
            raise IdentityError('own_session_changed_during_binding')
    elif identity.harness == 'codex':
        if require_transcript:
            transcript = binding.get('transcript_path')
            if not isinstance(transcript, str) or not Path(transcript).is_absolute():
                raise IdentityError('bound_transcript_path_unavailable')
    else:
        raise IdentityError('unsupported_harness')
    verify_pane(identity)
    return HarnessControl(identity, sid, transcript)


def _control_call(method, *args, require_transcript=False, **kwargs):
    from harness_control import ControlError, OperationInProgress
    from harness_identity import IdentityError
    try:
        control = _own_control(require_transcript=require_transcript)
        return getattr(control, method)(*args, **kwargs)
    except IdentityError as exc:
        return {'state': 'unavailable', 'reason': str(exc)}
    except OperationInProgress as exc:
        return {'state': 'refused', 'reason': 'operation_in_progress',
                'blocking_operation_id': exc.operation_id,
                'blocking_state': exc.state, 'next_action': exc.next_action}
    except ControlError as exc:
        return {'state': 'refused', 'reason': str(exc)}
    except (OSError, ValueError, TypeError, KeyError):
        # Filesystem/JSON exceptions can contain private data or file paths.
        return {'state': 'unavailable', 'reason': 'control_evidence_unavailable_or_invalid'}


@mcp.tool()
async def record_checkpoint(evidence: dict) -> dict:
    """Record a private receipt for this session's durable recovery shard.

    Required evidence: shard_path, repo_path, sha256, exact commit;
    private_storage_attested/obligations_preserved/pause_state_preserved=true;
    push_attestation=pushed_private_remote|no_remote_configured;
    authority=compact_authorized|exit_authorized;
    resources_disposition=active_recorded|released|handed_off;
    pause_state_reference and active_inventory_reference (nonempty strings).
    Verifies local bytes/commit and remote presence. Privacy, remote push and
    semantic authority/resource/pause obligations remain caller attestations.
    Returns receipt_id; this call performs no control delivery.
    """
    return await asyncio.to_thread(_control_call, 'record_checkpoint', evidence)


@mcp.tool()
async def self_compact(checkpoint_path: str, checkpoint_receipt: str,
                       continuation: str | None = None, focus: str | None = None,
                       timeout_seconds: int = 3600) -> dict:
    """Compact self and re-prompt once after a NEW compaction event. Call LAST.

    checkpoint_path must equal the shard in the recorded checkpoint_receipt.
    Save state first, call this tool, then END THE TURN. Returns a scheduled
    operation with the detached watcher PID and idle bound, not completion.
    Optional focus is an ordinary message before bare typed /compact.
    The native idle bound defaults to 3600 seconds and accepts 30 to 7200.
    Focus, when present, starts a fresh idle bound after its own turn. Sender
    and compaction confirmation time are separate from that bound. A new
    native root input turn cancels the scheduled command and emits one visible
    notice. A peer compaction observed before cancellation sends continuation.
    The detached observer waits for native idle, then sends one ordinary
    CONTINUE with the verified shard path and optional continuation text only
    after a new transcript boundary AND fresh pane completion evidence
    (marker count increase, or observed Claude progress-to-completion transition). That send has an
    additional bounded 115-second budget. If dispatch is deferred or the idle
    bound expires, it attempts one visible notice in the own pane. If /compact
    was delivered without confirmed completion, it records unconfirmed with
    the delivery receipt, emits one notice, and never retries or continues.
    No event means no re-prompt; a peer may deliberately resume the session.
    Tmux-delivered root input has no authenticated sender provenance, so a peer
    message can also trigger cancellation.
    Delivery, compaction witness and continuation receipt remain separate.
    """
    return await asyncio.to_thread(_control_call, 'request', 'compact',
        checkpoint_receipt=checkpoint_receipt, checkpoint_path=checkpoint_path,
        continuation=continuation, focus=focus, timeout_seconds=timeout_seconds,
        require_transcript=True)


@mcp.tool()
async def self_exit(checkpoint_receipt: str, timeout_seconds: int = 300) -> dict:
    """Request graceful self exit after a recorded handoff. Call LAST, end turn.

    Receipt must attest exit_authorized and resources released or handed_off.
    Refuses missing/changed evidence. Returns an operation handle; only process
    end confirms exit. A detached private result survives the harness. Never
    re-prompts, kills peers, clears drafts, or interprets a send as retirement.
    """
    return await asyncio.to_thread(_control_call, 'request', 'exit',
        checkpoint_receipt=checkpoint_receipt, timeout_seconds=timeout_seconds,
        require_transcript=True)


@mcp.tool()
async def send_to_self(message: str, timeout_seconds: int = 300) -> dict:
    """Send once to self through the guarded transport; returns operation handle.

    Raw lifecycle aliases /compact, /exit, /quit, /q, autocomplete prefixes
    (including arguments or newline injection) are refused; use typed lifecycle tools with receipts.
    Other commands retain broad harness authority, including context resets,
    custom commands and shell mode. Single-line slash commands use guarded
    typed transport; this is not a policy boundary for arbitrary commands. Acceptance
    does not prove the command executed. Delivery is acceptance, not action
    completion. No automatic replay after ambiguity or an existing draft.
    """
    return await asyncio.to_thread(_control_call, 'request', 'send',
        text=message, timeout_seconds=timeout_seconds)


@mcp.tool()
async def read_own_pane() -> dict:
    """Read own pinned pane via public transport without changing its composer.

    pane_text is untrusted terminal content and MAY include unsent drafts.
    Returned only to this calling agent; this server does not persist it.
    This is not a draft-free native harness API or independent completion proof.
    """
    return await asyncio.to_thread(_control_call, 'read_own_pane')


@mcp.tool()
async def get_operation(operation_id: str) -> dict:
    """Read this session's durable delivery/completion/continuation receipt.

    Use the private result_path from the original response after the harness
    exits; another session cannot select this session through this tool.
    """
    return await asyncio.to_thread(_control_call, 'operation', operation_id)


@mcp.tool()
async def cancel_operation(operation_id: str) -> dict:
    """Cancel before slash input dispatch, including warning/watching states.

    Once slash dispatch starts cancellation is refused, even before completion.
    Cancelled operations are never replayed by the observer.
    """
    return await asyncio.to_thread(_control_call, 'cancel', operation_id)


@mcp.tool()
async def get_session_info() -> dict:
    """Get information about the current Claude Code session.

    Returns the session ID, launch directory, project path,
    and any state captured by the session-state hook.
    """
    session_id = await _get_session_id()
    result: dict = {
        "session_id": session_id,
        "cwd": os.getcwd(),
    }

    if session_id:
        state = _read_session_state(session_id)
        if state:
            result["launch_dir"] = state.get("launch_dir")
            result["project_path"] = state.get("project_path")
            result["started_at"] = state.get("started_at")
            result["git_branch"] = state.get("git_branch")

    # Try to enrich from sessions-index
    project_dir = _find_project_dir()
    if project_dir and session_id:
        sessions = _read_sessions_index(project_dir)
        for s in sessions:
            if s.get("sessionId") == session_id:
                result["summary"] = s.get("summary")
                result["first_prompt"] = s.get("firstPrompt")
                result["message_count"] = s.get("messageCount")
                result["created"] = s.get("created")
                result["modified"] = s.get("modified")
                result["is_sidechain"] = s.get("isSidechain")
                break

    return result


@mcp.tool()
async def list_sessions(limit: int = 10) -> list[dict]:
    """List recent Claude Code sessions for the current project.

    Args:
        limit: Maximum number of sessions to return (default 10)
    """
    project_dir = _find_project_dir()
    if not project_dir:
        return [{"error": f"No project directory found for {os.getcwd()}"}]

    sessions = _read_sessions_index(project_dir)

    # Sort by modified date descending
    sessions.sort(
        key=lambda s: s.get("modified") if isinstance(s.get("modified"), str) else "",
        reverse=True,
    )

    results = []
    for s in sessions[:limit]:
        results.append({
            "session_id": s.get("sessionId"),
            "summary": s.get("summary"),
            "first_prompt": s.get("firstPrompt"),
            "message_count": s.get("messageCount"),
            "created": s.get("created"),
            "modified": s.get("modified"),
            "git_branch": s.get("gitBranch"),
            "project_path": s.get("projectPath"),
            "is_sidechain": s.get("isSidechain"),
        })

    return results


@mcp.tool()
async def branch_session(
    session_id: str | None = None,
    tmux_target: str | None = None,
    working_dir: str | None = None,
) -> dict:
    """Branch (fork) a Claude Code session into a new tmux window.

    Creates a copy of the conversation that diverges from this point.
    The original session continues unchanged.

    Args:
        session_id: Session ID to branch. Defaults to current session.
        tmux_target: Tmux target for the new window (e.g. "desktop:branch").
                     If not specified, creates a window in the current session.
        working_dir: Working directory for the branched session.
                     Defaults to the original session's launch directory.
    """
    sid = session_id or await _get_session_id()
    if not sid:
        return {"error": "No session ID available. Is the session-state hook installed?"}
    if not SESSION_ID.fullmatch(sid):
        return {"error": f"Invalid session ID format: {sid}"}

    # Determine working directory
    if not working_dir:
        state = _read_session_state(sid)
        launch_dir = state.get("launch_dir")
        working_dir = launch_dir if isinstance(launch_dir, str) and launch_dir else os.getcwd()

    # Determine tmux target
    if not tmux_target:
        # Try to detect current tmux session
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True, text=True, timeout=5,
            )
            current_session = result.stdout.strip()
            if current_session:
                tmux_target = f"{current_session}:branch-{sid[:8]}"
            else:
                tmux_target = f"claude:branch-{sid[:8]}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"error": "tmux not available"}

    # Parse session:window from target
    parts = tmux_target.split(":", 1)
    tmux_session = parts[0]
    tmux_window = parts[1] if len(parts) > 1 else f"branch-{sid[:8]}"

    # Check if tmux session exists
    session_exists = subprocess.run(
        ["tmux", "has-session", "-t", tmux_session],
        capture_output=True,
    ).returncode == 0

    # Build tmux command — pass claude args as a list, not through bash -c,
    # to avoid shell injection if sid were ever attacker-controlled.
    try:
        if session_exists:
            subprocess.run(
                ["tmux", "new-window", "-t", tmux_session,
                 "-n", tmux_window, "-c", working_dir,
                 "claude", "--resume", sid],
                capture_output=True, text=True, timeout=10,
                check=True,
            )
        else:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", tmux_session,
                 "-n", tmux_window, "-c", working_dir,
                 "claude", "--resume", sid],
                capture_output=True, text=True, timeout=10,
                check=True,
            )
    except subprocess.CalledProcessError as e:
        return {"error": f"tmux command failed: {e.stderr}"}
    except subprocess.TimeoutExpired:
        return {"error": "tmux command timed out"}

    return {
        "status": "branched",
        "original_session_id": sid,
        "tmux_target": f"{tmux_session}:{tmux_window}",
        "working_dir": working_dir,
        "hint": f"Switch with: tmux select-window -t {tmux_session}:{tmux_window}",
    }


@mcp.tool()
async def get_launch_dir(session_id: str | None = None) -> dict:
    """Get the original launch directory for a session.

    Useful when you've changed directories and need to know where
    Claude Code was originally started.

    Args:
        session_id: Session to look up. Defaults to current session.
    """
    sid = session_id or await _get_session_id()
    if not sid:
        return {"error": "No session ID available."}
    if not SESSION_ID.fullmatch(sid):
        return {"error": f"Invalid session ID format: {sid}"}

    state = _read_session_state(sid)
    launch_dir = state.get("launch_dir")
    if isinstance(launch_dir, str) and launch_dir:
        return {
            "session_id": sid,
            "launch_dir": launch_dir,
            "cwd": os.getcwd(),
            "changed": launch_dir != os.getcwd(),
        }

    # Fall back to sessions-index
    project_dir = _find_project_dir()
    if project_dir:
        for s in _read_sessions_index(project_dir):
            project_path = s.get("projectPath")
            if s.get("sessionId") == sid and isinstance(project_path, str) and project_path:
                return {
                    "session_id": sid,
                    "launch_dir": project_path,
                    "cwd": os.getcwd(),
                    "source": "sessions-index",
                }

    return {"error": f"No launch directory found for session {sid}"}


def main():
    """Run the stdio MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
