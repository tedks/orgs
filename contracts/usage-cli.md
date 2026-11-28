# Contract: usage-cli v1

Effective when the import (M2) merges; until then the dotfiles copy is the
only implementation and this is its description.

- **Owner:** Orgs, usage implementation (`skills/_shared/usage/`).
  **Consumers (ack list):** Orgs `usage` skill, `harness-control`
  `get_usage`, quota-reset monitor; dotfiles installers, cron row, serve
  unit and `npm-ai-update`; the desktop frontends.
- **Inputs / outputs:** three commands, found on `PATH` or at
  `~/.bin/<name>`, each with a top-level `--config FILE` before the
  subcommand:
  - `token-usage`: `scan`, `sessions`, `totals`, `meters`, `incidents`,
    `posture`, `paths`, and the quota subcommands `snapshot`, `observe`,
    `serve`.
  - `token-tripwire`: `tick`, `replay`, `status`.
  - `token-calibrate`: `sample`, `report`.

  The normative definition of every subcommand's flags, text output, JSON
  shape and exit codes is `skills/_shared/usage/README.md` at the import
  commit. The quota subcommands and the `serve` socket protocol are defined
  by the frontend repository's `docs/specs/quota-service.md` and
  `contract.py` at the revision the import pull request records; the pinned
  digest covers the vendored `quota_contract.py` alone, and the copied tests
  and fixtures come from that same revision. The shapes consumers depend on
  today, with the consumer's own check as the normative test of each:
  - `token-usage posture --no-scan --json` (closed shape; `get_usage`
    rejects any other; its validator in `harness-control/server.py` is the
    test): an object with exactly the keys `provider` (`openai`, `anthropic`
    or `none`), `reason` (string), `gated`, `scores`, `used_percent`,
    `resets_at`, `stale` and `staleness`. The five maps each have exactly
    the keys `openai` and `anthropic`: `gated` and `stale` hold booleans;
    `scores` and `used_percent` hold a finite number or null, null exactly
    when that provider's reading has expired; `resets_at` holds a string or
    a finite number. `staleness` has `stale` (bool), `newest_observed`
    (string), `age_seconds` (int) and optional `expired`, an object mapping
    meter ids to non-negative integer ages.
  - `token-usage meters --check --json` (the monitor reads the windows it
    knows and ignores other keys; `valid_reading` in
    `tools/quota_reset/monitor.py` is the test): an object keyed by meter id
    whose values are objects with `window_minutes` (int, the window's
    length), `account_scope`, `account_epoch` and `source` (non-empty
    strings), `used_percent` (number, 0 to 100), `observed` (timestamp) and
    `resets_at` (timestamp, or epoch seconds).
  - `token-usage sessions|totals|meters --no-scan [--json]`, `token-usage
    scan`, `token-tripwire status [--json]`: passed through by the `usage`
    skill without interpretation.
  - `token-usage [--config FILE] paths --json`: prints
    `{"schema": "token-usage-paths/1", "config": PATH, "config_exists":
    BOOL, "state_dir": PATH}` and exits 0. `config` is the path the tool
    would read: `--config`, else `$TOKEN_USAGE_CONFIG`, else
    `${XDG_CONFIG_HOME:-~/.config}/token-usage/config.toml`. A config file
    that does not exist is not an error for any subcommand; `config_exists`
    is then false and defaults apply. `state_dir` is
    `${XDG_STATE_HOME:-~/.local/state}/token-usage` unless the config sets
    it. Both paths are reported exactly as the other subcommands resolve
    them, with user expansion and nothing else, so they are absolute
    whenever the values supplied are; an installer rejects a result that is
    not absolute. `paths` reads only the config file and creates nothing.
- **Behavioral invariants:** from M2 to M5 the two copies' program files are
  byte-identical, so every command behaves identically on either. Reads with
  `--no-scan` do not scan. Output carries counts, identifiers, times and, for
  `paths`, filesystem paths; never message content. Python 3.11 or later,
  standard library only.
- **Failure semantics:** a consumer treats a nonzero exit, unparsable output
  or an unknown schema as "usage unavailable", never as zero usage or a
  fresh store. `paths` with a config file that exists but cannot be read or
  parsed exits 1 with the reason on stderr and prints nothing on stdout.
  Exit 127 from an installed name means the host's selector names a copy
  that is not present.
- **Intentionally unspecified:** the store's layout and formats; module
  names, functions and import paths; log wording; and, for versions after
  the migration completes, text-mode column widths and JSON key order.
- **Versioning / compatibility policy:** removing or renaming a subcommand,
  flag or JSON key, changing a type, an exit code or a default path is
  breaking. So is adding a key to a closed shape. A breaking change is
  proposed against this contract, acknowledged by every consumer on the ack
  list, and the provider fixes all call sites. Adding a subcommand, an
  optional flag, or a key to a shape not marked closed is not breaking.
- **Boundary tests:** in Orgs, from M2: the digest-pin test for the five
  program files; a consumer-driven test that runs the
  real `posture --no-scan --json` and `meters --check --json` on the
  synthetic store and feeds them to `harness-control`'s posture validator
  and the quota-reset monitor's parser; `skills/usage/scripts/test-usage.sh`
  for the skill's calls; a `paths` test for each precedence and failure
  case; the vendored quota suites. In dotfiles: the installer tests and the
  proxy tests of the layout contract.
- **Interpretation register:** the Interpretations Log of
  `docs/specs/usage-tooling-migration.md`.
