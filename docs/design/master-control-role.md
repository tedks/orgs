# Master control: a proposed role

Status: draft proposal for the CEO, 2026-11-28. Not doctrine. Nothing in
`doctrine/` changes until the open questions at the end are ruled and an
amendment is councilled. Where this draft takes a position that departs
from current doctrine or from the CEO's description, it says so and puts
the choice among the open questions.

Terms: a *sitrep* is a consolidated status report on request. A *directive*
is a control message from master control to a project CTO.

## Why this is on the table

The author did not hear the CEO describe this role. It reached the author
relayed, in these terms: a "master control / global COO" that issues
directives to project CTOs, who keep command authority in their lanes;
global monitoring, dispatch and sitreps; no machine-resource management;
and "never starts work on personal assessments".

The seat that relayed it, which acted as central command on the night
described below, read an earlier version of this draft and corrected three
things in it. The corrections are marked where they apply and are that
seat's account, which the CEO can confirm or correct:

- The first version read the last clause as "never starts work on its own
  assessment of what would be good". The relaying seat says the CEO meant
  the CEO's own personal assessments: master control never starts or
  dispatches that work. What exactly falls under that is for the CEO to
  say; this draft does not define it.
- The relaying seat also says the CEO expected the role to show some
  initiative within priorities the CEO names. Whether to authorise that,
  and how much, is a separate decision and is open question 8.
- Not every directive that night claimed to relay the CEO: some were sent
  on that seat's own judgment. This is set out under the evidence below.

The author is one project's CTO, and spent one night receiving directives
from another project's CTO acting as central command. That is one seat's
view of one night. What it can and cannot support:

- **Directives arrived with their context.** The ones this CTO received
  said which lanes were blocked, which quota was about to lapse and which
  defects were costing other projects. This CTO acted on each inside its
  own lanes without waiting for the CEO. How other recipients fared was not
  observed.
- **Authority travelled by assertion, and came in two kinds.** Some of the
  directives this CTO received said they relayed the CEO. Others, as the
  relaying seat has since said, were sent on that seat's own
  judgment as central command, inside priorities the CEO had stated to it,
  and said so. This CTO did not register the difference at the time, and
  an earlier version of this draft wrongly said every directive claimed to
  relay the CEO. For neither kind did this CTO have a committed record to
  check: not the CEO's words for the first, and not the CEO's priorities
  or any grant of initiative for the second. It is the
  same class of gap, authority reachable only through a live message, that
  an earlier cold-start audit filed as a protocol defect in this
  repository's tracker, under the `doctrine` component. The directives
  this CTO
  received all asked for drafts and reversible work, with merges held for
  named approvals, so it acted only on what it could already do on its own
  authority. That shows a way to act under an unverifiable directive. It
  does not show that doing so is safe in general.
- **The relaying seat also held a lane.** It was a project CTO with its own
  pull requests in review, and it was named as an approver for work it had
  asked this CTO to stage. This CTO saw its own lane only: the directives
  it received and the reviews of its own work. It saw nothing of the
  relaying seat's lane, its other directives or its reasoning, so it can
  report no harm without being able to rule any out.
- **Transport was unreliable in one visible way.** Many of this CTO's own
  control messages that night came back from the sending tool marked
  ambiguous
  although they had landed, and each of those needed a manual read of the
  recipient's pane. The relaying seat reported that many of its sends did
  the same. No count was kept, so this is an impression, not a rate.

## What exists today

`doctrine/ROLES.md` has an **Interface** hat: "The CEO's interface to the
whole org: gets things rolling, brings sitreps, runs retirements and
migrations, maintains doctrine and infrastructure. Not a central commander.
CTOs stay autonomous and the interface does not monitor them; it
dispatches, verifies receipts, and goes quiet." It is marked occasional.

Master control as described differs from that hat in three ways:

1. It is a standing seat, not an occasional one.
2. It monitors. By the relaying seat's account the CEO asked it for
   sitreps drawn from the lanes, on what the CEO could steer, and it
   produced every sitrep that night by reading panes. That account
   supports the reporting request and says how the seat met it. It does
   not establish a standing permission to read panes, or permission to
   route by what is read. An earlier version of this draft excluded
   reading other seats' panes outright; that was the author's position and
   may be stricter than what the relaying seat reports the CEO asked for,
   so the whole matter is now open question 9. What this draft still holds: monitoring is for sitreps and
   routing, it is not watching lanes turn by turn to direct them, which
   the CTO hat rules out even for CTOs, and the doctrine's rule that
   routine healthy acknowledgements stay silent still applies.
