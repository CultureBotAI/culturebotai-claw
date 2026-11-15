# PR1197 refresh after published main integration

2026-11-15, issue1262. The previous published head98345116994d17eaee050efb13f5414f5faaf3d4
used an older event base; the fleet audit correctly reported producer_untrusted.
After PR1112 actually merged, the owned repair branch received an ordinary merge
of published mainbd2b07480afd3b3984491a7fc729c64220d4dd81. Local result:
748cfaf510e96ffa6f8b4b08c877742cf8a492d8, treef8d88d90cc6fb1c63b8adf8696cea978104b6c56.

The complete tree is exactly current main plus the prior nine PR paths. No source
conflict or scientific/runtime change was introduced. Maintained check-baseline
and refresh preview both equal the existing baseline lock. Its actual source
66e6c6a15ff05a098bcb275686bcc6d74b20eaeb still authenticates all60 authority inputs;
no forced source pin or baseline-only commit was made. The unchanged baseline
SHA256 is67b52e3880438c827458241c366bdf8005efacbbdaec8664180b9bb7d746c424.

`integrate_current_main.executed.py.txt` preserves the exact executed helper
bytes as a historical archive. It is not an operational integration entry point.
Issue #1270 records the procedural defect: this execution created its merge
commit **inside** the metadata lease while explicitly setting
`core.hooksPath=/dev/null` and `commit.gpgsign=false`. Hook suppression did not
satisfy the instruction to prepare metadata under the lease and run the normal
commit, including configured hooks/signing, after releasing it. No normal-hook
execution is claimed for that historical merge.

The archive preserves what actually ran; the already-verified source tree,
parents, test results and original hash ledgers remain unchanged. No live integration was
rerun, and the merge was not recreated. `ARCHIVAL-PACKAGING.json` maps the
original executed pathname/hash to the byte-identical archive and records the
unchanged ledgers. Their original helper pathname remains a historical input
identity. A future supported utility must be reviewed separately and keep only
metadata preparation inside the lease, with commit/hooks outside and configured
hook/signing behavior preserved. `verify_refreshed_tree.py` remains read-only and
authenticates the full tree and retained maintained-tool outputs.

The raw baseline check/preview and earlier event failure log remain in private
durable evidence; their authority is the committed public source object, not a
copied status claim. Public integration/verification/validation receipts and the
actual focused pytest log are retained here. 215 tests passed in12.68seconds.

At this handoff, publication, independent review and new hosted final-head checks
are pending. No queue admission, force push, runtime installation, hook install,
consumer adoption or cleanup was performed. The existing owned repair worktree
is clean and retained for the parent publisher/reviewer. The root publisher owns
same-day publication after independent review.
