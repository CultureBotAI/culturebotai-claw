# Owned-name export evidence

This package preserves implementation, negative controls and diagnostic candidate generation for Claw issues #701–#708. It grants no scientific approval and publishes no MediaIngredientMech canonical mapping or baseline changes. Source authorship and independent review are separately attributed in the archived receipts.

The current diagnostic candidate was generated at Claw `90d110e663c10146351b09ae98d387dabdec0b1c`. A subsequent README-only fix at `a56f3ae4563619a5129ad944878c9205267315d6` synchronizes the documented mypy targets with AGENTS and CI. Generation receipts preserve their actual earlier revision and exact producer/source hashes. The source-bound entrypoint and captured dependency graph assume a trusted caller/interpreter; this is not cryptographic runtime attestation.

Actual v4 acceptance is **PASS_WITH_LIMITATIONS**: schema and unmodified native invariants pass with no rejected data rows, including Rule K with an empty in-memory baseline. B4 checks the available transforms; BTO (1 row) and MICRO (73 rows) are unavailable and explicitly recorded under the native warning-and-skip contract. The standalone B4 report preserves affected rows and available input hashes. This is not full ontology coverage. The prior v3 acceptance FAIL remains archived; its harness required all B4 transforms to exist, a stronger precondition than the native gate.

The candidate has 2,974 rows and the builder produced 25 events, aggregated into 20 sidecar rows for distinct subject/name pairs: 7 previously published tokens are removed, while 13 encountered aliases were already excluded by dedicated-label handling. These diagnostic encounters are not a claim that all deferred canonical policy changes were promoted. Detailed before/after classification and captured label-resolution differences are preserved in the acceptance evidence. MIM YAML, canonical SSSOM and Rule K baseline remained unchanged.

[FINAL CHECK RESULTS AND INDEPENDENT ASSESSMENT MUST BE FILLED FROM COMPLETED RECEIPTS BEFORE PUBLICATION.]

Failed probes and interrupted suites are retained with dispositions, including the real full-suite-v3 README/AGENTS/CI parity failure and its subsequent README-only repair. The v4 full-suite sandbox failure and successful authorized focused rerun are separate evidence; the complete v5 rerun is pending. The independent #708 frozen-selection substitution proof is preserved alongside the repaired packager controls. Earlier source and candidate evidence is historical where later fixes supersede it. None is relabeled as a successful final check.

`manifest.json` maps every retained original path and SHA-256 to its portable payload. Large files are compressed with deterministic gzip; identical bytes may share one payload. Original indexes remain unchanged and may reference explicitly omitted bulky fixture trees, copied repositories or caches. The portable selection and omission list define this package's exact scope.

From the repository root:

```bash
python reports/mim_owned_name_export_20261101/verify.py verify \
  --package reports/mim_owned_name_export_20261101 --repository . --require-tracked
```

Verification checks bytes, membership, recorded source references, command/log bindings, artifact/receipt links and the recorded limitations. It does not rerun the recorded checks or approve scientific assertions. The independent final committed-head review is external to avoid circular self-binding.
