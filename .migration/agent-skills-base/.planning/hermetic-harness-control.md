# Package harness-control as a pinned Nix application

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. Maintain this document in accordance with `.planning/PLANS.md`.

## Purpose / Big Picture

After this change, every active Linux workstation can run the `harness-control` MCP server from a dedicated Nix profile without installing `uv`, resolving Python dependencies at agent startup, or importing executable code from a mutable checkout. The operator can run `~/.local/bin/harness-control`; Claude and Codex use that same stable path; Nix supplies a pinned Python and MCP dependency through its content-addressed store and can roll the profile back independently of Home Manager.

The active deployment scope is the three x86_64 Linux workstations that have Nix. Legacy and offline hosts are outside this runtime rollout.

## Progress

- [x] (2026-10-15 01:00Z) Confirmed the active hosts have Nix and selected a dedicated profile instead of Home Manager, the general user profile, PEX, or `nix run` at every startup.
- [x] (2026-10-15 01:00Z) Created isolated `feat/hermetic-harness-control` worktrees in agent-skills and dotfiles and started the cross-repository tracker issue.
- [x] (2026-10-15 01:24Z) Added the canonical runtime, protocol smoke test, mutation-tested behavior suites, and a locked `nixos-25.11` Nix package.
- [x] (2026-10-15 01:24Z) Proved the packaged MCP handshake under hostile Python variables and PATH, with no mutable checkout reference or test-only scientific packages in its runtime closure.
- [x] (2026-10-15 01:50Z) Addressed council round 1 findings with isolated Python launch, packaged Git, isolated observer re-entry, commit-addressed installation, and session-id path validation; convergence review remains.
- [x] (2026-10-15 02:35Z) Addressed convergence round 2 findings by scrubbing every ambient `PYTHON*` variable plus `NIX_PYTHONPATH`, preserving source and installed observer entry through its exact file, and expanding malformed-state and package isolation tests; the next fix-delta round remains.
- [x] (2026-10-15 03:00Z) Convergence round 3 found no Critical issues; filtered malformed session-index entries, normalized their sort key, restored the hostile-PATH package proof, and made the private-tmux readiness poll tolerate transient reads.
- [x] (2026-10-15 03:12Z) Reached council-review fixpoint: OpenAI and Anthropic returned CLEAN on the final narrow delta; the Google seat remained empty because its provider quota was unavailable.
- [ ] Land the agent-skills PR, then pin that merged commit in dotfiles.
- [ ] Add the dedicated-profile installer and change Claude/Codex registration to the stable packaged command.
- [ ] Remove the superseded dotfiles runtime copy, update docs/tests, and prove install, upgrade, refusal, and rollback behavior.
- [ ] Reach council-review fixpoint, merge both PRs normally, and deploy the exact merged revisions to the three active workstations.

## Surprises & Discoveries

- Observation: two active hosts expose system Python 3.12, while the third exposes Python 3.14.
  Evidence: the 2026-10-15 fleet probe printed `/usr/bin/python3` versions 3.12.3, 3.12.3, and 3.14.4 respectively. An ambient interpreter cannot provide one hermetic dependency closure across the fleet.

- Observation: the server currently spans two mutable repositories.
  Evidence: dotfiles contains `mcp/claude-introspect/server.py` and its lifecycle modules, while `_skills_native.py` loads identity readers and `tmux-message.sh` from the installed agent-skills checkout. A package must pin both halves together.

- Observation: nixpkgs' MCP package enables its complete upstream test suite for every consumer, and its test-only dependency graph reaches SciPy through `inline-snapshot`, `isort`, `pylama`, `vulture`, `pint`, and `uncertainties`.
  Evidence: `nix why-depends --derivation` showed that exact chain after the first `nix flake check` began compiling SciPy. The MCP expression lists the first link under `nativeCheckInputs`; SciPy is not a runtime dependency.

