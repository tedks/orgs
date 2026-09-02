# Status entry: <work package id>

Path convention: `status/<work-package-id>.md`, one per claimed package,
owned and updated by the worker (at minimum: on claim, on every push, on
block/unblock, at every budget quarter). Mutable — unlike the ledger, this
file is overwritten in place; history lives in git.

- **State:** <mirrors the work package state>
- **Current task:** <one line>
- **Last commit:** <sha · one-line subject>
- **Budget burned:** <tokens and/or wall-clock vs. budget>
- **Blocked on:** none | <dependency / filed escalation / open huddle ref>
- **Deviations logged:** <ledger seq ids, or none>
- **Updated:** <ISO timestamp>
