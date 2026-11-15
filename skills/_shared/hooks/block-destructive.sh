#!/bin/bash
# Block destructive commands even in bypass permissions mode.
# Claude Code PreToolUse hook — exits with deny JSON to block, exits 0 to allow.

INPUT=$(cat)
COMMAND=$(jq -r '.tool_input.command' <<< "$INPUT")

# grep is line-oriented, so a command split across lines would never match a
# pattern. Reduce the command to one line for scanning, preserving shell
# semantics so we neither miss a split command nor fabricate a match across
# independent ones:
#   * backslash-newline is a line CONTINUATION -> fold to a space, so
#     "git push \<newline>--force" scans as the single-line "git push --force".
#   * a bare newline is a command SEPARATOR (like ';') -> map to ';', so the
#     [^;&|]* spans below stop at it and do NOT bridge across independent
#     commands ("git push origin main<newline>grep -f x" must not look like a
#     force push, exactly as the "&&" single-line form does not).
SCAN=${COMMAND//$'\\'$'\n'/ }
SCAN=${SCAN//$'\n'/;}

# Deletion guard: Python 3 lexes shell words without evaluating any shell text.
# Supported: simple commands/pipelines/lists, comments, single/double quotes,
# escapes/continuations, assignments, plain sudo/env/command/exec wrappers,
# simple timeout DURATION, reserved command-position words and brace groups,
# variable/parameter/command substitutions as opaque dynamic word fragments,
# GNU rm -r/-R (in any short-option bundle), --recursive and its abbreviations,
# options interspersed with operands, and --. No force flag is required.
# A glob needs a complete concrete directory component BEFORE its first glob;
# '.', '..', slash-only and dynamic-only components do not establish one.
# /tmp, /var/tmp and /dev/shm are shared: /tmp/prefix* is blocked;
# /tmp/run-123/* has a concrete directory boundary.
# A dynamic operand needs a concrete literal component (not just './$dir').
# Unquoted tilde at the start of an operand expands to a home directory and is
# blocked; quoted/escaped tildes and globs are literal names. Literal paths remain allowed: this
# guard does not prove ownership, inspect the filesystem or replace enumeration.
# Non-goals: aliases/functions, eval/sh -c, heredocs, dynamic command names,
# shell-specific expansions (brace/extglob), commands inside substitutions,
# leading redirections, or wrapper options taking a separate value (sudo -u).
# Keep the separate raw-text guards below unchanged, especially force-push.
if ! DELETION_REASON=$(python3 - "$COMMAND" <<'PY_DELETION'
import posixpath
import re
import sys

DYNAMIC = '\x00'

def token(text, globs, home):
    # Only an unquoted closing bracket in THIS word closes a bracket pattern.
    closing = [i for i in globs if text[i] == ']']
    return text, [i for i in globs if text[i] != ']' and
                  (text[i] != '[' or any(end > i for end in closing))], home


def words(source):
    """Yield (text, active-glob offsets, home-expansion), or None separators."""
    i, text, globs, quote, started, home = 0, '', [], '', False, False
    while i < len(source):
        c = source[i]
        if c == '\\' and quote != "'" and i + 1 < len(source):
            nxt = source[i + 1]
            if nxt == '\n':
                i += 2
                continue
            if not quote or nxt in '$`"\\':
                text += nxt
                started = True
                i += 2
                continue
        if c in "\"'" and (not quote or quote == c):
            quote = '' if quote else c
            started = True
            i += 1
            continue
        if not quote and (c.isspace() or c in ';|&()<>'):
            if started:
                yield token(text, globs, home)
                text, globs, started, home = '', [], False, False
            if c == '\n' or c in ';|&()':
                yield None
            elif c in '<>':
                # Redirection targets aren't rm operands. The command remains
                # in this segment; the consumer discards the next target word.
                yield c, [], False
            i += 1
            continue
        if not quote and c == '#' and not started:
            end = source.find('\n', i)
            i = len(source) if end < 0 else end
            continue
        if c == '$' and quote != "'":
            match = re.match(r'\$(?:[A-Za-z_][A-Za-z_0-9]*|[0-9@*#?$!_-])', source[i:])
            if i + 1 < len(source) and source[i + 1] in '{(':
                opener = source[i + 1]
                closer = '}' if opener == '{' else ')'
                depth, end, inner_quote = 1, i + 2, ''
                while end < len(source) and depth:
                    inner = source[end]
                    if inner == '\\' and inner_quote != "'":
                        end += 2
                        continue
                    if inner in "\"'" and (not inner_quote or inner_quote == inner):
                        inner_quote = '' if inner_quote else inner
                    elif not inner_quote:
                        if inner == opener:
                            depth += 1
                        elif inner == closer:
                            depth -= 1
                    end += 1
            elif match:
                end = i + len(match[0])
            else:
                end = i
            if end > i:
                text += DYNAMIC
                started = True
                i = end
                continue
        if c == '`' and quote != "'":
            end = source.find('`', i + 1)
            text += DYNAMIC
            started = True
            i = len(source) if end < 0 else end + 1
            continue
        if not quote and c in '*?[]':
            globs.append(len(text))
        if not quote and c == '~' and not started:
            home = True
        text += c
        started = True
        i += 1
    if started:
        yield token(text, globs, home)


def unsafe(word):
    text, globs, home = word
    if home:
        return 'unquoted home-directory expansion'
    # Literal content inside a dynamic component is an anchor too (run-$id).
    concrete = lambda part: part.replace(DYNAMIC, '') not in ('', '.', '..')
    if DYNAMIC in text and not any(concrete(p) for p in text.split('/')):
        return 'variable-only path'
    if globs:
        prefix = text[:min(globs)]
        directory = prefix.rsplit('/', 1)[0] if '/' in prefix else ''
        # Normalize literal dot components so /tmp/../tmp/* stays a sweep.
        directory = posixpath.normpath(directory)
        # Linux treats //tmp as /tmp; normpath preserves exactly two leading
        # slashes for other POSIX platforms, so canonicalize this fleet spelling.
        if directory.startswith('/'):
            directory = '/' + directory.lstrip('/')
        parts = directory.split('/')
        shared = ('/tmp', '/var/tmp', '/dev/shm')
        for root in shared:
            if directory.startswith(root + '/'):
                parts = directory[len(root) + 1:].split('/')
                break
        if not any(concrete(p) for p in parts) or directory in shared:
            return 'unanchored or shared temporary-directory glob'
    return None


def deletion_reason(segment):
    # Only command-position rm is meaningful; echo/printf strings aren't calls.
    i = 0
    while i < len(segment):
        name = segment[i][0]
        if re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', name) or name in (
                'do', 'then', 'else', 'elif', 'if', 'while', 'until', '!', 'time', '{', '}'):
            i += 1
        elif name == 'timeout' and i + 1 < len(segment):
            i += 2  # GNU timeout's simple DURATION COMMAND form.
        elif name in ('sudo', 'env', 'command', 'exec'):
            i += 1
            # Natural wrapper flags; flags taking values are outside this grammar.
            while i < len(segment) and segment[i][0].startswith('-'):
                i += 1
        else:
            break
    if i == len(segment) or segment[i][0] not in ('rm', '/bin/rm', '/usr/bin/rm'):
        return None
    recursive, options, operands, redirect = False, True, [], False
    for word in segment[i + 1:]:
        token = word[0]
        if token in ('<', '>'):
            redirect = True
            continue
        if redirect:
            redirect = False
            continue
        if options and token == '--':
            options = False
        elif options and token.startswith('-') and token != '-':
            if token.startswith('--'):
                recursive |= len(token) > 2 and '--recursive'.startswith(token)
            else:
                recursive |= 'r' in token or 'R' in token
        else:
            operands.append(word)
    if recursive:
        for operand in operands:
            reason = unsafe(operand)
            if reason:
                return 'Blocked recursive deletion: ' + reason + '. Enumerate and review an owned candidate list first.'
    return None

segment = []
for word in [*words(sys.argv[1]), None]:
    if word is None:
        reason = deletion_reason(segment)
        if reason:
            print(reason)
            break
        segment = []
    else:
        segment.append(word)
PY_DELETION
); then
  DELETION_REASON="Deletion check unavailable (requires Python 3). Restore the hook runtime before retrying."
fi
if [[ -n "$DELETION_REASON" ]]; then
  jq -n --arg reason "$DELETION_REASON" '{hookSpecificOutput: {
    hookEventName: "PreToolUse", permissionDecision: "deny",
    permissionDecisionReason: $reason
  }}'
  exit 0
