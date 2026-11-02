# tier-drift

The model tier a piece of agent work needs drifts downward as capabilities
improve: work that needed the frontier model a few months ago often fits a
mid or cheap tier today. Habits don't follow on their own. tier-drift reads
your own Claude Code, Codex, Antigravity and Gemini CLI session logs — on
this machine and any others you can ssh to — and tells you where your
dispatch has fallen behind the models.

## Prerequisites

- Nix (with flakes), or Python 3.12 and [uv](https://github.com/astral-sh/uv)
- For multi-machine collection: key-based ssh to each host. Remote hosts
  need only a `python3` (3.6 or newer) — nothing is installed on them.

## Getting started

```bash
nix develop --command bazel test //...
```

Status: the collector is built and tested; the insight engine is drafted and
golden-tested; the CLI and report are not started yet. See [docs/DESIGN.md](docs/DESIGN.md)
for the design and the roadmap.

## Project structure

| Path | What it holds |
|------|---------------|
| `src/tier_drift/` | the package |
| `catalog/` | the model catalog — edit this when a new model ships |
| `docs/DESIGN.md` | purpose, architecture, principles and roadmap |
| `page/` | the rendered report's HTML, CSS and JS |
| `tests/` | pytest suite |

## Contributing

See [AGENTS.md](AGENTS.md).

## License

tier-drift is free software, licensed under the
[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only).

**Other licenses are available for purchase.** If the AGPL does not suit how
you want to use tier-drift, for example in a proprietary product or a hosted
service whose source you do not want to publish, contact the copyright
holder about a commercial license.
