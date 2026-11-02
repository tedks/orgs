#!/usr/bin/env bash
# Publish selected files from a caller-owned tree without changing the shared checkout.
set -euo pipefail

repo=
source_root=
message=
index_builder=
session_id=
event_id=
allow_path=0
paths=()
while (($#)); do
    case $1 in
        --repo|--source-root|--build-index|--session-id|--event-id|-m)
            (($# >= 2)) || { echo "missing value for $1" >&2; exit 2; }
            case $1 in
                --repo) repo=$2 ;;
                --source-root) source_root=$2 ;;
                --build-index) index_builder=$2 ;;
                --session-id) session_id=$2 ;;
                --event-id) event_id=$2 ;;
                -m) message=$2 ;;
            esac
            shift 2 ;;
        --allow-path) allow_path=1; shift ;;
        --) shift; paths+=("$@"); break ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) paths+=("$1"); shift ;;
    esac
done
[[ -n $repo && -n $message && ${#paths[@]} -gt 0 ]] || {
    echo 'usage: offduty-push.sh --repo REPO [--source-root DIR] [--allow-path] FILE... -m MESSAGE' >&2
    exit 2
}
[[ -n $source_root ]] || source_root=$repo
[[ -z $index_builder || -x $index_builder ]] || { echo 'index builder unavailable' >&2; exit 2; }
[[ -z $session_id && -z $event_id || -n $index_builder && -n $session_id && -n $event_id ]] || {
    echo 'session identity requires an index builder and both identifiers' >&2; exit 2;
}
repo=$(realpath -- "$repo")
source_root=$(realpath -- "$source_root")
[[ -d $source_root ]] || { echo 'source root missing' >&2; exit 2; }
[[ $(git -C "$repo" rev-parse --is-inside-work-tree) == true ]] || {
    echo 'repo must be a working tree' >&2; exit 2;
}
for path in "${paths[@]}"; do
    [[ $path != /* && $path != *//* && $path != */ && $path != .* && $path != */.* && $path != *'/../'* && $path != *'/./'* && $path != *$'\n'* && $path != *$'\r'* && $path != *$'\t'* ]] || {
        echo "unsafe path: $path" >&2; exit 2;
    }
    if (( ! allow_path )); then
        case $path in waiting/*|receipts/*|lane-notes/*|writing/*) ;; *) echo "path not allowed: $path" >&2; exit 2 ;; esac
    fi
    source_file=$source_root/$path
    [[ -f $source_file && ! -L $source_file ]] || { echo "source is not a regular file: $path" >&2; exit 2; }
    canonical=$(realpath -- "$source_file")
    [[ $canonical == "$source_root/"* ]] || { echo "source escapes root: $path" >&2; exit 2; }
done

scratch_base=${XDG_RUNTIME_DIR:-${TMPDIR:-${XDG_CACHE_HOME:-/tmp}}}
[[ -d $scratch_base && -w $scratch_base ]] || { echo 'scratch directory unavailable' >&2; exit 2; }
scratch=$(mktemp -d "$scratch_base/offduty-push.XXXXXXXX")
worktree=$scratch/worktree
fetched_ref=refs/offduty-push/$$-$RANDOM-$RANDOM
cleanup() {
    status=$?
    if [[ -e $worktree/.git ]]; then
        if ! git -C "$repo" worktree remove --force "$worktree" >&2; then
            echo "temporary worktree cleanup failed: $worktree" >&2
            exit 1
        fi
    fi
    git -C "$repo" update-ref -d "$fetched_ref" 2>/dev/null || true
    rm -rf -- "$scratch"  # This invocation created this exact mktemp directory.
    exit "$status"
}
trap cleanup EXIT

for attempt in 1 2 3; do
    git -C "$repo" fetch --quiet origin "+refs/heads/master:$fetched_ref"
    git -C "$repo" worktree add --quiet --detach "$worktree" "$fetched_ref"
    base=$(git -C "$worktree" rev-parse HEAD)
    for path in "${paths[@]}"; do
        # An existing remote tree must not redirect a copy through a symlink.
        part=$worktree
        IFS=/ read -r -a components <<< "$path"
        for component in "${components[@]}"; do
            part=$part/$component
            [[ ! -L $part ]] || { echo "destination symlink: $path" >&2; exit 2; }
        done
        mkdir -p -- "$(dirname -- "$worktree/$path")"
        cp -- "$source_root/$path" "$worktree/$path"
    done
    if [[ -n $index_builder ]]; then
        "$index_builder" "$worktree" "$session_id" "$event_id"
        git -C "$worktree" add -- waiting/INDEX.md
    fi
    for path in "${paths[@]}"; do
        # Preserve the source bytes even if the remote tree configures a clean filter.
        oid=$(git -C "$worktree" hash-object -w --no-filters -- "$path")
        mode=100644
        [[ ! -x $source_root/$path ]] || mode=100755
        git -C "$worktree" update-index --add --cacheinfo "$mode" "$oid" "$path"
    done
    if git -C "$worktree" diff --cached --quiet; then
        printf '%s\n' "$base"
        exit 0
    fi
    git -C "$worktree" commit --quiet -m "$message"
    commit=$(git -C "$worktree" rev-parse HEAD)
    if git -C "$worktree" push --quiet origin HEAD:master; then
        printf '%s\n' "$commit"
        exit 0
    fi
    git -C "$repo" fetch --quiet origin "+refs/heads/master:$fetched_ref"
    current=$(git -C "$repo" rev-parse "$fetched_ref")
    [[ $current != "$base" ]] || { echo 'push failed without a remote advance' >&2; exit 1; }
    git -C "$repo" worktree remove --force "$worktree"
done
echo 'push failed after three remote advances' >&2
exit 1
