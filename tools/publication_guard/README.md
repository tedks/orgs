# Publication audit tools

The guard requires Python 3.11 or later and the standard library. Git is
needed for commit audits. Run it against a stable staging directory before
publication. Keep the deny list and review records in a private directory.

```sh
python3 tools/publication_guard/guard.py --tree "$staging_tree" \
  --deny-list "$private_deny" --allow-list "$synthetic_allow"

python3 tools/publication_guard/guard.py --git-range 'BASE..TIP' \
  --deny-list "$private_deny" --allow-list "$synthetic_allow"
```

Git mode reads the stored tree and message for every commit reachable from
TIP and excluded by BASE. Use `--repo` to select the repository and
`--changed` to audit only the changed file versions in each commit instead
of the complete trees. Changed-file mode checks merge changes against all
parents. Commit messages are checked in either mode. Review commit author
and committer fields separately.

The guard checks relative names, symlink targets, and UTF-8 file content.
It expands gzip members, checks member names and comments, and recognizes
JSON string escapes. Symlink targets are read as link text. Unreadable or
undecodable inputs produce hard findings, including opaque gzip extra data
and Git links whose contents are outside the audited tree.

The hard rules cover UUIDs, opaque request IDs, compact Codex IDs with the
`01` prefix, absolute home paths, and tmux pane targets. A standalone
percent-prefixed number is treated as a pane target. Percentages and common
format directives are ignored. The optional allow list accepts exact
synthetic IDs and home paths, one per line. Paths are case-sensitive and
entries do not grant access to descendants.

The deny list accepts one term per line. The guard checks whole words,
case-insensitively, including Claude's dash-encoded path spelling. Repeat
`--deny-list` to add another private list. Both list types accept blank
lines and lines beginning with `#`. Supply a nonempty deny list unless
deliberately opting out with `--allow-empty-deny-list`.

Findings are JSON lines with a rule, surface, file, and position when
available. The default hashes matches and masks matching filenames.
`--unredacted` includes exact values and line context for private review.
Deny-list findings carry review severity so a reviewer can distinguish
ordinary uses from private references. Keep the reviewer’s verdict with
the exact tree or commit it covers. The final line counts files, payload
bytes inspected (expanded for gzip), commits, messages, and findings.
Exit status is 0 for a clean scan, 1 for either kind of finding, and 2 for a
configuration error. The guard recognizes the patterns above. A publication
review also checks matters that require context, such as measured figures
without corresponding deny-list entries.

## Synthetic count fixtures

```sh
python3 tools/publication_guard/build_fixtures.py \
  --seed 304 --output "$fixture_directory" --allow-list "$synthetic_allow"
```

This writes one Claude fixture and one Codex fixture for a fixed synthetic
day. Use `--day YYYY-MM-DD` to select a different synthetic day. Each gzip
contains JSON lines with a home-relative `file` and transcript `rec`. The
sample includes two projects, Claude chunks for one request, and Codex
cumulative count re-emissions. The seed determines the IDs and counts.
Gzip headers omit timestamps and filenames. The allow list is overwritten
alongside the fixtures and covers only the generated identifiers and paths.

## Tests

```sh
nix develop --command bazel test \
  //tools/publication_guard:publication_guard_test \
  //tools/publication_guard:publication_guard_mutation_test
```

To show each mutation result, add `--test_output=all`. The mutation test
disables each rule in turn and requires its targeted test to fail.
