# Codex compaction evidence

**Owner** tmux sender. **Consumer** operator or controller issuing a live
command.

An explicit option selects command-outcome verification for the exact bare
`/compact` argument on the literal typed-command route in Codex. An
ineligible route or argument exits 1 before touching the pane. A non-Codex
or unverified pane defers with its reason and exits 2. The selected mode
never falls through to an ordinary sender route. A nonempty composer
before typing defers without mutation. Verify ownership before submitting
and send at most one Enter for the attempt. If ownership is lost after
typing, preserve the current input, report unknown and send no Enter.

Use a baseline captured before Enter. During the configured receipt wait,
fresh rendered Codex completion or refusal relative to that baseline
determines the outcome. Old history, ordinary submitted or queued rows,
an empty or quiet pane, and progress text alone are insufficient. Evidence
after the wait falls outside the attempt. Unsupported or conflicting
evidence gives an unknown outcome.

After input is attempted the structured result reports a distinct
`command_outcome` of `completed`, `refused` or `unknown`. Completion
exits 0. Refusal and unknown exit 3. Existing pre-input deferral and
unselected sender exits keep their meanings. Keep input ownership and
private pending-payload rules in force without automatic replay.

Unselected typed commands, ordinary messages, pasted `/compact`, Claude,
and the Codex fork's native completion watcher retain their existing routes
and semantics. The exact option name and supported rendered evidence
belong in the transport reference. Boundary checks cover completion,
refusal, stale evidence, quiet and ordinary receipt, one Enter, wrong
provider, route or payload rejected without mutation, draft preservation,
and route compatibility.
