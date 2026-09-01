---
name: initialize-repo
description: Initialize a new project with bare git repo, ditz issue tracking, branch protection, agent instructions, and optional language-specific scaffolding. Supports multiple project types. Also provides --sync to report drift between an existing repo and the canonical scaffold templates.
argument-hint: <project-name> [--type bare|sui-dapp|python|rust|ocaml|node|go] [description] | --sync <repo-path>
allowed-tools: Bash(~/.claude/skills/initialize-repo/scripts/*), Read, Write, Edit, Glob, Grep, WebFetch
---

# initialize-repo

Set up a new project from scratch with the full development environment: bare git repo with worktrees, ditz issue tracking, GitHub repo with branch protection, agent instruction files, and optional language-specific scaffolding.

## Usage

```
/initialize-repo <project-name> [--type <type>] [description]
/initialize-repo --sync <repo-path>
```

## Arguments

- `<project-name>`: The project name (used for directory, GitHub repo, and package names)
- `--type <type>`: Project type (default: `bare`). See [Project Types](#project-types).
- `[description]`: Optional one-line description for GitHub repo and README
- `--sync <repo-path>`: Don't scaffold anything; report drift between an existing repo and the templates. See [Sync mode](#sync-mode---sync).

## Project Types

| Type | What it adds |
|------|-------------|
| `bare` | Just the infrastructure — git, ditz, agents, planning. No language opinion. |
| `sui-dapp` | Sui Move contracts, frontend skeleton, Nix flake with pinned Sui binary |
| `python` | pyproject.toml (uv), pytest, src layout, Nix flake with Python |
| `rust` | Cargo project, clippy/rustfmt config, Nix flake with Rust toolchain |
| `ocaml` | Dune project, opam config, Nix flake with OCaml toolchain |
| `node` | pnpm + TypeScript, Nix flake with Node.js |
| `go` | Go module, Nix flake with Go toolchain |

## Templates

`templates/` (inside this skill) is the **single canonical source** for the scaffold files that repos previously copy-pasted from each other. When scaffolding, copy from here — never from another repo. When one of these files needs a fix, fix the template first, then propagate.

| Template | Lands at (in new repos) | Kind |
|----------|-------------------------|------|
| `templates/create-worktree` | `~/Projects/<project-name>/create-worktree` (project root, next to the bare `.git/`) | verbatim |
| `templates/PLANS.md` | `.planning/PLANS.md` | verbatim |
| `templates/github-workflows/claude.yml` | `.github/workflows/claude.yml` | verbatim |
| `templates/github-workflows/claude-code-review.yml` | `.github/workflows/claude-code-review.yml` | verbatim |
| `templates/github-workflows/ci-nix.yml` | `.github/workflows/ci.yml` | skeleton — replace the TODO build/test steps |
| `templates/AGENTS.md` | `AGENTS.md` | skeleton — fill `{{PROJECT_NAME}}`, `{{PROJECT_DESCRIPTION}}` and the TODO sections |
| `templates/flake-snippets/playwright.nix` | spliced into `flake.nix` | snippet — copy the pieces into the dev shell |

**Verbatim** templates work as-is and should stay byte-identical to the template until a repo has a real reason to diverge. **Skeleton** templates are starting points that every repo customizes; only their shared structure is canonical. The Playwright **snippet** is for repos that run browser tests under Nix.

## Sync mode (--sync)

`scripts/sync-check.sh` reports drift between a repo's copies of these files and the templates:

```bash
~/.claude/skills/initialize-repo/scripts/sync-check.sh ~/Projects/<project>/master
```

For each verbatim template it checks the known candidate locations (`.planning/PLANS.md` and root `PLANS.md`; `../create-worktree` for the project-root layout) and prints one line per file found: `identical`, `drifted` (with changed-line counts), or `missing`. Skeleton templates are reported presence-only, never diffed. The Playwright snippet is detected by grepping `flake.nix` for `playwright-driver`.

The script is **read-only** — it never modifies the target repo. Divergence after scaffolding is allowed; the report exists to make drift *visible* so it can be reviewed deliberately, not to enforce conformance. It always exits 0 (it's a report, not a gate) except on usage errors or a broken skill install (missing template files).

When "landing the plane" in a repo that was scaffolded by this skill, it's worth occasionally running sync-check and mentioning any drift in the handoff notes — drift that nobody knows about is how these files forked in the first place.

## What It Creates

### Base (all types)

```
~/Projects/<project-name>/
├── .git/                          # Bare git repo
├── create-worktree                # Worktree helper (from templates/)
└── master/                        # Primary worktree
    ├── .claude/skills/            # Agent skills (copied from dotfiles)
    ├── .github/workflows/         # claude.yml, claude-code-review.yml (from templates/)
    ├── .gitignore                 # Standard ignores
    ├── .planning/
    │   └── PLANS.md               # ExecPlan format guide (from templates/)
    ├── AGENTS.md                  # Agent instructions (from templates/, source of truth)
    ├── CLAUDE.md -> AGENTS.md     # Symlink for Claude Code
    └── README.md                  # Project README
```

Issues are not in this tree: ditz keeps them as YAML on the orphan
`ditz-metadata` branch, which is never checked out over the working tree,
so no per-worktree wiring is needed.

### sui-dapp additions

```
    ├── .envrc                     # Nix flake integration for direnv
    ├── contracts/<project-name>/  # Sui Move package
    │   ├── Move.toml
    │   ├── sources/
    │   └── tests/
    ├── contracts/docs/
    ├── flake.nix                  # Nix dev environment with Sui
    ├── flake.lock
    ├── frontend/
    │   ├── src/
    │   ├── static/
    │   └── docs/
    └── zklogin-backend/           # Optional zkLogin service
```

### python additions

```
    ├── .envrc
    ├── .python-version
    ├── flake.nix                  # Nix dev environment with Python + uv
    ├── flake.lock
    ├── pyproject.toml             # uv-managed project
    ├── src/<project-name>/
    │   └── __init__.py
    └── tests/
        └── test_placeholder.py
```

### rust additions

```
    ├── .envrc
    ├── flake.nix                  # Nix dev environment with Rust
    ├── flake.lock
    ├── Cargo.toml
    ├── rust-toolchain.toml
    └── src/
        └── lib.rs
```

### ocaml additions

```
    ├── .envrc
    ├── .ocamlformat              # OCamlformat config
    ├── flake.nix                  # Nix dev environment with OCaml
    ├── flake.lock
    ├── dune-project               # Dune build system config
    ├── <project-name>.opam        # Generated by dune
    ├── bin/
    │   ├── dune
    │   └── main.ml
    ├── lib/
    │   ├── dune
    │   └── <project-name>.ml
    └── test/
        ├── dune
        └── test_<project-name>.ml
```

### node additions

```
    ├── .envrc
    ├── flake.nix                  # Nix dev environment with Node.js
    ├── flake.lock
    ├── package.json               # pnpm-managed project
    ├── tsconfig.json              # TypeScript config
    └── src/
        └── index.ts
```

### go additions

```
    ├── .envrc
    ├── flake.nix                  # Nix dev environment with Go
    ├── flake.lock
    ├── go.mod                     # Go module
    ├── main.go
    └── main_test.go
```

## Instructions

When this skill is invoked, follow the steps in order: Part 1 (base), then Part 2 (type-specific, skip for `bare`), then Part 3 (finalization).

---

## Part 1: Base Setup (all types)

### Step B1: Create bare repo and master worktree

```bash
cd ~/Projects
mkdir <project-name>
cd <project-name>
git init --bare .git
git worktree add -b master master
cd master
```

The `git worktree add -b master master` command creates an orphan branch since there are no existing refs.

### Step B2: Create base directory structure

```bash
cd ~/Projects/<project-name>/master
mkdir -p .planning .claude/skills
```

### Step B3: Write .gitignore

Standard ignores for Nix, Node, Python, Rust, IDE, OS, and environment files:

```
# Nix
result
result-*
.direnv/

# Node
node_modules/
dist/
.next/
.nuxt/

# Python
__pycache__/
*.pyc
*.egg-info/
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/

# Rust
target/

# OCaml
_build/
*.install

# Go
/vendor/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Environment
.env
.env.local
.env.*.local
```

### Step B4: Copy PLANS.md from templates

```bash
cp ~/.claude/skills/initialize-repo/templates/PLANS.md \
   ~/Projects/<project-name>/master/.planning/PLANS.md
```

(The template originally came from the OpenAI cookbook's ExecPlan article; the copy in `templates/` is canonical now.)

### Step B5: Copy skills from dotfiles

Copy the skill directories from `~/Projects/dotfiles/.claude/skills/` into the repo's `.claude/skills/`:
- `stacked-prs/`
- `ask-agent/`
- `spawn-agent/`
- `initialize-repo/` (this skill)

Preserve executable permissions on scripts.

### Step B6: Copy scaffold files from templates

All from `~/.claude/skills/initialize-repo/templates/` (see [Templates](#templates)):

```bash
cd ~/Projects/<project-name>/master
mkdir -p .github/workflows
T=~/.claude/skills/initialize-repo/templates
cp "$T/github-workflows/claude.yml" "$T/github-workflows/claude-code-review.yml" .github/workflows/
cp "$T/create-worktree" ~/Projects/<project-name>/create-worktree
```

`create-worktree` lives at the project root (next to the bare `.git/`), untracked or tracked per project taste; it derives the remote, worktree prefix, and base branch from its surroundings, so it needs no editing.

**For types with a Nix flake**, also seed CI:

```bash
cp "$T/github-workflows/ci-nix.yml" .github/workflows/ci.yml
```

Then replace the TODO build/test steps below the end-of-preamble marker with the type-specific commands (the same ones listed in the type's AGENTS.md sections).

---

## Part 2: Type-Specific Setup

Run the section matching the selected `--type`. **Skip this part entirely for `bare`.**

---

### Type: sui-dapp

#### Step S1: Create directory structure

```bash
cd ~/Projects/<project-name>/master
mkdir -p contracts/docs frontend/src frontend/static frontend/docs
```

#### Step S2: Scaffold the Move contract

```bash
cd ~/Projects/<project-name>/master/contracts
nix develop --command sui move new <project-name>
```

This generates `Move.toml`, `sources/<project-name>.move`, and `tests/<project-name>_tests.move` automatically. Do not write these by hand.

#### Step S3: Create placeholder files

Write empty `.gitkeep` files in:
- `contracts/docs/.gitkeep`
- `frontend/src/.gitkeep`
- `frontend/static/.gitkeep`
- `frontend/docs/.gitkeep`

#### Step S4: Write flake.nix

Write a Nix flake that provides a dev shell with the Sui CLI (pinned binary release), Node.js, pnpm, TypeScript, Rust toolchain, and general utilities. The flake should:

- Use `nixpkgs` (nixos-unstable) and `flake-utils` as inputs
- Fetch the Sui binary from GitHub releases using `pkgs.fetchurl`
- Support `x86_64-linux` and `aarch64-linux` with platform-specific hashes
- Use `autoPatchelfHook` for binary compatibility on NixOS/non-FHS systems
- Include a shell hook that prints tool versions on entry

To get the correct Sui version and hashes:
1. Check the latest Sui release: `gh api repos/MystenLabs/sui/releases/latest --jq '.tag_name'`
2. Download the tarball for each platform and compute the SRI hash: `nix hash to-sri --type sha256 $(nix-prefetch-url --unpack <url>)`

#### Step S5: Write .envrc

Content: `use flake`

#### sui-dapp AGENTS.md sections

Include these in the AGENTS.md written during Part 3:
- Contract build/test: `nix develop --command sui move build`, `nix develop --command sui move test` (from contracts dir)
- Frontend: `pnpm install`, `pnpm dev`, `pnpm build`, `pnpm test`
- Directory layout showing contracts/, frontend/, zklogin-backend/

---

### Type: python

#### Step P1: Create directory structure

```bash
cd ~/Projects/<project-name>/master
mkdir -p src/<project-name> tests
```

#### Step P2: Write pyproject.toml

```toml
[project]
name = "<project-name>"
version = "0.1.0"
description = "<description>"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
]

[tool.ruff]
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

#### Step P3: Write initial source files

- `src/<project-name>/__init__.py`: empty file
- `tests/test_placeholder.py`:
  ```python
  def test_placeholder():
      pass
  ```

#### Step P4: Write .python-version

Content: `3.12`

#### Step P5: Write flake.nix

Write a Nix flake providing a dev shell with Python 3.12, uv, and ruff:

- Use `nixpkgs` (nixos-unstable) and `flake-utils` as inputs
- Support `x86_64-linux` and `aarch64-linux`
- Include a shell hook that prints Python and uv versions

#### Step P6: Write .envrc

Content: `use flake`

#### python AGENTS.md sections

Include these in the AGENTS.md written during Part 3:
- Package management: `uv sync`, `uv add <pkg>`
- Testing: `uv run pytest`
- Linting: `uv run ruff check .`, `uv run ruff format .`
- Src layout: `src/<project-name>/`

---

### Type: rust

#### Step R1: Initialize Cargo project

```bash
cd ~/Projects/<project-name>/master
nix develop --command cargo init --lib --name <project-name>
```

#### Step R2: Write rust-toolchain.toml

```toml
[toolchain]
channel = "stable"
components = ["rustfmt", "clippy"]
```

#### Step R3: Write flake.nix

Write a Nix flake providing a dev shell with Rust (stable), cargo, clippy, rustfmt, and rust-analyzer:

- Use `nixpkgs` (nixos-unstable) and `flake-utils` as inputs
- Use the nixpkgs Rust toolchain
- Support `x86_64-linux` and `aarch64-linux`
- Include a shell hook that prints rustc and cargo versions

#### Step R4: Write .envrc

Content: `use flake`

#### rust AGENTS.md sections

Include these in the AGENTS.md written during Part 3:
- Build: `cargo build`
- Test: `cargo test`
- Lint: `cargo clippy -- -D warnings`
- Format: `cargo fmt`

---

### Type: ocaml

#### Step O1: Create directory structure

```bash
cd ~/Projects/<project-name>/master
mkdir -p bin lib test
```

#### Step O2: Write dune-project

```
(lang dune 3.0)
(name <project-name>)
(generate_opam_files true)

(package
 (name <project-name>)
 (synopsis "<description>")
 (depends
  (ocaml (>= 5.1))
  (dune (>= 3.0))
  (alcotest (and :with-test (>= 1.7)))))
```

#### Step O3: Write dune build files

- `lib/dune`:
  ```
  (library
   (name <project-name>)
   (public_name <project-name>))
  ```

- `lib/<project-name>.ml`:
  ```ocaml
  let greeting () = "Hello from <project-name>"
  ```

- `bin/dune`:
  ```
  (executable
   (name main)
   (public_name <project-name>)
   (libraries <project-name>))
  ```

- `bin/main.ml`:
  ```ocaml
  let () = print_endline (<Project_name>.greeting ())
  ```

- `test/dune`:
  ```
  (test
   (name test_<project-name>)
   (libraries <project-name> alcotest))
  ```

- `test/test_<project-name>.ml`:
  ```ocaml
  let test_greeting () =
    Alcotest.(check string) "greeting" "Hello from <project-name>"
      (<Project_name>.greeting ())

  let () =
    Alcotest.run "<project-name>"
      [ ("basic", [ Alcotest.test_case "greeting" `Quick test_greeting ]) ]
  ```

Note: `<Project_name>` uses OCaml module naming (capitalize first letter, underscores preserved).

#### Step O4: Write .ocamlformat

```
profile = default
```

#### Step O5: Write flake.nix

Write a Nix flake providing a dev shell with OCaml 5.1+, dune, opam, ocaml-lsp-server, ocamlformat, and utop:

- Use `nixpkgs` (nixos-unstable) and `flake-utils` as inputs
- Use `pkgs.ocaml-ng.ocamlPackages_5_1` (or latest 5.x available)
- Include `alcotest` for tests
- Support `x86_64-linux` and `aarch64-linux`
- Include a shell hook that prints OCaml and dune versions

#### Step O6: Write .envrc

Content: `use flake`

#### ocaml AGENTS.md sections

Include these in the AGENTS.md written during Part 3:
- Build: `dune build`
- Test: `dune test`
- Run: `dune exec <project-name>`
- Format: `dune fmt`
- Clean: `dune clean`
- REPL: `dune utop lib`

---

### Type: node

#### Step N1: Create directory structure

```bash
cd ~/Projects/<project-name>/master
mkdir -p src
```

#### Step N2: Write package.json

```json
{
  "name": "<project-name>",
  "version": "0.1.0",
  "description": "<description>",
  "type": "module",
  "main": "dist/index.js",
  "scripts": {
    "build": "tsc",
    "dev": "tsc --watch",
    "test": "node --test dist/**/*.test.js",
    "lint": "tsc --noEmit"
  },
  "devDependencies": {
    "typescript": "^5.5"
  }
}
```

#### Step N3: Write tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node16",
    "moduleResolution": "Node16",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true
  },
  "include": ["src"]
}
```

