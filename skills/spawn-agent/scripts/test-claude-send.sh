#!/bin/bash
# Fake-tmux regression tests for human-composer-safe claude-send delivery.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export FIXTURES="$SCRIPT_DIR/fixtures/claude-send"
source "$SCRIPT_DIR/claude-pane-detect.sh"
for fixture in claude-2.1.302-login-modal.ansi claude-2.1.302-trust-modal.ansi \
               claude-2.1.302-permission-modal.ansi claude-2.1.302-exit-background-modal.ansi \
               SYNTHETIC-claude-update-dialog.ansi \
               SYNTHETIC-UNVERIFIED-claude-unsent-feedback-exit-dialog.ansi; do
  screen=$(cat "$FIXTURES/$fixture")
  claude_modal_active "$screen" || { echo "FAIL: $fixture was not modal" >&2; exit 1; }
  claude_composer_ready "$screen" && { echo "FAIL: $fixture looked ready" >&2; exit 1; }
done
screen=$(cat "$FIXTURES/SYNTHETIC-claude-yes-draft-usage-footer.ansi")
[[ "$screen" == *$'\xe2\x9d\xaf\xc2\xa0'* ]] || { echo 'FAIL: Yes-draft fixture lost the NBSP composer marker' >&2; exit 1; }
claude_modal_active "$screen" && { echo 'FAIL: no-cursor Yes draft looked modal' >&2; exit 1; }
claude_composer_ready "$screen" || { echo 'FAIL: no-cursor Yes draft was not ready' >&2; exit 1; }
for fixture in claude-2.1.302-auto-update-footer-live-scrubbed.ansi \
               claude-2.1.299-feedback-count-footer-live-scrubbed.ansi \
               SYNTHETIC-claude-2.1.302-usage-limit-footer.ansi \
               SYNTHETIC-claude-2.1.302-new-task-footer.ansi; do
  screen=$(cat "$FIXTURES/$fixture")
  claude_modal_active "$screen" && { echo "FAIL: $fixture looked modal" >&2; exit 1; }
  claude_composer_ready "$screen" || { echo "FAIL: $fixture was not ready" >&2; exit 1; }
done
screen="$(cat "$FIXTURES/claude-2.1.302-trust-modal.ansi")"$'\n'"$(cat "$FIXTURES/claude-blank.ansi")"
cursor_y=$(($(printf '%s\n' "$screen" | wc -l) - 2))
claude_modal_active "$screen" "$cursor_y" && { echo 'FAIL: old dialog text hid live composer' >&2; exit 1; }
claude_composer_ready "$screen" "$cursor_y" || { echo 'FAIL: old dialog text blocked live composer' >&2; exit 1; }
claude_modal_active() { return 2; }
screen=$(cat "$FIXTURES/claude-2.1.302-auto-update-footer-live-scrubbed.ansi")
claude_composer_ready "$screen" && { echo 'FAIL: classifier error looked ready' >&2; exit 1; }
source "$SCRIPT_DIR/claude-pane-detect.sh"
TEST_DIR=$(mktemp -d /tmp/test-claude-send.XXXXXX)
TEST_REAL_PYTHON3=$(command -v python3)
export TEST_REAL_PYTHON3
cleanup_test() {
  local rc=$?
  if ((rc == 0)); then
    rm -rf "$TEST_DIR"
  else
    echo "fake-tmux diagnostics preserved at $TEST_DIR" >&2
    if [[ -s "$FAKE_STATE/last-screen" && -s "$FAKE_STATE/last-cursor" ]]; then
      printf 'fake tmux command/exit trace:\n' >&2
      cat "$FAKE_STATE/tmux-trace" >&2 2>/dev/null || true
      printf 'fake parser command/exit trace:\n' >&2
      cat "$FAKE_STATE/parser-trace" >&2 2>/dev/null || true
      if [[ -f "$FAKE_STATE/last-parser-input" ]]; then
        printf 'last parser input:\n' >&2; cat "$FAKE_STATE/last-parser-input" >&2
      fi
      printf 'last fake pane mode: ' >&2; cat "$FAKE_STATE/mode" >&2
      printf 'last fake cursor: '; cat "$FAKE_STATE/last-cursor" >&2
      printf 'last fake screen:\n' >&2; cat "$FAKE_STATE/last-screen" >&2
      IFS=: read -r diag_x diag_y < "$FAKE_STATE/last-cursor"
      printf 'classifier result for synthetic payload: ' >&2
      python3 "$SCRIPT_DIR/claude-send-screen.py" "$TEST_DIR/payload" "$diag_x" "$diag_y" \
        < "$FAKE_STATE/last-screen" >&2 || true
    fi
  fi
  return "$rc"
}
trap cleanup_test EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/state" "$TEST_DIR/buffers"
mkdir -p "$TEST_DIR/runtime"
export FIXTURE_CURRENT="$FIXTURES/codex-context-queue.ansi"
export FAKE_STATE="$TEST_DIR/state"
export FAKE_LOG="$TEST_DIR/tmux.log"
export FAKE_BUFFER_DIR="$TEST_DIR/buffers"
export XDG_STATE_HOME="$TEST_DIR/state-home"
export XDG_RUNTIME_DIR="$TEST_DIR/runtime"
export CLAUDE_SEND_LOCK_DIR="$TEST_DIR/locks"
export SPAWN_TMUX_SOCKET="$TEST_DIR/tmux.sock"
export PATH="$TEST_DIR/bin:$PATH"

cat > "$TEST_DIR/bin/python3" <<'STUB'
#!/bin/bash
if [[ "${FAKE_VIRTUAL_CLOCK:-0}" == 1 && "${1:-}" == -c && "${2:-}" == *monotonic_ns* ]]; then
  exec "$TEST_REAL_PYTHON3" -c 'import pathlib,sys,time; clockpath=pathlib.Path(sys.argv[1]); time.monotonic_ns=lambda: int(clockpath.read_text()); program=sys.argv[2]; sys.argv=["-c"]+sys.argv[3:]; exec(program)' "$FAKE_STATE/clock" "$2" "${@:3}"
fi
if [[ "${FAKE_FAIL_CLOCK_BEFORE_PASTE:-0}" == 1 && "$*" == *monotonic_ns* && ! -s "$FAKE_STATE/pasted" ]]; then
  printf 'injected monotonic clock subprocess failure\n' >&2
  exit 1
fi
if [[ "${1:-}" == */claude-send-screen.py ]]; then
  input=$(mktemp "$FAKE_STATE/parser-input.XXXXXX")
  output=$(mktemp "$FAKE_STATE/parser-output.XXXXXX")
  errors=$(mktemp "$FAKE_STATE/parser-errors.XXXXXX")
  cat > "$input"
  if [[ "${FAKE_FAIL_PARSER_AFTER_PASTE:-0}" == 1 && -s "$FAKE_STATE/pasted" ]]; then
    printf 'injected classifier subprocess failure\n' > "$errors"
    rc=64
  else
    "$TEST_REAL_PYTHON3" "$@" < "$input" > "$output" 2> "$errors"
    rc=$?
  fi
  cp "$input" "$FAKE_STATE/last-parser-input"
  printf 'exit=%s args=%q output=%q stderr=%q\n' "$rc" "$*" "$(<"$output")" "$(<"$errors")" >> "$FAKE_STATE/parser-trace"
  cat "$output"
  cat "$errors" >&2
  exit "$rc"
fi
exec "$TEST_REAL_PYTHON3" "$@"
STUB

