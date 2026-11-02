# Blocking tmux delivery

Targets are exact `SESSION:WINDOW` names, stable `%PANE_ID`, or stable
`@WINDOW_ID` (its active pane). Prefixes, globs, bare names and implicit
window-index selectors are rejected. Named windows must be unique in the named
session. Resolution uses `list-windows`/`list-panes`, never `display-message`,
which may fall back to the active pane when a target is missing. Operations pin
the resolved pane ID; deletion afterward causes failure rather than retargeting.

The public sender uses `tmux-message.py`. It returns success only after observing
new application receipt evidence. The older `claude-send.sh` remains available
for compatibility, with transport-only semantics. Its measured busy Codex queue
layouts verify only single-line input, so ordinary drafts there defer before
input. Eligible command drafts can be cleared first; empty composers permit
supported short messages. Both entry points use `--typed-command`
explicitly for single-line slash commands; ordinary messages retain bracketed paste.

## Flow

1. Resolve the target to a stable pane and acquire one per-pane sender lock.
2. Compare the input text and relative cursor twice, one `--stable-window`
   apart (default: submit-delay, normally eight seconds). Output moving above
   the input does not count as typing. Changing input defers with bounded
   backoff. Preserve an unchanged draft and append a newline plus the outgoing
   payload; submit both only after verifying the combined input. Record only
   draft length (`stale_draft_length`). Modals and unsupported layouts defer.
   A draft must have a visibly verified end cursor. A stable single-line draft
   at its canonical Home cursor may receive End, followed by verification that
   its text is unchanged and its cursor is at the known end. Repaint polling
   stays within the original readiness budget. Unchanged Home drafts or
   incomplete repaint frames receive no further keys while waiting; known
   changed text, harness, modal or another cursor position stops the attempt. Other non-end
   positions defer. Collapsed markers and
   recognizable full outgoing content already in the draft remain ambiguous
   and defer. This prevents a retained combined input from receiving the same
   payload twice after a failed attempt. The replay guard compares full payload
   content ignoring whitespace; independently authored text containing the
   same content also conservatively defers. A Claude `Try …`
   suggestion retains the conservative Space/Backspace probe; suggestions are
   disabled fleet-wide, so normal idle Claude input is empty.
3. Snapshot receipt history, recheck input, and paste actual text once through
   tmux bracketed paste. For new input, compare the result with the expected
   text, tolerating wrapping/whitespace layout, or recognize a newly introduced
   collapsed paste marker. For co-submission, require the exact combined input
   or a measured harness-specific append marker described below.
4. Send Enter after paste evidence and the settling delay. A Claude
   stable-draft co-submission gets one Enter maximum. Other ordinary deliveries
   retain one bounded Enter retry if the same input remains after the retry
   interval. Wait for a new submitted user row or pending queue entry. An
   unclear result is ambiguous and may leave a combined draft and hidden paste
   unsent; never paste again or send another Enter after ambiguity.
5. Once the input empties, only wait for confirmation. Disappearance alone is
   not confirmation, and cannot authorize Enter into the next empty input.

New receipt means an additional matching record compared with the pre-paste
history. A collapsed receipt can match a marker observed in this attempt's
input; a marker found only in history is insufficient. Ordinary assistant prose
is not a receipt. `/compact` may instead be confirmed by a new visible
`Context compacted` completion event. Receipt and task completion remain distinct.

The observed Codex `[Pasted Content N chars]` form is supported when it is the
whole input and N matches the payload's Unicode code-point or UTF-16-unit
length. Visible text outside this whole-paste marker is mixed input and stops
submission. Existing `[Pasted text …]` markers retain their surrounding-text
checks. A retained file alone never establishes which paste is on screen.

For ordinary co-submission, Codex 0.157.1 can display the unchanged draft
immediately followed by `[Pasted Content N chars]`, with the appended newline
inside that collapsed block. The public sender accepts this measured shape
only when the original draft prefix is exact, the marker is the entire remaining
input, the original and current harness are Codex, and the cursor is at the
verified end. N must equal the newline plus outgoing payload's Unicode
code-point or UTF-16-unit count. Readiness rejects pre-existing paste markers
case-insensitively, so this evidence belongs to the current paste. Changed
prefixes, extra text, wrong counts and unsupported markers cannot authorize
Enter. A new matching submitted or queued receipt is still required; no replay
is introduced. Other Codex wrapped/collapsed co-submission shapes remain
unsupported.

Claude Code 2.1.283 can replace a long bracketed paste appended to a stable
ordinary draft with `[Pasted text #N +K lines]` while leaving the exact original
draft prefix visible. The sender accepts only this measured co-submit shape when
the prefix is exact, the marker is the only suffix, K equals one plus the
outgoing payload's newline count, the current and original harness are Claude,
and the cursor is at the verified end. The transient `paste again to expand`
hint is transient and is ignored. The current paste operation
appends one newline and the outgoing payload, and readiness excludes old paste
markers, so this marker is consistent with the one fresh paste. Its hidden
bytes cannot be inspected, so the marker does not prove the pasted contents.
After the sender first recognizes this shape, any change to the owned input
before submission defers. Other Claude markers, extra text, changed prefixes,
wrapped prefixes, and cursor or harness changes defer. All Claude stable-draft
co-submissions send Enter at most once and require a new submitted or queued
receipt; they never retry Enter or re-paste after ambiguity. Visible full-text
co-submission also requires the exact draft + newline + payload, the same
harness, and an end cursor.