3. It issues directives, where the Interface only carries the CEO's.

Whether master control replaces the Interface or sits beside a narrower
one is open question 5. The rest of this draft is written so that either
answer works.

Three existing rules bear on every part of the design:

- Standing authority: a coordinator pauses for four things only (money,
  the CEO's keys or secrets, product scope and rulings, irreversible or
  outward acts), and "a
  queue of approvals waiting on one person is the failure this exists to
  prevent." The CEO "is not an approval queue."
- Precedence: CEO rulings come first.
- Mission continuation: an explicit pause is absolute until the authority
  that set it lifts it.

## The role, as proposed

**Master control (Frontier tier, one standing seat for the org).** A
standing Frontier seat that monitors is a cost the doctrine otherwise
avoids, since it reserves that tier for synthesis, integration and audit.
The seat's budget is part of open question 1.

- **Owns:** the cross-project picture. Which CTO seats are filled, what
  each is holding, what is blocked on whom; cross-project sitreps; routing
  of CEO intent to the right CTO; its own decision record.
- **Issues:** directives, of three kinds, described below.
- **Decides alone:** which CTO a piece of CEO intent goes to; when to ask
  for a sitrep; what goes in its own record.
- **Does not** (marked *auditable* where a committed record or git history
  can show a breach, *prompt-only* where nothing but the seat's own
  discipline holds it):
  - start or dispatch work on the CEO's personal assessments. This is the
    CEO's condition as the relaying seat reports it; its exact scope is
    the CEO's to confirm. *Prompt-only*, since it turns on what the work
    is.
  - act on its own initiative, in this draft's baseline. Every directive
    traces to one of the three sources below. *Auditable* against the
    decision record. This fence is the author's design position and goes
    beyond the CEO's description; open question 8 puts the alternative,
    which is what the relaying seat understood the CEO to want.
  - command inside a lane: no briefs to another CTO's leads or workers.
    *Prompt-only.* No merges in another project. *Auditable.*
  - add approval points. An envelope in a directive may repeat what the
    CEO set; it never adds a "go" a CTO did not already need.
    *Auditable* where the CEO's envelope is on record; *prompt-only*
    otherwise.
  - issue a pause of its own, or lift one. A relayed CEO pause is the
    CEO's, and only the CEO lifts it. *Auditable.*
  - interpret CEO rulings or answer for the CEO from policy. *Prompt-only.*
  - hold a council seat, or be reviewer or approver of record, on any
    work it directed or any work outside a lane it holds in another hat.
    For a dedicated seat that is all work. *Auditable.* Review seats stay
    fresh, per provider and at the Lead tier, as they are today.
  - manage machine resources. Disk, memory, CPU, ports and host leases
    stay between their owners. *Prompt-only.*
  - arbitrate shared provider quota between projects. Each CTO owns its
    project's budget; a conflict over a shared window goes to the CEO.
    *Prompt-only*; a breach would show only as a directive that tells a CTO
    how to spend its budget.
- **Escalates:** money, keys and secrets, product scope and rulings,
  irreversible or outward acts, and any conflict between two CTOs that no existing rule
  settles.
- **Reports:** to the CEO only. Sitreps on request; blockers at once, one
  at a time, never batched.

### Directives: three kinds, by source

A directive's force follows where it comes from.

| Kind | Source | Force on the receiving CTO |
|---|---|---|
| Relay | An explicit CEO instruction that names the project or recipient and the action, quoted with its time | A CEO ruling, once verified (below). The CTO acknowledges it, or asks the CEO about it; it may not decline it. |
| Policy | A written, standing CEO policy that names this action and these circumstances | The policy binds as a CEO ruling. Master control's claim that it applies here is advisory: the CTO may dispute the match with a recorded reason, and the dispute goes to the CEO. It may not decline the policy itself. |
| Request | Another CTO asking for something the receiving CTO may already grant on its own authority | Advisory. The CTO may decline or defer with a recorded reason. Master control is a carrier; the request gains no authority by passing through it. |

