# Independent v3 provenance review — 2026-11-15

PASS for the final 38-file v3 stage identified by manifest SHA256
`a843411987f8b14bd8ac57cb6811f9b29303e5ab836781b71f9a8a04f9e1af19`.
This is a bounded packaging review, not a whole-PR merge-readiness assertion.

The operational packager remains exactly
`902a8400b8e244b01a70c4536698914bec8981625c8ab12021d69a2ab85293cd`.
Its fixed 30-input manifest remains
`fac861a12685b2859879dbb973dce85ae712634e34fbd9317e2061b4ccb8d7de`.
I recomputed every staged-file hash, authenticated every original input, rebuilt
all 27 primary output byte streams in memory and verified exact persisted bytes.
All original inputs remain unchanged. The eleven additional files are the
ongoing regression test plus explicitly identified archival/validation evidence.
The complete staged tree, including ignored and hidden files, was checked for
concrete home paths, email addresses and process identities; none were found.

Issue1268 is fixed: both historical plan inputs are parsed from the same cached
bytes that passed authentication, and ancestor aliases are refused. Four ongoing
synthetic regression tests passed independently without skips. The two original
mutation logs were read directly: inventory fails the intended item assertion;
drift fails the intended evidence assertion. Both are call-phase AssertionErrors,
not setup/import errors. Their hashes match the retained historical receipt.
The known-history packaging positive and eight refusal controls were also read
back; their input/output guards remain unchanged from the previously reviewed v2
path. No expensive historical review or actual cleanup was rerun.

Two additional defects were independently reproduced before final packaging:

- Under issue1265, the one-time preparation helper returned success after
  overwriting two existing metadata sentinel files.
- Under issue1263, the one-time mutation helper returned success and credited
  two mutations although both selected cases failed in unrelated fixture setup.

The final stage removes executable presentation of all four one-time preparation,
finalization and control generators. Their exact historical bytes are retained as
`.py.txt` files with original names, hashes, limitations and archive mapping.
I verified every archive against its unchanged private original and the manifest;
none remains under its original `.py` name in the staged tree. This retires the
unsafe reuse paths while preserving historical evidence. The operational packager
and four ongoing tests remain unchanged and executable.

Read-only review performed no source edits, GitHub mutation, publication, runtime
operation, branch cleanup or downstream action. Raw probe fixtures and original
historical outputs remain durable. V3-REVIEW.json binds this review's helpers,
receipts and logs; probe helpers should be retained as historical source archives
with this report because their original target filenames were subsequently retired.
