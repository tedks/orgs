> **Forced observe:** run every dev-loop command through the guard —
> `{{GUARD}} <id> -- <your command>` — for tests, builds and git. It passes
> your command's output through and appends any standup message on stderr.
> Exit code **87** means a halt is pending: stop and reorient before
> continuing.
