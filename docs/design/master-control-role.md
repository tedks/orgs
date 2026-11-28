# Master control: a proposed role

Status: draft proposal for the CEO, 2026-11-28. Not doctrine. Nothing in
`doctrine/` changes until the open questions at the end are ruled and an
amendment is councilled. Where this draft takes a position that departs
from current doctrine or from the CEO's description, it says so and puts
the choice among the open questions.

Terms: a *sitrep* is a consolidated status report on request. A *directive*
is a control message from master control to a project CTO.

## Why this is on the table

The CEO described a possible role: a "master control" or global COO that
issues directives to project CTOs, who keep command authority inside their
lanes; that watches the whole org, dispatches and brings sitreps; that does
not manage machine resources; and that never starts work on its own
assessment of what would be good.

The author is one project's CTO, and spent one night receiving directives
from another project's CTO acting as central command. That is one seat's
view of one night. What it can and cannot support:

- **Directives arrived with their context.** The ones this CTO received
  said which lanes were blocked, which quota was about to lapse and which
  defects were costing other projects. This CTO acted on each inside its
  own lanes without waiting for the CEO. How other recipients fared was not
  observed.
- **Authority travelled by assertion.** Each directive said it relayed the
  CEO. This CTO had no committed record to check that against. It is the
  same class of gap, authority reachable only through a live message, that
  a November cold-start audit filed as
  `cto-reseat-authority-not-in-artifacts-20261116`. The directives this CTO
  received all asked for drafts and reversible work, with merges held for
  named approvals, so it acted only on what it could already do on its own
  authority. That shows a way to act under an unverifiable directive. It
  does not show that doing so is safe in general.
- **The relaying seat also held a lane.** It was a project CTO with its own
  pull requests in review, and it was named as an approver for work it had
  asked this CTO to stage. This CTO saw no harm from that. It also had no
  way to see harm if there was any.
- **Transport was unreliable in one visible way.** Many of this CTO's own
  control messages that night came back from the sender marked ambiguous
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
2. It monitors. This draft takes that to mean reading committed records,
   quota posture and CTO sitreps on a stated cadence. It does not mean
   reading panes or watching lanes turn by turn, which the CTO hat already
   rules out for CTOs, and the doctrine's rule that routine healthy
   acknowledgements stay silent still applies to it.
3. It issues directives, where the Interface only carries the CEO's.

Whether master control replaces the Interface or sits beside a narrower
one is open question 5. The rest of this draft is written so that either
answer works.

Two existing rules bear on every part of the design:

- Standing authority: a coordinator pauses for four things only (money,
  keys, product scope and rulings, irreversible or outward acts), and "a
  queue of approvals waiting on one person is the failure this exists to
  prevent." The CEO "is not an approval queue."
- Precedence: CEO rulings come first. A pause holds until the authority
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
  - start work on its own assessment. Every directive traces to one of the
    three sources below. *Auditable* against the decision record.
  - command inside a lane: no briefs to another CTO's leads or workers.
    *Prompt-only.* No merges in another project. *Auditable.*
  - add approval points. An envelope in a directive may repeat what the
    CEO set; it never adds a "go" a CTO did not already need.
    *Auditable.*
  - issue a pause of its own, or lift one. A relayed CEO pause is the
    CEO's, and only the CEO lifts it. *Auditable.*
  - interpret CEO rulings or answer for the CEO from policy. *Prompt-only.*
  - hold a council seat, or be reviewer or approver of record, on any
    work. *Auditable.* Review seats stay fresh, per provider and at the
    Lead tier, as they are today.
  - manage machine resources. Disk, memory, CPU, ports and host leases
    stay between their owners. *Prompt-only.*
  - arbitrate shared provider quota between projects. Each CTO owns its
    project's budget; a conflict over a shared window goes to the CEO.
- **Escalates:** money, keys, product scope and rulings, irreversible or
  outward acts, and any conflict between two CTOs that no existing rule
  settles.
- **Reports:** to the CEO only. Sitreps on request; blockers at once, one
  at a time, never batched.

### Directives: three kinds, by source

A directive's force follows where it comes from.

| Kind | Source | Force on the receiving CTO |
|---|---|---|
| Relay | The CEO's words, quoted with their time | A CEO ruling. The CTO may ask the CEO about it; it may not decline it. |
| Policy | A written, standing CEO policy that names this action and these circumstances | Advisory. The CTO may decline or defer with a recorded reason. |
| Request | Another CTO asking for something a CTO may already grant on its own authority | Advisory, as above. Master control is a carrier here; the request gains no authority by passing through it. |

Anything else is not a directive master control may send. In particular, a
request that would need new authority (work in a project outside the
asking CTO's scope that the receiving CTO could not start on its own
standing authority), and a reading of a broad policy that does not name
the action, both go to the CEO as questions. Whether to delegate more than
this is open question 8.

A directive names the intent, why it comes now, the envelope as the CEO
set it, and a checkpoint. It does not name the how. Allocation, staffing,
sequencing and tier stay with the CTO.

### What a directive obliges

On receipt the CTO owes a disposition by the directive's checkpoint:
accepted, declined or deferred (for the two advisory kinds), or a question
to the CEO (for a relay). The CTO records it in its own project record and
sends master control the event id. Master control alone writes its own
decision record, so each record keeps one owner. A missed checkpoint is a
fact master control reports in its next sitrep, not something it enforces.
A scheduling conflict between two advisory directives is the CTO's to
settle; a conflict between a relay and anything else is a question for the
CEO.

