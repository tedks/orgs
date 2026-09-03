
## Forced observe — run your dev loop through the guard

A standup process is watching this run and may send you a redirect or a halt.
It reaches you only through the guard wrapper, so **run every dev-loop command
through it**: your tests, your builds, your git commands.

```bash
STANDUP_BUS={{BUS_ROOT}} {{GUARD}} {{SOLO_AGENT_ID}} -- <your command>
```

`STANDUP_BUS` is not optional and not decoration: without it the guard looks
for messages under your current directory instead of the run's shared bus, and
silently finds none. Keep it on every invocation.

The guard runs your command, passes its output through unchanged, and appends
any pending standup messages on stderr. If it exits **87**, a halt is pending:
stop what you are doing, read the message, and reorient before continuing.
