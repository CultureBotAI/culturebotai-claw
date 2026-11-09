# Additional original-path alias reproduction (#703)

The frozen artifact module normalizes `alias/../candidate.tsv` with `os.path.abspath` before checking symlink components. With `alias -> real/sub`, the supplied path resolves to `real/candidate.tsv`, but the publisher reports `complete` after writing `candidate.tsv` one directory higher. The actual supplied destination remains absent.

This is an independent reproduction with the real native publisher, transaction and lock. Check original lexical path components before normalization; refuse parent traversal and symlinks instead of silently changing destinations. Apply the same rule to outputs, inputs and beforeimage keys. Evidence: `probe_policy_and_paths.py`, `policy-and-path-results.json`, and `logs/step5-independent-policy-paths-preliminary-v1.log`. Root recorded the extension on #703 before repair.

The same run verified 100 ownership snapshots and 700 comparisons with the actual captured native Rule K implementation using an empty baseline. All agreed; 48 frozen pure-helper tests passed. No pure-helper provenance/ownership finding was identified in this bounded review.

`probe_legacy_boundary.py` additionally verified policy-candidate refusal for equal and different canonical bytes with no manifest, using actual repository identity validation. Four actual child-process exit cases confirmed generic/silent nonzero validation failures are refused and informational zero-exit output remains allowed. Canonical fixture bytes were preserved.
