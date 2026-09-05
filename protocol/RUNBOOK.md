# Runbook

The runbook is now the **skill graph**, not an inline procedure list. It moved
to `skills/sprint/SKILL.md` (the root skill that describes how the skills
connect) and the individual skills (each owns its own "how"). This file is a
map from the old sections to where each one lives.

**Read `skills/sprint/SKILL.md` first** — it is the overall runbook. Then each
skill below for the procedure.

| old §  | now |
|---|---|
| §1 Spec authoring | `skills/spec` |
| §2 Sizing (hats not headcount) | `skills/sprint` (the "size" step) + `protocol/templates/roster.md` |
| §3 Decomposition (player-coach) | `skills/decompose` (calls `skills/pack`) |
| §4 Execution (worker loop) | `skills/implement` |
| §5 Standup | `skills/standup` (wraps `tools/standup/`) |
| §5b Huddle | `skills/huddle` |
| §6 Review ladder | `skills/review` (freeze + one-rung-up) + `skills/council` (cross-provider) |
| §7 Speculative merge check | `skills/crystal` (wraps `tools/crystal/`) |
| §8 Integration & closure | `skills/integrate` + `skills/retro` |
| context packing (the firewall) | `skills/pack` |
| event log + status | `skills/ledger` |

Still here in `protocol/`: `STATES.md` (transition tables the skills cite) and
`templates/` (the artifact templates the skills instantiate). A named variety
(an ablation) is `skills/sprint` with a skill removed — see that file.
