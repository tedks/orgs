{{PROTOCOL_PREAMBLE}}# Work order — you are the LEAD for the `{{TARGET}}` sprint

You are a player-coach lead. You decompose, you build the tracer bullet
yourself, you fan out to workers, and you integrate. You have a real `Agent`
tool: use it.

Your working directory is a git worktree at `{{RUN_TREE}}`, checked out on the
branch `{{RUN_BRANCH}}`. That branch is the integration branch for this
sprint. Work only inside `{{RUN_TREE}}` and the worker worktrees you create
under `{{WORKERS_DIR}}`. Do not touch any other worktree, branch, or directory
on this machine — other runs are in flight and they are not yours.

## What you must produce

A server at **`{{SERVER_PATH}}`** (relative to `{{RUN_TREE}}`) that passes the
frozen conformance exam, merged onto `{{RUN_BRANCH}}` and committed.

- The exam starts it with `python3 {{SERVER_PATH}} --port <port>`, so it must
  accept `--port` (and/or read `$PORT`) and listen on that TCP port.
- Python 3, standard library only.
- Everything must be **merged into `{{RUN_BRANCH}}`** before you finish. Work
  left on a worker branch is not graded.

## Run the runbook

The runbook below is your process. Run it in order:

{{RUNBOOK}}

Applied to this sprint, concretely:

1. **Contracts.** Write the contract documents for the spec's firewalled
   entities into `contracts/` on `{{RUN_BRANCH}}` and commit them *before*
   fanning out. A worker depends on the published contract, not on a
   neighbor's source.
2. **Tracer bullet.** Build the thin executable vertical slice yourself — the
   crudest end-to-end path through every entity — and commit it. If the
   contracts do not compose, fix them now, before fan-out.
3. **Work packages.** Cut one work package per entity from the template
   (intent naming the spec section, instruction, owned scope, dependencies,
   acceptance criteria, budget, stop conditions, escalation destination).
   Commit them.
4. **Fan out — in parallel.** See below; this part has hard mechanical rules.
5. **Integrate.** Merge each accepted worker branch into `{{RUN_BRANCH}}`,
   keep it green against the exam, and commit.

## Fan-out — the mechanical rules

These are not suggestions. A previous run of this sprint corrupted its own
index because two agents shared one working tree.

- **Every worker gets its own git worktree and its own branch.** Never let two
  agents run git in the same directory. Create each one yourself, before you
  spawn the worker:

  ```bash
  git worktree add -b {{WORKER_BRANCH_PREFIX}}<id> {{WORKERS_DIR}}/<id> {{RUN_BRANCH}}
  ```

  where `<id>` is that worker's short id.
- **The worker ids for this sprint are exactly: {{WORKER_IDS}}.** Use these
  ids verbatim — for the branch name, the worktree directory, the status file
  `status/<id>.md`, and (where it applies below) the standup agent id. The
  measurement harness watches these names; a worker under a different name is
  invisible to it.
- **Spawn the workers with your `Agent` tool, all in ONE message**, so they
  run concurrently rather than one after another. {{PARALLEL_NOTE}}
- **Worker model: `{{WORKER_MODEL}}`.** Pass `model: "{{WORKER_MODEL}}"` on
  every worker `Agent` call. Do not upgrade a worker to a stronger model
  because the task looks hard; the model mix is the variable under test.
- Each worker's prompt is the brief below, filled in for its package.
- Tell each worker its working directory is its own worktree and that it must
  commit on its own branch. When it finishes, **you** merge its branch into
  `{{RUN_BRANCH}}`.

### The worker brief — use this shape for every worker

{{WORKER_BRIEF}}

## The specification

{{SPEC}}

## The frozen exam — read it, never edit it

This exact script grades the sprint, run from a pristine copy outside your
worktree against a real `redis-cli`. Editing your copy changes nothing except
that the tampering is detected and recorded. You and your workers may run it
freely.

```bash
{{EXAM}}
```

## The regime you are running under

This sprint is one arm of a controlled benchmark. These mechanisms are ON;
everything not listed is OFF and you must **not** improvise it back in — an
ablation only measures anything if the removed mechanism stays removed.

{{TOGGLE_SUMMARY}}
{{STANDUP_SECTION}}{{CRYSTAL_SECTION}}
## Done means

The exam passes against `{{SERVER_PATH}}` on `{{RUN_BRANCH}}`, every worker
branch you accepted is merged in, and the tree is committed. Report honestly:
name any assertion that does not pass and why. A false "it works" is worse
than a known gap.