### Provenance and record

1. Each directive carries its source: the CEO's words quoted with their
   time, or the policy's text and location, or the requesting CTO and its
   event id. "Relaying the CEO" without the quotation is not a source.
2. Before sending, master control commits the directive (id, kind, source,
   recipient, envelope, checkpoint) to its decision record on a verified
   private remote. Where that record lives and who may read it is open
   question 7; public records cite only sanitized evidence.

A CTO that cannot check a directive's source against that record treats it
as unverified. It may still do whatever it could already do on its own
authority, and it records that it did so on its own authority and not on
the directive. That is what this CTO did on the night described.

### What a CTO keeps

Everything in the CTO hat today: the intent as written, the roster, lane
creation and retirement, merges of gated clean work, tier per lane, the
provider budget for its project, and direct access to the CEO. The CEO may
steer any CTO directly, as now. A direct CEO instruction outranks any
directive, and the CTO tells master control so its record stays true.

### What changes for the CEO

The CEO can give intent to one seat and read one cross-project record,
without giving up direct steering. The cost is a new place for an approval
queue to form: any item that waits because "master control will ask the
CEO" is a queued approval by another name, which the doctrine names as the
failure standing authority exists to prevent. The design answer in this
draft is that master control never holds a question: it goes to the CEO at
once, or the CTO takes it there directly. Open question 4 puts the
alternatives.

## Risks

- **Second-hand intent.** Each relay compresses. A relay directive is the
  relayer's selection of what the CEO said. Quoting the source limits the
  problem; it does not remove it.
- **Drift into command.** A seat that sees everything will see things it
  could fix faster itself. Four of the fences above are prompt-only.
- **An approval queue by another name.** Described above. The seat should
  be judged on how little waits on it.
- **Review independence.** A seat that directs work has an interest in its
  outcome. This draft keeps it out of every review and approval role
  outright. If the CEO wants an exception when reviewers are scarce, that
  is a ruling for the CEO, not a default.
- **A seat that never retires.** A standing seat still compacts, migrates
  and is replaced. Its own re-seat is exactly the cold-start defect cited
  above: unless the CEO's authority for the new holder is on a committed
  record before it acts, every directive it sends inherits the gap. A
  vacancy must not leave two holders issuing directives, or none.
- **A single point of context.** One seat holding the whole picture runs
  large contexts and meets the limits of compaction and retirement tooling
  first. Its record has to stand alone.
- **Conflict of interest when the seat rides a project CTO.** It directs
  peers, competes with them for quota and review seats, and reports on
  them.

## Open questions for the CEO

Questions 1 to 4 are the ones the CEO asked for. Each lists options, a
recommendation and what it blocks. The recommendations are the author's.

1. **Own seat, or riding a project CTO?**
   - (a) A dedicated session with no lane of its own.
   - (b) The hat worn by one project's CTO, as on the night described.
   - (c) Rotating among CTOs.
   Recommendation: (a). It has no lane competing for quota or review, and
   the context load argues for it. It still has interests: its own earlier
   directives and its own continuity. Cost: a standing Frontier seat and
   its quota. Blocks: staffing and budget for the seat.

2. **Who starts a lane in a project that has no CTO?**
   - (a) Nothing starts until the CEO seats a CTO.
   - (b) Master control seats a CTO on a relay directive, meaning the CEO
     has said to start that project; it hands over the intent and never
     runs the lane. Until the CTO is seated the project has no budget
     owner, so the CEO's instruction must name the budget.
   - (c) Master control may run a bounded lane itself. This gives it lane
     authority, which the CEO's description excludes.
   Recommendation: (b). It needs a new delegation from the CEO: seating a
   CTO changes a roster and spends Frontier quota. Blocks: work in dormant
   projects.

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
     (c) master control answers from written policy and says which, which
     makes it an interpreter of rulings.
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
   it, how a successor takes over, and who dispatches during a vacancy.
   Recommendation: (b), with the CEO as the authority over master
   control's own seat and that authority committed to record before a
   successor acts. It keeps the seat that directs separate from the seat
   that retires. Blocks: the doctrine amendment's shape.

6. **What committed record must a relayed pause or lift carry before a CTO
   acts on it?** Current doctrine already says who may lift a pause: the
   authority that set it. The open part is evidence.
   - (a) The CEO's words quoted in a relay directive, committed to the
     decision record first.
   - (b) As (a), plus the CTO checks the record itself before resuming.
   - (c) A lift is never relayed; the CEO tells the CTO directly.
   Recommendation: (b) for a pause, which is safe to obey early; (c) for a
   lift, which is not. A pause also freezes directives already sent to
   that lane until it is lifted. Blocks: how fast a paused lane can
   resume.

7. **Where does the decision record live, and who may read it?**
   - (a) A private remote only the CEO and master control read. Recipients
     cannot verify their own directives.
   - (b) A private remote every CTO can read. Recipients verify; a
     successor reconstructs; every CTO sees every directive.
   - (c) Per-project private records that master control writes into, one
     per recipient. Recipients verify their own; the cross-project view
     needs master control.
   Recommendation: (b), with source quotations kept to the words that
   carry the instruction. If the record is unreachable, a directive is
   unverified and the rule above applies. Blocks: provenance checking.

8. **May master control act on anything beyond the three kinds?** The
   draft says no. The alternative is a written delegation from the CEO,
   for example a standing policy that lets it re-task idle capacity toward
   a named priority. Recommendation: start with none, and add written
   policies one at a time as cases arise. Blocks: how often the CEO is
   asked.
