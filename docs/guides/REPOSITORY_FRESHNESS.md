# Observed-revision goal entry and commit-sequence freshness

Freshness is an additional enforced boundary gate, not completion authority.
The supervisor invokes the packaged engine before scope/baseline capture and
after independently verifying an actual merged PR. A Codex or other native
runner uses the same engine through the batch command below. Review, evidence,
issue, cleanup and native acceptance gates remain required. No command here
starts a native goal, approves a prompt, merges a PR or adopts a workflow.

The contract is separately versioned at 1.0.0. Existing parents and active
profiles stay pinned. Follow [preparation and adoption](REPOSITORY_FRESHNESS_ADOPTION.md)
first. An unmerged canonical head is valid provenance for an inert candidate;
it is never a release pin. All existing sessions remain unadopted until a
reviewed release and an exact approved boundary record are configured.

## Batch request

Save a JSON list of requests outside the curated checkout. Each request has
exactly these fields (placeholders below must be replaced with verified facts):

```json
[{
  "schema_version": "1.0.0",
  "repository_key": "mediaingredientmech",
  "repository_root": "/absolute/owned/default-base",
  "lock_directory": "/absolute/shared/controller-locks",
  "receipt_directory": "/absolute/durable/goal-freshness",
  "protected_roots": ["/absolute/live/claw-deployment"],
  "adoption": {"path": "/absolute/approved-adoption.json", "sha256": "EXACT_FILE_SHA256"},
  "boundary_id": "UNIQUE_NATIVE_GOAL_OR_STAGE_BOUNDARY",
  "phase": "pre_goal",
  "workflow_sha256": "UNCHANGED_FROZEN_WORKFLOW_SHA256",
  "prior_inventory": null,
  "pull_requests": []
}]
```

The operator-owned adoption reference and shared lock directory are trusted
configuration, not facts inferred from directory names. Every controller must
use the same lock namespace. Protected roots must include the actual live claw
deployment; shared Git metadata with that checkout also returns `deploy_required`.
Do not declare unknown session ownership to be empty. The standalone runner
accepts no exception for another live cwd owner; the supervisor can permit only
its freshly verified idle native session identity. Unavailable or incomplete
ownership observations hold. An isolated independent Git base is the normal
choice when another checkout is owned. A feature branch is never auto-switched.

```bash
python -m kg_microbe_workflows.freshness_cli run --request /absolute/request.json
python -m kg_microbe_workflows.freshness_cli run --request /absolute/request.json --apply
python -m kg_microbe_workflows.freshness_cli verify --request /absolute/request.json
```

The first call is a non-authoritative preview and exits nonzero. Apply fetches
under the repository lease and writes immutable observations. Only `verified`
returns zero. The batch reports every member and exits nonzero if any holds.
Before inventory is read, persisted HEAD and the remote default ref are checked
again. The resulting inventory lists tracked paths and Git object IDs at that
exact HEAD. Pass its immutable artifact reference to subsequent goal work.
A repeated boundary reuses the original frozen inventory; it never overwrites
it or silently re-freezes from a newer revision. Verify re-reads the same
artifact and ref without fetching or changing the checkout.

A receipt records repository/root/remote/default branch, before/fetched/after
SHAs, UTC observations, ownership, divergence, retry outcomes and immutable
file/hash references. “Fresh” means the recorded observed revision. A remote
move during observation causes a bounded retry or hold; a move after inventory
freeze holds dispatch and requires a reviewed boundary decision. It does not
reset the goal, evidence, counters or budgets.

## After actual merge

Keep the same boundary and adoption reference. Set `phase` to `post_merge`,
`prior_inventory` to the exact pre-goal artifact `{path, sha256}`, and supply
`pull_requests` as an ordered list of `{number, head_sha, merge_commit_sha}`.
Each member is independently queried on GitHub; an unmerged PR, wrong exact
head, wrong repository/default base or wrong merge SHA holds. The engine then
fetches the current default revision and verifies every actual merge is an
ancestor. A newer external commit must be included too. The emitted
`verified_post_merge_freshness` artifact is an additional closure prerequisite,
not a substitute for ordinary exact-head review, issues, validation or cleanup.

For no-change completion, use `phase: no_change`, the same prior inventory,
and an empty PR list. It verifies the original persisted HEAD and remote ref;
there is no invented merge SHA or new baseline. New goals still execute the
pre-goal fetch even when their eventual inventory is empty.

Dirty/staged changes, local-ahead/diverged state, detached/feature checkouts,
active Git operations, ignored/untracked overwrite collisions, unknown/shared
owners, wrong remotes and failed fetches hold with a diagnosis. Noncolliding
ignored evidence stays in place. The gate never resets, stashes, cleans,
rebases, force-updates a branch or switches an active branch. Incoming active
workflow profile/parent changes require separate adoption, not code freshness.

The engine reuses the fleet updater's identity and shared lease primitives,
with stricter default-only and ownership rules. It is packaged in the wheel;
it does not import the checkout-only fleet-pull script. A deploy-required hold
on live claw must be resolved by the reviewed deployment/pin/restart/heartbeat
procedure, never by weakening the protected-root list.