A relay binds only as far as the CEO's own words go. A remark, a
suggestion, or an instruction about one project is not an instruction to
another, and master control may not make it one by choosing an excerpt.
Because the same seat selects the quotation, routes it and writes the
record, a matching entry in master control's record shows only what master
control recorded. It does not show that the CEO said it or meant this
recipient. So a relay counts as verified only when the CTO can check it
against something the CEO authored: a ruling the CEO wrote in a tracker or
decision record, or the CEO's direct confirmation. Where that authoritative
source should live is part of open question 7. Until one exists, every
relay is unverified and the rule under *Provenance and record* applies.

Anything else is not a directive master control may send. In particular, a
request that would need new authority (work the receiving CTO could not
start on its own standing authority), and a reading of a broad policy that
does not name the action, both go to the CEO as questions. Whether master
control may also direct on its own initiative is open question 8.

If the CEO adopts option (b) of open question 8, a fourth kind is added;
its source, verification and disposition rules are given there and would
join the rules in the next two sections.

A directive names the intent, why it comes now, the envelope as the CEO
set it, and a checkpoint. It does not name the how. Allocation, staffing,
sequencing and tier stay with the CTO.

### What a directive obliges

On receipt the CTO owes a disposition by the directive's checkpoint:

- for a verified relay: acknowledged, or a question to the CEO;
- for a policy directive: acknowledged, or a disputed match that goes to
  the CEO;
- for a request, or any unverified directive: accepted, declined or
  deferred, with a reason.

The CTO records the disposition in its own project record and sends master
control the event id. Master control alone writes its own decision record,
so each record keeps one owner. A missed checkpoint is a fact master
control reports in its next sitrep, not something it enforces.

When instructions conflict, the CEO's most recent explicit instruction
governs, whichever route it came by, direct or relayed and verified. A
scheduling conflict between two advisory directives is the CTO's to
settle. Where it is unclear which CEO instruction is later or whether one
supersedes the other, the CTO asks the CEO and holds the conflicting part
until answered. None of this applies to a pause: only an explicit lift
ends a pause, by the evidence open question 6 settles, and a later
instruction to a paused lane does not lift it by implication.

### Provenance and record

1. Each directive carries its source: the CEO's words quoted with their
   time, or the policy's text and location, or the requesting CTO and its
   event id. "Relaying the CEO" without the quotation is not a source. The
   one exception is restricted material, which is referenced by location
   and not quoted (point 2).
2. Before sending, master control commits the directive (id, kind, source,
   recipient, envelope, checkpoint) to its decision record on a verified
   private remote. Where that record lives and who may read it is open
   question 7; public records cite only sanitized evidence. A source that
   contains keys, secrets or other restricted material is never quoted
   into the record; the directive points to where the CEO put it.

A relay is verified as described above; a policy directive by reading the
policy at its cited location; a request by its event id in the asking
CTO's record or, where the receiving CTO cannot read that record, by
confirmation from the asking CTO. A CTO that cannot check a directive's source treats it as
unverified. It may still do whatever it could already do on its own
authority, and it records that it did so on its own authority and not on
the directive. That is what this CTO did on the night described.

### What a CTO keeps

Everything in the CTO hat today: the intent as written, the roster, lane
creation and retirement, merges of gated clean work, tier per lane, the
provider budget for its project, and direct access to the CEO. The CEO may
steer any CTO directly, as now. A direct CEO instruction is itself a CEO
ruling and needs no relay; the CTO tells master control when one changes
what a directive asked, so its record stays true.

### What changes for the CEO

The CEO can give intent to one seat and read one cross-project record,
without giving up direct steering. The cost is a new place for an approval
queue to form: any item that waits because "master control will ask the
CEO" is a queued approval by another name, which the doctrine names as the
failure standing authority exists to prevent. The design answer in this
draft is that master control never holds a question: it goes to the CEO at
once, or the CTO takes it there directly. Open question 4 puts the
alternatives. A second cost is stated plainly: until the CEO keeps a
ruling record the receiving CTO can read, a relay binds only after the CEO
confirms it directly, so relaying saves the CEO nothing on binding
instructions. Open question 7 decides whether such a record exists.

