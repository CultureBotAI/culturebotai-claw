---
name: onboard-mech
description: "Inventory, generate, adopt and update the reusable Mech baseline, or register a Mech in CLAW. Use for new-repository infrastructure, existing-consumer skills and workflow updates, and template maintenance."
metadata:
  category: cross-repo
  requires_database: false
  requires_internet: true
  version: 2.0.0
  tags: [fleet, onboarding, governance, cross-repo]
---

# Onboard a Mech

Run from CLAW. Read `docs/guides/MECH_STANDARD.md` for adoption requirements and
`docs/guides/VENDORED_GOVERNANCE.md` for the release contract. Re-derive current
membership and capabilities from `src/kg_microbe_fleet/fleet.yaml`; historical
counts and neighboring repositories are not a registration specification.

## Reusable baseline lifecycle

Read [the baseline guide](../../../docs/guides/MECH_TEMPLATE.md) for the current
composition, commands, ownership, migration and rollback process. Use the
existing authorities; do not copy a mature corpus's scientific policy.

1. Inventory published heads and pending dependency PRs, then compare native
   commands, skills, schema/writer/review contracts and instruction symlinks.
   Resolve public targets through `load_fleet_manifest` and `RepositorySettings`;
   keep private consumers on their separately declared identity/policy path.
2. Run `python -m kg_microbe_skills.template_cli check-baseline --source-root .`.
   Canonical changes use `unify-skills` and `evolve-mech-workflow`, followed by
   the reviewed baseline refresh. The baseline references those authorities;
   it never becomes a competing payload source.
3. Record every component's adoption/defer/inapplicability decision and evidence
   in the consumer configuration, including native checks and release holds.
   Do not enable a sealed admission capability to make a template selector work.
4. Plan in an isolated worktree, review conflicts and unmanaged regions, then
   apply the authorized scope through the deterministic template tool. Existing
   local scientific extensions and active cycles remain authoritative.
5. Complete one full canary: native checks, hosted checks, repeat-run no-op and
   preservation proof. Only then update additional consumers by the same path.
6. Independently review the changes, file and fix actual findings, and publish
   dependency-ordered PRs. Report candidate installation separately from merged
   adoption, release and runtime activation.

Fleet maintenance and ordinary CI check canonical currentness; consumer drift
checks drive subsequent update PRs through `cross-mech-sync`. This process does
not install a scheduler or grant merge/release permission. Registration below
is needed only when the reviewed scope changes fleet membership; ordinary
baseline adoption must not re-register an existing or private consumer.

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
   applicable path assertions. `kgx_export` and `sssom_export` apply to every
   Mech, so they are `enabled` or `disabled`, never `not_applicable` (#503). Recipe names alone do not prove shared-command
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
   and maintained setup documentation. Verify the Mech's instruction and skill
   layout matches the fleet convention (`AGENTS.md` as the real instruction file
   with `CLAUDE.md -> AGENTS.md` as a relative symlink, and `.claude/skills/` as
   the real skill directory with `.agents/skills -> ../.claude/skills` as a
   relative symlink so `src/kg_microbe_governance/artifacts/scripts/record_review.py`'s
   `O_NOFOLLOW` walker succeeds).
   Record Tier 1 gaps and deferred capability work with evidence; registration
   alone does not implement missing features.
7. When the companion X-Mech Suite repository (`CultureBotAI/CultureBotAI.github.io`,
   `CULTUREBOTAI_SITE_ROOT`) is in scope, refresh `CultureBotAI.github.io/_fleet/data/manifest.json`,
   card copy (`CultureBotAI.github.io/_fleet/mechs_template.md` and
   `CultureBotAI.github.io/_fleet/fleet_fragment.html`), and generated suite
   artifacts (`CultureBotAI.github.io/_fleet/data/site_audit.json` and
   `CultureBotAI.github.io/mechs.md`) via
   `CultureBotAI.github.io/.claude/skills/update-xmech-page/SKILL.md`
   so `https://culturebotai.github.io/mechs/` stays synchronized with
   `src/kg_microbe_fleet/fleet.yaml`.

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
