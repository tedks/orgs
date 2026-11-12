#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
# Bazel places this entrypoint at the package root; direct execution leaves it
# beside the Python suite in scripts/.
here="$(dirname "$0")"
if [[ -f "$here/scripts/test-tmux-message.py" ]]; then
    exec python3 "$here/scripts/test-tmux-message.py"
fi
exec python3 "$here/test-tmux-message.py"
