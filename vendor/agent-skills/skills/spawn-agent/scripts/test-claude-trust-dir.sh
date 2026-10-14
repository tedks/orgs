#!/bin/bash
# Hermetic tests for claude-trust-dir.sh's boundary resolution and predictor.
#
# No network, and the real ~/.claude.json is never read or written: every case
# runs against a throwaway config via CLAUDE_CONFIG_FILE. --verify is NOT
# exercised here (it launches a real Claude); it has its own guard rails and is
# checked by hand.
#
# These exist because the boundary rule has been wrong three times: an inferred
# "nearest ancestor wins", then a port that used --show-toplevel, then one that
# used dirname(--git-common-dir) and broke submodules and bare repos. Each
# shape below is a bug that actually shipped in review.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRUST="$SCRIPT_DIR/claude-trust-dir.sh"
TEST_DIR="$(mktemp -d /tmp/test-trust-dir.XXXXXX)"
trap 'chmod -R u+w "$TEST_DIR" 2>/dev/null || true; rm -rf -- "$TEST_DIR"' EXIT

CFG="$TEST_DIR/config.json"
printf '%s\n' '{"projects":{}}' > "$CFG"

git_q() { git -c user.email=t@e -c user.name=t -c protocol.file.allow=always "$@"; }

fail() { echo "FAIL: $1" >&2; exit 1; }

# git_root_of is the unit under test; source just that function so the tests
# exercise the shipped implementation rather than a copy.
sed -n '/^git_root_of() {/,/^}/p' "$TRUST" > "$TEST_DIR/git_root_of.sh"
# shellcheck source=/dev/null
. "$TEST_DIR/git_root_of.sh"

# --- repo shapes -------------------------------------------------------
git init -q "$TEST_DIR/plain"
git_q -C "$TEST_DIR/plain" commit -q --allow-empty -m x
mkdir -p "$TEST_DIR/plain/deep/deeper"

# Bare repo plus a genuine LINKED WORKTREE -- the layout this fleet actually
# uses, and the one the boundary rule exists for. A `git clone` would produce an
# independent .git and prove nothing about worktrees, so build it with
# `worktree add` off the bare repo.
git init -q "$TEST_DIR/seed"
git_q -C "$TEST_DIR/seed" commit -q --allow-empty -m x
git_q clone -q --bare "$TEST_DIR/seed" "$TEST_DIR/container/.bare" 2>/dev/null
git_q --git-dir="$TEST_DIR/container/.bare" worktree add -q "$TEST_DIR/container/master" 2>/dev/null

git init -q "$TEST_DIR/inner"
git_q -C "$TEST_DIR/inner" commit -q --allow-empty -m x
git init -q "$TEST_DIR/super"
git_q -C "$TEST_DIR/super" submodule add -q "$TEST_DIR/inner" sub 2>/dev/null
git_q -C "$TEST_DIR/super" commit -q -m add

git init -q --bare "$TEST_DIR/bare.git"
mkdir -p "$TEST_DIR/norepo"

expect_root() {
    local dir="$1" want="$2" got
    got="$(git_root_of "$dir")"
    [[ "$got" == "$want" ]] || fail "boundary for $dir: want '$want', got '$got'"
}

expect_root "$TEST_DIR/plain"              "$TEST_DIR/plain"
expect_root "$TEST_DIR/plain/deep/deeper"  "$TEST_DIR/plain"
# The regression that shipped: in a submodule --git-common-dir points into the
# SUPERPROJECT's .git/modules/<name>, whose parent is not an ancestor of the
# submodule at all. Using it made even a direct truthy entry unreachable, so
# --check contradicted --trust on the same directory.
expect_root "$TEST_DIR/super/sub"          "$TEST_DIR/super/sub"
expect_root "$TEST_DIR/super"              "$TEST_DIR/super"
# A bare repo's common dir IS the repo, so dirname() would hand back its parent
# -- a boundary one level too permissive.
expect_root "$TEST_DIR/bare.git"           "$TEST_DIR/bare.git"
# The case the whole boundary rule exists for: a linked worktree resolves to
# the CONTAINER (which holds the shared .bare), not to the worktree itself.
# Getting this wrong is what made ~/Projects/<repo>=true appear not to work.
expect_root "$TEST_DIR/container/master"   "$TEST_DIR/container"
# The CONTAINER itself, which is what you get opening a session at
# ~/Projects/<project>/ -- CLAUDE.md says that is normal. It holds a .git FILE
# pointing at .bare, so git reports is-bare=true with a common dir of .bare, a
# DESCENDANT of the target. A boundary below the target makes resolve() bail
# before reading the entry, so --check contradicted --trust here. Unbounded is
# correct: git offers no work tree to bound against.
printf 'gitdir: %s\n' "$TEST_DIR/container/.bare" > "$TEST_DIR/container/.git"
expect_root "$TEST_DIR/container"          ""
expect_root "$TEST_DIR/norepo"             ""

