---
name: council-review
description: Multi-agent code review council - one seat per provider (Claude, Codex, Antigravity/agy), reviewed simultaneously; the host fills its own provider's seat with its native subagent and the foreign seats via ask-agent
argument-hint: '[target] — e.g. PR #42, staged, branch, or a file path'
---

# council-review

Launch a code review "council" — get one review per AI provider (Claude, Codex, agy) simultaneously, then synthesize the results.

## Usage

```
/council-review [target]
```

## Arguments

- `[target]`: What to review (optional, defaults to uncommitted changes)
  - `staged` — review staged changes (`git diff --cached`)
  - `branch` — review all commits on this branch vs main/master
  - `PR #<number>` or `#<number>` — review a pull request
  - `<file-path>` — review a specific file
  - *(no argument)* — review all uncommitted changes (`git diff HEAD`)

## Provider-aware seating

This one SKILL.md is loaded by every host (Claude Code reads it from
`~/.claude/skills`, Codex from `~/.codex/skills`, which symlinks to the same
directory). The council has **one seat per model provider**, and which seat is
*yours* depends on which host you are running as — identify yourself from your
own harness/system prompt, not from anything in the repo.

Seats are named by the `/ask-agent` CLI name, but identity is the **provider**
behind it: `claude` = Anthropic, `codex` = OpenAI, `agy` = Google. A host is
"the same provider" as a seat when its model comes from that provider,
whatever the CLI is called — a Gemini CLI host owns the `agy` seat.

| Host you are running as | Your own seat — **native subagent** | Foreign seats — **`/ask-agent`** |
|-------------------------|-------------------------------------|----------------------------------|
| Claude Code (Anthropic) | Claude, via the `Agent` tool with `model: opus` | `/ask-agent codex -m gpt-6-sol` + `/ask-agent agy` |
| Codex CLI (OpenAI)      | Codex, via `multi_agent` with `model: gpt-6-sol` | `/ask-agent claude -m opus` + `/ask-agent agy` |
| Antigravity / Gemini CLI (Google) | agy, via its own Lead-tier in-process delegation if it has one — otherwise the inline fallback below | `/ask-agent claude -m opus` + `/ask-agent codex -m gpt-6-sol` |
| a host from a fourth provider | your own provider's Lead-tier native subagent — a **fourth** seat | `/ask-agent claude -m opus` + `/ask-agent codex -m gpt-6-sol` + `/ask-agent agy` |

The same thing as an algorithm, for a host the table does not name:

```
me    = the PROVIDER my model comes from          # Anthropic | OpenAI | Google | <other>
seats = {Anthropic: claude, OpenAI: codex, Google: agy}   # provider → /ask-agent CLI name
if me not in seats: seats[me] = <no CLI>          # a fourth provider adds a seat, never loses one
for (provider, cli) in seats:
    if provider == me:  fill it with my native/internal subagent
                        (cannot run → review inline yourself, record "(inline)";
                         NEVER /ask-agent <cli> — that is my own provider)
    else:               fill it with /ask-agent <cli>
                        (unavailable → leave the seat EMPTY and say so; never backfill)
```

Compare **providers**, never CLI names against a provider: an unlisted
Anthropic host is `me = Anthropic`, which owns the `claude` seat — it does not
ask-agent `claude` and then add itself as a fourth seat.

Rules — these are not style preferences, they are what makes the council a council:

1. **Your own provider's seat is always your native subagent.** Never
   `/ask-agent` your own provider: Claude must not ask-agent `claude`, Codex
   must not ask-agent `codex`, agy must not ask-agent `agy`. Doing so spawns a
   second instance of your own provider through a CLI — the same model family
   with correlated blind spots (even if a different model or config is picked),
   and none of your project context — and fills a seat that was supposed to
   bring a different provider to the table.
   **If your native subagent cannot run** (facility unavailable, own-provider
   usage limit, a host with no delegation at all), review inline yourself and
   record the seat as `(inline)`. That is still your provider's seat, filled by
   your provider. It is never filled through `/ask-agent`.
2. **Every foreign seat goes through `/ask-agent`.** That is what gives the
   council provider diversity. Do not make the council internal-only, and do
   not "save time" by having your native subagent play a foreign seat.
