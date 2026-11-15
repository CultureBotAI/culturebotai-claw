# Retained executed historical packagers

Date: 2026-11-15. Issues #1265/#1266 also apply to the four review packagers below.
Their original executed bytes are preserved as inert `.py.txt` files before
correcting their active entry points. Existing public summaries and original
private reports were not changed or regenerated.

| Archived source | Original and archive SHA-256 | Corrected entry-point SHA-256 |
| --- | --- | --- |
| `package_source_reviews.executed.py.txt` | `8f361c8b49222b363af157a55572e37d503e22ba55fc88fb68bd9c234f4e120a` | `b2b62873e9a05bc21defce9277a2699670038709ea93f518f1e1898bb1792d75` |
| `package_followup_reviews.executed.py.txt` | `42ad7c3549aaf2428531aa41dcc0d0ca59c35cdfb524911d19093db2cc602615` | `bbee1aa7de9d317003979ae6083946049be86437bac62b35ea96ca2a18fd83ae` |
| `package_review_pr1112_20261115.executed.py.txt` | `0f409dfc6059def0e31309c9dfe79c4b1fadd8fb7d907377353a2659218fe6d6` | `1e1bb96ed7b1587b2865a3259fc5b9f70b2c80582cb24dfac8c80de64d82a920` |
| `package_review_pr1236_20261115.executed.py.txt` | `f6508c1be607ed661ffbc05620631b7b8e24cef3280fef97c436f63a0b37f0e9` | `587006120a343a9dba8cfa5a292ec33ded8b0b0e3531bbd8f23c2ccb032b9f86` |

The entry points remain under `../../reviews/`. They now explicitly refuse all
execution requests with exit 2 before reading inputs or writing outputs. Their
`--help` paths still describe the preserved history. This is deliberate archival
retirement: the original scripts encoded particular review conclusions without
authenticating every input and could overwrite existing evidence. They are not
safe generic generators. The preserved historical outputs remain dated evidence;
retirement does not invalidate or fabricate their original review observations.

Twelve offline controls cover missing inputs, fabricated failing reports and existing
result files for all four entry points, require exit 2 with the archival-only reason,
and prove input bytes and directory absence remain unchanged. Original-byte
hashes and the harmless `--help` behavior are also checked. No expensive source
review or scientific generation was repeated. Any future general packager needs
its own reviewed input-authentication and exclusive-output contract.

Four further controls forbid filesystem reads and command execution while
invoking each retired entry point. The original two-wrapper receipt remains in
`retirement-verification.json`; the subsequent four-wrapper validation is
separately retained in `four-wrapper-verification.json` (51 tests passed) and
does not rewrite that earlier observation. For PR1112/1236, these archives are
the exact previously published portable copies; the original private guard
versions and their packaging-edit provenance remain retained separately.
