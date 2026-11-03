# orgs: A human Boydian software factory

Orgs is a harness-portable set of skills and protocols for running a
*virtual engineering organization* of AI agents according to Boydian
doctrine.

A human operator acts as the CEO of this organization, setting a
*commander's intent* that is understood by the agents within the org.
Agents are treated as trusted subordinates who carry out this intent
in the style of
*[auftragstaktik](https://en.wikipedia.org/wiki/Mission-type_tactics)*.
This permits wider agent autonomy to maneuver towards the
operator-defined
*[schwerpunkt](https://en.wiktionary.org/wiki/schwerpunkt)*, in
contrast to a more typical style of giving agents very specific
*[befehlstaktik](https://decadecity.net/blog/2018/09/26/auftragstaktik-and-befehlstaktik)*
style instruction. This latitude is enabled by collaboration between
more and less intelligent agents and by multiple layers of checks on
the tactical, operational, and strategic levels.

Orgs borrows several concepts from human engineering organizations, including:

 - Hierarchy between senior and junior workers. More senior workers
   operate at the strategic or operational level, generating and
   reviewing design documents, ensuring that junior workers are
   capturing the specification and operator's intent accurately.
   Junior workers receive more narrow assignments than senior workers,
   but are still empowered to maneuver in order to execute the
   high-level intent, preventing stalls and using on-the-ground
   knowledge to make the best decisions.
 - Standups, huddles, retrospectives, and other collaboration supports
   that human engineering organizations rely on or have been presented
   in the software engineering literature. These keep long-running
   agents oriented towards the operator's intent and provide
   opportunities to push back on drift. These meetings can occur
   either in-band, or from forked "clones" of agents. Orgs also
   implements a variation of the
   [Crystal](https://dl.acm.org/doi/10.1145/2025113.2025187) protocol
   for proactive conflict detection, simulating an engineering
   organization with higher situational awareness of ongoing parallel
   work than many human organizations.
 - Living design documents that function as a high-level source of
   truth. Senior level workers primarily output design documents and
   assess tradeoffs between possible implementations. These provide
   another layer of checks at the operational and strategic level,
   above the normal level of testing.

## Using Orgs

To use Orgs, install these skills in your agent, launch an agent that
will act as your CTO, and tell it to start using the Orgs doctrine to
work on your project or task.

Start with the [skills catalog](skills/README.md) and [sprint
runbook](skills/sprint/SKILL.md). The [role
definitions](doctrine/ROLES.md) and [doctrine](doctrine/DOCTRINE.md)
describe how agents divide responsibility and exercise judgment.
Harness-specific guidance lives in the [Claude
Code](bindings/claude-code.md) and [Codex CLI](bindings/codex-cli.md)
bindings.

Orgs is designed to be used via command-line agents in tmux, but can
also be used from outside tmux (though in the author's experience, the
messaging protocol here is much slower).

## Using Orgs with multiple providers

Orgs is designed to be used with multiple intelligence providers. Much
like diversity is a valuable asset in human engineering organizations,
model diversity can be a valuable asset in agent organizations. Orgs
has several pieces of infrastructure that work best with multiple
configured providers.

The most critical of these is the `council-review` skill, which
reviews changes using multiple configured providers, and can work with
`claude`, `codex`, and `agy`. Agents at different levels of the
hierarchy will choose to run this skill at various times, and changes
will always be reviewed with the council before landing.
`council-review` re-runs reviews on the delta after a review round,
with the agent under review pushing back on spurious findings (again,
simulating a human engineer), until a fixpoint is reached.

Orgs also contains tooling to evaluate your use of intelligence across
providers, and will monitor your quota usage across providers to
determine which models to use for implementation, team leads, and org
leads. This tooling lives in the `harness-control` directory and
provides MCP access to things like remaining token budget.

## Limitations / Dependencies

Orgs is designed around the `claude`, `codex`, and `agy` harnesses. It
uses the [ditz](https://github.com/tedks/ditz) issue tracker.

## License

[AGPL-3.0](LICENSE).
