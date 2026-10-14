# Vendored shared skills

Orgs carries exactly four shared skills (`ask-agent`, `initialize-repo`,
`spawn-agent`, `stacked-prs`) and the three `_shared` files they require
(`config.sh`, `agent_skills_config.py`, `configuration.md`) under
`vendor/agent-skills/skills/`. The files are copied verbatim from committed
Git objects, including executable modes. Other `_shared` subtrees are excluded. Working-tree changes and untracked
files in the source checkout are never copied.

`vendor/agent-skills.lock.json` records the canonical repository URL, exact
commit, SHA-256 digest and Git mode of every included file. The source
component's AGPLv3 license is copied as `vendor/agent-skills/LICENSE` and
included in the manifest. This component notice does not change licensing
for unrelated orgs content; the root license is unchanged.

## Local discovery and use

`.claude/skills/<name>` points relatively into the vendor tree; `_shared`
also has a local link so sibling references resolve. `.agents/skills` aliases
`.claude/skills` for Codex discovery; future entries in that directory are
therefore shared by both harnesses. These are committed Git symlinks, so a
checkout must support symlinks (`core.symlinks=true`). Both
[Claude Code](https://code.claude.com/docs/en/skills#choose-where-skills-load)
and [Codex](https://learn.chatgpt.com/docs/build-skills) document support for
symlinked skill folders.

No global skill installation or source checkout is needed to use this
snapshot. Read relative references next to the resolved `SKILL.md`. Run
scripts from the local tree; for example, from the orgs root:

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 vendor/agent-skills/skills/_shared/agent_skills_config.py validate
vendor/agent-skills/skills/spawn-agent/scripts/tmux-message.sh --help
```

The snapshot retains upstream text verbatim. Translate global skill paths
in its examples to `vendor/agent-skills/skills/` in this checkout. Use the
vendored `spawn-agent/scripts/tmux-message.sh` for examples naming the global
`tmux-message` alias. The upstream `allowed-tools` patterns refer to global
installed locations; they do not preapprove vendored commands. Normal
harness approval policy still applies. Claude's personal skills can take
precedence over same-name project skills, so `AGENTS.md` explicitly selects
this repository's local files for these four skills.

The source/configuration/runtime dependencies of the selected command still
apply (for example Python 3.11+, Bash, tmux, and harness executables). Machine
configuration may come from the operator's config file or the shared
loader's defaults; configuration is not vendored. Skill source is never
fetched during normal use. Commands that query agents or GitHub naturally
still use those services.

## Verify offline

```bash
python3 tools/vendor-skills/vendor_skills.py verify
python3 tools/vendor-skills/test_vendor_skills.py
```

Verification checks every file digest and executable bit, missing and extra
files/directories (including ignored or untracked additions), and exact
relative discovery links. It requires neither GitHub access nor the source
repository. It also rejects symlinks inside the vendor snapshot. Python
bytecode caches count as extra files, so use `PYTHONDONTWRITEBYTECODE=1` when
running its Python helpers.

The integration tests build disposable local Git repositories and a fresh
clone with an empty home. They check link/path discovery, a local executable,
deterministic refresh, source worktree isolation, repinning, drift refusal,
containment, missing license/commit, and removal refusal. They do not launch
agents or require a network connection.

## Refresh explicitly

Obtain and review the desired source commit separately, confirming that it
is reachable from the canonical repository named in the lock. The tool
checks committed content, not remote identity. An explicit pin may move
forward or backward; review the commit change in either direction. Then supply its full
40-character SHA and an explicit local checkout (no branch names or implicit
HEAD):

```bash
python3 tools/vendor-skills/vendor_skills.py sync \
  --checkout /path/to/agent-skills/checkout \
  --commit FULL_40_CHARACTER_COMMIT_SHA
python3 tools/vendor-skills/vendor_skills.py verify
python3 tools/vendor-skills/test_vendor_skills.py
git diff --stat
git diff --check
```

The sync command reads local Git objects only, disables lazy fetching, and
never fetches, pulls, executes source files, or deletes paths. It refuses an
already modified snapshot, unexpected discovery links, unsupported source
file types, or a source commit missing the required skills/license. A new
pin can add files and update content/modes. Only one maintainer should run a
refresh at a time; do not run helpers concurrently with it. Interrupted
writes fail verification and must be inspected before recovery.

An upstream removal stops the refresh before any writes and lists the
removed files. Rebuilding that snapshot requires a separate, exact-entry
cleanup reviewed against live worktrees and lane records and performed by
a fresh Utility agent under the repository deletion protocol. Rebuild from
the explicit commit after that reviewed cleanup; do not bypass drift checks
or recursively delete a glob. Keep the review, tests and source SHA with the
PR, and commit the snapshot, manifest and discovery links together.
