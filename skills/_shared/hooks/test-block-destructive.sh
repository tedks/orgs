#!/bin/bash
# Regression tests for the force-push and bounded recursive-deletion guards.
#
# Drives the real hook end-to-end: feeds it the same PreToolUse JSON Claude Code
# would, and asserts on its deny/allow decision. This catches regressions in the
# whole script (patterns, jq wiring, loop), not just an isolated regex.
#
# Threat model note: this guard protects against ACCIDENTAL / reflexive force
# pushes by the agent, not adversarial evasion. It greps raw shell text, so
# quoting (git push "-f") can slip past -- that is a documented non-goal, pinned
# below so the behavior is visible rather than silently assumed.
#
# Run: bash skills/_shared/hooks/test-block-destructive.sh   (exits non-zero on failure)

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="${HOOK_UNDER_TEST:-$HERE/block-destructive.sh}"

if [[ ! -f "$HOOK" ]]; then
  echo "FATAL: hook not found at $HOOK" >&2
  exit 2
fi

# Returns 0 if the hook denies the given command, 1 if it allows it.
hook_denies() {
  local cmd="$1" out
  out="$(jq -n --arg cmd "$cmd" '{tool_input: {command: $cmd}}' | PATH="${HOOK_RUNTIME_PATH:-$PATH}" bash "$HOOK")"
  LAST_HOOK_OUTPUT="$out"
  grep -q '"permissionDecision": "deny"' <<< "$out"
}

fails=0

expect() { # $1 = BLOCK|ALLOW, $2 = command
  local want="$1" cmd="$2" got
  if hook_denies "$cmd"; then got=BLOCK; else got=ALLOW; fi
  if [[ "$got" == "$want" ]]; then
    printf 'ok    %-5s | %q\n' "$want" "$cmd"
  else
    printf 'FAIL  want=%-5s got=%-5s | %q\n' "$want" "$got" "$cmd"
    fails=$((fails + 1))
  fi
}

if [[ -z "${DELETION_CASE_ONLY:-}" ]]; then
# --- MUST BLOCK: the real danger, in its natural forms ---
expect BLOCK 'git push -f'
expect BLOCK 'git push --force'
expect BLOCK 'git push -u origin main -f'
expect BLOCK 'git push --force origin main'
expect BLOCK 'git push origin main --force'

# MUST BLOCK: flexible whitespace (tabs / repeated spaces are shell-equivalent)
expect BLOCK 'git  push -f'
expect BLOCK $'git\tpush --force'
expect BLOCK $'git push\t-f'

# MUST BLOCK: bundled short flags -- any -..f.. cluster is force on git push
expect BLOCK 'git push -uf origin main'
expect BLOCK 'git push -fu origin main'
expect BLOCK 'git push -uvf'

# MUST BLOCK: flag at a shell-metachar boundary (not just space / end-of-line)
expect BLOCK 'git push --force;'
expect BLOCK 'git push -f;'
expect BLOCK 'git push --force|cat'
expect BLOCK 'git push -f && echo done'
expect BLOCK 'git push --force > push.log'

# MUST BLOCK: a backslash line-CONTINUATION is one command -- the hook folds it,
# so a force-push split across continued lines is still caught.
expect BLOCK $'git push \\\n  -f'
expect BLOCK $'git push \\\n  --force'
expect BLOCK $'git \\\n  push -f'
expect BLOCK $'git push origin main \\\n  --force'

# MUST BLOCK: a real force-push on a later line of a multi-line command.
expect BLOCK $'echo starting\ngit push --force'
expect BLOCK $'git status\ngit push -f'

# --- MUST ALLOW: false positives that bit us, plus the safe force variants ---
expect ALLOW 'git push -u origin identity-fallback'         # "-fa" is not the -f flag
expect ALLOW 'git push -u origin council-review-fixpoint'   # "-fi" is not the -f flag
expect ALLOW 'git push origin my-feature'                   # "-fe" inside a branch name
expect ALLOW 'git push origin HEAD'
expect ALLOW 'git push --set-upstream origin feat-x'
expect ALLOW 'git push --force-with-lease origin main'      # safer variant, intentionally permitted
expect ALLOW 'git push --force-with-lease'
expect ALLOW 'git push --force-if-includes origin main'     # also a safe lease-family variant

# MUST ALLOW: the force flag must belong to THIS push, not a later command --
# whether the next command is joined by && (single line) or by a newline.
expect ALLOW 'git push origin main && grep -f pattern file'
expect ALLOW $'git push origin main\ngrep -f pattern file'  # bare newline = separator, not continuation
expect ALLOW $'git push origin main\necho --force'          # --force here is just echoed text
expect ALLOW $'git push\n-f'                                # `git push` then a separate (non-force) `-f`
expect ALLOW 'git push origin main--force'                  # branch name ending in --force, not a flag

