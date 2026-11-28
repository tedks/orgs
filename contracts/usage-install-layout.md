# Contract: usage-install-layout v1

- **Owner:** Orgs, usage implementation. **Consumers (ack list):** dotfiles
  install layer.
- **Inputs / outputs:** the implementation directory is
  `${TOKEN_USAGE_IMPL:-$HOME/.claude/skills/_shared/usage}`. It contains the
  executable files `token_usage.py`, `tripwire.py` and `calibrate.py`, each
  with a `python3` interpreter line, and the modules they import. A proxy
  runs one of the three with `exec`, passing the caller's arguments and
  environment unchanged. The directory is not derived from
  `AGENT_SKILLS_ROOT`.
- **Behavioral invariants (implementation):** each entry point finds its
  sibling modules from its own real location, so it works by absolute path,
  through a symlinked directory and from any working directory. It does not
  depend on the name it was invoked as, on dotfiles being present, or on a
  package install.
- **Behavioral invariants (install layer):**
  - Pulling the dotfiles checkout changes nothing a host runs. Only the
    activation step repoints `~/.bin/token-usage`, `~/.bin/token-tripwire`
    and `~/.bin/token-calibrate`.
  - Before repointing to the Orgs copy, activation verifies in the
    implementation directory: the three entry points are executable; the
    five program files are byte-identical to the dotfiles copy while that
    copy exists; and running `token_usage.py paths --json` there, by path,
    exits 0 with schema `token-usage-paths/1`. If any check fails it changes
    nothing and reports which.
  - Activation stops the serve unit when it is enabled, switches the names,
    starts the unit again and reports each step. It records which names it
    switched, so a rerun in either direction completes or reverses a partial
    switch.
  - Installers obtain the tool's paths from `token-usage paths --json` and
    do not import the modules.
- **Failure semantics:** a proxy whose implementation directory is not an
  absolute path, or whose target is missing or not executable, prints one
  line to stderr naming the path and the remedy and exits 127. It never runs
  another copy. The serve unit does not restart on that status.
- **Intentionally unspecified:** every other file in the implementation
  directory; module structure; where in dotfiles the proxies live and how
  the activation step is invoked; how the skills view is built.
- **Versioning / compatibility policy:** renaming or removing an entry-point
  file, changing the implementation directory's default, or requiring more
  than Python 3.11 standard library is breaking and follows the ack rule in
  `usage-cli`.
- **Boundary tests:** in Orgs, the absolute-path, symlinked-directory,
  unrelated-working-directory run of each entry point. In dotfiles, against
  a synthetic implementation directory: proxy present, missing,
  non-executable and relative-path cases; activation refused on a missing
  entry point, a differing program file and a missing `paths`; activation
  and switch-back with the unit enabled; an interrupted switch completed by
  a rerun; `npm-ai-update` with a proxy that exits 127; a run with
  `AGENT_SKILLS_ROOT` set to another directory still using the
  implementation directory.
- **Interpretation register:** the Interpretations Log of
  `docs/specs/usage-tooling-migration.md`.
