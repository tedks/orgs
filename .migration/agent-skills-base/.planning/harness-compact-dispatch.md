# Make self compaction dispatch after native idle

This ExecPlan is a living document and follows `.planning/PLANS.md`. The current task is tracked as ditz issue `e33bd34f09f01e29d055f31df6d88591e07eda16` in the agent-skills metadata branch.

## Purpose / Big Picture

An agent that calls `self_compact` as its last tool action should receive a scheduled watcher receipt, finish its turn, then see the watcher type `/compact` into its own pane. Once a new native compaction event and pane marker are observed, the watcher sends one continuation containing the checkpoint path. If native idle or guarded delivery cannot be established, the pane receives one visible failure notice and the operation record explains what happened. This prevents a silent stalled lane with active obligations.

## Progress

### R1 ruling and merge gate (2026-10-16)

Ted ruled both product questions on the ditz issues. A submitted intervening operator turn now cancels the scheduled `/compact`, records `cancelled/intervening_turn`, and sends one pane notice. The observer watches briefly for a compaction event from another actor; when observed it records `completed_by_other` and sends one continuation. A delivered `/compact` with no confirmed completion records `unconfirmed` with its delivery receipt, sends a distinct one-time notice, and does not retry or continue. The watch uses an explicit nonterminal `watching_other` state, so a fresh request cannot race it. Claude's real boundary and compact-summary row shapes are covered, along with Codex peer events and focus-triggered compaction.

The focused core suite passes 103 tests. Available Codex native and Claude Opus council seats converged CLEAN on the R1 delta and the final narrow dispatch fix; Google agy remains unavailable due quota. A full `nix flake check` and `nix build .#harness-control` are running on a changing diff and will be rerun at the exact final commit before merge. The draft PR remains #7. No affected live pane or operation record was used in tests.

Next: obtain exact-head green Nix gates, push and ready PR #7, merge normally, close/sync the main ditz issue and the answered product questions, send `LANDED #7 <sha>` to the CTO pane, then complete the private retirement shard and `RETIRE-READY` handoff.

### Checkpoint for session 01a14353 (2026-10-16)

Worktree: `/home/tedks/Projects/agent-skills/harness-compact-dispatch`, branch `fix/harness-compact-dispatch`, draft PR #7. Head `6b7e8d5` is pushed. The initial implementation and native Claude/Codex disposable tests are complete. A full Codex core suite passed at the current head: 78 tests. An earlier `nix flake check` is still running as unified exec session 5661; it checks pre-review commit `a858308`, so the final head needs a fresh gate anyway. Foreign Claude Opus review completed and reported 1 Critical, 7 Important, plus nits; Google agy seat was unavailable (individual quota, reset ~42 h). Native Codex seat reported 2 Important. The two Codex findings were fixed in `6b7e8d5`: guarded cancellation on idle re-arm and sender-budget reservation; visible notice for a definite deferred sender refusal. Tests cover both. Claude's C1 overlaps this fix, except its focus re-arm note still needs inspection.

Claude findings still to triage and fix: I1 cancellation race in `_observe` final warning stage, I2 interrupted `_failure_notice` can strand `warning_dispatching`, I3 queue-operation and queued_command must mark busy in re-arm mode, I4 permanent native transcript errors should fail early instead of waiting 60 min, I5 possible post-turn `api-request` false busy and sidechain metadata, I6 real incident payload fixture, I7 tests for actual extended wait and notice/cancellation paths. I8 contains two operator product rulings; asynchronous questions have been sent to Ted: whether intervening operator turns cancel the scheduled compact and require a fresh checkpoint (recommended), and whether delivered-but-unconfirmed compaction gets a distinct review notice (recommended). Do not decide these unilaterally. The Claude review text is in `/home/tedks/.local/state/council-hcompact.PZndin/claude.out` and has exit status 0. The agy error is in the same directory.

Read-only verification of BOTH real incident transcripts found post-baseline `event_msg` / `task_complete` rows with both `turn_id` and `root_turn_id` equal to the fixture ID. First timestamp `2026-10-15T21:17:08.227Z`, second `2026-10-16T03:22:30.982Z`. Add sanitized rows to fixture and use them in the regression test. Never mutate the affected live panes or records.

### Post-compaction review follow-up (2026-10-16)

