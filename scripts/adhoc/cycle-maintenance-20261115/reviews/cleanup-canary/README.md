# Independent cleanup canary review: PR #1236

PASS at 2026-11-15T09:45:28Z. All 21,070 preserved entries across eight
preservation roots match the recorded inventory, including file hashes, modes
and symlink targets. The environment and all three original review helpers are
preserved. The recovery source commit matches all 1,596 recorded tracked paths.

The worktree and its Git registration directory are absent. The complete common
Git registration set changed from ten to nine entries: only the named canary
was removed, with no additions or changes to other registrations. The local
checkout was detached, so no local branch was deleted by this operation.

A fresh public GitHub read verified merged PR #1236 head
`7070392fcb5e31282499a599f7147b56b96e5aca` and merge
`99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d`. Its remote branch is absent; the
identity of the deleting actor was not verified. This report makes no space
reclamation claim and does not assert the quarantined environment was executed.

The verifier is read-only and accepts explicit input paths; it prints JSON to
stdout. Full manifests and the detailed receipt remain private. The committed
result removes only the private_detail field. PROVENANCE.json binds all helper
versions and result bytes. The exact executed source is retained as a .py.txt
archive; the maintained copy differs only in standard-library import order.
No cleanup or GitHub mutation was performed by the independent reviewer.
