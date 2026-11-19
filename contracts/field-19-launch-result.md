# Launcher task result

**Owner** launcher. **Consumers** callers and lane dispatchers.

When a caller supplies a task to the launcher, it can send that task after
launch. If the child launched and the task sender returns nonzero, emit a
diagnostic beginning `Child launched; task delivery unconfirmed` and retain
the existing target and pane identity on the line. Preserve the sender
output and exit from the launcher with the sender's exact status so callers
can distinguish deferral from ambiguity. The diagnostic identifies the
launch branch even when exit codes overlap. It directs the caller to
inspect that child before any retry. It never instructs automatic replay
or launches a duplicate.

Confirmed delivery and actual launch failure keep their existing paths.
Task delivery after a successful fork uses the same diagnostic. The fork's
native completion watcher and its failure path keep their behavior. Change
only the checked-in task-result branch. The separate live operator patch
changes tmux window targeting and stays outside this PR. Boundary checks
exercise successful delivery, deferred and ambiguous task results, and
genuine launch failure.
