#!/usr/bin/env bash
# test-crystal.sh — tripwire for crystal-check.sh. Builds a scratch repo
# with three engineered situations and asserts crystal reports each one
# distinctly (so a crystal that always says "clean" or always says
# "conflict" fails loudly — the test can fail, by construction):
#   1. textual conflict         (same line edited both sides)
#   2. semantic conflict        (clean merge, test command fails)
#   3. compatible pair          (clean merge, test command passes)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
crystal="$here/crystal-check.sh"
[ -x "$crystal" ] || { echo "not executable: $crystal" >&2; exit 1; }

tmp=$(mktemp -d "${TMPDIR:-/tmp}/crystal-test.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"

fail() { echo "FAIL: $1" >&2; exit 1; }
run_crystal() { # args: branches... ; captures output+status without set -e exit
    out=$("$crystal" --base master --test-cmd 'bash main.sh' "$@" 2>&1) \
        && status=0 || status=$?
}

git init -q -b master .
git config user.email crystal@test && git config user.name crystal-test

# base: lib.sh sets X=1; main.sh checks it, with padding so later edits on
# nearby-but-distinct lines merge cleanly.
printf 'X=1\n' > lib.sh
cat > main.sh <<'EOF'
. ./lib.sh
# padding 1
# padding 2
# padding 3
[ "$X" = 1 ] || exit 1
# padding 4
# padding 5
# padding 6
exit 0
EOF
printf 'one\n' > conflict.txt
git add -A && git commit -qm base

# textual-a / textual-b: same line of conflict.txt, different edits.
git checkout -qb textual-a master
printf 'alpha\n' > conflict.txt && git commit -qam textual-a
git checkout -qb textual-b master
printf 'beta\n' > conflict.txt && git commit -qam textual-b

# sem-a: moves X to 2 and updates the existing check — green alone.
git checkout -qb sem-a master
printf 'X=2\n' > lib.sh
sed -i 's/= 1 \] || exit 1/= 2 ] || exit 1/' main.sh
bash main.sh || fail "sem-a must be green alone"
git commit -qam sem-a

# sem-b: appends a new check assuming X=1 — green alone, red merged with sem-a.
git checkout -qb sem-b master
sed -i 's/^exit 0$/[ "$X" = 1 ] || exit 1\nexit 0/' main.sh
bash main.sh || fail "sem-b must be green alone"
git commit -qam sem-b

# ok-a: unrelated change — compatible with sem-b.
git checkout -qb ok-a master
printf 'unrelated\n' > other.txt && git add other.txt && git commit -qm ok-a
git checkout -q master

# 1. textual conflict detected, exit 1, names the file
run_crystal textual-a textual-b
[ "$status" -eq 1 ] || fail "textual pair: expected exit 1, got $status"
grep -q 'CONFLICT (conflict.txt)' <<<"$out" || fail "textual pair: conflict.txt not named:
$out"

# 2. semantic conflict: clean merge, FAILing tests, exit 1
run_crystal sem-a sem-b
[ "$status" -eq 1 ] || fail "semantic pair: expected exit 1, got $status"
grep -A1 'sem-a@.* × sem-b@' <<<"$out" | grep -q 'merge: clean' \
    || fail "semantic pair: merge should be clean:
$out"
grep -q 'tests: FAIL' <<<"$out" || fail "semantic pair: tests should FAIL:
$out"

# 3. compatible pair: everything clean and passing, exit 0
run_crystal ok-a sem-b
[ "$status" -eq 0 ] || fail "compatible pair: expected exit 0, got $status:
$out"
grep -q 'tests: FAIL\|CONFLICT' <<<"$out" && fail "compatible pair: spurious conflict:
$out"

# 4. no scratch worktrees left behind in the test repo
[ "$(git worktree list | wc -l)" -eq 1 ] || fail "leaked worktrees:
$(git worktree list)"

echo "PASS: crystal-check distinguishes textual, semantic, and clean pairs"
