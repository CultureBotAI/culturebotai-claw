# Bounded primary review-clone archival candidate

Date: 2026-11-15. Related issues: CultureBotAI/culturebotai-claw#1269 and #1272–#1275.
Implementation and synthetic tests only. Independent review and fresh operator
proof are required before any actual move. No real clone has been moved by this
preparation. All actual receipts are private; publish only inspected source and
safe validation summaries.

This Darwin-only helper handles the completed task-owned shallow no-checkout
primary at the explicit task-relative path reviews/1236/repo. It preserves the
entire directory, including .git, object packs, unreachable objects, refs,
reflogs, hooks, shallow boundaries and the absent index. It uses no checkout,
read-tree, status-based restoration, fetch, unshallow, hook, prune, clean, force,
copy/delete fallback, automatic rollback or disk-space-reclamation operation.

Inputs are explicit task/source/archive/evidence/proof/plan/review/lock/helper
paths and immutable expected HEAD. The exact remaining plan and independent
checklist hashes are pinned in the source; another document cannot silently
replace their authority. The reviewed retirement helper is loaded only after
its immutable SHA256 matches5513d8c984104fe0c0d6da1c8aaa37549e6e3307baa541498a862a185bac1af9.
Only its path, JSON, Git observation and short-lease primitives are reused; its
linked-worktree retirement operation is never called.

The fresh operator JSON proof contains:

- schema_version1, canonical repository, exact task_scope/source/destination and
  expected_head; plan_sha256 and review_sha256;
- observed_at with UTC offset, at most15minutes old; owner_complete true and a
  nonempty owner_evidence explanation;
- dependencies_reviewed true, unknown_dependencies empty, and borrower_review
  with a nonempty bounded_scope plus known_borrowers empty;
- refs_sha256 over exact for-each-ref output using the helper's recorded format;
- exactly four retirements, each with relative_root, receipt absolute path and
  SHA256: the two1138 R reviews, permanent-cycle/remote-independent, and the
  remote-verifier snapshot. Each applied receipt must name the exact absent
  source and a recovery ref still present/readable in the clone.

Owner/dependency/borrower acceptance is an explicit trusted-operator boundary.
The helper authenticates the receipt bytes and their completed/exact-path/ref
shape; it does not independently redo each earlier quarantine audit or prove
there are no unknown consumers anywhere on the machine. The operator must use
accepted preservation/readback evidence and a fresh bounded borrower search.
Neither an old report nor an empty known-borrower list invented by the helper is
accepted as a global absence proof.

Before mutation the helper refuses extra primary files, any index, linked or
residual worktree metadata, operations/lock markers, unsupported config/includes,
alternates, partial-clone settings, external symlinks, hardlinks, special files,
mounts, path redirects and cross-device destinations. Equal evidence/archive
paths are also refused before creating either output (#1273). Symlink targets
must be relative and remain inside the clone at every component, including
chained links; absolute targets and escape/re-entry via old ancestry are refused
before output or movement (#1272). Ordinary internal relative chains remain
supported without rewriting their bytes. It requires a single
detached primary registration, expected origin/HEAD, readable recovery commits
and trees, intact shallow bytes and shallow-aware connectivity success.

Outside the lease it captures all hidden/ignored descendants, file hashes,
identities/timestamps, types, permissions, uid/gid, flags, ACLs, xattrs, symlink
text and empty directories. Every os.walk enumeration error propagates in the
primary inventory, quick comparison and marker scan (#1274). The shared linked
retirement walk now applies the same minimal fail-closed callback (#1275).
The original shared helper remains retained under its exact historical hash;
this correction makes no claim of loss from previously verified retirements. Darwin ACL absence is accepted only after an ENOENT
response plus an independent successful existing-node ACL listing with no ACL
entries; permission or unsupported errors remain failures. Actual ACL presence
and xattr bytes are tested. Sensitive Git/config/history bytes are never copied
into the public validation summary. Two explicit lsof observations must be clear.

The single transition uses a60second shared claw lease with a45second operation
budget. Proof/plan/receipts, registrations, refs, markers, paths and whole-tree
fingerprints are rechecked; long hashing, reader scans and connectivity checks
stay outside. Opened parent descriptors and source identity are checked before
renameatx_np with RENAME_EXCL (SDK constant0x00000004). Collision or unsupported
rename means refusal, with no fallback. The archive parent is reserved exclusively
as mode0700; output evidence uses a separate new mode0700 directory.

Post-move full readback verifies original inode/device, all descendants, bytes,
ACL/xattr/flags/modes, refs/recovery trees, shallow bytes and absent index. Only the
root ctime may legitimately differ after rename. A later failure retains the
archive, intent and original evidence without rollback or overwriting a new source.
Original receipts keep their paths; relocation.json provides the separate map.

Repaired validation: 29 archival tests passed in 10.37 seconds and 20 linked
retirement tests passed in 4.50 seconds, without skips, failures or errors.
Nine fresh-process original/fixed pairs reproduce the issue cases: three symlink
forms (#1272), equal output paths (#1273), three primary traversal consumers
(#1274), and real ACL plus injected traversal errors in the shared helper
(#1275). Each exact original source produces one assertion failure with zero
setup errors; each fixed source passes. Three earlier paired guard mutations
also remain detected. Ruff0.16.3 passes. The Darwin-specific tests explicitly
skip unsupported platforms; the injected shared-walk regression is portable.

VALIDATION.json and paired-controls-public.json remain unchanged historical
receipts for the original 22-test candidate; they do not approve the repaired
source. VALIDATION-r2.json, paired-controls-r2-public.json and
issue-paired-controls-public.json bind this repair. ARCHIVAL-PROVENANCE.json maps
the original names/hashes to exact inert source/test/docs archives. Original raw
logs, independent probes and all earlier evidence remain private and unchanged.
No real clone action or prior cleanup rerun occurred.

Packaging proposal: place archive_primary_clone.py and verify_archival_mutations.py
beside the existing retirement helper in scripts/adhoc/cycle-maintenance-20261115/
cleanup-inventory/, and test_archive_primary_clone.py under tests/. The reviewed
retire_owned_worktree.py replacement differs only by its raising traversal
callback. Its existing maintained tests gain two distinguishing regressions and
an optional synthetic-scope override for private paired runs; normal tests retain
their existing repository .temp behavior. Include test_retire_owned_worktree.py
under tests/, preserving its original exact archive. Normal packaged
tests use their own disposable ignored repository .temp fixtures; private review
runs may explicitly select a durable fixture root. Final validation receipts bind
the exact source and test hashes. Historical development failures remain private:
an initial launcher had no pytest outside a project, the first meaningful run
exposed absent-ACL/native-xattr API differences, and an import-order lint failure
was fixed. Those unversioned development sources are not represented as the final
reviewed source; their exact logs remain retained.
