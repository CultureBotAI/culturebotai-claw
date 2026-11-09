EdgeMech needs shared contracts for external ledger storage and inherited native assertions before its storage and adapter implementations can be integrated. This PR extracts the reviewed contract definitions from #953 so they can land independently of the fleet-admission prerequisite tracked in #960.

Adds the versioned Parquet-generation manifest and native-assertion envelope, fail-closed validators, mutation tests, and the prerequisite contract review. The manifest checks declared structure and accounting; storage readers must still verify persisted files, exact rows, hashes, and replay. Native assertions preserve original payloads, locators, evidence bindings, and inherited or withheld review scope. They grant no new scientific approval, and existing occurrence identities, curation bundles, the SQLite ledger, and RecordReview authority are unchanged.

This is an exact-byte cherry-pick of `1b5391d083ba85ac94e5279c3cba25ac4fde243c` onto current main `c7485ddbd86dba34a02f94bc24b72ff69a8ee4b6`. Downstream consumers retain their existing immutable source pin. The 11-file diff does not modify fleet membership, vendored governance, release declarations, rollout configuration, or workflow assets. The active DUFMech cycle release remains unchanged; EdgeMech admission stays in draft #953 and depends on #960.

Contributes to #766 and #767. The original prerequisite findings are recorded in #951 and #952; this PR alone does not complete the migration or eligible-overlap census milestones.

Validation:

- Focused contract, ledger, and active cycle-release regression tests: 198 passed in 241.26 seconds (`test_curation_artifact`, `test_curation_native`, `test_curation_contract`, `test_curation_ledger`, `test_governance_cycle_release_audit`, and `test_governance_cycle_release_workflow`).
- Required Ruff 0.16.3 check across `cli plugins pipelines src tests`: passed.
- Required mypy check: passed across 103 source files.
- Exact source-commit blob comparison and `git diff --check`: passed; worktree clean.

A separate read-only adversarial review of exact head `6031604c3b24a1a47a0b15a1ec1d46db47d73e1e` inspected both validators, schemas, and tests and confirmed the unchanged identity/review and release boundaries. No new findings. Merge remains subject to explicit user approval.

Final merge-readiness recheck, 2026-11-07: the exact head remains unchanged and
all five GitHub checks passed (pytest, fleet-audit, id-label-contract,
embedding-projection, history-round-trip). A fresh read-only pass rechecked
schema/validator agreement, strict identities, payload/evidence closure,
integer and membership accounting, inherited-status limits, and the negative
scientific-review controls; no additional blocking finding was identified.

Open review issues #951 and #952 remain cross-repository integration trackers,
not unresolved defects in this contract-only diff. EdgeMech PR #2 now has the
lossless 1,000-row migration and real native packet canaries, plus the verified
327,941-native-assertion/1,000-KG-row baseline conformance canary. Those results
create zero scientific approvals. The expanded full-population census and
specialist follow-ups continue separately; #960 admission is not a prerequisite
of this contracts-only PR. Ready for the human merge decision; no merge is
authorized by this review.
