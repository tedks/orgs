# Contract: <name> v<version>

- **Owner:** <team/lead> · **Consumers (ack list):** <teams that must
  acknowledge changes>
- **Inputs / outputs:** <types, formats, ranges>
- **Behavioral invariants:** <what is promised>
- **Failure semantics:** <errors, retries, idempotency>
- **Intentionally unspecified:** <observable behavior consumers must NOT
  depend on — documentation of freedom, not a defense; the defenses are the
  boundary tests and cheap interpretation filings>
- **Versioning / compatibility policy:** <what counts as breaking; provider
  fixes all call sites on breaking change (LSC-style)>
- **Boundary tests:** <path to consumer-driven contract tests — each
  consumer asserts the behavior it relies on; these run against the
  provider>
- **Interpretation register:** <path/projection — open questions and rulings
  for this contract; clarifications promote into this document immediately>
