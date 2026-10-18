# Sui usage corpus inventory

**State:** bounded inventory; nested manifest and metadata-only log coverage checks completed on 2026-10-18. This is corpus coverage evidence, not the usage analysis or a claim about Sui-session volume.

## Method and limits

Scope was restricted to the three named hosts, six project roots named in the lead brief, and the two explicit log roots (`~/.claude/projects` and `~/.codex/sessions`). SSH used `BatchMode=yes` and an 8-second connect timeout. All three hosts answered without interactive access. The checks were read-only; no Sui command was run except `sui --version` on framework0. Project inventory enumerated `Move.toml`, `package.json`, and `Cargo.toml` to depth four within each named root, pruning `.git`, `node_modules`, `target`, `.next`, and `dist`, then inspected only manifest lines matching Sui/Move/Walrus package declarations or Sui scripts. Log coverage counted filenames and file metadata only: Codex session dates came from `YYYY/MM/DD` paths; Claude session dates use file mtime and are only ceilings, since Claude filenames have no date path. No log bodies were read.

Method sketch (run from the assessment worktree). The Python bodies were inline on stdin and were not retained, so this is not an exact reproducible command transcript:

```sh
for host in framework0 tower0.local splinter1.local; do
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" 'python3 -' <<'PY'
  # manifest pass: os.walk only the six named roots; prune
  # .git,node_modules,target,.next,dist; do not descend below depth 4
  # log pass: os.walk matching Claude project slugs, count *.jsonl mtimes
  # between 2026-09-26 and 2026-10-18 inclusive
  # separate log pass: os.walk ~/.codex/sessions; accept rollout-*.jsonl
  # only when the YYYY/MM/DD path date is in that inclusive interval
PY
done
```

The ephemeral manifest matcher emitted only lines from `Move.toml`, `package.json`, or `Cargo.toml` containing Sui/Move/Walrus dependency declarations or Sui command scripts; reported manifest totals are files with at least one such matching line. Ephemeral log scripts emitted counts and ISO week buckets only, never filenames or file content. Exact inline script bodies were not saved, so these results are not independently reproducible from the command block alone.

The Claude directory set was filtered to project slugs containing `chaos`, `diy-hrt`, `predictionbook`, `pairmarket`, `sui-devstack`, or `mysten`; it was not a full-home or full-project scan. Counts below are **coverage ceilings**, not Sui-relevant session counts: no transcript body was parsed or copied. Claude mtime can shift after file copying/restoration and does not prove session activity date. Project/provider/model counts remain unknown. Do not use these totals as denominators for pain rates.

## Host and corpus coverage

Counts are JSONL files, with Claude project directory counts shown separately. “Unknown” means not derived in this bounded pass, rather than zero.

| Host | Claude matching dirs / JSONL files with mtime in window | Codex rollout files with path date in window | In-window Sui sessions by project/provider/model |
|---|---:|---:|---|
| framework0 | 419 / 1,368 | 797 | Unknown |
| tower0.local | 81 / 0 | 16 | Unknown |
| splinter1.local | 0 / 0 | 10 | Unknown |

Both log roots existed on all three hosts. Weekly metadata-only ceilings (ISO year-week; Claude mtime / Codex path date):

| Host | Claude files by week | Codex files by week |
|---|---|---|
| framework0 | 2026-W39 186; W40 392; W41 364; W42 426 | 2026-W40 2; W41 217; W42 578 |
| tower0.local | 0 in window | 2026-W40 14; W41 1; W42 1 |
| splinter1.local | 0 in window | 2026-W40 1; W42 9 |

Codex file counts are per dated rollout filename, often one session per file but not verified here. Claude transcript files are under project-slug directories; mtime is an imperfect date proxy. No provider/model/tier or Sui relevance was inferred from filename or mtime. The lead brief identifies Claude `assistant.message.content[]` tool-use blocks and Codex `custom_tool_call` / `exec_command` shapes; those event structures were not independently validated against corpus content in this inventory.

## Project and version evidence

