# Observed quota reset consumer

`monitor.py` consumes `token-usage meters --check --json` and submits an alert
only after a fresh, ordered pair of observations shows a reset window advance
and at least a five percentage point decrease in used quota. The earlier
window's `resets_at` must have passed by the later observation. The first
observation is only a baseline. A scan of saved data, elapsed timestamp,
missing meter, or old observation cannot create an alert. Each recognized
meter key has an exact expected `window_minutes` (300 or 10080).

The producer's agreed additive contract puts `account_scope` and
`account_epoch` on **each** meter object. Both must be nonempty strings. The
scope is an operator configured local namespace, not a provider authenticated
account ID; the epoch changes on scope transitions, including removal and
re-addition. The producer binds these fields when ingesting a source
observation, never by relabeling saved data at export. The series and event
IDs include both, so scope changes establish a new baseline while old dedup
records remain. Deployment must bind the configured scope to the account in
use. A credential switch without a scope/epoch change is undetectable.
The descriptive `source` value is also part of each series identity; a source
change establishes a baseline rather than combining differently collected
readings into one reset claim.

`observed` is the Codex event time or Claude statusline capture time, **not**
scan time or proof of an authenticated provider fetch. Observations older than
20 minutes, future observations, malformed values, and observations more than
one window apart do not establish a reset pair. Quiet harnesses cannot supply
fresh readings, so detection can be delayed or missed. The consumer does not
use `posture.preferred` as evidence.

Run after the producer contract and notification destination are deployed:

```sh
python3 tools/quota_reset/monitor.py \
  --state-file "${XDG_STATE_HOME:-$HOME/.local/state}/quota-reset-monitor/state.json" \
  --notify-command /path/to/approved-adapter
```

The adapter is one executable, called with event JSON on standard input.
Exit zero proves only adapter or transport acceptance; it never proves Ted
read the notification. Nonzero, timeout, or execution failure leaves delivery
`unknown`. The state file and lock must be on durable local storage. A file
lock serializes concurrent invocations. Before invoking the adapter the
consumer atomically persists an `in_flight` intent and fsyncs the state and
directory. A crash before or after possible external acceptance leaves that
intent untouched; it is treated as unknown and **never automatically
retried**. Repeated observations and restarts cannot send that event again.
This chooses no duplicate automatic sends over eventual delivery when the
outcome is ambiguous. An operator may reconcile unknown records using the
private state and destination evidence; this tool does not guess. There is
no exactly once or human-read claim.

The producer, scheduling, host activation, destination choice, and end to end
notification proof belong to the deployment owners. This package carries no
destination, account namespace, or live host configuration.

Tests:

```sh
nix develop --command bazel test //tools/quota_reset:monitor_test //tools/quota_reset:monitor_mutation_test
```
