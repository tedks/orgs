# Blocking tmux delivery

Targets are exact `SESSION:WINDOW` names, stable `%PANE_ID`, or stable
`@WINDOW_ID` (its active pane). Prefixes, globs, bare names and implicit
window-index selectors are rejected. Named windows must be unique in the named
session. Resolution uses `list-windows`/`list-panes`, never `display-message`,
which may fall back to the active pane when a target is missing. Operations pin
the resolved pane ID; deletion afterward causes failure rather than retargeting.

The public sender uses `tmux-message.py` and returns success only with a
new application receipt. Use this entry point for inter-agent traffic and
lifecycle commands. The standalone legacy `claude-send.sh` reports
`status=sent receipt=unverified`. Its legacy path can append to stable
ordinary drafts and clear eligible command drafts. Keep that command out of
inter-agent delivery and lifecycle workflows.

## Flow

1. Resolve the target to an exact pane, observe its receiver identity and
   acquire the shared sender lock. Defer if this identity has an unresolved
   paste. Receiver checks use the socket, server PID and start time, pane ID,
   pane PID and terminal device. A server restart or pane respawn can produce
   a new identity without consuming the old attempt.
2. Compare input and relative cursor at least twice across
   `--stable-window` (default eight seconds). Require a recognized empty
   composer at its start cursor with no visible draft rows. A stable draft,
   including a command-shaped draft or collapsed marker, defers as
   `existing-input` before paste, Enter, cursor navigation or clearing.
   `--backoff` can wait for the receiver's composer to become empty. Modals,
   image placeholders and unsupported layouts defer. The measured Claude
   idle-suggestion probe and literal-exit handling retain their checks.
3. For bracketed paste, persist the pending bytes and attempt metadata under
   the pane lock. Recheck input and snapshot the receipt baseline. Paste the
   outgoing bytes once. Compare the rendered input with the payload,
   tolerating terminal wrapping, or require a fresh whole-paste marker.
   Paired OSC 8 hyperlinks on a captured row contribute only their visible
   labels. Other OSC controls, malformed and unbalanced links, and unrelated
   visible text cannot match the payload through this handling.
4. After the settling delay, send Enter only with fresh evidence of this
   attempt's input. Allow one bounded Enter-only retry for ordinary delivery
   while the same input remains. When the composer empties, only wait for a
   new receipt. Disappearance alone provides no confirmation.

New receipt means an additional matching record compared with the pre-paste
history. A collapsed receipt can match a marker observed in this attempt's
input; a marker found only in history is insufficient. Ordinary assistant prose
is not a receipt. The ordinary `/compact` route can also accept a new visible
`Context compacted` notice as a command receipt. Use the opt-in mode below
when the caller needs the rendered command outcome.
Claude can show a flush-left `❯` payload row followed by
`  ctrl+x ctrl+s to send now`, then a busy spinner and live composer. Plain
screen text cannot distinguish that queue row from a transcript copy with the
same rows. The sender leaves this shape ambiguous; an empty composer or
`Press up to edit queued messages` does not strengthen it. The measured frame
can return `mixed-input-after-paste` after one Enter. Inspect immediately for
independent new receipt evidence, such as a later submitted `❯` row without
the send-now hint or a recognized `Messages to be submitted` block; then mark
`delivered`. A subsequent response attributable to the exact message supports
`acknowledged (transport ambiguous)` or observed task completion, while the
sender's transport result stays ambiguous. If neither exists, leave delivery
unconfirmed and preserve the private pending payload. Claude may retain little
scrollback. Do not send a new message to manufacture proof or replay an
ambiguous payload.

The observed Codex `[Pasted Content N chars]` form is supported when it is the
whole input and N matches the payload's Unicode code-point or UTF-16-unit
length. Visible text outside this whole-paste marker is mixed input and stops
submission. For an independently observed fresh `[Pasted text …]` marker,
visible surrounding text must agree with the outgoing payload. A retained
file alone never establishes which paste is on screen.

## Unresolved paste records

An ordinary send publishes a private write-ahead record before pasting.
`tmux-message unresolved` lists attempts in
`${XDG_STATE_HOME:-~/.local/state}/tmux-message`. Use the same state home
for cooperating invocations. Each attempt has a unique ID, the resolved
receiver, the sender process and available tmux context, and the path to
the owner-only payload file. Listing reports metadata and finishes interrupted
cleanup of completed attempts. An attempt with no outcome may still be active
or have been interrupted. A controlled ambiguous outcome reports `enters`
and `submit_not_attempted`. The latter says what the sender attempted.
It provides no evidence of submission by the receiver or another actor.
A failed Enter operation can leave its effect unknown even when the sender
counted the call.

