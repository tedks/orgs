# standup — keep a working agent's OODA loop open

A **standalone** first stab at the situational-awareness layer
([design](../docs/design/situational-awareness.md)). It keeps one or more
coding agents on track by forcing them to *observe* the outside world at
chokepoints they cannot avoid — rather than trusting them to remember to
check. It needs **no org hierarchy**: point it at a repo and some agents and
it works. That is the deliberate bet — the standup may be most of the value
of the whole "virtual engineering org" with little of the machinery, so it is
built self-contained and extractable.

## The idea in one line

The agent you most need to redirect is the one that has stopped observing
(rabbit-holing *is* a collapsed OODA loop), so the **environment** forces the
Observe — not the agent's goodwill.

## Parts

- **`bus.sh`** — a git-native, file-backed message bus. Delivery is
  *constructed* (a message is in the inbox or it isn't; it moves to
  `delivered/` only once actually shown), which is why it can't silently drop
  a redirect. Severities: `info | redirect | halt`.
- **`guard.sh <agent> -- <cmd...>`** — the forced-observe wrapper. Wrap the
  tools an agent uses in its dev loop (tests, build, git); it runs the
  command, appends any pending bus messages as a footer the agent can't miss
  (it ran the command to read the result), and on a pending `halt` forces a
  nonzero exit (code 87) so the agent treats it as a stop-and-reorient.
- **`standup.sh`** — the Observe step for a lead or human: `observe` reads
  git history + status files, flags stalls (no commit past a threshold =
  candidate rabbit-hole), and `redirect`/`halt` queue guidance the guarded
  tools will deliver.

## Use it on any repo (no org required)

```bash
# an agent works with its dev tools wrapped:
alias t='/path/standup/guard.sh worker-a -- pytest -q'
alias g='/path/standup/guard.sh worker-a -- git'

# a watcher (human, /loop, or a lead) checks in and redirects:
standup/standup.sh observe
standup/standup.sh redirect worker-a "You're rebuilding retry logic that already lives in lib/retry.py — stop and use it."
standup/standup.sh halt     worker-a "Scope creep: this PR grew past its package. Stop; we'll re-cut it."
```

Next time `worker-a` runs `t` or `g`, the redirect is appended to the output;
a `halt` makes the command "fail," forcing the reorient.

## Relationship to the org

In the full org, the standup's triggers are the tripwires (budget, Crystal
conflict, stop-condition) and its digest includes contract deltas and peer
status — `situational_awareness()` as the union of all forced observes. But
none of that is required to get the core value here: this component stands on
its own, and if it proves to be the 80/20, it lifts out of this repo whole.

## Not yet (v1 backlog)

Cadence-forced observe (inject every Nth call), the git-hook gate (block a
commit until acknowledged), preempt-and-resume wired to a budget tripwire, and
an MCP `situational_awareness()` pull tool for interactive agents. See the
design doc. This first stab is the bus + the tool-piggyback delivery + the
observe/redirect runner — enough to force an observe in a real dev loop.

## Tests

`test-standup.sh` — exercises bus delivery, one-shot semantics, the guard
footer, and the halt→nonzero override, each mutation-checked (removing the
mechanism makes its case go red).
