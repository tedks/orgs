---
name: orgs-pack
description: Assemble a role's context pack — the firewall. Give a role the doctrine block, its hat, and ONLY its owned scope plus the published contracts it may depend on. Used by decompose (to pack workers), review/council (to pack fresh reviewers), and implement (to read its pack). This is the only place lean-vs-full packing lives.
---

# orgs-pack — the firewall

Assembling what a role sees is the firewall. A role gets its own scope and the
*published contracts* it may depend on — never a neighbor's source. Knowledge
crosses boundaries through published surfaces, not by reading across them; that
is what makes defect-class propagation and Hyrum's-Law resistance possible.

Template: `protocol/templates/context-manifest.md`.

## What every pack contains

1. **The doctrine prompt block** from `doctrine/DOCTRINE.md` (§ Prompt block),
   verbatim, first. Every role prompt begins with it.
2. **The hat** — one line: "you are the L5 lead for entity X" / "you are the
   accountable lead reviewing PR N".
3. **The whole design doc.** It always rides whole.
4. **The role's scope + the contracts it consumes** — for an implementer, its
   owned paths and the published contracts of what it depends on; nothing else.
5. **Selected lessons** relevant to the act.

Record the pack as a manifest (what was included, at which sha) so a takeover
or audit can reconstruct what the role could see.

## Lean by default

Pack the minimum; the role reads more on demand. If a role had to find
something in the source that a contract should have published, it files a
docs-bug rather than depending on the found detail.

## Two packing modes

- **Journey roles** (continuation, takeover) inherit the prior agent's
  committed artifacts — branch, diff, PR thread, status entry, a transcript
  excerpt where the reasoning matters. The journey travels via artifacts.
- **Judgment roles** (review, necessity challenge, cold-start audit) get a
  **fresh, decontaminated** pack: the diff + spec + criteria + contracts,
  **never the reviewed agent's transcript or rationalizations.**

## Fresh vs. warm (a distinction that bites)

"Fresh context" for a review hat means fresh *of the work being reviewed*. It
does **not** forbid a review *seat* from carrying its **own** prior-round
context: warm-chaining a seat so it remembers what it already flagged is
intended — it is what lets the seat that found an issue re-verify its own fix.
**Fresh vs. the reviewed work; warm vs. its own prior rounds.**