A confirmed transport receipt removes the attempt. A controlled ambiguity
after at least one completed Enter operation retains the ordinary temporary
pending file and releases the unresolved gate. A possible zero-Enter
ambiguity or crash stays discoverable and blocks sends to that receiver
identity. Other senders cannot overwrite the record, and a later pane or
server incarnation with reused numeric IDs cannot silently consume it.

Observe the exact receiver and identify this attempt before recording a
disposition. Use `receipt-confirmed` for independently verified fresh
application receipt, `acknowledged` for an attributable response,
`draft-removed` when the operator confirmed removal of the stranded draft,
or `receiver-replaced` when the original receiver is gone. For example:

```bash
tmux-message resolve ATTEMPT_ID --disposition receipt-confirmed
```

Resolution is metadata-only and works even after the receiver has exited.
It uses the same lock as delivery, records the disposition, and deletes the
payload bytes. Repeating the same disposition can finish pending cleanup.
A different disposition cannot overwrite it. A resolution is the operator's
recorded observation. It does not send Enter, clear a pane, verify a receipt
automatically, or replay a payload. Where authorized separately, deliberate
Enter-only recovery still requires fresh identification of the exact
retained paste, a compatible receiver, and no unrelated input or modal.

## Options

Options precede actual message text or `--prompt-file FILE`:

| Option | Default seconds | Purpose |
| --- | ---: | --- |
| `--stable-window` | submit-delay (8) | Interval between composer observations |
| `--stable-wait` | same | Compatibility alias for stable-window |
| `--max-wait` | 10 | Input readiness budget (launcher uses 30) |
| `--submit-delay` | 8 | Earliest first Enter after paste |
| `--render-wait` | 3 | Wait for initial paste evidence |
| `--receipt-wait` | 15 | Additional confirmation budget |
| `--retry-wait` | 3 | Minimum interval before the second Enter |
| `--poll-interval` | 0.25 | Screen sampling cadence |
| `--diagnostic-file ABSOLUTE_NEW_PATH` | off | One-attempt private structural diagnostic; see below |

`--backoff` waits within `--max-wait` for changing input to settle, rather than
returning immediately when typing is detected. Stable drafts no longer block
ordinary messages. Stability resets when input changes; choose a readiness
budget longer than the settle window.
The 8/3/10 submit/render/readiness defaults remain; input readiness now uses
the submit-delay as its default settle window, rather than three seconds;
receipt confirmation and recovery do not depend on shortening that delay.
The lock wait has a separate `--max-wait` budget. Confirmation is bounded by
render + submit-delay + receipt-wait; operations also have subprocess timeouts.
The launcher gives `/compact` its configured compaction timeout as the receipt
budget, because some layouts show only completion rather than an initial user
row. Receipt waits may exceed 600 seconds when explicitly configured.

### Opt-in structural diagnostic

`--diagnostic-file` is an explicit option on one `send` invocation. It does
not persist to subsequent calls, install a watcher, or collect additional
frames. The sender reserves a new file before any input. Its absolute parent
path must have no symlink component; the final directory must be owned by the
caller with mode 0700. Existing targets and unsafe paths return a fixed
`unsafe-diagnostic-path` usage error before paste, Enter, or cursor navigation.
The reserved file is mode 0600. The ordinary target resolver and per-pane lock
still pin the one destination; the diagnostic cannot redirect it.

The JSON artifact contains a fixed schema, safe outcome/reason enums, input
method, sender Enter count, the last pre-paste sample, at most 16 recent
post-paste samples, and bounded paste/Enter events. Samples report elapsed
time, pane dimensions, relative cursor, composer kind/harness, selected
predicate decisions, and at most 12 composer rows of 160 display cells each.
Every arbitrary non-whitespace glyph is replaced by a width-preserving `#`;
combining marks are omitted. SGR is reduced to the allowlisted style flags
bold, dim, italic, underline, inverse, foreground and background with cell
spans. Recognized prompt/paste/image marker types and bounded numeric counts
are separate fields. Unknown, modal, malformed or non-SGR control framing
yields no row structure. No raw ANSI/OSC payload, arbitrary text, history,
native identifier, pending payload, screenshot or text hash enters the file.
The entire JSON is capped at 64 KiB; older post-paste samples are dropped if
needed. This layout, cursor and timing metadata is still private and may
reveal word boundaries and lengths, including those of any human draft. Only
reviewed synthetic reconstruction belongs in public fixtures.

