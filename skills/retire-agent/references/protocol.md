# Shard and recovery contract

The offer assigns `<git-common-dir>/retirements/<unique-event>.shard`, a private pending
JSON file outside the working tree. After
validation the controller preserves its bytes in
`waiting/YYYY-MM-DD-sessionprefix-retire-<event>.md`, one shard per known
session, and updates only its bounded generated section in `waiting/INDEX.md`. The `.md` file contains JSON.
The agent must already have permission to write that private path. Workspace
sandboxing or an approval modal can prevent this; never bypass permissions or
send into a modal. The agent can decline, letting the authorized caller write
the recovery shard through the deliberate caller continuation.
A completion is a fresh assistant response row `RETIRE-DONE-<event>` after
writing the shard; a decline is `RETIRE-DECLINED-<event>`. The marker must be
the agent's entire final reply, without prose before or after it. The terminal
must show that marker as the final assistant block; trailing continuation text
or a later assistant response keeps completion pending. Trailing UI whitespace
is ignored. Blank rows and the
pure horizontal Claude composer separator are permitted suffix rows. A pinned
Codex target may also render one measured UI footer `  Worked for 1m 21s · 12:23`,
`  Worked for 19s • 19:35`, or `• Worked for 19s • 19:35` (the duration and 24-hour time vary). Only that anchored minute/second/time
layout is recognized; additional prose, duplicate footers, other status text,
and that footer on a Claude target still keep completion pending. A bullet-prefixed
Codex footer is accepted only when the pinned rollout's latest completed turn
has the exact DONE or DECLINED marker as `last_agent_message`; a later started
turn, partial rollout or changed final message keeps it pending. This witness
is rechecked before private handoff publication and before exit.
A pinned Claude target may render one native duration row, optionally followed by
one padded integer `tokens` status row or the measured Claude 2.1.288
`globalVersion` / `latestVersion` auto-update status row. A narrow pane may
wrap that exact status into two or three display rows; only contiguous rows
that reassemble to the measured status are accepted. Because tmux may trim
one space at a wrap boundary, each boundary is checked both with and without
that space against the exact full-row pattern. The duration row is
`✻ Baked for 37s · done 6:25 PM`. Claude's
local renderer verifies the glyph and verb pool Baked, Brewed, Churned,
Cogitated, Cooked, Crunched, Sautéed, Worked, and seconds/minutes-plus-seconds
format. Only the measured default 12-hour AM/PM done time and the measured
status formats are accepted; unknown verbs, other time layouts, partial status, extra
prose or later assistant blocks remain pending. This consumer disposition
rule uses the public shared response-row API; it does not fork its normalizer.
The observed terminal
must render an assistant `●` or `•` row marker. Bare wrapped user text and
live composer text do not count. Unsupported response layouts stay pending.
The controller never accepts a reported alternate shard path.

If the shared sender reported an ambiguous **offer** after an actual paste and
positive Enter, `--resume` may observe this same event without sending again.
The pinned pane and process, complete byte-for-byte preserved event-specific
offer file (checked against its length and SHA-256 saved before the first send)
and sender input report must still agree on every pending resume,
including one with a cached DONE disposition. Only the current exact final assistant completion or
decline block above advances disposition; the sender report remains ambiguous
in the private record. A missing, wrong, quoted, incomplete or followed marker
does not advance. This is not a retry or a way to waive shard, resource,
private remote, native-session or exit checks. No such observation-only path
exists for an ambiguous exit command.
The saved offer is checked without re-reading a potentially changed native
session; exit still requires a fresh pinned native binding matching the shard.
An ambiguous offer persisted by the installed pre-change version has no saved digest.
For that exact legacy envelope only, reconstruct the pre-change offer text,
compare its complete bytes, then save its length and digest for later resumes.
Missing or partial digest fields on any other payload remain pending.

The complete envelope (use explicit `"none"` or empty lists where appropriate):