fi

DANGEROUS_PATTERNS=(
  'git clean -f'
  'git checkout \.'
  'git restore \.'
  'git reset --hard'
  # Force-push guard. This is a guardrail against the agent ACCIDENTALLY or
  # reflexively force-pushing, NOT a sandbox against deliberate evasion: this
  # greps raw shell text, so quoting (git push "-f") or encoding can always slip
  # past a regex, and an agent with shell access could do so anyway. We therefore
  # match the *natural* force-push forms robustly:
  #   * [[:space:]]+ / [[:space:]] tolerate tabs and repeated spaces.
  #   * [^;&|]* keeps the flag attached to THIS push, so a flag belonging to a
  #     later command in a compound line (git push origin main && grep -f x) is
  #     not a false positive.
  #   * The flag token must end at a boundary -- a non-hyphen (long) / non-letter
  #     (short) char, or end-of-line. This blocks a flag at end-of-string (which
  #     the old [^-]/[^o] missed) and a flag followed by a shell metachar
  #     (git push --force;), while still ALLOWING --force-with-lease and
  #     --force-if-includes (force followed by '-', the safe lease/includes
  #     family the operator clearly intends to permit).
  #   * -[[:alpha:]]*f[[:alpha:]]* catches bundled short flags (-uf, -fu): -f is
  #     git push's only short option containing 'f', so any -..f.. cluster forces.
  #   * Leading [[:space:]] before --force avoids blocking a branch whose name
  #     ends in --force (git push origin main--force).
  # Out of scope here (other force/destructive VECTORS, not bugs in these flag
  # patterns; tracked as a follow-up): the '+' refspec force prefix
  # (git push origin +main), global options before the subcommand
  # (git -c x=y push --force), the dashed 'git-push' variant, and --mirror.
  # Also accepted: a dry-run force (git push --dry-run --force) is still blocked
  # -- over-blocking a no-op is the safe direction, and an ERE has no negative
  # lookahead to cleanly exempt it.
  'git[[:space:]]+push[^;&|]*[[:space:]]--force([^-]|$)'
  'git[[:space:]]+push[^;&|]*[[:space:]]-[[:alpha:]]*f[[:alpha:]]*([^[:alpha:]]|$)'
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if printf '%s\n' "$SCAN" | grep -qE "$pattern"; then
    jq -n --arg reason "Blocked by hook: '$pattern' matched. Ask the user to run this manually." '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $reason
      }
    }'
    exit 0
  fi
done

exit 0
