# Narrow Claude modal detection to dialog frames

This ExecPlan follows `.planning/PLANS.md` and is a living record of the modal false-positive repair.

## Purpose / Big Picture

`tmux-message` must send into a live Claude composer even when a usage, update, or feedback-count footer is visible. It must defer on a real dialog. The visible proof is a fixture table, regression tests that fail before the repair, and a draft PR containing the exact tested commit.

## Progress

- [x] (2026-10-18) Read the Lead brief, role, binding, and issue; confirmed branch `tmux-message-modal` in the assigned worktree; started the ditz issue.
- [x] (2026-10-18) Started a private tmux server and scratch Claude 2.1.302 session. The unauthenticated run captured the login selector; the authenticated real config under an isolated cwd captured trust, permission, and background-exit dialogs without copying credentials.
- [x] (2026-10-18) Record the available real captures and label provisional synthetic fixtures: login, trust, permission, background-exit, scrubbed live auto-update and feedback-count footers, synthetic usage-limit and `/clear` footers, synthetic update dialog, and synthetic-unverified unsent-feedback dialog. Replacing the unavailable real dialogs is tracked in `tmux-message-replace-synthetic-dialog-fixtures` under MODAL-R2.
- [x] (2026-10-18) Add fixture assertions and verify the usage-limit regression fails on the old classifier (`modal` instead of `empty`).
- [x] (2026-10-18) Narrow both senders' modal classification without changing exit codes or status contract.
- [x] (2026-10-18) Run affected tests, repository configuration checks, and mutation probes: restoring broad footer matching makes the footer fixture fail; accepting ordinary-space choices as composers makes the unfamiliar-choice regression fail. The source-tree leak scan has a pre-existing failure filed as ditz `setup-leaks-existing-plans`.
- [x] (2026-10-18) Push the fixture/red-test commit and open draft PR #10.
- [ ] Review the MODAL-R2 delta to fixpoint, rerun exact-SHA gates, and merge PR #10 under MODAL-MERGE-OK.

## Surprises & Discoveries

- With `CLAUDE_CONFIG_DIR` and `XDG_STATE_HOME` in a scratch directory, interactive Claude 2.1.302 opens its login selector before the trust prompt. `--no-session-persistence` cannot be used in interactive mode. Capturing authenticated screens therefore needs a credential decision or an equivalent isolated authentication method.
- The existing `tmux-message.py` classifier searches any of the last 25 rows for `Esc to cancel`, so a usage-limit footer can become `modal` despite an intact composer. The legacy sender has a second, separate broad detector.
- The authenticated real config defaults to bypass permissions on this host, so a scratch permission dialog required `--permission-mode manual --setting-sources project`. `pwd` remained auto-allowed, while a scratch-file write produced the dialog. An older scratch-installed Claude 2.1.301 launched normally and did not display an update dialog.
- The read-only feedback-count footer was captured from Claude 2.1.299; that version is in its filename. The usage-limit and `/clear` fixtures are synthetic and labeled in their filenames and PR table.
- The owned scratch tmux session, 154 enumerated scratch transcript/trust entries, and scratch trust key were removed after fixture capture. The real authentication config and credential stayed in their original location.
- Council round 1 found that unfamiliar choice rows could be mistaken for writable composers. A positive composer check now requires the measured flush-left `❯` plus NBSP marker immediately beneath a rule, another rule below, and the cursor within that frame. Unknown choice layouts defer without input. This relies on the measured 2.1.30x prompt shape; a future Claude rendering change fails closed until remeasured.
- Convergence rounds 2–5 exposed a Codex ambiguity outside this Claude footer repair: quoted Claude dialog text can falsely block a live Codex composer, while a selected Codex choice with a retained context footer can resemble a writable draft. Attempts to address both here caused fresh approval and ordinary-draft regressions. This patch restores the pre-existing Codex parser and tracks the separate ambiguity in `tmux-message-codex-choice-versus-draft`. Round 6 restored master's narrow legacy pre-routing dialog checks and broad public Codex dialog guard; the Claude footer exemption applies only with a positively identified Claude composer.
- A truncated legacy combined-input frame with the cursor below its bottom rule now returns `unknown` instead of `busy`; both defer, and `unknown` describes the missing live frame more accurately.
- MODAL-R2 identified a no-cursor false positive: a draft beginning `Yes` inside a measured composer frame plus the usage-limit footer made the generic frame/selected/instruction branch return `modal`. The new synthetic fixture reproduced that result before the fix; selection evidence now excludes measured composer rows even when the caller lacks a cursor coordinate.
- A future dialog rendered in the exact measured composer shape could be mistaken for input. Recheck the shape when Claude's UI version changes; the synthetic update layout is invented and proves detector-anchor deferral only.

## Decision Log

