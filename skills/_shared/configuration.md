# Shared configuration

Operational defaults live in `${XDG_CONFIG_HOME:-$HOME/.config}/agent-skills/config.toml`.
The loader requires Python 3.11+ (`tomllib`) and reads only data. Missing default
configuration uses generic defaults; an unreadable, malformed, wrongly typed or
unknown value fails before operations. An explicitly selected missing file also
fails. No values are shell-evaluated.

```toml
projects_root = "~/Projects"

[operator]
name = "the operator"

[off_duty]
path = "~/Projects/agent-handoffs"
remote = ""  # Optional expected origin URL; never creates or changes a remote.

[doctrine]
roles_path = ""  # Handoff requires a real roles file or explicit --roles.

[tmux]
socket = ""  # Empty auto-detects; label uses -L, absolute path uses -S.

[fleet]
hosts = []

[harness]
codex_bin = "codex"

[github]
owner = ""  # Repository creation needs an explicitly supplied owner.
```

Absent `off_duty.path` defaults to `<projects_root>/agent-handoffs`. The retirement
repository must already exist on `master` with a verified private `origin`.
`off_duty.remote`, when nonempty, must equal every origin fetch/push URL exactly;
it supplements the existing privacy verification. There is no default remote,
GitHub owner, fleet, doctrine checkout, or tmux socket.

`AGENT_SKILLS_CONFIG` selects an alternate file. Each dotted key can be overridden
with its upper-case underscored environment name, for example
`AGENT_SKILLS_OPERATOR_NAME`, `AGENT_SKILLS_PROJECTS_ROOT`,
`AGENT_SKILLS_OFF_DUTY_PATH`, `AGENT_SKILLS_DOCTRINE_ROLES_PATH`,
`AGENT_SKILLS_TMUX_SOCKET`, `AGENT_SKILLS_HARNESS_CODEX_BIN`, and
`AGENT_SKILLS_GITHUB_OWNER`. `AGENT_SKILLS_FLEET_HOSTS` is a JSON array of strings.
The file is validated even when environment overrides are supplied. Paths expand
`~`; project, handoff and roles paths must be absolute. The Codex executable is
a command name or an absolute path, never a cwd-relative path. Bare tmux labels
such as `~label` remain literal labels. No `$VARIABLE` expansion
occurs. Empty strings are allowed only for remote, roles, tmux and GitHub owner.

Explicit command options take precedence over legacy `RETIRE_*` / `SPAWN_*`
variables, which take precedence over shared configuration. Without an explicit environment
socket override, a valid active `$TMUX` server takes precedence over the file
configuration; the configured socket is a fallback outside tmux. If neither is
available, the default server is used. A nonempty `$TMUX` naming an unavailable
socket fails closed; explicitly select a different socket to override it.
Pinned targets in an ongoing delivery or retirement continue to use their
recorded socket. Setting configuration never grants permission to create a
repository, publish a shard, or operate on a host.

Read or validate configuration from an installed tree:

```sh
python3 ~/.claude/skills/_shared/agent_skills_config.py validate
python3 ~/.claude/skills/_shared/agent_skills_config.py get github.owner
python3 ~/.claude/skills/_shared/agent_skills_config.py  # resolved JSON
```

Install the whole `skills/` tree, including `_shared/`, and retain sibling
relationships. `_shared` is a library, not an independently discoverable skill.
Shell tmux consumers share `config.sh` through `tmux-ctx.sh`. The Python tmux
transport and retirement script import the same loader directly. Hygiene
requires a complete per-host policy with an explicit absolute remote
`projects_root`, and its `--remote` source payload has no checkout dependency.
It does not read unused local configuration: a local user's home-expanded path
is not evidence of the remote user's project root. Operators may intentionally
copy `get projects_root` into a policy after confirming the target host path.
`/tmp` ownership remains explicit policy data (default `unknown`), never inferred
from a hostname.

Ask-agent uses the configured Codex executable in its Codex branch.
The transcript readers, screen parsers, trust helper and
scaffold comparison scripts have no setup-dependent defaults and do not load
configuration unnecessarily. Initialize-repo instructions consume `projects_root`
and `github.owner`; operator and fleet values are available to skill workflows,
not automatic authorization or a target allowlist.
