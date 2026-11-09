# Second preliminary journal repair re-review

Reviewed exact artifact helper SHA256 `971e3cd2e8d65a1ff4a476d8c8c22a1e4209d3ea7bb0f98d184f1c7f92a820b0`, frozen in `snapshot/`. This is uncommitted repair content, not final-head approval.

The exact original journal-directory callback probe is now refused by the real native validator before artifact writes; the outside journal directory remains empty. The positive set-publication control still succeeds. The prior case/Unicode alias and no-op/postwrite destination-drift probes all refuse as expected.

One remaining concrete completion-validation issue: the helper treats a missing completed journal as a stable `None` value, and treats arbitrary stable `{}` bytes as acceptable. A wrapper runs the actual native commit, then deletes or corrupts its journal immediately before returning its original WriteResult to the helper. Both variants are reported complete. The first leaves no recovery journal; the second leaves `{}`. This models drift before the first journal capture; no production writer or input is replaced in the probe.

Require the initial completed journal to exist, parse, have the native completed shape and agree with the expected root and exact changed/created/preimage set. Keep the post-callback byte/path recheck. The finding was reported to root before any repair.

Evidence: `probe_journal_initial_capture.py` and `journal-initial-capture-results.json`; runner log `step5-independent-journal-initial-capture-v1` SHA256 `946b66f97a5d343b57819b9e75ba2114d72b6f025932453af1e116c39ccd738f`. All earlier evidence directories remain immutable.
