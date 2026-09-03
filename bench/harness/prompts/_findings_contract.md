## Required output format — read this twice

Whatever prose you write, your reply MUST end with exactly one fenced JSON
block, and **nothing may follow it**:

```json
[
  {"severity": "Critical", "claim": "one sentence naming the defect, the file, and why it is wrong"},
  {"severity": "Important", "claim": "..."}
]
```

Rules, all load-bearing (this block is parsed by a machine and counted as the
benchmark's primary metric — prose findings that are not in the block are
**not counted**, so anything you want on the record goes in here):

- `severity` is exactly one of `Critical`, `Important`, `Minor`.
  - **Critical** — crashes the server, hangs it, corrupts data, or is remotely
    exploitable (DoS included). A wire-reachable unhandled exception in a
    network server is Critical, not Important.
  - **Important** — wrong behavior against the spec or the exam, or a defect a
    user will hit on a normal path.
  - **Minor** — style, naming, redundancy, speculative hardening, taste.
- `claim` is a single sentence. Name the file and the construct.
- Report only defects you can point at in the code shown. Do not report
  "consider adding tests for X" as Critical or Important.
- If you found nothing, emit exactly `[]`. An empty array is a legitimate,
  respected outcome — do **not** invent findings to look diligent.
- One block. Do not emit an example block earlier in your reply; the parser
  takes the last block and an illustrative one would be mistaken for it.
