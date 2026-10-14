#!/bin/bash
# claude-trust-dir.sh - Inspect and set Claude Code's workspace trust.
#
# Claude Code shows a workspace trust dialog the first time it starts in a
# directory whose trust it cannot resolve. There is no CLI flag and no
# settings.json key to pre-grant it (checked against `claude --help` and the
# settings surface as of 2.1.259 -- `trustedNetworkDirectories` is unrelated,
# it guards /net automounts and UNC paths). The only store is
#
#   projects."<absolute path>".hasTrustDialogAccepted
#
# in ~/.claude.json, which is Claude Code's own state file rather than a
# documented config surface. Treat the shape as version-dependent.
#
# HOW TRUST RESOLVES. `resolve()` below is a port of the walker extracted from
# claude.exe v2.1.261 (minified `AB`), not a rule inferred from behaviour --
# an earlier inferred rule ("nearest ancestor wins") was wrong in both
# directions and PR #111's council caught it. The real rule:
#
#   * only a TRUTHY hasTrustDialogAccepted grants. A `false` entry does NOT
#     veto: it is skipped and the walk continues upward. Note `false` is also
#     what Claude WRITES BY DEFAULT for any project it opens -- observed on a
#     directory it trusted by inheritance without ever showing the dialog. So a
#     false entry is NOT evidence that anyone declined anything, and must not be
#     reported as one.
#   * the walk is BOUNDED by the project container -- the directory holding the
#     git common dir, shared by every worktree of a repo. A truthy entry above
#     that boundary never applies, so ~/Projects=true does NOT blanket-trust a
#     repo beneath it. Outside a repo the walk runs to the filesystem root.
#
# `--verify` launches a real Claude, which RECORDS THE PROJECT in the config as
# a side effect (a new entry, with hasTrustDialogAccepted false by default). It
# never answers the dialog and never grants trust, but it is not read-only.
#
# This is an undocumented internal and WILL drift. `--verify` is the tripwire:
# it launches Claude in a throwaway tmux window, observes whether the dialog
# actually appears, and reports any disagreement with the prediction. Run it
# after a Claude upgrade. It never answers the dialog.
#
# Usage:
#   claude-trust-dir.sh --list                     show every stored entry
#   claude-trust-dir.sh --check <dir>...           predict trust, set nothing
#   claude-trust-dir.sh --verify <dir>...          check the prediction against reality
#   claude-trust-dir.sh [--dry-run] <dir>...       mark directories trusted
#
# Granting trust is an operator decision. Nothing here runs automatically:
# agent-spawn.sh calls it only behind an explicit --trust flag.
#
# CONCURRENCY: every running Claude Code instance writes this file, using its
# own lockfile protocol (<config>.lock) that flock does not participate in.
# So the risk runs in BOTH directions: a live session can flush its copy over
# our change, and we could clobber a setting it wrote after we read.
#
# Atomic rename prevents a torn file; it does not prevent a lost update. To
# stop the second direction being SILENT, the write re-stats the file
# immediately beforehand and refuses to replace it if it changed since we read
# it -- turning data loss into a loud retry. The check hashes the file's bytes,
# so it cannot be fooled by a same-size rewrite. A microsecond-wide window
# remains between that check and the rename. Prefer running with few sessions
# live.

set -euo pipefail

# Claude resolves its config as $CLAUDE_CONFIG_DIR/.claude.json, falling back
# to $HOME. Honouring the same override matters: with an alternate profile in
# play, defaulting to $HOME writes a store the launched process never reads, so
# --trust would report success and the child would still prompt.
CONFIG="${CLAUDE_CONFIG_FILE:-${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json}"
LOCKFILE="${CONFIG}.trust-lock"

usage() {
    sed -n '/^# Usage:/,/^#$/p' "${BASH_SOURCE[0]}" | sed 's/^# \?//' >&2
    exit 1
}

# Canonicalise to the physical path. A tmux window opened with `new-window -c`
# gives the agent that directory as its cwd, and a process's cwd is always
# physical, so symlinked paths must be resolved the same way here or the key
# we write will never be the key Claude Code looks up.
canonicalise() {
    local d="$1"
    if [[ ! -d "$d" ]]; then
        echo "Error: not a directory: $d" >&2
        return 1
    fi
    (CDPATH='' cd -P -- "$d" && pwd -P)
}

