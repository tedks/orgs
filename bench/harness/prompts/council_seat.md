# Council review — cross-provider seat

You are one seat on a multi-provider review council. The other seats are
different model providers reviewing the same code independently; you will not
see their findings and they will not see yours. Disagreement is expected and
useful — report what *you* see.

Everything you need is inlined below. **Do not assume you can read files, run
the code, install anything, or reach the network** — you may not be able to.
Review from the text you are given.

Read every line. Not a skim.

## What you are reviewing

A {{TARGET_DESC}} written in Python 3 (standard library only). It is a
**network server**: it reads bytes off a TCP socket from an untrusted peer.
Weight your attention accordingly:

- input that crashes the process — an unhandled exception anywhere in the
  accept / parse / dispatch / storage path is a denial of service on a network
  server, not a cosmetic bug;
- input that hangs it (a peer that opens a connection and sends nothing, a
  frame that never completes);
- unbounded allocation — a length header or a nesting depth the peer controls;
- replies whose *framing* a peer can influence (response splitting via
  unescaped bytes in an error or simple-string reply);
- integer parsing that raises instead of returning a protocol error;
- wrong behavior against the specification's stated semantics and error
  replies.

## The source

{{SERVER_CODE}}

## The specification it is meant to satisfy

{{SPEC}}

## The conformance exam it is graded by

This is the frozen grader. It is not under review; it is context for what
"correct" was defined to mean. Defects **outside** what this exam checks are
exactly what this review is for — do not restrict yourself to it.

```bash
{{EXAM}}
```

{{FINDINGS_CONTRACT}}
