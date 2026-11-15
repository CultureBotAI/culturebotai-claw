Retained PR1197 integration helper commits inside the metadata lease and disables normal Git hooks/signing

The retained integration helper in `scripts/adhoc/cycle-maintenance-20261115/repairs/1197-refresh/integrate_current_main.py` at reviewed source `2597b50f1cf9ee630316c880b43030e04cfac664` has SHA256 `fcb8613130d42921f38ae6d74a0073d7375abdbe4c9c7bf36af511fe8cbc97ea`.

Its common Git argument vector sets `core.hooksPath=/dev/null` and `commit.gpgsign=false`. Inside the `manager.lock("claw", "merge-pr1197-actual-main")` context, it calls `git merge --no-ff ... -m ...` without `--no-commit`. The successful apply path therefore creates the merge commit while the metadata lease is held, with normal hook execution and configured commit signing disabled. This differs from the explicit instruction to prepare the merge under a short metadata lease, then run the normal commit and hooks outside that lease.

The adjacent integration receipt records local result `748cfaf510e96ffa6f8b4b08c877742cf8a492d8`, parents `98345116994d17eaee050efb13f5414f5faaf3d4` and `bd2b07480afd3b3984491a7fc729c64220d4dd81`. The README describes the procedure as short metadata leases and says hooks do not run inside them; it does not explain that hooks/signing were explicitly suppressed or that the commit itself ran inside the lease. Keeping this as a supported executable and leaving that incomplete description would preserve the wrong procedure for reuse.

The resulting full tree and 215 focused tests were independently verified. This finding does not allege a tree defect, runtime activation or remote mutation, and does not require recreating or rewriting the valid merge history. No live merge, hook execution or runtime action is needed to reproduce the control flow: a command recorder can observe the merge invocation and active lease using offline doubles.

Acceptance:

- Preserve exact executed helper bytes and original hash as a clearly marked historical `.py.txt` archive, without an operational executable entry point. Retain original receipts and hash ledgers; add an explicit archival mapping instead of replacing the recorded history.
- Correct current README/provenance to state that this execution committed inside the lease with hooks and signing disabled. Do not describe it as the instructed prepare-then-normal-commit procedure.
- Keep the already-verified PR1197 tree and test evidence unchanged; no unnecessary rerun, force push or recreated merge.
- Verify archive bytes/hash, updated documentation and path/provenance readback independently. Any future supported integration utility must separately preserve configured hooks/signing and perform only metadata preparation inside the lease, with commit/hooks outside.

This review was read-only against the source and retained receipts; root owns issue filing and correction. No Git or GitHub mutation was performed by the reviewer.
