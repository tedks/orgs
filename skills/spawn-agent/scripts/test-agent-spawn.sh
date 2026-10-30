#!/bin/bash
# Launcher boundary tests plus retained structured completion watcher tests.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/test-agent-spawn.py"
python3 "$SCRIPT_DIR/test-codex-fork-task.py"
TEST_DIR=$(mktemp -d)
trap 'rm -rf -- "$TEST_DIR"' EXIT
WATCH="$SCRIPT_DIR/codex-jsonl-watch.py"
STDERR="$TEST_DIR/stderr"
ROLLOUT="$TEST_DIR/.codex/sessions/2026/09/05/rollout-2026-09-05T03-00-00-01a07050-1111-7222-8333-444444444444.jsonl"
mkdir -p "$(dirname "$ROLLOUT")"
printf '%s\n' '{"type":"session_meta","payload":{"id":"01a07050-1111-7222-8333-444444444444"}}' > "$ROLLOUT"
# The JSONL watcher ignores prompt/user/commentary/non-prefix matches. A valid
# final assistant record is invisible until its terminating newline arrives,
# then its full multi-part output is printed exactly once.
JSONL="$TEST_DIR/watcher.jsonl"
WATCH_OUT="$TEST_DIR/watcher.out"
MARKER='STEP-JSONL-91ac COMPLETE — EXECUTIVE RECAP'
EXPECTED="$MARKER
All work is verified."
: > "$JSONL"
"$WATCH" recap "$JSONL" "$MARKER" 5 > "$WATCH_OUT" &
watch_pid=$!
printf '%s\n' \
    '{"type":"response_item","payload":{"type":"message","role":"user","phase":"final_answer","content":[{"type":"output_text","text":"STEP-JSONL-91ac COMPLETE — EXECUTIVE RECAP"}]}}' \
    '{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"commentary","content":[{"type":"output_text","text":"STEP-JSONL-91ac COMPLETE — EXECUTIVE RECAP"}]}}' \
    '{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"final_answer","content":[{"type":"output_text","text":"prefix STEP-JSONL-91ac COMPLETE — EXECUTIVE RECAP"}]}}' \
    >> "$JSONL"
matching='{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"final_answer","content":[{"type":"output_text","text":"STEP-JSONL-91ac COMPLETE — EXECUTIVE RECAP\n"},{"type":"output_text","text":"All work is verified."}]}}'
split=$(( ${#matching} / 2 ))
printf '%s' "${matching:0:split}" >> "$JSONL"
/bin/sleep 0.4
kill -0 "$watch_pid"
[[ ! -s "$WATCH_OUT" ]]
printf '%s\n' "${matching:split}" >> "$JSONL"
wait "$watch_pid"
[[ "$(<"$WATCH_OUT")" == "$EXPECTED" ]]
[[ $(grep -oF "$MARKER" "$WATCH_OUT" | wc -l) -eq 1 ]]

# Session IDs resolve to rollout paths, and cursor stops after the final
# newline rather than skipping an incomplete trailing record.
session_result=$(CODEX_HOME="$TEST_DIR/.codex" "$WATCH" recap \
    01A07050-1111-7222-8333-444444444444 "$MARKER" 1 \
    --after-byte 0 2>"$STDERR" || true)
[[ -z "$session_result" ]]
grep -Fq 'timed out' "$STDERR"
printf '{}\n{"partial"' > "$JSONL"
[[ "$($WATCH cursor "$JSONL")" -eq 3 ]]

if "$WATCH" recap "$JSONL" "$MARKER" nan >/dev/null 2>"$STDERR"; then
    echo 'FAIL: non-finite timeout was accepted' >&2
    exit 1
fi
grep -Fq 'timeout must be a positive number' "$STDERR"

# Codex can rewrite a large rollout to its smaller compacted form when the
# task begins. The watcher restarts at byte zero, ignores inherited records by
# shape/marker, and still emits the later matching final response exactly once.
TRUNCATED_JSONL="$TEST_DIR/truncated-watcher.jsonl"
TRUNCATED_OUT="$TEST_DIR/truncated-watcher.out"
printf '%04096d\n' 0 > "$TRUNCATED_JSONL"
truncated_cursor=$(wc -c < "$TRUNCATED_JSONL")
"$WATCH" recap "$TRUNCATED_JSONL" "$MARKER" 5 \
    --after-byte "$truncated_cursor" > "$TRUNCATED_OUT" &
truncated_pid=$!
/bin/sleep 0.3
printf '%s\n' \
    '{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"final_answer","content":[{"type":"output_text","text":"an inherited final without the marker"}]}}' \
    > "$TRUNCATED_JSONL"
/bin/sleep 0.3
printf '%s\n' "$matching" >> "$TRUNCATED_JSONL"
wait "$truncated_pid"
[[ "$(<"$TRUNCATED_OUT")" == "$EXPECTED" ]]

# Compaction events have no unique marker, so a shrink must fail closed rather
# than rescan and accidentally accept an inherited context_compacted event.
printf '%04096d\n' 0 > "$TRUNCATED_JSONL"
truncated_cursor=$(wc -c < "$TRUNCATED_JSONL")
"$WATCH" compaction "$TRUNCATED_JSONL" "$truncated_cursor" 5 \
    > /dev/null 2> "$STDERR" &
truncated_pid=$!
/bin/sleep 0.3
printf '%s\n' '{"type":"event_msg","payload":{"type":"context_compacted"}}' \
    > "$TRUNCATED_JSONL"
if wait "$truncated_pid"; then
    echo 'FAIL: compaction watcher accepted an event after rollout truncation' >&2
    exit 1
fi
grep -Fq 'rollout was truncated' "$STDERR"

# New Codex compaction record is accepted only after the supplied cursor.
printf '%s\n' '{"type":"compacted","payload":{}}' > "$JSONL"
old_compact_after=$("$WATCH" cursor "$JSONL")
if "$WATCH" compaction "$JSONL" "$old_compact_after" 0.1 > /dev/null 2> "$STDERR"; then
    echo 'FAIL: inherited compacted record accepted' >&2; exit 1
fi
printf '%s\n' '{"type":"compacted","payload":{}}' >> "$JSONL"
"$WATCH" compaction "$JSONL" "$old_compact_after" 1 > /dev/null
echo 'PASS: shared tmux launcher delivery and optional JSONL completion'
