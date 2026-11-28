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

Git mode reads the stored tree, headers, and message for every commit
reachable from TIP and excluded by BASE. Use `--repo` to select the
repository. `--changed` selects only changed names and file versions
in each commit, including comparisons against all parents of a merge.
This is a partial result. It requires BASE to be an ancestor of TIP, and
BASE must already be on the public remote. Use a full-tree scan to audit
the contents of every commit tree. Shallow history and active grafts
produce hard findings. An empty range or directory scan requires
`--allow-empty-scan`.

The guard checks relative names, including directory names, symlink
targets, and UTF-8 file content. It scans gzip member payloads both
individually and as a concatenated stream, and checks member names and
comments. The guard scans original text and forms reached by up to four
rounds of percent or backslash decoding. Symlink targets are read as link
text. Unreadable or
undecodable inputs produce hard findings, including opaque gzip extra data
and Git links whose contents are outside the audited tree.

The hard rules cover delimited UUIDs, compact UUIDs with version and
variant nibbles, request, message, and tool IDs, home paths, and tmux
pane targets. A compact digest that happens to match the UUID rule can
be added to the allow list after review. Home path detection covers
common Linux and macOS home roots, the root account, and named-user
tilde paths. A standalone percent-prefixed number is treated as a pane
target. Percentages and common format directives are ignored. The
optional allow list accepts exact synthetic IDs and full home path
tokens, one per line. Paths are case-sensitive and entries do not
grant access to descendants.

The guard treats base64-looking runs of at least 200 characters as
hard opaque findings. Reviewers still inspect base64 and other encodings
that the guard does not decode, as well as contextual details such as
measured figures without corresponding deny-list entries.

The deny list accepts one ASCII term per line after NFC normalization
and removal of zero-width characters. Matching applies the same text
normalization, ignores letter case, and checks overlapping matches,
whitespace variants and Claude's dash-encoded path spelling. Digits,
punctuation and transitions from lowercase to uppercase delimit terms.
Repeat `--deny-list` to add another private list. Both list types accept
blank lines and lines beginning with `#`. Each supplied deny list must
contain an entry unless deliberately waived with `--allow-empty-deny-list`.

Findings are JSON lines with a rule, surface, file, and position when
available. A decoded finding marks its column as belonging to the
decoded view. Gzip records include the member number where applicable.
The default masks matching or undecodable filenames and hashes sensitive
values with a key generated for that run alone. A deny-list finding
reports the source list number and physical entry line number instead.
`--unredacted` includes exact values and line context for private review.
Deny-list findings carry review severity. Keep the reviewer's verdict with
the exact tree or commit it covers. The final line gives the scope and
counts files, bytes inspected (expanded payload and text headers for gzip),
commits, messages, and findings.
Exit status is 0 for a clean scan, 1 for either kind of finding, and 2 for a
configuration error.

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
