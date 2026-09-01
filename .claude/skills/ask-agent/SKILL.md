---
name: ask-agent
description: Ask another AI agent a question and get the response back (subagent pattern)
argument-hint: <agent> [options] <prompt>
allowed-tools: Bash(~/.claude/skills/ask-agent/scripts/*)
---

<!-- Codex reads this same file through the .codex/skills/<name> symlink, so the
     paths below assume install-claude-config ran. Never copy this file into
     .codex/skills -- see the skills comment in scripts/install/install-codex-config. -->

# ask-agent

Query another AI agent non-interactively and get the response back. Use this
when you want a second opinion from a different agent (Claude, Codex, Antigravity/agy, etc.).

## Usage

```
/ask-agent <agent> [options] <prompt>
```

## Arguments

- `<agent>`: The agent to query (`claude`, `codex`, `agy`)
- `<prompt>`: The question or request for the agent

## Options

- `-d, --dir <dir>`: Set working directory for the agent
- `-m, --model <model>`: Specify model (agent-specific)
- `-f, --prompt-file <file>`: Read prompt from a file instead of inline (use for
  large prompts to avoid ARG_MAX limits at the caller-to-script boundary)

## Instructions

When this skill is invoked, **always pass the prompt via a temp file** to avoid
ARG_MAX errors with large prompts.

This protects the *caller-to-script* boundary. Past that point no agent is
constrained by argv: `claude` and `codex` receive the prompt on stdin, and
`agy` -- which has no stdin mode -- is handed a file path to read instead of
the prompt text, so nothing large ever transits argv. Ordinary limits still
apply of course: the model's context window, and whatever the agent decides to
do with a very long prompt.

```bash
# 1. Write prompt to a temp file
prompt_file=$(mktemp /tmp/ask-agent-prompt.XXXXXX)
cat << 'PROMPT_DELIM' > "$prompt_file"
<your prompt here>
PROMPT_DELIM

# 2. Run the script with --prompt-file
~/.claude/skills/ask-agent/scripts/agent-query.sh <agent> [options] --prompt-file "$prompt_file"

# 3. Clean up (the script does NOT delete caller-provided files)
rm -f "$prompt_file"
```

For short prompts that are clearly under the ARG_MAX limit (~128KB), inline
is also fine:

```bash
~/.claude/skills/ask-agent/scripts/agent-query.sh <agent> [options] <prompt>
```

The script pipes the prompt via stdin to `claude` and `codex`, and stages it in
a file for `agy`, so inline prompts are safe at the script-to-agent boundary for
all three. The --prompt-file approach
protects the caller-to-script boundary as well.

Report the response back to the user.

## Examples

```bash
# Get Codex opinion on an approach (short prompt, inline ok)
/ask-agent codex "What do you think of using JWT for this auth flow?"

# Ask Claude with a specific model
/ask-agent claude -m opus "Review this error handling pattern"

# Query from a specific directory
/ask-agent codex -d ./src "Explain what the auth module does"

# Ask agy (Antigravity CLI) for a summary
/ask-agent agy "Summarize this codebase"

# Ask agy with a specific model (see `agy models` for available names)
/ask-agent agy -m <model> "Review this architecture"

# Use a prompt file for large prompts (avoids ARG_MAX)
/ask-agent codex --prompt-file /tmp/review-prompt.txt
```

## Agent CLI Mappings

| Agent  | Non-interactive command | Stdin |
|--------|------------------------|-------|
| claude | `claude -p` | Yes - reads from stdin when no positional prompt given |
| codex  | `codex exec -` | Yes - `-` reads from stdin |
| agy | `agy --add-dir <dir> -p "Read <file>..."` | **No** - no stdin mode; the script stages the prompt in a private dir and passes the path |

## Notes

- Response is synchronous - the calling agent waits for the response
- Useful for getting a second opinion or different perspective
- Each agent has different training data and reasoning patterns
- ask-agent is for **foreign** providers. Never ask-agent your own provider
  (Claude must not ask-agent `claude`, Codex must not ask-agent `codex`, agy
  must not ask-agent `agy`) — that is another instance of your own model
  family, correlated blind spots and none of your context, even if a different
  model is picked. For a same-provider second pass use your native subagent
  (or review inline if it cannot run — never ask-agent yourself). In a
  council this is a hard rule: your own provider's seat is your native
  subagent, and a missing foreign seat is noted, never backfilled — see
  `council-review`.
- Prompts are piped via stdin to `claude` and `codex` (never as CLI args)
- **`agy` has no stdin mode**, so the script stages the prompt in a private
  0700 temp directory and passes agy a *path* plus `--add-dir`, letting agy
  read it with its own tools. Only the path reaches argv, so there is no size
  cap (verified reading a 251031-byte prompt in full) and no prompt content in
  `ps` / `/proc/<pid>/cmdline`.
  - Do not "simplify" this to `agy -p "$prompt"`. That reintroduces the
    128 KiB `MAX_ARG_STRLEN` cap and exposes the prompt to every local account
    for as long as agy runs.
  - `--add-dir` is required: without it agy auto-denies its own `read_file`
    in headless mode and exits with no output. Loud, not silent.
  - The staged prompt ends with a per-run marker that agy is told to reproduce
    as the last line of its reply. A reply without it means agy may have
    answered without reading the prompt to the end, so the script says so on
    stderr and **exits 3**. The reply is still printed (marker stripped), but
    treat exit 3 as "this answer may be based on a partial prompt", not as a
    clean result. Exit 3 also covers a reply that is *only* the marker.
  - The marker is stripped from the last line only, so if agy decorates it the
    punctuation survives: a reply ending `**MARKER**` leaves a stray `****`
    line. A known trade-off — stripping the whole line would eat a short answer
    that shares the line with the marker, and stripping every occurrence would
    corrupt a reply that legitimately quotes it mid-body.

### The headless permission flake

`--add-dir` grants a directory **read**, and nothing else. agy usually reads the
staged prompt with its built-in file tool, but it sometimes decides to shell out
(`cat`) instead — and the `command` permission that needs cannot be prompted for
in headless mode, so it is auto-denied and the run produces nothing:

```
jetski: no output produced — a tool required the "command" permission that
headless mode cannot prompt for, so it was auto-denied.
```

Which tool it picks varies run to run, so this presents as an intermittent
failure (roughly 1 in 8 from an untrusted workspace).

**It arrives in two shapes**, and they look completely different from outside:

| | stdout | stderr | exit |
|---|---|---|---|
| **hard** — agy aborts | *empty* | the `jetski:` message | 0 |
| **soft** — agy carries on | the message is *in the reply* | — | 0 |

The script captures stdout but not stderr (stderr passes through live, which is
what you want for visibility), so the hard shape shows up simply as **an empty
reply that exited 0**.

Mitigations, neither touching machine-wide permissions:

- the preamble tells agy to use its file-reading tool and not a shell command;
- the script retries **once**, when the run exited 0 **and the reply does not
  carry the marker**, and is then either empty (hard) or carries the auto-deny
  text (soft). The stderr note says which shape it was.

The marker-absence gate is what makes this safe. A genuine denial produced no
answer, so it cannot carry the marker; a real reply that merely *quotes* the
denial text — which every "review ask-agent" prompt does, since that phrase is
in this very file — does carry it. Without the gate, a good answer was thrown
away and re-asked. And given the gate, "empty" is a sound trigger by itself:
the marker is mandatory, so empty-and-exit-0 can never be a valid reply.

It is deliberately **not** a general retry on exit 3 — that would paper over
genuine partial reads, which is what the marker exists to catch. If you see the
retry note often, the durable fix is a permission allow-rule in
`~/.gemini/config/config.json`, which is an operator security decision and is
tracked separately (ditz `agy-headless-command-permission`) rather than shipped
here.

### Reply trimming is locale-sensitive — there is a tripwire

`scripts/test-rtrim.sh` exercises the reply-trimming function across
`en_US.UTF-8`, `C.UTF-8`, `C` and `POSIX` and asserts byte-identical results.
**Run it after touching anything in the reply-handling path.** It takes a second
and needs no framework:

```bash
.claude/skills/ask-agent/scripts/test-rtrim.sh
```

It exists because this exact code shipped a bug twice, from opposite directions
— once blanking whole replies containing an undecodable byte (the `timeout`
path, where agy is killed mid-character), once letting an invisible character
pass as a successful answer. The caller's locale is not reliable: `LANG` is
unset under cron, systemd units, `ssh host cmd`, `docker exec` and `sudo` with
`env_reset`, and a `LANG` naming an ungenerated locale degrades to `C` silently.
The test extracts the function from `agent-query.sh` rather than copying it, so
it cannot drift.

### Known residuals

- **Replies above ~500KB with no newline at all** hit a quadratic parameter
  expansion when the last line is located: ~0.36s at 200KB, ~3.4s at 500KB,
  ~15.4s at 1MB. Any plausible reply is far below the cliff, but callers run
  this under `timeout`, so it is worth knowing the shape.
- **A signal arriving after agy is reaped but during reply handling discards
  the reply** (~0.4s window). Deliberate: the signal-forwarding traps are
  disarmed once the child is reaped, because leaving them armed meant firing
  `kill` at a PID that may already have been recycled. Losing a reply to a
  signal that arrived in a 0.4s window is the better failure.
- **On a system without `C.UTF-8`, trimming degrades to ASCII-only.** The trim
  pins `C.UTF-8`; if that is unavailable the guard detects the byte locale and
  drops the named non-breaking characters rather than letting the character
  class shred multibyte tails. Consequence: **no corruption ever**, but a reply
  ending in U+00A0 / U+202F / U+FEFF is not trimmed, so the invisible-content
  case would pass as success *in that environment only*. glibc ships `C.UTF-8`
  built in — `LOCPATH` cannot even unseat it — so this is a documented edge, not
  a live hole on this fleet. Asserted in `test-rtrim.sh` rather than only
  described here.