#### Step N4: Write initial source file

- `src/index.ts`:
  ```typescript
  export function hello(): string {
    return "Hello from <project-name>";
  }
  ```

#### Step N5: Write flake.nix

Write a Nix flake providing a dev shell with Node.js (LTS) and pnpm:

- Use `nixpkgs` (nixos-unstable) and `flake-utils` as inputs
- Support `x86_64-linux` and `aarch64-linux`
- Include a shell hook that prints Node and pnpm versions

#### Step N6: Write .envrc

Content: `use flake`

#### Step N7: Install dependencies

```bash
cd ~/Projects/<project-name>/master
nix develop --command pnpm install
```

This generates `pnpm-lock.yaml`.

#### node AGENTS.md sections

Include these in the AGENTS.md written during Part 3:
- Install: `pnpm install`
- Build: `pnpm build`
- Dev: `pnpm dev`
- Test: `pnpm test`
- Lint: `pnpm lint`

---

### Type: go

#### Step G1: Initialize Go module

```bash
cd ~/Projects/<project-name>/master
nix develop --command go mod init github.com/tedks/<project-name>
```

#### Step G2: Write main.go

```go
package main

import "fmt"

func Greeting() string {
	return "Hello from <project-name>"
}

func main() {
	fmt.Println(Greeting())
}
```