mode="set"
dry_run=0
dirs=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --list)    mode="list"; shift ;;
        --check)   mode="check"; shift ;;
        --verify)  mode="verify"; shift ;;
        --dry-run) dry_run=1; shift ;;
        -h|--help) usage ;;
        --) shift; while [[ $# -gt 0 ]]; do dirs+=("$1"); shift; done ;;
        -*) echo "Unknown option: $1" >&2; usage ;;
        *)  dirs+=("$1"); shift ;;
    esac
done

if [[ ! -f "$CONFIG" ]]; then
    echo "Error: $CONFIG does not exist." >&2
    echo "  Run Claude Code once so it creates its state file, then retry." >&2
    echo "  This script deliberately does not synthesise one: guessing the" >&2
    echo "  shape of another program's state file is how you corrupt it." >&2
    exit 1
fi

if [[ "$mode" == "list" ]]; then
    python3 - "$CONFIG" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
projects = cfg.get("projects", {})
rows = [(p, v.get("hasTrustDialogAccepted"))
        for p, v in projects.items()
        if isinstance(v, dict) and "hasTrustDialogAccepted" in v]
for path, trusted in sorted(rows):
    # NOT "DECLINED": false is what Claude writes by default for every project
    # it opens, so the overwhelming majority of these are defaults rather than
    # refusals. Calling them declines sends an operator hunting for a stray
    # refusal through dozens of false alarms -- and may prompt needless --trust
    # writes to a live config.
    print(f"{'trusted' if trusted else 'no grant':>8}  {path}")
print(f"\n{len(rows)} entries. Only a truthy entry grants; 'no grant' means false or"
      "\nunset, which is Claude's default and NOT a decline. The search also stops"
      "\nat the project root -- use --check to resolve a specific directory.")
PY
    exit 0
fi

