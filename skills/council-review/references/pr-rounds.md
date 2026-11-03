# PR round records

This reference defines what `scripts/council_pr.py` writes to and reads from a
PR, and the rules it applies. `scripts/test_council_pr.py` replays each rule
below as a scenario fixture, and its `--mutation-check` confirms the fixtures
fail when a guard is removed.

## The record

A round record is a PR comment holding a readable summary and one
authoritative block:

```
<!-- council-review-round
{ ...JSON... }
-->
```

The summary's first line contains `council-review-round v1`, which makes
records findable with search. The JSON has `schema: "council-review-round"`,
`version: 1`, `phase` (`open` or `outcome`), `repo` (`owner/name`), `pr`,
`round_id` (`<first 12 hex of head>-<UTC time>-<random hex>`, bound to the
record's own head), and the round's frame:
`head` (the frozen pushed head), `base` (the merge-base of head and the
target tip), `target_ref` and `target_oid` (the target branch's live remote tip at invocation).
All SHAs are full 40-character hashes. Every object has a closed key set: a
record with any field not listed here is invalid.

Each seat entry has `seat` (provider: `anthropic`, `openai`, `google` or a
fourth provider), `mechanism` (`native`, `inline` or `ask-agent`), `model` (a
short model name), `scope`, `from`, `continuity` and `status`. Scopes:

- `full` — reviewed `base..head`; `from` must equal `base`.
- `delta` — reviewed `from..head`, where `from` is this seat's previous
  coverage; requires `continuity: warm`.
- `disposition` — no new bytes at an unchanged head; the seat re-examined
  the dispositions of its own findings; `from` equals `head`; requires warm.

An `open` record is posted before dispatch. Its seats have status
`dispatched`; its `covered` list names seats whose clean review of this head
is reused rather than re-dispatched; it must name at least one seat either
way. Its `invocation` block holds `shape`, `route`, `notes`, `corrections`
(each `{id, shape, reason}` with a random 8-hex event id), `unknown` (event
ids of lost refusal capture) and `cohort` (below). An `outcome` record repeats the frame and carries, per
seat, `status: received` (with `verdict` `clean` or `findings` and `counts`
of `critical`, `important`, `nit`; the verdict must agree with the counts) or
`status: empty` with a `reason` code: `unavailable`, `usage-limit`,
`timeout`, `permission-denied`, `partial-prompt`, `not-installed`,
`tool-error` or `abandoned`. It also carries `unresolved_findings`, the number
of earlier findings not yet dispositioned. A round may have several outcome
records (a late reviewer posts its own), and a disposition-only round's
outcome has no seats.

Public records hold only closed vocabularies: argument shapes (`pr-ref`,
`branch`, `formal-sha`, `formal-sha-base`, `formal-other`, `none`, `other`),
routes (`pr`, `branch-pr`, `legacy-formal`), notes (`legacy-formal-alias`,
`branch-routed-to-pr`, `unpushed-local-commits`), cohorts (`production`,
`evaluation`), caller refusal codes (`unrecognized-argument`,
`pr-not-found`, `pr-not-open`, `formal-sha-missing`, `formal-without-pr`,
`supplied-sha-mismatch`, `supplied-base-mismatch`) and EMPTY reason codes.
Raw argument text, paths, quota readings and session ids cannot enter a
valid record. Findings and dispositions go in a separate readable comment,
which the runner keeps free of private material.

## Which comments count

A comment counts only if its author's association is `OWNER`, `MEMBER` or
`COLLABORATOR` and it was never edited (`updated_at` equals `created_at`).
It is ignored, with the reason reported, when its block is unterminated,
repeated, not JSON, of another schema or a newer version, about another
repository or PR, or malformed by the rules above. An outcome without an open
record for its round id is ignored. Comments without a block are ordinary
discussion and are skipped silently. Ignoring a comment can only cost a
review; it can never produce coverage or clearance.

Re-posting an identical record is a retry and counts once. A round is
**void** when it has two different open records, an outcome whose frame
differs from its open record, an outcome for a seat it did not dispatch, an
outcome claiming a scope other than its dispatch (except a full review), or
two different received outcomes for one seat. A void round grants nothing,
and it erases the coverage of every seat it names: those seats review the
full change again. Every frame named by any of a void round's open records
counts, so a conflicting record cannot hide the void from a head. A received outcome supersedes an EMPTY one for the same
seat in the same round: that is a late reviewer, attributed to that round's
frozen head. A round's `unresolved_findings` is the largest value any of its
outcome records reports, so a later record cannot lower it.

**Standing findings, the one rule.** A seat's findings stand from the first
posting of its received findings outcome until that seat later posts a
received clean outcome, or another seat posts a received review in a round at
the current head whose open record was posted after the findings. That later
round's prompts carry the standing findings and their dispositions, so its
received reviews examine them: a delta after a fix push examines the fix, and
a `disposition` review at an unchanged head examines a rejection or deferral.
EMPTY outcomes, `covered` entries and silence examine nothing. Every case
follows from this: a late reviewer's findings posted after the latest round
opened stand; a finder that goes EMPTY does not erase its findings, and a
present seat's received disposition review resolves them without a push; a
round that only carries seats as covered resolves nothing. An identical
outcome re-posted later is a retry and keeps its first posting time.

## Planning

Rounds are ordered by the GitHub time (then comment id) of their open record.
For each seat, coverage is built by walking the rounds with the current
`base` and `target_ref`: a void round naming the seat clears its coverage; a
received `full` outcome sets coverage to that round's head; a warm `delta` or
`disposition` outcome extends coverage only if its `from` equals the coverage
so far and is an ancestor of the round's head; anything else clears it.
Finally, coverage that is not an ancestor of the current head (a force-push)
is cleared.

The plan per seat is then: no coverage gives `full` from `base`; coverage at
an older ancestor gives a warm `delta` from it; coverage at the head with a
clean latest verdict is `covered`; coverage at the head with open findings
gives a warm `disposition`. While any finding stands, covered seats are
dispatched as `disposition` instead, and the plan lists `standing_findings`
for every prompt. Every non-full plan carries a `fallback` full
review for a seat whose warm identity is unavailable. Consequences:

- A fix push gives each warm seat its own last-reviewed..head delta, and an
  EMPTY or new seat the whole change.
- A force-push, a merge of the target into the branch that moves the
  merge-base, or a retarget sends every seat back to a full review.
- A restarted reviewer cannot record a delta (a fresh delta is invalid), and
  a delta that skips commits or crosses a force-push breaks the chain, so
  neither becomes coverage.
- Re-running at the same head dispatches only uncovered seats and seats with
  open findings. When nothing needs dispatch but the latest round at the head
  is void, has no outcome, reports undispositioned findings, or a finding
  stands, the plan
  opens a disposition-only round (every seat `covered`) whose outcome
  restates the count. When nothing is outstanding, no round is opened and the
  invocation is not a measured round.

## Clearance

`check --expect-head <sha>` re-resolves the live PR and judges the **latest
round opened at its head**, void or not. CLEAN requires that the live head
equals the expected head; that the latest round is not void (an earlier round
never stands in for it); that every seat it dispatched has a received or
EMPTY outcome (a silent seat blocks; record EMPTY if it is not coming); that
every `covered` seat still chains to a clean review of the head; that no
finding stands (above); that at least one seat is clean; and that the
round's count of undispositioned findings is zero. EMPTY, missing, stale and
unlisted seats are reported as limits and never counted as clean.

## Resolution

`plan` routes the typed argument itself: `PR #N`, `#N` or `N` is a PR round;
`branch` is the current branch's open PR (advisory without one); `formal
<sha> [base]` is the alias; anything that starts like a PR reference or the
alias but is malformed is refused as `unrecognized-argument`; everything else
is an advisory target. It reads the PR with `gh pr view`, fetches
`refs/pull/N/head` and the target branch from the remote that points at the
PR's repository, and confirms with `git ls-remote` that `refs/pull/N/head`
still equals `gh`'s `headRefOid`; otherwise it refuses with `pr-moved` and
the runner retries. Locally cached objects therefore cannot hide a moved PR.
The target tip is the remote's own `refs/heads/<target>` at that moment, not
`gh`'s `baseRefOid`, which GitHub records at the PR's last push and leaves
behind when the target branch moves. Only a PR-reference prefix (`PR`,
`PR #`, `PR7`, `#`) makes a malformed argument a refusal; names such as
`PR.md` or `pr-notes.md` are advisory file targets. `check` accepts the same
PR reference forms.

## Invocation measurement

The question is how often callers still get the argument or mode wrong.

- **Start:** the time the dotfiles owner deploys this interface to hosts,
  recorded on ditz `council-invocation-measurement`; `tally --since <that
  time>` ignores anything opened earlier.
- **Unit:** one production **round**: a round id with a valid open record of
  cohort `production` and at least one outcome record, counted once however
  often it was re-posted. A void round still counts: it was an invocation.
  Abandoned open-only rounds, evaluation rounds and invocations that open no
  round are not counted.
- **Window:** the first ten such rounds across every repository, in
  open-record order. It never resets per PR.
- **Mistakes:** a round's `corrections`. When the helper refuses an
  invocation for a caller reason, it appends `{id, shape, reason, cohort}`
  to a small file inside the checkout's git directory (each worktree has its
  own). The next open record of the same cohort posted from that checkout
  carries those entries, and posting it removes exactly those ids, so a
  retried post can never remove a newer refusal and each refusal is counted
  once; the tally also counts each event id once, so two rounds planned
  concurrently cannot double-count. Updates to the file hold an exclusive
  lock, so concurrent sessions in one checkout cannot lose each other's
  entries. There is no cap. If a refusal cannot be recorded at all, the
  helper says so on stderr and the refusal is unknown to the tally. A pending file that
  cannot be read is moved aside (`.unreadable-<id>`, kept for inspection),
  and the next production record lists that id under `unknown`: the tally
  reports such rounds as `rounds_with_unknown_corrections`, whose mistake
  count is a floor, never a zero. `corrections: []` with `unknown: []` means
  the helper saw no caller refusal in that checkout since its last round. A
  `pr-moved` retry is not a caller mistake. Valid alias use and branch
  routing are adoption, reported as `notes` and `alias_uses`.
- **Exclusions:** fixture tests never contact GitHub. Acceptance replays and
  dogfooding pass `plan --evaluation`; their refusals are kept apart and
  never carried into, or consumed by, a production round.
- **Known limits:** a refusal in a checkout that never posts another round,
  and a mistyped argument the helper reads as an advisory target, are not
  observed.

To tally, find the PRs whose comments carry records, for example
`gh search prs --owner <owner> --match comments "council-review-round v1" --json repository,number`
(the records live in comments, not PR bodies), and run
`council_pr.py tally --since <deploy time> OWNER/REPO#N ...` (`--since` in
GitHub's form, `YYYY-MM-DDTHH:MM:SSZ`). It prints the
window's rows, the rounds with mistakes, the mistake total and the alias
uses. A PR missing from the list shifts the window, so cite the search used.

## Compatibility alias

`formal <sha> [base]` is accepted through the host rollout that first
deploys PR rounds and removed by the next `council-review` change deployed to
hosts. Its use is the note `legacy-formal-alias`. It is refused with
`formal-sha-missing`, `supplied-sha-mismatch` or `supplied-base-mismatch`
unless it names the PR's current head and merge-base (abbreviated SHAs are
expanded first), and with `formal-without-pr` when the branch has no open PR.