```json
{
  "event": "copy the assigned event",
  "identity": {"copy": "the complete identity object in the offer"},
  "author": "agent",
  "date": "2026-09-26",
  "session_id": "your real provider-native session ID",
  "harness": "codex",
  "model": "your actual model",
  "working_directory": "/actual/worktree",
  "tmux_window": "session:window",
  "role": "your role",
  "landed_work": "PR and exact SHA, or explicit none",
  "lessons": "One to five lines of lessons learned",
  "provenance": "agent-authored from named evidence",
  "recovery": {
    "mission": "mission",
    "authorization": "scope and authority",
    "pauses": "explicit pauses, or none",
    "worktree": "/actual/worktree",
    "branch": "branch",
    "heads": "exact heads",
    "tested_vs_merged": "distinguish tested commits from merged commits",
    "evidence": "evidence paths",
    "limits": "evidence and reconstruction limits",
    "failures": "failed attempts, or none",
    "open_decisions": [{"decision": "pending decision", "owner": "named owner"}],
    "outstanding_sends": "ambiguous sends that must never be replayed, or none",
    "next_action": "first bounded next action"
  },
  "resources": [{"name": "owned server or lease", "status": "released", "receipt": "verification evidence"}],
  "waiting": {"decision": "pending human decision (waiting mode only)", "owner": "human owner"},
  "exact_resume_command": "optional provider-native command; this field is last"
}
```

An empty resources list explicitly claims none remain. A transferred resource
needs `status: "transferred"`, a named `owner`, and a transfer acceptance
`receipt`. Unknown or pending resources block exit. Optional personal thanks
use `personal_thanks` and `thanks_provenance`, apart from recovery. Recovery
must stand alone without live chat, pane inspection or predecessor resumption.
The optional native resume handle is last and is not a reconstruction shortcut.

Retain every running exec session handle until that call completes or is
deliberately stopped. A yielded output chunk is not a completion receipt. Track
owned child processes, including descendants of shells; a shell exiting after
a stop signal does not establish that its children exited. Stop only processes
whose ownership and identity were verified, then check actual descendants
ended or document an accepted transfer. If a handle or child is still running,
unknown, or orphaned without verified release, keep resource status pending and
do not claim quiescence or submit DONE.

After an observed decline, the caller writes the assigned file with
`author: "caller"`, `declined: true`, and honest evidence attribution and
uncertainty. Preserve a known session ID; explicitly use `"unknown"` if it
cannot be established. Never invent the agent's own-word thanks. A caller may
include an actual quotation only with `thanks_provenance: "quoted-agent"`.
Then invoke `--resume PRIVATE_STATE --caller-shard` in the same mode.

The checkout must already have private `origin/master`. Privacy is checked for
every fetch/push URL. GitHub uses authenticated `gh repo view` with an explicit
github.com URL, independent of `GH_HOST`; unknown/public
remotes fail closed. `RETIRE_PRIVATE_CHECK` names an optional trusted site-owned
executable accepting one URL and returning zero only when that URL is verifiably
private (tests use local bare repositories). It is a privacy authority; never
set it to `true`. `RETIRE_REPO` and `RETIRE_SPAWN_SKILL` select alternate private
records and the existing shared skill. The default shared skill is the
sibling spawn-agent in the same resolved checkout; overrides must provide the
matching published Claude/Codex model-selection and guarded literal-Claude-exit
contracts. No pane or unsent human text is saved.

Git transactions hold `.git/retirement.lock` (the common directory for
worktrees) around duplicate-session validation and publication; a per-event
lock protects longer orchestration. Shards and receipts are staged under the
event's private `.git/retirements/<event>.publication/` directory, not written
to the shared checkout. The helper creates a disposable detached worktree at
fetched `origin/master`, copies only the event's named paths, regenerates the
bounded INDEX section against that current tree, commits and pushes. A
non-fast-forward push retries from fresh origin at most three times. A failed
push blocks exit and keeps the event's staging files for deliberate resume.
Foreign JSON records are indexed only after a matching receipt claims their
event and path; malformed claimed remote metadata stops without changing the
shared checkout. The recovery procedure for an already drifted shared tree is
in [README.md](../README.md).
Verify the shard blob on fetched private `origin/master`, publish its unique
ledger receipt, then request bare harness exit through the shared sender.
Claude `/exit` uses `--literal-exit`; Codex `/exit` uses `--typed-command`.
Both require an empty composer and type the command using the shared bounded
Enter recovery; Claude literal exit permits one Enter, Codex typed command
permits at most two with fresh owned-input evidence. An
ordinary stale draft defers exit without sending exit keys; preserve it and
resume only after deliberate composer reconciliation. Pasted Claude `/exit`
is ordinary text and cannot retire a harness.

