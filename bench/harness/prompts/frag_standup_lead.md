
### Standup (ON)

A standup process observes this run on a cadence: it reads git history and
`status/<id>.md`, flags an agent that has not committed in a while as a
candidate rabbit-hole, and may send that agent a redirect.

Redirects reach an agent only through the guard wrapper, so **every worker's
brief must tell it to run its dev-loop commands through the guard** (the line
is already in the brief below — keep it). Run your own commands through it
too, as `{{LEAD_AGENT_ID}}`:

```bash
{{GUARD}} {{LEAD_AGENT_ID}} -- <your command>
```

Guard exit code **87** means a halt is pending: stop, read, reorient.