The Claude C1/I1/I2/I3/I4/I6/I7 findings have code and test fixes pending full gate. The final warning decision is made under the state guard, and a crashed warning send recovers to its prior terminal state with an ambiguous notice receipt. Queued Claude input stays busy in re-arm mode; deterministic transcript shape errors defer immediately. The incident fixture now contains sanitized real completion rows. Core suite: 86 passed.

I5 was investigated read-only in seven native Claude runs and 40 bounded recent transcripts: 17 `api-request` rows after a root `turn_duration` all preceded a new root user row. Seven `querySource: sdk` rows occurred within active root turns. Sampled request rows had no `isSidechain` property. Keep post-duration `api-request` busy; explicit sidechain rows are ignored. A hypothetical orphan background request remains a fail-closed long wait, with no observed example. Product decisions I8(a)/(b) remain with Ted; the questions were re-sent after compaction. No live affected pane or record was changed.

First convergence found one Important from each available seat. Native Codex identified a queue marker before the current turn's completion being erased by that completion. A read-only survey found multiple queued messages and queue events before turn duration; the safe response is now immediate deferral for any post-baseline root queue event or queued-command attachment. Claude identified further permanent parser errors saved in `_idle_cursor.error`; all such errors now defer immediately. Claude also noted a weak receipt race, fixed by rereading after taking the observer lease. The current core suite passes 89 tests. The previous full `nix flake check` failed at a stale mutation anchor, which has been updated; mutation and final gates must run again at the final commit. Both available seats need a new fix-delta convergence pass. Google agy remains unavailable.

Second convergence on `0b7216d..f898f39` was CLEAN in both Codex and Claude seats. Claude noted two more permanent pre-cursor errors (`idle_transcript_replaced_or_truncated`, `idle_observation_limit`); these are now included in immediate deferral and require a final delta review/gate. The two pending product rulings are tracked separately as `compact-intervening-turn-policy` and `compact-unconfirmed-review-notice` under `open-questions`; `ditz sync` succeeded. Their answers block merge. Other review nits are either fixed in this branch or can be tracked as proportional follow-up if still present after final review.

Final proportional convergence on `f898f39..c37b260` was CLEAN in both available seats. The lower-priority review items were filed under `compact-observer-hardening-followup` and synced. `nix build .#harness-control` passed at `c37b260`. `nix flake check` reached mutation checks and failed because the existing `focus_pair_rearm` mutation anchor matched two locations; the anchor is now scoped to the focus branch. An AST preflight found no remaining literal anchor count mismatches. A full gate at the next commit remains required.

At `40405c3`, full `nix flake check` reached the end of core mutation checks; two mutants survived because their tests raised `TypeError` before recording an assertion failure. A fresh Luna worker added two explicit failure-notice presence assertions. Its standalone core suite passed 89 tests; its full core mutation run exited 0 with every mutant killed, including `failure_notice` and `warning_before_terminal`. The lead reviewed the exact two-assertion diff. A final full Nix gate remains required on the new commit. The product rulings still block merge.

Next: finish triage/fixes and tests, run Nix check/build at final head, run council convergence on fix delta to CLEAN, mark PR ready and merge normally only with green gates, close/sync ditz issue `e33bd34f09f01e29d055f31df6d88591e07eda16`, notify CTO tmux `%321` with `LANDED #7 <sha>` (or BLOCKED), then file and push retirement shard and send RETIRE-READY. The private native reports are `/home/tedks/.local/state/hcompact-native-ycmcc16p/report.json` (Claude) and `/home/tedks/.local/state/hcompact-native-a_ogrjrb/report.json` (Codex). Native Codex used direct interactive launch; `--no-daemon` blank startup UI was not pasted into.

- [x] (2026-10-16 06:15 UTC) Claimed an isolated agent-skills worktree and ditz issue. Read the two incident records without changing live panes or state.
- [x] (2026-10-16 06:20 UTC) Reproduced the Codex idle parser miss with sanitized fixtures from both incidents; the test failed before the parser fix.
- [x] (2026-10-16 06:30 UTC) Changed compact scheduling, the native idle bound, re-arming, failure notice, and transition history. Core unit tests and synthetic private tmux integration pass.
- [x] (2026-10-16 06:41 UTC) Disposable native Claude and Codex runs each completed compact, witnessed the pane marker and transcript event, delivered the continuation, released the owned tmux server, and left the disposable Git repository clean.
- [ ] Complete mutation checks and Nix quality gates at the exact branch head.
- [ ] Push a draft PR, run the provider council to a clean fixpoint, merge normally, sync and close the ditz issue, notify the dotfiles CTO, then file a private retirement shard.

