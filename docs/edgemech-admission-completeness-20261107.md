# Complete EdgeMech admission across fleet consumers

The final read-only dependency audit of PR #953 at
`68ea856081c963465ba2ee58a5a7748463e2b8cb` found 17 failing tests in
[CI job 128534585492](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/42416152893/job/128534585492):
7,836 passed and 446 skipped. Only one failure is the intentional immutable
release-policy blocker tracked by #960. The remaining failures expose incomplete
fleet admission and stale fixed-cohort test fixtures.

Runtime defects: `fleet_pull` rejects `edgemech` in its LinkML vocabulary;
`load_policy()` rejects the entire merge-queue policy because its keys omit the
new fleet member; EdgeMech has no explicit unverified serialization profile;
the research vocabulary omits its display name. Repair these declarations
without claiming native record serialization, scientific review, research
execution, or queue readiness. Keep EdgeMech queue adoption explicitly blocked
on #960. Derive membership-only test expectations from the canonical fleet or
capability declarations; retain meaningful domain-specific fixtures.

Exact failing tests (module names below are under `tests/`):

- `test_fleet_manifest_wheel.py::test_wheel_packages_canonical_manifests_and_payloads`
- `test_fleet_pull.py::test_cli_selects_manifest_repositories_and_reports_coverage[False]`
- `test_fleet_pull.py::test_fleet_pull_schema_repository_keys_match_manifest`
- `test_governance_cycle_release_audit.py::test_packaged_release_binds_exact_manifest_and_workflow_assets` — preserve this #960 blocker.
- `test_governance_fleet_audit_cli.py::test_fleet_audit_cli_parses_repeated_roots_and_reports_success`
- `test_merge_queue.py::test_policy_covers_manifest_including_taxon_and_ships_with_wheel`
- `test_merge_queue.py::test_claw_required_workflows_are_queue_ready`
- `test_merge_queue.py::test_dufmech_policy_uses_native_validation_not_pages`
- `test_merge_queue.py::test_cmmmech_policy_uses_verified_native_validation_context`
- `test_merge_queue.py::test_aimech_policy_uses_native_validation_context`
- `test_record_serialization.py::test_every_mech_declares_a_serialization_profile`
- `test_record_serialization.py::test_an_unverified_profile_refuses_rather_than_guessing[edgemech]`
- `test_record_serialization.py::test_an_unverified_profile_records_why[edgemech]`
- `test_research_schema.py::test_schema_vocabularies_cannot_drift_from_provider_and_fleet_contracts`
- `test_review_domain_fit.py::test_domain_cases_cover_the_actual_manifest`
- `test_skill_catalogue.py::test_review_eligibility_is_independent_of_scientific_curation`
- `test_vendored_consumer_completeness.py::test_the_manifest_declares_the_consumers_the_fleet_expects`

Acceptance: focused regression tests, lint and type checks pass; a separate
read-only review approves the repairs; the final PR CI has no failures beyond
the unchanged release gate in #960. Do not rewrite historical DUF policy,
weaken release checks, repin consumers, or modify contracts-only PR #962.
