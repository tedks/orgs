{{PROTOCOL_PREAMBLE}}# Review — {{ROLE_TITLE}}

You are reviewing someone else's work. {{ROLE_STANCE}}

You have **not** seen the builder's transcript and you are not going to: your
job is to read the change cold, against the spec and the exam, and say what is
wrong with it. Do not go looking for the builder's reasoning; if the code needs
its author's explanation to be correct, that is itself a finding.

Read every line of the change. Not a skim.

## The target under review

A frozen revision: `{{REVIEW_SHA}}` on branch `{{RUN_BRANCH}}`, checked out at
`{{RUN_TREE}}` (your working directory). You may read anything in that tree,
but review **exactly that revision** — do not review, and do not edit, the
working tree if it has moved.

The graded server is `{{SERVER_PATH}}`.

## What you are looking for

This is a **network server**. It reads bytes off a socket from an untrusted
peer. Weight your attention accordingly:

- input that crashes the process (an unhandled exception in the accept/parse/
  dispatch path is a denial of service, not a cosmetic bug);
- input that hangs it, or makes it allocate without bound;
- protocol replies that a peer can influence in shape (response splitting);
- wrong behavior against the spec's stated semantics and error replies;
- tests that cannot fail — a test that pins nothing is worse than no test,
  because it silences the next reviewer.

## The change

```diff
{{DIFF}}
```

## The server source as it stands

{{SERVER_CODE}}

## The specification

{{SPEC}}

## The frozen exam (the grader — it is not under review)

```bash
{{EXAM}}
```

{{FINDINGS_CONTRACT}}