3. **An unavailable foreign reviewer leaves an empty seat, noted in the
   summary.** Not installed, usage limit, timeout, the agy permission flake —
   whatever the cause, report which seat is missing and continue with the
   rest. Do **not** substitute a second native subagent, or any other reviewer
   from your own provider, for the missing one: two reviews from one provider
   are one opinion twice, and a summary that hides the gap overstates the
   consensus.

4. **Seats run at the Lead tier, never Frontier unless the CEO asks.** Councils
   burn Frontier quota when a seat inherits the host's model. Pin the model on
   every seat: the Claude native seat is spawned with `model: opus`; the Codex
   native seat with `model: gpt-6-sol`; the foreign Codex seat with `/ask-agent
   codex -m gpt-6-sol`; the foreign Claude seat with `/ask-agent claude -m
   opus`; agy uses its default Lead tier. A Frontier model (Fable, Astra) sits
   a seat only when the CEO asks for it on that review, and the record says so
   (CEO ruling, 2026-10-13).

## Instructions

When this skill is invoked, follow these steps:

### Step 1: Determine what to review

Based on the `[target]` argument (or lack thereof), gather the review material:

| Target | How to gather context |
|--------|----------------------|
| *(none)* — `worktree` in Step 3 | `git diff HEAD` (all uncommitted changes — staged and unstaged) |
| `staged` | `git diff --cached` |
| `branch` | Detect default branch (see below), then `git log --oneline <default>..HEAD` + `git diff <default>...HEAD` |
| `PR #N` / `#N` | `gh pr view N` (title + description — the *why*, which reviewers need for design/scope calls), then `gh pr diff N` |
| `<file>` | Read the file contents |

**Detecting the default branch:** Run `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|.*/||'`. If that fails, check whether `main` or `master` exists as a local branch.

Run the diff command now and look at it: if the diff is empty, tell the user
there's nothing to review and stop. Do **not** stash it in a variable or a
file for later — nothing survives from one tool call to the next (see the
comment in Step 3), so Step 3 runs the same command again inside the one call
that builds the prompt.

### Step 2: Build the review prompt

Construct the review prompt text. The diff/context is **not** pasted here —
Step 3 appends it, inside the one call that builds the prompt file:

```
Review the following code changes. For each issue found, cite the specific file and line.

Organize your review into these sections:
- **Critical** (bugs, security issues — must fix)
- **Important** (design problems, missing edge cases — should fix)
- **Nits** (style, naming, minor improvements — nice to fix)

If the code looks good, say so briefly and note any minor suggestions.
```

The prompt should cover: correctness, security, design, edge cases, and concrete suggestions.

### Step 3: Launch every seat in parallel

Seat the council per the matrix above: one native subagent for your own
provider, one `/ask-agent` per foreign provider. Start every seat
**concurrently** — as separate tool calls, or in whatever parallel batch your
host supports; the native subagent and the `/ask-agent` shell calls are
different mechanisms, and "launch together" never means "put your own provider
in the `/ask-agent` batch". Every seat gets the **same review prompt with the
diff inline**, staged in two files inside one per-invocation directory — the
bare prompt for your own seat, and the same prompt behind a "do not run
commands" opener for the foreign seats:

