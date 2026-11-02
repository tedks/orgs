#!/usr/bin/env bash
# shellcheck disable=SC2329,SC2016
# where against temp git repos in a private HOME and XDG_CACHE_HOME.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHERE="$HERE/where"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
export HOME="$WORK/home"
export XDG_CACHE_HOME="$WORK/cache"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
mkdir -p "$HOME/Projects"
fail=0
check() { local what="$1"; shift; if "$@"; then echo "ok   $what"; else echo "FAIL $what"; fail=1; fi; }
not() { ! "$@"; }

# Bare-repo + worktrees layout: $HOME/Projects/proj/{.git,master,feat}
SEED="$WORK/seed"
git init -q -b master "$SEED"
mkdir -p "$SEED/src/core" "$SEED/docs"
echo 'print(1)' > "$SEED/src/core/a.py"
echo 'hello' > "$SEED/docs/guide.md"
head -c 5000 /dev/zero > "$SEED/src/blob.bin"
cat > "$SEED/AGENTS.md" <<'DOC'
# Agent Instructions

## Project structure

- `src/` -- the code
- `docs/` -- the docs

## Environment

Not part of the structure section.
DOC
git -C "$SEED" add -A
git -C "$SEED" commit -q -m seed
PROJ="$HOME/Projects/proj"
mkdir -p "$PROJ"
git clone -q --bare "$SEED" "$PROJ/.git"
git -C "$PROJ/.git" worktree add -q "$PROJ/master" master
git -C "$PROJ/.git" worktree add -q -b feat "$PROJ/feat" master
# Untracked noise that must not appear in the map.
mkdir -p "$PROJ/master/node_modules/dep"
echo x > "$PROJ/master/node_modules/dep/index.js"

cd "$PROJ/master" || exit 1
"$WHERE" > "$WORK/out" 2> "$WORK/err"
check "names the project root" grep -q "root: $PROJ\$" "$WORK/out"
check "lists worktrees of a bare layout" grep -q "$PROJ/feat" "$WORK/out"
check "tree shows top-level dirs with sizes" grep -Eq '^ *src/ +[0-9.]+ ?[KMB]' "$WORK/out"
check "tree goes to depth 2" grep -q 'core/' "$WORK/out"
check "tree stops at depth 2" not grep -q 'a\.py' "$WORK/out"
check "untracked node_modules is not mapped" not grep -q node_modules "$WORK/out"
check "prints the Project structure section verbatim" grep -q '^- `docs/` -- the docs' "$WORK/out"
check "stops the section at the next heading" not grep -q 'Not part of the structure' "$WORK/out"

# Cache
CACHEFILE_COUNT=$(find "$XDG_CACHE_HOME/where" -type f | wc -l)
check "writes one cache file under XDG_CACHE_HOME" test "$CACHEFILE_COUNT" -eq 1
"$WHERE" > "$WORK/out2" 2> "$WORK/err2"
check "second run is a cache hit" grep -qi 'cached' "$WORK/err2"
check "cache hit prints the same map" cmp -s "$WORK/out" "$WORK/out2"
"$WHERE" --refresh > /dev/null 2> "$WORK/err3"
check "--refresh bypasses the cache" not grep -qi 'cached' "$WORK/err3"
"$WHERE" --max-age 0 > /dev/null 2> "$WORK/err4"
check "an expired cache is rebuilt" not grep -qi 'cached' "$WORK/err4"

echo more > docs/more.md
git add docs/more.md
git commit -q -m more
"$WHERE" > "$WORK/out5" 2> "$WORK/err5"
check "a new HEAD invalidates the cache" not grep -qi 'cached' "$WORK/err5"
check "the rebuilt map sees the new file's directory size" grep -q 'docs/' "$WORK/out5"

# Path argument from an unrelated cwd
cd "$WORK" || exit 1
"$WHERE" "$PROJ/feat" > "$WORK/out6" 2> /dev/null
check "path argument selects that worktree" grep -q "worktree: $PROJ/feat" "$WORK/out6"

# Bare-layout root: worktrees listed, tree skipped with a note
"$WHERE" "$PROJ" > "$WORK/out7" 2> /dev/null
check "project root without a worktree still lists worktrees" grep -q "$PROJ/master" "$WORK/out7"
check "project root without a worktree says why there is no tree" grep -qi 'no worktree' "$WORK/out7"

