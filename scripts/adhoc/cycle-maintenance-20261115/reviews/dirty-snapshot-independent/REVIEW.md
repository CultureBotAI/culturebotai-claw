# Independent dirty snapshot preservation review

Date: 2026-11-15. Verdict: PASS for the two bounded preparation snapshots and
plan e85417c9e7ddc907ab40453df3c941f1d22d2ee747d13abd0fa849c875976400.
No blocking finding was reproduced. No production restoration, cleanup, GitHub
write or runtime action was performed. This is not evidence of a completed merge.

The reviewer did not author the capture helper, probe or restoration plan.
Reviewed capture helper: 9c793f327c0bb21f9607ac80d257506295c202a3cdcebf05c8a16ea94b40405c.
Original executed archive: c4473009f4095dc2a71237c69717597dfc608e5bc9a7c76be0b14439910eda2c.
Index probe: a65c199c8674e2d8a2ed857479d261d94506d944917b1017e3e35892525d8d90.

The independent verifier read all 45 first-snapshot and 40 second-snapshot
payloads back, checked current selected source bytes/modes, HEAD and original
index bytes, and compared saved HEAD/index objects against the source object
database. Both saved patch sequences reconstructed their changed index and
worktree bytes/modes exactly in new synthetic Git repositories. The first snapshot
contains 15 staged paths, including seven additions, and no unstaged changes.
The second contains seven unstaged paths and 12 preserved nonignored untracked
files. The NUL-delimited restoration lists match the plan exactly.

An additional isolated control exercised the maintained capture helper with
binary staged content, a staged symlink, a separate unstaged change, an untracked
file and an ignored directory. Source index bytes stayed unchanged. Wrong HEAD
and mismatching private-index inputs were refused before creating output. Exact
path restoration in this synthetic repository preserved the unselected tracked
change and both untracked/ignored extras. These were fixture-only mutations.

The private copied index used by the real remote-verifier capture is outside the
source worktree and has a different inode from its source index. Its original
bytes and the source index match. All three saved probe observations report
identical source/copy hashes and successful commands. The earlier refusal is
retained and correctly states that its cause is unknown; it is not evidence
that Git caused the drift or that original content was lost. The current capture
uses the copied index for index-aware queries and rechecks the source index.

Acceptance is limited to preparation. Before any actual restoration, the operator
must still verify each associated PR is merged, published-main ancestry, owner
completion, no readers or operation markers, exact HEAD/origin/common-Git identity,
all payload/index/selected-byte hashes, and the complete changed path sets. Use
the short owned metadata lease and the plan's disabled filters/conversions plus
literal path semantics. Recheck untouched extras afterward. The 12 untracked
files and all ignored descendants remain for full later quarantine inventory;
this capture deliberately makes no ignored-descendant hash-completeness claim.
The first snapshot's workspace directory must be included in that inventory.

The capture/probe are bounded evidence utilities, not general cleanup executors.
The retained review helpers take explicit input paths. verification.json and
controls.json contain public-safe hashes/counts; private fixtures and originals
remain in the owned durable work area. No source helper or plan was edited during
this review. No new issue was filed because no actual blocking defect was found.
