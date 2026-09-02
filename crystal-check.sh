#!/usr/bin/env bash
# crystal-check.sh — speculative merge conflict detector (Crystal, v0).
#
# Textual conflicts are detected with `git merge-tree --write-tree`, which
# computes the merge without touching the index, any worktree, or any ref.
# Semantic conflicts (a clean merge whose tests fail) are detected by
# materializing the merged tree in a disposable detached worktree and
# running the boundary-test command there. Nothing is ever pushed and no
# real branch or worktree is modified.
#
# Assumptions: git >= 2.38 (checked); the test command is green on each
# branch individually — if it fails on a branch by itself, every pairing of
# that branch will report FAIL and the report is noise, not signal.
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
usage: crystal-check.sh [--base <branch>] [--test-cmd <cmd>] [branch ...]

Checks each named branch against the base, and every pair of named
branches against each other, for textual merge conflicts — and, when
--test-cmd is given, for semantic conflicts: a clean merge whose test
command fails. The command runs with the scratch merge tree as its
working directory, via `bash -c`.

Default branches: every local branch except the base.
Default base: master, else main.

Exit: 0 no conflicts · 1 at least one conflict (textual or semantic) ·
2 usage or environment error.
EOF
    exit 2
}

base="" test_cmd=""
branches=()
while [ $# -gt 0 ]; do
    case "$1" in
        --base)     [ $# -ge 2 ] || usage; base=$2; shift 2 ;;
        --test-cmd) [ $# -ge 2 ] || usage; test_cmd=$2; shift 2 ;;
        -h|--help)  usage ;;
        --*)        usage ;;
        *)          branches+=("$1"); shift ;;
    esac
done

git rev-parse --git-dir >/dev/null 2>&1 \
    || { echo "crystal: not inside a git repository" >&2; exit 2; }
git merge-tree --write-tree HEAD HEAD >/dev/null 2>&1 \
    || { echo "crystal: git merge-tree --write-tree unsupported (need git >= 2.38)" >&2; exit 2; }

if [ -z "$base" ]; then
    if   git show-ref --verify -q refs/heads/master; then base=master
    elif git show-ref --verify -q refs/heads/main;   then base=main
    else echo "crystal: no master or main branch; pass --base" >&2; exit 2; fi
fi

if [ ${#branches[@]} -eq 0 ]; then
    while IFS= read -r b; do
        [ "$b" = "$base" ] || branches+=("$b")
    done < <(git for-each-ref --format='%(refname:short)' refs/heads)
fi
[ ${#branches[@]} -gt 0 ] || { echo "crystal: no branches to check" >&2; exit 2; }

had_error=0
for ref in "$base" "${branches[@]}"; do
    git rev-parse --verify -q "$ref^{commit}" >/dev/null \
        || { echo "crystal: unknown ref: $ref" >&2; had_error=1; }
done
[ "$had_error" -eq 0 ] || exit 2

# Disposable worktrees live under one scratch root, removed on exit even if
# a test command wedges the script.
scratch_root=$(mktemp -d "${TMPDIR:-/tmp}/crystal.XXXXXX")
cleanup() {
    local wt
    for wt in "$scratch_root"/wt-*; do
        [ -e "$wt" ] && git worktree remove --force "$wt" >/dev/null 2>&1 || true
    done
    rm -rf "$scratch_root"
    git worktree prune >/dev/null 2>&1 || true
}
trap cleanup EXIT

found_conflict=0
wt_seq=0

# check_pair X Y — one report stanza; sets found_conflict/had_error.
check_pair() {
    local x=$1 y=$2
    local xsha ysha mt_out mt_status=0 tree conflicts test_line="" commit wt
    xsha=$(git rev-parse --short "$x")
    ysha=$(git rev-parse --short "$y")
    echo "## ${x}@${xsha} × ${y}@${ysha}"

    mt_out=$(git merge-tree --write-tree "$x" "$y" 2>&1) || mt_status=$?
    if [ "$mt_status" -eq 0 ]; then
        echo "merge: clean"
        tree=${mt_out%%$'\n'*}
        if [ -n "$test_cmd" ]; then
            commit=$(git commit-tree "$tree" -p "$(git rev-parse "$x")" \
                     -m "crystal scratch: $x + $y")
            wt_seq=$((wt_seq + 1))
            wt="$scratch_root/wt-$wt_seq"
            git worktree add -q --detach "$wt" "$commit"
            if (cd "$wt" && bash -c "$test_cmd") >/dev/null 2>&1; then
                test_line="pass"
            else
                test_line="FAIL"
                found_conflict=1
            fi
            git worktree remove --force "$wt"
            echo "tests: $test_line"
        else
            echo "tests: skipped (no --test-cmd)"
        fi
    elif [ "$mt_status" -eq 1 ]; then
        # Conflicted-file lines are "<mode> <oid> <stage>\t<path>".
        conflicts=$(printf '%s\n' "$mt_out" \
            | sed -n 's/^[0-7]* [0-9a-f]* [0-9]*\t//p' | sort -u | paste -sd', ' -)
        echo "merge: CONFLICT (${conflicts:-unparsed})"
        found_conflict=1
    else
        echo "merge: error — merge-tree exited $mt_status"
        had_error=1
    fi
    echo
}

echo "# Crystal report — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "base: ${base}@$(git rev-parse --short "$base")"
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
