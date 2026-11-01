The same independent review confirmed a second alias-preflight failure: `artifact_paths` calls `abspath` before checking original path components. For output `alias/../candidate.tsv`, where `alias` is a symlink to `real/sub`, the writer normalizes away the forbidden component and reports complete after writing a different path from the supplied filesystem path.

Extend #703 to reject parent traversal and symlink components before lexical normalization for artifact paths and explicit input paths. Add a regression with the real symlink/parent-traversal shape and prove neither the lexically normalized destination nor the supplied resolved destination is written. This is confined to path identity; it does not change ownership-token normalization.

Independent evidence: `step5-claw-independent/preliminary/probe_policy_and_paths.py`, `policy-and-path-results.json`, log SHA256 `b70d4c6b9d7ad41ad2341c2af09bdb19a3b0678c981645b0a2d679a9b933b935`. Filed here before applying the additional fix.