- Observation: the inherited real-`/proc` parsing test assumed `/bin/sleep`, which does not exist in a pure Nix build sandbox.
  Evidence: the first stable-branch check failed at `subprocess.Popen` before the child started. The test now accepts a test-only sleep path, and the flake supplies coreutils' immutable executable.

- Observation: the lifecycle code also invokes Git, and its detached observer originally re-entered the library through a bare interpreter path.
  Evidence: council round 1 traced checkpoint verification to `subprocess.run(["git", ...])` and the observer to `sys.executable <module-file>`. A minimal client environment could therefore lose Git or Python dependency setup.

- Observation: putting pinned Bash and Python on `PATH` was insufficient for the captured transport because several scripts used `/usr/bin/env` shebangs.
  Evidence: the first private-tmux Nix check failed with `bad interpreter: No such file or directory`. The filtered transport tree is now copied to its own store output and `patchShebangs` binds every executable directly to the Nix interpreters.

- Observation: Python isolated mode alone does not exclude nixpkgs' `NIX_PYTHONPATH` hook.
  Evidence: a hostile `.pth` file named by `NIX_PYTHONPATH` executed under the packaged interpreter even with `python -I`. The wrapper and every harness-launched Python subprocess now remove all inherited `PYTHON*` variables and `NIX_PYTHONPATH`; the artifact test asserts that the hostile `.pth` marker is never written.

## Decision Log

- Decision: Use a normal Nix package, installed once, rather than PEX/scie or `nix bundle`.
  Rationale: Ted prefers Nix and does not want another embedded CPython copy. Nix keeps the interpreter as a shared store closure and deduplicates exact paths across packages.
  Date/Author: 2026-10-15, operator and Codex.

- Decision: Install into `~/.local/state/nix/profiles/harness-control` and expose `~/.local/bin/harness-control`.
  Rationale: A dedicated profile has atomic generations and rollback without coupling the service to a stale Home Manager checkout or unrelated user packages. The stable link gives MCP clients one registration path.
  Date/Author: 2026-10-15, operator and Codex.

- Decision: agent-skills owns the runtime and Nix package; dotfiles owns checkout resolution, profile installation, and client registration.
  Rationale: agent-skills already owns the canonical identity readers, shared configuration loader, and messaging transport used by the service. Dotfiles already owns machine installation and Claude/Codex configuration.
  Date/Author: 2026-10-15, Codex.

- Decision: Treat the host tmux client/server as an explicit platform capability rather than bundling a second tmux.
  Rationale: tmux clients must speak the running server's protocol. The package pins its Python code and command wrappers, while the configured tmux command deliberately addresses the host server.
  Date/Author: 2026-10-15, Codex.

- Decision: Pin the package to the cached `nixos-25.11` nixpkgs branch rather than a four-day-old unstable revision or a local MCP override.
  Rationale: the stable branch provides MCP 1.15, satisfying the declared API range, entirely from the binary cache. Its MCP dependency download was 4.7 MiB and added 26.4 MiB unpacked on the development host. The unstable revision required local builds whose test-only dependency graphs reached SciPy. Consuming the cached upstream MCP output avoids both those build inputs and the maintenance risk of overriding dependency checks.
  Date/Author: 2026-10-15, Codex.

- Decision: Launch the MCP server with the Nix Python in isolated mode, scrub every inherited `PYTHON*` variable and `NIX_PYTHONPATH`, re-enter the detached observer through the exact installed module file with `-E -s`, and include Git in the package's executable path.
  Rationale: `python -I` ignores standard ambient Python configuration and user site packages but nixpkgs' site customization still consumes `NIX_PYTHONPATH`. Explicit scrubbing closes that path. The exact observer file works from both a source checkout and the installed package while ignoring environment and user-site configuration; packaged Git makes checkpoint verification independent of the caller's PATH.
  Date/Author: 2026-10-15, Codex.

