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
  an earlier cold-start audit filed as a protocol defect. The directives
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
2. It monitors. This draft takes that to mean reading committed records,
   quota posture and CTO sitreps on a stated cadence. It does not mean
   watching lanes turn by turn, which the CTO hat rules out for CTOs, and
   this draft also excludes reading other seats' panes. The doctrine's rule
   that routine healthy acknowledgements stay silent still applies to it.
3. It issues directives, where the Interface only carries the CEO's.

Whether master control replaces the Interface or sits beside a narrower
one is open question 5. The rest of this draft is written so that either
answer works.

Two existing rules bear on every part of the design:

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
  - start work on its own assessment. Every directive traces to one of the
    three sources below. *Auditable* against the decision record.
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
    work. *Auditable.* Review seats stay fresh, per provider and at the
    Lead tier, as they are today.
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
does not name the action, both go to the CEO as questions. Whether to
delegate more than this is open question 8.

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
until answered.

### Provenance and record

1. Each directive carries its source: the CEO's words quoted with their
   time, or the policy's text and location, or the requesting CTO and its
   event id. "Relaying the CEO" without the quotation is not a source.
2. Before sending, master control commits the directive (id, kind, source,
   recipient, envelope, checkpoint) to its decision record on a verified
   private remote. Where that record lives and who may read it is open
   question 7; public records cite only sanitized evidence. A source that
   contains keys, secrets or other restricted material is never quoted
   into the record; the directive points to where the CEO put it.

A CTO that cannot check a directive's source, as described above for each
kind, treats it as unverified. It may still do whatever it could already do on its own
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
alternatives.

## Risks

- **Second-hand intent.** Each relay compresses. A relay directive is the
  relayer's selection of what the CEO said. Quoting the source limits the
  problem; it does not remove it.
- **Drift into command.** A seat that sees everything will see things it
  could fix faster itself. Several of the fences above are prompt-only,
  and each is marked.
- **An approval queue by another name.** Described above. The seat should
  be judged on how little waits on it.
- **Review independence.** A seat that directs work has an interest in its
  outcome. This draft keeps it out of every review and approval role
  outright. If the CEO wants an exception when reviewers are scarce, that
  is a ruling for the CEO, not a default. Under a dual-hat or rotating
  arrangement the same ban follows the holder; question 1 says what that
  costs.
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
   Under (b) and (c) the holder is also a CTO, so the review and approval
   ban has to be worked out per holder: it keeps its duties inside its own
   project, but for as long as it holds the hat, and for work it directed
   while holding it, it cannot be reviewer or approver of record in any
   other project, and someone else must be named. Under (c) that follows
   each holder past the end of its turn for the work it directed.
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
     master control selects and seats the CTO. This is a new delegation,
     since seating a CTO changes a roster and spends Frontier quota.
   - (d) Master control may run a bounded lane itself. This gives it lane
     authority, which the CEO's description excludes.
   In (b) and (c) the CEO's instruction must name who owns the project's
   budget until the CTO is seated, and under the split in question 5 the
   seating act itself is the Interface's, on master control's routing.
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
   both, the outgoing holder's authority to send directives ends at the
   recorded handover and the successor's starts when the CEO's authority
   for it is on record, so there are never two.
   Recommendation: (b), with the CEO as the authority over master
   control's own seat, and no holder during a vacancy. It keeps the seat
   that directs separate from the seat that retires. Blocks: the doctrine
   amendment's shape.

6. **What evidence does a relayed pause, and a relayed lift, need?**
   Current doctrine already says who may lift a pause: the authority that
   set it. The open part is evidence, and the two directions differ.
   - Honoring a pause. Recommendation, not offered as a choice: a CTO
     holds at once on any notice of a CEO pause, verified or not, because
     holding is safe; it then checks the source and reports a mismatch to
     the CEO. An unverified pause is a temporary hold until the CEO
     confirms or denies it.
   - Resuming. Options: (a) a verified relay is enough; (b) a verified
     relay plus the CTO's own check of the CEO-authored source; (c) a lift
     is never relayed, and the CEO tells the CTO directly.
     Recommendation: (c).
   Directives sent to a lane before or during its pause do not resume by
   themselves: after a lift the CTO checks each for supersession before
   acting. Blocks: how fast a paused lane can resume.

7. **Where do the records live, and who may read them?** Two records are
   in play: the CEO-authored source that makes a relay verifiable, and
   master control's own decision record.
   - (a) A private record only the CEO and master control read. Recipients
     cannot check anything, so under this draft's rule every relay stays
     unverified.
   - (b) A private record every CTO can read: the CEO writes rulings
     there, master control writes directives there. Recipients verify; a
     successor reconstructs; every CTO sees every directive and ruling.
   - (c) Per-recipient records, each owned and written by master control
     alone, plus a CEO-authored ruling record the recipient can read.
     Recipients verify their own; the cross-project view needs master
     control.
   In every option, restricted material is referenced and never quoted,
   and quotations are kept to the words that carry the instruction.
   Recommendation: (b). If a record is unreachable, a directive is
   unverified. Blocks: provenance checking, and whether any relay can
   bind.

8. **Does the CEO want to grant master control any discretion?** The draft
   gives it none: a written policy that names the action and the
   circumstances is already the policy kind. The alternative is a concrete
   grant, for example: "when a project's lanes are idle and a CEO-named
   priority is unstaffed, master control may ask that project's CTO to
   take it, without a per-case instruction." Such a grant would transfer
   the decision of which CTO to ask and when; it would apply only in the
   circumstances it names; and its directives would stay advisory unless
   the CEO says they bind.
   - (a) No discretion.
   - (b) Named grants, written one at a time as cases arise, each saying
     what it transfers and whether it binds.
   Recommendation: (a) to start, moving to (b) case by case. Blocks: how
   often the CEO is asked.
