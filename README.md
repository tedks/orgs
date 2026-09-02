# orgs

**Draft — design in active discussion; everything here is subject to change.**

A harness-portable set of skills and protocols for running a *virtual
engineering organization* of AI agents.

The human operator acts as CEO. A root CTO agent iterates with the CEO on a
design-doc-style spec whose most important content is the **firewalled
contract boundaries** between agent teams. Once the spec stabilizes,
team-lead agents (L5–L7) decompose their slice into tactical tasks executed
by junior-model agents (L3/L4); work flows back up a review ladder where
senior-tier agents refine or take over PRs. Periodic standups — attended by
context-carrying forks of the workers — catch rabbit-holing and redirect
effort. Spec gaps are resolved cheaply through logged "interpretations,"
with amendments kept rare and deliberate. Lessons learned persist in the
repo.

Design goals:

- **Protocol over application.** Durable state is files in git; the repo is
  the office. Any harness (Claude Code, Codex, Antigravity) binds the
  protocol to its native agent primitives.
- **Contracts first.** Boundaries are designed up front and enforced
  physically through context assembly — an implementer sees the published
  contract, not the neighboring team's source.
- **Mission-type tactics.** Agents carry the commander's intent, are
  empowered to deviate toward it, huddle when instruction and intent
  conflict, and log the bends.
- **Existing org wisdom, applied.** Agents act out the processes of a
  well-run engineering org — design review, player-coach leads, written
  standups, blameless retros — rituals models already understand deeply.

No skills are implemented yet; see [docs/spec-template.md](docs/spec-template.md)
and [skills/README.md](skills/README.md) for the intended shape.

## License

[AGPL-3.0](LICENSE).