## Risks

- **Second-hand intent.** Each relay compresses. A relay directive is the
  relayer's selection of what the CEO said. Quoting the source limits the
  problem; it does not remove it.
- **Drift into command.** A seat that sees everything will see things it
  could fix faster itself. Several of the fences above are prompt-only,
  and each is marked. Taking both recommended options in questions 8 and
  9 widens this risk: the seat would read panes and direct on its own
  judgment. The record of priorities is what bounds it.
- **An approval queue by another name.** Described above. The seat should
  be judged on how little waits on it.
- **Review independence.** A seat that directs work has an interest in its
  outcome. This draft keeps a dedicated seat out of every council,
  review and approval role, and keeps any holder out of those roles on
  work it directed. If the CEO wants an exception when reviewers are
  scarce, that is a ruling for the CEO, not a default. Under a dual-hat or
  rotating arrangement the ban follows the holder; question 1 says what it
  gives up and what it keeps.
- **A seat that never retires.** A standing seat still compacts, migrates
  and is replaced. Its own re-seat is exactly the cold-start defect cited
  above: unless the CEO's authority for the new holder is on a committed
  record before it acts, every directive it sends inherits the gap. A
  handover must never leave two holders issuing directives.
- **A single point of context.** One seat holding the whole picture runs
  large contexts and meets the limits of compaction and retirement tooling
  first. Its record has to stand alone.
- **Conflict of interest when the seat rides a project CTO.** It directs
  peers, competes with them for quota and review seats, and reports on
  them.

## Open questions for the CEO

Questions 1 to 4 are the ones the CEO asked for. Questions 8 and 9 come
from the relaying seat's corrections. Each lists options, a recommendation
and what it blocks. The recommendations are the author's.

1. **Own seat, or riding a project CTO?**
   - (a) A dedicated session with no lane of its own.
   - (b) The hat worn by one project's CTO, as on the night described.
   - (c) Rotating among CTOs.
   Under (b) and (c) the holder is also a CTO, and the ban in the role
   follows the holder across both hats. What it gives up: while it holds
   the hat it is not a council seat, reviewer or approver of record on any
   work in another project; and it recuses from council service, review
   and approval on any work it directed as master control, in any project
   including its own, with another reviewer or approver named. What it
   keeps: its ordinary CTO duties on work
   in its own project that it did not direct as master control. Under (c)
   the recusal for work it directed outlasts its turn.
   Recommendation: (a). It has no lane competing for quota or review, and
   the context load argues for it. It still has interests: its own earlier
   directives and its own continuity. Cost: a standing Frontier seat and
   its quota. Blocks: staffing and budget for the seat.

2. **Who starts a lane in a project that has no CTO?**
   - (a) Nothing starts until the CEO seats a CTO directly.
   - (b) The CEO names the project, the CTO's provider and model, and the
     budget; master control relays that appointment and hands over the
     intent. The choice is the CEO's and master control only carries it.
   - (c) The CEO delegates the choice: within a named budget and scope,
     master control selects the CTO. This is a new delegation, since
     seating a CTO changes a roster and spends Frontier quota.
   - (d) Master control may run a bounded lane itself. This gives it lane
     authority, which the relayed description does not give it and which
     the CTO hat reserves to CTOs.
   In (b) and (c) the CEO's instruction must name who owns the project's
   budget until the CTO is seated. Who performs the seating act follows
   question 5: under the split it is the Interface, on master control's
   routing; under replacement it is master control. Either way it seats
   the CTO the CEO named under (b), or the one selected under the CEO's
   delegation in (c).
   Recommendation: (b). Blocks: work in dormant projects.

3. **How is "I'll coordinate locally" recorded?** Peers settling things
   directly is the doctrine's default, not a gap. The question is what
   master control's picture shows meanwhile.
   - (a) The CTO who says it records the handoff in its own project record
     with a next-update time, sends master control the event id, and sends
     the outcome's event id when done. If the update time passes, master
     control asks once and then reports the item as stale.
   - (b) Master control marks the item delegated and stops tracking.
     Cheapest; the picture goes dark for that item.
   - (c) Master control keeps asking through sitreps. Most visible; most
     chatter, and against quiet coordination.
   Recommendation: (a). Blocks: sitrep accuracy.

