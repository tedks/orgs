# Observed quota reset consumer

`monitor.py` consumes `token-usage meters --check --json` and submits an alert
only after a fresh, ordered pair of observations shows a reset window advance
and a strictly positive decrease in used quota. The earlier
window's `resets_at` must have passed by the later observation. The first
observation is only a baseline. A scan of saved data, elapsed timestamp,
missing meter, or old observation cannot create an alert. Each recognized
meter key has an exact expected `window_minutes` (300 or 10080).
OpenAI's `secondary` slot is accepted only when its reported duration is 300;
the producer does not guarantee that duration across plans. Unsupported
durations appear in the `rejected` result, rather than being treated as a
five-hour observation.

The producer's agreed additive contract puts `account_scope` and
`account_epoch` on **each** meter object. Both must be nonempty strings. The
scope is an operator configured local namespace, not a provider authenticated
account ID; the epoch changes on scope transitions, including removal and
re-addition. The producer binds these fields when ingesting a source
observation, never by relabeling saved data at export. The series and event
event IDs include both and exclude descriptive source. Only the current identity is retained as each meter's
baseline, so scope/epoch transitions, including a return to an earlier value,
cannot resurrect an old comparison. Old dedup records remain. Deployment must
bind the configured scope to the account in
use. A credential switch without a scope/epoch change is undetectable.
The descriptive `source` value is part of the current identity: a change,
including a return to an earlier source, establishes a baseline.

`observed` is the Codex event time or Claude statusline capture time, **not**
scan time or proof of an authenticated provider fetch. Observations older than
20 minutes, future observations and malformed values cannot establish a reset
pair. A historical baseline was fresh when it was accepted; a fresh later
observation may show replenishment after a long gap. The notification says it
was observed **since the last reading**, gives both observation times and the
current measured remaining percentage; it does not claim when or how many
resets happened. Quiet harnesses cannot supply fresh readings, so detection
can be delayed or missed. The consumer does not use `posture.preferred` as
evidence.
If the source reports 0% both before and after a reset, there is no observed
decrease to prove replenishment and no alert. A reset with no timely source
observation can likewise be missed.

Run after the producer contract and notification destination are deployed:

```sh
python3 tools/quota_reset/monitor.py \
  --state-file "${XDG_STATE_HOME:-$HOME/.local/state}/quota-reset-monitor/state.json" \
  --notify-command /path/to/approved-adapter
```

The adapter is one executable, called with event JSON on standard input.
Exit zero proves only adapter or transport acceptance; it never proves Ted
read the notification. Nonzero, timeout, or execution failure leaves delivery
`unknown`. The state file and lock must be on durable local storage in a
private directory (mode 0700 or stricter). A file
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