The compatibility `claude-send.sh` uses the same exact Claude co-submit input
predicate and freezes its first recognized text/cursor fingerprint through its
single Enter. It keeps its legacy `status=sent receipt=unverified` result and
does not claim application delivery. It preserves exact visible hard-newline
rows, including matching trailing blank rows through the cursor; cropped views,
unsupported wrapped-prefix layouts, changed rows, and misplaced cursors remain
ambiguous. Its legacy Codex collapsed-append recognition retains its existing
visible-input limits.

For Claude 2.1.283's measured submitted-row layout, the native receipt may show
the draft after `❯`, one blank separator row, then the payload on continuation
rows with the measured two-space indent. The sender checks that complete block
against the same expected co-submit body and the pre-paste count, using the
existing receipt normalization for terminal wrapping. This public receipt
check supports only the measured single blank separator; extra blank paragraphs
and cropped views remain ambiguous. It only counts an explicit new column-zero
`❯` user row before a recognized current composer;
assistant prose, an archived composer, an incomplete or cropped block, and an
unchanged old body do not confirm delivery. Other blank-row or queued layouts
remain subject to the ordinary receipt parser and may stay ambiguous.

## Stable command drafts

A stable command-shaped draft is cleared without executing it before the
outgoing message is sent. The message supplies context that may pre-empt the
command. This is the explicit exception to ordinary draft preservation.
Only an exact visible single-line command in a recognized composer is eligible:
slash command syntax follows the validated `--typed-command` grammar and
200-byte limit; a supported single-line `!` shortcut follows the same visible
shape limits. Real command-clear smokes cover slash drafts; `!` eligibility
is tested only in synthetic recognized prompt frames. A bash-mode prompt with
a different glyph remains unknown and defers; real `!` clearing is unverified.
Command names are recognized syntactically, so an existing draft
such as `/tmp is full again` is command-shaped. Outgoing slash-looking prose
still uses ordinary paste unless `--typed-command` is explicit.

Recheck the stable draft, verify its end cursor, send Ctrl-U once, and wait
within the original readiness budget for an empty composer of the same
harness. Incomplete repaint and unchanged command frames receive no further
keys. Known new text, modal, harness or cursor changes stop the attempt. Recheck
empty input before dispatching the outgoing payload. Never execute the discarded
command or retry clearing blindly. Long, malformed, multiline or unsupported
command-like drafts defer; replay residue and collapsed markers take precedence
and cannot authorize clearing.

Results include `cleared_command_draft_length` only after empty input is
verified, and `clear_attempted` whenever clearing was attempted, never the
command's contents. A failure after a clear attempt is ambiguous even if
`input_attempted` and `paste_attempted` are false: those fields describe outgoing
input only. The retained pending file still contains only the outgoing payload.

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
For slash commands such as `/compact` and `/exit`, use `--typed-command`: the sender inserts
literal characters with `tmux send-keys -l` rather than bracketed paste. The
same lock, input verification, settling delay, and NEW
receipt requirements apply. A command has an ASCII letter name (letters, digits, `_`
and `-`), optionally followed by a space and arguments. Controls, newlines,
leading whitespace, trailing Unicode whitespace or semicolons, commands over 200 UTF-8 bytes,
and ordinary prose are rejected. These limits avoid tmux argument loss and
ambiguous wrapped or trimmed composer evidence. Ordinary messages retain
bracketed paste. Typed commands require an empty composer: joining a draft
would change command semantics, so ordinary stable drafts defer in this mode.
Eligible command drafts are cleared and verified empty first. Typed
input requires exact visible command text; a collapsed paste marker cannot
authorize its Enter. Failure JSON distinguishes `input_attempted` from
`paste_attempted` and labels `input_method`; an ambiguous typed attempt must
never be blindly replayed. `--typed-command` and `--literal-exit` cannot be combined.

Payloads are nonblank UTF-8 with no control characters except newlines. Message
bytes, including trailing whitespace/newlines, are preserved in the paste.

Exit 0 emits delivered JSON on stdout. Failures emit JSON on stderr. Exit 2
means deferred before a clear or outgoing input attempt. Cursor navigation and
the suggestion probe may still have occurred. Exit 3 means ambiguous after a clear
or outgoing input attempt.
Use `input_attempted` to determine whether outgoing input may have occurred.
Either `clear_attempted` or `input_attempted` indicates possible composer mutation;
`paste_attempted` applies to bracketed paste, except that the legacy
`--literal-exit` mode retains its compatibility meaning of any input attempt.
Both literal modes report `input_method: "typed"`. Signals retain conventional 128+signal exit
codes. Unsuccessful attempts retain the outgoing message in a private temporary
directory (700) with a private file (600). Remove that file/directory after
resolving it. No human draft or pane contents are logged automatically.

## Agent escalation and extension

`needs_review=true` means a caller can use `tmux-message read TARGET` to inspect
an unsupported layout, modal or ambiguous attempt. The result also carries a
reason, paste-attempted flag and Enter count. An orchestrator may delegate this
inspection to an agent; there is no compulsory model call or model dependency
inside the sender. The inspecting agent must check for receipt before taking
any further action. Changing input normally needs only bounded backoff; an unchanged draft is
co-submitted with ordinary messages. Typed commands still require empty input.

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
