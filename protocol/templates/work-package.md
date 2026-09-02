# Work package: <id>

- **State:** DRAFT
- **Owner (role):** <e.g. L3 implementer, team A> · **Model:** <assigned per
  task; tier default overridable both ways>
- **Base revision:** <sha the package was cut against>
- **Intent:** <why this exists — which spec goal/section it serves, what the
  boundary protects. The worker deviates toward THIS when instruction
  conflicts with it.>
- **Instruction:** <the objective — what to build/change>
- **Non-goals:** <explicitly out of scope>
- **Owned scope:** <files/component this package may change>
- **Dependencies:** <contracts consumed, with versions>
- **Acceptance criteria:** <prose: behavior, edge cases, "done means" — the
  implementer writes the unit tests; these criteria are what the tests must
  demonstrate, and the review evaluates the tests as a first-class artifact>
- **Boundary tests:** <pre-written contract tests this must pass, by path>
- **Budget:** <tokens and/or wall-clock — soft; exceeding it is normal when
  logged, a tripwire when silent>
- **Stop conditions:** <e.g. same test failing 3 distinct ways → reorient or
  escalate>
- **Escalation destination:** <who adjudicates for this package>
- **Deviation envelope:** default (doctrine) | tightened: <explicit
  acceptance-condition constraints, e.g. clean-room, no scope deviation>
- **Expected artifact:** <PR against branch X; docs; etc.>