if [[ ${#dirs[@]} -eq 0 ]]; then
    usage
fi

canonical=()
for d in "${dirs[@]}"; do
    canonical+=("$(canonicalise "$d")")
done

# The walk's boundary. NOT `--show-toplevel`: in a bare-repo-plus-worktrees
# layout that returns the individual worktree, and --verify proved that wrong
# (it predicted PROMPTS for a directory Claude actually trusts). The boundary
# is the directory holding the git COMMON dir -- the project container, shared
# by every worktree -- which explains both observed cases. Empty means "not in
# a repo", i.e. an unbounded walk.
git_root_of() {
    local target="$1" common boundary toplevel
    # "git is missing" must never be mistaken for "not in a repo": the latter is
    # legitimately an unbounded walk, the former is us not knowing, and silently
    # unbounding would restore the blanket-trust semantics this predictor exists
    # to correct. Callers get "?" and must refuse to claim an answer.
    # `command -v` only catches git being ABSENT. A git that is present but
    # broken (bad install, unreadable objects) also cannot answer, and must not
    # be mistaken for "not in a repo" -- that reading silently unbounds the walk
    # and restores the blanket-trust semantics this predictor exists to correct.
    git --version >/dev/null 2>&1 || { printf '?\n'; return 0; }
    # A rev-parse failure is ambiguous: "not a git repository" legitimately means
    # an unbounded walk, but dubious-ownership rejections, permission errors and
    # wrapper failures ALSO fail here -- and reading those as "not a repo" would
    # silently unbound the walk while Claude, running as a user git does trust,
    # finds the repo and bounds normally. LC_ALL=C so the message is stable.
    # The assignment is shielded with `|| status=$?` rather than left bare. A bare
    # `var=$(failing-cmd)` aborts the caller under `set -e`; today the only call
    # site wraps this in $( ) inside an array append, which happens to suppress
    # that -- but depending on a caller's syntax for correctness is exactly what
    # a later refactor breaks. Verified both ways in the suite.
    #
    # Stderr is re-fetched on the failure path instead of being captured to a
    # temp file, so there is nothing to leak if a signal lands mid-probe.
    local status=0 errout
    common=$(cd "$target" 2>/dev/null && LC_ALL=C git rev-parse --git-common-dir 2>/dev/null) \
        || status=$?
    if (( status != 0 )); then
        errout=$( { cd "$target" && LC_ALL=C git rev-parse --git-common-dir; } 2>&1 >/dev/null ) || true
        case "$errout" in
            *"not a git repository"*) return 0 ;;      # genuinely outside a repo
            *)                        printf '?\n'; return 0 ;;  # cannot tell; do not guess
        esac
    fi
    [[ -n "$common" ]] || return 0
    # --git-common-dir may come back relative to the directory it resolved in.
    common=$(cd "$target" && cd "$common" 2>/dev/null && pwd -P) || return 0

    if [[ "$(cd "$target" && git rev-parse --is-bare-repository 2>/dev/null)" == "true" ]]; then
        # A bare repo's common dir IS the repo, so dirname() would hand back its
        # parent -- one level too permissive.
        boundary="$common"
    else
        boundary=$(dirname "$common")
    fi

    # ONE containment gate for both derivations. A candidate that does not
    # contain the target is unusable however it was derived, because resolve()
    # tests the boundary before consulting the entry -- so such a boundary makes
    # even a direct truthy entry unreachable, and --check then contradicts
    # --trust on the same directory. Two shapes hit this:
    #
    #   submodule  -- common dir is the SUPERPROJECT's .git/modules/<name>,
    #                 whose parent is outside the submodule entirely.
    #   bare-repo container (this fleet's layout) -- the container holds a .git
    #                 FILE pointing at .bare, so git reports is-bare=true and a
    #                 common dir of <container>/.bare, a DESCENDANT of the
    #                 target. Gating only the dirname path missed this one.
    if [[ "$target" == "$boundary" || "$target" == "$boundary"/* ]]; then
        printf '%s\n' "$boundary"
        return 0
    fi
    toplevel=$(cd "$target" && git rev-parse --show-toplevel 2>/dev/null) || true
    if [[ -n "$toplevel" && ( "$target" == "$toplevel" || "$target" == "$toplevel"/* ) ]]; then
        printf '%s\n' "$toplevel"
        return 0
    fi
    # Nothing defensible: unbounded rather than wrong.
    return 0
}

predict() {
    local pairs=()
    local d
    for d in "$@"; do
        pairs+=("$d" "$(git_root_of "$d")")
    done
    python3 - "$CONFIG" "${pairs[@]}" <<'PY'
import json, sys, os

cfg = json.load(open(sys.argv[1]))
projects = cfg.get("projects", {})

def resolve(start, boundary):
    """Port of `AB` from claude.exe v2.1.261.

    Only truthy entries grant. `boundary` (the git root, or None) stops the
    walk. Returns (trusted, granting_path_or_None)."""
    cur = start
    while True:
        if boundary is not None and cur != boundary and            not cur.startswith(boundary.rstrip("/") + "/"):
            return False, None
        entry = projects.get(cur)
        if isinstance(entry, dict) and entry.get("hasTrustDialogAccepted"):
            return True, cur
        if cur == boundary:
            return False, None
        parent = os.path.dirname(cur)
        if parent == cur:
            return False, None
        cur = parent

args = sys.argv[2:]
for path, root in zip(args[0::2], args[1::2]):
    if root == "?":
        print(f"  UNKNOWN   {path}\n            (git is not available, so the boundary cannot be"
              f" determined;\n             refusing to guess -- the answer depends on it)")
        continue
    boundary = root or None
    trusted, granter = resolve(path, boundary)
    # An empty boundary means "no usable containing project root" -- either not
    # a repo at all, or a repo shape (a bare container) that offers none. Do not
    # claim the former; we only know the walk is unbounded.
    where = (f"project root {boundary}" if boundary
             else "/ (no containing project root; the walk is unbounded)")
    if trusted:
        via = "own entry" if granter == path else f"granted by {granter}"
        print(f"  trusted   {path}\n            ({via}; {where})")
    else:
        blocked = ""
        entry = projects.get(path)
        if isinstance(entry, dict) and entry.get("hasTrustDialogAccepted") is False:
            blocked = "; its own entry is false, which does NOT veto -- it is simply not a grant"
        print(f"  PROMPTS   {path}\n            (no truthy entry at or under {where}{blocked})")
print("\nPredicted from a port of Claude's internal resolver; run --verify to confirm.")
PY
}

if [[ "$mode" == "check" ]]; then
    predict "${canonical[@]}"
    exit 0
fi

if [[ "$mode" == "verify" ]]; then
    # The tripwire. Launch Claude in a throwaway tmux window, watch for the
    # dialog or the composer, kill it. No key is ever sent, so this cannot
    # answer the dialog or alter stored trust.
    source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude-pane-detect.sh"
    command -v tmux >/dev/null || { echo "Error: --verify needs tmux." >&2; exit 1; }
    command -v claude >/dev/null || { echo "Error: --verify needs claude on PATH." >&2; exit 1; }
    # The prediction would read $CONFIG while the launched Claude reads its own
    # profile, so any disagreement would be an artefact of the split rather than
    # real drift -- and it would be reported as "the internal has changed".
    if [[ -n "${CLAUDE_CONFIG_FILE:-}" ]]; then
        echo "Error: --verify is meaningless with CLAUDE_CONFIG_FILE set." >&2
        echo "  Prediction would read $CONFIG; the launched Claude would not." >&2
        echo "  Unset it (CLAUDE_CONFIG_DIR is honoured by both and is fine)." >&2
        exit 1
    fi

    predict "${canonical[@]}"
    echo
    echo "Observed:"
    sock="/tmp/claude-trust-verify.$$"
    # kill-server does not unlink the socket path; without the rm these
    # accumulate one per run and a later reuse fails with "server exited
    # unexpectedly".
    trap 'tmux -S "$sock" kill-server 2>/dev/null || true; rm -f "$sock"' EXIT
    # Three counters, not one flag. "Nothing disagreed" is NOT the same as
    # "the prediction was confirmed": a run in which every directory was
    # unverifiable must not report success, or the tripwire is disarmed while
    # claiming to be armed.
    mismatch=0
    verified=0
    unverifiable=0
    for d in "${canonical[@]}"; do
        pred=$(predict "$d")
        # An UNKNOWN prediction is not a prediction of PROMPTS. Verifying
        # against it would manufacture a MISMATCH out of a question we declined
        # to answer.
        if printf '%s\n' "$pred" | grep -q '^  UNKNOWN'; then
            echo "  SKIPPED   $d: no prediction was made (git unavailable), nothing to verify"
            unverifiable=$((unverifiable + 1))
            continue
        fi
        expected="PROMPTS"
        printf '%s\n' "$pred" | grep -q '^  trusted' && expected="trusted"
        # Fixed wide geometry: claude_trust_dialog_specific matches phrases long
        # enough to wrap on a narrow pane, and here we own the pane, so we simply
        # render wide enough that they cannot.
        tmux -S "$sock" new-session -d -x 200 -y 50 -s v -n w -c "$d" claude 2>/dev/null || {
            echo "  ERROR     $d (could not start a tmux window)"
            unverifiable=$((unverifiable + 1)); continue; }
        observed="timeout"
        for _ in $(seq 1 120); do
            pane=$(tmux -S "$sock" capture-pane -p -t v:w 2>/dev/null) || { observed="exited"; break; }
            # The trust dialog specifically -- the broad detector also matches
            # the bypass-permissions dialog, which would be reported as drift.
            if claude_trust_dialog_specific "$pane"; then observed="PROMPTS"; break; fi
            if claude_trust_modal_active "$pane"; then observed="other-dialog"; break; fi
            if claude_composer_ready "$pane"; then observed="trusted"; break; fi
            sleep 0.25
        done
        tmux -S "$sock" kill-session -t v 2>/dev/null || true
        case "$observed" in
            other-dialog)
                # Some other modal (bypass-permissions, an update chooser) got
                # there first. Not evidence either way about trust resolution.
                echo "  INCONCLUSIVE $d: a non-trust dialog is on screen; cannot judge"
                unverifiable=$((unverifiable + 1))
                ;;
            timeout|exited)
                # Claude never reached a state we can classify. That is a
                # failure to observe, not evidence that the prediction is wrong.
                echo "  INCONCLUSIVE $d: claude $observed before showing a dialog or composer"
                unverifiable=$((unverifiable + 1))
                ;;
            "$expected")
                echo "  agrees    $d ($observed)"
                verified=$((verified + 1))
                ;;
            *)
                echo "  MISMATCH  $d: predicted $expected, observed $observed"
                mismatch=$((mismatch + 1))
                ;;
        esac
    done
    echo
    if [[ "$mismatch" -ne 0 ]]; then
        echo "The prediction no longer matches this Claude build. resolve() is a port of" >&2
        echo "an internal that has evidently changed; re-extract it before trusting --check." >&2
        exit 2
    fi
    if [[ "$verified" -eq 0 ]]; then
        echo "Verified NOTHING: all $unverifiable target(s) were unverifiable." >&2
        echo "  This is not a pass. The tripwire made no observation it could compare," >&2
        echo "  so --check remains unconfirmed on this build." >&2
        exit 3
    fi
    if [[ "$unverifiable" -ne 0 ]]; then
        echo "Partial: $verified confirmed, $unverifiable unverifiable, 0 disagreements." >&2
        echo "  The confirmed ones agree, but this run did not cover everything asked." >&2
        exit 3
    fi
    echo "Prediction matches observed behaviour on this build ($verified confirmed)."
    exit 0
fi

# --- set ---------------------------------------------------------------
# flock serialises concurrent runs of this script; the temp-file rename makes
# the replacement atomic for everyone else.
exec 9>"$LOCKFILE"
if ! flock -w 10 9; then
    echo "Error: could not acquire $LOCKFILE within 10s." >&2
    exit 1
fi

live=$(pgrep -c -u "$(id -u)" -x claude 2>/dev/null || true)
if [[ "${live:-0}" -gt 0 && "$dry_run" -eq 0 ]]; then
    echo "Warning: $live Claude Code process(es) are running. Each holds" >&2
    echo "  $CONFIG in memory and may flush over this change on exit." >&2
    echo "  Re-check with --list afterwards." >&2
fi

DRY_RUN="$dry_run" python3 - "$CONFIG" "${canonical[@]}" <<'PY'
import hashlib, json, os, sys, tempfile

config_path = sys.argv[1]
targets = sys.argv[2:]
dry_run = os.environ.get("DRY_RUN") == "1"

# Fingerprint the file we are about to base our edit on, so a concurrent
# writer between here and the rename is detected rather than silently undone.
# Content hash, not (mtime, size): a same-size rewrite on a coarse-timestamp
# filesystem can reproduce both, and the whole point of this check is to be
# unable to miss a concurrent write.
def fingerprint(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

before = fingerprint(config_path)

with open(config_path) as fh:
    cfg = json.load(fh)

projects = cfg.setdefault("projects", {})
changed = []

for path in targets:
    entry = projects.get(path)
    if not isinstance(entry, dict):
        # A fresh entry carrying only this key is the same shape Claude Code
        # writes for a directory it has only ever asked about; it fills in the
        # rest on first use.
        entry = {}
        projects[path] = entry
    previous = entry.get("hasTrustDialogAccepted")
    if previous is True:
        print(f"  already trusted  {path}")
        continue
    entry["hasTrustDialogAccepted"] = True
    changed.append(path)
    print(f"  {'would trust' if dry_run else 'trusted'}      {path}"
          + ("  (previous value was false)" if previous is False else ""))

if not changed:
    print("\nNothing to change.")
    sys.exit(0)

if dry_run:
    print(f"\n--dry-run: {len(changed)} entr{'y' if len(changed)==1 else 'ies'} left unwritten.")
    sys.exit(0)

# Same directory, so the rename is atomic on the same filesystem. Preserve
# the original mode rather than inheriting mkstemp's 0600 by accident.
directory = os.path.dirname(config_path) or "."
mode = os.stat(config_path).st_mode & 0o777
fd, tmp = tempfile.mkstemp(dir=directory, prefix=".claude.json.trust.")
try:
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, mode)
    # Refuse rather than clobber. Everything a live Claude wrote since we read
    # is in the file and absent from our copy; replacing it would revert it
    # silently while we report success.
    if fingerprint(config_path) != before:
        os.unlink(tmp)
        sys.exit(
            "\nAborted: %s changed while this ran (a live Claude Code session "
            "wrote to it).\n  Nothing was written -- replacing it would have "
            "silently reverted that change.\n  Re-run; it is idempotent." % config_path
        )
    os.replace(tmp, config_path)
except BaseException:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise

print(f"\nWrote {len(changed)} entr{'y' if len(changed)==1 else 'ies'} to {config_path}.")
PY
