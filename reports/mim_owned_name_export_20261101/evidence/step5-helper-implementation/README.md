# Pure owned-name policy implementation — Claw #701

Author implementation evidence only. Issue [#701](https://github.com/CultureBotAI/culturebotai-claw/issues/701) was filed before source edits. The parent coordinates builder/publication integration and independent review. No staging, commits, GitHub mutations, canonical edits or scientific approvals were performed by this author.

Only two maintained files were edited:

| File | SHA-256 |
|---|---|
| `src/kg_microbe_utils/owned_name_policy.py` | `18ffd0430d0256b6da6cbb1f3da2327c4cf3418e2b0b2da71ff283ee2f4351ae` |
| `tests/test_mim_owned_name_policy.py` | `62c8675b32177dbc609218851ac13d409cf6dfd628fe37118a76a6c2cc7516b6` |

The helper has the frozen API: `build_owner_index`, immutable `AliasCandidate`/`Suppression`, `filter_owned_aliases`, and `render_suppressed_aliases`. The integration-agreed exports are `SIDECAR_COLUMNS` (the exact eight-field tuple) and `POLICY_VERSION = "owned-name-policy-v1"`. There are no file reads, locks, writes, external lookups, MIM runtime imports or global ownership caches in the helper. Source arrays remain unchanged; SUPPRESS makes no scientific identity decision. Raw pipe lists refuse at the single-token boundary, so the builder must split them with their source attribution before calling.

Native representative-presence semantics, multiple credited owners, unsupported/non-emitting and AMBIGUOUS owners, Unicode casefolding, current-subject membership, deterministic aggregation and provenance requirements have direct assertion tests. Repeated suppressions aggregate one subject/casefolded-token row and retain all evidence origins. Empty output is the exact header-only TSV.

## Checks

- Focused native runtime: **48 PASS**.
- Hermetic Claw profile without sibling roots: **48 PASS**; no mandatory helper tests skipped.
- Pinned Ruff **0.16.3**, offline cached run: **PASS**.
- Isolated unchanged-source baseline: **48 PASS**.
- **Five fresh-process mutation controls killed**: disabled suppression, truthy representative fallback, first-owner-only credit, loss of later source evidence, and lowercasing instead of casefolding. Every expected failure contains actual assertion failures and excludes collection/import/syntax failures. Each child has its own source tree and bytecode prefix; production source hashes remained unchanged.
- Actual native MIM Rule K parity over **14 synthetic mapped fixtures**: owner indexes agree exactly; **240 row/token trials**, **192 native rejected trials before**, **0 after**, **165 unique suppression pairs**. The native baseline is explicitly empty. This is a synthetic contract test, not the current live mapping output and not independent review.

`commands/` retains exact argv, runtime profile, timestamps, return codes and logs. The first non-offline Ruff attempt failed package-index DNS before lint; its log is preserved and classified in `attempt-dispositions.json`. Re-running the same pinned tool with `--offline` succeeded without installing or editing the shared environment. No source defect or new finding was discovered during this focused author verification.

`run_mutations.py`, each small isolated control's source/test/log/receipt, and `mutation-results.json` retain reproducible controls. `probe_native_rule_k.py` and `native-parity-results.json` preserve the exact synthetic fixture data, validator/helper hashes and result; `native-parity-sidecar.tsv` is diagnostic test evidence only. `source/` preserves the two frozen author files. No whole corpus, database or unrelated fixture tree is copied.

The parent must still run the integrated builder/publication checks and obtain independent review before publishing the implementation. This helper does not implement bounded canonical promotion, change the Rule K baseline, drop source aliases or apply deferred Step 7 pairs.