- Decision: Capture `skills/_shared` and only the five spawn-agent transport files reachable from `tmux-message.sh` in the runtime source tree.
  Rationale: these are the canonical helpers and transport the server imports. Filtering at the Nix source boundary prevents unrelated skill edits from rebuilding the service or entering its closure while preserving one immutable revision for all runtime code.
  Date/Author: 2026-10-15, Codex.

## Outcomes & Retrospective

The agent-skills package implementation is complete and its local gates pass. Its current total closure is about 292 MiB, dominated by shared Nix Python/MCP and Git paths; the package itself does not embed a private interpreter archive. Cold MCP initialization and tool listing completed in 0.367 seconds on the development host. No runtime or fleet installation has changed yet.

## Context and Orientation

The agent-skills repository currently contains shared operational code under `skills/`. Three canonical native readers live in `skills/_shared/native/`. The guarded tmux transport lives in `skills/spawn-agent/scripts/`. Dotfiles currently contains the MCP server under `mcp/claude-introspect/`; its `_skills_native.py` adapter imports the canonical readers and locates the transport through an `AGENT_SKILLS_ROOT` environment variable.

An MCP server is a long-running child process that exchanges JSON-RPC messages with Claude or Codex over standard input and output. The current registration starts `uv run --script <dotfiles>/mcp/claude-introspect/server.py`. On a host without `uv`, installers silently skip registration. On a cold host, `uv` can also need to construct a dependency environment before the server starts.

A Nix profile is a stable symlink to one immutable generation of packages in `/nix/store`. Installing into a dedicated profile changes that symlink atomically and preserves older generations for rollback. The package built here will contain a wrapper, a pinned Python environment with `mcp` below major version 2, the harness-control source, and immutable references to the exact agent-skills source tree used at build time.

## Plan of Work

First, copy the current harness-control runtime and its self-contained tests into `harness-control/` in agent-skills. Retain the existing adapter during migration, but ensure the packaged wrapper sets `AGENT_SKILLS_ROOT` to the immutable `skills/` tree captured by the same flake source. This keeps the current reviewed reader and transport boundaries while removing mutable-checkout lookup from production.

Add `flake.nix` and its generated `flake.lock`. The flake supports `x86_64-linux`, uses a pinned nixpkgs input, constructs a Python 3.12 environment containing `mcp` below major version 2, and exposes `packages.x86_64-linux.harness-control`, the default package, an app, and checks. The wrapper must run isolated from `PYTHONPATH` and user site packages, set `PYTHONDONTWRITEBYTECODE`, point `AGENT_SKILLS_ROOT` at the captured source, and execute the packaged `server.py`. It must leave the ordinary runtime inputs HOME, XDG configuration, session state, `/proc`, and the configured host tmux command available.

Move the runtime-focused tests from dotfiles into agent-skills and adapt only repository-relative paths. Add an artifact smoke test that uses the built executable and the MCP client to initialize the server and list tools under a private HOME. Prove the executable works with `uv` absent, a hostile `PYTHONPATH`, and the source checkout temporarily unavailable from the test's point of view. Run the existing identity, session-binding, Codex status, messaging, lifecycle, and mutation tests that cover the bundled boundary.

After the agent-skills PR is reviewed and merged, update dotfiles `.agent-skills.ref` to the merged commit. Add `scripts/install/install-harness-control`. It resolves the existing clean pinned checkout, verifies Nix exists, and installs `git+file://<checkout>?rev=<exact-commit>#harness-control` into the dedicated profile so only committed files enter the Nix source. It verifies the resulting executable and its MCP handshake, then atomically manages `~/.local/bin/harness-control`. A failed build, install, or smoke test must leave the prior profile generation and stable link usable.

Change `scripts/install/install-claude-introspect` and the Codex registration in `scripts/install/install-codex-config` to register the stable executable with no `uv run --script` arguments. Preserve the current ownership checks for custom registrations. Add private-HOME installer tests for first install, idempotence, upgrade, failure preservation, absent Nix, foreign stable links, stale old registration migration, exact registration output, and the repository's bare-repo plus linked-worktree layout. Remove the old dotfiles runtime only after all tests consume the packaged source.