4. **What happens when a CTO is blocked on something only the CEO can
   answer?** Two different things are meant by this.
   - A product question or ruling. Options: (a) the CTO files it under the
     project tracker's `open-questions`, where the CEO already answers,
     tells the CEO at once, and master control only notes the block in its
     sitrep; (b) master control holds one ordered queue and presents the
     questions together, which trades time-to-decision for the CEO's
     attention and is the approval queue the doctrine warns against;
     (c) the CEO delegates interpretation: master control may answer from
     written policy and must say which. That is a grant of authority the
     baseline role does not have, and it makes the seat an interpreter of
     rulings.
     Recommendation: (a). Independent work in the lane continues while the
     question is open.
   - A permission prompt in the CTO's own session that only the human can
     accept. No agent message is consent. Options: (a) the CTO, or master
     control on noticing, tells the CEO which session is waiting, and no
     peer answers it; (b) nothing, and the lane waits to be found.
     Recommendation: (a).
   Blocks: how long lanes wait.

5. **Replace the Interface hat, or keep a narrower one beside master
   control?**
   - (a) Replace: master control takes dispatch, sitreps, retirements and
     migrations of CTO seats, and doctrine and infrastructure upkeep.
   - (b) Split: master control takes dispatch, monitoring and sitreps; an
     occasional Interface keeps lifecycle control (retirements,
     migrations, compaction on request) and doctrine and infrastructure.
   Under either, someone other than master control must hold lifecycle
   control over master control itself: who may pause, retire or re-seat
   it, and how a successor takes over. For a vacancy the CEO chooses
   between a named interim holder and no holder, in which case CTOs use
   their existing direct route to the CEO and nothing is dispatched. In
   both, the outgoing holder's authority to send directives ends at a
   recorded cutoff, and the successor's starts only after that cutoff and
   once the CEO's authority for it is on record, so there are never two.
   Recommendation: (b), with the CEO as the authority over master
   control's own seat, and no holder during a vacancy. It keeps the seat
   that directs separate from the seat that retires. Blocks: the doctrine
   amendment's shape.

6. **What evidence does a relayed pause, and a relayed lift, need?**
   Current doctrine already says who may lift a pause: the authority that
   set it. A pause the CEO has actually set is absolute. The open part is
   what a CTO does with a notice it cannot yet verify, and what it needs
   before resuming.
   - A pause notice the CTO cannot verify. Options: (a) hold the whole
     lane at once until the CEO confirms or denies it. Safest if the notice
     is real; a mistaken or stale notice stalls the lane, and every such
     hold waits on the CEO. (b) Keep working and ask the CEO at once;
     treat the pause as in force only once verified. Nothing stalls; a real
     pause is honored late. (c) Ask the CEO at once, hold every irreversible
     or outward step and any merge, and continue reversible work until the
     CEO answers. The hold ends when the CEO confirms the pause, which then
     applies in full, or denies it.
     Under (b) and (c) a real pause is not fully honored until it is
     verified. Adopting either amends Mission continuation's "absolute"
     for the unverified case, and that is a departure from current
     doctrine for the CEO to accept or refuse.
     Recommendation: (c).
   - Resuming. Options: (a) a verified relay is enough, which under this
     draft already means the CTO checked a CEO-authored source or had the
     CEO's confirmation; (b) a lift is never relayed, and the CEO tells
     the CTO directly.
     Recommendation: (b).
   Directives sent to a lane before or during its pause do not resume by
   themselves: after a lift the CTO checks each for supersession before
   acting. Blocks: how fast a paused lane can resume, and how much a
   mistaken notice can cost.

7. **Where do the records live, and who may read them?** Two records are
   in play: the CEO-authored source that makes a relay verifiable, and
   master control's own decision record.
   - (a) A private record only the CEO and master control read. Recipients
     cannot verify a relay from the record, so each binding relay needs the
     CEO's direct confirmation.
   - (b) A private record every CTO can read: the CEO writes rulings
     there, master control writes directives there. Recipients verify; a
     successor reconstructs; every CTO sees every directive and ruling.
   - (c) Per-recipient records, each owned and written by master control
     alone, plus a CEO-authored ruling record the recipient can read.
     Recipients verify their own; the cross-project view needs master
     control.
   In every option, restricted material is referenced and never quoted,
   and quotations are kept to the words that carry the instruction.
   Recommendation: (b). If a record is unreachable, a relay is unverified
   unless the CEO confirms it directly; a request can still be checked
   with the CTO that made it. Blocks: provenance
   checking, and whether a relay can bind without the CEO's confirmation.