# "git is missing" must not be mistaken for "not in a repo", which would
# silently restore an unbounded walk.
[[ "$(PATH=/nonexistent git_root_of "$TEST_DIR/plain")" == "?" ]] \
    || fail "git-absent must yield '?', not an unbounded walk"

# A git that is PRESENT but broken cannot answer either, and `command -v` does
# not catch that -- so the probe is `git --version`, not mere existence.
mkdir -p "$TEST_DIR/brokenbin"
printf '#!/bin/sh\nexit 127\n' > "$TEST_DIR/brokenbin/git"
chmod +x "$TEST_DIR/brokenbin/git"
[[ "$(PATH="$TEST_DIR/brokenbin:$PATH" git_root_of "$TEST_DIR/plain")" == "?" ]] \
    || fail "a broken git must yield '?', not a silent unbounded walk"

# And a git that answers --version fine but cannot inspect THIS repo -- dubious
# ownership, a permissions failure, a wrapper. That failure is not "not a repo",
# so it must not silently unbound the walk either.
mkdir -p "$TEST_DIR/partialbin"
cat > "$TEST_DIR/partialbin/git" <<'STUB'
#!/bin/sh
case "$1" in
  --version) echo "git version 2.99.0"; exit 0 ;;
  *) echo "fatal: detected dubious ownership in repository" >&2; exit 128 ;;
esac
STUB
chmod +x "$TEST_DIR/partialbin/git"
[[ "$(PATH="$TEST_DIR/partialbin:$PATH" git_root_of "$TEST_DIR/plain")" == "?" ]] \
    || fail "a git that fails rev-parse for a non-'not a repository' reason must yield '?'"

# ...but a genuine "not a git repository" must still mean unbounded, not "?".
mkdir -p "$TEST_DIR/norepobin"
cat > "$TEST_DIR/norepobin/git" <<'STUB'
#!/bin/sh
case "$1" in
  --version) echo "git version 2.99.0"; exit 0 ;;
  *) echo "fatal: not a git repository (or any of the parent directories): .git" >&2; exit 128 ;;
esac
STUB
chmod +x "$TEST_DIR/norepobin/git"
[[ -z "$(PATH="$TEST_DIR/norepobin:$PATH" git_root_of "$TEST_DIR/plain")" ]] \
    || fail "a genuine not-a-repository must yield unbounded, not '?'"

# git_root_of must survive a command substitution that INHERITS errexit.
#
# Default bash does not propagate set -e out of a command substitution, so a
# bare `common=$(failing-rev-parse)` runs the classifier normally and any test
# omitting POSIX mode passes on the broken form -- an earlier version of this
# test did exactly that and pinned nothing. POSIX mode (and inherit_errexit)
# DO propagate it, aborting before the classifier and killing the prediction.
out=$(POSIXLY_CORRECT=1 CLAUDE_CONFIG_FILE="$CFG" "$TRUST" --check "$TEST_DIR/norepo" 2>&1) \
    || fail "--check aborts under POSIX mode on a non-repo (unshielded substitution)"
printf '%s\n' "$out" | grep -qE '^  (trusted|PROMPTS)' \
    || fail "--check under POSIX mode produced no prediction"

# ...and the same for a directory git can see, so the success path is covered too.
POSIXLY_CORRECT=1 CLAUDE_CONFIG_FILE="$CFG" "$TRUST" --check "$TEST_DIR/plain" >/dev/null 2>&1 \
    || fail "--check aborts under POSIX mode on a real repo"

