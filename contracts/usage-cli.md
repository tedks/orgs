# Contract: usage-cli v1

- **Owner:** Orgs (usage implementation, `skills/_shared/usage/`), from the
  import milestone on. Until cutover the installed copy is dotfiles'.
  **Consumers (ack list):** Orgs `usage` skill, `harness-control`
  `get_usage`, quota-reset monitor; dotfiles installers and
  `npm-ai-update`; the desktop frontends.
- **Inputs / outputs:** three commands, found on `PATH` or at
  `~/.bin/<name>`: `token-usage` (`scan`, `sessions`, `totals`, `meters`,
  `incidents`, `posture`, and with the quota service `snapshot`, `observe`,
  `serve`; after M2b `paths`), `token-tripwire` (`tick`, `replay`, `status`)
  and `token-calibrate` (`sample`, `report`). Each takes `--config`. Flags, text output, `--json` shapes and exit
  codes are those of the imported commit; the quota subcommands follow the
  external quota contract. Configuration: `$TOKEN_USAGE_CONFIG`, else
  `${XDG_CONFIG_HOME:-~/.config}/token-usage/config.toml`. State:
  `${XDG_STATE_HOME:-~/.local/state}/token-usage/` unless the config says
  otherwise. `token-usage paths --json` prints
  `{"schema": "token-usage-paths/1", "config": PATH|null, "state_dir": PATH}`
  and reads nothing but the config.
- **Behavioral invariants:** the move changes no byte of any command's
  output for the same inputs and store. Reads with `--no-scan` do not scan
  and do not take the store lock where the imported commit says they do not.
  Output carries counts and identifiers only, never message content. The
  commands need Python 3.11 or later and only the standard library.
- **Failure semantics:** as imported. A consumer treats any nonzero exit,
  unparsable output or unknown schema as "usage unavailable", never as zero
  usage or a fresh store. Exit 127 from an installed entry point means the
  implementation is not installed on this host.
- **Intentionally unspecified:** the store's file layout and formats; the
  Python module names, functions and import paths; log wording; text-mode
  column widths; the order of keys in JSON objects.
- **Versioning / compatibility policy:** removing or renaming a subcommand,
  flag or JSON key, changing a type, an exit code or a default path is
  breaking. A breaking change is proposed against this contract, acknowledged
  by every consumer on the ack list, and the provider fixes all call sites.
  Adding a subcommand, an optional flag or a JSON key is not breaking.
- **Boundary tests:** `skills/usage/scripts/test-usage.sh` (the skill's
  calls); `harness-control` posture-shape tests; `tools/quota_reset` monitor
  tests; in dotfiles, the installer tests and the installed-proxies test; the
  quota suites vendored with the service. At import, a golden-output test
  runs each read-only subcommand against the synthetic fixtures and compares
  with outputs recorded from the pre-move code on the same fixtures.
- **Interpretation register:** the Interpretations Log of
  `docs/specs/usage-tooling-migration.md`.