## Concrete Steps

In the agent-skills feature worktree, add the runtime and flake, add all new paths to Git so flake source filtering includes them, then run:

    nix flake check
    nix build .#harness-control
    ./result/bin/harness-control

The bare executable blocks waiting for MCP input; the automated smoke test will instead initialize it and list tools, then exit cleanly.

Run the Python and shell tests named by the package README and this plan. Run mutation checks where the migrated tests provide them. Commit, push, create a draft PR early, run council review to fixpoint, and merge normally after exact-head local gates pass.

In the dotfiles feature worktree, update the pin only after the first PR merges. Implement and test the installer and registration changes, then repeat the draft PR, exact-head gates, council fixpoint, and normal merge workflow.

Finally, on each active host, fast-forward clean dotfiles and agent-skills master worktrees, run the narrow harness-control and Claude/Codex installers, restart no live harness automatically, and verify both clients report the stable executable registration. Existing sessions load the new registration only after their next normal restart.

## Validation and Acceptance

The agent-skills change is accepted when `nix flake check` and the runtime test suites pass, the built executable completes a real MCP initialize/list-tools exchange, and that exchange still passes with `uv` absent and a hostile `PYTHONPATH`. `nix-store --query --references` or `nix path-info -r` must show the pinned Python/MCP closure, and the wrapper must not reference the mutable checkout path.

The dotfiles change is accepted when isolated installer tests prove first install, no-op reinstall, failed-upgrade preservation, custom-registration refusal, legacy `uv run --script` migration, and stable-path registration. The live fleet is accepted when all three active workstations have the same agent-skills Git commit, the dedicated profile resolves to the expected package output, `~/.local/bin/harness-control` is executable, and Claude/Codex list the same stable command without `uv` arguments.

The final runtime should start without network access. Startup duration is measured from process creation through MCP initialization on a cold process and a second warm process; unexpected delay must be diagnosed before rollout rather than hidden by increasing client timeouts.

## Idempotence and Recovery

Nix profile installation is repeatable. The installer must build and smoke-test the candidate before publishing the stable link. If installation fails before profile advancement, no live state changes. If the new generation installs but fails its postcondition, run `nix profile rollback --profile ~/.local/state/nix/profiles/harness-control` and restore the prior stable link target. Dotfiles registration changes preserve unknown custom policy and refuse corrupted client configuration as they do today.

Worktree cleanup happens only after both PRs merge and fleet verification succeeds. Never delete the old runtime or an old profile generation merely to make a retry pass.

## Artifacts and Notes

The cross-repository tracker is `harness-codex-installer-followups` in dotfiles. Dotfiles selects the production agent-skills checkout through `.agent-skills.ref`.

## Interfaces and Dependencies

The agent-skills flake must expose `packages.x86_64-linux.harness-control`, `packages.x86_64-linux.default`, and `apps.x86_64-linux.harness-control`. The package installs `bin/harness-control`. Its only ambient executable dependency is the configured tmux client used to reach the already-running host tmux server; its Python interpreter, MCP library, Bash and core command dependencies come from Nix.

Dotfiles `scripts/install/install-harness-control` must accept no destructive default. It operates on the fixed dedicated profile, resolves agent-skills through the existing validated reference, and prints a distinct installed, unchanged, skipped, or failed result. Claude and Codex registration must have command `~/.local/bin/harness-control` expanded to an absolute path and an empty argument list.

Revision note, 2026-10-15: initial plan written after the implementation ruling and fleet/Nix preflight. Updated after the first build exposed uncached unstable dependency tests, after council round 1 exposed ambient Git/Python and local-path source boundaries, and after convergence round 2 demonstrated that `NIX_PYTHONPATH` bypasses Python's ordinary isolated-mode protections.
