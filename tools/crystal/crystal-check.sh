#!/usr/bin/env bash
# crystal-check.sh — speculative merge conflict detector (Crystal, v0).
#
# Textual conflicts are detected with `git merge-tree --write-tree`, which
# computes the merge without touching the index, any worktree, or any ref.
# Semantic conflicts (a clean merge whose tests fail) are detected by
# checking the merged tree out as PLAIN FILES (via a throwaway index +
# `git checkout-index`, no .git in the scratch dir) and running the
# boundary-test command there with git's environment variables and OLDPWD
# unset.
#
# Isolation is best-effort against ACCIDENTS, not a security sandbox against
# hostile code. It defeats the common accidental mutation — a test that runs
# git in its working directory (a shared-.git worktree would let that reach
# the real object store and refs; this does not) — and the inherited-env and
# OLDPWD paths back to the real repo. It does NOT contain a command that uses
# an absolute path to the real repo, escapes via a symlink, or otherwise
# means harm. Only point --test-cmd at boundary-test commands you trust; in
# the org, those are commands the team authored.
#
# Other consequences, by design:
#   - a --test-cmd that itself requires a git repository is out of scope in
#     v0: it will find no .git and report FAIL. Do not point Crystal at such
#     commands; that FAIL is noise, not a semantic conflict.
#   - a --test-cmd that backgrounds a process can still leak that process
#     (--timeout bounds a wedged foreground command, not a daemon it spawns).
#     Boundary-test commands must not daemonize.
#
# Requires: bash >= 4 (associative arrays); git >= 2.38 (both checked); a
# coreutils `timeout` for --timeout. The test command should be green on each
# branch individually — a branch red on its own makes every pairing FAIL,
# which is noise.
set -Eeuo pipefail

[ "${BASH_VERSINFO[0]:-0}" -ge 4 ] || { echo "crystal: bash >= 4 required" >&2; exit 2; }

usage() {
    cat >&2 <<'EOF'
usage: crystal-check.sh [--base <branch>] [--test-cmd <cmd>] [--timeout <sec>] [branch ...]

Checks each named branch against the base, and every pair of named
branches against each other, for textual merge conflicts — and, when
--test-cmd is given, for semantic conflicts: a clean merge whose test
command fails. The command runs via `bash -c` with the merged tree
extracted as plain files (no .git) as its working directory.

Only local branch names are accepted (not tags, SHAs, or HEAD); each is
pinned to a commit once, up front, so a concurrent ref update cannot make
the report and the tested tree disagree.

Default branches: every local branch except the base (deduplicated).
Default base: master, else main.
Default timeout: 120s per test command (0 disables; needs coreutils
`timeout`, else the test runs unbounded and a note is printed once).

Exit: 0 no conflicts · 1 at least one conflict (textual or semantic) ·
2 usage or environment error.
EOF
    exit 2
}

die() { echo "crystal: $1" >&2; exit 2; }

base="" test_cmd="" timeout_s=120
branches=()
while [ $# -gt 0 ]; do
    case "$1" in
        --base)     [ $# -ge 2 ] || usage; base=$2; shift 2 ;;
        --test-cmd) [ $# -ge 2 ] || usage; test_cmd=$2; shift 2 ;;
        --timeout)  [ $# -ge 2 ] || usage; timeout_s=$2; shift 2 ;;
        -h|--help)  usage ;;
        --*)        usage ;;
        *)          branches+=("$1"); shift ;;
    esac
done
case "$timeout_s" in ''|*[!0-9]*) die "--timeout wants a non-negative integer" ;; esac

git rev-parse --git-dir >/dev/null 2>&1 || die "not inside a git repository"
git rev-parse --verify -q HEAD >/dev/null \
    || die "no commits yet (unborn HEAD) — nothing to check"
git merge-tree --write-tree HEAD HEAD >/dev/null 2>&1 \
    || die "git merge-tree --write-tree unsupported (need git >= 2.38)"

