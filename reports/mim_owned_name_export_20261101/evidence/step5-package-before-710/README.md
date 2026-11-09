# Owned-name export evidence

This package preserves implementation, negative controls, independent review, and diagnostic candidate generation for Claw issues [#701](https://github.com/CultureBotAI/culturebotai-claw/issues/701)–[#708](https://github.com/CultureBotAI/culturebotai-claw/issues/708). It grants no scientific approval and publishes no MediaIngredientMech canonical mapping or baseline changes. Source authorship and independent review are separately attributed in the archived receipts.

The diagnostic candidate was generated at Claw `90d110e663c10146351b09ae98d387dabdec0b1c`. The subsequent `a56f3ae4563619a5129ad944878c9205267315d6` commit changes only README mypy-target documentation. The final full suite ran at that later source head. Generation receipts retain their actual earlier revision and exact producer/source hashes. The source entrypoint and captured dependency graph assume a trusted caller/interpreter; this is not cryptographic runtime attestation.

Actual v4 candidate acceptance is **PASS_WITH_LIMITATIONS**: schema and unmodified native invariants pass with zero rejected data rows, including Rule K with an empty in-memory baseline. B4 checks the available transforms; BTO (1 row) and MICRO (73 rows) are unavailable under the native warning-and-skip contract. The standalone B4 report preserves affected rows and available input hashes. This is not full ontology coverage. The prior v3 acceptance FAIL remains archived: its harness required all B4 transforms to exist, a stronger precondition than the native gate.

The candidate has 2,974 rows. The builder produced 25 suppression events, aggregated into 20 sidecar rows for distinct subject/name pairs: 7 previously published tokens are removed, while 13 encountered aliases were already excluded by dedicated-label handling. These diagnostic encounters do not imply promotion of deferred canonical policy changes. Detailed before/after classification and captured label-resolution differences remain in the acceptance evidence. MIM YAML, canonical SSSOM, and Rule K baseline remained unchanged.

The completed v5 full suite passed **6,660 tests**, with 390 skips and 16 warnings; measured coverage was **87.19%**. Safety-module coverage was **76%**, above its 60% gate. Final maintained mypy and Ruff checks passed. The final validation summary binds their exact receipts and logs, along with configuration, canary QC, generation, acceptance, and README-parity checks. Each archived command retains its own actual execution context; earlier configuration/canary runs are not relabeled as final-head executions.

Independent source-repair review and the #708 packaging repair review both record **PASS_WITH_LIMITATIONS**, no remaining findings within their reviewed scope, and the trusted-caller and review-stage boundaries. The #708 repair binds the frozen plan to the hash-bound selection plus explicit run root and checks the packaged README against selected content. Its original successful substitution proof is retained. The repaired packager passes 21 fixture checks; old code and four fresh guard-removal mutants fail actual assertions.

Failed probes and interrupted suites remain archived with dispositions. These include the real full-suite-v3 README/AGENTS/CI parity failure and README-only repair; the v4 sandbox refusal of `/bin/ps` in an existing lifecycle fixture; the successful authorized focused rerun; and the complete, successful v5 rerun with process access. Earlier incomplete suites and source/candidate evidence remain historical where later repairs supersede them. None is relabeled as a successful final check.

`manifest.json` maps each retained original path and SHA-256 to its portable payload. Large files use deterministic gzip; identical bytes may share one payload. Historical indexes remain unchanged and may reference explicitly omitted bulky fixture trees, copied repositories, or caches. The portable selection and omission list define this package's exact scope.

From the repository root:

```bash
python reports/mim_owned_name_export_20261101/verify.py verify \
  --package reports/mim_owned_name_export_20261101 --repository . --require-tracked
```

Verification checks bytes, membership, source references, command/log bindings, artifact/receipt links, and recorded limitations. It does not rerun checks or approve scientific assertions. The independent review of the eventual package commit and PR body remains external to avoid circular self-binding; this package does not claim that future review, remote CI, publication, or merge has completed.