# --- Documented NON-GOALS: pinned as ALLOW so the limitations stay visible. ---
# (1) Adversarial quoting evades a raw-text regex (and an agent with shell access
#     could bypass any text guard regardless).
expect ALLOW 'git push "-f"'
expect ALLOW "git push '--force'"
# (2) Other force/destructive VECTORS, out of scope of the two flag patterns and
#     tracked as a follow-up issue: the '+' refspec force prefix, global options
#     before the subcommand, the dashed git-push variant, and --mirror.
expect ALLOW 'git push origin +main'
expect ALLOW 'git -c color.ui=always push --force'
expect ALLOW 'git-push --force'
expect ALLOW 'git push --mirror'

# --- Other destructive guards still fire (catch accidental over-narrowing) ---
expect ALLOW 'rm -rf /tmp/x'
expect BLOCK 'git reset --hard'

fi

# Bounded deletion policy: each named case is driven through the real JSON hook.
# Mutation runner selects one ID at a time, so every case must independently kill
# its mutant rather than borrowing another case's failure.
deletion_case() { # ID EXPECT COMMAND
  [[ -z "${DELETION_CASE_ONLY:-}" || "$DELETION_CASE_ONLY" == "$1" ]] || return 0
  local fixture=''
  if [[ "$1" == runtime_failure ]]; then
    # Only the hook gets this PATH. The fake runtime emits no stderr and exits
    # nonzero; the test runner retains its real jq/Python and never executes rm
    # operands. Cleanup touches only the generated fixture file/directory.
    fixture="$(mktemp -d "${TMPDIR:-/tmp}/deletion-runtime-test.XXXXXXXX")" || exit 2
    printf '#!/bin/sh\nexit 1\n' > "$fixture/python3"
    chmod +x "$fixture/python3"
    HOOK_RUNTIME_PATH="$fixture:$PATH"
  fi
  printf 'case %s: ' "$1"
  expect "$2" "$3"
  if [[ "$1" == runtime_failure ]]; then
    if ! jq -e '.hookSpecificOutput.permissionDecisionReason ==
        "Deletion check unavailable (requires Python 3). Restore the hook runtime before retrying."' \
        <<< "$LAST_HOOK_OUTPUT" > /dev/null; then
      printf 'case %s: FAIL  missing exact runtime-unavailable deny reason\n' "$1"
      fails=$((fails + 1))
    fi
    unset HOOK_RUNTIME_PATH
    rm -f -- "$fixture/python3"
    rmdir -- "$fixture"
  fi
}
# DELETION_CASES_BEGIN
deletion_case literal ALLOW $'rm -rf /tmp/owned-run-123'
deletion_case relative_literal ALLOW $'rm -fr ./owned-run-123'
deletion_case variable_literal ALLOW $'rm -rf "$root"/owned-run-123'
deletion_case literal_variable ALLOW $'rm -rf /tmp/owned-run-$id'
deletion_case owned_glob ALLOW $'rm -rf ./owned-run-123/*'
deletion_case tmp_owned_glob ALLOW $'rm -rf /tmp/owned-run-123/*'
deletion_case dynamic_owned_glob ALLOW $'rm -rf "$root"/owned-run-123/*'
deletion_case quoted_star ALLOW $'rm -rf \'*\''
deletion_case double_quoted_star ALLOW $'rm -rf "*"'
deletion_case escaped_star ALLOW $'rm -rf \\*'
deletion_case quoted_variable_star ALLOW $'rm -rf "$root/owned-*"'
deletion_case comment ALLOW $'echo okay # rm -rf *'
deletion_case string ALLOW $'printf \'%s\\n\' \'rm -rf *\''
deletion_case nonrecursive ALLOW $'rm -f "$dir"'
deletion_case separate_literal ALLOW $'rm -r -f ./owned-run-123'
deletion_case uppercase_literal ALLOW $'rm -Rf ./owned-run-123'
deletion_case long_literal ALLOW $'rm --recursive --force ./owned-run-123'
deletion_case separator ALLOW $'rm -r ./owned-run-123; echo "$dir"'
deletion_case newline_separator ALLOW $'rm -r ./owned-run-123\necho "$dir"'
deletion_case unmatched_bracket ALLOW $'rm -rf ['
deletion_case glob BLOCK $'rm -rf *'
deletion_case reverse_glob BLOCK $'rm -fr cache*'
deletion_case question_glob BLOCK $'rm -r file?'
deletion_case bracket_glob BLOCK $'rm -R [ab]'
deletion_case dot_glob BLOCK $'rm -rf ./*'
deletion_case parent_glob BLOCK $'rm -rf ../*'
deletion_case prefix_glob BLOCK $'rm -rf owned-*/child'
deletion_case tmp_glob BLOCK $'rm -rf /tmp/council-*'
deletion_case tmp_dynamic_glob BLOCK $'rm -rf /tmp/${prefix}*'
deletion_case tmp_dynamic_directory BLOCK $'rm -rf /tmp/$dir/*'
deletion_case tmp_dot_glob BLOCK $'rm -rf /tmp/../tmp/./council-*'
deletion_case variable BLOCK $'rm -rf "$dir"'
deletion_case braced_variable BLOCK $'rm -rf "${dir}"'
deletion_case unquoted_variable BLOCK $'rm -rf $dir'
deletion_case variable_dots BLOCK $'rm -rf ./$dir/..'
deletion_case variable_dot_suffix BLOCK $'rm -rf "$dir".'
deletion_case substitution BLOCK $'rm -r "$(printf dir)"'
deletion_case backtick BLOCK $'rm -r `printf dir`'
deletion_case multiple BLOCK $'rm -rf ./owned-run-123 "$dir"'
deletion_case separate_flags BLOCK $'rm -r -f "$dir"'
deletion_case uppercase BLOCK $'rm -Rf "$dir"'
deletion_case long BLOCK $'rm --recursive --force "$dir"'
deletion_case abbreviated_long BLOCK $'rm --rec "$dir"'
deletion_case no_force BLOCK $'rm -r "$dir"'
deletion_case flags_after_operand BLOCK $'rm "$dir" -r'
deletion_case double_dash BLOCK $'rm -rf -- "$dir"'
deletion_case tabs BLOCK $'rm\t-rf\t"$dir"'
deletion_case continuation BLOCK $'rm -\\\nrf "$dir"'
deletion_case newline BLOCK $'echo okay\nrm -r "$dir"'
deletion_case pipeline BLOCK $'printf okay | rm -r "$dir"'
deletion_case sudo BLOCK $'sudo rm -r "$dir"'
deletion_case env_assignment BLOCK $'env MODE=test rm -r "$dir"'
deletion_case command BLOCK $'command rm -r "$dir"'
deletion_case exec BLOCK $'exec rm -r "$dir"'
deletion_case absolute_rm BLOCK $'/bin/rm -r "$dir"'
deletion_case redirection BLOCK $'rm -r "$dir" > ./log'
deletion_case loop BLOCK $'for dir in one two; do rm -r "$dir"; done'
deletion_case post_comment BLOCK $'echo okay # safe\nrm -r "$dir"'
deletion_case option_boundary ALLOW $'rm -- -rf "$dir"'
deletion_case redirection_target ALLOW $'rm -rf ./owned-run-123 > "$log"'
deletion_case var_tmp_glob BLOCK 'rm -rf /var/tmp/council-*'
deletion_case var_tmp_owned_glob ALLOW 'rm -rf /var/tmp/owned-run-123/*'
deletion_case shm_glob BLOCK 'rm -rf /dev/shm/council-*'
deletion_case shm_owned_glob ALLOW 'rm -rf /dev/shm/owned-run-123/*'
deletion_case nested_quote_substitution BLOCK $'rm -r "$(printf \' )\')"'
deletion_case bracket_other_word ALLOW 'rm -rf [ literal]'
deletion_case bracket_quoted_close ALLOW 'rm -rf [a"]"'
deletion_case literal_dollar ALLOW $'rm -rf \'$dir\''
deletion_case normalized_tmp_glob BLOCK 'rm -rf /tmp/owned-run-123/../*'
deletion_case runtime_enabled ALLOW 'printf harmless'
deletion_case runtime_failure BLOCK 'printf harmless'
deletion_case double_slash_tmp BLOCK 'rm -rf //tmp/*'
deletion_case double_slash_tmp_owned ALLOW 'rm -rf //tmp/owned-run-123/*'
deletion_case double_slash_var_tmp BLOCK 'rm -rf //var/tmp/*'
deletion_case double_slash_var_tmp_owned ALLOW 'rm -rf //var/tmp/owned-run-123/*'
deletion_case double_slash_shm BLOCK 'rm -rf //dev/shm/*'
deletion_case double_slash_shm_owned ALLOW 'rm -rf //dev/shm/owned-run-123/*'
deletion_case home_expansion BLOCK 'rm -rf ~'
deletion_case home_glob BLOCK 'rm -rf ~/*'
deletion_case home_user BLOCK 'rm -rf ~other/*'
deletion_case quoted_home ALLOW "rm -rf '~'"
deletion_case escaped_home ALLOW 'rm -rf \~'
deletion_case else_rm BLOCK 'if false; then :; else rm -rf "$dir"; fi'
deletion_case brace_rm BLOCK '{ rm -rf "$dir"; }'
deletion_case bang_rm BLOCK '! rm -rf "$dir"'
deletion_case time_rm BLOCK 'time rm -rf "$dir"'
deletion_case timeout_rm BLOCK 'timeout 5 rm -rf "$dir"'
# DELETION_CASES_END

echo
if (( fails )); then
  echo "$fails test(s) FAILED"
  exit 1
fi
echo "all tests passed"