# Unexpected failure of any unguarded command lands here as a clean exit 2
# rather than leaking git's raw 1/128 (errtrace carries this into functions).
trap 'st=$?; echo "crystal: unexpected error near line $LINENO (exit $st)" >&2; exit 2' ERR

if [ -z "$base" ]; then
    if   git show-ref --verify -q refs/heads/master; then base=master
    elif git show-ref --verify -q refs/heads/main;   then base=main
    else die "no master or main branch; pass --base"; fi
fi
git show-ref --verify -q "refs/heads/$base" || die "base is not a local branch: $base"

if [ ${#branches[@]} -eq 0 ]; then
    while IFS= read -r b; do
        [ "$b" = "$base" ] || branches+=("$b")
    done < <(git for-each-ref --format='%(refname:short)' refs/heads)
fi

# Validate (local branches only), drop the base, and deduplicate while
# preserving order — so an explicit `base` or a repeated name cannot produce
# self-merges or doubled stanzas.
declare -A seen=()
deduped=()
for b in "${branches[@]}"; do
    git show-ref --verify -q "refs/heads/$b" || die "not a local branch: $b"
    [ "$b" = "$base" ] && continue
    [ -n "${seen[$b]:-}" ] && continue
    seen[$b]=1
    deduped+=("$b")
done
branches=("${deduped[@]}")

# Pin every ref to a commit SHA ONCE. All merge/archive/report operations use
# the pinned SHA; names are display-only. This closes the re-resolution race.
declare -A sha=()
sha[$base]=$(git rev-parse --verify "refs/heads/$base^{commit}")
for b in "${branches[@]}"; do
    sha[$b]=$(git rev-parse --verify "refs/heads/$b^{commit}")
done

# A repo with only the base and no other branches has no pair to check: that
# is vacuously clean, not an error.
if [ ${#branches[@]} -eq 0 ]; then
    echo "# Crystal report — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "base: ${base}@$(git rev-parse --short "${sha[$base]}")"
    echo
    echo "summary: all clean (no non-base branches)"
    exit 0
fi

have_timeout=0
if [ "$timeout_s" -gt 0 ]; then
    # Probe for GNU-coreutils semantics, not mere presence: a non-GNU
    # `timeout` (e.g. one without --kill-after) would exit non-zero on a
    # perfectly clean test and turn it into a spurious semantic conflict —
    # a false positive, worse than running unbounded. Only trust a timeout
    # that actually runs `true` to success with the flags we use.
    if timeout --kill-after=1 1 true >/dev/null 2>&1; then
        have_timeout=1
    else
        echo "crystal: no GNU 'timeout' (--kill-after); test commands run unbounded" >&2
    fi
fi

scratch_root=$(mktemp -d "${TMPDIR:-/tmp}/crystal.XXXXXX")
scratch_root=$(cd "$scratch_root" && pwd -P)   # physical path for GIT_CEILING_DIRECTORIES (git walks the physical tree; a symlinked TMPDIR like macOS /tmp would else defeat the ceiling)
cleanup() { rm -rf "$scratch_root"; }
trap cleanup EXIT

found_conflict=0
had_error=0
wt_seq=0

# Git's own environment variables, unset before running a test so an
# inherited GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE cannot point it back at the
# real repository. Computed once.
git_env_vars=$(git rev-parse --local-env-vars 2>/dev/null || true)

# run_test <dir> — run the test command in <dir>; return its status. The dir
# is applied with `cd` (not interpolated into the bash -c source, so an odd
# TMPDIR path is harmless); git env vars and OLDPWD are unset so the sandbox
# cannot be escaped by inherited environment or `cd -`. Called in an `if`,
# so a failing test is data, not death.
run_test() {
    (
        cd "$1" || exit 127
        # Unset AFTER cd: cd itself re-sets OLDPWD to the invoking (real
        # repo) directory, so `cd -` would otherwise walk straight back.
        # shellcheck disable=SC2086
        unset $git_env_vars OLDPWD 2>/dev/null || true
        # Stop git's upward repo discovery at the scratch root, so a test
        # running `git` cannot find a real repo that TMPDIR happens to sit
        # inside. (Not in --local-env-vars, so the unset above leaves it.)
        export GIT_CEILING_DIRECTORIES="$scratch_root"
        if [ "$have_timeout" -eq 1 ]; then
            timeout --kill-after=10 "$timeout_s" bash -c "$test_cmd"
        else
            bash -c "$test_cmd"
        fi
    ) >/dev/null 2>&1
}

# join_conflicts — read conflicted paths on stdin, emit ", "-joined (paste
# -d cycles single chars, so it is not usable for a two-char separator).
join_conflicts() {
    local first=1 line out=""
    while IFS= read -r line; do
        if [ "$first" -eq 1 ]; then out=$line; first=0; else out="$out, $line"; fi
    done
    printf '%s' "$out"
}

# check_pair X Y — one report stanza; may set found_conflict/had_error.
check_pair() {
    local x=$1 y=$2 xs=${sha[$1]} ys=${sha[$2]}
    local mt_out mt_status=0 tree conflicts wt
    echo "## ${x}@$(git rev-parse --short "$xs") × ${y}@$(git rev-parse --short "$ys")"

    # stdout only: git guarantees the tree OID at the head of STDOUT, so a
    # warning on stderr can never be mistaken for it.
    mt_out=$(git merge-tree --write-tree "$xs" "$ys" 2>/dev/null) || mt_status=$?
    if [ "$mt_status" -eq 0 ]; then
        echo "merge: clean"
        tree=${mt_out%%$'\n'*}
        if [ -n "$test_cmd" ]; then
            wt_seq=$((wt_seq + 1)); wt="$scratch_root/wt-$wt_seq"; mkdir "$wt"
            # Extract the merged tree as plain files with `git archive`.
            # Settled v0 choice (do not flip back to checkout-index): archive
            # emits stored blobs and runs NO clean/smudge filter code, so a
            # repo-configured filter (e.g. LFS) cannot execute side effects
            # or hit the network from a speculative background check. The
            # cost is that archive honors export-ignore/export-subst, so a
            # repo relying on those for its buildable tree is out of scope
            # for v0 semantic checks — the safer failure of the two.
            git archive --format=tar "$tree" | tar -x -C "$wt"
            if run_test "$wt"; then echo "tests: pass"
            else echo "tests: FAIL"; found_conflict=1; fi
            rm -rf "$wt"
        else
            echo "tests: skipped (no --test-cmd)"
        fi
    elif [ "$mt_status" -eq 1 ]; then
        # Conflicted-file lines are "<mode> <oid> <stage>\t<path>"; the tree
        # OID line and trailing messages lack that exact shape and are skipped.
        conflicts=$(printf '%s\n' "$mt_out" \
            | awk -F'\t' 'NF>1 && $1 ~ /^[0-7]+ [0-9a-f]+ [0-9]+$/ {print $2}' \
            | sort -u | join_conflicts)
        echo "merge: CONFLICT (${conflicts:-unparsed})"
        found_conflict=1
    else
        echo "merge: error — merge-tree exited $mt_status"
        had_error=1
    fi
    echo
}

echo "# Crystal report — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "base: ${base}@$(git rev-parse --short "${sha[$base]}")"
echo

for b in "${branches[@]}"; do
    check_pair "$base" "$b"
done
n=${#branches[@]}
for ((i = 0; i < n; i++)); do
    for ((j = i + 1; j < n; j++)); do
        check_pair "${branches[$i]}" "${branches[$j]}"
    done
done

if   [ "$had_error" -eq 1 ];      then echo "summary: errors — see above"; exit 2
elif [ "$found_conflict" -eq 1 ]; then echo "summary: conflicts found";    exit 1
else                                   echo "summary: all clean";          exit 0
fi
