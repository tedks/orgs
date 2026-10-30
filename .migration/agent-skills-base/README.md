# Agent skills

Shared Claude and Codex skills, with their history extracted from dotfiles.
Dotfiles references this repository; it does not vendor it or use a submodule.

## Installation contract

The checkout contains `skills/<name>/SKILL.md` and the scripts and templates
owned by each skill. The expected local layout is a bare repository at
`~/Projects/agent-skills/.git` with its `master` worktree at
`~/Projects/agent-skills/master`.

Dotfiles records the remote URL, branch, and checkout in `.agent-skills.ref`.
Its Claude and Codex installers resolve that reference, clone a missing
checkout, and reject dirty or stale checkouts. Update a clean checkout with
`git pull --ff-only` before rerunning an installer when it is behind.

Claude's installed `~/.claude/skills` points to this checkout's `skills/`.
Codex uses individual `~/.codex/skills/<name>` links so its local `.system`
contents remain intact. These installed paths remain the stable interface
for skill scripts, allowed-tools declarations, and global instructions.
The app-managed `synced/` cache is ignored and preserved during migration.

Project repositories may use the stable installed paths or carry a reviewed,
commit-pinned vendor snapshot when they must remain self-contained. Vendored
copies record their source commit and retain this repository's license.

## Configuration

Machine-specific values live outside the repository in
`${XDG_CONFIG_HOME:-$HOME/.config}/agent-skills/config.toml`. Dotfiles seeds
that file from its own template. Existing valid machine-owned configuration
is preserved. The shared loader supports `AGENT_SKILLS_*` overrides for
tests and generic defaults; see its configuration documentation for keys.
Python 3.11 or later is required for TOML parsing. Config is data, never shell
code, and should not contain secrets.

## History

The current source snapshot is dotfiles commit
`53159f2b203c7e2e72ff523dc114b29bb90d202a`. `git subtree split -P .claude/skills` produced
`df7982e3750fc48c2eaf1ba11cad9fcfea4ee3d7`, retaining 270 commits.
Its tree `7efbbf9cdff6279cbfee350a32e99bc36d439922` exactly matched the source
subtree. A separate rename commit placed the original extraction under
`skills/`; the current branch merges the updated extraction so both source
histories remain reachable. The ignored sync cache was never part of that
history.

Current-tree cleanup does not remove former setup-specific values from
historical commits. The repository is initially private so its installation
and historical disclosure can be reviewed before a deliberate public release.

## harness-control Nix package

The `harness-control` MCP server is available as the default Nix package for
`x86_64-linux`. The package pins Python and the MCP library and captures the
canonical identity readers, configuration loader, and tmux transport from the
same source revision. It intentionally uses the host's configured tmux client
to communicate with the already-running tmux server.

Build and test it with:

```sh
nix flake check
nix build .#harness-control
```

Production installers should install the package into a dedicated Nix profile
and register its stable profile link with the MCP client. Starting the service
does not evaluate the flake or resolve Python dependencies.

`self_compact` cancels before slash-command dispatch when a new native root
input turn appears after its checkpoint. Cancellation records one notice
receipt, reaches terminal `cancelled`, and permits another request after the
observer releases its sender lease. `cancel_operation` also accepts a pending
warning or old `watching_other` record if the slash command was never
dispatched. A refused concurrent request names the operation ID, state, and
whether to cancel it or wait for its terminal receipt.

The intended policy distinguishes an operator adding work from a peer telling
the lane to compact. Current Claude and Codex transcript rows do not
authenticate whether a root input came from the operator or a tmux peer. The
safe observable rule therefore counts either as an intervening turn; exempting
message text would let an operator's identical input bypass cancellation.
Native metadata and tool-result rows remain excluded. A separate follow-up will
apply the CTO's configured control-prefix convention; an operator using the
same prefix will then also be exempt under that convention.
If a peer compaction boundary and a root input appear within one transcript
poll, the observed boundary wins and the request resumes from that compaction.

## License

Agent skills is free software licensed under the
[GNU Affero General Public License, version 3](LICENSE).

See [AGENTS.md](AGENTS.md) for contribution and verification instructions.
