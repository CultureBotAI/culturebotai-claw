# Repository freshness 1.0.0 release

The committed declaration is
`src/kg_microbe_governance/releases/repository-freshness-v1.0.0.json`.
It names `repository-freshness-v1.0.0`, contract `repository-freshness` version
`1.0.0`, and source PR #1128. The package version remains distinct. The user
authorized this feature's reviewed PR and release; this procedure adds no
second approval barrier. Every other PR still requires its own merge approval.

This releases the shared mechanism and governed supervisor contract. It neither
installs it nor adopts it for any active goal. Native standalone Codex hooks
remain a separate integration with their own review and adoption requirements.

## Reviewed source, without a self-referential commit

Before queuing #1128 alone, retain independent exact-head and current-main
integration review, the complete expected merge-tree SHA and integration base,
passing required checks, and an empty queue observation. Follow
[merge queues](MERGE_QUEUES.md); never bypass checks or stack unrelated work.
If the queue uses a different base, re-review that exact integration tree before
release. A merged PR is insufficient if the actual tree differs.

After actual merge, retain the GitHub PR mapping and queue/check receipts. Fetch
the exact objects into an owned isolated audit checkout, never the live control
deployment. The local object store must identify the canonical GitHub origin.
Wait for protected-main integrity verification, then run from the reviewed
implementation (variables come from that retained evidence):

```bash
uv run python -m kg_microbe_workflows.freshness_release \
  --root "$AUDIT_CHECKOUT" --reviewed-head "$REVIEWED_HEAD" \
  --merge-commit "$ACTUAL_MERGE" --reviewed-base "$REVIEWED_BASE" \
  --reviewed-tree "$REVIEWED_TREE" --output "$EVIDENCE/release-audit.json"
```

The command reads only existing Git objects and GitHub. It requires exact merged
PR identity, protected main first-parent inclusion, the reviewed squash parent
and complete tree, successful required checks and main integrity, and the same
declaration at the reviewed head and merge. It hashes the feature payloads and
packaged manifest/loader. The complete tree binds all transitive source files.
It refuses edited/reintroduced release declarations and unexpected file modes.
It never tags, publishes, fetches, updates checkouts, edits pins or adopts a goal.
The output is exclusively created. Keep its original bytes; never overwrite an
audit after an observation changes. Re-observe under a new evidence directory.

The reviewed head/base/tree arguments are a trusted operator review boundary,
not cryptographic proof that a review happened. Retain the independent review
and exact-head checks alongside the audit. Public audit output contains no local
paths, session identities, private fleet evidence or free-text runtime content.

## Publish and read back

1. Re-read both the exact tag ref and release by tag. Only an explicit HTTP 404
   means absent; authentication, rate-limit or network errors hold publication.
   An existing tag or release is a collision: stop, never move or overwrite it.
2. Save the exact tag-ref request before submitting it:
   `{"ref":"refs/tags/repository-freshness-v1.0.0","sha":"ACTUAL_MERGE"}`.
   Create it with `gh api --method POST repos/CultureBotAI/culturebotai-claw/git/refs
   --input "$EVIDENCE/tag-request.json"`. Creation is atomic; a collision fails.
   Read it back and require its commit SHA to equal the audited source.
3. Publish the release, retaining the command/result and prepared public notes:

   ```bash
   gh release create repository-freshness-v1.0.0 \
     --repo CultureBotAI/culturebotai-claw --verify-tag \
     --target "$ACTUAL_MERGE" --title 'Repository freshness 1.0.0' \
     --notes-file "$EVIDENCE/release-notes.md" "$EVIDENCE/release-audit.json"
   ```

4. From the reviewed package, call `freshness_release.verify_publication` with
   the original parsed audit. It checks the tag's actual peeled commit, published
   metadata, and the uploaded audit's exact digest/size, then re-reads the ref.
   Save this separate readback. Also read the release notes and asset back to
   verify the intended public content. A release name or `target_commitish`
   string alone is not source proof.

No tag protection or release immutability is presumed. The audit explicitly says
so; the readback records the release's observed immutable flag. Consumers bind
the verified full source commit and exact payload hashes, never a moving tag.
The readback is a timestamped observation, not perpetual equality.

If a tag was created but release publication fails, retain the tag and evidence
and report the partial result; do not overwrite or silently retry publication.
If readback contradicts the source, hold all installation/adoption and report it.
Do not delete a published artifact to disguise a failed verification.

## Consumer dependencies and recovery

Refresh the published fleet through its exact loader and manifest at release
time. Existing proposal-only candidates keep their true source identities. Prove
payload equality to the released source or prepare reviewed updated candidates;
never relabel unmerged source as a release. New members need their own coverage.

Consumer merges, deployment and boundary adoption are separate decisions.
Runtime `canonical_release_commit` must name the actual verified protected
merge, and the approved effective workflow snapshot must be complete. The live
claw deployment still needs reviewed pins, restart and heartbeat verification;
this release does not move it. Existing active workflow identities, evidence and
budgets stay frozen. Recovery before adoption is to leave consumers unchanged.
An adopted runtime requires its documented boundary/deployment rollback, never
retagging this source or rewriting prior receipts.
