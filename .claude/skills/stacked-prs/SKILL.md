---
name: stacked-prs
description: Detailed workflow for managing stacked PRs. Use when rebasing a PR stack, resolving merge conflicts in a stack, merging stacked PRs, or when user mentions "stack" and "PR" together.
---

<!-- Codex reads this same file through the .codex/skills/stacked-prs symlink. Never
     copy it into .codex/skills -- the copy that used to live there drifted a commit
     behind; see the skills comment in scripts/install/install-codex-config. -->

# Stacked PRs Workflow

## Mental Model

A stack is a chain: `main ← PR1 ← PR2 ← PR3`. Each PR targets the one below it, except the bottom which targets main. The stack is a sequence of logical changes that build on each other.

## PR Targeting

- **Only the bottom PR targets main.**
- PR2 targets PR1's branch
- PR3 targets PR2's branch
- If you're confused about what targets what, run `gh pr view --json baseRefName`

This is what keeps each PR's diff limited to its own changes. Target them
all at main instead and every PR shows the cumulative diff of the whole
stack below it, which is what makes a stack unreviewable.

## Merging a Stack

When the bottom PR is approved:

1. Merge PR1 into main (normal merge, not squash)
2. **Stop.** Don't script the rest.
3. Checkout PR2's branch
4. `git rebase main`
5. If conflicts arise: **read them.** Open the file, look at both versions, edit to synthesize. Never `--ours` or `--theirs` blindly.
6. After resolving, `git rebase --continue`
7. Force push PR2's branch
8. Now PR2 targets main. Update the PR base if needed: `gh pr edit --base main`
9. Repeat for PR3, rebasing onto PR2's (now updated) branch

## Conflict Resolution Philosophy

Conflicts mean two changes touched the same place. The answer is almost never "pick one." The answer is usually "both changes were intended, integrate them."

- Open the conflicted file in an editor
- Read the `<<<<<<<` section (theirs) and `>>>>>>>` section (ours)
- Write what the code *should* be given both intentions
- Remove the conflict markers
- Test if possible before continuing

## What NOT to Do

- Don't write a bash loop that rebases all branches
- Don't use `-X ours` or `-X theirs`
- Don't resolve conflicts without reading them
- Don't try to update all PR targets at once
- Don't delete branches until the whole stack is merged

## Checking Stack State

```bash
# See what a PR targets
gh pr view <pr-number> --json baseRefName,headRefName

# See all your open PRs
gh pr list --author @me

# See commit graph
git log --oneline --graph main..HEAD
```

## Updating a PR Mid-Stack

If you need to make changes to PR1 while PR2 and PR3 exist:

1. Make changes on PR1's branch, commit, push
2. Checkout PR2's branch
3. `git rebase PR1-branch` (not main!)
4. Resolve conflicts one at a time, reading each one
5. Force push PR2
6. Repeat for PR3, rebasing onto PR2