cat > "$TEST_DIR/bin/tmux" <<'STUB'
#!/bin/bash
set -euo pipefail
while [[ "${1:-}" == -S || "${1:-}" == -L ]]; do shift 2; done
cmd=$1; shift
original_args=$*
record_tmux_exit() {
  local rc=$?
  printf 'exit=%s command=%q args=%q\n' "$rc" "$cmd" "$original_args" >> "$FAKE_STATE/tmux-trace"
}
trap record_tmux_exit EXIT
printf '%s\n' "$cmd" >> "$FAKE_STATE/tmux-calls"
case "$cmd" in
  list-windows) printf '@7\tworker\n@8\talias\n';;
  list-panes)
    if [[ "$*" == *"@8"* ]]; then printf '4242:%%7:1:alias\n'; else printf '4242:%%7:1:worker\n'; fi;;
  display-message)
    if [[ "${*: -1}" == '#{pid}:#{pane_id}' ]]; then printf '4242:%%7\n'
    elif [[ "${*: -1}" == '#{cursor_x}:#{cursor_y}' ]]; then
      if [[ "$(<"$FAKE_STATE/mode")" == forkcompact && -s "$FAKE_STATE/pasted" ]]; then cursor='10:50'
      elif [[ "$(<"$FAKE_STATE/mode")" == forkcompact ]]; then cursor='2:50'
      elif [[ "$(<"$FAKE_STATE/mode")" == busycontext-draft ]]; then cursor="$(($(wc -m < "$FAKE_STATE/composer") + 2)):2"
      elif [[ "$(<"$FAKE_STATE/mode")" == busyqueue-draft ]]; then cursor="$(($(wc -m < "$FAKE_STATE/composer") + 2)):27"
      elif [[ "$(<"$FAKE_STATE/mode")" == busycontext && -s "$FAKE_STATE/pasted" ]]; then cursor='57:2'
      elif [[ "$(<"$FAKE_STATE/mode")" == busycontext ]]; then cursor='2:2'
      elif [[ "$(<"$FAKE_STATE/mode")" == busyqueue && -s "$FAKE_STATE/pasted" ]]; then cursor='37:27'
      elif [[ "$(<"$FAKE_STATE/mode")" == busyqueue ]]; then cursor='2:27'
      elif [[ "$(<"$FAKE_STATE/mode")" == stable-claude-trailing-lf && -s "$FAKE_STATE/pasted" ]]; then cursor='2:4'
      elif [[ "$(<"$FAKE_STATE/mode")" == stable-claude-marker-preenter && -s "$FAKE_STATE/pasted" ]]; then
        ordinal=3; [[ "$(<"$FAKE_STATE/marker-screen-count")" -ge 3 ]] && ordinal=4
        marker="stale TICK[Pasted text #$ordinal +2 lines]"
        cursor="$(($(printf '%s' "$marker" | wc -m) + 2)):1"
      elif [[ "$(<"$FAKE_STATE/mode")" == stable-claude-marker && -s "$FAKE_STATE/pasted" ]]; then
        ordinal=3; [[ -s "$FAKE_STATE/marker-seen" ]] && ordinal=4
        marker="stale TICK[Pasted text #$ordinal +2 lines]"
        cursor="$(($(printf '%s' "$marker" | wc -m) + 2)):1"
      elif [[ "$(<"$FAKE_STATE/mode")" == stable-claude-marker-harness && -s "$FAKE_STATE/pasted" ]]; then
        marker='stale TICK[Pasted text #3 +2 lines]'
        cursor="$(($(printf '%s' "$marker" | wc -m) + 2)):1"
      elif [[ "$(<"$FAKE_STATE/mode")" == stable-codex-marker-claude && -s "$FAKE_STATE/pasted" ]]; then
        marker='stale TICK[Pasted text #3 +2 lines]'
        cursor="$(($(printf '%s' "$marker" | wc -m) + 2)):1"
      elif [[ "$(<"$FAKE_STATE/mode")" == persistent-empty-after-paste && -s "$FAKE_STATE/pasted" ]]; then cursor='2:1'
      elif [[ "$(<"$FAKE_STATE/mode")" == render-stale-empty && -s "$FAKE_STATE/pasted" && $(<"$FAKE_STATE/captures") -eq 4 ]]; then cursor='2:1'
      elif [[ "$(<"$FAKE_STATE/mode")" == home-* && ( ! -s "$FAKE_STATE/end-moved" || "$(<"$FAKE_STATE/mode")" == *-noend || "$(<"$FAKE_STATE/mode")" == *-delay && $(<"$FAKE_STATE/captures") -le $(($(<"$FAKE_STATE/end-capture") + 2)) ) ]]; then cursor='2:1'
      elif [[ "$(<"$FAKE_STATE/mode")" == human || "$(<"$FAKE_STATE/mode")" == slash ]]; then cursor='4:1'
      elif [[ -s "$FAKE_STATE/composer" ]]; then
        cursor=$(python3 - "$FAKE_STATE/composer" <<'PY'
from pathlib import Path
import sys
rows = Path(sys.argv[1]).read_text().splitlines()
print(f"{2 + len(rows[-1])}:{1 + len(rows) - 1}")
PY
        )
      elif [[ "$(<"$FAKE_STATE/mode")" == streaming ]]; then cursor='2:2'
      else cursor='2:1'; fi
      printf '%s\n' "$cursor" > "$FAKE_STATE/last-cursor"
      printf '%s\n' "$cursor"
    else printf '0\n'; fi
    ;;
  capture-pane)
    n=0; [[ -f "$FAKE_STATE/captures" ]] && n=$(<"$FAKE_STATE/captures")
    n=$((n + 1)); printf '%s' "$n" > "$FAKE_STATE/captures"
    mode=$(<"$FAKE_STATE/mode")
    if [[ "$mode" == interrupt-before-paste && $n -eq 1 ]]; then
      while [[ ! -s "$FAKE_STATE/sender-pid" ]]; do /usr/bin/sleep 0.01; done
      kill -TERM "$(<"$FAKE_STATE/sender-pid")"
      exit 143
    fi
    if [[ "$mode" == command-claude-prechange && $n -eq 3 || "$mode" == command-claude-finalrace && -s "$FAKE_STATE/cleared" && $n -eq $(($(<"$FAKE_STATE/clear-capture") + 2)) ]]; then
      printf 'new human text' > "$FAKE_STATE/composer"
    fi
    if [[ "$mode" == slow-first-own && $n -eq 4 ]]; then /usr/bin/sleep 1.2; fi
    if [[ "$mode" == slow-third-empty && $n -eq 3 ]]; then /usr/bin/sleep 1.2; fi
    if [[ "$mode" == slow-second-empty && $n -eq 2 ]]; then /usr/bin/sleep 1.2; fi
    if [[ "$mode" == changing-draft || "$mode" == second-change && $n -eq 2 ]]; then
      printf 'changing draft %s' "$n" > "$FAKE_STATE/composer"
    fi
    if [[ "$mode" == human-before-paste && $n -ge 3 ]]; then
      printf 'human text before paste\n' > "$FAKE_STATE/composer"
    fi
    if [[ "$mode" == render-unknown-human && -s "$FAKE_STATE/pasted" && $n -ge 5 ]]; then
      printf 'human mixed input\n' > "$FAKE_STATE/composer"
    fi
    if [[ "$mode" == render-late-unknown && -s "$FAKE_STATE/pasted" && $n -eq 4 ]]; then /usr/bin/sleep 1.2; fi
    if [[ "$mode" == human-during-delay && -s "$FAKE_STATE/pasted" && ! -s "$FAKE_STATE/mutated" ]]; then
      printf ' human began typing' >> "$FAKE_STATE/composer"
      printf 'mutated' > "$FAKE_STATE/mutated"
    fi
    if [[ "$mode" == busyqueue-draft || "$mode" == busycontext-draft ]]; then
      python3 - "$mode" "$FAKE_STATE/composer" "$FIXTURES" > "$FAKE_STATE/last-screen" <<'PYQUEUE'
from pathlib import Path
import sys
mode, draft, fixtures = sys.argv[1:]
name, old = ('codex-generating-queue.ansi', 'Reply with exactly P141-QUEUED-TEST') if mode == 'busyqueue-draft' else ('codex-context-queue.ansi', 'S short control: reply S-BUSY-1 after the current task.')
print(Path(fixtures, name).read_text().replace(old, Path(draft).read_text()), end='')
PYQUEUE
    elif [[ "$mode" == command-*-unknown* && -s "$FAKE_STATE/cleared" && ( "$mode" == *-timeout || $n -le $(($(<"$FAKE_STATE/clear-capture") + 2)) ) ]]; then
      printf 'Starting Claude Code\n' > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == forkcompact ]]; then
      if [[ -s "$FAKE_STATE/pasted" ]]; then
        cat "$FIXTURES/codex-fork-compact.ansi" > "$FAKE_STATE/last-screen"
      else
        cat "$FIXTURES/codex-fork-empty.ansi" > "$FAKE_STATE/last-screen"
      fi
    elif [[ "$mode" == home-*-unknown* && -s "$FAKE_STATE/end-moved" && ( "$mode" == *-timeout || $n -le $(($(<"$FAKE_STATE/end-capture") + 2)) ) ]]; then
      printf 'Starting Claude Code\n' > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-trailing-lf && ! -s "$FAKE_STATE/pasted" ]]; then
      cat "$FIXTURES/claude-stable-draft.ansi" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-trailing-lf && -s "$FAKE_STATE/pasted" ]]; then
      printf '────────────────────────────────────────\n❯ stale TICK\n  alpha\n  beta\n  \n────────────────────────────────────────\n' > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-marker-preenter && ! -s "$FAKE_STATE/pasted" ]]; then
      cat "$FIXTURES/claude-stable-draft.ansi" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-marker-preenter && -s "$FAKE_STATE/pasted" ]]; then
      n=$(($(<"$FAKE_STATE/marker-screen-count") + 1)); printf '%s' "$n" > "$FAKE_STATE/marker-screen-count"
      ordinal=3; ((n >= 3)) && ordinal=4
      printf '────────────────────────────────────────\n❯ stale TICK[Pasted text #%s +2 lines]\n────────────────────────────────────────\n' "$ordinal" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude && ! -s "$FAKE_STATE/pasted" ]]; then
      cat "$FIXTURES/claude-stable-draft.ansi" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-marker && ! -s "$FAKE_STATE/pasted" ]]; then
      cat "$FIXTURES/claude-stable-draft.ansi" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-marker && -s "$FAKE_STATE/pasted" ]]; then
      ordinal=3; [[ -s "$FAKE_STATE/marker-seen" ]] && ordinal=4
      printf seen > "$FAKE_STATE/marker-seen"
      printf '────────────────────────────────────────\n❯ stale TICK[Pasted text #%s +2 lines]\n────────────────────────────────────────\n' "$ordinal" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-marker-harness && ! -s "$FAKE_STATE/pasted" ]]; then
      cat "$FIXTURES/claude-stable-draft.ansi" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-claude-marker-harness && -s "$FAKE_STATE/pasted" ]]; then
      if [[ ! -s "$FAKE_STATE/marker-seen" ]]; then
        printf seen > "$FAKE_STATE/marker-seen"
        printf '────────────────────────────────────────\n❯ stale TICK[Pasted text #3 +2 lines]\n────────────────────────────────────────\n' > "$FAKE_STATE/last-screen"
      else
        printf '› stale TICK[Pasted text #3 +2 lines]\n\n  Any model · Context 50%% left\n' > "$FAKE_STATE/last-screen"
      fi
    elif [[ "$mode" == stable-codex-marker-claude && ! -s "$FAKE_STATE/pasted" ]]; then
      cat "$FIXTURES/codex-stable-draft.ansi" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-codex-marker-claude && -s "$FAKE_STATE/pasted" ]]; then
      printf '────────────────────────────────────────\n❯ stale TICK[Pasted text #3 +2 lines]\n────────────────────────────────────────\n' > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == stable-codex && ! -s "$FAKE_STATE/pasted" ]]; then
      cat "$FIXTURES/codex-stable-draft.ansi" > "$FAKE_STATE/last-screen"
    elif [[ "$mode" == busycontext ]]; then
      if [[ -s "$FAKE_STATE/pasted" ]]; then
        cat "$FIXTURE_CURRENT" > "$FAKE_STATE/last-screen"
      else
        sed 's/S short control: reply S-BUSY-1 after the current task.//' "$FIXTURE_CURRENT" > "$FAKE_STATE/last-screen"
      fi
    elif [[ "$mode" == busyqueue ]]; then
      if [[ -s "$FAKE_STATE/pasted" ]]; then
        cat "$FAKE_STATE/busyqueue" > "$FAKE_STATE/last-screen"
      else
        sed 's/Reply with exactly P141-QUEUED-TEST//' "$FAKE_STATE/busyqueue" > "$FAKE_STATE/last-screen"
      fi
    elif [[ -s "$FAKE_STATE/pasted" && "$mode" == render-stale-empty && $n -eq 4 ]]; then
      cat "$FAKE_STATE/empty" > "$FAKE_STATE/last-screen"
    elif [[ -s "$FAKE_STATE/pasted" && "$mode" == persistent-empty-after-paste ]]; then
      cat "$FAKE_STATE/empty" > "$FAKE_STATE/last-screen"
    elif [[ -s "$FAKE_STATE/pasted" && ( "$mode" == unknown-after-paste || "$mode" == unknown-after-own && $n -ge 5 || ( "$mode" == render-unknown || "$mode" == render-late-unknown || "$mode" == render-unknown-human ) && $n -eq 4 ) ]]; then
      printf 'Starting Claude Code\n' > "$FAKE_STATE/last-screen"
    else
    case "$mode" in
      modal) cat "$FAKE_STATE/modal" ;;
      unknown) printf 'Starting Claude Code\n';;
      *)
        if [[ -s "$FAKE_STATE/composer" ]]; then
          python3 - "$FAKE_STATE/composer" <<'PY'