#### Step G3: Write main_test.go

```go
package main

import "testing"

func TestGreeting(t *testing.T) {
	got := Greeting()
	want := "Hello from <project-name>"
	if got != want {
		t.Errorf("Greeting() = %q, want %q", got, want)
	}
}
```

#### Step G4: Write flake.nix

Write a Nix flake providing a dev shell with Go, gopls, and golangci-lint:

- Use `nixpkgs` (nixos-unstable) and `flake-utils` as inputs
- Support `x86_64-linux` and `aarch64-linux`
- Include a shell hook that prints Go version

#### Step G5: Write .envrc

Content: `use flake`

#### go AGENTS.md sections

Include these in the AGENTS.md written during Part 3:
- Build: `go build ./...`
- Test: `go test ./...`
- Lint: `golangci-lint run`
- Run: `go run .`

---

## Part 3: Finalization (all types)

### Step F1: Write AGENTS.md

Start from `templates/AGENTS.md`. Replace the placeholders (`{{PROJECT_NAME}}`, `{{PROJECT_DESCRIPTION}}`) and fill in the TODO sections:
- Project structure (directory layout — adapt to the selected type)
- Environment setup (Nix + direnv if the type includes a flake, or just note "no special environment" for `bare`)
- **Type-specific build and test commands** (see the "AGENTS.md sections" in the type above)
- Repo specifics (domain constraints, licensing, deploy targets — whatever is genuinely unique)

