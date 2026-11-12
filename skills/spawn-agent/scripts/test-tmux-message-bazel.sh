#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$(dirname "$0")/scripts/test-tmux-message.py"
