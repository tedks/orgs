---
name: lean-automation
description: Diagnose and prevent CI/deploy latency caused by automation inheriting a human's environment. Use when CI or a deploy feels slow, when auditing a repo's pipeline, when adding a dependency to a shared dev environment (flake devShell, base image, requirements file), or when writing a guard that is supposed to keep an environment lean.
---

# lean-automation

**Automation declares its environment; it never inherits one.** A default is a
decision nobody made. Where a machine reuses an environment built for a human,
two consumers with opposite needs are coupled — humans want everything
present, automation wants nothing present — and the machine silently
subsidises the human.

This is not Nix-specific. The same shape appears as a base image built for
developers, a `requirements.txt` that carries the linters, an `apt-get` line
inherited from a setup guide.

## Diagnose

**1. Setup-to-work ratio.** Read one run's step timings and ask what each
command actually does. A step named "Configure Docker for Artifact Registry"
taking 438s to run `gcloud auth configure-docker` (~2s of real work) is a 200:1
ratio: you are timing the environment, not the work.

```bash
gh run list --workflow <wf> --limit 10 --json databaseId,conclusion,createdAt,updatedAt
gh run view <id> --json jobs   # per-step startedAt/completedAt
```

**2. Cold-vs-warm asymmetry.** Suspect any cost amortised locally but recurring
remotely. Adding a dependency costs its author one local build, then zero
forever; it costs every cold runner the same minutes on every run. Ask: *who
pays this on a cold machine, and how often?* The person best placed to notice
is structurally the one who never feels it.

**3. Bimodality tells you whether a cache works.** A working cache produces a
warm/cold split in run durations. If every run takes the same time, the cache
does nothing — regardless of what its step reports.

## Before optimising, confirm both ingredients

The waste requires **(a)** automation entering the shared environment **and**
**(b)** that environment holding expensive-to-materialise paths. Auditing for
one alone produces false positives and inverted recommendations.

For Nix, check (b) by asking which paths are not substitutable:

```bash
nix develop <ref> --profile /tmp/p --command true
nix path-info -S /tmp/p            # closure bytes
nix path-info -r /tmp/p | wc -l    # path count
# 404 = built on every cold machine:
curl -s -o /dev/null -w '%{http_code}' https://cache.nixos.org/<hash>.narinfo
```

**"Uncached" is not one failure mode.** Rank before pricing:
compiled-from-source (an OCaml/LLVM toolchain: minutes) ≫ fixed-output fetch
(an SDK zip: download-bound) ≫ symlink-farm `buildEnv` (~0). Same 404, three
prices.

## Fix

Name one environment per consumer — `ci`, `deploy-frontend`, `deploy-backend`,
`default` — composed from shared tool sets so they cannot drift. Keep the rich
interactive shell exactly as it is; it is not the problem. Ambient tooling the
runner already provides (a cloud CLI from an auth action) should stay ambient:
`nix develop` appends to PATH rather than replacing it.

## Guards: measure, don't parse

Assert what the system **produced**, not the config meant to produce it.
Config assertions are proxies, and proxies drift.

A ~400-line guard that grepped YAML and Nix took eight review rounds, was found
to have 47 false passes, and stabilised only at 59 regression cases — a test
needing its own test suite is scaffolding. A ~15-line probe of the *realised*
package list did strictly more, because no indirection (an alias, a shadowed
`mkShell`, a tool set appending the interactive set) can hide a package from
its own shell's inputs:

```bash
nix develop .#ci --command bash -c \
  'echo "$nativeBuildInputs $buildInputs $propagatedBuildInputs $propagatedNativeBuildInputs"
   echo "$PATH" | tr ":" "\n" | grep "^/nix/store"' > packages.txt
grep -E -- '-(ditz|watchman|docker-compose)|-openjdk-11' packages.txt && exit 1
```

Sample every input list, not just `nativeBuildInputs` — a package in
`buildInputs` still reaches PATH, and a `shellHook` can prepend one directly.

**When a guard needs round after round of hardening, change its shape, not its
rounds.** And for any cache or optimisation, name the observable that differs
if it silently breaks. If you cannot name one, you have a comment, not a guard.

**Cheapest guard of all:** alert on run duration against the trailing median.
It needs no repo knowledge, works in any ecosystem, and catches the whole class
rather than one instance.

## Method, when you do write a guard

Mutation-test it: make the change it is supposed to catch and confirm it fails.
**Add** the bad thing rather than **replacing** a good one — otherwise a
neighbouring assertion fires and you have learned nothing about the guard under
test. Four mutations looked "caught" until isolated that way.

## Worked example (goals, 2026-08)

CI was written 2026-01-18 as `nix develop --command …` — correct then, all
cache hits. On 2026-08-20 one commit added the `ditz` issue tracker to the only
devShell, pulling an opam-built OCaml closure in which 129 of 415 store paths
were in no binary cache. Every CI run and deploy job then compiled an OCaml
compiler before doing any work: **153 jobs, ~17.9 machine-hours over 9 days**,
unnoticed.

Neither commit was wrong alone. The coupling was, and no single commit contains
it. Per-consumer shells took CI from 12.6 → 5.3 min and deploys from 12.4–14.9
→ 5.8–6.5 (frontend) and 9.2–10.7 → 2.3–2.9 (backend).

**The counter-example matters as much.** A sibling repo had ingredient (b) in
abundance — 1.93 GiB of uncached Android SDK — but not (a): its CI used gradle
and pip directly. Moving it onto the flake would have *added* ~2 GiB of
downloads to a job whose real work was 49 seconds. The rule is not "put CI in a
lean Nix shell"; it is "automation declares what it needs."

**Fix at the source when the cost is shared.** That OCaml closure is in no
binary cache at all, so it is paid by every consumer of that dependency — CI,
fresh clones, `home-manager switch`. Removing it from one repo's CI shell is a
workaround at the consumer; publishing a binary cache fixes it once for
everyone.