- Decision: keep the scratch Claude session on a separate `tmux -L modal-fixture-751` server with cwd and state inside this worktree. Rationale: no control of live panes and no new shared session state. Date/author: 2026-10-18, Codex lead.
- Decision: do not copy OAuth credentials into scratch config without a ruling. Rationale: the brief explicitly stops at keys. Date/author: 2026-10-18, Codex lead.
- Decision: apply CTO ruling MODAL-R1. Use the authenticated real config in an isolated scratch cwd and tmux server; never copy credentials. Read-only live footer captures may be scrubbed, and usage-limit text from the XRW record is explicitly synthetic. Rationale: authenticated prompts were otherwise unreachable. Date/author: 2026-10-18, Codex lead.
- Decision: override the host's bypass-permissions default only inside the scratch session to induce the real permission prompt. Rationale: the default cannot produce that fixture. Date/author: 2026-10-18, Codex lead.
- Decision: request an evidence ruling for the update and unsent-feedback dialogs. A scratch-installed 2.1.301 did not show an update dialog, and the 2.1.302 feedback flow required a final outward submit; pressing Esc discarded the draft, so no exit prompt appeared. Rationale: manufacturing those screens would misstate the evidence or cross the outward-act stop. Date/author: 2026-10-18, Codex lead.
- Decision: remove a proposed footer text exclusion list after council review. It could delete text belonging to a real dialog. Require a positive live composer frame and leave footer text intact. Date/author: 2026-10-18, Codex lead.
- Decision: return Codex-specific parsing to the previous behavior after convergence round 5. The new blank-row heuristic could treat a selected approval choice as writable; strengthening it blocked ordinary drafts. Scope the PR to Claude footers and file a separate Codex issue with both failure modes. Date/author: 2026-10-18, Codex lead.
- Decision: keep master's narrow legacy pre-routing checks and broad public Codex dialog guard after round 6 identified their accidental removal. The broader public guard applies unless a live Claude composer frame is established at the cursor, preserving the footer repair. Date/author: 2026-10-18, Codex lead.
- Decision: apply CTO ruling MODAL-R2. Exact-string synthetic update and detector-anchor synthetic-unverified feedback dialogs are accepted for PR #10; neither blocks merge, and a follow-up requires real read-only replacement captures. Fix the no-cursor selected-draft false positive, review the delta to clean, then merge normally after final gates. Date/author: 2026-10-18, Codex lead.

## Outcomes & Retrospective

Pending.

## Context and Orientation

`skills/spawn-agent/scripts/tmux-message.py` classifies live input and receipts for the public sender. `claude-send.sh` is a legacy transport with its own `screen_state`. `claude-pane-detect.sh` shares Claude dialog/composer checks with the spawner. `claude-send-screen.py` parses composer content. Fixtures and tests live under `skills/spawn-agent/scripts/`. A modal is a Claude dialog, not arbitrary text that happens to contain a button phrase. An ambiguous frame remains deferred.

## Plan of Work

Capture reachable dialogs with `tmux capture-pane -e -p` in an isolated Claude Code 2.1.302 pane, and capture allowed status footers read-only from live panes, naming each fixture with its provenance. Add a table-driven test for the public and legacy detectors, paired with a positive composer assertion so a negative modal check cannot pass vacuously. Confirm old behavior is red. Use a shared frame classifier for known dialogs and a strict positive composer shape. Unknown or mixed input must never permit paste. Run mutation checks by temporarily restoring the old broad modal detector or weakening the composer shape, then restore the implementation and run affected gates.

## Concrete Steps

Work in the assigned feature worktree. Use a private tmux socket only for scratch Claude. Run `bash skills/spawn-agent/scripts/test-claude-send.sh`, `python3 skills/spawn-agent/scripts/test-tmux-message.py`, `bash skills/spawn-agent/scripts/test-tmux-message.sh`, and `python3 skills/spawn-agent/scripts/test-tmux-message-live.py`. Run the repository configuration checks identified by the repository's test scripts. Commit and push coherent milestones, then create a draft PR.

## Validation and Acceptance

Every captured footer must classify as a ready or occupied Claude composer according to its actual input, never as `modal`. Every captured dialog must classify as `modal`, with zero paste or Enter actions in the sender test. Restoring broad text matching or weakening the positive composer shape must make a regression test fail. The final gate commands must pass on the pushed SHA.

## Idempotence and Recovery

Tests must use private tmux or fake tmux state and never send to live panes. If an authentic fixture cannot be captured, record the missing condition and seek the named CTO's ruling before changing acceptance evidence. Retain an ambiguous message payload privately; do not replay it.

## Artifacts and Notes

The scratch Claude sessions use a private tmux server. Captured fixture files contain only dialog or footer regions, with local paths and unrelated conversation text scrubbed.

## Interfaces and Dependencies

Keep the public `tmux-message.sh` JSON status, exit codes, and reason contract. A new reason for ambiguous dialog frames would require a product ruling. Python 3.11+, Bash, tmux 3.6a, and Claude Code 2.1.302 are installed on this host.

Revision 2026-10-18: Initial plan records the login-first discovery and the credential stop condition before modifying classifiers.
Revision 2026-10-18: Recorded MODAL-R1, authentic and synthetic fixture provenance, and the scratch permission-mode deviation.
Revision 2026-10-18: Council round 1 led to a stricter positive composer shape and removal of footer text filtering, which could hide a dialog line.