Ruling RETIRE-FIX-R1 requires two independent exit receipts: all pinned original
PID/start-time/boot-ID actors ended, and a fresh harness-native exit notice
naming the exact UUID in the immutable verified shard. Codex's notice block is
`Token usage: ...`, `To continue this session, run:`, then `codex resume UUID`.
Claude's block is `Resume this session with:` then `claude --resume UUID`.
`Shutting down...` is optional. Before requesting exit, persist only the count
of matching native notice blocks, never terminal text. A submitted command
receipt or an ambiguous attempt with actual input and a positive Enter count
is required; typed characters and proven no-input deferrals cannot retire.
Resume rereads the pinned pane and requires a greater count; cached confirmation is not authority.
A failed resume of a locally retired state does not republish or downgrade its
historical remote receipt. Current failure audits remain unconfirmed until the
current process/notice pair verifies; loaded or forged retired status is never
new publication authority. Historical accepted evidence and current pending
reverification are distinct.
An old notice, wrong UUID, bare resume command, absent pane or ended process
alone cannot establish retirement. Unsupported layouts and unknown caller
session IDs preserve the handoff pending exit verification. If the original
ended before any exit request, leave pending without sending into its shell.

Before offering retirement, the controller observes the pinned peer through
the canonical `skills/_shared/native/session_binding.py` and puts its verified provider-native
session UUID in the offer beside the assigned shard path. The retiring agent
copies that exact ID into the shard; it does not find a helper or rediscover
its session. The controller rechecks the pinned peer just before sending the
offer, before requesting exit, and again just before exit input. Codex uses
the canonical bounded `codex_status.py` reader on the pinned native core (or
original process): a unique writable CLI rollout descriptor, its first native
session metadata, and descriptor inode/device checks, with pinned `CODEX_HOME`.
Require `state: observed` and the same session UUID at each action boundary.
Only a Codex session running in its own process can be bound. A TUI attached to
the shared app-server daemon (what plain `codex` and `codex resume` do while the
daemon runs; some options happen to force a private process, only `--no-daemon`
guarantees one) holds no rollout descriptor: the daemon
writes every attached thread, and nothing the process exposes says which one is
its own. The reader reports `ambiguous_or_missing_live_rollout`, and handoff
stays pending. Such a client's `/exit` prints `To reconnect, run:` and leaves the
thread loaded in the daemon, so it is not an exit either. Launch and resume
lanes with `--no-daemon` where the CLI offers it; `spawn-agent` passes it when
the binary's own help lists it. An older CLI without the flag launches without
it, and nothing here shows such a session runs in its own process: if the
reader cannot bind it, handoff stays pending.
If the reader or binding is unavailable, report the blocker; do not search all
of home or `/nix/store` or infer a session from cwd, environment or newest rollout.
Claude reads only `current.<pid>` from pinned `CLAUDE_CONFIG_DIR/session-state`
and the installed hook's pinned `HOME/.claude/session-state` contract. Any
present pointer must contain the same UUID, process start ticks and boot ID;
missing, stale, malformed or conflicting bindings leave handoff pending before
exit input. No inherited environment UUID, newest-file search, cwd or timestamp
inference establishes attribution. The actor is rechecked around lookup and
again immediately before the sender call. Claude's pointer is asynchronous:
it reflects the last PreToolUse hook update. A `/clear` or `/resume` after DONE
without a later tool call can leave the old pointer, even before the sender's
readiness interval. Neither that window nor a switch during readiness can be
atomically excluded; an old pointer may leave a preserved handoff pending after
exit because the new native notice names a different session. The installed
capture hook and canonical Codex reader are prerequisites, not inferred IDs.
Exit notice capture joins wrapped rows and reads retained full scrollback;
history eviction or unsupported native layouts still leave completion pending.