from pathlib import Path
import sys
rows = Path(sys.argv[1]).read_text().splitlines()
import os
mode = Path(os.environ['FAKE_STATE'], 'mode').read_text().strip()
codex = mode in {'stable-codex', 'stable-codex-marker-claude'} or mode.startswith(('home-codex', 'command-codex'))
if not codex: print('─' * 40)
else: print('')
print(('› ' if codex else '❯\u00a0') + (rows[0] if rows else ''))
for row in rows[1:]: print('  ' + row)
if mode.endswith('-command-blank'): print('')
if codex: print('')
print('  Any model · Context 50% left' if codex else '─' * 40)
PY
        elif [[ "$mode" == command-claude-harness && -s "$FAKE_STATE/cleared" || "$mode" == command-codex* || "$mode" == home-codex* && -s "$FAKE_STATE/cleared" ]]; then
          printf '\n› \n\n  Any model · Context 50%% left\n'
        elif [[ "$mode" == human || "$mode" == slash ]]; then
          if [[ "$mode" == slash ]]; then printf '────────────────────────────────────────\n❯ /compact\n────────────────────────────────────────\n'
          else printf '────────────────────────────────────────\n❯ human draft\n────────────────────────────────────────\n'; fi
        elif [[ "$mode" == streaming ]]; then
          printf 'Assistant is thinking…\n────────────────────────────────────────\n❯ \n────────────────────────────────────────\n'
        else cat "$FAKE_STATE/empty"; fi
        ;;
    esac > "$FAKE_STATE/last-screen"
    fi
    cat "$FAKE_STATE/last-screen"
    ;;
  load-buffer)
    while (($#)); do if [[ "$1" == -b ]]; then b=$2; shift 2; else f=$1; shift; fi; done
    cp "$f" "$FAKE_BUFFER_DIR/$b" ;;
  paste-buffer)
    b=''; while (($#)); do if [[ "$1" == -b ]]; then b=$2; shift 2; else shift; fi; done
    printf 'paste-start\n' >> "$FAKE_LOG"
    python3 -c 'import time; print(time.monotonic_ns())' >> "$FAKE_STATE/times"
    if [[ "${FAKE_FAIL_PASTE:-0}" == 1 ]]; then exit 1; fi
    cat "$FAKE_BUFFER_DIR/$b" >> "$FAKE_STATE/composer"
    printf 'pasted\n' > "$FAKE_STATE/pasted"
    if [[ "${FAKE_INTERRUPT_AFTER_PASTE:-0}" == 1 ]]; then
      kill -TERM "$PPID"
      exit 143
    fi
    sleep 0.05
    printf 'paste-end\n' >> "$FAKE_LOG"
    rm -f "$FAKE_BUFFER_DIR/$b" ;;
  delete-buffer) printf 'delete-buffer\n' >> "$FAKE_LOG" ;;
  send-keys)
    if [[ "${!#}" == C-u ]]; then
      printf 'clear\n' >> "$FAKE_LOG"
      cp "$FAKE_STATE/captures" "$FAKE_STATE/clear-capture"
      printf attempted > "$FAKE_STATE/cleared"
      if [[ "$(<"$FAKE_STATE/mode")" == *-clearfail ]]; then exit 1; fi
      if [[ "$(<"$FAKE_STATE/mode")" == *-clearsignal ]]; then kill -TERM "$PPID"; exit 143; fi
      case "$(<"$FAKE_STATE/mode")" in
        *-noclear) ;;
        *-changed) printf 'new human text' > "$FAKE_STATE/composer" ;;
        *) : > "$FAKE_STATE/composer" ;;
      esac
      exit 0
    fi
    if [[ "${!#}" == End ]]; then
      printf 'end\n' >> "$FAKE_LOG"
      cp "$FAKE_STATE/captures" "$FAKE_STATE/end-capture"
      if [[ "$(<"$FAKE_STATE/mode")" != *-noend ]]; then printf moved > "$FAKE_STATE/end-moved"; fi
      exit 0
    fi
    if [[ "$*" == *' -l '* ]]; then
      printf '%s' "${!#}" >> "$FAKE_STATE/composer"
      printf 'pasted\n' > "$FAKE_STATE/pasted"
      exit 0
    fi
    [[ "${!#}" == Enter ]]
    printf 'enter\n' >> "$FAKE_LOG"
    python3 -c 'import time; print(time.monotonic_ns())' >> "$FAKE_STATE/times"
    cp "$FAKE_STATE/composer" "$FAKE_STATE/submitted"
    : > "$FAKE_STATE/composer"
    ;;
  *) echo "unexpected tmux command: $cmd" >&2; exit 64 ;;
esac
STUB
cat > "$TEST_DIR/bin/sleep" <<'STUB'
#!/bin/bash
if [[ "${FAKE_VIRTUAL_CLOCK:-0}" == 1 ]]; then
  "$TEST_REAL_PYTHON3" -c 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_text(str(int(p.read_text())+round(float(sys.argv[2])*1e9)))' "$FAKE_STATE/clock" "$1"
  exit
fi
printf '%s\n' "$1" >> "$FAKE_STATE/sleeps"
if [[ "${FAKE_REAL_SLEEP:-0}" == 1 ]]; then exec /usr/bin/sleep "$1"; fi
exec /usr/bin/sleep 0.01
STUB
cat > "$TEST_DIR/bin/flock" <<'STUB'
#!/bin/bash
if [[ "${FAKE_FAIL_FLOCK:-0}" == 1 ]]; then exit 1; fi
exec /usr/bin/flock "$@"
STUB
chmod +x "$TEST_DIR/bin/python3" "$TEST_DIR/bin/tmux" "$TEST_DIR/bin/sleep" "$TEST_DIR/bin/flock"

reset_case() {
  printf 0 > "$FAKE_STATE/clock"
  : > "$FAKE_LOG"
  : > "$FAKE_STATE/composer"
  : > "$FAKE_STATE/mutated"
  : > "$FAKE_STATE/end-moved"
  printf 0 > "$FAKE_STATE/end-capture"
  printf 0 > "$FAKE_STATE/clear-capture"
  : > "$FAKE_STATE/cleared"
  : > "$FAKE_STATE/pasted"
  : > "$FAKE_STATE/captures"
  : > "$FAKE_STATE/sleeps"
  : > "$FAKE_STATE/times"
  : > "$FAKE_STATE/tmux-calls"
  : > "$FAKE_STATE/tmux-trace"
  : > "$FAKE_STATE/parser-trace"
  : > "$FAKE_STATE/marker-seen"
  printf 0 > "$FAKE_STATE/marker-screen-count"
  : > "$FAKE_STATE/sender-pid"
  printf '%s\n' "${1:-empty}" > "$FAKE_STATE/mode"
  if [[ "${1:-}" == busy*-draft || "${1:-}" == home-* || "${1:-}" == stable-* || "${1:-}" == changing-draft || "${1:-}" == second-change ]]; then printf 'stale TICK' > "$FAKE_STATE/composer"; fi
  cp "$FIXTURES/claude-blank.ansi" "$FAKE_STATE/empty"
  cp "$FIXTURES/modal.txt" "$FAKE_STATE/modal"
  cp "$FIXTURES/codex-generating-queue.ansi" "$FAKE_STATE/busyqueue"
}
run_sender() {
  if [[ "$(<"$FAKE_STATE/mode")" == interrupt-before-paste ]]; then
    bash "${SENDER_SCRIPT:-$SCRIPT_DIR/claude-send.sh}" "$@" &
    local sender_pid=$!
    printf '%s' "$sender_pid" > "$FAKE_STATE/sender-pid"
    wait "$sender_pid"
  else
    bash "${SENDER_SCRIPT:-$SCRIPT_DIR/claude-send.sh}" "$@"
  fi
}
run_sender_without_xdg_runtime() { env -u XDG_RUNTIME_DIR bash "${SENDER_SCRIPT:-$SCRIPT_DIR/claude-send.sh}" "$@"; }
assert_pending() {
  local status=$1 output=$2 path
  grep -q "status=$status" "$output"
  path=$(sed -n 's/.*pending_file=//p' "$output" | tail -n1)
  [[ -n "$path" && -f "$path" && $(stat -c %a "$(dirname "$path")") == 700 && $(stat -c %a "$path") == 600 ]]
  printf '%s' "$path"
}

# The live Claude frame has a suggestion in an otherwise empty composer.
prompt_file="$TEST_DIR/payload"
printf 'alpha\nbeta' > "$prompt_file"