# POSIX mode turns inherit_errexit ON, so these are two routes into ONE
# mechanism rather than two mechanisms. Pinned separately anyway: BASHOPTS is
# reachable from the environment independently of POSIX mode, and a future bash
# could decouple them. Note the `env` prefix is required -- a bare
# `BASHOPTS=... cmd` trips bash's readonly guard and never reaches the child,
# which silently turns this assertion into a no-op.
env BASHOPTS=inherit_errexit CLAUDE_CONFIG_FILE="$CFG" "$TRUST" --check "$TEST_DIR/norepo" >/dev/null 2>&1 \
    || fail "--check aborts under inherit_errexit on a non-repo"
env BASHOPTS=inherit_errexit POSIXLY_CORRECT=1 CLAUDE_CONFIG_FILE="$CFG" \
    "$TRUST" --check "$TEST_DIR/norepo" >/dev/null 2>&1 \
    || fail "--check aborts under inherit_errexit + POSIX mode"

# No stderr-capture temp file may be left behind on the failure path.
# Scoped to a private TMPDIR rather than counting /tmp: this machine runs many
# concurrent sessions, so a global before/after count races against unrelated
# mktemp activity (false failure) AND would miss a leak from an implementation
# that honours a different TMPDIR (false pass).
_leakdir="$TEST_DIR/tmpprobe"
mkdir -p "$_leakdir"
TMPDIR="$_leakdir" CLAUDE_CONFIG_FILE="$CFG" "$TRUST" --check "$TEST_DIR/norepo" >/dev/null 2>&1 || true
[[ -z "$(ls -A "$_leakdir")" ]] \
    || fail "--check leaked a temp file on the non-repo path: $(ls -A "$_leakdir")"

# --- predictor ---------------------------------------------------------
check() { CLAUDE_CONFIG_FILE="$CFG" "$TRUST" --check "$@" 2>&1; }
grant() { CLAUDE_CONFIG_FILE="$CFG" "$TRUST" "$@" >/dev/null 2>&1; }

# A false entry does NOT veto: it is skipped and the walk continues UPWARD.
# The false entry must sit BETWEEN the target and the truthy one, or the walker
# never reaches it and the test would pass even against an implementation where
# false vetoes -- which is what the first cut of this test did.
#   deeper (no entry) -> deep (FALSE, must be skipped) -> plain (TRUE, grants)
python3 - "$CFG" "$TEST_DIR" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1])); root = sys.argv[2]
cfg["projects"] = {
    f"{root}/plain/deep": {"hasTrustDialogAccepted": False},
    f"{root}/plain":      {"hasTrustDialogAccepted": True},
}
json.dump(cfg, open(sys.argv[1], "w"))
PY
check "$TEST_DIR/plain/deep/deeper" | grep -q '^  trusted' \
    || fail "a false entry between target and grant must be skipped, not veto"

# A truthy entry ABOVE the boundary must not apply.
python3 - "$CFG" "$TEST_DIR" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1])); root = sys.argv[2]
cfg["projects"] = {root: {"hasTrustDialogAccepted": True}}
json.dump(cfg, open(sys.argv[1], "w"))
PY
check "$TEST_DIR/plain" | grep -q '^  PROMPTS' \
    || fail "a truthy entry above the project boundary must not grant"
# ...but with no repo there is no boundary, so the same entry does apply.
check "$TEST_DIR/norepo" | grep -q '^  trusted' \
    || fail "outside a repo the walk is unbounded and should reach the ancestor"

# --check must never contradict --trust on the same directory.
printf '%s\n' '{"projects":{}}' > "$CFG"
check "$TEST_DIR/super/sub" | grep -q '^  PROMPTS' || fail "submodule should start untrusted"
grant "$TEST_DIR/super/sub"
check "$TEST_DIR/super/sub" | grep -q '^  trusted' \
    || fail "--check contradicts --trust on a submodule (the round-2 regression)"

# Granting is idempotent and reports it.
CLAUDE_CONFIG_FILE="$CFG" "$TRUST" "$TEST_DIR/super/sub" 2>&1 | grep -q 'already trusted' \
    || fail "second grant should report already-trusted"

echo 'PASS: boundary resolution across repo shapes, and predictor/grant agreement'
