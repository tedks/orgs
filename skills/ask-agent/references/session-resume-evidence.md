# ask-agent session resume: what was actually verified

Empirical notes behind the `--resume` / `--session-id-file` support in
`../scripts/agent-query.sh` (ditz `ask-agent-session-resume`).

Everything below was run on 2026-09-01 against **throwaway sessions created for
the purpose** — no pre-existing conversation of the user's was resumed or
mutated. Versions: `claude` 2.1.252, `codex-cli` 0.152.0, `agy` 1.1.3,
`bash` 5.2.21, Linux 6.17.

The point of writing this down is that all three CLIs answer "what does resume
do to the original session?" differently, and one of them answers "what happens
on an unknown id?" in a way that silently destroys the property we are buying.

## Summary

| | resume flag | fork-vs-append | yields id where | unknown id |
|---|---|---|---|---|
| claude | `-p --resume <id>` | **append**, id unchanged | caller can *mint* it with `--session-id <uuid>` | **exit 1**, loud |
| codex  | `codex exec resume <id> -` | **append**, id unchanged, original rollout mutated | stderr header `session id: <uuid>` | **exit 1**, loud |
| agy    | `--conversation <id> -p` | **append**, id unchanged | `--log-file` line `Print mode: conversation=<uuid>` | **exit 0, silently starts a NEW conversation** |

That last cell is the reason the script has an exit-4 guard. See below.

## codex — resume APPENDS to the original rollout; fork does not

Run 1, fresh (`codex exec -` with the prompt on stdin):

```
$ echo "Remember the code word BANANA47. Reply with exactly: OK" \
    | codex exec - --skip-git-repo-check -s read-only
```

- stdout: `OK` — **and nothing else**.
- stderr: the whole banner, including `session id: 01a05f34-ff2b-7d32-aa54-51fb05efa6b4`.
- rollout created: `~/.codex/sessions/2026/09/01/rollout-2026-09-01T19-01-43-01a05f34-….jsonl`,
  **14 lines / 75838 bytes**. Total `*.jsonl` under `~/.codex/sessions`: 549 → 550.

The stream split is load-bearing for this skill: codex's own session-id line is
already on stderr, so capturing it never risks contaminating the reply.

Run 2, resume:

```
$ echo "What was the code word I told you? …" \
    | codex exec resume 01a05f34-ff2b-7d32-aa54-51fb05efa6b4 - --skip-git-repo-check
BANANA47
```

- Warm context confirmed.
- Header reports **the same** `session id: 01a05f34-…`.
- The **same** rollout file grew **14 → 26 lines, 75838 → 93256 bytes**.
- Total `*.jsonl` unchanged at 550 — no new file anywhere.

**So `codex exec resume` appends in place and mutates the original rollout.**
There is no forked continuation file and no new id.

Run 3, fork, for contrast:

```
$ echo "Reply with exactly the code word again." \
    | codex exec fork 01a05f34-… - --skip-git-repo-check
BANANA47
```

- Header reports a **new** `session id: 01a05f36-82f8-7f00-a121-c399b7c81ce4`.
- The original file is **untouched** — still 26 lines / 93256 bytes.
- Total `*.jsonl`: 550 → 551.

So `resume` and `fork` are exactly the two halves you would want, and codex
gives you the choice. `agent-query.sh` exposes only `resume`: a council round
*wants* the seat's history to accumulate. If you ever need to branch a
reviewer's context without touching the canonical thread, `codex exec fork` is
the primitive — deliberately not wrapped here.

### codex option surface differs between `exec` and `exec resume`

`codex exec resume` is **not** `codex exec` plus an id. It rejects several
options the parent subcommand takes:

```
$ echo … | codex exec resume <id> - --skip-git-repo-check -s read-only
error: unexpected argument '-s' found
```

Accepted by `exec resume`: `-c/--config`, `--last`, `--all`, `--enable`,
`--disable`, `-i/--image`, `--strict-config`, `-m/--model`,
`--dangerously-bypass-*`, `--thread-source`, `--skip-git-repo-check`,
`--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--output-schema`,
`--json`, `-o/--output-last-message`.