# Command-shaped stable drafts are cancelled, never executed with the new message.
{
  failures=0
  for mode in command-claude command-codex command-claude-unknown command-codex-unknown home-claude home-codex busyqueue-draft busycontext-draft; do
    reset_case "$mode"
    printf '/compact old context' > "$FAKE_STATE/composer"
    expected_keys=$'clear\npaste-start\npaste-end\nenter'
    [[ "$mode" != home-* ]] || expected_keys=$'end\n'"$expected_keys"
    if out=$(run_sender %7 --submit-delay 0 --max-wait 3 'fresh control' 2>"$TEST_DIR/command.err") &&
       [[ "$(<"$FAKE_LOG")" == "$expected_keys" && "$(<"$FAKE_STATE/submitted")" == 'fresh control' && "$out" == *'cleared_command_draft_length=20'* ]]; then
      echo "PASS: $mode verified command clear before outgoing"
    else echo "FAIL: $mode command was not cleared safely"; failures=$((failures + 1)); fi
  done
  reset_case command-claude
  printf '/compact old context' > "$FAKE_STATE/composer"
  if out=$(run_sender %7 --typed-command --submit-delay 0 --max-wait 3 '/status' 2>"$TEST_DIR/command.err") &&
     [[ "$(<"$FAKE_LOG")" == $'clear\nenter' && "$(<"$FAKE_STATE/submitted")" == '/status' ]]; then
    echo 'PASS: typed outgoing follows verified command clear'
  else echo 'FAIL: typed outgoing command clear'; failures=$((failures + 1)); fi
  for mode in command-claude-noclear command-codex-changed command-claude-unknown-timeout command-claude-clearfail command-claude-clearsignal command-claude-harness; do
    reset_case "$mode"
    printf '/compact old context' > "$FAKE_STATE/composer"
    if run_sender %7 --submit-delay 0 --max-wait 1 'fresh control' >"$TEST_DIR/command.out" 2>"$TEST_DIR/command.err"; then rc=0; else rc=$?; fi
    expected_rc=3
    [[ "$mode" != *-clearsignal ]] || expected_rc=143
    if [[ $rc -eq $expected_rc && "$(<"$FAKE_LOG")" == clear ]] && grep -q 'status=ambiguous.*clear_attempted=true' "$TEST_DIR/command.err" && ! grep -q cleared_command_draft_length "$TEST_DIR/command.err"; then
      echo "PASS: $mode uncertain clear stops before outgoing"
    else echo "FAIL: $mode uncertain clear safety"; failures=$((failures + 1)); fi
  done
  for mode in command-claude command-codex; do
    reset_case "$mode"
    printf '!echo old context' > "$FAKE_STATE/composer"
    if out=$(run_sender %7 --submit-delay 0 --max-wait 3 'fresh control' 2>"$TEST_DIR/command.err") && [[ "$(<"$FAKE_STATE/submitted")" == 'fresh control' && "$out" == *'cleared_command_draft_length=17'* ]]; then
      echo "PASS: $mode ordinary shortcut command clear"
    else echo 'FAIL: shortcut command clear'; failures=$((failures + 1)); fi
  done
  for mode in command-claude-prechange command-claude-finalrace; do
    reset_case "$mode"
    printf '/compact old context' > "$FAKE_STATE/composer"
    if run_sender %7 --submit-delay 0 --max-wait 3 'fresh control' >"$TEST_DIR/command.out" 2>"$TEST_DIR/command.err"; then rc=0; else rc=$?; fi
    if [[ "$mode" == *-prechange && $rc -eq 2 && ! -s "$FAKE_LOG" || "$mode" == *-finalrace && $rc -eq 3 && "$(<"$FAKE_LOG")" == clear ]] && [[ "$(<"$FAKE_STATE/composer")" == 'new human text' ]]; then
      echo "PASS: $mode race prevents outgoing"
    else echo 'FAIL: command clear race'; failures=$((failures + 1)); fi
  done
  for draft in ' /compact' '/tmp/path' '/compact;' '/compact fresh control' '/compact [Pasted text #1 +2 lines]' '!' $'/compact\ncontext' "/compact $(printf '%0200d' 0)"; do
    reset_case command-claude
    printf '%s' "$draft" > "$FAKE_STATE/composer"
    if run_sender %7 --submit-delay 0 --max-wait 1 'fresh control' >"$TEST_DIR/command.out" 2>"$TEST_DIR/command.err"; then rc=0; else rc=$?; fi
    if [[ $rc -eq 2 && ! -s "$FAKE_LOG" ]]; then echo 'PASS: invalid command-like or replay draft preserved'
    else echo 'FAIL: invalid command-like or replay draft modified'; failures=$((failures + 1)); fi
  done
  for mode in home-claude-command-blank home-codex-command-blank; do
    reset_case "$mode"
    printf '/compact' > "$FAKE_STATE/composer"
    if run_sender %7 --submit-delay 0 --max-wait 1 'fresh control' >"$TEST_DIR/command.out" 2>"$TEST_DIR/command.err"; then rc=0; else rc=$?; fi
    if [[ $rc -eq 2 && ! -s "$FAKE_LOG" ]]; then echo "PASS: $mode raw blank continuation protected"
    else echo 'FAIL: raw command continuation cleared'; failures=$((failures + 1)); fi
  done
  ((failures == 0))
  if [[ "${COMMAND_INPUT_ONLY:-0}" == 1 ]]; then exit; fi
}

# Busy queue frames support only single-line exact input: do not append newline to drafts.
{
  failures=0
  for mode in busyqueue-draft busycontext-draft; do
    reset_case "$mode"
    if run_sender %7 --submit-delay 0 --max-wait 1 'fresh control' >"$TEST_DIR/queue-draft.out" 2>"$TEST_DIR/queue-draft.err"; then rc=0
    else rc=$?; fi
    if [[ $rc -eq 2 && ! -s "$FAKE_LOG" && "$(<"$FAKE_STATE/composer")" == 'stale TICK' ]]; then
      echo "PASS: $mode unsupported append deferred without changes"
    else
      echo "FAIL: $mode unsupported append modified the draft"; failures=$((failures + 1))
    fi
  done
  ((failures == 0))
  if [[ "${QUEUE_DRAFT_ONLY:-0}" == 1 ]]; then exit; fi
}

# Stable single-line drafts at Home navigate once, preserving text before append.
{
  failures=0
  for mode in home-claude home-codex; do
    reset_case "$mode"
    if out=$(run_sender %7 --submit-delay 0 --max-wait 3 --prompt-file "$prompt_file" 2>"$TEST_DIR/home.err") &&
       [[ "$(<"$FAKE_STATE/submitted")" == $'stale TICK\nalpha\nbeta' ]] &&
       [[ "$(<"$FAKE_LOG")" == $'end\npaste-start\npaste-end\nenter' ]]; then
      echo "PASS: $mode End then one append and Enter"
    else
      echo "FAIL: $mode stable Home draft stranded or changed"; failures=$((failures + 1))
    fi
    reset_case "$mode-noend"
    if run_sender %7 --submit-delay 0 --max-wait 3 --prompt-file "$prompt_file" >"$TEST_DIR/home-noend.out" 2>"$TEST_DIR/home-noend.err"; then
      echo "FAIL: $mode ineffective End authorized append"; failures=$((failures + 1))
    elif [[ "$(<"$FAKE_LOG")" == end ]] && grep -q 'reason=cursor-navigation-unverified' "$TEST_DIR/home-noend.err"; then
      echo "PASS: $mode ineffective End defers without append"
    else
      echo "FAIL: $mode ineffective End was not verified"; failures=$((failures + 1))
    fi
  done
  for mode in home-claude-delay home-codex-delay home-claude-unknown home-codex-unknown; do
    reset_case "$mode"
    if out=$(run_sender %7 --submit-delay 0 --max-wait 3 --prompt-file "$prompt_file" 2>"$TEST_DIR/home-delay.err") &&
       [[ "$(<"$FAKE_STATE/submitted")" == $'stale TICK\nalpha\nbeta' ]] &&
       [[ "$(<"$FAKE_LOG")" == $'end\npaste-start\npaste-end\nenter' ]]; then
      echo "PASS: $mode unchanged repaint waited before append"
    else
      echo "FAIL: $mode unchanged repaint stranded"; failures=$((failures + 1))
    fi
  done
  reset_case home-claude-unknown-timeout
  if run_sender %7 --submit-delay 0 --max-wait 1 --prompt-file "$prompt_file" >"$TEST_DIR/home-timeout.out" 2>"$TEST_DIR/home-timeout.err"; then
    echo 'FAIL: persistent navigation repaint authorized append'; failures=$((failures + 1))
  elif [[ "$(<"$FAKE_LOG")" == end ]] && grep -q 'status=deferred' "$TEST_DIR/home-timeout.err"; then
    echo 'PASS: persistent navigation repaint defers without outgoing input'
  else
    echo 'FAIL: persistent navigation repaint changed outgoing input'; failures=$((failures + 1))
  fi
  ((failures == 0))
  if [[ "${HOME_INPUT_ONLY:-0}" == 1 ]]; then exit; fi
}

