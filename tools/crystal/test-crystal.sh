#!/usr/bin/env bash
# test-crystal.sh — tripwire for crystal-check.sh. Builds a scratch repo
# with engineered situations and asserts crystal reports each distinctly,
# so a crystal that always says "clean" OR always says "conflict" fails
# loudly — the test can fail, by construction, in both directions:
#   1. textual conflict   (same line edited both sides)
#   2. semantic conflict  (clean merge, test command fails) — asserted
#                          scoped to the specific pair's stanza
#   3. compatible pair    (clean merge, test command passes)
#   4. base-only repo     (no non-base branch → vacuously clean, exit 0)
#   5. sandbox isolation  (a side-effecting test cannot mutate the real repo)
#   6. no-argument no-op despite historical local branches
#   7. red input baseline is an error, never a semantic conflict
#   8. a moved input ref makes the pinned report stale
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
crystal="$here/crystal-check.sh"
[ -x "$crystal" ] || { echo "not executable: $crystal" >&2; exit 1; }

tmp=$(mktemp -d "${TMPDIR:-/tmp}/crystal-test.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"

fail() { echo "FAIL: $1" >&2; exit 1; }
run_crystal() { # args: branches... ; capture output+status without set -e exit
    out=$("$crystal" --base master --test-cmd 'bash main.sh' "$@" 2>&1) \
        && status=0 || status=$?
}
# stanza PAIR-REGEX — print the block of $out from the matching "## " header
# to the blank line, so assertions can be scoped to one pair.
stanza() { awk -v re="$1" '/^## /{on=($0 ~ re)} on{print} on&&/^$/{exit}' <<<"$out"; }

git init -q -b master .
git config user.email crystal@test && git config user.name crystal-test

printf 'X=1\n' > lib.sh
# main.sh has a TOP check and a BOTTOM slot separated by padding, so an edit
# to the top region and an edit to the bottom region merge textually clean.
# All files written whole (no sed -i — BSD/POSIX portability).
write_main() { # $1 = TOP check line · $2 = BOTTOM slot line
    { printf '. ./lib.sh\n'
      printf '# top pad 1\n# top pad 2\n# top pad 3\n'
      printf '%s\n' "$1"
      printf '# mid pad 1\n# mid pad 2\n# mid pad 3\n# mid pad 4\n# mid pad 5\n# mid pad 6\n'
      printf '%s\n' "$2"
      printf '# bot pad 1\n# bot pad 2\n# bot pad 3\n'
      printf 'exit 0\n'
    } > main.sh
}
write_main '[ "$X" = 1 ] || exit 1' ':'
printf 'one\n' > conflict.txt
git add -A && git commit -qm base

git checkout -qb textual-a master
printf 'alpha\n' > conflict.txt && git commit -qam textual-a
git checkout -qb textual-b master
printf 'beta\n' > conflict.txt && git commit -qam textual-b

# sem-a: lib X=2 and the TOP check updated to match — green alone; touches
# only the top region + lib.sh.
git checkout -qb sem-a master
printf 'X=2\n' > lib.sh
write_main '[ "$X" = 2 ] || exit 1' ':'
bash main.sh || fail "sem-a must be green alone"
git commit -qam sem-a

# sem-b: fills the BOTTOM slot with a check assuming X=1 — green alone;
# touches only the bottom region. Merges cleanly with sem-a (distinct
# regions) but is then red: lib X=2 vs the bottom check's X=1.
git checkout -qb sem-b master
write_main '[ "$X" = 1 ] || exit 1' '[ "$X" = 1 ] || exit 1'
bash main.sh || fail "sem-b must be green alone"
git commit -qam sem-b

# ok-a: unrelated change — compatible with sem-b.
git checkout -qb ok-a master
printf 'unrelated\n' > other.txt && git add other.txt && git commit -qm ok-a
git checkout -qb red-alone master
printf 'X=9\n' > lib.sh && git commit -qam red-alone
git checkout -q master

# 1. textual conflict detected, exit 1, names the file
run_crystal textual-a textual-b
[ "$status" -eq 1 ] || fail "textual pair: expected exit 1, got $status:
$out"
stanza 'textual-a@.* × textual-b@' | grep -q 'CONFLICT (conflict.txt)' \
    || fail "textual pair: conflict.txt not named:
$out"

# 2. semantic conflict: within the sem-a × sem-b stanza specifically, the
#    merge is clean AND its tests FAIL (scoped — a spurious base-pair failure
#    cannot satisfy this).
run_crystal sem-a sem-b
[ "$status" -eq 1 ] || fail "semantic pair: expected exit 1, got $status:
$out"
sem_stanza=$(stanza 'sem-a@.* × sem-b@')
grep -q 'merge: clean' <<<"$sem_stanza" || fail "semantic pair: merge should be clean:
$out"
grep -q 'tests: FAIL' <<<"$sem_stanza" || fail "semantic pair: this pair's tests should FAIL:
$out"

# 3. compatible pair: everything clean and passing, exit 0
run_crystal ok-a sem-b
[ "$status" -eq 0 ] || fail "compatible pair: expected exit 0, got $status:
$out"
grep -q 'tests: FAIL\|CONFLICT' <<<"$out" && fail "compatible pair: spurious conflict:
$out"

# 4. base-only repo: a fresh repo with just master is vacuously clean.
#    Capture without letting set -e abort, and clean up regardless.
base_only=$(mktemp -d "${TMPDIR:-/tmp}/crystal-baseonly.XXXXXX")
bo_status=0
( cd "$base_only" && git init -q -b master . \
  && git config user.email t@t && git config user.name t \
  && printf 'x\n' > f && git add -A && git commit -qm base \
  && "$crystal" --base master >/dev/null 2>&1 ) || bo_status=$?
rm -rf "$base_only"
[ "$bo_status" -eq 0 ] || fail "base-only repo: expected exit 0, got $bo_status"

# 5. sandbox isolation: a test command that tries to mutate git must NOT
#    affect the real repo. Covers every escape path the sandbox closes — cwd
#    (no .git present + GIT_CEILING stops upward discovery), OLDPWD/`cd -`,
#    and an inherited GIT_DIR pointing at the real repo — each of which, if
#    it reached the real repo, would create a pwned-* branch. Crystal must
#    exit 0 (evil ends in `true`, so tests pass); a non-zero exit would mean
#    crystal errored before evil ran, which must not count as a pass.
branch_names() { git for-each-ref --format='%(refname)' refs/heads | sort; }
before=$(branch_names)
evil='git branch pwned-cwd 2>/dev/null;
      cd - >/dev/null 2>&1 && git branch pwned-oldpwd 2>/dev/null;
      cd "${OLDPWD:-/nonexistent}" 2>/dev/null && git branch pwned-oldpwd2 2>/dev/null;
      git branch pwned-gitdir 2>/dev/null;
      true'
iso_status=0
# Export GIT_DIR/GIT_WORK_TREE at the real repo so a regressed sandbox that
# stops unsetting git-env would let `git branch` inside evil hit the real repo.
out=$(GIT_DIR="$tmp/.git" GIT_WORK_TREE="$tmp" \
      "$crystal" --base master --test-cmd "$evil" ok-a 2>&1) || iso_status=$?
[ "$iso_status" -eq 0 ] || fail "sandbox isolation: crystal exited $iso_status (should be 0):
$out"
after=$(branch_names)
[ "$before" = "$after" ] || fail "sandbox isolation: test command mutated the real repo:
before=$before
after=$after"

# 6. upward-discovery isolation: when TMPDIR sits INSIDE the real repo, git's
#    parent-directory discovery would find it from the scratch dir — unless
#    GIT_CEILING_DIRECTORIES stops the walk. Point TMPDIR at a dir under the
#    test repo and assert an evil `git branch` from the sandbox cannot reach it.
mkdir -p "$tmp/nested"
before6=$(branch_names)
iso6_status=0
out=$(TMPDIR="$tmp/nested" \
      "$crystal" --base master --test-cmd 'git branch pwned-ceiling 2>/dev/null; true' ok-a 2>&1) \
      || iso6_status=$?
[ "$iso6_status" -eq 0 ] || fail "upward-discovery: crystal exited $iso6_status (should be 0):
$out"
after6=$(branch_names)
[ "$before6" = "$after6" ] || fail "upward-discovery: sandbox reached the enclosing repo via TMPDIR:
before=$before6
after=$after6"

# No branches means no active pair, even though this fixture has several
# historical refs. This fails if the old all-local-branches default returns.
noop_status=0
noop_out=$("$crystal" --base master --test-cmd 'bash main.sh' 2>&1) || noop_status=$?
[ "$noop_status" -eq 0 ] || fail "no-argument check should be a clean no-op:
$noop_out"
grep -q 'no active branches selected' <<<"$noop_out" || fail "no-argument report lacks no-op disposition:
$noop_out"
grep -q '^## ' <<<"$noop_out" && fail "no-argument check selected historical branches:
$noop_out"

# red-alone fails its own test. Its clean merge with sem-b must not be
# labelled a semantic conflict; the same command has no valid green baseline.
run_crystal red-alone sem-b
[ "$status" -eq 2 ] || fail "red baseline: expected exit 2, got $status:
$out"
grep -q 'baseline: red-alone@.* FAIL' <<<"$out" || fail "red baseline not reported:
$out"
red_stanza=$(stanza 'red-alone@.* × sem-b@')
grep -q 'merge: clean' <<<"$red_stanza" || fail "red baseline pair should merge cleanly:
$out"
grep -q 'tests: skipped (input baseline not green)' <<<"$red_stanza" || fail "red baseline pair was classified as a semantic conflict:
$out"

# A fixture-only test command moves ok-a while Crystal is checking its
# pinned commit. The report stays internally consistent but must say stale.
printf -v stale_cmd 'git -C %q update-ref refs/heads/ok-a %q; true' "$tmp" "$(git rev-parse sem-a)"
stale_status=0
stale_out=$("$crystal" --base master --test-cmd "$stale_cmd" ok-a 2>&1) || stale_status=$?
[ "$stale_status" -eq 2 ] || fail "moved head: expected exit 2, got $stale_status:
$stale_out"
grep -q '^stale: ok-a moved from ' <<<"$stale_out" || fail "moved head not marked stale:
$stale_out"

echo "PASS: crystal distinguishes textual/semantic/clean, proves green baselines, ignores historical refs, detects stale heads, and isolates tests"
