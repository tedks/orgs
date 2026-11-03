# PR round records

This reference defines what `scripts/council_pr.py` writes to and reads from a
PR, and the rules it applies. `scripts/test_council_pr.py` replays each rule
below as a scenario fixture.

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
`round_id`, and the round's frame: `head` (the frozen pushed head),
`base` (the merge-base of head and the target tip), `target_ref` and
`target_oid` (the target tip at invocation). All SHAs are full 40-character
hashes.

Each seat entry has `seat` (provider: `anthropic`, `openai`, `google` or a
fourth provider), `mechanism`, `model`, `scope`, `from`, `continuity` and
`status`. Scopes:

- `full` — reviewed `base..head`; `from` must equal `base`.
- `delta` — reviewed `from..head`, where `from` is this seat's previous
  coverage; requires `continuity: warm`.
- `disposition` — no new bytes at an unchanged head; the seat re-examined
  the dispositions of its own findings; `from` equals `head`; requires warm.

An `open` record is posted before dispatch. Its seats have status
`dispatched`; its `covered` list names seats whose clean review of this head
is reused rather than re-dispatched; its `invocation` block holds `shape`,
`route`, `notes` and `corrections` (below). An `outcome` record repeats the
frame and carries `status: received` (with `verdict` `clean` or `findings`
and `counts` of `critical`, `important`, `nit`; the verdict must agree with
the counts) or `status: empty` with a `reason` code: `unavailable`,
`usage-limit`, `timeout`, `permission-denied`, `partial-prompt`,
`not-installed`, `tool-error` or `abandoned`. It also carries
`unresolved_findings`, the number of earlier findings not yet dispositioned.
A round may have several outcome records (a late reviewer posts its own).

Public records hold only closed vocabularies: argument shapes (`pr-ref`,
`branch`, `formal-sha`, `formal-sha-base`, `formal-other`, `none`, `other`),
routes (`pr`, `branch-pr`, `legacy-formal`), notes (`legacy-formal-alias`,
`branch-routed-to-pr`, `unpushed-local-commits`), refusal codes
(`pr-not-open`, `head-not-fetchable`, `supplied-sha-mismatch`,
`supplied-base-mismatch`, `unrecognized-argument`, and `wrong-pr` for a PR
number the caller corrected) and EMPTY
reason codes. Raw argument text, paths, quota readings and session ids never
enter a record; a record that tries is invalid. Findings and dispositions go
in the readable summary the runner writes, which the runner keeps free of
private material.

## Which comments count

A comment counts only if its author's association is `OWNER`, `MEMBER` or
`COLLABORATOR` and it was never edited (`updated_at` equals `created_at`).
It is ignored, with the reason reported, when its block is unterminated,
repeated, not JSON, of another schema or a newer version, about another
repository or PR, or malformed by the rules above. An outcome without an open
record for its round id is ignored. Comments without a block are ordinary
discussion and are skipped silently. Ignoring a record can only cost a review;
it can never produce coverage.

Re-posting an identical record is a retry and counts once. Two different
open records for one round id, an outcome whose frame differs from its open
record, an outcome for a seat the round did not dispatch, an outcome claiming
a scope other than its dispatch (except a full review), or two different
received outcomes for one seat make the whole round count for nothing. A
received outcome supersedes an EMPTY one for the same seat in the same round:
that is a late reviewer, attributed to that round's frozen head.

## Planning

Rounds are ordered by the GitHub time of their open record. For each seat,
coverage is built by walking its received outcomes in that order, using only
rounds with the current `base` and `target_ref`: a `full` outcome sets
coverage to that round's head; a warm `delta` or `disposition` outcome
extends coverage only if its `from` equals the coverage so far; anything else
clears coverage. Finally, coverage that is not an ancestor of the current
head (a force-push) is cleared.

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
  a delta that skips commits breaks the chain, so neither becomes coverage.
- Re-running at the same head dispatches only uncovered seats and seats with
  open findings.

## Clearance

`check` re-resolves the live PR and judges the latest round opened at its
head. CLEAN requires that the live head equals the expected head (when
given); that every seat that round dispatched has a received or EMPTY outcome
(a silent seat blocks; record EMPTY if it is not coming); that every
`covered` seat still chains to a clean review of the head; that no seat has
open Critical/Important findings; that at least one seat is clean; and that
the round's latest outcome reports zero unresolved findings. EMPTY, missing
and stale seats are reported as limits and never counted as clean.

## Invocation measurement

The question is how often callers still get the argument or mode wrong. The
unit is one **round**: a round id with a valid open record and at least one
outcome record, counted once however often it was re-posted. An abandoned
open-only round is not counted; the session that reruns carries its
corrections forward. The window is the first ten such rounds across every
repository, ordered by open-record time, starting with the first version-1
open record; it never resets per PR. A round's mistakes are its
`corrections`, the invocations refused earlier in the same session before
this one succeeded, each recorded as shape and refusal code. Valid use of the
compatibility alias or branch routing is adoption, reported separately, not a
mistake. Fixture tests never contact GitHub and cannot be counted. Refusals
in a session that never completes a round are not observed; that is a known
limit of keeping the measurement ceremony-free.

To tally, list the PRs that carry records (for example
`gh search prs --owner <owner> "council-review-round v1" --json repository,number`)
and run `council_pr.py tally OWNER/REPO#N ...`. It prints the window's rows,
the rounds with mistakes, the mistake total and the alias uses.

## Compatibility alias

`formal <sha> [base]` is accepted through the host rollout that first
deploys PR rounds and removed by the next `council-review` change deployed to
hosts. Its use is the note `legacy-formal-alias`. It is refused with
`supplied-sha-mismatch` or `supplied-base-mismatch` when it names anything
other than the PR's current head and merge-base.
