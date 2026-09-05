# Skills — the protocol as a graph

The protocol is a set of composable skills. **`sprint/` is the root** (the
overall runbook: how the skills connect); the rest are the individual acts.
A named **variety** (an ablation) is `sprint` composing a *subset* — never a
flag. Each skill's `SKILL.md` owns its own procedure; `sprint` owns how they
fit together.

## The graph

```
[spec] ─▶ [decompose] ─▶ ( [implement]×N ∥ [standup] ∥ [crystal] )
       ─▶ [council] ─▶ [review] ─▶ [integrate] ─▶ [retro]
                             ▲
     [huddle] — the escalation floor, always available via doctrine
   · every step appends to [ledger]   · every role prompt is built by [pack]
```

Leaf skills are **unconditional about their own act**; all cross-skill wiring
("wrap your dev-loop in the guard", "deliver conflicts over the bus") lives in
`sprint` — so removing a skill from a variety removes its mechanism from every
prompt. Descriptive catalogs (ledger's event kinds, standup's triggers) are
references, not leaks.

## The skills

| skill | the act | wraps |
|---|---|---|
| `sprint` | **root runbook** — composes the graph; a variety trims it | `protocol/RUNBOOK.md` (absorbed) |
| `spec` | CEO+CTO author the contracts-first design doc | `docs/spec-template.md` |
| `decompose` | lead → tracer bullet, work packages, necessity challenge | templates, `pack` |
| `implement` | one worker builds one package in firewalled scope | — |
| `review` | the accountable lead's one-rung-up review to fixpoint (+ council CLEAN = ACCEPTED) | `pack` |
| `council` | cross-provider review to fixpoint (the robustness keystone) | `council-review`, `ask-agent` |
| `standup` | forced re-observation — redirect/halt a drifting agent | `tools/standup/` |
| `crystal` | speculative merge-check; report conflicts to the lead | `tools/crystal/` |
| `integrate` | merge ACCEPTED packages, keep the trunk green | — |
| `huddle` | escalate at the reversibility gate | — |
| `retro` | lessons, meta:product, amendments, cold-start audit | — |
| `pack` | **the firewall** — assemble a role's lean context | `protocol/templates/context-manifest.md` |
| `ledger` | the event log + status entries (the sprint's memory) | `protocol/STATES.md`, templates |

## Packaging

Each `SKILL.md` carries Claude Code skill frontmatter (`name: orgs-<skill>`).
They are the portable protocol artifacts; a harness binding
(`bindings/claude-code.md`) installs or symlinks them into that harness's
skill location. `tools/crystal/` and `tools/standup/` are the executables two
of the skills wrap.
