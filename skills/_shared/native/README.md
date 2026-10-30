# Native harness identity readers

These three modules are the canonical native identity implementation shared by
retire-agent and the orgs harness-control MCP server. They were moved without
behavior changes from dotfiles `mcp/claude-introspect` at commit
`5fc9f92d5a4a23dbe32507256743cbaff3ad33c9`.

Retirement imports this sibling directory from its installed skills tree.
This repository holds compatibility shims under `harness-control/` that execute
these sources while preserving the shim module's `__file__`;
`__agent_skills_source__` records the canonical source.
The shims require installed `~/.claude/skills`, or an explicit absolute
`AGENT_SKILLS_ROOT` pointing to a staged `skills` directory. There is no bundled
implementation fallback or implicit network fetch.

The tests in `tests/` moved from the matching dotfiles `scripts/test-*.py` paths.
Run each with Python 3, then with `--mutation-check`. Dotfiles keeps MCP-specific
wiring suites. Run those with
`AGENT_SKILLS_ROOT` pointing to this checkout's `skills` directory.

Whole-tree links and per-entry links (including a symlinked `_shared`) are
supported. Helper-file containment is checked against the resolved native
directory. The isolated layout tests in `tests/test_native_helpers.py` at the
repository root also support `--mutation-check` for these import guards.

Dotfiles' embedded retire-agent remains a temporary pre-cutover compatibility
copy until its separately authorized fleet migration removes the embedded skill
tree. Its tests must set `AGENT_SKILLS_ROOT` to the exact staged checkout under
review; no gate should resolve native helpers from the operator's installed tree.
The MCP controller resolves its spawn-agent sender through the same external-root
contract, so embedded skill removal does not change transport selection.