# Missing AGENTS.md section
PLAIN="$HOME/Projects/plain"
git init -q -b master "$PLAIN"
echo x > "$PLAIN/f.txt"
git -C "$PLAIN" add -A
git -C "$PLAIN" commit -q -m init
"$WHERE" "$PLAIN" > "$WORK/out8" 2> /dev/null
check "plain repo is mapped" grep -q "root: $PLAIN\$" "$WORK/out8"
check "missing AGENTS.md is a one-line note" grep -q 'no AGENTS.md' "$WORK/out8"
printf '# Hi\n\n## Other\n\ntext\n' > "$PLAIN/AGENTS.md"
"$WHERE" --refresh "$PLAIN" > "$WORK/out9" 2> /dev/null
check "AGENTS.md without the section is a one-line note" grep -q 'no "Project structure" section' "$WORK/out9"
rm "$PLAIN/AGENTS.md"
printf '# Hi\n\n## Project structure\n\nfrom claude\n' > "$PLAIN/CLAUDE.md"
"$WHERE" --refresh "$PLAIN" > "$WORK/out10" 2> /dev/null
check "falls back to CLAUDE.md" grep -q 'from claude' "$WORK/out10"

# Truncation
BIG="$HOME/Projects/big"
git init -q -b master "$BIG"
for i in $(seq 1 80); do mkdir -p "$BIG/d$i/sub"; echo x > "$BIG/d$i/sub/f"; done
{ echo '## Project structure'; for i in $(seq 1 200); do echo "- line $i"; done; } > "$BIG/AGENTS.md"
git -C "$BIG" add -A
git -C "$BIG" commit -q -m big
"$WHERE" "$BIG" > "$WORK/out11" 2> /dev/null
check "output is capped near 120 lines" test "$(wc -l < "$WORK/out11")" -le 125
check "truncation is announced" grep -qi 'truncated' "$WORK/out11"

# Paths with spaces: bare layout and worktree
SP="$HOME/Projects/my proj"
mkdir -p "$SP"
git clone -q --bare "$SEED" "$SP/.git"
git -C "$SP/.git" worktree add -q "$SP/work tree" master
"$WHERE" "$SP/work tree" > "$WORK/outsp" 2> /dev/null
check "spaces: root and worktree named intact" grep -q "root: $SP\$" "$WORK/outsp"
check "spaces: worktree path intact" grep -q "worktree: $SP/work tree\$" "$WORK/outsp"
check "spaces: worktree list shows the spaced path" grep -q "$SP/work tree" "$WORK/outsp"
check "spaces: tree built" grep -q 'src/' "$WORK/outsp"
(cd "$SP/work tree/src/core" && "$WHERE" > "$WORK/outsp2" 2> /dev/null)
check "spaces: run from a subdirectory maps the worktree" grep -q "worktree: $SP/work tree\$" "$WORK/outsp2"

# Refusal at broad roots (exit 2 with a hint, nothing mapped)
for broad in "$HOME" "$HOME/Projects" / /tmp; do
  "$WHERE" "$broad" > "$WORK/o" 2> "$WORK/e"
  rc=$?
  check "refuses $broad with exit 2" test "$rc" -eq 2
  check "refusal of $broad carries a hint" grep -qi 'broad' "$WORK/e"
  check "refusal of $broad maps nothing" test ! -s "$WORK/o"
done
(cd "$HOME/Projects" && "$WHERE" > /dev/null 2> "$WORK/e")
rc=$?
check "refuses when the cwd is a broad root" test "$rc" -eq 2

# Not a project
mkdir -p "$WORK/notgit"
"$WHERE" "$WORK/notgit" > /dev/null 2> "$WORK/e"
rc=$?
check "a non-git directory exits 2" test "$rc" -eq 2

# --- council round 1 regressions ---

# Symlinked AGENTS.md pointing outside the project must not be read.
SYM="$HOME/Projects/sym"
git init -q -b master "$SYM"
printf '## Project structure\nTOPSECRET-OUTSIDE\n' > "$WORK/outside.md"
ln -s "$WORK/outside.md" "$SYM/AGENTS.md"
echo x > "$SYM/f"
git -C "$SYM" add -A
git -C "$SYM" commit -q -m sym
"$WHERE" "$SYM" > "$WORK/osym" 2> /dev/null
check "symlink outside the project is not read" not grep -q TOPSECRET "$WORK/osym"
check "symlink outside the project is called out" grep -qi 'outside the project' "$WORK/osym"

# Worktree added without HEAD moving invalidates the cache.
"$WHERE" --refresh "$PROJ" > /dev/null 2>&1
"$WHERE" "$PROJ" > /dev/null 2> "$WORK/ec1"
check "baseline: root map is cached" grep -qi cached "$WORK/ec1"
git -C "$PROJ/.git" worktree add -q "$PROJ/extra" -b extra master
"$WHERE" "$PROJ" > "$WORK/oc2" 2> "$WORK/ec2"
check "adding a worktree invalidates the cache" not grep -qi cached "$WORK/ec2"
check "the new worktree is listed" grep -q "$PROJ/extra" "$WORK/oc2"

