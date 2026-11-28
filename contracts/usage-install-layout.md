# Contract: usage-install-layout v1

- **Owner:** Orgs (usage implementation). **Consumers (ack list):** dotfiles
  install layer (proxies, installers, adapters list).
- **Inputs / outputs:** under the skills root (`$AGENT_SKILLS_ROOT`, default
  `~/.claude/skills`) the directory `_shared/usage/` contains the executable
  files `token_usage.py`, `tripwire.py` and `calibrate.py`, each with a
  `python3` interpreter line. A proxy runs one of them with `exec`, passing
  the caller's arguments and environment unchanged.
- **Behavioral invariants:** each entry point finds its sibling modules from
  its own real location, so it works when run by absolute path, through a
  symlinked skills root, or from any working directory. It does not depend on
  the name it was invoked as, on dotfiles being present, or on a package
  install. An installer that needs the tool's resolved paths runs
  `token-usage paths --json`; it does not import the modules.
- **Failure semantics:** a proxy whose skills root is not absolute, or whose
  target is missing or not executable, prints one line to stderr naming the
  path and the remedy, and exits 127. It never runs a different
  implementation. An installer run against a skills root without the three
  entry points refuses to link the proxies and reports the missing paths.
- **Intentionally unspecified:** every other file in `_shared/usage/`; the
  modules' internal structure; how the skills root is built.
- **Versioning / compatibility policy:** renaming or removing one of the
  three entry-point files, or requiring anything beyond Python 3.11 standard
  library, is breaking and follows the ack rule in `usage-cli`.
- **Boundary tests:** in Orgs, a test that runs each entry point by absolute
  path through a symlinked directory from an unrelated working directory; in
  dotfiles, the installed-proxies test against a synthetic skills root,
  covering the present, missing and non-executable cases.
- **Interpretation register:** the Interpretations Log of
  `docs/specs/usage-tooling-migration.md`.