Diagnostic serialization or writing happens after the transport decision. A
late failure reports fixed `diagnostic_status=write-failed` while preserving
the send's original status, receipt, Enter count and exit code. Cleanup removes
the reserved name only if its device/inode still match; an unknown replacement
is left untouched. A successful artifact reports `diagnostic_status=written`.
If the process crashes or is killed, a reserved empty or partial file may
remain for its owner to inspect and dispose of; there is no automatic cleanup,
upload or retention policy. Normal pending-message ambiguity rules still
apply, and a diagnostic never licenses replay.
For slash commands such as `/compact` and `/exit`, use `--typed-command`: the sender inserts
literal characters with `tmux send-keys -l` rather than bracketed paste. The
same lock, input verification, settling delay, and NEW
receipt requirements apply. A command has an ASCII letter name (letters, digits, `_`
and `-`), optionally followed by a space and arguments. Controls, newlines,
leading whitespace, trailing Unicode whitespace or semicolons, commands over 200 UTF-8 bytes,
and ordinary prose are rejected. These limits avoid tmux argument loss and
ambiguous wrapped or trimmed composer evidence. Ordinary messages retain
bracketed paste. Typed commands require an empty composer and exact visible command text after
typing. A collapsed paste marker cannot
authorize its Enter. Failure JSON distinguishes `input_attempted` from
`paste_attempted` and labels `input_method`; an ambiguous typed attempt must
never be blindly replayed. `--typed-command` and `--literal-exit` cannot be combined.

Payloads are nonblank UTF-8 with no control characters except newlines. Message
bytes, including trailing whitespace/newlines, are preserved in the paste.

Exit 0 emits delivered JSON on stdout. Failures emit JSON on stderr.
Exit 2 means deferred before outgoing input. Exit 3 means ambiguous after
outgoing input may have occurred. The Claude suggestion probe can still
have occurred before a deferral. Use `input_attempted` to determine whether
outgoing input may have occurred. `paste_attempted` applies to bracketed
paste, with its compatibility meaning for `--literal-exit`. Signals retain
conventional 128+signal exit codes except for selected compaction after input.
Unsuccessful sends retain the outgoing message privately, either as an
unresolved attempt or as a private temporary file. Remove temporary payloads
after disposition. If private storage fails, the result reports the failure.

## Verify a typed Codex compaction

```bash
tmux-message send %PANE --typed-command --verify-compact /compact
```

`--verify-compact` requires `--typed-command` with the exact positional
argument `/compact`. Other arguments, prompt files, paste, and
`--literal-exit` combinations exit 1 before resolving the pane. Malformed
timing options use argparse's pre-input usage exit 2. A detected draft, a
known non-Codex harness, or an unverified composer defers with exit 2
without sending keys. The sender types once
only after verifying the canonical empty cursor position and a single
blank separator before the footer. A dim Codex placeholder at that position
classifies as empty. The separate suggestion state applies to Claude.
Visible whitespace in the prompt or extra blank rows defer even when the
parsed text is empty. A space-only draft whose cells are absent from the
capture can be indistinguishable from empty input if its cursor is at Home.
After typing and again immediately before Enter, the sender requires the
untrimmed single-line command, the empty separator, and the cursor at the
end of the command. Visible trailing spaces or an extra blank row stop
submission even if the cursor moves back to the command end. Trailing spaces
omitted by capture can be indistinguishable if the cursor returns to that
position. Lost ownership preserves the input and sends no Enter. The attempt
sends at most one Enter.

The last pre-Enter capture establishes the baseline. The sender looks for
either full, flush-left row above a recognized Codex composer. It strips
ANSI styling and terminal padding.

- `• Context compacted`, optionally followed by a rendered elapsed time
  such as ` · 14s`, ` · 1m 04s` or ` · 2h 01m 04s`.
- `■ '/compact' is disabled while a task is in progress.`

