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
- **Contracts first.** Boundaries are designed up front and enforced at the
  dependency level — build visibility, consumer-driven contract tests, and
  total review. Context packing is lean by default (an implementer is
  *given* the published contract, not the neighboring team's source), but
  reading is always free: the packing list is hygiene, not a firewall.
- **Mission-type tactics.** Agents carry the commander's intent and are
  empowered to deviate from instruction to serve it, on their own judgment,
  logging the bend; huddles are reserved for irreversible or
  boundary-crossing moves and for genuine uncertainty.
- **Existing org wisdom, applied.** Agents act out the processes of a
  well-run engineering org — design review, player-coach leads, written
  standups, blameless retros — rituals models already understand deeply.

The protocol is a graph of composable skills under [skills/](skills/README.md),
rooted at `skills/sprint`. Start with [doctrine/ROLES.md](doctrine/ROLES.md)
for the hats, then [doctrine/DOCTRINE.md](doctrine/DOCTRINE.md) for how we
work. Harness bindings map both to real primitives:
[bindings/claude-code.md](bindings/claude-code.md) and
[bindings/codex-cli.md](bindings/codex-cli.md). Specs start from
[docs/spec-template.md](docs/spec-template.md).

## License

[AGPL-3.0](LICENSE).
