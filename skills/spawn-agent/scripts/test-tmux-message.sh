#!/usr/bin/env bash
# Regression: repository and installed aliases must resolve sibling helpers.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf -- "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/installed bin" "$TEST_DIR/fake bin"
ln -s "$SCRIPT_DIR/tmux-message.sh" "$TEST_DIR/installed bin/tmux-message"
cat > "$TEST_DIR/fake bin/tmux" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$TMUX_TEST_ARGS"
case " $* " in
    *' list-windows '*) printf '@7\twindow\n';;
    *' list-panes '*) printf '4242:%%88:1:window\n';;
    *' capture-pane '*) printf 'controlled pane history\n';;
    *) exit 99;;
esac
STUB
chmod +x "$TEST_DIR/fake bin/tmux"
export PATH="$TEST_DIR/fake bin:$PATH"
export TMUX_TEST_ARGS="$TEST_DIR/args"
export SPAWN_TMUX_LABEL=alias-test
unset SPAWN_TMUX_SOCKET
for entry in "$SCRIPT_DIR/tmux-message.sh" "$TEST_DIR/installed bin/tmux-message"; do
    status=0
    "$entry" > "$TEST_DIR/out" 2> "$TEST_DIR/err" || status=$?
    [[ $status == 2 ]]
    [[ $(cat "$TEST_DIR/err") == Usage:* ]]
    [[ $("$entry" read session:window) == 'controlled pane history' ]]
    printf '%s\n' -L alias-test capture-pane -e -p -t %88 -S -200 > "$TEST_DIR/expected"
    cmp "$TEST_DIR/expected" "$TEST_DIR/args"
done
# Isolate send forwarding from the live transport while keeping both alias hops.
mkdir -p "$TEST_DIR/skills/spawn-agent/source scripts" "$TEST_DIR/repo bin"
cp -R "$SKILLS_ROOT/_shared" "$TEST_DIR/skills/_shared"
cp "$SCRIPT_DIR/tmux-message.sh" "$SCRIPT_DIR/tmux-ctx.sh" "$TEST_DIR/skills/spawn-agent/source scripts/"
cat > "$TEST_DIR/skills/spawn-agent/source scripts/tmux-message.py" <<'STUB'
import os, sys
with open(os.environ['TMUX_TEST_ARGS'], 'wb') as f:
    f.write(b''.join(s.encode() + b'\0' for s in sys.argv[1:]))
sys.exit(3)
STUB
chmod +x "$TEST_DIR/skills/spawn-agent/source scripts/tmux-message.py"
ln -s "$TEST_DIR/skills/spawn-agent/source scripts/tmux-message.sh" "$TEST_DIR/repo bin/tmux-message"
ln -s "$TEST_DIR/repo bin/tmux-message" "$TEST_DIR/installed bin/send-message"
message=$'Actual Unicode λ text\nwith $literal content'
for entry in "$TEST_DIR/repo bin/tmux-message" "$TEST_DIR/installed bin/send-message"; do
    status=0
    "$entry" send %88 --submit-delay 8 "$message" || status=$?
    [[ $status == 3 ]]
    printf '%s\0' %88 --submit-delay 8 "$message" > "$TEST_DIR/expected"
    cmp "$TEST_DIR/expected" "$TEST_DIR/args"
done
printf 'tmux-message alias tests passed\n'
