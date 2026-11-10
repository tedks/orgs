#!/usr/bin/env bash
# crystal-check.sh — speculative merge conflict detector (Crystal, v0).
#
# Textual conflicts are detected with `git merge-tree --write-tree`, which
# computes the merge without touching the index, any worktree, or any ref.
# Semantic conflicts (two green inputs whose clean merge fails the tests)
# are detected by extracting each pinned tree as PLAIN FILES with git archive
# (no .git in the scratch dir) and running the same boundary-test command.
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
# coreutils `timeout` for --timeout. Red input baselines make dependent pair
# tests inconclusive; they are reported as errors, not semantic conflicts.
set -Eeuo pipefail

[ "${BASH_VERSINFO[0]:-0}" -ge 4 ] || { echo "crystal: bash >= 4 required" >&2; exit 2; }

usage() {
    cat >&2 <<'EOF'
usage: crystal-check.sh [--base <branch>] [--test-cmd <cmd>] [--timeout <sec>] [branch ...]

Checks each explicitly named branch against the base, and every pair of named
branches against each other, for textual merge conflicts — and, when
--test-cmd is given, for semantic conflicts: a clean merge whose test
command fails after both input commits pass it alone. The command runs via
`bash -c` with the merged tree
extracted as plain files (no .git) as its working directory.

Only local branch names are accepted (not tags, SHAs, or HEAD); each is
pinned to a commit once, up front, so a concurrent ref update cannot make
the report and the tested tree disagree.

No named branches: clean no-op. Select current active branches explicitly;
the local branch list may include historical worktrees.
Default base: master, else main.
Default timeout: 120s per test command (0 disables; needs coreutils
`timeout`, else the test runs unbounded and a note is printed once).

Exit: 0 selected checks clean · 1 conflict without other error ·
2 usage, environment, red baseline, test timeout, or stale ref. Exit 2 can
coexist with actionable conflict stanzas; read the whole report.
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
    echo "base: ${base}@${sha[$base]}"
    echo
    echo "summary: all clean (no non-base branches selected)"
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
declare -A baseline_ok=()

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

# test_tree <tree> — extract a separate plain-file copy for each
# baseline/pair. Return 0 for green, 1 for red tests, 2 for extraction error,
# 3 for an inconclusive timeout/infrastructure exit from GNU timeout.
test_tree() {
    local tree=$1 wt rc
    wt_seq=$((wt_seq + 1)); wt="$scratch_root/wt-$wt_seq"
    mkdir "$wt" || return 2
    if ! git archive --format=tar "$tree" | tar -x -C "$wt"; then
        rm -rf "$wt"
        return 2
    fi
    if run_test "$wt"; then rc=0; else rc=$?; fi
    rm -rf "$wt" || return 2
    if [ "$have_timeout" -eq 1 ]; then
        case "$rc" in 124|125|137) return 3 ;; esac
    fi
    if [ "$rc" -eq 0 ]; then return 0; else return 1; fi
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
    local mt_out mt_status=0 tree conflicts test_status=0
    echo "## ${x}@${xs} × ${y}@${ys}"

    # stdout only: git guarantees the tree OID at the head of STDOUT, so a
    # warning on stderr can never be mistaken for it.
    mt_out=$(git merge-tree --write-tree "$xs" "$ys" 2>/dev/null) || mt_status=$?
    if [ "$mt_status" -eq 0 ]; then
        echo "merge: clean"
        tree=${mt_out%%$'\n'*}
        if [ -n "$test_cmd" ]; then
            if [ "${baseline_ok[$x]:-0}" -ne 1 ] || [ "${baseline_ok[$y]:-0}" -ne 1 ]; then
                echo "tests: skipped (input baseline not green)"
            else
                test_tree "$tree" || test_status=$?
                case "$test_status" in
                    0) echo "tests: pass" ;;
                    1) echo "tests: FAIL (semantic conflict)"; found_conflict=1 ;;
                    2) echo "tests: ERROR (tree extraction)"; had_error=1 ;;
                    3) echo "tests: ERROR (test timeout/infrastructure)"; had_error=1 ;;
                esac
            fi
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
echo "base: ${base}@${sha[$base]}"
echo

if [ -n "$test_cmd" ]; then
    for b in "$base" "${branches[@]}"; do
        baseline_status=0
        # Archive a tree, as pair checks do: archiving a commit expands
        # export-subst and can make baseline/pair inputs differ in fidelity.
        test_tree "${sha[$b]}^{tree}" || baseline_status=$?
        case "$baseline_status" in
            0) echo "baseline: ${b}@${sha[$b]} PASS"; baseline_ok[$b]=1 ;;
            1) echo "baseline: ${b}@${sha[$b]} FAIL"; had_error=1 ;;
            2) echo "baseline: ${b}@${sha[$b]} ERROR (tree extraction)"; had_error=1 ;;
            3) echo "baseline: ${b}@${sha[$b]} ERROR (test timeout/infrastructure)"; had_error=1 ;;
        esac
    done
    echo
fi

for b in "${branches[@]}"; do
    check_pair "$base" "$b"
done
n=${#branches[@]}
for ((i = 0; i < n; i++)); do
    for ((j = i + 1; j < n; j++)); do
        check_pair "${branches[$i]}" "${branches[$j]}"
    done
done

# A pinned result stays internally consistent when a ref moves, but an
# operator must not act on it as if it described the current branch heads.
for b in "$base" "${branches[@]}"; do
    current=$(git rev-parse --verify -q "refs/heads/$b^{commit}" 2>/dev/null) || current="<missing>"
    if [ "$current" != "${sha[$b]}" ]; then
        echo "stale: ${b} moved from ${sha[$b]} to $current"
        had_error=1
    fi
done

if [ "$had_error" -eq 1 ] && [ "$found_conflict" -eq 1 ]; then
    echo "summary: errors and conflicts found — see above"; exit 2
elif [ "$had_error" -eq 1 ]; then echo "summary: errors — see above"; exit 2
elif [ "$found_conflict" -eq 1 ]; then echo "summary: conflicts found";    exit 1
else                                   echo "summary: all clean";          exit 0
fi
