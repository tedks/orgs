---
name: orgs-crystal
description: Check selected concurrent branch pairs for textual conflicts and clean merges that fail a shared boundary test; deliver revision-stamped findings to the responsible lead and owners.
---

# orgs-crystal — speculative merge check

Crystal warns a sprint lead while concurrent package branches can still be repaired cheaply. It follows the idea in [Brun, Holmes, Ernst, and Notkin's Crystal tool demonstration](https://homes.cs.washington.edu/~mernst/pubs/vc-conflicts-fse2011-tooldemo.pdf): preview likely integrations and distinguish textual from test failures. This protocol is a small, manually invoked check, not the original Crystal implementation.

Tool: `tools/crystal/crystal-check.sh`. It computes merges with `git merge-tree`, extracts committed trees with `git archive` into temporary **plain files**, and runs an optional boundary-test command there. It creates no Git worktree, changes no ref, and pushes nothing. The plain-file directory has no `.git`; this is accident containment, not a security boundary. Use only trusted, non-daemonizing test commands.

## Choose work and cadence

At the cadence set by the sprint root, read the **current** roster and package status entries. Select only branches whose owners are actively working concurrently on this sprint and whose revisions and boundary tests you are authorized to inspect. Pass those branch names explicitly. Do not enumerate every local branch: old worktrees remain in this repository, and all-pairs work grows quadratically. With fewer than two active package branches, there is no branch pair to check; the command with no branch arguments is a clean no-op. The script also checks each selected branch against the named base, so an operator may check one branch's integration with trunk explicitly.

Choose the published boundary tests for the contract shared by the selected branches. The **same command** runs on each input revision and on every clean merged tree. If the branches need different tests, run separate focused checks with the relevant branches; do not call a red input a semantic conflict. The command must work on committed plain files without `.git`, clean/smudge filters, or build artifacts outside the extracted tree. The checker cannot supply secrets, network authority, or a test command for a project that requires Git metadata.

For example, from the project repository with two active package branches:

    tools/crystal/crystal-check.sh --base master \
      --test-cmd 'bash tests/boundary.sh' package-a package-b

Run once at the standup heartbeat in the full sprint variety. Without standup, run at each accepted-package integration; `skills/sprint/SKILL.md` owns that wiring. Do not start a background loop unless the sprint root has set one. Run after a material head change or boundary-test change if its earlier result matters to a decision.

## Read and deliver the report

The report prints full pinned commit IDs. A `baseline: ... FAIL` or `ERROR` means the check cannot establish an individually green input; pairs containing it skip semantic testing and the command exits `2`. A `merge: CONFLICT` is textual. `merge: clean` plus `tests: FAIL (semantic conflict)` means both inputs passed their baselines but their combined tree failed the boundary test; the command exits `1`. Exit `0` means the selected checks passed. A `stale:` line means a selected ref moved during the check; exit `2` makes the report non-actionable until rerun. A ref can move just after the final comparison, so recheck heads before acting on an old result.

For an actionable conflict, append one `crystal-conflict` event through `orgs-ledger` with the two full SHAs, test command or published test name, result, and owning packages. **Deliver the finding to the accountable lead and both branch owners** through the sprint's configured channel; a ledger entry alone is not delivery. If the same pair remains conflicted at the next cadence, cite the prior event and tell the lead the debt is still open. Avoid duplicate events for the same unchanged pair and failure. A contract provider changing a published contract migrates callers; a consumer with an invalid assumption fixes its use; the lead adjudicates a disputed ownership and records `semantic-deadlock` when needed. Whoever merges second cleans up by default unless the responsible lead decides otherwise.

The operator can rerun after a repair and record a clean result against the new SHAs. A clean old report does not clear a conflict on new heads. Crystal gives early evidence; the integration owner still runs its exact-head boundary gates before merging.

## Cost and limits

For `n` selected branches the tool attempts `n` base merges and `n(n-1)/2` branch pairs. With a test command it also tests the base and each branch once. The default invocation does no pair work, preserving sequential or no-fan-out varieties. `git archive` honors `export-ignore` and does not apply clean/smudge filters; repositories that need those transformations are not supported by this semantic check. GNU `timeout` bounds foreground tests when available, but cannot stop processes a test backgrounds. The script's README lists prerequisites and exit codes.
