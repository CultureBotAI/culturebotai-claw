# Preparing repository freshness without changing a running cycle

The canonical publication procedure is
[Repository freshness 1.0.0 release](REPOSITORY_FRESHNESS_RELEASE.md). A source
PR, proposal-only adapter or release tag alone does not adopt a running session.

The independent repository-freshness contract is version 1.0.0. Its packaged
LinkML schema and canonical YAML live in `src/kg_microbe_workflows/schema/` and
`src/kg_microbe_workflows/templates/`. Existing six- and seven-goal parents,
profile bytes and their evidence remain unchanged. The same contract applies
to agy and Codex execution; a rendered skill is not enforcement or adoption.

## Preparation

`python -m kg_microbe_governance.freshness_candidates` reads the canonical fleet
manifest through its loader and includes claw separately. With no
`--repository`, its explicit root map must contain every manifest Mech plus
claw. Repeat `--repository KEY` only for an explicitly scoped canary or batch.
No implicit `.env` target, live-checkout fallback or branch switch exists.

Create separately owned feature worktrees under durable agent work storage.
Resolve each through `RepositorySettings` and verify its canonical identity.
The root map is a trusted coordinator's explicit ownership declaration:

```json
{
  "mediaingredientmech": {
    "root": "/absolute/owned/worktree",
    "expected_head": "FULL_OBSERVED_CONSUMER_COMMIT",
    "expected_branch": "prepare/repository-freshness",
    "default_branch": "main",
    "ownership": {
      "owner_id": "freshness-preparation",
      "repository_key": "mediaingredientmech",
      "root": "/absolute/owned/worktree",
      "head": "FULL_OBSERVED_CONSUMER_COMMIT",
      "branch": "prepare/repository-freshness"
    }
  }
}
```

The placeholders above are documentation, not accepted SHA values. Never
manufacture ownership evidence for a live session checkout. Preparation also
checks live/shared worktree owners through the common host observer, Git
operation markers, exact HEAD/branch, tracked/untracked state and ignored
candidate collisions. Its shared `LockManager` lease is mandatory. It performs
all selected preflights before writes and repeats the checks just before each
transaction; a later race fails nonzero and reports already-prepared targets.

```bash
python -m kg_microbe_governance.freshness_candidates \
  --source-root /absolute/reviewed/claw \
  --source-commit "$REVIEWED_SOURCE_COMMIT" \
  --root-map /absolute/durable/root-map.json \
  --locks-dir /absolute/shared/locks \
  --owner-id freshness-preparation --repository mediaingredientmech
```

Save that dry run. Apply the same command with `--apply`. Source bytes must
exactly match regular Git blobs at the actual full canonical source commit and
the installed builder package. The source may be an unmerged reviewed PR head;
it is labelled `released: false`, never a published release pin. Preparation
writes only `workflow/candidates/repository-freshness-v1/`: policy, schema,
rendered adapter and `proposal.json`. Every proposal is `proposal_only`,
`blocked_on_canonical_release`, `installed: false`, `adopted: false`. Existing
workflow, parent, schema and vendored pin hashes are preserved and read back.
No downstream schema/corpus serialization occurs.

Before fan-out, exercise the real consumer through the shared freshness CLI on
an isolated default base, verify persisted fetched HEAD and inventory bytes,
then create the candidate feature branch and use this same batch preparer.
Re-canary after fixes. The candidate PRs depend on the reviewed canonical merge
and release; neither their merge nor their presence would authorize activation.

## Approval and adoption

An operator must first verify the canonical source is a protected merged
release, review exact payload equality and consumer compatibility, and approve
a specific stopped/assessed initial boundary or verified final closure into a
new cycle. Approval is an immutable local JSON record, pinned by SHA-256 in
operator-owned target configuration (`freshness_adoption.path` and `.sha256`).
The protected release proof is a deployment/operator obligation; a string in
that field does not independently prove GitHub release authority.

The record has exactly these fields:

- `schema_version: "1.0.0"`, `authority: "approved_boundary_adoption"`;
- canonical `repository_key`, `github_repository`, absolute `repository_root`;
- full `canonical_release_commit`, exact packaged `contract_sha256`;
- `boundary`: `run_id`, integral `cycle`, `stage: 1`, the unchanged
  `workflow_sha256`, and exact `predecessor_receipt_sha256` (null only for the
  explicitly assessed initial boundary);
- `approval`: immutable `record_id`, past UTC `approved_at`, `approved_by`.

`load_adoption` rejects proposals, unknown fields, duplicate JSON keys,
symlinks, digest/root/repository/workflow/boundary mismatch and invalid approval
metadata. It reads only. The supervisor must independently prove the actual
native boundary, preserve old workflow/evidence/counters, snapshot this
adoption separately and reject mid-goal activation. Other goals remain
explicitly not adopted until verified. Codex uses the same policy and approved
record through `python -m kg_microbe_workflows.freshness_cli`; see the released
`REPOSITORY_FRESHNESS.md` for strict request and gate-artifact handling.

A live claw control checkout is never an eligible automatic fast-forward.
Its update requires separate reviewed deployment, source-pin refresh, restart,
heartbeat and binding verification. Pre-task freshness instead applies to
owned isolated claw task worktrees.