The shapes come from the Codex 0.170.0 renderer. [Completion](https://github.com/openai/codex/blob/29eb79e9866b3262a777fdf8195c1b9e63684c91/codex-rs/tui/src/chatwidget/compaction.rs#L42-L55),
[elapsed time](https://github.com/openai/codex/blob/29eb79e9866b3262a777fdf8195c1b9e63684c91/codex-rs/tui/src/status_indicator_widget.rs#L75-L90),
[active-turn refusal](https://github.com/openai/codex/blob/29eb79e9866b3262a777fdf8195c1b9e63684c91/codex-rs/tui/src/chatwidget/slash_dispatch.rs#L187-L193)
and [history row prefixes](https://github.com/openai/codex/blob/29eb79e9866b3262a777fdf8195c1b9e63684c91/codex-rs/tui/src/history_cell/notices.rs#L334-L356).

A distinct notice can establish freshness. A full-screen repaint can copy
an identical old notice into scrollback, so extra scrollback copies leave
its freshness unknown. An identical notice can count if a single visible
frame contains more copies than the entire baseline capture. The baseline
and receipt frames require a positive measured pane width. A missing or
non-positive baseline width stops the attempt before Enter with `unknown`.
A receipt width that is non-positive or differs from the baseline also
ends verification with `unknown`. Reflow can turn a wrapped old notice
into an exact row.

The `--receipt-wait` window starts after the synchronous Enter call returns.
A completion or refusal normally takes the full window to report, even when
the notice appears immediately. The default is 15 seconds. Waiting through
the window allows a contradictory notice to change the outcome to unknown.
Once input is attempted, the result has `command_outcome`.

| Outcome | Status | Exit |
| --- | --- | --- |
| `completed` | `delivered` with `receipt=command` | 0 |
| `refused` | `refused` | 3 |
| `unknown` | `ambiguous` | 3 |

A refusal can leave `/compact` in the composer.

Existing history, ordinary submit or queue receipts, progress, and silence
cannot establish an outcome. Conflicting notices, unsupported layouts with no
verifiable evidence, and notices outside the window leave it unknown. A row
that wraps or scrolls out can be missed. Rendered history carries no command
identifier, so a concurrent compaction or identical output can be
indistinguishable. Input protection remains observational. After refusal or
ambiguity the private pending payload is retained for inspection. The sender
never retypes it or retries Enter. Unselected commands and the fork launcher's
native completion watcher keep their existing semantics.

## Agent escalation and extension

`needs_review=true` means a caller can use `tmux-message read TARGET` to inspect
an unsupported layout, modal or ambiguous attempt. The result also carries a
reason, paste-attempted flag and Enter count. An orchestrator may delegate this
inspection to an agent; there is no compulsory model call or model dependency
inside the sender. The inspecting agent must check for receipt before taking
any further action. Changing input normally needs only bounded backoff. Stable drafts defer.

Screen interpretation uses semantic prompt/frame/footer and queue markers,
relative cursor position, and before/after receipt counts, not model identity
or fixed row offsets. Extend the composer/receipt functions with representative
frames for additional harnesses; the send/recovery loop stays shared.

These are evidence-based heuristics, not atomic ownership proofs. Humans can
type between observations; whitespace-only differences are not message identity;
assistant output deliberately formatted like a user message can be ambiguous.
History outside the captured 2000-row window and layouts that hide both input
and acceptance can cause a timeout. Such cases require inspection, not replay.
The Codex launcher uses `--no-alt-screen`: alternate-screen mode can discard a
long receipt's first rows before the sender can sample them. Existing sessions
retain their launch mode; the sender does not reconfigure or restart them.
Unknown shells, modals and unsupported input surfaces do not authorize paste.

Run `test-tmux-message.py` for behavior tests and `test-tmux-message-live.py`
for a private real tmux test with a deterministic terminal. Neither uses model
tokens or touches installed tools or live controllers.

## Literal Claude exit

For a verified retirement handoff, send the bare `/exit` with `--literal-exit`.
Claude treats pasted slash commands as text; this mode uses `tmux send-keys -l`
for `/exit` through the same stability, composer, lock and ownership checks.
It sends at most one Enter, never a second recovery Enter. Other payloads and
other harnesses are rejected before input. Success requires a fresh shell
resume notice (`Resume this session with:` followed by `claude --resume UUID`),
not a submitted user row. The retirement caller separately verifies the
original harness processes ended. A modal, mixed input or missing fresh notice
preserves the attempt for inspection; do not retype it blindly.

The compatibility `paste_attempted` field also means a literal input attempt
in this mode. A successful literal exit reports `transport: "literal"` and
`receipt: "command"`. Example: `tmux-message send %PANE --literal-exit /exit`.

## Python observation contract

Callers may import `scripts/tmux-message.py` from this same skill installation
and use `read_response_rows(pane, socket)` with a stable `%PANE_ID` and absolute
verified socket path. Register the imported module in `sys.modules` before
executing it, as required for dataclasses. This read-only API returns
ANSI-stripped visible rows strictly above a recognized composer. It returns
`None` for modal or unknown layouts, including a frame whose cursor or size
changes during capture, and raises `DeliveryError`
with a sanitized `reason` for invalid targets or server/read failure.
It never types, pastes, probes, returns archived redraw history, or changes
global environment variables. Missing read evidence is not process-end proof.
All other Python names are internal; actual sends use the public CLI.

For `--literal-exit` only, a stable Claude canonical `Try "…"` suggestion
with its cursor at the input start counts as idle, as authorized for retirement.
Unquoted suggestions, multiline input, and a cursor in actual draft text still
defer. Ordinary messages retain the probe-and-defer rule. This distinction is
screen evidence and cannot exclude a human typing between observations.

Observation checks cursor and size around one capture; it does not establish a
multi-sample typing-stability interval. The send path performs its own stable
input checks. Literal-exit unit and disposable-terminal tests do not model every
real Claude slash-command menu layout. An unrecognized menu remains a safe
deferral; do not infer compatibility or retry an ambiguous exit from these tests.

Completion consumers require a marker-only final assistant block. Nonblank
status or queued-message rows between that block and the composer keep
retirement pending; fixtures cover blank rows and plain horizontal rules.
