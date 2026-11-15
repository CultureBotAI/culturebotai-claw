# PR1138 main refresh evidence

Prepared 2026-11-15 after PR1112 actually merged. The local ordinary merge
integrates exact published main while preserving all nine reviewed PR additions,
including the four byte-identical inert candidate files and existing release
provenance. No new source repair was required. The prior aggregate failed with
producer_untrusted while its two component jobs passed; the protected checkout
was stale relative to authoritative main, as tracked in issue1225.

The focused archive/candidate/contract suite passed53 tests with no skips; scoped
Ruff and Git whitespace checks passed. proof.json binds exact parents/tree,
reviewed file hashes and test-log hash. It records a local head, not hosted-check
success. Independent review and publication remain root's responsibility.

metadata_refresh.py.txt retains the exact one-time metadata helper source that
prepared this merge under the shared short lease. It is a historical source
archive, not a supported executable or new cleanup/runtime interface. The commit
and normal hooks ran after releasing the lease. The private original helper,
raw failure/test logs, preflight ignored-path list and receipt remain retained.
Ignored paths were checked for continued presence; their full bytes were not
rehash-inventoried. No push, queue action, runtime adoption or root test-environment
change was performed by this preparation.
