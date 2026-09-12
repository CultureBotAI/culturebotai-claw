---
name: onboard-mech
description: "Register a Mech repository in CLAW's fleet, configure its local root, and reconcile its capabilities and vendored governance. Use when adding a new Mech or completing an existing repository's fleet onboarding."
metadata:
  category: cross-repo
  requires_database: false
  requires_internet: true
  version: 1.0.0
  tags: [fleet, onboarding, governance, cross-repo]
---

# Onboard a Mech

Run from CLAW. Read `docs/guides/MECH_STANDARD.md` for adoption requirements and
`docs/guides/VENDORED_GOVERNANCE.md` for the release contract. Re-derive current
membership and capabilities from `src/kg_microbe_fleet/fleet.yaml`; historical
counts and neighboring repositories are not a registration specification.

## Establish the candidate

```bash
uv run python -m kg_microbe_fleet list --format tsv
```

A user-named repository outside this output permits read-only bootstrap
inspection. Verify its exact Git worktree root, every origin fetch/push URL,
owner/repository identity, and remote default branch. Record the inspected
committed revision and inspect worktree changes separately. Label cached
evidence when remote verification is unavailable.

Inspect the installed package, LinkML schemas, record directories, recipes,
workflows, research profiles, generated artifacts, and vendored pin. Capability
claims must describe committed default-branch behavior; report differences in
the working tree. Before concluding a path or feature is absent, search with
`rg --no-ignore --hidden` (or equivalent), including ignored files.

## Register the local integration

1. Add the candidate's exact identity, root environment variable, package path,
   schema paths, and record globs to `src/kg_microbe_fleet/fleet.yaml`.
   Declare every current capability catalogue key. Enable only capabilities
   supported by implementation evidence, including all required settings;
   otherwise use `disabled` or `not_applicable` with a reason and the catalogue's
   applicable path assertions. Recipe names alone do not prove shared-command
   compatibility. Check required profiles and adapter contracts.
2. Preserve `record_globs` for read-only corpus inventory, including generated
   records; exclude unrelated fixtures and runtime state. Generated corpora use
   `serialization.verified: false`, a reason, and no options to preserve their
   native writer/reproduction gate, even if byte-identical round trips are
   possible. Other corpora require measured round-trip evidence before declaring
   verified options. Never invent serialization fields.
3. Add the matching consumer identity and package path to
   `src/kg_microbe_governance/vendored_artifacts.json`. Fleet membership and
   consumer membership must agree exactly; do not relax their equality check.
   Measure every applicable artifact against committed `origin/main` with
   `git ls-tree`, independently of working-tree copies. Record exact missing
   paths and the inspected SHA. If admission precedes artifact completion, use
   the temporary `INCOMPLETE_CONSUMERS` ledger in
   `tests/test_vendored_consumer_completeness.py`, declaring the exact
   `expected_missing` paths and reason. Run its bidirectional checks and remove
   the entry when complete. This ledger does not establish deployment.
4. Add the root field to `src/kg_microbe_config/openclaw_config.yaml` and
   `.env.example`. Configure only this root in local `.env` when its location is
   verified, preserving unrelated values and avoiding secret-bearing output.
   Check `plugins/repository_settings.py` integration; do not duplicate its list.
5. Add the candidate's workflow/check mapping to the packaged merge queue policy
   at `src/kg_microbe_merge_queue/policy.json`; its keys must equal the fleet plus
   CLAW. Inspect exact GitHub job names, make required PR triggers unconditional,
   add `merge_group: {types: [checks_requested]}`, and validate the combined commit.
   Follow `docs/guides/MERGE_QUEUES.md`: land CI readiness before enabling rules,
   retain before/after receipts and prove an authorized PR actually merges through
   the queue. Membership alone does not enable the remote queue.
6. Reconcile `MechEnum` in
   `src/kg_microbe_research/schema/research.yaml`, required fleet contract tests,
   and maintained setup documentation. Record Tier 1 gaps and deferred capability
   work with evidence; registration alone does not implement missing features.

Use existing authorization for the requested local onboarding. Preserve dirty
downstream checkouts; use dedicated clean worktrees for downstream changes under
the repository-lock workflow in `cross-mech-sync`. Never stash, reset, switch an
active checkout's branch, or include unrelated changes to complete onboarding.

## Verify local coverage

```bash
uv run openclaw-cli config validate
uv run python -m kg_microbe_fleet targets --capability vendored_sync --dotenv .env
uv run pytest tests/test_fleet_manifest.py tests/test_fleet_cli.py tests/test_research_fleet_contract.py tests/test_authoritative_governance_layout.py -q
```

Run the affected manifest/profile, governance, configuration, and fleet-report
checks as required by the changed files. Validate configured roots for relevant
capabilities with
`uv run python -m kg_microbe_fleet targets --capability <capability> --dotenv .env`.
Omit `--dotenv` only when using exported roots instead of a local environment file.
Verify the repository appears in fleet-wide reports, even when dirty,
unconfigured, or ineligible for a particular capability. Inventory and root
validation are read-only; update checkouts only when that work is requested.

## Complete the governing release

Adding a consumer changes the canonical manifest even when payload bytes remain
identical. Released onboarding therefore requires a published immutable CLAW
revision containing the registration, coordinated re-pinning of **every**
consumer to that revision, and a successful `kg-microbe-governance fleet-audit`
against all committed default-branch tips. Derive the exact consumer set from
the manifest. Follow the governance guide and `cross-mech-sync` release workflow;
the synchronizer rejects a local package that differs from the published ref.

Do not invent an unpublished pin, hand-edit governed downstream copies, or use
the legacy `transition` migration state to bypass authoritative equality or
audit checks. Prepare reviewable changes before any publication approval needed
by the session; existing explicit authorization persists. Do not expand local
onboarding into an unrequested fleet publication or claim a release is complete
while its coordinated rollout remains outstanding.

Finish with a table of registration, root, capabilities, runtime visibility,
validation, and release status. Distinguish local onboarding from released
deployment; identify release dependencies and preserved dirty checkouts.