## Surprises & Discoveries

The records `b353c001…` and `17f313…` ended idle observation at 155 seconds because 145 seconds of a 300 second operation were reserved for sending and compaction observation. Their native root `task_complete` events occurred 3.34 and 2.54 seconds after the request. The parser still held `turn=null`: those long turns began outside its bounded 8 MiB tail. A post-baseline completion whose `turn_id` equals `root_turn_id` is enough to identify the root turn when no newer input intervened.

Claude Code 2.1.301 emits `api-request-shape`, `api-request-blob`, and `api-request` metadata before a focus turn. The old parser classified these as unknown. Its pane shows `⎿ Compacted`, where the older observed row included a parenthetical summary hint. Both shapes must count as native completion markers. The native test initially exposed a further race: a deferred state was visible while the failure notice was still dispatching. The watcher now keeps that stage nonterminal.

The native Codex 0.163.0 `--no-daemon` launcher produced an unsupported blank startup screen in a disposable pane, with no paste attempted. A direct disposable Codex launch without that flag completed the full watcher path. The two real no-daemon incident records still exercise the root-completion parser regression. This difference is evidence about startup transport only; it does not prove no-daemon compaction end to end.

## Decision Log

- Decision: Treat `timeout_seconds` on `self_compact` as a per-turn native idle bound, defaulting to 3600 seconds, with a fresh sender budget after idle. Focus starts a new idle bound. Reason: the calling turn remains open at tool return, so a sender reserve cannot also be the observation bound. Date/author: 2026-10-16, Codex lead.
- Decision: Keep exit and ordinary send budgets at their existing default of 300 seconds. Reason: this incident concerns self compaction and the exit contract has different safety semantics. Date/author: 2026-10-16, Codex lead.
- Decision: Let a compact watcher follow new root turns and reset its idle deadline, while retaining strict focus-turn matching and guarded sender checks. Reason: a new turn should not strand the scheduled compaction, but focus must still be the exact message delivered by this watcher. Date/author: 2026-10-16, Codex lead.
- Decision: A failure notice is attempted once only when `/compact` was definitely not dispatched. Ambiguous post-input delivery never uses the text “NOT DISPATCHED.” Reason: do not tell an agent to repeat a command that may already have been sent. Date/author: 2026-10-16, Codex lead.

## Orientation and work

`harness-control/server.py` defines the MCP tool default and its user-facing contract. `harness-control/harness_control.py` creates private operation records, starts a detached `setsid` watcher, reads native transcript rows, sends through the shared `tmux-message` transport, confirms a transcript boundary plus pane marker, and sends the continuation. `harness-control/test_harness_control_core.py` contains offline tests, mutation checks, and a private synthetic tmux integration. `harness-control/test_compact_native.py` is an opt-in real Claude/Codex rehearsal: it creates a unique private tmux server and disposable Git repository, retains a report, and kills only the server it created. The sanitized incident fixture is `harness-control/fixtures/compact-stalled-records.json`.

The operation record stores transitions for state, deadlines, delivery, completion, continuation, and failure notice. It stores no pane or conversation text in the transition list. The sender rechecks the pinned process, pane, session, and native idle before typing a slash command. Unknown or replaced transcript evidence remains a refusal or deferred result.

## Validation

From `/home/tedks/Projects/agent-skills/harness-compact-dispatch`, run `python3 -m unittest -q test_harness_control_core` in `harness-control/`, `python3 test_harness_control_core.py --mutation-check`, and `python3 test_harness_control_core.py --live-integration`. Run `nix flake check` and `nix build .#harness-control` from the repository root; the Nix check supplies the MCP Python dependency and runs the package tests. Run `python3 test_compact_native.py --harness claude` and `--harness codex` only on an owned test machine with available model tokens. Successful native results print `native compact and continuation confirmed` and retain `report.json` with `completed`, `delivered`, `confirmed`, `delivered`, `server_released: true`, and an empty disposable repository status.

The regression test for the two incident fixtures failed against the previous implementation (`busy_or_unknown` instead of `idle`). Mutation checks must kill a missing root completion fallback, a shortened idle bound, a disabled new-turn rearm, and a missing failure notice. Review the branch diff and rerun gates after any rebase or council fix.

## Outcomes & Retrospective

Implementation and native evidence are in hand. The implementation is committed at `32783ef`; Nix gates, review, merge, and handoff remain. No live affected pane or operation record was modified.
