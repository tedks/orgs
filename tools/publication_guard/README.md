# Publication audit tools

The guard requires Python 3.11 or later and the standard library. Git is
needed for commit audits. Run it against a stable staging directory before
publication. Keep the deny list and review records in a private directory.

The guard looks for accidental disclosure when transcripts, logs,
fixtures, paths, or names are copied into a staging tree or Git commit.
Use it alongside a review of where the staged material came from and
what will be published.

## What this guard does not defend against

The guard covers text produced by ordinary tools. A reviewer must assess
the origin of any material someone could have deliberately disguised.
In particular, the guard's patterns do not cover deliberately overlapping
IDs, zero-width characters inside IDs or home prefixes, surrogate-pair
escapes, or more than four rounds of percent or backslash decoding.
Deny matching removes zero-width characters and normalizes text to NFC.
It does not perform full Unicode case folding.

The input paths come from Linux and macOS. Windows home paths and
upper-case spellings of the supported prefixes are outside that coverage.
Deny phrases match within a physical line. Add each distinctive word
as a separate entry if a phrase can wrap. Git mode audits commits.
Review annotated tag objects separately before pushing tags. Report
redaction applies to scan output. The argument parser may include a
mistyped command-line argument in its terminal diagnostics.

```sh
python3 tools/publication_guard/guard.py --tree "$staging_tree" \
  --deny-list "$private_deny" --allow-list "$synthetic_allow"

python3 tools/publication_guard/guard.py --git-range 'BASE..TIP' \
  --deny-list "$private_deny" --allow-list "$synthetic_allow"
```

Git mode reads the stored tree, headers, and message for every commit
reachable from TIP and excluded by BASE. Use `--repo` to select the
repository. In either mode, any BASE used to exclude history must
already be on the public remote. Use `--git-range '..TIP'` in full-tree
mode to audit history without an exclusion. The summary records the
resolved commit IDs for both endpoints, with a null base for whole history.
`--changed` selects only changed names and file versions in each commit,
including comparisons against all parents of a merge. It is a partial
result and requires BASE to be an ancestor of TIP. Shallow history and
active grafts produce hard findings. An empty range, empty directory scan,
or empty commit tree in full-tree mode requires `--allow-empty-scan`.

The guard checks relative names, including directory names, symlink
targets, and UTF-8 file content. It scans gzip member payloads both
individually and as a concatenated stream, and checks member names and
comments. The guard scans original text and forms reached by up to four
rounds of percent or backslash decoding. Symlink targets are read as link
text. Unreadable or undecodable inputs produce hard findings, including
opaque gzip extra data and Git links whose contents are outside the
audited tree.

The hard rules cover delimited UUIDs, compact UUIDs with version and
variant nibbles, request, response, reasoning, message, and tool and
function call IDs, home paths, and tmux pane targets. A compact digest
that happens to match the UUID rule can
be added to the allow list after review. Home path detection covers
common Linux and macOS home roots, the root account, and named-user
tilde paths. A standalone percent-prefixed number is treated as a pane
target. Percentages and common format directives are ignored. The
optional allow list accepts exact synthetic IDs and full home path
tokens, one per line. Paths are case-sensitive and entries do not
grant access to descendants.

The guard treats diverse base64-looking runs of at least 200 characters
as hard opaque findings, including bodies wrapped across consecutive
base64-only lines. Reviewers inspect encoded inputs and contextual
details such as measured figures without corresponding deny-list entries.

The deny list accepts one ASCII term per line after NFC normalization
and removal of zero-width characters. Matching applies the same text
normalization, ignores letter case, and checks overlapping matches,
whitespace variants and Claude's dash-encoded path spelling. Digits,
punctuation and transitions from lowercase to uppercase delimit terms.
Repeat `--deny-list` to add another private list. Both list types accept
blank lines and lines beginning with `#`. Deny entries cannot contain
control characters. `--allow-empty-deny-list` permits an empty list or
omitting the option. An explicit list path must still be readable.

Findings are JSON lines with a rule, surface, file, and position when
available. A decoded finding marks its column as belonging to the
decoded view. Gzip records include the member number where applicable.
The default masks matching or undecodable filenames and hashes sensitive
values with a key generated for that run alone. A deny-list finding
reports the source list number and physical entry line number instead.
`--unredacted` includes exact values and line context for private review.
Deny-list findings carry review severity. Commit-header matches on the
repository owner's known public Git identity are expected review items.
Keep the reviewer's verdict with the exact tree or commit it covers.
The final line gives the scope and
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

To show each mutation result, add `--test_output=all`. The mutation
target requires the unmutated suite to pass before it credits any kills.
It then changes individual rules, boundaries, and refusal checks and
requires each targeted test to fail.
