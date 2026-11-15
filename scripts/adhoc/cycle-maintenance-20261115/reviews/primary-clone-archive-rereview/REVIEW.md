# Independent archive-helper rereview

Date: 2026-11-15. Verdict: PASS for the exact sources below. Findings
CultureBotAI/culturebotai-claw#1272–#1275 are resolved in these bytes. This review
is evidence about implementation and synthetic behavior, not fresh authorization
or current-state proof for moving a real clone.

Reviewed archive helper SHA256:
5ce40d5164a70a3ceb6084b6ea2a9d0e99452ec11479693e67ff0e4242d1a835.
Reviewed shared retirement helper SHA256:
5513d8c984104fe0c0d6da1c8aaa37549e6e3307baa541498a862a185bac1af9.
The archive helper pins this exact repaired shared helper. The shared change
only propagates traversal errors; prior original bytes and receipts remain intact.

The scoped repairs reject absolute links and resolve each relative link component
and chain without leaving the clone, reject equal output directories, and make
all archival/shared directory walks fail on enumeration errors. Relative internal
links retain their positive preservation test. Reviewed plan/checklist pins,
cached authenticated proof bytes, fresh owner and borrower attestations, retirement
receipt/recovery gates, final proof rechecks and path identity checks remain.

Shallow history is preserved with Git's existing boundary; no ancestry assumption
requires missing parents. The supported source shape remains one detached
no-checkout primary containing only its Git directory, with an absent index.
Full inventory includes hidden/ignored entries, metadata, ACLs, xattrs and empty
directories. The short lease contains metadata rechecks and a descriptor-bound
Darwin exclusive rename. Collision, changed source identity, unreadable traversal
and unsupported dependencies refuse. Post-move failures retain the archive and
intent without rollback or a success receipt. No actual task clone was scanned
in full, moved, retired, reset, pruned or otherwise changed in this review.

Independent validation used byte-identical isolated copies and fresh Python/cache
process state: 55 tests passed in 15.30 seconds, with no failures, errors or skips.
This comprised 29 archival tests, 20 shared retirement tests and the six unchanged
independent probes retained with the initial review. Actual Darwin ACL and native
exclusive-rename behavior were exercised only on disposable fixture directories.

The author's nine original/fixed paired receipts were independently read back:
all source/log/JUnit hashes match; every original reaches its intended assertion
failure, every fixed control passes, and none has setup errors or skipped tests.
The original archive and shared helper archives retain exact SHA256 values
417893f1064336d04c90e41cffebc1675c538ab16064ce28373bc498def107d9 and
91c07258e5efdd77d5f4c91b07c1815469bc3cd803db87e5e62e223c27b5de2e.

Raw private test logs/JUnit remain retained; public results contain only their
hashes and verified counts. The exact one-time review probes are preserved in
the initial review's inert archives. No helper was changed or regenerated for
this rereview. Ongoing regressions belong under tests/ when packaged.

Before real archival, the operator must still verify the exact published/reviewed
helper bytes and current linked-retirement receipts, ownership and bounded borrower
release, readers, source/head/ref state, complete private inventory, accepted plan
and destination absence. This review does not waive those gates or imply runtime,
release, consumer-adoption or unrelated cleanup authority.