**Not** accepted: `-s/--sandbox`, `-C/--cd`, `--add-dir`, `--approve-for-me`,
`-p/--profile`.

`agent-query.sh` only ever passes `-m`, which survives the move, so the resume
path takes the same options as the fresh path. Anyone adding a codex option to
this script must check it against *both* lists.

On sandboxing: because `exec resume` has no `-s`, it uses the config default.
This is not a downgrade introduced by resume — `agent-query.sh` has never
passed `-s` either, so both paths land on the same `sandbox_mode` from
`~/.codex/config.toml`. Worth knowing, not worth "fixing" here.

## claude — the caller can choose the id up front

`claude` has `--session-id <uuid>`: "Use a specific session ID for the
conversation". That removes the parsing problem entirely for the fresh case —
the id is an *input*, not something to scrape out of the output.

```
$ CID=$(cat /proc/sys/kernel/random/uuid)
$ echo "Remember the code word CHERRY91. Reply with exactly: OK" | claude -p --session-id "$CID"
OK
$ echo "What was the code word? …" | claude -p --resume "$CID"
CHERRY91
```

- stdout carries the reply and nothing else; stderr was empty on both runs.
- On disk: `~/.claude/projects/<slug>/<uuid>.jsonl`, and after the resume the
  project directory still holds **exactly one** jsonl. Append, no fork, id
  unchanged — same shape as codex.
- `claude --fork-session` exists for the other behaviour; not wrapped here, same
  reasoning as `codex exec fork`.

Because the id can be minted, the claude path never has to capture anything and
keeps its `exec` (see "why exec matters" below).

## agy — the ids are on disk, and an unknown id fails *silently*

### Where the ids live

`agy conversations list` needs a TTY (bubbletea), but the state behind it does
not: every conversation is its own SQLite file.

```
~/.gemini/antigravity-cli/conversations/<conversation-uuid>.db   (+ -shm, -wal)
```

1195 files / 403 distinct `.db` at the time of writing. So conversation ids
*are* enumerable from a script — no TUI scraping, no tmux window.

Diffing that directory around a run would work, but it races any other agy
process. There is a better, per-run signal.

### Getting the id of *this* run: `--log-file`

`agy --log-file <path>` redirects the CLI log, and print mode logs the
conversation id twice:

```
server.go:891]   Created conversation e3beb82f-5a5c-4aa7-a410-7a0d2991d4b5
printmode.go:209] Print mode: conversation=e3beb82f-5a5c-4aa7-a410-7a0d2991d4b5, sending message
```

`printmode.go:209` is the one to parse: it is emitted on **both** fresh and
resumed runs, whereas `Created conversation` only appears when a new one is
made. Verified properties of `--log-file`:

- It is a **complete** redirect — no new file appeared in
  `~/.gemini/antigravity-cli/log/`, and the `cli.log` symlink was left pointing
  at the previous session's log.
- The log records `promptLength=184` but **not the prompt text** (grepped for
  three distinct strings from the prompt: zero hits). It is still created mode
  0644, so the script keeps it inside a 0700 directory anyway.
- Redirecting means an ask-agent run no longer leaves a log in agy's default
  directory, which is why the script only passes `--log-file` when it actually
  needs the id.

### `--conversation` does work headlessly with `-p`

```
$ agy --log-file … --conversation 1500ab20-4c78-4d32-9732-d827a37de9ba \
      -p "What was the code word? …"
DURIAN63
```

- Warm context confirmed, with no `--add-dir` needed for the resume itself.
- The log reports `conversationID="1500ab20-…"` on the way in and
  `conversation=1500ab20-…` on the way out — same id.
- `.db` count 405 → 405. **Append, in place**, like the other two.

### The sharp edge: an unknown id is not an error

```
$ agy --conversation 00000000-0000-4000-8000-000000000000 -p "Reply with exactly: HELLO"
HELLO
$ echo $?
0
```

The log tells the real story:

```
Created conversation 77ad09b5-1c88-4e83-979f-46c4635d1145
Print mode: conversation=77ad09b5-1c88-4e83-979f-46c4635d1145
```

