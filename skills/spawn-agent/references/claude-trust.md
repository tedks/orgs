# Claude Code workspace trust

Claude Code has its own dialog, shown the first time it starts somewhere whose
trust it cannot resolve:

```
Quick safety check: Is this a project you created or one you trust?
Claude Code'll be able to read, edit, and execute files here.

❯ No, exit
  Yes, I trust this folder

Enter to confirm · Esc to cancel
```

**Which button is the default is build-specific — do not assume either way.**
Both of these were observed on one machine on the same day, an auto-update
having re-pointed the `claude` symlink between them:

```
v2.1.261:  ❯ No, exit                    / Yes, I trust this folder
v2.1.220:  ❯ 1. Yes, I trust this folder / 2. No, exit
```

So a blind Enter may *decline* on one build and silently **grant trust to a
directory nobody vetted** on another — the same failure this skill already
treats as serious for agy. On the declining build the damage is quieter but
real: the window exits, tmux reaps it, an unguarded spawner reports success
having launched nothing, and the refusal is persisted.

Detection matches fragments present in **both** layouts, so it fails closed on
both. Note that `--verify` **cannot** catch this class of drift: it compares a
trust *prediction* against observation, and both layouts observe as a prompt.

**How trust actually resolves.** Two rules, both counter-intuitive, both
established by extracting the resolver from the Claude binary rather than
inferred from behaviour — an inferred rule was wrong, and so was the first
port:

- **Only a truthy entry grants.** A `false` entry does *not* veto; it is
  skipped and the walk continues upward. `false` is also what Claude writes by
  default for any project it opens — observed on a directory it trusted by
  inheritance without ever showing the dialog — so a `false` entry is **not**
  evidence that anyone declined anything.
- **The walk stops at the project container** — the directory holding the git
  *common* dir, shared by every worktree of a repo. A truthy entry above that
  boundary never applies, so `~/Projects: true` does **not** blanket-trust the
  repos beneath it. Outside a repo the walk runs to `/`.

In a bare-repo-plus-worktrees layout the boundary is the project directory, not
the individual worktree — which is why `~/Projects/foo: true` covers every
worktree of `foo`, and why a repo whose own entry is missing or `false` prompts
regardless of anything set above it.

There is no CLI flag and no settings.json key for any of this: `~/.claude.json`
is the only store, and it is Claude Code's own state file rather than a
supported configuration surface. It follows that the model above **will drift**.
`--verify` exists to notice when it does.

Use `--check <dir>` to see what a directory resolves to and why, `--verify` to
confirm that prediction against a live Claude, and `--trust` to grant
deliberately before launch.

## agy and the workspace trust prompt

The **first** interactive `agy` in a directory it has not been trusted with
opens a modal before the composer exists:

```
Do you trust the contents of this project?

Antigravity CLI requires permission to read, edit, and execute files here.

> Yes, I trust this folder
  No, exit

  ↑/↓ Navigate · enter Confirm
```

The default button is *Yes* and the footer is *enter Confirm*, so a blind
`Enter` grants trust — and answering it writes the directory into
`trustedWorkspaces` in `~/.gemini/antigravity-cli/settings.json`, permanently.

**The spawner never answers it.** When that modal is on screen the spawn fails
immediately, having sent no keystroke at all, and tells you to answer it
yourself. Granting a coding agent read/edit/execute over a directory is an
operator decision, not something a script should make on your behalf while you
are looking elsewhere.

So: attach to the session, answer the prompt, then re-run the spawn.

This is also why the readiness check waits for the composer *specifically* — its
rule line **and** its `? for shortcuts` hint — rather than for any box-drawing
character. The banner draws rules before the input box is live, and the modal
draws none at all; matching on rules alone pasted into whatever happened to be
on screen.
