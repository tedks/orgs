---
name: ask-agent
description: Ask another AI agent a question and get the response back (subagent pattern)
argument-hint: <agent> [options] <prompt>
allowed-tools: Bash(~/.claude/skills/ask-agent/scripts/*)
---

The Codex branch uses `harness.codex_bin` from the [shared configuration](../_shared/configuration.md) (Python 3.11+).

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
- `-r, --resume <id>`: Continue an existing session instead of starting a new
  one. Mapped to each agent's own flag — see the mapping table below.
- `-S, --session-id-file <file>`: Write the session id this run **yielded** to
  `<file>`, so the next round can pass it back via `--resume`. The file holds
  the bare id and a newline, nothing else — or is left **empty**, which means
  "nothing came out of this round that is safe to chain", never a stale id from
  the round before. It is written by atomic rename at the end, so a run that
  fails before reaching an agent (a typo'd agent name, a bad `--dir`, a
  rejected id) leaves whatever was there **untouched**.

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

# Round 1 of a council: keep the seat warm by capturing its session id
/ask-agent codex --session-id-file /tmp/codex.sid --prompt-file /tmp/round1.txt

# Round 2: same seat, so the prompt can be the fix delta alone
/ask-agent codex --resume "$(cat /tmp/codex.sid)" --prompt-file /tmp/round2.txt
```

## Agent CLI Mappings

| Agent  | Non-interactive command | Stdin |
|--------|------------------------|-------|
| claude | `claude -p` | Yes - reads from stdin when no positional prompt given |
| codex  | `codex exec -` | Yes - `-` reads from stdin |
| agy | `agy --add-dir <dir> -p "Read <file>..."` | **No** - no stdin mode; the script stages the prompt in a private dir and passes the path |

### Session resume, per agent

| Agent | `--resume <id>` becomes | Fork or append? | How the yielded id is obtained |
|-------|------------------------|-----------------|-------------------------------|
| claude | `--resume <id>` | **Append.** Same id, one jsonl in the project dir before and after | The caller **mints** it: the script generates a UUID and passes `--session-id <uuid>` |
| codex | `codex exec resume <id> -` | **Append, in place.** Same rollout file (14 → 26 lines), same id, no new `*.jsonl` | Parsed from codex's stderr banner (`session id: <uuid>`) |
| agy | `--conversation <id>` | **Append.** Same id, no new `.db` | Parsed from a per-run `--log-file` (`Print mode: conversation=<uuid>`) |

All three **append**, so `--resume` mutates the session's history rather than
branching it — which is what a council round wants, but worth knowing before
pointing it at a session you care about. The non-mutating halves exist
(`codex exec fork <id>`, `claude --fork-session`) and are deliberately **not**
wrapped here. Note `codex exec fork` — the `exec` one — runs headless and needs
no terminal. For a steerable, transcript-preserving Codex child that hands a
final recap back to a high-level parent, use `spawn-agent --fork-session`; it
wraps the interactive bare `codex fork` and its tmux lifecycle.

Every claim above was checked rather than inferred; commands, byte counts and
file counts are in [historical session-resume evidence](references/session-resume-evidence.md).

### agy will not tell you a resume failed — the script does

Give codex or claude an unknown session id and they exit 1 with a clear message.
Give **agy** one and it **silently starts a brand-new conversation and exits 0**,
answering from a cold context with nothing on stderr to say so.

For a fixpoint council that is the worst failure available: round 3 believes it
is talking to the reviewer that settled rounds 1–2 and instead gets a stranger
who re-litigates them. So on `--resume` the script compares the conversation id
agy *logged* against the one it was *asked* for, and **exits 4** on a mismatch:

```
Error: agy did NOT resume 00000000-… -- it started d74dd188-… instead,
       so this reply has no memory of the earlier rounds
```

Being unable to determine the id counts as a mismatch too — it fails closed on
purpose, since "assume the resume we cannot confirm probably worked" is the
silent failure again with an extra step. **Exit 4 always still prints the
reply** — it is a real answer, just a cold one — and reports the id of the
conversation agy actually used on stderr. It does **not** record that id in
`--session-id-file`: the stranger has no history in it, and writing it would
promote the cold conversation to being the seat. The file is left empty.

`--resume ""` is a hard error rather than quietly meaning "fresh": the intended
call is `--resume "$(cat sid)"` and that file is empty exactly when a previous
round failed to determine its id.

### Chaining rounds (council use)

Round 1 asks for the id; every later round passes it back. Two files per seat —
one for the prompt, one for the id:

```bash
# A private directory, not a predictable /tmp path: on a shared machine anyone
# can pre-create /tmp/council-codex.sid, and it is the seat of the whole round.
council=$(mktemp -d /tmp/council.XXXXXX)
prompt="$council/prompt.txt"

# Round 1: full context, fresh seat.
cat > "$prompt" <<'P'
Review this diff for correctness bugs. <full diff here>
P
timeout 900 ~/.claude/skills/ask-agent/scripts/agent-query.sh codex \
    --session-id-file "$council/codex.sid" --prompt-file "$prompt"

# 2>/dev/null: on a run that failed before reaching the agent the file is left
# untouched, which can mean it does not exist. Unguarded, that aborts a caller
# running under `set -e`.
seat=$(cat "$council/codex.sid" 2>/dev/null || true)   # keep it in a variable too
[[ -n "$seat" ]] || { echo "round 1 yielded no session id; cannot chain" >&2; }

# Round 2..n: the fix delta ONLY. The seat still remembers round 1, so there is
# no need to re-feed the diff, the findings, or what was already agreed.
cat > "$prompt" <<'P'
Here is the delta that fixes your findings. Did any fix introduce a new bug?
<git diff <last-reviewed-sha>..HEAD>
P
timeout 900 ~/.claude/skills/ask-agent/scripts/agent-query.sh codex \
    --resume "$seat" --prompt-file "$prompt"
rc=$?
case $rc in
    0) ;;                                     # warm seat, real answer
    4) echo "seat went cold — redo this round, do not count it" >&2 ;;
    5) echo "answer is good but the id was not recorded — do not trust the file" >&2 ;;
    *) echo "seat failed with $rc" >&2 ;;
esac
rm -r -f "$council"
```

Points that matter in a council:

- **Check the exit status, and 4 specifically.** 4 means the seat answered
  without the earlier rounds; its "no new findings" is not a convergence signal
  and the round should be redone (or restarted fresh, with context re-fed).
- **One sid file per seat.** Seats run in parallel; a shared file is a race.
- **One round at a time per seat.** A codex thread has a single active writer:
  a second `resume` of the same seat while the first is still running — or while
  that thread's interactive TUI is open — fails with `thread-store conflict:
  thread <id> already has an active writer` and exit 1. Different seats in
  parallel is fine and is what a council does; the same seat twice at once is
  not. It fails loudly, so it needs no guard, but it will stop a round.
- **Fresh seats need no `--resume`.** Round 1 just asks for the id.
- **Keep the id for the whole fixpoint loop, not just one round.** The point is
  that round 4 still remembers round 1, which is what makes "re-run the council
  on the fix delta only" cheap enough to run to convergence.
- **On a resume round `--session-id-file` tells you nothing new** — resume
  yields the id you passed it. Skip it. In particular do not aim it at the same
  file you read the id *from*: that file is the seat, and a round that comes
  back 4 (or cannot determine an id) would empty it, leaving you nothing to
  retry with. Keep the warm id in a shell variable as well as a file.

## Notes

- Response is synchronous - the calling agent waits for the response
- Useful for getting a second opinion or different perspective
- Each agent has different training data and reasoning patterns
- Exit status is the agent's own, plus three of the script's: **3** = agy's
  reply did not carry the end-of-prompt sentinel (it may have answered on a
  partial prompt); **4** = `--resume` did not demonstrably land in the
  requested session; **5** = the run was fine but the id could not be written
  where `--session-id-file` asked — which matters because the destination may
  still hold the *previous* round's id, and the status is the only thing that
  tells you not to chain onto it. All three still print the reply. 3 outranks
  4 outranks 5, and the agent's own non-zero status outranks all of them.
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

### Session resume has its own tripwire

`scripts/test-session-resume.sh` covers `--resume` / `--session-id-file` the
same way — the real script against stub `claude`, `codex` and `agy` binaries,
no network and no agent state touched. **Run it after touching option parsing,
the per-agent command build, the agy log handling, or the tail of the script.**

```bash
.claude/skills/ask-agent/scripts/test-session-resume.sh
```

What it pins, and why each one is there:

- the agy id comparison actually firing — a silent fork must be exit 4, not 0,
  and that check is the entire reason `--resume` is safe to point at agy;
- `--session-id-file` getting the right thing in *both* directions: a round
  that cannot determine an id leaves it empty rather than holding the
  *previous* round's (which would chain the next round onto the wrong thread
  while looking perfectly healthy), while a run that never reached an agent at
  all — a typo'd agent name, a bad `--dir` — leaves it untouched rather than
  throwing away a warm seat;
- the reply outranking the bookkeeping: the id is recorded in front of the
  reply on the agy path, under `set -e`, with the reply's capture file already
  unlinked, so a failing write there must not be able to abort the script;
- the **negative** argv assertions — a plain query must not grow `--log-file`
  or `--session-id`, or every existing caller changes behaviour at once;
- the codex capture path keeping the reply, the exit status and live stderr, and
  forwarding TERM, since it is the one path that gave up `exec` and so the one
  path that can drop any of them or orphan an agent under `timeout`.

### Known residuals

- **If the `--session-id-file` destination directory becomes unwritable *during*
  a run**, the 0600 scratch file created beside it at startup cannot be removed
  and is left behind. Same residual class as the agy staging directory. The run
  itself is unaffected: the reply is printed and the status is 5.
- **The id file is written by rename, so it gets a fresh inode each round.** A
  destination deliberately made group-readable (a sid file shared between two
  processes) reverts to 0600 on the first write. One file per seat, which is
  the advice anyway, makes this moot.
- **A signal arriving between arming the traps and learning the child's pid** is
  remembered and forwarded once the pid is known, but only the *last* such
  signal is kept if several distinct ones land in that window. Forwarding one
  signal is what matters here; the window is microseconds wide.

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