`.db` count 405 → 406. agy **silently started a brand-new conversation** and
answered from a cold context, exit 0, nothing on stderr.

For a fixpoint council this is the worst possible failure: round 3 believes it
is talking to the reviewer that already agreed on rounds 1–2, and instead gets a
stranger who will happily re-litigate settled findings — with no signal that
anything went wrong. codex and claude both exit 1 with a clear message here:

```
codex:  Error: thread/resume: thread/resume failed: no rollout found for thread id … (code -32600)
claude: No conversation found with session ID: …
```

**This is why `agent-query.sh` compares the yielded conversation id against the
requested one and exits 4 on a mismatch.** The comparison is free once you are
already parsing the log for the id, and it converts a silent correctness bug
into a loud one.

## Why the claude/codex `exec` matters, and where it had to go

`agent-query.sh` ends with `exec "${cmd[@]}"` for claude and codex. That is
deliberate: the agent inherits the process, so signals, exit status and stdout
streaming are transparent, and there is no wrapper left to go wrong.

Capturing a session id the CLI *generates* is incompatible with that — nothing
survives the `exec` to do the capturing. Mapping out which cases actually need
capture:

| case | id known before the run? | `exec` kept |
|---|---|---|
| claude, fresh | yes — we mint it (`--session-id`) | yes |
| claude, resume | yes — it is the id we passed | yes |
| codex, resume | yes — verified identical (append) | yes |
| **codex, fresh** | **no — only in codex's stderr banner** | **no** |
| agy, either | no — only in the log | n/a, the agy path never `exec`ed |

So exactly one new wrapped path: **codex, fresh, and only when the caller asked
for the id**. Everything else keeps today's behaviour byte for byte.

That wrapped path needs the same signal forwarding the agy path already has —
callers run this under `timeout`, and without forwarding a `timeout` kill would
leave codex orphaned and still billing. Rather than keep two copies of that
subtle logic, it was extracted into `_run_child_capturing` and both paths call
it.

`bash` sets `$!` to the PID of a process substitution and `wait` accepts it,
which is what makes the live-stderr tee deterministic rather than racy:

```
$ { echo hi >&2; } 2> >(tee -- "$f" >&2); tp=$!; wait "$tp"
procsub pid=[941097]; wait rc=0; captured=[hi]      # bash 5.2.21
```

Verified on this fleet's bash 5.2.21. The script does not depend on it being
fatal if absent: an empty `$!` just skips the `wait`, and the worst case is a
missing id, never a corrupted reply.

## End-to-end, through the wrapper

The sections above probe the CLIs directly. These run the finished
`agent-query.sh`, from a git repo (codex refuses to run outside one unless
`--skip-git-repo-check` is passed, which this script does not pass — pre-existing
behaviour, unrelated to resume, and it fails loudly).

**codex, three rounds chained:**

```
$ agent-query.sh codex --session-id-file /tmp/codex.sid \
      "Remember the code word ELDERBERRY12. Reply with exactly: OK"
OK
ask-agent: session id: 01a05f45-8ca0-7ae1-bb59-3d992dac1c66      (stderr)

$ agent-query.sh codex --resume "$(cat /tmp/codex.sid)" \
      --session-id-file /tmp/codex2.sid "What was the code word? …"
ELDERBERRY12
$ cat /tmp/codex2.sid
01a05f45-8ca0-7ae1-bb59-3d992dac1c66      # same id, as append implies

$ agent-query.sh codex --resume "$(cat /tmp/codex2.sid)" "Say the code word one more time…"
ELDERBERRY12
```

**claude:** round 1 with `--session-id-file` yielded
`1946616b-2d54-46f4-bc9e-780d14089a32` (the minted id); round 2 with `--resume`
answered `FIGWORT44`.

**agy, genuine resume:** round 1 yielded
`1a8697c7-ed5e-42ee-bb52-ad9dd45d6c80`; round 2 answered `GOOSEBERRY77`, exit 0,
same id back.

**agy, the guard firing on a real agy** — the case bare agy reports as success:

```
$ agent-query.sh agy --resume 00000000-0000-4000-8000-000000000000 \
      --session-id-file /tmp/agy3.sid "What was the code word? …"
I was not provided with a code word in the instructions or our conversation.
$ echo $?
4
```

