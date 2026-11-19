# Launcher task result

**Owner** launcher. **Consumers** callers and lane dispatchers.

When a child was launched and the task sender returns nonzero, report that
the child launched and its task delivery is unconfirmed, with the existing
target and pane identity. Preserve the sender output and exact exit
status so callers can distinguish deferral from ambiguity. The diagnostic
directs the caller to inspect that child before any retry. It never instructs
automatic replay or launches a duplicate.

Confirmed delivery and actual launch failure keep their existing paths.
The fork compaction gate is outside this boundary. The change uses only the
checked-in source and leaves the separate live operator launcher patch
outside the PR. Boundary checks exercise successful delivery, deferred and
ambiguous task results, and genuine launch failure.
