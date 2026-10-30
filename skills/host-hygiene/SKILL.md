---
name: host-hygiene
description: Plan and apply reviewed, exact-entry disk reclamation on Linux SSH hosts while protecting live and paused lanes, Docker artifacts, Nix roots, and shared temporary files.
---

Follow orgs `doctrine/DOCTRINE.md`, “Host resources and hygiene”. The owning
lane inventories and reviews; a **fresh Utility agent** receives exactly that
reviewed list and applies it. Authorization for hygiene does not authorize
killing peers, deleting worktrees or peer caches, or changing shared tags.

Use `scripts/hygiene.sh plan HOST PLAN.json --policy POLICY.json`. Linux,
Python 3, SSH BatchMode, Docker and Nix tools are expected; nothing uses sudo.
The per-host policy must specify an absolute `projects_root` on the remote host.
Do not substitute the local user's home-expanded root: another host or SSH user
may keep projects elsewhere. The [shared configuration](../_shared/configuration.md)
CLI can supply a candidate only after you confirm that path on the target host.
The script runs over SSH without installing or creating remote helper files.
Use a private local state directory, e.g. `~/.local/state/hygiene/YYYYMMDD/HOST/`.
Plan files are created exclusively with mode 0600. The printed SHA256 binds the
whole reviewed list; neither edit the list nor substitute a new inventory after
review. Before deletion, inspect each full ID/name/path, size in bytes, ownership,
reason, eligibility, and every diagnostic. Missing sizes are never deletable.
Buildx versions may render human sizes: `size_display` preserves them,
`size_exact=false` marks the `bytes` value as an estimate rather than an exact
byte measurement. Unsupported size formats disable cache eligibility. `/tmp`
uses allocated inode blocks for nondirectories. Directories use GNU `du` in
batches of at most 256 exact paths, with NUL input/output and a shared 60s
measurement budget. Symlinks are not followed; path aliases, mounted roots or directories
containing mounts are retained without traversal. Directory sizes count every
hardlink to avoid cross-operand deduplication and are marked `size_exact=false`:
they can exceed an independent per-root deduplicated measurement and do not
predict freed bytes. Missing/unsupported output, stderr, nonzero exit, timeout,
or changed directory/mount identity discards every size in that affected batch;
all entries remain in the plan with unknown sizes and diagnostics. Failed batches
include output byte counts and at most 512-byte excerpts per stream; subprocess
capture itself is not a streaming memory bound. CLI snapshots
cannot exclude a concurrent mount or inode change atomically.
Measure `df -h` before and after separately and retain the plan and apply output.

A small owner-maintained policy looks like this (replace full IDs):

```json
{
  "projects_root": "/absolute/path/to/projects",
  "records": ["/absolute/path/to/current-owner-and-paused-lane-record.md"],
  "protected": ["peer-service"],
  "tmp_owner": "peer-lane",
  "builder": "default",
  "claims": [
    {"kind": "container", "id": "FULL_64_HEX_ID", "owner": "my-lane", "idle": true},
    {"kind": "image", "id": "sha256:FULL_64_HEX_ID", "owner": "my-lane", "idle": true,
     "released_tags": ["my-owned-repo:old-tag"]},
    {"kind": "volume", "id": "my-owned-compose-volume", "owner": "my-lane", "idle": true},
    {"kind": "cache", "id": "FULL_BUILDKIT_CACHE_ID", "owner": "my-lane", "idle": true}
  ]
}
```

`records` is the explicit, nonempty list of required local ownership/reference
documents. Include current ownership and pause records for every project on
the target host; confirm their paths with the owning lanes.
The owning lane confirms completeness; missing/unreadable records disable all
eligibility. Incomplete remote project-root/compose scans disable Docker eligibility
while independent Nix dead-graph/root checks remain usable.
Reference scans have a 60s budget, reject symlink/nonregular compose files,
and fail closed on symlink directories instead of silently missing external
worktree references. Review external references explicitly and declare complete
coverage in the policy; do not blindly follow arbitrary links or loops.
An incomplete scan retains Docker/cache entries. Compose files below
`projects_root`, including paused worktrees, conservatively protect references,
except intentionally excluded `.git`, `.bare`, `node_modules` and `.venv` trees.
The owner must provide relevant compose/lane references from excluded trees or
other unscanned coverage in `records`; exclusions do not establish absence of
references. Add other project roots' compose/lane information as local
records; the owning lane must confirm the declared root covers its host's worktrees.
`protected` adds exact names, full IDs, tags or paths from peer leases and records.
Paused is not abandoned: their images, volumes, unrooted store paths and caches
must be named in records or `protected`; do not grant their ownership to yourself.
`claims` are affirmative owner-confirmed idle assertions, not inferred from age.
Conflicting claims for one resource, including a peer's non-idle claim, retain it;
one lane's idle claim cannot borrow another lane's tag-release authorization.
For images, `released_tags` is an explicit release of every current tag by its
owner; shared tags may not be released by this lane.