# Cache identity includes the git common dir.
CF=$(find "$XDG_CACHE_HOME/where" -type f -name "*proj_master*" | head -1)
"$WHERE" "$PROJ/master" > /dev/null 2>&1
CF=$(find "$XDG_CACHE_HOME/where" -type f -name "*proj_master*" | head -1)
check "cache header records the common dir" grep -q "$PROJ/.git" "$CF"
sed -i "1s|common=[^ ]*|common=/elsewhere/.git|" "$CF"
"$WHERE" "$PROJ/master" > /dev/null 2> "$WORK/ec3"
check "a different common dir in the cache is a miss" not grep -qi cached "$WORK/ec3"

# Files directly inside a top-level dir are shown; singular wording.
check "files directly inside a top-level dir are shown" grep -q 'blob.bin' "$WORK/out"
check "header says untracked dirs are excluded" grep -qi 'untracked' "$WORK/out"

# Every top-level entry survives truncation; truncation names the command.
check "every top-level entry is printed (d1 and d80)" bash -c "grep -q ' d1/' '$WORK/out11' && grep -q ' d80/' '$WORK/out11'"
check "truncation line names the full-content command" grep -Eq 'truncated.*(git ls-files|git worktree list)' "$WORK/out11"

# Root mode lists many worktrees.
MANY="$HOME/Projects/many"
mkdir -p "$MANY"
git clone -q --bare "$SEED" "$MANY/.git"
for i in $(seq 1 40); do git -C "$MANY/.git" worktree add -q -b "b$i" "$MANY/w$i" master; done
"$WHERE" "$MANY" > "$WORK/oman" 2> /dev/null
check "root mode lists all 40 worktrees" test "$(grep -c "$MANY/w" "$WORK/oman")" -eq 40

# Heading variants, code fences, CLAUDE.md fallback.
H="$HOME/Projects/heads"
git init -q -b master "$H"
printf '# A\n\n## Structure\n\n```\n## not a heading\n```\nafter fence\n\n## Next\nx\n' > "$H/AGENTS.md"
git -C "$H" add -A; git -C "$H" commit -q -m h
"$WHERE" "$H" > "$WORK/oh" 2> /dev/null
check "'## Structure' is accepted" grep -q 'after fence' "$WORK/oh"
check "a ## inside a code fence does not end the section" not grep -q '^x$' "$WORK/oh"
printf '# A\n\n## repository LAYOUT\n\nlayout-body\n' > "$H/AGENTS.md"
"$WHERE" --refresh "$H" > "$WORK/oh2" 2> /dev/null
check "case-insensitive 'repository layout' accepted" grep -q layout-body "$WORK/oh2"
printf '# A\n\n## Other\n' > "$H/AGENTS.md"
printf '## Project structure\n\nclaude-fallback\n' > "$H/CLAUDE.md"
"$WHERE" --refresh "$H" > "$WORK/oh3" 2> /dev/null
check "AGENTS.md lacking the section falls through to CLAUDE.md" grep -q claude-fallback "$WORK/oh3"

# Failure modes: no traceback, one-line message, nonzero.
mkdir -p "$WORK/fakebin"
cat > "$WORK/fakebin/git" <<'FAKE'
#!/bin/sh
case "$*" in *ls-files*) sleep 5 ;; esac
exec /usr/bin/git "$@"
FAKE
chmod +x "$WORK/fakebin/git"
WHERE_GIT_TIMEOUT=1 PATH="$WORK/fakebin:$PATH" "$WHERE" --refresh "$PLAIN" > /dev/null 2> "$WORK/etm"
rc=$?
check "git timeout exits nonzero" test "$rc" -ne 0
check "git timeout prints no traceback" not grep -q Traceback "$WORK/etm"
check "git timeout prints a one-line message" test "$(wc -l < "$WORK/etm")" -eq 1

# Size work is bounded.
WHERE_MAX_STAT=3 "$WHERE" --refresh "$BIG" > "$WORK/obs" 2> /dev/null
check "past the stat bound, sizes are skipped and said so" grep -qi 'sizes skipped' "$WORK/obs"

# Inherited git env must not redirect the map.
GIT_DIR="$PLAIN/.git" "$WHERE" --refresh "$PROJ/master" > "$WORK/oenv" 2> /dev/null
check "GIT_DIR in the environment is ignored" grep -q "root: $PROJ\$" "$WORK/oenv"

# --- council round 2 regressions ---