**Do not add sections restating global workflow rules** (landing the plane, branch/PR discipline, granular commits, stacked PRs, worktree layout). Those live in `~/.claude/CLAUDE.md` and the skeleton already points at them; restating them is how per-repo copies drift.

### Step F2: Create CLAUDE.md symlink

```bash
cd ~/Projects/<project-name>/master
ln -s AGENTS.md CLAUDE.md
```

### Step F3: Write README.md

A user-facing README with:
- Project title and description
- Prerequisites (Nix if applicable, or just git for `bare`)
- Getting started (type-specific: build/test/run commands)
- Project structure overview
- Link to AGENTS.md for contributing

### Step F4: Generate flake.lock (types with a flake only)

```bash
cd ~/Projects/<project-name>/master
nix develop --command echo "flake loaded"
```

This generates `flake.lock` and validates the flake works. **Skip this step for `bare`.**

### Step F5: Initial commit

```bash
cd ~/Projects/<project-name>/master
git add -A
git commit -m "Initial project scaffold: <project-name>

<type-specific summary of what was set up>"
```

### Step F6: Create GitHub repo and push

```bash
gh repo create tedks/<project-name> --private --description "<description>"
cd ~/Projects/<project-name>/master
git remote add origin git@github.com:tedks/<project-name>.git
git push -u origin master
```

