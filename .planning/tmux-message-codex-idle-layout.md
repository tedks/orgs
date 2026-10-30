# Recognize idle Codex composers across footer variants

This ExecPlan follows `.planning/PLANS.md` and is the current-state record for MODAL-M2.

## Purpose / Big Picture

An idle Codex input should accept guarded `tmux-message` delivery even if the status footer changes wording or model. An unknown layout must still defer before input. The user can see the result in regression tests that classify scrubbed live Codex captures and a footer variant as ready, and in distinct diagnostic reasons for unknown layout and unstable recognized input.

## Progress

- [x] (2026-10-29) Recovered the private checkpoint, read Lead doctrine and issue, confirmed the old branch clean, and created `fix/tmux-message-codex-idle-layout` from `origin/master` at `f703451`.
- [x] (2026-10-29) Started and synced ditz `tmux-message-codex-idle-unsupported-layout`.
- [x] (2026-10-29) Inspected two read-only, scrubbed October 18 live-current captures. Their original incident panes are gone; both captures classify `empty` today and are not incident reproductions.
- [x] (2026-10-29) Committed the two scrubbed live-current fixtures and one labeled synthetic footer variant at `6238a09`. The old source failed two focused tests: changed footer returned `unknown`, and recognized/unknown alternation reported `unsupported-layout`.
- [x] (2026-10-29) Opened draft PR #13 with the red-test commit and sent `MODAL-M2-ACK MODAL-CHECKPOINT` to `%321` with a verified submitted receipt.
- [x] (2026-10-29) Added guarded changed-footer recognition, exact post-paste ownership, transient-unknown readiness handling, and distinct `unstable-composer` diagnosis. Red tests covered the old behavior, the readiness-only intermediate state, and the interleaved-unknown state. Final local gates: Python 128 pass, tmux alias pass, private live tmux pass, legacy sender pass, config 21 pass, syntax/diff pass.
- [x] (2026-10-29) Pushed implementation at `75b1199` and marked PR #13 ready for Lead-tier council.
- [x] (2026-10-29) Council round 1 found two Important defects: archived unsent changed-footer composers could count as receipts, and multiline/collapsed pastes could be left unobserved. Added failing end-to-end tests and repaired both; 130 Python sender tests pass.
- [x] (2026-10-29) Convergence found a footer-update redraw could still count an archived unsent composer when the live input became unknown. A red test reproduced it; receipt filtering now retains the status row observed before paste. Filed wrapped-line residual as ditz `tmux-message-codex-changed-footer-wrapped-paste`.
- [x] (2026-10-29) A second convergence case showed two footer updates (A→B→C) defeating one remembered status row. Both single-line and multiline red tests reproduced false delivery. The receipt parser now excludes the measured bold Codex prompt, blank separator, and indented status shape in archived scrollback regardless of status wording.
- [x] (2026-10-29) Convergence then found that broad structural exclusion could hide a genuine bold submitted row followed by indented reply. A new positive receipt test failed before narrowing the guard; it now applies only while the current input is unknown or still matches the archived unsent text. The A→B→C and B→A dropped-Enter tests remain green.
- [x] (2026-10-29) The narrowed guard reopened false delivery when an outside clear made the live composer empty after a dropped Enter. A red test proved this; the guard now distinguishes the structured status row from an indented prose reply regardless of live input kind. A second red subtest changed the archived model name to prove that status comparison cannot rely on a fixed prefix.
- [x] (2026-10-30) CTO R3 ruled fail closed: the ambiguous bold/blank/indented Codex row is not a receipt. Updated the fallback archive guard to exclude it regardless of footer wording. New unit and end-to-end tests failed before the change and now verify `receipt-timeout`, including a genuine but ambiguous bold submission. The submitted-row capture follow-up is already its own agent-skills issue.
- [ ] PR #13 remains unmerged. The `MODAL-NEEDS-RULING` relay to `%321` deferred twice before paste; R3 was received here. MODAL-M3 has not started.
- [x] (2026-10-30) Lead-tier Codex native and Claude Opus convergence seats returned CLEAN on `0c105da..67e6c69`. Google agy was unavailable at quota. The focused sender suite, config checks, alias gate, and private live tmux gate pass at `67e6c69`.
- [ ] Run the legacy sender gate to completion, post the council/gate record on PR #13, report `MODAL-DONE` to `%321` or inbox fallback, and wait for CTO merge before starting MODAL-M3.

