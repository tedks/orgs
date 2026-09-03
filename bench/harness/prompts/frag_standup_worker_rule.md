> **Forced observe:** run every dev-loop command — tests, builds, git —
> through the guard:
>
> ```bash
> STANDUP_BUS={{BUS_ROOT}} {{GUARD}} <id> -- <your command>
> ```
>
> It passes your command's output through unchanged and appends any standup
> message on stderr. Exit code **87** means a halt is pending: stop and
> reorient before continuing. `STANDUP_BUS` must be there every time — you are
> in your own worktree, and without it the guard reads an empty bus beside you
> instead of the run's, so a redirect meant for you is never delivered.