Note: `gh repo create --source` does not work from a worktree. Create the repo without `--source`, then add the remote manually.

### Step F7: Initialize ditz

`ditz` is installed via Nix — `nix run github:tedks/ditz -- <cmd>`, or
install it once with `nix profile install github:tedks/ditz#ditz`.

Run `ditz init` from inside the worktree. It creates the orphan
`ditz-metadata` branch that holds the issues; nothing lands in the
working tree, so there is no redirect to create and no per-worktree
setup for later worktrees.

```bash
cd ~/Projects/<project-name>/master
ditz init --no-onboarding
```

`--no-onboarding` suppresses the onboarding block ditz would otherwise
append to `AGENTS.md`; the AGENTS.md written in Step F1 already carries a
curated "Issue tracking (ditz)" section, and letting ditz append its own
would duplicate it. Drop the flag if you would rather have ditz's text
and delete the template's section instead — but do not keep both.

Then push the branch so the issues exist on the remote:

```bash
ditz sync
```

No merge driver is needed: issues are one YAML file each, so concurrent
edits to different issues do not collide, and git's default merge handles
the branch.

### Step F8: Set up branch protection

Create a GitHub ruleset requiring PRs for the master branch:

```bash
cd ~/Projects/<project-name>/master
gh api repos/tedks/<project-name>/rulesets -X POST --input - <<'RULES'
{
  "name": "protect-master",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/master"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    }
  ]
}
RULES
```

