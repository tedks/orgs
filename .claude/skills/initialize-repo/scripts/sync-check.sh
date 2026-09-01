#!/usr/bin/env bash
#
# sync-check.sh - report drift between a repo's scaffold files and the
# canonical templates in ../templates.
#
# READ-ONLY: this script never modifies the target repo. Divergence after
# scaffolding is allowed; this only makes drift visible so it can be
# reviewed deliberately.
#
# Usage:
#   sync-check.sh <repo-path>
#
# Exit codes:
#   0  report printed (drift or not — this is a report, not a gate)
#   2  usage error, or the skill install itself is broken (missing
#      templates dir or template file)
#
# Assumes target files are readable; unreadable files surface as diff/cmp
# errors rather than tidy report lines.

set -euo pipefail

print_usage() {
  echo "Usage: $(basename "$0") <repo-path>"
}

case "${1:-}" in -h|--help) print_usage; exit 0 ;; esac
if [[ $# -ne 1 ]]; then
  print_usage >&2
  exit 2
fi

REPO="$1"
if [[ ! -d "$REPO" ]]; then
  echo "[sync-check][error] Not a directory: $REPO" >&2
  exit 2
fi
REPO="$(cd "$REPO" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES="$SCRIPT_DIR/../templates"
if [[ ! -d "$TEMPLATES" ]]; then
  echo "[sync-check][error] Templates directory not found: $TEMPLATES" >&2
  exit 2
fi
TEMPLATES="$(cd "$TEMPLATES" && pwd)"

# Verbatim templates: every found candidate is diffed against the template.
# Format: <template-relative-path>|<candidate>[|<candidate>...]
# Candidates are relative to the repo path; ../ candidates cover Ted's
# project layout where loose scripts sit at the project root above the
# primary worktree.
VERBATIM=(
  "create-worktree|create-worktree|create-worktree.sh|../create-worktree|../create-worktree.sh"
  "PLANS.md|.planning/PLANS.md|PLANS.md"
  "github-workflows/claude.yml|.github/workflows/claude.yml"
  "github-workflows/claude-code-review.yml|.github/workflows/claude-code-review.yml"
)

# Skeleton templates: repo-specific by design, so only presence is checked.
SKELETON=(
  "github-workflows/ci-nix.yml|.github/workflows/ci.yml"
  "AGENTS.md|AGENTS.md"
)

n_identical=0
n_drifted=0
n_missing=0
n_skeleton=0

report() { # status, detail
  printf '  %-10s %s\n' "$1" "$2"
}

echo "sync-check: $REPO"
echo "templates:  $TEMPLATES"
echo

for entry in "${VERBATIM[@]}"; do
  IFS='|' read -r -a parts <<<"$entry"
  template="${parts[0]}"
  template_file="$TEMPLATES/$template"
  if [[ ! -f "$template_file" ]]; then
    echo "[sync-check][error] Template missing from skill: $template_file" >&2
    exit 2
  fi

  found=0
  for candidate in "${parts[@]:1}"; do
    target="$REPO/$candidate"
    [[ -f "$target" ]] || continue
    found=1
    if cmp -s "$template_file" "$target"; then
      report "identical" "$candidate"
      n_identical=$((n_identical + 1))
    else
      # Count changed lines from the unified diff. tail -n +3 drops the
      # ---/+++ headers without excluding content lines (a bare '+'/'-'
      # is an added/removed blank line and must be counted).
      diff_body=$(diff -u "$template_file" "$target" | tail -n +3 || true)
      added=$(grep -c '^+' <<<"$diff_body" || true)
      removed=$(grep -c '^-' <<<"$diff_body" || true)
      report "drifted" "$candidate (vs $template: +$added/-$removed lines)"
      n_drifted=$((n_drifted + 1))
    fi
  done
  if [[ "$found" -eq 0 ]]; then
    report "missing" "${parts[1]} (template: $template)"
    n_missing=$((n_missing + 1))
  fi
done

for entry in "${SKELETON[@]}"; do
  IFS='|' read -r -a parts <<<"$entry"
  template="${parts[0]}"
  candidate="${parts[1]}"
  if [[ -f "$REPO/$candidate" ]]; then
    report "skeleton" "$candidate (present; repo-specific by design, not diffed)"
    n_skeleton=$((n_skeleton + 1))
  else
    report "missing" "$candidate (skeleton template: $template)"
    n_missing=$((n_missing + 1))
  fi
done

# Playwright flake snippet: presence-only, detected by content.
if [[ -f "$REPO/flake.nix" ]]; then
  if grep -q 'playwright-driver' "$REPO/flake.nix"; then
    report "skeleton" "flake.nix (uses playwright-driver; snippet template, not diffed)"
    n_skeleton=$((n_skeleton + 1))
  else
    report "n/a" "flake.nix (no playwright block; snippet not in use)"
  fi
else
  report "n/a" "flake.nix (absent; playwright snippet not in use)"
fi

echo
echo "summary: $n_identical identical, $n_drifted drifted, $n_missing missing, $n_skeleton skeleton-present"
exit 0
