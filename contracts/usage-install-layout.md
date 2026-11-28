# Contract: usage-install-layout v1

- **Owner:** Orgs, usage implementation. **Consumers (ack list):** dotfiles
  install layer.
- **Inputs / outputs:** the Orgs copy is the directory
  `~/.claude/skills/_shared/usage`. It contains the executable entry points
  `token_usage.py`, `tripwire.py` and `calibrate.py`, each with a `python3`
  interpreter line, and the modules `quota_service.py` and
  `quota_contract.py`. These five are the program files. The install layer
  keeps one symlink per host, the selector, at a fixed path under the home
  directory; it names either the Orgs copy or the dotfiles copy. A proxy
  resolves the selector once and runs the selected copy's entry point by
  its resolved real path with `exec`, passing the caller's arguments and
  environment unchanged.
- **Behavioral invariants (implementation):** each entry point finds its
  sibling modules from its own real location, so it works by absolute path,
  through a symlinked directory and from any working directory. It does not
  depend on the name it was invoked as, on dotfiles being present, on any
  environment variable to locate its modules, or on a package install.
- **Behavioral invariants (install layer):**
  - The selector's path depends on the home directory only. No environment
    variable, including `AGENT_SKILLS_ROOT`, changes which copy a proxy
    runs.
  - A proxy on a host with no selector
    runs the dotfiles copy beside it, with the same arguments, environment,
    output and exit status as running that entry point directly. Pulling
    the dotfiles checkout and running any installer other than the
    activation step never creates or changes the selector and never changes
    which copy a host runs.
  - Activation toward the Orgs copy first verifies, in that directory: the
    three entry points are executable; the five program files are
    byte-identical to the dotfiles copy while it exists; and
    `token_usage.py paths --json`, run there by path under the cron row's
    environment, exits 0 with schema `token-usage-paths/1` and the same
    `config`, `config_exists` and `state_dir` as the installed command. If
    any check fails it changes nothing and says which.
  - Activation holds an exclusive lock. Where the serve unit is installed
    it installs a per-host policy that the unit does not restart on status
    127 and confirms the unit manager has loaded it; where the unit is not
    installed it skips this. It never edits the unit file linked from the
    checkout. Before changing anything it records the prior selector,
    policy and unit state. It records whether the serve unit was active, stops it if so, replaces the
    selector by one atomic rename, restores the unit's recorded state and
    verifies it. On a failed start or check it stops the unit, confirms the
    new process has ended, renames the previous selector back, restores
    the policy and the unit to their recorded state, verifies selector,
    policy and unit together and exits nonzero. A rerun after an
    interruption at any point brings all three to one consistent state.
  - The policy follows the selector: present exactly when the selector
    names the Orgs copy and the unit is installed. The quota-service
    installer installs and verifies it before starting or restarting the
    unit, on enable and on refresh, on a host whose selector names the Orgs
    copy.
  - The quota-service installer takes the same exclusive lock as activation
    for the whole of any run that reads the selector, changes the policy or
    starts, stops or restarts the unit, so the two never interleave. While
    an interrupted activation's record is pending it does none of these and
    says that activation must be rerun first.
  - Activation toward the dotfiles copy performs no check of the Orgs copy,
    cannot be blocked by it, and removes the per-host service policy.
  - Installers obtain the tool's paths from `token-usage paths --json` and
    do not import the modules.
- **Failure semantics:** a proxy whose selector names a directory or entry
  point that is missing or not executable prints one line to stderr naming
  the path and the remedy and exits 127. It never runs the other copy. The
  serve unit does not restart on that status while the Orgs copy is
  selected.
- **Intentionally unspecified:** every other file in the Orgs copy; module
  structure; the selector's exact path and the activation step's command
  line and record format; how the skills view is built.
- **Versioning / compatibility policy:** renaming or removing a program
  file, moving the Orgs copy, or requiring more than Python 3.11 standard
  library is breaking and follows the ack rule in `usage-cli`.
- **Boundary tests:** in Orgs, each entry point run by absolute path,
  through a symlinked directory, from an unrelated working directory, with
  `AGENT_SKILLS_ROOT` set elsewhere. In dotfiles, against synthetic copies
  and a synthetic home: a proxy with no selector equals the direct run; a
  selector naming each copy; a dangling selector exits 127 and runs neither
  copy; `AGENT_SKILLS_ROOT` set elsewhere changes nothing; an installer
  rerun after activation leaves the selector and the selected copy
  unchanged, including on a host whose `~/.bin` is the checkout's `.bin`;
  activation refused on a missing entry point, a differing program file and
  a `paths` mismatch; activation and switch-back with the unit active and
  with it inactive, on a synthetic store that a state-changing command
  writes before and after; a failed unit start reverses the switch; an
  interruption before and after the rename is resolved by a rerun; two
  concurrent activations serialize; a process started before a switch
  loads its later modules from the copy it started in; activation on a
  host with the unit installs and verifies the no-restart policy and a
  switch back removes it; an interruption after the policy loads and
  before the rename is resolved by a rerun with no policy left on a host
  still on the dotfiles copy; a failure after the rename restores selector,
  policy and unit together; enabling the unit on an already activated host
  installs the policy before the first start, and a refresh restores a
  missing one before restarting; an installer run that would start the unit
  while an activation is in progress waits for it, and one that finds a
  pending activation record refuses; activation on a host without the unit
  succeeds;
  pulling the cutover change leaves the linked unit file unchanged.
- **Interpretation register:** the Interpretations Log of
  `docs/specs/usage-tooling-migration.md`.