## Surprises & Discoveries

- The October 18 captures are after the incidents: `%748` says Context 79% left and `%749` says 96%, not the reported 38%. The originals are unavailable; fixture names must preserve that distinction.
- `tmux-message.py:composer` requires a footer regex after a Codex prompt. `ready()` initializes `last_reason` to `unsupported-layout` and can time out for unknown samples or moving recognized samples under the same label. Output above the composer is already excluded from `Input.fingerprint`.
- Harness-control used `--max-wait 5 --stable-wait 3`, so a correctly recognized stable composer had a chance to pass. The saved operation records only the deferred reason, not raw screen samples; the exact incident failure mode cannot be proved retrospectively.
- Readiness-only recognition was insufficient: the sender could paste into the synthetic changed-footer frame, then could not verify its own text and returned `paste-not-observed` before Enter. The post-paste test was red on that intermediate implementation.
- Council round 1 found that an archived copy of a still-unsent fallback composer could count as a submitted receipt after a dropped Enter. A second red test exposed `paste-not-observed` for multiline and collapsed fallback pastes. The repair compares archived composer rows to the currently observed status row and recognizes exact owned multiline text or a counted Codex paste marker with the same status row.
- Convergence exposed a second archived-composer false receipt when the footer changes after the dropped Enter, leaving the current input `unknown`. The receipt filter now also uses the status row measured before paste, even when the current input is unknown. The regression includes single-line unchanged, single-line changed, and multiline archived composer cases.
- A further convergence pass exposed the same receipt error after an intermediate status B was archived and the live status advanced to C. The structural archived-composer guard does not depend on either status string; regression subtests cover A→B→C for one-line and multiline payloads. Each expects `receipt-timeout` rather than a false delivered receipt.
- The structural guard was initially too broad for a real bold submitted row followed by indented assistant output. A positive synthetic receipt test failed; narrowing to unknown or matching live unsent text preserved the receipt. A separate follow-up, ditz `tmux-message-codex-bold-receipt-structure`, requests a real scrubbed submitted-row capture to check the actual ANSI layout.
- The current structural guard uses status field separators when the measured status has them, regardless of model name. When the measured status has no separators, it excludes the ambiguous bold-box shape conservatively. The positive synthetic receipt with a plain indented reply still counts; an outside clear after a dropped Enter does not make an archived status into a receipt. Real submitted-row evidence remains a follow-up.
- Council round on `0c105da` could not make both arbitrary footer changes and arbitrary indented replies safe using screen text alone. An archived unsent bold input box and a genuine bold submitted row can both be `› payload`, a blank row, and an indented row. CTO R3 accepted the safety-first recommendation: exclude the ambiguous receipt and return `receipt-timeout` even after a genuine send. The real submitted-row follow-up remains open for measured evidence.
- A 5-second readiness window with 3-second stability requirement fails on the real normal-footer fixture when a single unreadable capture appears every fourth sample; the pre-change loop reset stability on every unknown frame and timed out `unstable-composer`. The operation log did not save screen samples, so this is a plausible mechanism, not proof of the three original incidents.

## Decision Log

- Decision: use the two scrubbed captures as real layout evidence but not as reproduced failures; construct a clearly synthetic footer variant to exercise the missing-footer branch. Rationale: the incident panes have ended and the captured states classify ready on current code. Date/Author: 2026-10-29, Codex Lead.
- Decision: keep the cursor and selected-choice guards when recognizing a new footer. Rationale: a quoted prompt or choice screen must not authorize input. Date/Author: 2026-10-29, Codex Lead.
- Decision: the fallback accepts the measured bold Codex prompt, dim idle placeholder, blank separator, and one indented final status row with arbitrary wording. After paste, it accepts only the exact outgoing single-line text at the end cursor with the same status row observed immediately before paste. Rationale: preserve unknown choice and unrelated draft deferrals while completing one guarded send. Date/Author: 2026-10-29, Codex Lead.
- Decision: an unreadable readiness sample does not erase a previously seen composer fingerprint; acting still requires two fresh consecutive recognized samples after the gap and an immediate unchanged sample before paste. A changed known draft across the gap remains `human-typing`. Rationale: transient capture races should not consume harness-control's bounded readiness window, while uncertain or changing input stays closed. Date/Author: 2026-10-29, Codex Lead.
- Decision: preserve fallback delivery for multiline and counted collapsed paste markers rather than preflight-defer those payloads. Rationale: `tmux-message` accepts them generally, and the fallback can verify full visible text or the exact count while requiring the same measured status row and end cursor. Date/Author: 2026-10-29, Codex Lead.