```bash
# ONE tool call, start to finish. Every shell tool call is a fresh process:
# a variable set in an earlier call is empty here, a file a trap deleted on
# that call's exit is gone, and `cat ""` fails quietly into a prompt that has
# no diff in it. So: no `trap ... EXIT`, the context command runs HERE (not
# "saved from Step 1"), the result is size-checked, and the literal paths this
# prints are what every launch uses. This machine runs many concurrent
# council-review invocations at once, so everything is staged inside one
# mktemp -d directory, never as flat files directly under /tmp — that is what
# lets cleanup rm -rf just this invocation's directory instead of glob-deleting
# across /tmp and catching another session's in-flight files. rm -rf the
# printed $WORK dir after Step 4.
TARGET='pr'        # what Step 1 decided: pr | staged | branch | file | worktree
PR='N'             # pr:     the PR number
DEFAULT='master'   # branch: the default branch Step 1 detected
FILE='path'        # file:   the path — keep the quotes, paths can contain spaces
WORK=$(mktemp -d /tmp/council.XXXXXX) || { echo "council: mktemp -d failed — not launching" >&2; exit 1; }
PROMPT_FILE="$WORK/prompt.txt"
FOREIGN_FILE="$WORK/foreign.txt"
fail() { rm -rf -- "$WORK"; echo "council: $1 — not launching" >&2; exit 1; }
cat << 'REVIEW_EOF' > "$PROMPT_FILE"
<the review prompt from step 2>
REVIEW_EOF
# `before` is taken AFTER any preamble (PR title, branch log) and BEFORE the
# diff, so the guard measures the diff alone and a preamble cannot mask an
# empty one. Only the `pr` arm touches gh: a bare `gh pr view` on a branch
# that happens to have a PR would succeed and splice that PR's title into a
# staged/branch/file review.
case "$TARGET" in
  pr)       { gh pr view "$PR" && echo; } >> "$PROMPT_FILE" || fail "gh pr view failed"
            before=$(wc -c < "$PROMPT_FILE")
            gh pr diff "$PR" >> "$PROMPT_FILE" || fail "gh pr diff failed" ;;
  staged)   before=$(wc -c < "$PROMPT_FILE")
            git diff --cached >> "$PROMPT_FILE" || fail "git diff failed" ;;
  branch)   { git log --oneline "$DEFAULT..HEAD" && echo; } >> "$PROMPT_FILE" || fail "git log failed"
            before=$(wc -c < "$PROMPT_FILE")
            git diff "$DEFAULT...HEAD" >> "$PROMPT_FILE" || fail "git diff failed" ;;
  file)     before=$(wc -c < "$PROMPT_FILE")
            cat < "$FILE" >> "$PROMPT_FILE" || fail "cannot read $FILE" ;;   # redirection: `-` and `--help` are filenames here, never options or stdin
  worktree) before=$(wc -c < "$PROMPT_FILE")
            git diff HEAD >> "$PROMPT_FILE" || fail "git diff failed" ;;
  *)        fail "unknown target '$TARGET'" ;;
esac
[[ $(wc -c < "$PROMPT_FILE") -gt $before ]] || fail "nothing to review for target '$TARGET'"
{
  echo "Everything you need is in this prompt. Do not run any commands and do not fetch anything — review only what is written below."
  echo
  cat "$PROMPT_FILE"
} > "$FOREIGN_FILE"
echo "$WORK $PROMPT_FILE $FOREIGN_FILE"
```

The opener goes to every foreign seat and **only** to foreign seats. It is
there because `claude -p` runs under whatever permission settings the machine
has (bare `claude -p`, no permission flags — see `agent-query.sh`) and may not
be allowed to run `gh`, and `codex exec` may or may not have network from
inside its sandbox: telling either to pull the PR is a gamble that costs a
wasted turn at best and an "I couldn't fetch the diff" non-review at worst.
Inline is right for all of them, and it is what makes the seats comparable:
they all reviewed the same bytes. Your **own** seat must *not* get the opener:
its native subagent has tools and project context, and that context — reading
the post-change files, not just the diff — is the whole reason the seat exists
(see Notes). Hand it `$PROMPT_FILE` and tell it so.

Then, per seat:

| Seat | If this is **your own** provider | If this is **foreign** to you |
|------|----------------------------------|-------------------------------|
| Claude | native subagent (Claude Code: `Agent` tool, `model: opus`) given `$PROMPT_FILE`, told it has tools and project context and should read the post-change files (and the PR number, for a PR target) | `/ask-agent claude -m opus --prompt-file "$FOREIGN_FILE"` |
| Codex | native subagent (Codex CLI: `multi_agent`, `model: gpt-6-sol`) given `$PROMPT_FILE`, same instruction | `/ask-agent codex -m gpt-6-sol --prompt-file "$FOREIGN_FILE"` — **from a trusted directory**: any git repo (the worktree), or a directory trusted in Codex's config. `codex exec` refuses to start anywhere else — `-d /tmp`, or a non-repo scratch dir, fails with "Not inside a trusted directory" and you get no review |
| agy | in-process delegation if it has one, else inline (see Rule 1) — given `$PROMPT_FILE` | `/ask-agent agy -d /tmp --prompt-file "$FOREIGN_FILE"` — `-d /tmp` is **required** here and only here, see below |

`-d` is a plain working-directory option in `agent-query.sh`, valid for every
agent; it is the two CLIs' behaviour that differs. agy needs a neutral cwd so
nothing invites exploration; codex needs a trusted one. claude is indifferent,
so leave it off.

