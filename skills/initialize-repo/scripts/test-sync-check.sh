#!/usr/bin/env bash
# shellcheck disable=SC2016
# sync-check.sh and the AGENTS.md template's required "Project structure" section.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC="$HERE/sync-check.sh"
TEMPLATE="$HERE/../templates/AGENTS.md"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
fail=0
check() { local what="$1"; shift; if "$@"; then echo "ok   $what"; else echo "FAIL $what"; fail=1; fi; }

check "template has a Project structure heading" grep -qx '## Project structure' "$TEMPLATE"
check "template marks the section REQUIRED" grep -q 'REQUIRED' "$TEMPLATE"
check "template points agents at the where skill" grep -q '`where` skill' "$TEMPLATE"

mkdir -p "$WORK/none" "$WORK/placeholder" "$WORK/filled" "$WORK/absent"
printf '# Agent Instructions\n\n## Build and test\n\nmake\n' > "$WORK/none/AGENTS.md"
# A repo scaffolded from the template and never filled in.
sed 's/{{PROJECT_NAME}}/x/g; s/{{PROJECT_DESCRIPTION}}/d/g' "$TEMPLATE" > "$WORK/placeholder/AGENTS.md"
printf '# A\n\n## Project structure\n\n- `src/` -- code\n\n## Build and test\n\nmake\n' > "$WORK/filled/AGENTS.md"

"$SYNC" "$WORK/none" > "$WORK/o1" 2>&1
check "missing section is reported" grep -Eq 'structure +.*AGENTS.md.*no .Project structure. section' "$WORK/o1"
"$SYNC" "$WORK/placeholder" > "$WORK/o2" 2>&1
check "unfilled template section is reported" grep -Eq 'structure +.*AGENTS.md.*placeholder' "$WORK/o2"
"$SYNC" "$WORK/filled" > "$WORK/o3" 2>&1
check "a filled section is reported ok" grep -Eq 'structure +.*AGENTS.md.*present' "$WORK/o3"
"$SYNC" "$WORK/absent" > "$WORK/o4" 2>&1
check "no AGENTS.md is not double-reported as a structure problem" test "$(grep -c "structure " "$WORK/o4")" -eq 0
# Same heading definition as the where skill: case-insensitive, Structure/Layout
# variants, and a ## inside a code fence does not end the section.
mkdir -p "$WORK/variant" "$WORK/fenced"
printf '# A\n\n## Structure\n\n- `src/` -- code\n' > "$WORK/variant/AGENTS.md"
"$SYNC" "$WORK/variant" > "$WORK/o5" 2>&1
check "'## Structure' counts as the section" grep -Eq 'structure +.*AGENTS.md.*present' "$WORK/o5"
printf '# A\n\n## repository LAYOUT\n\n- `src/` -- code\n' > "$WORK/variant/AGENTS.md"
"$SYNC" "$WORK/variant" > "$WORK/o6" 2>&1
check "'## repository LAYOUT' counts as the section" grep -Eq 'structure +.*AGENTS.md.*present' "$WORK/o6"
printf '# A\n\n## Project structure\n\n```\n## inside fence\n```\n- `src/` -- code\n' > "$WORK/fenced/AGENTS.md"
"$SYNC" "$WORK/fenced" > "$WORK/o7" 2>&1
check "a ## inside a code fence does not end the section" grep -Eq 'structure +.*AGENTS.md.*present' "$WORK/o7"

exit "$fail"