Manifest discovery was bounded to depth four. Status is direct if a matching Sui/Move/Walrus declaration or `sui` CLI script appears in a discovered manifest, absent-in-bounded-search if none did. Presence of an independent reference checkout under `mysten` is recorded as indirect corpus/reference evidence, not as a deployed fleet product. “Absent” does not rule out generated manifests, excluded directories, or deeper files.

| Host | Project root | Membership in depth-four manifest search |
|---|---|---|
| framework0 | `chaos` | **Direct.** 34 matching manifests; TypeScript SDK (`@mysten/sui`, `@mysten/walrus`, `@mysten/seal`) and several Move packages. Explicit pins include `@mysten/sui` 1.45.2, Walrus 0.8.6, Seal 0.9.2; other package ranges vary. |
| framework0 | `diy-hrt` | **Absent-in-bounded-search.** Root present, no matching Sui/Move/Walrus manifest declaration found to depth four. |
| framework0 | `predictionbook` | **Direct.** 4 matching manifests; `contracts/predictionbook/Move.toml` pins Sui framework and Walrus/WAL dependencies to Git revisions; frontend pins `@mysten/sui` `^2.29.0`. |
| framework0 | `pairmarket` | **Direct.** 4 matching manifests; Move package docs identify Nix-pinned Sui CLI target `mainnet-v1.73.2`; web/core pin `@mysten/sui` 2.20.1 and core pins Seal/Walrus 1.2.3. |
| framework0 | `sui-devstack` | **Absent-in-bounded-search.** Root present, no matching package declaration or Sui script found in manifests to depth four. |
| framework0 | `mysten` | **Indirect/reference corpus.** 223 matching manifests in a mixed reference checkout, including Move examples and Sui source; not counted as one product project. |
| tower0.local | `chaos` | **Direct.** 36 matching manifests; same principal SDK families and version pins observed on framework0. |
| tower0.local | `diy-hrt` | **Unavailable.** Named root absent. |
| tower0.local | `predictionbook` | **Direct.** 2 matching manifests; Move package explicitly comments Sui 2024 edition; frontend pins `@mysten/sui` `^2.9.0`, Seal `^1.1.1`. |
| tower0.local | `pairmarket` | **Direct.** 4 matching manifests; same CLI target note and `@mysten/sui` 2.20.1 / Walrus and Seal 1.2.3 pins as framework0. |
| tower0.local | `sui-devstack` | **Absent-in-bounded-search.** Root present, no matching package declaration or Sui script found to depth four. |
| tower0.local | `mysten` | **Unavailable.** Named root absent. |
| splinter1.local | All six roots | **Unavailable.** None of the named roots present. |

framework0 reports `sui 1.64.0-d4a0c80be602` from `~/.local/bin/sui --version`. This is a host CLI version, not proof of the version agents used in a particular session. These manifests show meaningful per-project pin variance (Chaos 1.45.x, PredictionBook 2.x, Pairmarket 2.20.1); no session-level CLI/SDK assumption was checked.

## Sanitized taxonomy leads

These are project/topic hints from names and command-script shapes, not measured transcript findings. The usage miner should confirm incidence and avoid turning them into conclusions without session evidence.

| Candidate area | Sanitized observed shape | Evidence strength |
|---|---|---|
| Move build/test setup and CLI environment selection | `sui move build --path <contracts-dir> --build-env <environment>`; corresponding `sui move test` | Directly seen in pairmarket scripts; no error-loop evidence |
| SDK/API pin drift | host CLI `1.64.0` alongside app pin `@mysten/sui 1.45.2` | Two explicit versions, but not comparable by themselves and not evidence of an agent mismatch |
| Walrus, Seal, zkLogin, DeepBook and shared-object work | Matching lane/project slug themes exist in the Claude corpus directory names | Topic presence only; no counts or error classes safely attributed |

No wallet values, addresses, prompts, transcript lines, or raw errors were collected. Candidate error classes, turns spent, retries, RPC behavior, tool versions by session, and `ask-agent` topics are all **unmeasured** here.