stderr:

```
ask-agent: session id: d74dd188-5a67-4b49-8edf-4563ced903f7
Error: agy did NOT resume 00000000-0000-4000-8000-000000000000 -- it started
       d74dd188-5a67-4b49-8edf-4563ced903f7 instead, so this reply has no
       memory of the earlier rounds
```

The reply text is itself the confirmation: cold context, exit 0 from agy, exit 4
from the wrapper. That is the whole feature in one run.

## What is covered by tests rather than by this document

`scripts/test-session-resume.sh` runs the real script against stub CLIs — no
network, no agent state — and pins the behaviours above that are cheap to
regress: the agy id comparison firing, `--session-id-file` being truncated so a
failed round cannot leave a stale id, the negative argv assertions (a plain
query must not grow `--log-file` or `--session-id`), and the codex capture path
keeping the reply, the exit status, live stderr and TERM forwarding.

40 assertions. `test-rtrim.sh` still passes unchanged at 112 — the
reply-handling path was not touched.

## Field findings from the orgs council, checked here

Four observations came back from the founding-council session while this was in
review. All four were re-run against this fleet; three confirm, one needs a
correction.

### A codex thread has a single active writer — confirmed

Two `codex exec resume` runs against the same thread at the same time: the first
succeeds, the second fails immediately and loudly.

```
Error: thread/resume: thread/resume failed: thread 01a05f68-… already has an
       active writer (code -32600)
$ echo $?
1
```

The same applies to a thread whose interactive TUI is open. The lock is released
when the writing process exits, so sequential rounds against one seat are fine —
which is the shape the chaining recipe already has.

Consequences for a council, neither of which needs code:

- **Rounds against one seat must be sequential.** Different seats in parallel is
  what the recipe does and is unaffected; two rounds against the *same* seat at
  once is not.
- **It fails at exit 1, not silently**, so it lands in the "the agent's own
  status" category rather than needing a guard like agy's. Nothing to add.

### `codex exec fork` is headless — the TUI-only one is `codex fork`

The field note reported `codex fork <id>` as TUI-only and gave a
`tmux new-session -d 'codex fork <id>'` recipe to materialise a forked thread.
That is right about `codex fork` — the top-level command, which opens a picker —
but there are **two different commands**, and the `exec` one needs no terminal:

```
$ echo "What was the code word?" | codex exec fork 01a05f68-… - --skip-git-repo-check
HONEYDEW08
session id: 01a05fb2-da66-7d30-9c49-a200cb25fc64      (stderr, a NEW id)
parent rollout: 98500 bytes before, 98500 bytes after
```

No TUI, no tmux, warm context, parent byte-identical. So the tmux workaround is
not needed for scripted forking; `codex exec fork` is the headless spelling.
(The field note's other observation stands and matches what is recorded above:
the fork's metadata carries `forked_from_id`, and the parent is untouched.)

### Resume continues the same thread id — confirmed

Already recorded above from the direct probes, and the field note agrees: round
N+1 resumes the same id once round N's process has exited.

### `--json` / `-o` would be a cleaner capture than the banner — confirmed, deferred

`codex exec --json` puts JSONL on stdout, and the **first** line carries the id
in a structured field:

```
{"type":"thread.started","thread_id":"01a05fb2-6561-7eb0-a325-9f367e1e30fd"}
{"type":"turn.started"}
```

with `-o/--output-last-message <FILE>` giving the clean reply text
(`JSONPROBE`, verified). That would retire the banner parsing, the stderr tee,
and the prompt-injection surface the anchoring exists to close.

It is **not** adopted here, for two reasons worth writing down rather than
rediscovering:

- stdout would become JSONL, so the reply could no longer stream to the caller
  live — it would arrive only at the end, out of the `-o` file. Today the reply
  is inherited stdout and streams as codex produces it.
- `-o` is documented as *the last message*, which is not necessarily everything
  the current path prints. That is a change in what callers receive, not just
  in how the id is found.

Tracked as ditz `ask-agent-codex-json-capture` rather than folded into a PR that
had already reached convergence.
