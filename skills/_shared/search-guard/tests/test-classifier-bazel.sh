#!/usr/bin/env bash
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[ -f "$here/tests/test_search_guard.py" ] || here=$(cd -- "$here/.." && pwd)
exec python3 "$here/tests/test_search_guard.py"
