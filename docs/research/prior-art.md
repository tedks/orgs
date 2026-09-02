# Prior art survey: orgs vs. the field

**Status:** research note, not spec text. Compiled 2026-09-02 by a research pass
across web sources (frameworks' own docs/repos/papers, plus independent
write-ups). Not a substitute for reading the primary sources linked below —
treat citations as starting points, not as verified-forever facts; several
projects (AutoGen, Swarm, Gas Town) are mid-migration as of this writing and
will have moved on by the time anyone reads this again.

**Method:** three parallel research passes — (1) multi-agent orchestration
frameworks, (2) single/few-agent autonomous coding tools, (3) theoretical and
adjacent software-engineering foundations — each instructed to be skeptical
and to say plainly when orgs' claimed novelty already exists elsewhere. This
document synthesizes those three passes and adds a cross-cutting read.

Everything below is checked against orgs' six distinctive bets, stated here
in the vocabulary `doctrine/DOCTRINE.md` actually uses:

1. **Protocol-over-application.** Durable state is files in git; the repo is
   the office. Any harness (Claude Code, Codex, Antigravity) binds the same
   protocol to its native primitives. Not an app you install and run.
2. **Contracts-first firewalls.** Team boundaries designed up front, enforced
   at the dependency level ("the contract is the API. Read anything in the
   repo; depend only on what's published."). Observed effect: **defect-class
   propagation** — a bug fixed in one team became a contract *clarification*
   (an Interpretation, in doctrine's terms) that prevented the whole bug
   class in a downstream team, with zero cross-team code reading.
3. **Auftragstaktik / mission command.** Agents carry commander's intent
   (the design doc's goals/non-genoals — the *Schwerpunkt*), are empowered to
   deviate from a work package's letter when it defeats that intent, and must
   log the bend in one line. Huddle-first only at the reversibility gate
   (unnameable rollback, contract-boundary change, scope overrun).
4. **Cross-provider council review to fixpoint.** Independent LLM providers
   (Claude, Codex, Antigravity/agy) review the same diff in parallel, to a
   round that comes back clean — because same-provider review has correlated
   blind spots.
5. **Standup — forced observation at chokepoints.** "The recurring or
   event-triggered review of statuses, logs, and open work; adjudicates
   deviations, redirects rabbit holes." The working hypothesis under test:
   a rabbit-holing agent is exactly the one that stopped observing outside
   updates, and this single mechanism may be 80% of the system's value for
   20% of its implementation cost.
6. **Model-tier economics.** Cheap/fast models do tactical execution;
   expensive models review.

---

## 1. Multi-agent orchestration frameworks

These are the frameworks people reach for first when building "a team of AI
agents." All seven are, at bottom, **in-process libraries or hosted runtimes
you install and run** — none is a protocol other harnesses bind to, so bet #1
gets no real competition from this category. The finer-grained comparison is
on bets #2, #4, #5.

### MetaGPT

Role-based agents (PM, Architect, Engineer, QA) turn a one-line ask into PRDs,
designs, code, and tests under a fixed "Code = SOP(Team)" pipeline.
[Paper](https://arxiv.org/abs/2308.00352) (ICLR 2024) ·
[repo](https://github.com/foundationagents/metagpt).

Coordination runs through a **global message pool** that every role
subscribes to by filter — the opposite of a firewall: anything published is
visible to everyone, filtering happens on the read side, not by dependency
enforcement. No cross-provider review. No forced re-observation; its
executable-feedback loop reacts to its own test output, not to outside-world
state.

### ChatDev

A "virtual software company" where role-playing agents move through the SDLC
via structured two-party dialogues chained into phases (now a general DAG in
ChatDev 2.0, "MacNet"). [Paper](https://arxiv.org/abs/2307.07924) ([ACL
2024](https://aclanthology.org/2024.acl-long.810/)) ·
[repo](https://github.com/OpenBMB/ChatDev).

Its phase-scoped dialogues, where only the resulting *artifact* (not the raw
transcript) carries forward, is the closest thing to a contract-like boundary
found in this category — weak, but real. It also has an optional
**Human-Agent-Interaction mode** letting a person inject guidance mid-run;
genuine human-in-the-loop, but user-initiated and optional, not a forced
chokepoint. No cross-provider review.

### AutoGen → AG2 / Microsoft Agent Framework

AutoGen pioneered `GroupChat` (broadcast-to-all, a manager picks the next
speaker); now in maintenance mode, folded into [Microsoft Agent
Framework](https://github.com/microsoft/agent-framework) (April 2026), while
the original team's fork [AG2](https://github.com/ag2ai/ag2) moved to a
Hub/typed-channel "Network" architecture. Group chats are an explicitly
shared-transcript model — the architectural opposite of a firewall. Per-agent
pluggable LLM backends make a heterogeneous-provider group chat *assemblable*,
but no built-in council-to-fixpoint workflow exists. `UserProxyAgent`'s
`human_input_mode` allows free-text injection per turn — a real interrupt,
but optional and human-initiated, not a forced or periodic re-observation.

### OpenAI Swarm → OpenAI Agents SDK

Swarm's core primitive, the **handoff**, transfers control by returning
another agent object, with the entire chat history persisting by default
across handoffs — [repo](https://github.com/openai/swarm); superseded by the
production [Agents SDK](https://openai.github.io/openai-agents-python/).
Passing full history forward by default is the opposite of lean, contract-only
transfer. The SDK's **guardrails** (parallel validators that can trip a
"tripwire") and tool-approval gates are pass/fail or approve/deny checks on a
proposed action — not injection of fresh outside-world state into a running
agent.

### CrewAI

Agents/Tasks/Crews (Sequential or Hierarchical) plus an event-driven `Flows`
layer. [Repo](https://github.com/crewaiinc/crewai) (~51k stars). Per-agent
LLM choice via LiteLLM makes cross-provider execution trivial to *assemble*,
but nothing runs it as an independent-review workflow. `human_input=True` and
task guardrails are approval/validation gates tied to task completion, not a
world-state refresh; one-shot `@before_kickoff`/`@after_kickoff` hooks aren't
chokepoints either.

### LangGraph

Graph-based orchestration over a shared/typed state object with a
checkpointer. [Repo](https://github.com/langchain-ai/langgraph). **This is
the one genuine partial precedent for bet #5 found across the whole survey:**
`interrupt(value)` pauses a running node and persists state via the
checkpointer; resuming via `Command(resume=value)` or `update_state()` can
inject *arbitrary new data* into the paused run, not just an approve/deny
signal. That is materially closer to "inject fresh external state mid-run"
than any approval gate elsewhere in this survey. The caveat that matters:
every `interrupt()` is a specific line of code a developer chooses to place
at a specific node. There is no generic mechanism forcing *any* running agent
at *any* boundary-crossing or irreversible action to pause — it's opt-in and
per-node, not systemic and forced. Subgraphs *can* get an isolated state
schema (no shared keys), the one piece of infrastructure that could support
something contract-like, but it's a per-graph developer choice, not a
designed-up-front, dependency-enforced boundary with a published-contract
format — and nothing resembling defect-class propagation appears in its
docs. No cross-provider review construct.

### AutoGPT

Began as a single-agent autonomous loop; now the **AutoGPT Platform**, a
hosted/self-hosted visual builder composing a DAG of typed "blocks."
[Repo](https://github.com/Significant-Gravitas/AutoGPT) (187k+ stars). Squarely
a centralized application/platform. What passes for human oversight is
step-by-step confirmation vs. continuous mode — binary allow/deny gates, not
situational-awareness refresh. No contract firewalls, no cross-provider
review.

### Category synthesis

Every framework in this category defaults to **shared, global context**: a
message pool, a group-chat/hub transcript, full history on handoff, a shared
state object, or a single graph/run context — with at most manual, per-instance
narrowing (LangGraph subgraph state, CrewAI task `context` fields, ChatDev's
phase-scoped artifacts). None exhibits anything resembling defect-class
propagation. Cross-provider council-to-fixpoint is universally absent as a
*workflow*, even though several frameworks trivially support assigning
different providers to different agents as a config choice — provider
substitutability is not the same thing as independent adversarial review.
Forced observation is also universally absent except for LangGraph's
`interrupt()`, which is real but opt-in and per-node rather than forced and
systemic. The frameworks are mature, well-adopted prior art for *role
decomposition and handoff mechanics as an installable application* — not for
any of orgs' four sharper bets (#1, #2, #4, #5) as a bundle, and only
LangGraph offers a non-superficial partial precedent for one of them.

---

## 2. Single/few-agent autonomous coding tools

A different lineage: tools built around *doing* a coding task autonomously,
rather than orchestrating a cast of role-playing agents.

### GPT-Engineer

Single-pass CLI generator, largely of historical interest now (ancestor of
lovable.dev). [Repo](https://github.com/AntonOsika/gpt-engineer). Open-loop:
generate once, stop. No planning/execution split, no team concept, nothing
resembling any of orgs' bets.

### Devin (Cognition)

Commercial, cloud-hosted autonomous engineer with its own sandbox.
["Devin Fusion"](https://cognition.com/blog/introducing-devin) pairs a frontier
reasoning model for planning with smaller models for routine work — real
model-tier economics (bet #6), the least distinctive of orgs' six bets and
already mainstream. Two human checkpoints bracket autonomous execution: a
**Planning Checkpoint** (human reviews/edits the plan) and a **PR Checkpoint**
(human reviews the final diff). Both are human-approval gates on Devin's *own*
plan/output — not a mechanism forcing Devin to re-observe *outside-world*
state (new commits from others, CI status, incoming messages) mid-run. No
cross-provider review; no contract firewalls (one sandbox, one task, no team
boundary concept).

### OpenHands (formerly OpenDevin)

MIT-licensed open-source [SDK](https://github.com/OpenHands/software-agent-sdk)
originally built to replicate Devin. The most architecturally multi-agent tool
in this category: explicit **sub-agent delegation** — a parent spawns
sub-agents with isolated context and workspace running in parallel, with only
the sub-agent's final answer returning to the parent. This is the closest
analog anywhere in this survey to bet #2's isolation half (bounded context
between agents), but it is *runtime task-parallelization isolation*, not a
designed-up-front, dependency-enforced interface contract between persistent
teams — no described defect-class-propagation effect. No forced
re-observation; delegation gives isolation, not a live world-state check. No
built-in cross-provider review workflow, though its model-agnostic routing
makes it the easiest tool in this category to bolt one onto.

### Aider

Terminal-based pair-programming CLI that edits a local git repo directly and
auto-commits. [Site](https://aider.chat/). Single-loop, human-driven per turn.
Its **architect/editor mode** — a planning model proposes a solution, a
separate editor model translates it into concrete edits, optionally two
*different* providers — is a real planner/executor split, and can pair
different providers, but it's cost/capability pairing for one edit, not
adversarial review of the same artifact to fixpoint. Leaning on the local git
repo as state is a partial echo of "state is files in git," but there's no
team/contract layer on top — one working tree, one session, manually curated
context rather than an enforced contract system.

### SWE-agent (Princeton/Stanford)

Academic system introducing the **Agent-Computer Interface (ACI)** — a
tailored command/feedback set that makes LLMs effective at autonomous SWE,
evaluated on SWE-bench. [Paper](https://arxiv.org/abs/2405.15793) ·
[repo](https://github.com/SWE-agent/SWE-agent). A single ReAct loop
(Thought→Action→Observation) against one static issue until submit/limit/error
— the clearest pure-open-loop example in this survey. Arguably the closest
thing here to a "protocol" in spirit (a defined interface between model and
tools), but it's a protocol between *model and tools*, not between *agent
teams*, and still ships as an installable tool. No multi-agent structure, no
cross-provider review, no contract firewalls, no re-observation (nothing to
re-observe — SWE-bench tasks are static and sandboxed).

### Amazon Kiro

AWS's agentic IDE built around **spec-driven development**: Requirements
(EARS-formatted user stories) → Design (interfaces, schemas, data-flow,
human-approved) → Tasks (dependency-ordered, agent-executed), with Autopilot
or Supervised (hunk-by-hunk approval) execution modes.
[kiro.dev](https://kiro.dev/) · [hooks docs](https://kiro.dev/docs/hooks/).
Its `.kiro/specs/` and `.kiro/hooks/` artifacts live in-repo, giving it more
"state as files" character than most tools surveyed, but it ships as an
installed IDE product, not a harness-portable protocol. **Kiro specs vs.
orgs contracts, precisely:** Kiro specs are per-feature planning artifacts
*within a single codebase/session*, written and then consumed by the *same*
agent — a formalized "think before you code" discipline, not an interface
published *between* independently-scoped teams that a separate,
context-firewalled team reads instead of the first team's code. No described
defect-class-propagation effect. **Hooks** are the closest thing to a
chokepoint mechanism found anywhere in this category, but they fire on the
agent's *own* actions (file save, tool call, task completion) — reactive to
self, not to external state landing from elsewhere. Different mechanism than
bet #5. No cross-provider review (built on Claude models per AWS's own
announcement).

### "Gas Town" (Steve Yegge)

The tool orgs' own founding notes explicitly contrast itself against ("less
of an app, more a flexible skill structure multiple harnesses share —
contrast with Gas Town"). Worth stating precisely since it's the closest
sibling project surveyed: a Mad-Max-themed multi-agent workspace/orchestration
system (`gt` CLI), Go binary, managing tmux sessions and git worktrees, with a
genuinely hierarchical architecture — Town (workspace) → Rigs (project
containers) → Mayor (central coordinator) → Polecats (ephemeral tactical
workers on Convoys of Beads/tickets), plus Witness/Deacon health-monitoring
watchdogs, a Bors-style Refinery merge queue, and Seance for cross-session
context recovery via event logs. [Repo](https://github.com/gastownhall/gastown)
· [origin post](https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04)
· [v1.0 post](https://steve-yegge.medium.com/gas-town-from-clown-show-to-v1-0-c239d9a407ec)
· independent write-ups:
[justin.abrah.ms](https://justin.abrah.ms/blog/2026-01-05-wrapping-my-head-around-gas-town.html),
[tenzinwangdhen.com](https://tenzinwangdhen.com/posts/gastown-good-bad-ugly/),
[maggieappleton.com](https://maggieappleton.com/gastown).

**Orgs' self-framing checks out, with a nuance.** Gas Town is an installed
application in the sense that matters most — a binary managing tmux, worktrees,
and stateful watchdogs on your machine, much more "runtime you run" than
"protocol you bind to." That said, its README now claims multi-runtime support
(Claude, Codex, Copilot, Gemini, Kiro, configurable per-rig), even though
independent write-ups and its own changelog describe deeply Claude-Code-native
mechanics (tmux "nudge" timing around Claude Code's UI, detecting/dismissing
the Claude Code Rewind menu during automated input). The accurate
characterization is "Claude-Code-native with bolted-on multi-runtime
configuration," not "exclusively Claude Code" — orgs' contrast should be
sharpened to that, not overstated.

Gas Town does have "agent contracts" and rig-level isolation, but they're a
different mechanism from bet #2: role-based behavioral restrictions on what
one agent type may do (e.g. the refinery agent is prompted/forbidden from
writing application code) plus filesystem/process isolation between rigs to
prevent "cross-rig contamination" — not a dependency-level-enforced interface
contract between teams where team B is architecturally prevented from reading
team A's code and can only consume A's published surface. No described
defect-class-propagation effect; rigs read as parallel independent projects
for throughput, not a dependency-firewalled org chart.

**The sharpest comparison in this whole survey is here, on bet #5.** Gas
Town's Witness/Deacon watchdogs are real monitoring machinery, but they watch
*from outside* and intervene when an agent appears **stuck** — liveness/health
monitoring triggered by an agent's own failure to progress, not a mechanism
that forces an otherwise-healthily-running agent to pause and check "has
anything changed in the world" at defined waypoints. Seance is post-hoc
context recovery for a *new* session after a restart, not in-flight forced
re-observation by a *currently-executing* agent. No mechanism resembling
Standup — forced re-observation of live external state at a chokepoint, for a
still-running agent — was found in Gas Town, despite it being the most
sophisticated multi-agent-coding-fleet system surveyed. No cross-provider
review either (multi-runtime support is provider *choice* per rig, not
adversarial cross-provider review of the same artifact).

### Category synthesis

Bet #6 is essentially mainstream already (Devin's Fusion, Aider's
architect/editor split, Kiro's model tiering). Bet #1 has no real match:
every tool is a hosted product, an installed CLI, or an installable SDK — none
is designed as harness-neutral, though Aider's git-native state and Kiro's
in-repo `.kiro/` artifacts gesture partway there. Bet #2 has a genuine but
shallow echo in OpenHands' sub-agent context isolation and a different,
weaker echo in Gas Town's per-role behavioral contracts — nothing found
enforces a contract at the dependency-graph level between persistent teams,
and the specific defect-class-propagation effect was not found duplicated
anywhere. Bet #3 has partial analogs in Devin's plan-approval checkpoint and
Kiro's design-approval gate, but those are human-approves-agent-plan patterns,
not agents-empowered-to-deviate-and-log-it. Bet #4 is close to absent — only
OpenHands' model-agnostic routing even makes it technically easy, and no tool
implements it as a designed workflow. **Bet #5 is the sharpest and, on this
evidence, the most novel claim in the whole survey**: Kiro's hooks fire on
self-action, Gas Town's watchdogs watch for stuck-ness from outside, SWE-agent
and GPT-Engineer are purely open-loop. Nothing surveyed — including the most
mature multi-agent-fleet system found (Gas Town) — forces a live, healthy,
still-running autonomous agent to pause and check what changed in the world
since it last looked.

---

## 3. Theoretical and adjacent foundations

Five non-AI-specific bodies of prior art orgs draws on. The important
question for each: has anyone already applied it to AI agents specifically?

### Auftragstaktik / mission command / Boyd

Real 19th-century Prussian doctrine (via Clausewitz), formalized further
through 1864–1945, adopted into US doctrine as mission-type orders (FM 100-5,
1986); NATO's "mission command."
([USNI](https://www.usni.org/magazines/proceedings/2025/may/auftragstaktik-leads-decisive-action),
[Army War College](https://press.armywarcollege.edu/cgi/viewcontent.cgi?article=1942&context=parameters))
Two mechanisms orgs cites are named doctrine, not invented: **disciplined
initiative** ("if execution of an order was rendered impossible, an officer
should seek to act in line with the intention behind it" —
[army.mil](https://www.army.mil/article/106872/understanding_mission_command)),
and the **backbrief** — a subordinate briefs *how* they intend to execute
before acting, so the commander can confirm it nests inside their intent (FM
101-5-1, [via GlobalSecurity](https://www.globalsecurity.org/military/library/policy/army/fm/101-5-1/f545-b.htm)).
Boyd's own "Organic Design for Command and Control" (1987) names
Auftragstaktik, Einheit (mutual trust), and Schwerpunkt as the pillars of
"organic" (vs. "mechanical") command —
["Without a common outlook superiors cannot give subordinates freedom-of-action
and maintain coherency of ongoing action."](https://www.ausairpower.net/JRB/organic_design.pdf)
Chet Richards' *Certain to Win* (2004), Boyd-endorsed, threads Auftragstaktik
through Boyd's Blitzkrieg analysis, framing "mission" as "a contract between
superior and subordinate."

**Already applied to AI agents:** yes, and specifically. Lt. Col. Matthew
Corbett (Army Cyber Institute), ["Commander's Intent for
Machines"](https://mwi.westpoint.edu/commanders-intent-for-machines-reimagining-unmanned-systems-control-in-communications-degraded-environments/)
(Modern War Institute, July 2025) proposes machine-readable commander's intent
for autonomous drone systems under comms-degraded conditions, citing fielded
Ukrainian autonomous drone systems. This is AI-agent application of
commander's intent — but for battlefield robotics, not coding agents. **No
prior art was found tying Auftragstaktik with backbrief-and-huddle
specifically to coding agent teams** — orgs' huddle-before-irreversible-action
mechanism (doctrine's reversibility gate) has no exact doctrinal analog
either; it rhymes with the backbrief's purpose but is orgs' own addition.

### Conway's Law / Inverse Conway Maneuver

Melvin Conway, "How Do Committees Invent?" (Datamation, 1968):
["Any organization that designs a system... will produce a design whose
structure is a copy of the organization's communication
structure."](https://www.melconway.com/Home/Conways_Law.html) The **Inverse
Conway Maneuver** — deliberately shape team structure to get a desired
architecture — was coined by LeRoy & Simons (Cutter IT Journal, 2010),
popularized for microservices by [Lewis &
Fowler (2014)](https://martinfowler.com/articles/microservices.html).

**Already applied to AI agents: yes, directly, and this significantly
undercuts novelty here.** [aipatternbook.com's "Inverse Conway
Maneuver"](https://aipatternbook.com/inverse-conway-maneuver) entry states
plainly: "For agentic systems, the maneuver is both cheaper and faster. You
don't move desks or change reporting lines. You write an instruction file
that scopes each agent to its domain" — and works a full example (support-
ticket routing agents drifting into each other's territory until scoped
instruction files + restricted tool permissions + explicit interfaces fix
it). [Forrester](https://www.forrester.com/blogs/conways-law-your-operating-model-matters-more-than-the-ai-model/)
and multiple 2025–2026 practitioner posts make the same move. **The
"contracts-first firewall via deliberate boundary design" pattern, applied to
AI agents specifically, is already named by others.** Orgs' potential
contribution has to be in the specifics — dependency-level enforcement (not
just instruction-file scoping) and the defect-class-propagation observation —
not the base analogy.

### Google monorepo / Large-Scale Changes / design-doc & review culture

Potvin & Levenberg, ["Why Google Stores Billions of Lines of Code in a Single
Repository"](https://cacm.acm.org/research/why-google-stores-billions-of-lines-of-code-in-a-single-repository/)
(CACM 2016); *Software Engineering at Google*'s [LSC
chapter](https://abseil.io/resources/swe-book/html/ch22.html): logically-
related changes too big to land atomically, executed by a small central team
across thousands of files via dedicated tooling, under a single canonical
repo with universal visibility. Design docs: [Ubl, "Design Docs at
Google"](https://www.industrialempathy.com/posts/design-docs-at-google/).

**This is the weakest, most contrastive mapping of the five, correctly so.**
Google's model is *centralized, single-repo, universal-visibility*
coordination for change at scale — structurally the opposite of orgs'
firewalled, lean-context, git-as-substrate bet, and closer in spirit to
federated DVCS/OSS upstream-downstream coordination (Linux kernel-style) than
to Google's monorepo. No AI-agent-specific extension of Google's LSC tooling
was found; the closest hit, ["Migrating Code At Scale With LLMs At
Google"](https://arxiv.org/abs/2504.09691), uses LLMs to *execute* LSCs within
Google's existing centralized model — not to coordinate independent agent
teams the orgs way. Treat this as a contrast case ("here's the mainstream
alternative, here's why orgs bets differently"), not a lineage claim.

### Speculative merging — Brun & Notkin's Crystal

Brun, Holmes, Ernst, Notkin, ["Speculative Analysis: Exploring Future
Development States of
Software"](https://www.cs.ubc.ca/~rtholmes/papers/foser_2010_brun.pdf) (FoSER
2010), then **Crystal** itself: "Proactive Detection of Collaboration
Conflicts" (ESEC/FSE 2011, ACM SIGSOFT Distinguished Paper Award) — an
Eclipse-integrated tool that continuously, speculatively merges a developer's
in-progress workspace with others' branches in the background, then
build/tests the speculative merge to surface textual, compilation, *and
behavioral* conflicts before anyone actually merges (evaluated on 9 OSS
systems, 3.4M LOC, 550K snapshots).

**This is the tightest 1:1 mechanism match in the whole survey, and the
project's own tool name (`crystal/`) is almost certainly a deliberate
homage.** Both take independent, uncommitted, ongoing parallel work, both
speculatively merge in the background, both use build/test signal (not pure
diff) as the conflict oracle, both aim to warn before divergence compounds.
The only substantive difference is the actor doing the parallel work — human
developers vs. AI coding agents.

**Already applied to AI agents:** yes, as of 2026, and worth being precise
about *how far*. ["AgenticFlict: A Large-Scale Dataset of Merge Conflicts in
AI Coding Agent Pull Requests on
GitHub"](https://arxiv.org/abs/2604.03551) (142K+ agent-authored PRs, 59K+
repos, 27.67% conflict rate) establishes AI-agent merge conflicts as an
active, named research problem — but it's a measurement/dataset paper, not a
speculative-merge tool. On the tooling side, [Autonoma's "5 Ways to Stop AI
Agents Stepping on Each
Other"](https://getautonoma.com/blog/parallel-ai-agent-prs) already describes
`git merge-tree`-based pre-flight conflict detection between agent worktrees
plus static dependency-graph task assignment — i.e., practitioners are
already building **lighter-weight, text/tree-diff-only** versions of
Crystal-style detection for AI agent workstreams. **What was not found:** a
tool replicating Crystal's actual core innovation — background speculative
*build-and-test* (behavioral) merging, not just tree-diff — applied to
concurrent AI agent branches specifically.

**Checked against the actual implementation:** `crystal/crystal-check.sh`
does the behavioral version, not just tree-diff. `git merge-tree
--write-tree` computes each speculative merge without touching any worktree,
index, or ref; when `--test-cmd` is given, the clean merged tree is extracted
as plain files via `git archive | tar` (chosen specifically because archive
runs no clean/smudge filter code, so a repo-configured filter can't execute
side effects from a speculative background check) into an isolated scratch
directory with git's own env vars and `OLDPWD` unset and
`GIT_CEILING_DIRECTORIES` pinned, and the boundary-test command runs there; a
failure is reported as a semantic conflict (`crystal/README.md`,
`crystal/crystal-check.sh:196-237`). That is a build-and-test oracle, the
same shape as the original Crystal's behavioral conflict detection, applied
to AI agent branches instead of human developer branches. On this survey's
evidence, that combination — behavioral (not just textual) speculative
merge-conflict detection, purpose-built for concurrent AI coding agents — is
a genuine, currently-unclaimed extension; the AgenticFlict/Autonoma prior art
above is textual/tree-diff only.

### Consumer-driven contract testing — Pact

[pact.io](https://docs.pact.io/getting_started/how_pact_works): the consumer
writes a test against a Pact mock expressing its expectations, generating a
JSON contract; the provider independently verifies its real implementation
against that contract — neither side needs the other's source. Replaces
brittle full-integration tests with fast, independent, per-side verification
anchored to a shared explicit artifact.

**Direct and substantive mapping** — "contracts define the interface, both
sides verify independently, zero cross-side code reading" is exactly Pact's
model, and it maps closely onto doctrine's "the contract is the API. Read
anything in the repo; depend only on what's published." The gap: Pact
contracts are typically machine-checkable request/response schemas verified
by an automated pass/fail; orgs' contracts for an AI agent team likely also
carry semantic/behavioral expectations enforced by an agent *reading and
reasoning about* a written document, not just schema comparison — closer to
Pact's spirit than its literal machinery.

**Already applied to AI agents**, on two fronts, neither of which duplicates
orgs' specific claim. First, PactFlow itself ships [agentic tooling that uses
AI to generate/maintain Pact contracts](https://pactflow.io/blog/pactflow-mcp-server/)
— AI-assisted contract *authoring*, not AI agents whose own team boundaries
are contract-governed. Second, and closer: ["Designing Intelligent Enterprise
Agents"](https://arxiv.org/abs/2605.08258) (arXiv 2605.08258) introduces the
"Agent Capability Contract," explicitly analogous to an SOA service contract,
where agents "consume enterprise capabilities through explicit contracts...
they do not own enterprise capabilities by default." Also [a trace-based
assurance framework](https://arxiv.org/html/2603.18096v1) (arXiv 2603.18096)
defines machine-checkable "step contracts" and "trace contracts" over agent
execution traces. **The general idea of contract-governed agent boundaries is
already circulating in 2026 multi-agent-architecture literature under other
names (ACC, trace contracts)** — but framed around single-agent-to-platform
capability grants and runtime trace verification, not Pact's specific
bilateral consumer/provider model applied to *pairs of AI agent teams*, and
the defect-class-propagation observation specifically was not found
duplicated anywhere.

### Faithfulness ranking

**Tightest mechanism match:** speculative merging (Crystal) and Pact contract
testing — both map almost mechanically onto what orgs describes, not just
vocabulary. **Faithful but contested for novelty:** Auftragstaktik and
Conway's Law — both real doctrine, both already explicitly extended to AI
agents by others (drones for the former, instruction-file scoping for the
latter), so orgs' novelty here has to rest on specifics, not the base
analogy. **Loosest / most contrastive:** Google's monorepo-and-LSC culture —
legitimate as a foil, not as a lineage claim.

---

## 4. Cross-cutting synthesis

### Bet-by-bet scorecard

| Bet | Best prior art found | Verdict |
|---|---|---|
| #1 Protocol-over-app | None of the ~15 systems surveyed is harness-neutral; Aider's git-native state and Kiro's in-repo `.kiro/` come closest, both still shipped as installed products | No real competitor found |
| #2 Contract firewalls | OpenHands sub-agent isolation (runtime, not designed boundary); Gas Town role contracts (behavioral, not interface); Pact (mechanism match, different domain); Inverse Conway for AI agents (concept match, shallower enforcement) | Concept exists elsewhere for AI agents (Conway); dependency-level enforcement + defect-class propagation specifically does not |
| #3 Auftragstaktik | Corbett/MWI commander's-intent-for-drones (2025); Devin/Kiro plan-approval gates (weaker: approve, not deviate-and-log) | Doctrine is real and already applied to military AI; coding-agent-specific application with backbrief/huddle not found elsewhere |
| #4 Cross-provider council | Nothing — universally absent as a workflow across all ~15 systems; several make it technically assemblable | Genuinely unclaimed as a designed workflow |
| #5 Standup / forced observation | LangGraph `interrupt()`+`update_state()` (real but opt-in/per-node); Gas Town Witness/Deacon (external stuck-detection, not forced self-observation); Kiro hooks (reactive to self, not to world) | Sharpest, most novel claim in the survey — nothing found forces a healthy, running agent to re-observe external state at a chokepoint |
| #6 Model-tier economics | Devin Fusion, Aider architect/editor, Kiro tiering | Already mainstream; least distinctive bet |

### What's genuinely novel about orgs

Not any single idea — every individual component has real lineage, and in
several cases (Conway's Law for AI agents, Auftragstaktik for autonomous
systems, contract-governed agent boundaries under other names) someone has
already made the base move of applying the underlying concept to AI agents.
What this survey did not find *anywhere else*, including in the most
sophisticated multi-agent-fleet system surveyed (Gas Town), is:

- The **specific bundle**: protocol-not-app + dependency-enforced (not just
  instruction-scoped) contract firewalls + forced situational-awareness
  chokepoints + cross-provider review-to-fixpoint, combined.
- **Bet #5 in isolation** is the strongest single novelty claim to come out
  of this survey. Every system surveyed that has *any* human/external
  touchpoint during a run implements it as either an approval gate (binary,
  on the agent's own proposed action) or external stuck-detection (triggered
  by the agent's *failure* to progress). None forces a *healthy, still
  making-progress* agent to stop and check what changed in the world at a
  defined waypoint. If a rabbit-holing agent is specifically the one that
  stopped observing — rather than the one that got stuck in an obviously
  detectable way — that failure mode is structurally invisible to every
  watchdog-style mechanism surveyed (Gas Town's Witness/Deacon included),
  because watchdogs key off unproductive-looking activity, not off staleness
  of the agent's world-model. That's a real, separate failure mode from
  "stuck," and nothing surveyed targets it directly.
- The **defect-class-propagation observation** as a named empirical claim
  (a contract clarification in one team preventing a bug class in a
  downstream team with zero cross-team code reading) was not found stated
  anywhere else, in AI-agent or human-team contexts. Pact and the Inverse
  Conway Maneuver predict this *should* happen if contracts are enforced
  properly — but no source claims to have actually observed and named the
  effect.

### What orgs should steal

- **LangGraph's `interrupt()`/`update_state()` mechanics** are worth studying
  directly as an implementation reference for Standup, even though their
  design intent differs (opt-in per-node vs. forced systemic) — the
  state-injection-into-a-paused-run primitive is the right shape of tool.
- **Kiro's hooks** (`PreToolUse`-style triggers) are a reasonable model for
  *how* to wire a forced chokepoint into a harness without rebuilding the
  harness — reactive-to-self-action infrastructure could plausibly be
  repurposed to also fire on external events if the harness exposes them.
- **OpenHands' sub-agent delegation** (isolated context + workspace, only the
  final answer crosses back) is a clean existing pattern for the *isolation*
  half of a contract firewall, even though it lacks the *published-contract*
  half — useful as a harness-binding reference for Claude Code / other
  runtimes' native subagent primitives.
- **Gas Town's Witness/Deacon/Overseer escalation ladder** is a mature,
  battle-tested design for *who gets told what, in what order* when
  something goes wrong — worth reusing for orgs' own escalation destinations
  even though its trigger condition (stuck) differs from Standup's
  (stale world-model).
- **Pact's bilateral independent-verification discipline** — a machine- or
  agent-checkable pass/fail against the contract text, on *both* sides
  independently — is a concrete pattern to borrow for how doctrine's
  Interpretation/Amendment mechanism could be made checkable rather than
  purely prose-adjudicated.

### The Standup / 80-20 hypothesis, against this evidence

The hypothesis holds up, provisionally, on the "nothing else does this"
axis — no forced-observation mechanism for a healthy running agent was found
anywhere in ~15 systems surveyed, including systems (Gas Town, LangGraph)
built by people who clearly thought hard about human-in-the-loop and
liveness monitoring. That absence is real signal, not an artifact of
under-searching: LangGraph's interrupt mechanism shows the *primitive* is
easy to build once you think of it, and Gas Town's watchdogs show that
serious engineers building serious multi-agent-fleet tooling in the same
period (2025–2026) reached for stuck-detection rather than forced
re-observation — suggesting the two are not the same idea in most
practitioners' minds, and that orgs' framing (rabbit-holing = stopped
observing, not = stuck) is a genuinely different diagnosis of the failure
mode than the field's default.

What this survey *cannot* establish is the 80/20 cost-benefit claim itself —
that's an empirical question about orgs' own system, not something prior art
resolves. The absence of the mechanism elsewhere is consistent with two very
different explanations that this research cannot distinguish: (a) it's a
high-value idea nobody happened to build, or (b) it's a low-value idea for
most use cases (most surveyed systems run short, bounded, or human-supervised
enough tasks that rabbit-holing is a lesser risk than it is for orgs'
longer-horizon, higher-autonomy agents) and only matters once you're already
committed to the long-autonomous-run, low-supervision regime orgs is built
for. The hypothesis is worth testing on its own merits; prior art's
contribution here is narrower than "proves the hypothesis" — it's "confirms
the mechanism is currently unclaimed, not that it's currently
underappreciated for the right reasons."

---

## Sources cited

Multi-agent frameworks: MetaGPT
([paper](https://arxiv.org/abs/2308.00352),
[repo](https://github.com/foundationagents/metagpt)); ChatDev
([paper](https://arxiv.org/abs/2307.07924),
[ACL](https://aclanthology.org/2024.acl-long.810/),
[repo](https://github.com/OpenBMB/ChatDev)); AutoGen/AG2
([Agent Framework](https://github.com/microsoft/agent-framework),
[AG2](https://github.com/ag2ai/ag2),
[AutoGen 0.2 docs](https://microsoft.github.io/autogen/0.2/docs/Use-Cases/agent_chat/));
OpenAI Swarm/Agents SDK ([Swarm](https://github.com/openai/swarm),
[Agents SDK](https://openai.github.io/openai-agents-python/)); CrewAI
([repo](https://github.com/crewaiinc/crewai)); LangGraph
([repo](https://github.com/langchain-ai/langgraph)); AutoGPT
([repo](https://github.com/Significant-Gravitas/AutoGPT)).

Coding agents: GPT-Engineer
([repo](https://github.com/AntonOsika/gpt-engineer)); Devin
([Cognition](https://cognition.com/blog/introducing-devin)); OpenHands
([SDK](https://github.com/OpenHands/software-agent-sdk),
[delegation docs](https://docs.openhands.dev/sdk/guides/agent-delegation));
Aider ([site](https://aider.chat/)); SWE-agent
([paper](https://arxiv.org/abs/2405.15793),
[repo](https://github.com/SWE-agent/SWE-agent)); Amazon Kiro
([site](https://kiro.dev/), [hooks](https://kiro.dev/docs/hooks/)); Gas Town
([repo](https://github.com/gastownhall/gastown),
[origin post](https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04),
[v1.0 post](https://steve-yegge.medium.com/gas-town-from-clown-show-to-v1-0-c239d9a407ec),
[independent review 1](https://justin.abrah.ms/blog/2026-01-05-wrapping-my-head-around-gas-town.html),
[independent review 2](https://tenzinwangdhen.com/posts/gastown-good-bad-ugly/),
[independent review 3](https://maggieappleton.com/gastown)).

Theory: Auftragstaktik/mission command
([USNI](https://www.usni.org/magazines/proceedings/2025/may/auftragstaktik-leads-decisive-action),
[Army War College](https://press.armywarcollege.edu/cgi/viewcontent.cgi?article=1942&context=parameters),
[army.mil](https://www.army.mil/article/106872/understanding_mission_command),
[Boyd primary source](https://www.ausairpower.net/JRB/organic_design.pdf),
[Corbett/MWI](https://mwi.westpoint.edu/commanders-intent-for-machines-reimagining-unmanned-systems-control-in-communications-degraded-environments/));
Conway's Law ([Conway](https://www.melconway.com/Home/Conways_Law.html),
[Fowler/Lewis](https://martinfowler.com/articles/microservices.html),
[aipatternbook.com](https://aipatternbook.com/inverse-conway-maneuver));
Google engineering ([Potvin & Levenberg,
CACM](https://cacm.acm.org/research/why-google-stores-billions-of-lines-of-code-in-a-single-repository/),
[SWE at Google, LSC chapter](https://abseil.io/resources/swe-book/html/ch22.html),
[design docs](https://www.industrialempathy.com/posts/design-docs-at-google/));
speculative merging
([Brun et al., FoSER 2010](https://www.cs.ubc.ca/~rtholmes/papers/foser_2010_brun.pdf),
[AgenticFlict](https://arxiv.org/abs/2604.03551),
[Autonoma](https://getautonoma.com/blog/parallel-ai-agent-prs)); Pact
([docs](https://docs.pact.io/getting_started/how_pact_works),
[PactFlow MCP](https://pactflow.io/blog/pactflow-mcp-server/),
[Agent Capability Contract](https://arxiv.org/abs/2605.08258),
[trace-based assurance](https://arxiv.org/html/2603.18096v1)).