8. **How much initiative does master control have?** This draft's baseline
   gives it none: it routes the CEO's instructions, applies written
   policies and carries CTO requests. That is the author's position. The
   relaying seat says the CEO expected more: a seat that works out, within
   priorities the CEO names, where effort is best spent, and directs CTOs
   accordingly. On the night described, two of the directives this CTO
   received were of that kind. This CTO found both useful and acted on
   them; that is one recipient and two reversible requests, and it does
   not compare initiative with ordinary routing between peers.
   - (a) No initiative. Everything traces to an instruction, a written
     policy or a request.
   - (b) Initiative inside CEO-named priorities. The CEO states the
     priorities and any limits in a record CTOs can read, and grants
     master control leave to direct inside them. That adds a fourth row to
     the directive table:

     | Kind | Source | Force on the receiving CTO |
     |---|---|---|
     | Initiative | The CEO's grant and the named priority the directive serves, both cited by their place in the record | Advisory, if the CEO chooses that form: the CTO verifies by reading the record, and accepts, declines or defers with a reason, as for a request, with no CEO ruling needed. |

     The CEO would also decide whether such a directive should bind
     instead. A binding form would put a judgment that is not the CEO's
     above a CTO's own authority over mission allocation, which nothing in
     current precedence does.
     Under either form every other fence stays: no added approval points,
     no pause, no review or approver role on directed work, nothing held
     or batched for the CEO, nothing touching the CEO's personal
     assessments, and the same escalations. The quota fence stays too: an
     initiative directive may point out a lapsing window or an unstaffed
     priority and recommend where effort goes; it never allocates a CTO's
     budget or arbitrates a shared window between projects.
   - (c) Named grants, written one at a time as cases arise, each saying
     what decision it transfers and whether its directives bind.
   Recommendation: (b), advisory. The author's first draft recommended
   (a). What (b) needs that the night lacked is the record: a CTO should
   be able to read the grant and the priority a directive claims to serve.
   Blocks: how often the CEO is asked, and whether the table has a fourth
   row.

9. **May master control read other seats' panes?** The relaying seat says
   the CEO asked for sitreps drawn from the lanes, and that every sitrep
   on the night was made that way. That shows panes are a timely source;
   it does not show they are the only current one.
   - (a) Yes, routinely and read-only, for sitreps and routing. Most
     current. Cost: a pane holds unfinished human input and private
     session content, which the doctrine keeps out of records, and a seat
     that reads panes is one step from steering by them.
   - (b) No. Sitreps come from committed records, quota posture and what
     CTOs report. Cost: sitreps are only as current as the records, and
     CTOs are asked for status more often.
   - (c) Only when the lane's own CTO asks for or agrees to the read.
     Least exposure of session content. Cost: sitreps lag, and a CTO that
     is itself stuck cannot ask.
   - (d) When master control judges a record is lagging or a lane looks
     stuck, it reads that pane and records that it did. More exposure than
     (c) and less than (a). Cost: "looks stuck" is itself a judgment.
   Under any option that allows reading, the same rule applies to records
   and to sitreps alike: nothing learned from a pane is quoted, summarised
   or inferred into them beyond operational state (working, idle, blocked
   on a prompt) and results already in a committed record, cited by event
   id or commit and not by their text, and only where the reader of the
   record or sitrep is allowed to know that work exists. The rule also
   covers the seat's own compaction notes and retirement shard: nothing
   read from a pane survives into them beyond operational state. Reading
   never leads to input into another CTO's lane. Whether what is read may
   inform routing, and not only sitreps, is part of the CEO's choice.
   Recommendation: (a) with that rule, for sitreps and for routing. This
   is the author's recommendation, not something the CEO is reported to
   have granted: the relaying seat's account covers sitreps on one night.
   The author's first draft said (b). Blocks: how sitreps are produced.
