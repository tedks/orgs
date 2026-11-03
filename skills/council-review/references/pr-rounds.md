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
`round_id` (`<head-prefix>-<UTC time>-<random hex>`), and the round's frame:
`head` (the frozen pushed head), `base` (the merge-base of head and the
target tip), `target_ref` and `target_oid` (the target tip at invocation).
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
and `cohort` (below). An `outcome` record repeats the frame and carries, per
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
full change again. A received outcome supersedes an EMPTY one for the same
seat in the same round: that is a late reviewer, attributed to that round's
frozen head. A round's `unresolved_findings` is the largest value any of its
outcome records reports, so a later record cannot lower it.

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
gives a warm `disposition`. Every non-full plan carries a `fallback` full
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
  is void, has no outcome, or reports undispositioned findings, the plan
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
seat, listed or not, has open Critical/Important findings at the head; that
at least one seat is clean; and that the round's count of undispositioned
findings is zero. EMPTY, missing, stale and unlisted seats are reported as
limits and never counted as clean.

## Resolution

`plan` routes the typed argument itself: `PR #N`, `#N` or `N` is a PR round;
`branch` is the current branch's open PR (advisory without one); `formal
<sha> [base]` is the alias; anything that starts like a PR reference or the
alias but is malformed is refused as `unrecognized-argument`; everything else
is an advisory target. It reads the PR with `gh pr view`, fetches
`refs/pull/N/head` and the target branch from the remote that points at the
PR's repository, and confirms with `git ls-remote` that both remote refs
still equal what `gh` reported; otherwise it refuses with `pr-moved` and the
runner retries. Locally cached objects therefore cannot hide a moved PR.

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
  invocation for a caller reason, it stores the argument's shape and the code
  in a small file inside the checkout's git directory; the next open record
  posted from that checkout carries those entries and posting it clears them,
  so each refusal is counted exactly once. `corrections: []` therefore means
  the helper saw no caller refusal in that checkout since the last round,
  not that nobody reported. A `pr-moved` retry is not a caller mistake.
  Valid alias use and branch routing are adoption, reported as `notes` and
  `alias_uses`.
- **Exclusions:** fixture tests never contact GitHub. Acceptance replays and
  dogfooding pass `plan --evaluation`.
- **Known limits:** a refusal in a checkout that never posts another round,
  and a mistyped argument the helper reads as an advisory target, are not
  observed.

To tally, find the PRs whose comments carry records, for example
`gh search prs --owner <owner> --match comments "council-review-round v1" --json repository,number`
(the records live in comments, not PR bodies), and run
`council_pr.py tally --since <deploy time> OWNER/REPO#N ...`. It prints the
window's rows, the rounds with mistakes, the mistake total and the alias
uses. A PR missing from the list shifts the window, so cite the search used.

## Compatibility alias

`formal <sha> [base]` is accepted through the host rollout that first
deploys PR rounds and removed by the next `council-review` change deployed to
hosts. Its use is the note `legacy-formal-alias`. It is refused with
`formal-sha-missing`, `supplied-sha-mismatch` or `supplied-base-mismatch`
unless it names the PR's current head and merge-base (abbreviated SHAs are
expanded first), and with `formal-without-pr` when the branch has no open PR.