# Ruling regression group can run alone against the unmodified sender.
{
  failures=0
  for mode in stable-claude stable-codex; do
    reset_case "$mode"
    if out=$(run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/$mode.err") &&
       [[ "$(<"$FAKE_STATE/submitted")" == $'stale TICK\nalpha\nbeta' ]] &&
       [[ "$out" == 'status=sent receipt=unverified stale_draft_length=10' ]]; then
      echo "PASS: $mode co-submitted"
    else
      echo "FAIL: $mode co-submitted"
      failures=$((failures + 1))
    fi
  done
  reset_case stable-claude-trailing-lf
  trailing_prompt="$TEST_DIR/trailing-prompt"
  trailing_expected="$TEST_DIR/trailing-expected"
  printf 'alpha\nbeta\n' > "$trailing_prompt"
  printf 'stale TICK\nalpha\nbeta\n' > "$trailing_expected"
  if out=$(run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$trailing_prompt" 2>"$TEST_DIR/trailing-lf.err") &&
     cmp -s "$trailing_expected" "$FAKE_STATE/submitted" &&
     [[ "$out" == 'status=sent receipt=unverified stale_draft_length=10' &&
        "$(grep -c '^paste-start$' "$FAKE_LOG")" -eq 1 &&
        "$(grep -c '^enter$' "$FAKE_LOG")" -eq 1 ]]; then
    echo 'PASS: legacy Claude preserves exact trailing-LF input through one Enter'
  else
    echo 'FAIL: legacy Claude trailing-LF input did not preserve exact bytes'; failures=$((failures + 1))
  fi
  reset_case stable-claude-marker
  if run_sender %7 --submit-delay 0 --render-wait 3 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/marker-change.out" 2>"$TEST_DIR/marker-change.err"; then
    echo 'FAIL: changed Claude paste marker was re-owned'; failures=$((failures + 1))
  elif grep -q 'reason=input-changed-after-paste' "$TEST_DIR/marker-change.err" &&
       [[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]] &&
       [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]; then
    echo 'PASS: changed Claude paste marker stops before Enter'
  else
    echo 'FAIL: changed Claude paste marker did not fail closed'; failures=$((failures + 1))
  fi
  reset_case stable-claude-marker-preenter
  if run_sender %7 --submit-delay 0 --render-wait 3 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/marker-preenter.out" 2>"$TEST_DIR/marker-preenter.err"; then
    echo 'FAIL: marker change at immediate pre-submit was re-owned'; failures=$((failures + 1))
  elif grep -q 'reason=input-changed-before-submit' "$TEST_DIR/marker-preenter.err" &&
       [[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]] &&
       [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]; then
    echo 'PASS: changed Claude marker at immediate pre-submit defers'
  else
    echo 'FAIL: immediate pre-submit marker change did not fail closed'; failures=$((failures + 1))
  fi
  reset_case stable-claude-marker-harness
  if run_sender %7 --submit-delay 0 --render-wait 3 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/marker-harness.out" 2>"$TEST_DIR/marker-harness.err"; then
    echo 'FAIL: changed Claude harness was re-owned'; failures=$((failures + 1))
  elif grep -q 'status=ambiguous' "$TEST_DIR/marker-harness.err" &&
       [[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]] &&
       [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]; then
    echo 'PASS: changed Claude harness stops before Enter'
  else
    echo 'FAIL: changed Claude harness did not fail closed'; failures=$((failures + 1))
  fi
  reset_case stable-codex-marker-claude
  if run_sender %7 --submit-delay 0 --render-wait 3 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/reverse-harness.out" 2>"$TEST_DIR/reverse-harness.err"; then
    echo 'FAIL: Codex draft was re-owned as Claude combined input'; failures=$((failures + 1))
  elif grep -q 'status=ambiguous' "$TEST_DIR/reverse-harness.err" &&
       [[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]] &&
       [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]; then
    echo 'PASS: original Codex draft cannot be re-owned by Claude'
  else
    echo 'FAIL: Codex-to-Claude harness switch did not fail closed'; failures=$((failures + 1))
  fi
  for mode in changing-draft modal; do
    reset_case "$mode"
    if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/$mode.out" 2>"$TEST_DIR/$mode.err"; then
      echo "FAIL: $mode submitted"; failures=$((failures + 1))
    elif [[ ! -s "$FAKE_LOG" ]]; then
      echo "PASS: $mode deferred without input"
    else
      echo "FAIL: $mode attempted input"; failures=$((failures + 1))
    fi
  done
  ((failures == 0))
  if [[ "${STABLE_INPUT_ONLY:-0}" == 1 ]]; then exit; fi
}

# A change on exactly sample2 resets a full window; the unchanged twin succeeds.
reset_case stable-claude
out=$(FAKE_VIRTUAL_CLOCK=1 run_sender %7 --submit-delay 1 --max-wait 2 --poll-interval 1 --prompt-file "$prompt_file")
[[ "$out" == 'status=sent receipt=unverified stale_draft_length=10' ]]
reset_case second-change
if FAKE_VIRTUAL_CLOCK=1 run_sender %7 --submit-delay 1 --max-wait 2 --poll-interval 1 --prompt-file "$prompt_file" >"$TEST_DIR/second-change.out" 2>"$TEST_DIR/second-change.err"; then
  echo 'FAIL: sample2 change reused initial settle window' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
[[ ! -s "$FAKE_LOG" ]]
echo 'PASS: identical timing unchanged twin submits and sample2 change defers'

if [[ "${TIMING_SKIP_PROSE:-0}" != 1 ]]; then
# Ordinary slash-prefixed prose is a bracketed paste, not a typed command.
reset_case empty
out=$(run_sender %7 --submit-delay 0 --max-wait 3 '/tmp is full again')
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 1 ]] || { echo 'FAIL: slash-prefixed prose was auto-typed' >&2; exit 1; }
[[ $(grep -c '^send-keys$' "$FAKE_STATE/tmux-calls") -eq 1 ]]
echo 'PASS: slash-prefixed prose remains a paste'

fi

# Default8 settle samples at8 rather than backoff overshooting to15.5.
reset_case empty
if out=$(FAKE_VIRTUAL_CLOCK=1 run_sender %7 --max-wait 12 --prompt-file "$prompt_file"); then
  [[ "$out" == 'status=sent receipt=unverified' ]]
  python3 - "$FAKE_STATE/times" <<'PYTIME'
from pathlib import Path
import sys
values = [int(n) for n in Path(sys.argv[1]).read_text().splitlines()]
assert 8_000_000_000 <= values[0] <= 8_010_000_000, values
PYTIME
else
  echo 'FAIL: default8 window overshot12-second readiness budget' >&2; exit 1
fi
echo 'PASS: default8 settles before12-second readiness deadline'
if [[ "${TIMING_INPUT_ONLY:-0}" == 1 ]]; then exit; fi

# Identifiable retained combined or mixed payload must not be appended again.
{
  failures=0
  for mode in stable-claude stable-codex; do
    for residue in combined mixed; do
      reset_case "$mode"
      if [[ "$residue" == combined ]]; then printf 'stale TICK\nalpha\nbeta' > "$FAKE_STATE/composer"
      else printf 'alpha\nbeta human' > "$FAKE_STATE/composer"; fi
      printf 'pasted\n' > "$FAKE_STATE/pasted"
      if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/replay.out" 2>"$TEST_DIR/replay.err"; then
        echo "FAIL: $mode $residue outgoing payload replayed"; failures=$((failures + 1))
      elif [[ ! -s "$FAKE_LOG" ]]; then
        echo "PASS: $mode $residue deferred without repeated input"
      else
        echo "FAIL: $mode $residue attempted repeated input"; failures=$((failures + 1))
      fi
    done
  done
  ((failures == 0))
  if [[ "${REPLAY_INPUT_ONLY:-0}" == 1 ]]; then exit; fi
}

# Explicit command mode validates like the public sender and protects drafts.
python3 - "$TEST_DIR" <<'PYCOMMAND'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for index, value in enumerate(('hello', '/x\n/exit', '/model x;', '/model x\u3000', '/model ' + 'x' * 194)):
    (root / ('invalid-command-' + str(index))).write_text(value, encoding='utf-8')
PYCOMMAND
for index in 0 1 2 3 4; do
  reset_case empty
  if run_sender %7 --typed-command --submit-delay 0 --max-wait 1 --prompt-file "$TEST_DIR/invalid-command-$index" >"$TEST_DIR/typed-invalid.out" 2>"$TEST_DIR/typed-invalid.err"; then
    echo 'FAIL: invalid typed command accepted' >&2; exit 1
  fi
  [[ ! -s "$FAKE_STATE/tmux-calls" ]]
done
reset_case empty
out=$(run_sender %7 --typed-command --submit-delay 0 --max-wait 3 '/model example')
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^send-keys$' "$FAKE_STATE/tmux-calls") -eq 2 ]]
reset_case stable-claude
if run_sender %7 --typed-command --submit-delay 0 --max-wait 1 '/compact' >"$TEST_DIR/typed-draft.out" 2>"$TEST_DIR/typed-draft.err"; then
  echo 'FAIL: typed command combined with stable draft' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
[[ ! -s "$FAKE_LOG" ]]

# Once a draft append is prepared, failures report only its length and keep outgoing bytes.
reset_case stable-claude
if FAKE_FAIL_PASTE=1 run_sender %7 --submit-delay 0 --max-wait 3 --prompt-file "$prompt_file" >"$TEST_DIR/stale-failure.out" 2>"$TEST_DIR/stale-failure.err"; then
  echo 'FAIL: stale append paste failure ignored' >&2; exit 1
else rc=$?; [[ $rc -eq 3 ]]; fi
grep -q 'stale_draft_length=10' "$TEST_DIR/stale-failure.err"
if grep -q 'stale TICK' "$TEST_DIR/stale-failure.err"; then echo 'FAIL: failure metadata leaked stale text' >&2; exit 1; fi
pending=$(assert_pending ambiguous "$TEST_DIR/stale-failure.err")
cmp "$pending" "$prompt_file"
rm -rf "$(dirname "$pending")"

# Invalid byte sequences, control characters, blank content, and trailing
# whitespace are rejected before any tmux operation, so they cannot be pasted.
python3 - "$TEST_DIR" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
payloads = {
    'malformed-utf8': b'valid then \xff',
    'carriage-return': b'left\rright',
    'delete': b'left\x7fright',
    'c1-control': b'left\xc2\x85right',
    'blank': b' \n\t\n',
    'trailing-space': b'valid text \n',
}
for name, content in payloads.items():
    (root / name).write_bytes(content)