# Flat repo: thousands of top-level files collapse into one line.
FLAT="$HOME/Projects/flat"
git init -q -b master "$FLAT"
for i in $(seq 1 3000); do : > "$FLAT/f$i.txt"; done
for i in $(seq 1 200); do mkdir -p "$FLAT/dir$i"; : > "$FLAT/dir$i/x"; done
git -C "$FLAT" add -A; git -C "$FLAT" commit -q -m flat
"$WHERE" "$FLAT" > "$WORK/oflat" 2> /dev/null
check "flat repo output stays near 120 lines" test "$(wc -l < "$WORK/oflat")" -le 125
check "excess top-level files collapse into one counted line" grep -Eq 'more top-level files.*git ls-files' "$WORK/oflat"
check "excess top-level directories are capped with a notice" grep -Eq 'truncated.*(more )?(top-level )?director(y|ies).*git ls-files' "$WORK/oflat"
check "plural of directory is right" not grep -q 'directorys' "$WORK/oflat"

# Past WHERE_MAX_STAT, deleted tracked files are still dropped.
DEL="$HOME/Projects/del"
git init -q -b master "$DEL"
echo a > "$DEL/keep.txt"; echo b > "$DEL/gone.txt"
git -C "$DEL" add -A; git -C "$DEL" commit -q -m del
rm "$DEL/gone.txt"
WHERE_MAX_STAT=1 "$WHERE" --refresh "$DEL" > "$WORK/odel" 2> /dev/null
check "past the stat bound, the index is listed unfiltered" grep -q gone.txt "$WORK/odel"
check "past the stat bound, the skip line says deleted files are not filtered" grep -q 'deleted files not filtered' "$WORK/odel"
check "past the stat bound, live files are listed" grep -q keep.txt "$WORK/odel"
"$WHERE" --refresh "$DEL" > "$WORK/odel2" 2> /dev/null
check "below the bound, deleted files are still dropped" not grep -q gone.txt "$WORK/odel2"

# Bad numeric env: one line, exit 1.
WHERE_GIT_TIMEOUT=abc "$WHERE" "$PLAIN" > /dev/null 2> "$WORK/eb1"; rc=$?
check "non-numeric WHERE_GIT_TIMEOUT exits 1" test "$rc" -eq 1
check "non-numeric WHERE_GIT_TIMEOUT is one line, no traceback" test "$(wc -l < "$WORK/eb1")" -eq 1
WHERE_MAX_STAT=x "$WHERE" "$PLAIN" > /dev/null 2> "$WORK/eb2"; rc=$?
check "non-numeric WHERE_MAX_STAT exits 1" test "$rc" -eq 1
check "non-numeric WHERE_MAX_STAT is one line, no traceback" test "$(wc -l < "$WORK/eb2")" -eq 1

# A ~~~ fence is not closed by a ``` line.
printf '# A\n\n## Structure\n~~~\n```\n## inside\n~~~\nafter-tilde\n\n## Next\n' > "$H/AGENTS.md"
rm -f "$H/CLAUDE.md"
"$WHERE" --refresh "$H" > "$WORK/oh4" 2> /dev/null
check "fence closes only on its own type" grep -q after-tilde "$WORK/oh4"

# Bad numbers: non-finite, non-positive timeout, negative stat bound.
for bad in nan inf -inf 0 -1; do
  WHERE_GIT_TIMEOUT=$bad "$WHERE" "$PLAIN" > /dev/null 2> "$WORK/eg"; rc=$?
  check "WHERE_GIT_TIMEOUT=$bad exits 1" test "$rc" -eq 1
  check "WHERE_GIT_TIMEOUT=$bad is one line naming the variable" bash -c "test \$(wc -l < '$WORK/eg') -eq 1 && grep -q WHERE_GIT_TIMEOUT '$WORK/eg'"
done
for bad in -1 1.5; do
  WHERE_MAX_STAT=$bad "$WHERE" "$PLAIN" > /dev/null 2> "$WORK/eg"; rc=$?
  check "WHERE_MAX_STAT=$bad exits 1" test "$rc" -eq 1
  check "WHERE_MAX_STAT=$bad is one line naming the variable" bash -c "test \$(wc -l < '$WORK/eg') -eq 1 && grep -q WHERE_MAX_STAT '$WORK/eg'"
done
WHERE_MAX_STAT=0 "$WHERE" --refresh "$PLAIN" > "$WORK/ez" 2> /dev/null; rc=$?
check "WHERE_MAX_STAT=0 is valid (never stat)" test "$rc" -eq 0
check "WHERE_MAX_STAT=0 skips sizes" grep -q 'sizes skipped' "$WORK/ez"

exit "$fail"
