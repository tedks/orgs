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
    rejects any other, and what `_read_usage_posture` in
    `harness-control/server.py` accepts is the definition): an object with
    exactly the keys `provider` (`openai`, `anthropic` or `none`), `reason`
    (string), `gated`, `scores`, `used_percent`, `resets_at`, `stale` and
    `staleness`. The five maps each have exactly the keys `openai` and
    `anthropic`: `gated` and `stale` hold booleans; `scores` and
    `used_percent` hold a finite number or null; `resets_at` holds a string
    or a finite number. `staleness` has `stale` (bool), `newest_observed`
    (string), `age_seconds` (int) and optional `expired`, an object whose
    keys are among `openai`, `anthropic.seven_day` and
    `anthropic.five_hour` with non-negative integer ages. A provider's
    score and percentage are null exactly when its weekly meter is listed
    as expired.
  - `token-usage meters --check --json`: an object keyed by meter id. Each
    value is an object with `observed` (ISO-8601 string in UTC, written
    with `Z`; a consumer accepts `Z` or an offset),
    `used_percent` (number), `window_minutes`, `resets_at` (ISO-8601 string
    or epoch seconds) and `source` as the provider reported them, and
    `account_scope` and `account_epoch` (non-empty string, or null when the
    identity is unbound or masked). With `--check` and exit 0, `openai` and
    `anthropic.seven_day` are present with `used_percent` in 0 to 100,
    `window_minutes` equal to 10080 and valid `observed` and `resets_at`.
    The quota-reset monitor reads the windows it knows, ignores other keys,
    and additionally requires a non-null identity, an integer window,
    freshness and `resets_at` after `observed`; it ignores readings that
    fail (`valid_reading` in `tools/quota_reset/monitor.py`).
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
    it. Both are reported exactly as the other subcommands resolve them:
    `config` as given, `state_dir` with `${XDG_STATE_HOME}` substituted and
    user expansion. `install-token-tripwire` requires an absolute
    `state_dir`, as it does today; `install-quota-service` keeps its
    comparison note; neither places a new requirement on `config`. `paths` reads only
    the config file and creates nothing.
- **Behavioral invariants:** while both copies exist their program files
  are byte-identical and frozen, so a command given the same arguments,
  environment, config and store behaves identically on either. Reads with
  `--no-scan` do not scan. Output carries counts, identifiers, times and, for
  `paths`, filesystem paths; never message content. Python 3.11 or later,
  standard library only.
- **Failure semantics:** a consumer treats a nonzero exit, unparsable output
  or an unknown schema as "usage unavailable", never as zero usage or a
  fresh store. `paths` with a config file that exists but cannot be read or
  parsed exits 1 with the reason on stderr and prints nothing on stdout.
  Exit 127 from an installed name means the selected copy cannot be run:
  the selector names a missing directory or a missing or non-executable
  entry point. A missing `python3` gives the same status.
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