### Step F9: Verify

Run the following checks:
- `cd ~/Projects/<project-name>/master && git status` — clean working tree
- `git worktree list` — shows bare root and master worktree
- `ditz list` — ditz works (returns an empty list on a fresh repo)

**Type-specific checks (skip for `bare`):**
- `nix develop --command echo "ok"` — Nix shell loads
- `sui-dapp`: `nix develop --command sui --version`, `nix develop --command sui move build` (from contracts dir)
- `python`: `nix develop --command python --version`, `nix develop --command uv run pytest`
- `rust`: `nix develop --command cargo --version`, `nix develop --command cargo test`
- `ocaml`: `nix develop --command ocaml --version`, `nix develop --command dune build`, `nix develop --command dune test`
- `node`: `nix develop --command node --version`, `nix develop --command pnpm build`, `nix develop --command pnpm test`
- `go`: `nix develop --command go version`, `nix develop --command go test ./...`

Report the results to the user.

## Notes

- The Sui binary version and hashes will need updating as new releases come out. Check `gh api repos/MystenLabs/sui/releases/latest` for the current version.
- The skill assumes the user's GitHub username is `tedks`. Adjust the `gh repo create` and remote URL if needed.
- Skills are copied into the repo (not symlinked) so the repo is self-contained. Check `~/Projects/dotfiles/.claude/skills/` for upstream updates periodically.
- To add a new project type: add a new section under Part 2, define its AGENTS.md sections, and add verification checks to Step F9.
- To fix a bug in a scaffold file: fix it in `templates/` first, then use `scripts/sync-check.sh` on the repos that carry copies to see where the fix needs to propagate.