Give the fresh Utility agent the reviewed plan, digest, policy and owning lane:

```sh
scripts/hygiene.sh apply HOST PLAN.json --policy POLICY.json \
  --owner my-lane --reviewed-sha256 REVIEWED_DIGEST > APPLY.json
```

Apply reloads current policy/records and inventories the same host/user, then
matches only saved eligible entries against fresh IDs, inspection fingerprints,
ages, references and ownership. It checks the exact Docker/backend identity again
before each deletion and rechecks the Nix dead graph before one exact-list daemon
delete batch (referrers and references can be deleted together).
Docker removes exited containers older than 24h without force/volume removal;
untagged unused images; tagged unused images older than 14d with explicit tag
release; and unreferenced compose volumes whose size and mount identity can be
read. No broad prune runs. Nix inventories roots and the dead graph with sizes;
the exact reviewed dead-path subset is passed as one batch to `nix-store --delete`, which
rechecks liveness through the daemon. No roots/profiles/generations are removed,
and newly eligible paths are never added to the reviewed list. Store mtimes are
normalized and do not prove installation age; generation-age cleanup is deferred
under follow-up `host-hygiene-profile-age`. Keep paused
unrooted closures protected explicitly; the daemon protects rooted closures.

Concrete retained classes:

- Build cache unused >72h is inventoried as NDJSON on the explicit `builder`.
  Only immutable, private, reclaimable, owner-confirmed records qualify. Apply
  pins the builder/backend identity and uses ANDed `id=FULL_ID`, `until=72h`,
  `private=true`, `inuse=false`, and `immutable=true` filters, then verifies the
  selected ID is absent. Mutable/shared/paused/unowned entries are retained;
  unsupported JSON or filter options fail closed without a broad-prune fallback.
  See [Docker Buildx prune](https://docs.docker.com/reference/cli/docker/buildx/prune/)
  and [disk usage](https://docs.docker.com/reference/cli/docker/buildx/du/).
- `/tmp` entries older than 2d are enumerated with exact paths and sizes, but no
  `/tmp` deletion is implemented: unprivileged access cannot prove complete
  process, mount and socket references across peers. Diagnostics name exact
  `sudo lsof +D PATH` and `sudo findmnt --target PATH` commands; these alone are
  not a deletion authorization or complete reference proof. `/tmp` ownership is
  unknown unless the current policy names `tmp_owner`; record explicit release
  receipts with the owning lane. Changing a plan's owner or release field cannot enable it;
  even a released lease still requires a separate implementation of complete
  reference checking before any `/tmp` apply can be supported. Tracked follow-up:
  `host-hygiene-tmp-references`.
- Inaccessible volume sizes need the exact diagnostic `sudo du` inspection;
  unreadable tools/data retain that class rather than skipping checks.

Live concurrent ownership changes cannot be atomically excluded by CLI snapshots.
Coordinate the exact resource lease with its owner before apply; a failed delete
stops the run without retrying or widening scope. Earlier success/failure receipts
are emitted even when apply exits nonzero; a failed Nix batch explicitly reports
that partial deletion is possible. If SSH or the outer timeout loses contact,
remote work may still be running: inspect it and reconcile the exact saved list
before retrying. Never force Docker removal. After three
failed attempts at a repair approach, report the evidence and escalate. Preserve
the plan and partial results, measure again, and review a new plan for any retry.

Run `scripts/test-host-hygiene.sh` for the disposable SSH/CLI fixture suite and
guard-removal mutations. The suite never connects to a real host.
