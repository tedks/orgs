# Workflow checks

`evals.json` and `fixtures/` contain synthetic caller scenarios, not real issue
histories. Run each prompt in a fresh agent with the skill and a matched fresh
agent without it; give both the same current ditz command references. Save the
response, stdout, stderr, exit status and command arguments for comparison.

The context-conflict scenario is a tabletop check: the metadata branch is
absent, so the configured filesystem store matters. Its follow-up checks the
opposite case, where the metadata branch takes precedence.

For execution checks, prepare separate disposable Git repositories and isolated
configuration for each agent before handing over the prompt. Initialize their
trackers as test setup, never as the agent's recovery action. Give each a local
bare remote, with no production remotes or credentials:

- Create `widget-literal` with description `old description`; let the agent
  replace it and start work. Inspect the stored description byte-for-byte and
  verify the resulting status/history and remote metadata ref.
- Create `alpha`, close `alpha absent --fixed --json`, and preserve the mixed
  result. Append `Verified literal receipt` to alpha, but withhold that receipt
  from the agent. Make one further local metadata change, then use a rejecting
  pre-receive hook on the disposable remote. The agent should inspect history,
  avoid duplicate close/comment events, leave the unknown ID unresolved, and
  distinguish local completion from failed synchronization.

Inspect both positive outcomes and forbidden extra mutations. Record any
assertion the evidence cannot establish as unverified, not passed. A stored
literal description proves the bytes survived but does not by itself prove a
particular shell quoting technique was used; capture the invocation script if
that implementation detail is being graded. Likewise, a correct status update
does not prove an external ownership coordination took place.

One paired run per case is a smoke check, not a performance or effectiveness
benchmark. Similar baseline results do not demonstrate that the skill improves
agent behavior. Keep private run artifacts outside the installed skill tree.