## Outcomes & Retrospective

Pending implementation and review.

## Context and Orientation

Owned source is `skills/spawn-agent/scripts/tmux-message.py`; its `composer()` returns an `Input` and `Sender.ready()` waits for two stable samples. `skills/spawn-agent/scripts/claude-send-screen.py` is the related post-paste ownership detector. Tests live in `skills/spawn-agent/scripts/test-tmux-message.py` and `test-claude-send.sh`; fixtures live in `skills/spawn-agent/scripts/fixtures/claude-send/`. Private, already scrubbed evidence is under `/home/tedks/.local/state/org-briefs/20261018/modal-m2-evidence/` and must not be relabeled as incident captures.

## Assumptions and failure modes

- A real Codex composer has a flush-left `›` row containing the cursor; for empty input the placeholder is dim and the cursor is at x=2. The pane can have moving transcript rows above it.
- The footer below it can change model or wording. Footer text alone cannot prove a composer; a choice list or unrelated text below the prompt must defer.
- A malformed or truncated capture, cursor outside the composer, or change in draft text/cursor between observations is uncertain and must not cause paste or Enter.
- The caller can be malicious or stale: a quoted `›` in transcript, an approval menu, and an old payload in the input must not be treated as an empty composer.

## Plan of Work

The red-test commit is in draft PR #13. Adjust Codex composer recognition based on cursor and measured prompt structure while leaving modal and input ownership guards intact. A post-paste test proves delivery requires exact owned text and a new receipt. Adjust readiness reason when recognized samples never stabilize. Run focused tests, full changed-skill gates and repository config tests; the pre-fix red runs supply mutation evidence. Review the whole PR and subsequent fix deltas with one native Codex Lead seat and available foreign Lead seats to a clean round.

## Concrete Steps

From `/home/tedks/Projects/agent-skills/tmux-message-codex-idle`, run `python3 skills/spawn-agent/scripts/test-tmux-message.py`, `bash skills/spawn-agent/scripts/test-claude-send.sh`, `bash skills/spawn-agent/scripts/test-tmux-message.sh`, `python3 skills/spawn-agent/scripts/test-tmux-message-live.py`, and `python3 tests/test_config.py`. The new focused test must fail before the implementation and pass after; no test may send to a live pane.

## Validation and Acceptance

An exact cursor in an idle Codex composer classifies `empty` with both captured footer shapes and the synthetic changed footer. A quoted prompt, choice row, truncated screen or mismatched cursor remains unknown/modal/occupied. A stable recognized composer reaches readiness; no stable recognized composer reports `unsupported-layout`, while a recognized composer that keeps changing reports `human-typing` or an explicit stability reason. Final gates run on the exact PR head reported for merge.

## Idempotence and Recovery

All tests use recorded or synthetic screens and local mocks. Re-running them does not send to live panes. Source changes are reversible by Git; keep the old merged branch and original private captures intact. Ditz mutations are checked before retry and synced separately from source push.

## Artifacts and Notes

Evidence: 2026-10-18 read-only `capture-pane -e -p` scrubbed captures, with placeholder transcript rows and preserved composer/footer. The PR table says “live current, after incident.” At `6238a09`, focused tests had 2 failures of 3; after a readiness-only patch, the full-delivery test failed `paste-not-observed` with zero Enters.

## Interfaces and Dependencies

Keep `composer(Frame) -> Input` and `Sender.ready() -> (Frame, Input)` or `DeliveryError` contracts. Do not change the public JSON status or exit-code contract; only refine `reason` values when useful. `claude-send-screen.py` is a separate post-paste parser and should change only if a failing regression shows its ownership path is affected.

## Revision note

2026-10-29: Created after resuming the October 18 checkpoint; records the unavailable incident capture and the current base before edits.

2026-10-29: Updated after the red-test commit, post-paste ownership failure, and interleaved-unreadable-capture failure; narrowed the fallback and retained exact evidence labels.
