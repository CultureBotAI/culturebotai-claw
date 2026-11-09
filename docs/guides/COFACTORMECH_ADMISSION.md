# CofactorMech admission and release hold

CofactorMech is a public cofactor corpus at
[CultureBotAI/CofactorMech](https://github.com/CultureBotAI/CofactorMech).
This admission reserves its integration identity and planned paths. The inspected
main is the empty initial commit
`3cb9d7a6ce527c84277daf6ddfd5cd56decbb4d1`, verified on 2026-11-08.
The scaffold and evidence-backed seed records are separate downstream PRs;
registration does not claim they have merged.

The package is `src/cofactormech`, the planned LinkML root is
`src/cofactormech/schema/cofactormech.yaml`, and the record inventory is
`data/cofactors/*.yaml`. Configure `COFACTORMECH_ROOT` to an identity-verified
worktree, for example `~/agent-work/CofactorMech/repo`. Keep clones, worktrees,
review receipts, unpublished commits and retained session state under
`~/agent-work/CofactorMech/`; never retain them in temporary system directories.
Push authorized committed work the same day.

## Capability and artifact status

No implementation capability is enabled based on a scaffold branch. The
manifest requires every authoritative consumer to enable `vendored_sync` as a
governance obligation; the exact 22 missing artifacts are recorded in
`tests/test_vendored_consumer_completeness.py`. That admission ledger is not proof
of deployment. It rejects an additional gap and also fails once the scaffold
reaches main, requiring removal of the completed exception.

The workflow/check mapping is the planned unconditional
`.github/workflows/validate-strict.yaml` / `validate-strict` contract. It does
not enable a remote ruleset or demonstrate a queue merge. The scaffold must
provide the actual check and `merge_group` trigger before queue activation.
Native validation, schema generation, history, source catalogues, scientific
cross-links and serialization each require their own adoption evidence before
shared capabilities are enabled. The embeddings row is a deferred text plan,
with the inspected empty tree as evidence and no claimed vectors or projection.

## Bootstrap provenance

The governance synchronizer cannot select a repository absent from its pinned
manifest. A pushed immutable commit of this admission branch can supply the
new consumer identity for supported dry-run and apply synchronization, using
the package at that exact same commit. The scaffold records that full SHA in
`scripts/.vendored_canon_ref`; all payloads remain canonical and unmodified.
An unmerged published commit is a bootstrap source, not an approved fleet
release. Preserve the pin's commit until a later reviewed re-pin is complete.

## Merge and release dependencies

The active DUFMech cycle-v2 canary release freezes the governance consumer cohort
in `src/kg_microbe_governance/releases/mech-cycle-v2-canary.json`.
`cycle_release_audit.py` rejects a change to that authority layout. A green PR
fleet audit uses the trusted base cohort and therefore does not prove the new
cohort can be released. Do not merge this admission while that lane is active.
Do not edit its declaration or weaken the audit to admit CofactorMech.
The concurrent [EdgeMech admission PR #953](https://github.com/CultureBotAI/culturebotai-claw/pull/953)
also changes fleet authority. Refresh this admission against the current main
before its merge; its EdgeMech-specific release exception is not CofactorMech
authorization.

After the release owner completes and retires that lane, the user decides the
merge sequence. Re-check the new repository's committed main, remove completed
admission gaps, reconcile capabilities against the merged scaffold, and publish
a reviewed immutable claw revision containing this registration. Synchronize
all manifest consumers to that revision, account for coupled pins, and pass the
exact committed-main fleet audit. Existing consumers are outside this PR's
mutation scope. Remote merge-queue activation, the X-Mech Suite projection and
the coordinated re-pin remain separately reviewed release work.

Cofactor seeds are candidates derived from MIM roles, not automatic assertions
of cofactor identity or biochemical requirement. Record evidence separately for
coenzymes, prosthetic groups and metal ions. Use only verified MIM, PathwayMech
and ProteinTraitsMech targets with immutable source revisions. Until MIM #1265
is merged, supplier links are provisional; no guessed `MIM:` identifier is
permitted. Missing evidence remains an explicit curation gap.