Recognized Node wrappers and native children are one logical harness; both must
end. A replacement actor blocks completion. Nothing kills a process. Resumes
reverify the preserved blob and receipt before exit or successor.
History discovery owns only `<32-lowercase-hex-event>.json` state filenames
in the private retirement directory. Other JSON names, including independent
publication receipts, are left untouched and do not block a new offer.
Malformed event state records stop with their bytes preserved for operator
reconciliation.
After a failed immutable-shard or receipt revalidation, failure handling only
records the private attempt audit; it does not publish a handoff-authorizing
receipt from cached state. Repeated resumes preserve the rejected evidence
until the operator reconciles it deliberately.
The ledger records pending handoff, pending exit and retired;
its index preserves all steward-owned legacy metadata outside the bounded
generated section. A legacy filename matching the same session ID prefix
(eight characters or more) blocks another shard until deliberate reconciliation.

Waits are bounded: `--wait` defaults to 300 seconds (maximum 1800), model-result
polling `--poll` defaults to 60 seconds (maximum 90); tests may shorten polling.
Use `--wait 1200` for a handoff that needs 10–20 minutes. If the observation
budget ends, continue with the same mode and target using
`scripts/retire.sh %PANE --resume PRIVATE_STATE --wait 1200`; a delivered offer is never resent.
Process exit has a separate fast poll. The shared sender has its own bounded
waits. Exit may end the harness before a sender receipt; the original process
end and fresh same-session native notice remain mandatory. Offer acceptance
and DONE remain separate. An attempted successor launch is never automatically
repeated, including after a crash or
unconfirmed initial delivery. Inspect the launcher's pane/receipt before any
deliberate operator recovery. There is no ambiguous-send override or manual
relay in this script.

Screen markers are heuristics, not atomic human exclusion or cryptographic
actor attribution. An assistant/user deliberately spoofing another actor's
terminal framing can be ambiguous. Schema validation checks fields and resource
receipts, not the truth of claims, PR hashes, model identification or operational
prose; the caller must audit those before requesting retirement.
Observation consumes only spawn-agent's published `read_response_rows(pane,
socket)` and `DeliveryError` Python contract. It excludes archived redraws and
the live composer. Keep the final marker visible until the controller records
DONE. For an ambiguous offer, every resume before the handoff receipt rechecks
the exact preserved offer and current final marker, even after a recorded DONE
or DECLINED. A delivered offer may use its recorded disposition on resume.
The socket is pinned in private state and reused for observation and transport;
server failure is not evidence that the pane disappeared. Recognized
`codex mcp-server` and exact Nix `codex-desktop` `app-server --listen stdio://`
support processes are excluded from harness identity, but their resources
still require shard receipts. Their process records remain in descendant
traversal so a nested interactive CLI cannot disappear with its parent.
Other `codex app-server` shapes and additional harness
invocations remain a safe deferral pending operator reconciliation.
Follow-up `retire-agent-helper-identification` tracks richer auxiliary-command
classification; do not weaken identity checks to bypass that deferral.
The npm `node …/codex.js mcp-server` shape also remains a safe helper-identity
deferral. `retire-agent-commit-ownership-recovery` tracks crashes between Git
commit and its ownership audit: reconcile an orphaned commit deliberately,
never infer ownership from its subject. `retire-agent-concurrent-lock-budget`
tracks the bounded Git-lock wait; busy transactions require a deliberate
resume rather than an overlapping publication attempt.

Each event also has an append-only private `<event>.jsonl` attempt ledger in
the Git common directory: target/pane, event marker, transport exit and receipt
type, completion disposition, verified shard path and original process exit.
It contains no payload or pane text; exact outgoing payloads remain separate.

The native rehearsal defaults to both harnesses; `--harness claude` or `codex`
allows independent diagnosis without claiming the combined gate. The cwd must
be a clean exclusively owned Git toplevel, have no remotes, and use a different
Git common directory from source. Owned cwd checks include ignored files and
refs. Source/shared hashes and dirty states record source fidelity, not global
containment. Agents retain normal host access. The published Claude `--trust`
launcher persists authorization for this exact disposable directory; retain
and document that grant rather than racing unrelated trust-store entries.
