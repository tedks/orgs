{{PROTOCOL_PREAMBLE}}# Fix round — apply the review findings

A review of `{{SERVER_PATH}}` returned the findings below. Apply them.

Your working directory is the git worktree at `{{RUN_TREE}}`, on branch
`{{RUN_BRANCH}}`. Work only there. Commit your fixes on that branch —
uncommitted work is not graded and is not re-reviewed.

## The findings

```json
{{FINDINGS_JSON}}
```

{{FINDINGS_PROSE}}

## How to apply them

- Fix every **Critical** and every **Important** finding.
- **Smallest defensible change.** Fix the defect, not the neighborhood. This
  is a fix round, not a refactor; scope creep here is what makes fix rounds
  introduce their own regressions.
- A finding you believe is **wrong** does not have to be obeyed — but it has to
  be answered. Say in one line why the code is already correct, with the
  evidence. Silently ignoring a finding is the one disallowed response.
- **Any test you add to pin a fix must be mutation-checked**: revert the fix,
  watch the test go red, restore the fix. A test that cannot fail reads as
  coverage while guarding nothing.
- Do not edit the conformance exam. It is frozen; a change to it is a spec
  amendment, not a fix.
- The server must still pass the exam when you are done. Re-run it.

## The specification

{{SPEC}}

## The frozen exam — read it, never edit it

```bash
{{EXAM}}
```

## Report

End your reply with a short list: for each finding, `FIXED <one line>` or
`DISPUTED <one line of evidence>`. Nothing else is an acceptable disposition.
