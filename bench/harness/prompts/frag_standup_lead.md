
### Standup (ON)

A standup process observes this run on a cadence: it reads git history and
`status/<id>.md`, flags an agent that has not committed in a while as a
candidate rabbit-hole, and may send that agent a redirect.

Redirects reach an agent only through the guard wrapper, so **every worker's
brief must tell it to run its dev-loop commands through the guard** (the line
is already in the brief below — keep it, `STANDUP_BUS` included). Run your own
commands through it too, as `{{LEAD_AGENT_ID}}`:

```bash
STANDUP_BUS={{BUS_ROOT}} {{GUARD}} {{LEAD_AGENT_ID}} -- <your command>
```

`STANDUP_BUS` is load-bearing. Your workers run in **their own worktrees**, and
without it the guard resolves the bus relative to whatever directory the agent
is standing in — a different, empty bus. The redirect is then queued forever
and delivered to nobody. Every guard invocation, yours and theirs, carries it.

Guard exit code **87** means a halt is pending: stop, read, reorient.

The stall signal the standup reads is **your agents' commits** (it matches the
worker id in commit messages across every branch), which is why the brief
requires the id in each commit message. Status files live in each worker's own
worktree and are not visible to the observer until you merge — the commits are
what keep an agent visible.
