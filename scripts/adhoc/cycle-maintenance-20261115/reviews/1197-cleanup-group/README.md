# Independent PR #1197 cleanup readback

PASS at 2026-11-15T12:00:37Z. Both completed quarantines were read back in full,
including hidden/ignored entries, hashes, recorded modes and symlink targets.
No link target was traversed, and any directory enumeration error refuses.

| Retired checkout | Preserved entries | Recoverable tracked paths |
| --- | ---: | ---: |
| Original review | 14 | 1,660 |
| Refreshed repair | 469 | 1,744 |
| Total preserved | **483** | |

Both target paths and their Git registration directories are absent. Recovery
refs resolve to their exact recorded heads; their complete tracked trees match
the pre-retirement inventory and are ancestors of the merged PR source
`748cfaf510e96ffa6f8b4b08c877742cf8a492d8`. Fresh public GitHub evidence confirms
merge `9a4b0b22ce6e9bed878d512be4597502e03ed98a`; its locally read tree is
`f8d88d90cc6fb1c63b8adf8696cea978104b6c56`, matching the reviewed source tree.

The comparison accounts for exactly the two sequential removals. Every other
registration remains identical to the recorded preflight, including root head
`720776c99ba456e9c0ba3f2662ca7af162e25bd8`. Both common Git groups remained stable
during this review. The only recorded local branch deletion is
`repair/pr1197-baseline-20261115`; the review checkout was detached. The remote
source branch is absent. The expected-old-source tracking-ref deletion receipt
matches, and that exact ref is absent from both common Git groups.

The manifests measure bytes, file modes and link targets; this readback makes
no ACL/xattr claim. No complete historical census of unregistered local refs
was supplied, so the branch comparison covers the recorded deletion and all
remaining registered branches. All original receipts and quarantine contents
remain retained. No cleanup, Git/GitHub write, restoration, runtime action or
test rerun occurred during this verification.

## Helper and retained provenance

`verify_cleanup_group.py` is a narrow read-only adaptation of the retained
PR1112 group verifier, SHA256
`34d2ff30571e5a54a5c5c493a0418980de9bc154825194b1a65a459f55f4e33f`.
That original remains unchanged. Adaptation replaces only the case-specific
PR/source/merge/plan identities, verifies two sequential removals and the exact
tracking-ref receipt, removes inapplicable dirty-snapshot/root-advance checks,
and requires all remaining registrations and root HEAD to stay unchanged.
The independent directory reader propagates enumeration errors, consistent
with issue #1275, and verifies opened-file identity before hashing.

Inputs are explicit canonical paths: `--task-root`, `--reader`,
`--retirement-helper` and `--other-common-git`. The exact reader and reviewed
retirement-helper hashes are pinned in source. The reader's regular-file and
Git/GitHub functions are reused; its older walk function is not called. The
retirement helper is read only for its hash and is never invoked or imported.
The verifier emits JSON to stdout; `--private` adds local identities. Exceptions
produce nonzero exit status. It contains no apply, cleanup or output-file mode.

The helper passed scoped Ruff before one actual readback. The private full
receipt is retained under `reviews/1197-cleanup-group/verification-private.json`
in the durable task evidence. `VERIFICATION.json` was produced with the standard
`jq 'del(.private_detail)'` projection of that receipt, with no new executable
packager and no repeated inventory. `PROVENANCE.json` binds these exact bytes.
No helper is claimed to be a generic future cleanup authorizer.
