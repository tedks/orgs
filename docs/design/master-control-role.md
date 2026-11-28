# Master control: a proposed role

Status: draft proposal for the CEO, 2026-11-28. Not doctrine. Nothing in
`doctrine/` changes until the open questions at the end are ruled and an
amendment is councilled.

## Why this is on the table

The CEO described a possible role: a "master control" or global COO that
issues directives to project CTOs, who keep command authority inside their
lanes; that watches the whole org, dispatches and brings sitreps; that does
not manage machine resources; and that never starts work on its own
assessment of what would be good.

One night of the org running something close to it, with one project's CTO
acting as central command for the others, is the evidence available. What
that night showed:

- **It worked as a router.** Directives reached CTOs with their context
  attached (which lanes were blocked, which quota was about to expire, which
  defects were costing every project), and CTOs acted inside their own
  lanes without waiting for the CEO.
- **Authority travelled by assertion.** Each directive said it relayed the
  CEO. The receiving CTO had no committed record to check that against, the
  same gap the cold-start audits filed in November
  (`cto-reseat-authority-not-in-artifacts-20261116`). Every directive that
  night was reversible and drafts-only, which is why acting on it was safe.
  That will not always hold.
- **The relaying seat also held a lane.** The same agent was a project CTO
  with its own pull requests in review and was the reviewer of record for
  work it had directed another CTO to stage. Nothing went wrong; the
  structure would not have shown it if something had.
- **Transport was the weak link.** Roughly half of the control messages
  came back from the sender as "ambiguous" although they had landed, and
  each needed a manual read of the recipient's pane.

## What exists today

`doctrine/ROLES.md` has an **Interface** hat: the CEO's interface to the
whole org, which gets things rolling, brings sitreps, runs retirements and
migrations and maintains doctrine and infrastructure. It says in terms that
the Interface is "not a central commander", that CTOs stay autonomous, and
that the Interface "does not monitor them; it dispatches, verifies receipts,
and goes quiet."

Master control differs from that hat in two ways: it monitors continuously,
and it issues directives rather than only carrying the CEO's. Adopting it
means amending that paragraph, not adding a hat beside it.

## The role, as proposed

**Master control (Frontier tier, one seat for the org).**

- **Owns:** the cross-project picture. Which CTO seats are filled, what each
  is holding, what is blocked on whom; the queue of things only the CEO can
  answer; cross-project sitreps; dispatch of CEO intent to the right CTO.
- **Issues:** directives. A directive names the intent, the reason it comes
  now, the envelope (what may merge, what needs whose go), and a checkpoint.
  It does not name the how. The receiving CTO decides allocation, staffing,
  sequencing and tier, and may answer "not now" with a reason.
- **Decides alone:** which CTO a piece of CEO intent goes to; the order in
  which it raises blocked questions with the CEO; when to ask for a sitrep.
- **Does not:**
  - start work on its own assessment. Every directive traces to a CEO
    instruction, a standing CEO policy, or a request from a CTO.
  - command inside a lane: no briefs to another CTO's leads or workers, no
    merges in another project, no retirement of another CTO's agents except
    as the lifecycle controller the CEO has named.
  - manage machine resources. Disk, memory, CPU, ports and host leases stay
    between their owners under the host-hygiene rules.
  - review or gate work it directed, where another seat can.
- **Escalates:** money, keys, product scope and rulings, irreversible or
  outward acts, and any conflict between two CTOs it cannot route to an
  existing rule.
- **Reports:** to the CEO only. Sitreps on request; blockers at once; a
  decision log the CEO reads when they choose.

### Directives and their record

A directive is a control message, so the transport rules already apply. Two
additions make it checkable:

1. **Provenance.** Each directive carries its source: the CEO's words
   quoted with their time, or the standing policy it applies, or the CTO
   request it answers. "Relaying the CEO" without the quotation is not a
   source.
2. **A committed record.** Before sending, master control appends the
   directive (id, source, recipient, envelope, checkpoint) to a private
   decision record on the control remote. The recipient may check the id
   against that record, and a cold successor can reconstruct what was asked
   of whom. Routine steering stays in session.

A CTO that receives a directive whose source it cannot check acts on it only
inside what it could already do on its own authority, and says so. That is
what happened on the night described above, and it should be the stated
rule rather than each CTO's improvisation.

### What a CTO keeps

Everything in the CTO hat today: the intent as written, the roster, lane
creation and retirement, merges of gated clean work, tier per lane, the
provider budget for its project. A directive changes what a CTO is asked to
serve, never who decides how. A CTO may decline or defer a directive with a
recorded reason; the disagreement goes to the CEO, not to a second
directive.

### What changes for the CEO

The CEO steers one seat instead of many and reads one decision log. The
cost is a new place for an approval queue to form: every item waiting on
"master control will ask the CEO" is a queued approval by another name.
The seat should be measured on how short that queue is.

## Risks

- **Second-hand intent.** Each relay compresses. A directive is the relayer's
  reading of what the CEO said. Quoting the source is the mitigation; it
  does not remove the problem.
- **Drift into command.** A seat that watches everything will see things it
  could fix faster itself. The "does not" list is the only fence, and it is
  prompt-enforced.
- **A single point of failure and of context.** One seat holding the whole
  picture runs large contexts and hits the limits of compaction and
  retirement tooling first. Its record has to stand alone.
- **Conflict of interest when the seat rides a project CTO** (open question
  1): it directs peers, competes with them for quota and review seats, and
  reports on them.

## Open questions for the CEO

1. **Own seat, or riding a project CTO?** Options: a dedicated session with
   no lane of its own; the hat worn by one project's CTO, as on the night
   described; rotating among CTOs. Recommendation: its own seat. The
   conflict of interest and the context load both argue for it, and a seat
   with no lane has nothing to prefer. What it blocks: staffing and the
   quota budget for the seat.
2. **Who starts a lane in a project that has no CTO?** Options: master
   control seats a CTO and hands it the intent (it never runs the lane);
   master control may run a bounded lane itself; nothing starts until the
   CEO seats a CTO. Recommendation: the first, with the seating recorded as
   a directive. What it blocks: work in dormant projects.
3. **How is "I'll coordinate locally" recorded?** When a CTO tells master
   control it will settle something directly with a peer, the cross-project
   picture goes dark for that item. Options: the CTO owes a one-line outcome
   to the decision record; master control marks the item delegated and
   stops tracking; master control keeps tracking through sitreps.
   Recommendation: the first. What it blocks: sitrep accuracy.
4. **What happens when a CTO is blocked on a prompt only the CEO can
   answer?** Options: master control holds a single ordered queue of such
   questions and presents them together; each CTO asks the CEO directly and
   master control only notes the block; master control may answer from
   standing policy and must say which. Recommendation: the queue, plus the
   third option limited to policies the CEO has written down. What it
   blocks: how long lanes wait.
5. **Does master control hold lifecycle control** (retirements, migrations,
   compaction on request) for CTO seats, as the Interface hat does today,
   or does that stay a separate hat?
6. **What may a directive override?** A CEO pause is absolute today. Can a
   directive lift one by relaying the CEO, and if so what record does that
   need?
7. **Where does the decision record live**, and who else may read it?
