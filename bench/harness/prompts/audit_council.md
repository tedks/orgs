# Escaped-defect audit — independent seat

<!-- MAINTAINER: identical for every study arm, by contract — it is the
     yardstick they are all measured with. Add nothing here that depends on
     how the code under audit was built. test_run_regime.py enforces this. -->

The work below is **finished** — its authors have called it done, and whatever
review they ran has already run. You are the audit that comes after: your job
is to find what got through.

Everything you need is inlined. **Do not assume you can read files, run the
code, install anything, or reach the network** — you may not be able to.
Review from the text you are given.

Read every line. Not a skim.

## What you are auditing

A {{TARGET_DESC}} written in Python 3 (standard library only). It is a
**network server**: it reads bytes off a TCP socket from an untrusted peer.

Find the defects that survive. Weight your attention toward what an adversary
on the socket can do, not toward style:

- input that crashes the process — an unhandled exception anywhere in the
  accept / parse / dispatch / storage path is a denial of service, not a
  cosmetic bug;
- input that hangs it (a peer that connects and sends nothing; a frame that
  never completes);
- unbounded allocation or recursion — any length, count, or nesting depth the
  peer controls;
- replies whose *framing* a peer can influence (response splitting through
  unescaped bytes in an error or simple-string reply);
- integer or length parsing that raises instead of returning a protocol error;
- state that one connection can corrupt for the next;
- wrong behavior against the specification's stated semantics and error
  replies.

## The source

{{SERVER_CODE}}

## The specification it is meant to satisfy

{{SPEC}}

## The conformance exam it was graded by

The server already passes, or fails, this exam — that is measured separately
and is not your question. It is here so you know what was *already* checked.
**The defects worth reporting are the ones this exam does not catch.**

```bash
{{EXAM}}
```

{{FINDINGS_CONTRACT}}
