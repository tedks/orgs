# Target: RESP (Redis-compatible subset)

The first bench target. Design spec (goals, non-goals, firewalled entities,
contracts, milestones, and the frozen conformance grading):
[`docs/specs/2026-09-02-resp-tracer.md`](../../../docs/specs/2026-09-02-resp-tracer.md).

The built server lands **here** (`targets/resp/`) as the pilot sprint's
product — it is not part of the bench scaffold. The server must accept
`--port <port>` (or read `$PORT`) so `conformance/resp_conformance.sh` can
drive it through a real `redis-cli`.

Entities (each a work-package scope): `resp-codec` (bytes ↔ frames),
`command-engine` (store + semantics), `server` (socket loop). Contracts C1
(codec) and C2 (engine) live in the sprint's `contracts/` before fan-out.