PY
for invalid in malformed-utf8 carriage-return delete c1-control blank trailing-space; do
  reset_case empty
  if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$TEST_DIR/$invalid" 2>"$TEST_DIR/$invalid.err"; then
    echo "FAIL: invalid $invalid payload was accepted" >&2; exit 1
  fi
  [[ ! -s "$FAKE_STATE/tmux-calls" ]]
  [[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
done

# Numeric inputs too large for the documented ranges are rejected before the
# sender attempts to resolve or mutate a pane.
for option in --submit-delay --render-wait --max-wait --poll-interval; do
  reset_case empty
  if run_sender %7 "$option" 999999999999999999999 --prompt-file "$prompt_file" 2>"$TEST_DIR/numeric.err"; then
    echo "FAIL: overflowing $option was accepted" >&2; exit 1
  fi
  [[ ! -s "$FAKE_STATE/tmux-calls" ]]
done
reset_case empty
if run_sender %7 --render-wait 0 --prompt-file "$prompt_file" 2>"$TEST_DIR/zero-render-wait.err"; then
  echo 'FAIL: zero render budget was accepted' >&2; exit 1
fi
[[ ! -s "$FAKE_STATE/tmux-calls" ]]
reset_case empty
if run_sender %7 --max-wait 0 --prompt-file "$prompt_file" 2>"$TEST_DIR/zero-max-wait.err"; then
  echo 'FAIL: zero max-wait was accepted' >&2; exit 1
fi
[[ ! -s "$FAKE_STATE/tmux-calls" ]]
python3 - "$SCRIPT_DIR/claude-send-screen.py" "$FIXTURES" "$prompt_file" <<'PY'
from pathlib import Path
import subprocess, sys
parser, fixtures, payload = sys.argv[1:]
def classify(frame, text, x='2', y='1'):
    Path(payload).write_text(text)
    return subprocess.check_output([sys.executable, parser, payload, x, y], input=(Path(fixtures) / frame).read_bytes()).decode().strip()
assert classify('claude-blank.ansi', 'outgoing') == 'empty'
assert classify('multiline.txt', 'first harmless line\nsecond harmless line', str(2 + len('second harmless line')), '2') == 'own'
assert classify('multiline.txt', 'different') == 'busy'
assert classify('modal.txt', 'outgoing') == 'unknown'
assert classify('claude-blank.ansi', 'different') == 'empty'
codex = ('\n' * 26 + '\x1b[1m›\x1b[0m \x1b[2mAsk Codex to do anything\x1b[0m\nWorking (12s • esc to interrupt)\n'
         '  GPT-6-Astra · Context 100% left · disposable\n'
         '  ← for agents · ? for shortcuts\n')
Path(payload).write_text('unused')
assert subprocess.check_output([sys.executable, parser, payload, '2', '26'], input=codex.encode()).decode().strip() == 'empty'
Path(payload).write_text('harmless draft')
codex_own = codex.replace('Ask Codex to do anything', 'harmless draft').replace('Working (12s • esc to interrupt)\n', '')
assert subprocess.check_output([sys.executable, parser, payload, '16', '26'], input=codex_own.encode()).decode().strip() == 'own'

def classify_fixture(name, text, x, y):
    Path(payload).write_text(text)
    return subprocess.check_output(
        [sys.executable, parser, payload, str(x), str(y)],
        input=(Path(fixtures) / name).read_bytes(),
    ).decode().strip()
assert classify_fixture('claude-blank.ansi', 'outgoing', 2, 1) == 'empty'
empty_suggestion = (Path(fixtures) / 'claude-suggestion-empty.ansi').read_bytes()
typed_home_suggestion = (Path(fixtures) / 'claude-suggestion-typed-home.ansi').read_bytes()
assert empty_suggestion == typed_home_suggestion
# Claude emits no ANSI style distinction for this exact cursor-home collision;
# both frames must be deferred as occupied after transport updates.
assert classify_fixture('claude-suggestion-empty.ansi', 'outgoing', 2, 1) == 'unknown'
assert classify_fixture('claude-suggestion-typed-home.ansi', 'outgoing', 2, 1) == 'unknown'
assert classify_fixture('claude-try-prefix-typed.ansi', 'outgoing', 16, 1) == 'unknown'
assert classify_fixture('codex-empty-dim.ansi', 'outgoing', 2, 26) == 'empty'
assert classify_fixture('codex-typed-home.ansi', 'outgoing', 2, 26) == 'busy'
for ordinary in ('Yes, proceed', 'No.', '1. Fix X\n2. Verify Y',
                 'Explain status\nEsc to cancel is ordinary text'):
    rendered = '› ' + ordinary.replace('\n', '\n  ') + '\n\n  Any model · Context 50% left\n'
    Path(payload).write_text(ordinary)
    cursor_y = ordinary.count('\n')
    cursor_x = 2 + len(ordinary.rsplit('\n', 1)[-1])
    assert subprocess.check_output(
        [sys.executable, parser, payload, str(cursor_x), str(cursor_y)],
        input=rendered.encode()).decode().strip() == 'own', repr(ordinary)
queue_payload = 'Reply with exactly P141-QUEUED-TEST'
queue_screen = (Path(fixtures) / 'codex-generating-queue.ansi').read_bytes()
queue_empty = queue_screen.replace(queue_payload.encode(), b'', 1)
Path(payload).write_text(queue_payload)
assert subprocess.check_output(
    [sys.executable, parser, payload, '2', '27'], input=queue_empty
).decode().strip() == 'empty'
assert subprocess.check_output(
    [sys.executable, parser, payload, '3', '27'], input=queue_empty
).decode().strip() == 'busy'
Path(payload).write_text(queue_payload + '\n')
assert subprocess.check_output(
    [sys.executable, parser, payload, '37', '27'], input=queue_screen
).decode().strip() == 'unknown'
Path(payload).write_text(queue_payload)
assert Path(fixtures, 'codex-generating-queue.cursor').read_text().strip() == '37:27'
assert subprocess.check_output(
    [sys.executable, parser, payload, '37', '27'], input=queue_screen
).decode().strip() == 'own'
unstyled_queue_hint = queue_screen.replace(b'\x1b[1mtab\x1b[0m', b'tab', 1)
assert subprocess.check_output(
    [sys.executable, parser, payload, '37', '27'], input=unstyled_queue_hint
).decode().strip() == 'unknown'
Path(payload).write_text('Reply with a different harmless payload')
assert subprocess.check_output(
    [sys.executable, parser, payload, '37', '27'], input=queue_screen
).decode().strip() == 'busy'
Path(payload).write_text(queue_payload)
assert subprocess.check_output(
    [sys.executable, parser, payload, '36', '27'], input=queue_screen
).decode().strip() == 'busy'
assert subprocess.check_output(
    [sys.executable, parser, payload, '37', '26'], input=queue_screen
).decode().strip() == 'busy'
extra_queue_row = queue_screen.replace(
    b'  \x1b[1mtab\x1b[0m to queue message',
    b'  unrelated app row\n  \x1b[1mtab\x1b[0m to queue message', 1,
)
assert subprocess.check_output(
    [sys.executable, parser, payload, '37', '27'], input=extra_queue_row
).decode().strip() == 'unknown'
# Measured current Codex separate model/context and queue-hint footer.
current = (Path(fixtures) / 'codex-context-queue.ansi').read_bytes()
text = 'S short control: reply S-BUSY-1 after the current task.'
x, y = map(int, Path(fixtures, 'codex-context-queue.cursor').read_text().split(':'))
def current_state(frame, wanted=text, px=x, py=y):
    Path(payload).write_text(wanted)
    return subprocess.check_output([sys.executable, parser, payload, str(px), str(py)], input=frame).decode().strip()
assert current_state(current) == 'own'
assert current_state(current, px=x-1) == 'busy'
assert current_state(current, py=y-1) == 'busy'
assert current_state(current, wanted=text+'\n') == 'unknown'
assert current_state(current.replace(text.encode(), b''), px=2) == 'empty'
assert current_state(current.replace(text.encode(), b'human draft'), px=13) == 'busy'
assert current_state(current.replace(text.encode(), (text+' HUMAN').encode()), px=x+6) == 'busy'
assert current_state(current.replace(b'\x1b[1mtab\x1b[0m', b'tab')) == 'unknown'
assert current_state(current+b'  unrelated modal\n') == 'unknown'
assert current_state(current.replace(b'  GPT-6-Sol', b'  arbitrary footer\n  GPT-6-Sol')) == 'unknown'
assert current_state(current.replace(text.encode(), b'Ask Codex to do anything'), px=2) == 'busy'
assert current_state(current.replace(text.encode(), b'\x1b[2mAsk Codex to do anything\x1b[0m'), px=2) == 'empty'
codex_dim = (Path(fixtures) / 'codex-empty-dim.ansi').read_text()
for color_sgr in ('\x1b[38;5;2m', '\x1b[38;2;2;2;2m', '\x1b[38:2:2:2:2m'):
    color_only = codex_dim.replace('\x1b[2mAsk Codex to do anything', color_sgr + 'Ask Codex to do anything')
    assert subprocess.check_output(
        [sys.executable, parser, payload, '2', '26'], input=color_only.encode()
    ).decode().strip() == 'busy'
PY
printf 'alpha\nbeta' > "$prompt_file"

# Measured fresh fork lacks a Context percentage. Require the exact model and
# shortcuts/warnings frame; dim suggestion style and exact cursor still matter.
python3 - "$SCRIPT_DIR/claude-send-screen.py" "$FIXTURES" <<'PYTEST'
import importlib.util, sys
from pathlib import Path
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("screen", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
screen = Path(sys.argv[2], "codex-fork-empty.ansi").read_text()
x, y = map(int, Path(sys.argv[2], "codex-fork-empty.cursor").read_text().split(':'))
assert m.state(screen, '/compact', x, y) == 'empty'
assert m.state(screen.replace('GPT-6-Sol', 'Unrecognized'), '/compact', x, y) == 'unknown'
assert m.state(screen.replace('shortcuts', 'unrecognized footer'), '/compact', x, y) == 'unknown'
assert m.state(screen.replace('warnings', 'unrecognized-warning'), '/compact', x, y) == 'unknown'
compact = Path(sys.argv[2], "codex-fork-compact.ansi").read_text()
cx, cy = map(int, Path(sys.argv[2], "codex-fork-compact.cursor").read_text().split(':'))
assert m.state(compact, '/compact', cx, cy) == 'own'
assert m.state(compact, '/compact', cx + 1, cy) == 'busy'
assert m.state(compact, 'different', cx, cy) == 'unknown'
assert m.state(compact.replace('summarize conversation', 'unrecognized command'), '/compact', cx, cy) == 'unknown'
# Text painted into the measured composer must own its exact bytes and cursor.
raw_lines = screen.splitlines()
index = next(i for i, line in enumerate(raw_lines) if i == y)
raw_lines[index] = '› /compact'
owned = '\n'.join(raw_lines)
assert m.state(owned, '/compact', 10, y) == 'own'
assert m.state(owned, '/compact', 11, y) == 'busy'
assert m.state(owned, 'different', 10, y) == 'busy'
PYTEST

# Legacy Claude co-submit recognition shares the public sender's exact-text /
# measured-marker predicate and freezes only a private fingerprint.
python3 - "$SCRIPT_DIR/claude-send-screen.py" "$SCRIPT_DIR/fixtures/claude-send/claude-combined-composer.ansi" <<'PYTEST'
import importlib.util, sys, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("screen", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
raw = Path(sys.argv[2]).read_text()
draft = 'Stable rehearsal draft.'
payload = 'First payload line\nSecond payload line'
expected = draft + '\n' + payload
lines = raw.splitlines()
prompt_y = next(i for i, row in enumerate(lines) if row.startswith('❯'))
cursor_x = 2 + m.cell_width('Second payload line')
assert m.state(raw, expected, cursor_x, prompt_y + 2, draft) == 'own'
assert m.state(raw, expected, cursor_x - 1, prompt_y + 2, draft) == 'busy'

with tempfile.TemporaryDirectory() as tmp:
    observed = Path(tmp, 'fingerprint')
    assert m.observe(raw, expected, cursor_x, prompt_y + 2, observed, draft) == 'own'
    first = observed.read_text()
    assert len(first) == 64 and payload not in first
    marker_text = draft + '[Pasted text #3 +2 lines]'
    marker_raw = ('─' * 20 + '\n❯ ' + marker_text + '\n' + '─' * 20 + '\n')
    marker_x = 2 + m.cell_width(marker_text)
    assert m.observe(marker_raw, expected, marker_x, 1, observed, draft) == 'own'
    marker_fingerprint = observed.read_text()
    assert marker_fingerprint != first
    assert m.state(marker_raw, expected, marker_x, 1, draft) == 'own'
    for wrong, x in ((draft + '[Pasted text #3 +1 lines]', 2 + m.cell_width(draft + '[Pasted text #3 +1 lines]')),
                     ('Changed prefix[Pasted text #3 +2 lines]', 2 + m.cell_width('Changed prefix[Pasted text #3 +2 lines]')),
                     (draft + ' x[Pasted text #3 +2 lines]', 2 + m.cell_width(draft + ' x[Pasted text #3 +2 lines]'))):
        bad = '─' * 20 + '\n❯ ' + wrong + '\n' + '─' * 20 + '\n'
        assert m.observe(bad, expected, x, 1, observed, draft) != 'own'
        assert observed.read_text() == ''
    assert not m.claude_combined_input_evidence(
        'text', expected, 'codex', draft, payload, True)
    assert not m.claude_combined_input_evidence(
        'unknown', expected, 'claude', draft, payload, True)
    assert not m.claude_combined_input_evidence(
        'text', expected, 'claude', draft, payload, False)
    assert not m.claude_combined_input_evidence(
        'text', '\n' + payload, 'claude', '', payload, True)

    # Exact visible co-submit ownership retains trailing hard-newline rows
    # through the real cursor and ignores only blank terminal padding below it.
    for outgoing in ('alpha\nbeta', 'alpha\nbeta\n', 'alpha\nbeta\n\n'):
        wanted = draft + '\n' + outgoing
        parts = wanted.split('\n')
        rows = ['─' * 20, '❯ ' + parts[0]] + ['  ' + row for row in parts[1:]]
        cursor_y = len(rows) - 1
        cursor_x = 2 + m.cell_width(parts[-1])
        raw = '\n'.join(rows + ['─' * 20, ''])
        assert m.state(raw, wanted, cursor_x, cursor_y, draft) == 'own', repr(outgoing)
        padded = '\n'.join(rows + ['  ', '   ', '─' * 20, ''])
        assert m.state(padded, wanted, cursor_x, cursor_y, draft) == 'own'
        assert m.state(raw, wanted, cursor_x + 1, cursor_y, draft) == 'busy'
        assert m.state(raw, wanted, cursor_x, cursor_y - 1, draft) == 'busy'
        missing = '\n'.join(rows[:-1] + ['─' * 20, ''])
        assert m.state(missing, wanted, cursor_x, cursor_y, draft) == 'unknown'
    extra = '\n'.join(rows + ['  unexpected continuation', '─' * 20, ''])
    assert m.state(extra, wanted, cursor_x, cursor_y, draft) == 'busy'
PYTEST

# Fresh fork command/menu shape runs through the real sender once.
reset_case forkcompact
out=$(run_sender %7 --submit-delay 0 --render-wait 3 --max-wait 3 --typed-command '/compact')
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^paste-buffer$' "$FAKE_STATE/tmux-calls" || true) -eq 0 ]]
[[ $(grep -c '^send-keys$' "$FAKE_STATE/tmux-calls") -eq 2 ]]
[[ $(cat "$FAKE_STATE/submitted") == '/compact' ]]

# A measured Codex busy-queue composer accepts one exact short payload once.
reset_case busyqueue
queue_prompt="$TEST_DIR/queue-prompt"
printf 'Reply with exactly P141-QUEUED-TEST' > "$queue_prompt"
out=$(run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$queue_prompt")
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG") -eq 1 ]]
[[ $(<"$FAKE_STATE/submitted") == 'Reply with exactly P141-QUEUED-TEST' ]]
[[ ! -s "$FAKE_STATE/composer" ]]

# The current separate model/context queue footer works end-to-end too.
reset_case busycontext
printf 'S short control: reply S-BUSY-1 after the current task.' > "$queue_prompt"
out=$(run_sender %7 --submit-delay 0 --render-wait 2 --max-wait 3 --poll-interval 0.1 --prompt-file "$queue_prompt")
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG") -eq 1 ]]
cmp "$queue_prompt" "$FAKE_STATE/submitted"

# Once ownership was visible, an unknown frame stops even with a large budget.
reset_case unknown-after-own
if run_sender %7 --stable-window 0 --submit-delay 8 --render-wait 30 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/ownership-loss.err"; then
  echo 'FAIL: unknown frame after ownership was submitted' >&2; exit 1
else rc=$?; [[ $rc -eq 3 ]]; fi
grep -q 'reason=post-paste-unknown' "$TEST_DIR/ownership-loss.err"
pending=$(assert_pending ambiguous "$TEST_DIR/ownership-loss.err")
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# Reporting can fail after Enter: retain as ambiguous, never safe-to-retry deferred.
reset_case empty
if run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" >/dev/full 2>"$TEST_DIR/report-failure.err"; then
  echo 'FAIL: failed success reporting returned success' >&2; exit 1
else rc=$?; [[ $rc -eq 1 ]]; fi
pending=$(assert_pending ambiguous "$TEST_DIR/report-failure.err")
[[ $(<"$pending") == $'alpha\nbeta' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG") -eq 1 ]]
rm -rf "$(dirname "$pending")"

# The stable-empty pair and pre-paste recheck must finish before max-wait.
# Simulate a second capture that itself returns only after the deadline.
reset_case slow-second-empty
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/slow-capture.err"; then
  echo 'FAIL: late empty observation was delivered after max-wait' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
pending=$(assert_pending deferred "$TEST_DIR/slow-capture.err")
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# The immediate pre-paste recheck is the third capture and must share max-wait.
reset_case slow-third-empty
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/slow-third.err"; then
  echo 'FAIL: slow third empty observation was delivered after max-wait' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
pending=$(assert_pending deferred "$TEST_DIR/slow-third.err")
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# A signal while waiting before any paste must still retain the outgoing payload.
reset_case interrupt-before-paste
if FAKE_INTERRUPT_BEFORE_PASTE=1 run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/pre-paste-signal.err"; then
  echo 'FAIL: pre-paste interruption returned success' >&2; exit 1
else rc=$?; [[ $rc -eq 143 ]]; fi
pending=$(assert_pending deferred "$TEST_DIR/pre-paste-signal.err")
[[ $(<"$pending") == $'alpha\nbeta' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# A clock subprocess failure after snapshot creation but before paste keeps a private deferred copy.
reset_case empty
if FAKE_FAIL_CLOCK_BEFORE_PASTE=1 run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/clock-failure.err"; then
  echo 'FAIL: injected pre-paste clock failure returned success' >&2; exit 1
else rc=$?; [[ $rc -eq 1 ]]; fi
pending=$(assert_pending deferred "$TEST_DIR/clock-failure.err")
[[ $(<"$pending") == $'alpha\nbeta' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# Empty composer plus unrelated generation output still accepts queued input.
reset_case streaming
out=$(run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file")
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^enter$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]

# A single stale empty frame after paste is tolerated until the paste renders exactly.
reset_case render-stale-empty
out=$(run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file")
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG") -eq 1 ]]

# Initial unknown repaint may settle, but a known mixed composer stops.
for mode in render-unknown render-late-unknown slow-first-own; do
  reset_case "$mode"
  out=$(run_sender %7 --render-wait 2 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file")
  [[ "$out" == 'status=sent receipt=unverified' ]]
  [[ $(grep -c '^enter$' "$FAKE_LOG") -eq 1 ]]
done
for mode in render-late-unknown render-unknown-human slow-first-own; do
  reset_case "$mode"
  if run_sender %7 --render-wait 1 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/render-limit.err"; then
    echo 'FAIL: timeout or mixed render was submitted' >&2; exit 1
  else rc=$?; [[ $rc -eq 3 ]]; fi
  pending=$(assert_pending ambiguous "$TEST_DIR/render-limit.err")
  [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
  rm -rf "$(dirname "$pending")"
done

# Persistently stale empty rendering times out ambiguously; it never presses Enter.
reset_case persistent-empty-after-paste
if run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/persistent-empty.err"; then
  echo 'FAIL: persistent stale empty rendering was submitted' >&2; exit 1
else rc=$?; [[ $rc -eq 3 ]]; fi
pending=$(assert_pending ambiguous "$TEST_DIR/persistent-empty.err")
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(<"$FAKE_STATE/composer") == $'alpha\nbeta' ]]
rm -rf "$(dirname "$pending")"

# A persistent unknown render frame exhausts its budget without Enter.
reset_case unknown-after-paste
if run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/unknown-after-paste.err"; then
  echo 'FAIL: unknown post-paste frame was submitted' >&2; exit 1
else rc=$?; [[ $rc -eq 3 ]]; fi
pending=$(assert_pending ambiguous "$TEST_DIR/unknown-after-paste.err")
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# Static draft fixtures with a middle cursor are not provable append targets; modals also defer.
for mode in human slash modal; do
  reset_case "$mode"
  if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/$mode.err"; then
    echo "FAIL: $mode composer was sent" >&2; exit 1
  else rc=$?; [[ $rc -eq 2 ]]; fi
  pending=$(assert_pending deferred "$TEST_DIR/$mode.err")
  [[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
  [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
  [[ $(<"$pending") == $'alpha\nbeta' ]]
  rm -rf "$(dirname "$pending")"
done

# Real captured dialogs and an unfamiliar framed choice must not reach tmux
# paste or Enter in the legacy sender.
for fixture in claude-2.1.302-login-modal.ansi claude-2.1.302-trust-modal.ansi \
               claude-2.1.302-permission-modal.ansi claude-2.1.302-exit-background-modal.ansi \
               SYNTHETIC-claude-update-dialog.ansi \
               SYNTHETIC-UNVERIFIED-claude-unsent-feedback-exit-dialog.ansi; do
  reset_case modal
  cp "$FIXTURES/$fixture" "$FAKE_STATE/modal"
  if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/$fixture.out" 2>"$TEST_DIR/$fixture.err"; then
    echo "FAIL: $fixture accepted input" >&2; exit 1
  fi
  [[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
  [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
done
# These current-wording dialogs take the Codex parser route if quoted Codex
# rows are visible. They must still defer without paste or Enter.
for fixture in claude-2.1.302-trust-modal.ansi claude-2.1.302-permission-modal.ansi; do
  reset_case modal
  cp "$FIXTURES/$fixture" "$FAKE_STATE/modal"
  printf '\n› quoted Codex input\n  Any model · Context 50%% left\n' >> "$FAKE_STATE/modal"
  if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/$fixture-quoted.out" 2>"$TEST_DIR/$fixture-quoted.err"; then
    echo "FAIL: $fixture with quoted Codex screen accepted input" >&2; exit 1
  fi
  [[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
  [[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
done
# Master's narrow pre-routing trust check must still win over the Codex sniff.
reset_case modal
printf 'Do you trust the contents of this project?\n❯ No, exit\n› quoted Codex input\n  Any model · Context 50%% left\n' > "$FAKE_STATE/modal"
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/legacy-trust-precheck.out" 2>"$TEST_DIR/legacy-trust-precheck.err"; then
  echo 'FAIL: legacy trust precheck accepted input' >&2; exit 1
fi
grep -q 'reason=composer-modal' "$TEST_DIR/legacy-trust-precheck.err"
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
reset_case modal
printf '────────────────\nChoose an account:\n❯ 1. Foo\n  2. Bar\n────────────────\n' > "$FAKE_STATE/modal"
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/unfamiliar.out" 2>"$TEST_DIR/unfamiliar.err"; then
  echo 'FAIL: unfamiliar framed choice accepted input' >&2; exit 1
fi
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]

# Synthetic Codex approval with a retained context footer must also defer.
reset_case modal
printf 'Would you like to run this command?\n› 1. Yes, proceed\n  2. No\nPress enter to confirm · Esc to cancel\n  Any model · Context 50%% left\n' > "$FAKE_STATE/modal"
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/codex-approval.out" 2>"$TEST_DIR/codex-approval.err"; then
  echo 'FAIL: synthetic Codex approval accepted input' >&2; exit 1
fi
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]

reset_case modal
printf 'Choose an option:\n› 1. Continue\n  2. Stop\n  Any model · Context 50%% left\n' > "$FAKE_STATE/modal"
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$prompt_file" >"$TEST_DIR/unknown-codex-choice.out" 2>"$TEST_DIR/unknown-codex-choice.err"; then
  echo 'FAIL: synthetic unknown Codex choice accepted input' >&2; exit 1
fi
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]

# A new human draft between stable-empty observations and paste defers safely.
reset_case human-before-paste
if run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/before-paste.err"; then
  echo 'FAIL: pre-paste human draft was sent' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
pending=$(assert_pending deferred "$TEST_DIR/before-paste.err")
[[ $(grep -c '^paste-start$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# If human input appears after our paste, do not Enter, erase, or paste again.
reset_case human-during-delay
if run_sender %7 --submit-delay 1 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/midflight.err"; then
  echo 'FAIL: changed composer was submitted' >&2; exit 1
else rc=$?; [[ $rc -eq 3 ]]; fi
pending=$(assert_pending ambiguous "$TEST_DIR/midflight.err")
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
[[ $(<"$FAKE_STATE/composer") == $'alpha\nbeta human began typing' ]]
# A second attempt while the ambiguous composer is occupied must defer, never duplicate.
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$pending" 2>"$TEST_DIR/retry-occupied.err"; then
  echo 'FAIL: retry was pasted over occupied composer' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
# A deliberate retry after the composer is empty delivers the retained payload exactly once.
rm -f "$FAKE_STATE/pasted"
: > "$FAKE_STATE/composer"
printf empty > "$FAKE_STATE/mode"
out=$(run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$pending")
[[ "$out" == 'status=sent receipt=unverified' ]]
[[ $(grep -c '^enter$' "$FAKE_LOG") -eq 1 ]]
rm -rf "$(dirname "$pending")"

# If the sender stops after paste, its pending message must not be pasted over
# the same exact visible payload on a deliberate retry.
reset_case empty
if FAKE_INTERRUPT_AFTER_PASTE=1 run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/interrupted.err"; then
  echo 'FAIL: injected post-paste interruption returned success' >&2; exit 1
else rc=$?; [[ $rc -ne 0 ]]; fi
pending=$(assert_pending ambiguous "$TEST_DIR/interrupted.err")
[[ $(<"$FAKE_STATE/composer") == $'alpha\nbeta' ]]
if run_sender %7 --submit-delay 0 --max-wait 1 --poll-interval 0.1 --prompt-file "$pending" 2>"$TEST_DIR/retry-own.err"; then
  echo 'FAIL: exact visible payload was submitted twice' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# A parser subprocess failure after paste becomes unknown and keeps the payload.
reset_case empty
if FAKE_FAIL_PARSER_AFTER_PASTE=1 run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/parser-failure.err"; then
  echo 'FAIL: parser failure after paste was treated as success' >&2; exit 1
else rc=$?; [[ $rc -eq 3 ]]; fi
pending=$(assert_pending ambiguous "$TEST_DIR/parser-failure.err")
grep -q 'reason=post-paste-render-timeout' "$TEST_DIR/parser-failure.err"
[[ $(grep -c '^paste-start$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# Paste failure retains payload and never submits; the named buffer is cleaned.
reset_case empty
if FAKE_FAIL_PASTE=1 run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/paste.err"; then
  echo 'FAIL: paste failure reported success' >&2; exit 1
else rc=$?; [[ $rc -eq 3 ]]; fi
pending=$(assert_pending ambiguous "$TEST_DIR/paste.err")
[[ $(grep -c '^delete-buffer$' "$FAKE_LOG") -eq 1 ]]
[[ $(grep -c '^enter$' "$FAKE_LOG" || true) -eq 0 ]]
rm -rf "$(dirname "$pending")"

# The default submit delay remains eight seconds, measured from paste to Enter.
reset_case empty
if out=$(FAKE_REAL_SLEEP=1 run_sender %7 --stable-window 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file"); then
  [[ "$out" == 'status=sent receipt=unverified' ]]
else
  echo 'FAIL: successful prompt-file delivery returned nonzero' >&2
  exit 1
fi
python3 - "$FAKE_STATE/times" <<'PY'
from pathlib import Path
import sys
values = [int(x) for x in Path(sys.argv[1]).read_text().splitlines()]
assert len(values) == 2, values
elapsed = (values[1] - values[0]) / 1_000_000_000
assert 7.8 <= elapsed <= 11.5, elapsed
PY

# A target-lock timeout is a deferred, privately retained delivery.
reset_case empty
if FAKE_FAIL_FLOCK=1 run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" 2>"$TEST_DIR/lock.err"; then
  echo 'FAIL: failed target lock was ignored' >&2; exit 1
else rc=$?; [[ $rc -eq 2 ]]; fi
pending=$(assert_pending deferred "$TEST_DIR/lock.err")
grep -q 'reason=target-lock-timeout' "$TEST_DIR/lock.err"
[[ ! -s "$FAKE_LOG" ]]
rm -rf "$(dirname "$pending")"

# Aliases resolving to the same pane serialize the full paste/delay/submit sequence.
reset_case empty
run_sender %7 --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" & one=$!
run_sender_without_xdg_runtime test:worker --submit-delay 0 --max-wait 3 --poll-interval 0.1 --prompt-file "$prompt_file" & two=$!
wait "$one"; wait "$two"
python3 - "$FAKE_LOG" <<'PY'
from pathlib import Path
import sys
lines = Path(sys.argv[1]).read_text().splitlines()
assert lines == ['paste-start','paste-end','enter','paste-start','paste-end','enter'], lines
PY

echo 'claude-send composer protection tests passed'
