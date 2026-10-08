# TaxonMech onboarding — 2026-09-11

> Historical onboarding snapshot from 2026-09-11, archived on 2026-10-08 UTC.
> The pending steps below describe the original pre-release checkpoint.
> Registration merged in [PR #397](https://github.com/CultureBotAI/culturebotai-claw/pull/397),
> and admission completion merged in [PR #400](https://github.com/CultureBotAI/culturebotai-claw/pull/400).
> Use the maintained [onboarding skill](../../.claude/skills/onboard-mech/SKILL.md)
> and [governance guide](../guides/VENDORED_GOVERNANCE.md) for current procedures.
> The ignored workspace evidence referenced below is local historical provenance.

TaxonMech is registered locally in CLAW. Published governance adoption remains
pending the coordinated canonical release described below.

| Area | Result |
|---|---|
| Identity | `taxonmech`, `CultureBotAI/TaxonMech`, package `src/taxonmech` |
| Root | `TAXONMECH_ROOT` added to configuration, setup example, and local environment; exact root/origin validation passes |
| Membership | Fleet manifest and governed-consumer registry agree; research `MechEnum` includes TaxonMech |
| Capabilities | All 25 catalogue keys declared: 13 enabled, 9 disabled, 3 not applicable |
| Committed-main corpus report | 100 taxon records read successfully; 2,728,149 bytes; four configured classification fields populated |
| Shared site contract | 104 HTML pages and one stylesheet checked; no findings |
| Generic record writes | Refused through `serialization.verified: false`; native seeder and corpus reproduction remain required |
| Pull visibility | Offline preview reports all 10 registered repositories, including TaxonMech as skipped because its active checkout is dirty |
| Claude procedure | `.claude/skills/onboard-mech/SKILL.md` created, catalogued, validated, and followed for this admission |
| Candidate CI | Completeness checks clone newly proposed members as well as checking the deployed fleet |
| Governed rollout | Pending: canonical admission revision, missing workflow, coordinated pin update, committed-main audit |

## Evidence and capability decisions

The inspected committed main is
`95fef619dba5694ee24c5f5c884c96e6f71d762a`. The complete GitHub tree was checked,
and searches used to establish absence included ignored and hidden local files.
Independent edits in the active checkout were inspected separately and preserved.

Read-only records are `data/taxa/**/*.yaml`, with schema
`src/taxonmech/schema/taxonmech.yaml`. Raw inventories and the slug registry are
excluded. Shared corpus statistics use `taxon_domain`, `rank`,
`grounding_status`, and `mapping_status`.

Enabled capabilities cover ID/label validation, curation history, closed-schema
validation, schema generation, shared release/build/documentation/testing/
refactoring/hook orchestration, vendored synchronization, corpus statistics, and
site checks. Orchestration eligibility does not assert installed local hook
copies or a native release recipe.

Deferred capabilities are research execution, knowledge-gap scanning, page
budgets, shared writer auditing, SSSOM export, METPO proposals, KGX export,
source queues, and the shared source catalogue. Each has a reason in the
manifest. TaxonMech references METPO in its schema but does not publish proposal
cohorts; it therefore appears in fleet inventory without becoming a METPO
proposal input. Edison discovery, environment coverage, and unmapped-ingredient
inventory do not apply to its current corpus.

## Governing release dependency

TaxonMech main pins `eeccfebe2369dec0f5575aff25e0350e04ec19ec`, whose consumer
registry excludes TaxonMech. Merely copying the missing workflow cannot make
that pin recognize the repository.

Thirteen applicable governed artifacts match the current canonical bytes and
Git executable modes. The one missing artifact is
`.github/workflows/pr-shepherd.yml`. The temporary `INCOMPLETE_CONSUMERS` entry
records this admission gap and must be removed when main carries the workflow.
It does not waive pin identity, canonical checksums, or the final fleet audit.
The admission check requires exactly this missing path, rejects additional
omissions, and requires removal of the entry when the gap is closed.

A clean, independent checkout and an unapplied patch derived from the canonical
artifact were prepared locally under `workspace/taxon-onboarding/`.
`git apply --check` accepts `taxonmech-pr-shepherd.preview.patch`; the checkout
remains clean. `governance-preview.json` records every artifact digest and mode.
The governed synchronizer must apply the actual release after its immutable
revision exists; the preview does not invent or substitute a pin.

Release in dependency order:

1. Publish the reviewed CLAW admission revision with aligned fleet and consumer
   registries and the candidate-completeness CI fix.
2. From that revision, preview and apply governed synchronization in isolated
   consumer worktrees. TaxonMech receives the missing workflow and the new pin;
   the existing consumers receive the same pin and any manifest-required changes.
3. Land the downstream changes, remove the temporary completeness entry, and
   run the strict fleet audit against every committed main tip and the common
   immutable revision. A later CLAW commit that only removes the ledger need
   not change the canonical pin when the governing manifest/payloads are equal.

The [onboarding skill](../../.claude/skills/onboard-mech/SKILL.md) and
[governance guide](../guides/VENDORED_GOVERNANCE.md) distinguish local admission
from completed publication. No active downstream checkout was changed by this
onboarding work.

## Local validation

Manifest/profile, root configuration, research membership, capability reason,
packaging, skill catalogue/reference, governance admission/audit, serialization,
fleet pull, METPO aggregation, corpus, and site tests were exercised. The new
candidate CI tests cover a new consumer, invalid declarations, clone failures,
and mismatched origins. Admission regressions check unexpected missing files,
completed adoption, and required roots.

The broad run exposed stale fleet-count and TraitMech link-count assertions;
the counts were updated for membership, while the TraitMech test now checks its
published-root invariant without fixing the number of growing corpus links.
Ignored bytecode left under a retired compatibility directory was moved to a
local backup so the existing absence guard could run; no source was removed.

The installed commands validate configuration, resolve all configured roots,
list the onboarding skill, include TaxonMech in the pull preview, and read its
corpus and site successfully. Full native QC was not run in the active TaxonMech
checkout because it would generate files during independent work. The final
published-pin audit remains part of the governing release above.