> **agy cannot fetch anything.** Headless agy has no usable tool access: the
> `command` permission cannot be prompted for in headless mode and is
> auto-denied, so `gh pr diff`, `git`, `cat` — anything but reading the one
> staged prompt file — will fail. See ditz `agy-headless-command-permission`;
> granting it is an operator decision and is deliberately not part of the
> tooling.
>
> The denial shows up in one of two ways, and **neither is review content**:
> the *hard* shape produces no output at all, while the *soft* shape puts the
> denial text on stdout, where it looks superficially like a reply. ask-agent
> retries once and normally absorbs both — so if that text ever does reach you,
> read it as the flake, not as agy's opinion of the diff.
>
> So for **every** agy review: put the complete diff *in the prompt*, tell it
> explicitly not to run commands or fetch anything, and run it from a neutral
> directory so nothing in the cwd invites exploration:
>
> ```bash
> /ask-agent agy -d /tmp --prompt-file "$FOREIGN_FILE"
> ```
>
> and open the prompt with a line like: *"Everything you need is in this
> prompt. Do not run any commands and do not fetch anything — review only what
> is written below."*

#### Worked example: a Claude Code host

Concurrently: (1) own seat — `Agent` tool with `$PROMPT_FILE` and the
"you have project context, read the files" instruction; (2) foreign —
`/ask-agent codex -m gpt-6-sol --prompt-file "$FOREIGN_FILE"` from the worktree; (3)
foreign — `/ask-agent agy -d /tmp --prompt-file "$FOREIGN_FILE"`. A Codex host
swaps (1) for its built-in subagent and (2) for `/ask-agent claude -m opus
--prompt-file "$FOREIGN_FILE"`; any other host applies the matrix.

Reading the staged prompt file is the *one* tool agy is permitted (that is
what `--add-dir` grants); anything else is auto-denied and costs you the whole
review.

### Step 4: Present the council's findings

Once every seat has answered (or been recorded as missing), present a unified summary:

```markdown
## Council Review Summary

Seats: <own provider> (native subagent | inline), <foreign> (ask-agent), <foreign> (ask-agent — MISSING: <reason>)

### Consensus (issues flagged by 2+ reviewers)
- ...

### <seat>'s Review
<summary of unique points>

### Recommendations
<synthesized action items, prioritized>
```

Fill the `Seats:` line in from *your* host — it is a template, not a Claude
Code example — and write one `<seat>'s Review` section per seat that answered,
in `Seats:` order. The `Seats:` line records which seats were native (or inline) and which
foreign, and names any seat that went unfilled. Highlight **consensus issues**
(flagged by multiple reviewers) as highest priority — these are almost
certainly real. Different agents may describe the same issue differently, so
match semantically, not by wording. Note any disagreements between reviewers
as discussion points.

Omit the review section for a seat that failed to respond, but keep it in the
`Seats:` line — a missing seat is a fact about the round, not something to
tidy away. Consensus is counted over the seats that actually answered, and it
is a **prioritisation signal, not a filter**: with two seats it means both
agreed, with one seat there is no consensus section at all — and every
Critical/Important still gets triaged regardless.

Then remove the staged directory (`rm -rf` the `$WORK` path Step 3 printed)
— there is no trap doing it for you. Removing that one directory is safe even
with dozens of concurrent council-review invocations on the same machine,
because `mktemp -d` gave it a unique name — unlike a glob-delete over `/tmp`,
which would also catch other sessions' in-flight files. If the literal
`$WORK` path is lost (e.g. to context compaction) before cleanup, **never**
fall back to a pattern or prefix delete over `/tmp` (including
`/tmp/council.*`) to find it — that reproduces the same class of bug one
level up, deleting other sessions' directories instead of just their files.
Leave the orphaned directory; it is one `mktemp -d`'d directory, not a leak
worth another session's files.

## Notes

- All seats run in parallel for speed
- Your native subagent's review has full project context; foreign reviewers only see the diff (or PR)
- If a foreign reviewer fails (not installed, usage limit, timeout, etc.), note it and continue with whatever reviews succeed — **do not** fill its seat with another reviewer from your own provider. If your *own* subagent fails, review inline and record it — **do not** fill your seat through `/ask-agent`
- For the PR merge gate (fixpoint, triage, proportionality, PR record), see "Council review to fixpoint" in the global agent instructions (`~/.claude/CLAUDE.md`, which Codex reads as `~/.codex/AGENTS.md`); this skill is one round of that loop
