# Claw-authoritative vendored governance

The canonical source for general byte-identical Mech artifacts is
`src/kg_microbe_governance/`. The package contains one strict manifest, the
canonical payload bytes, a provenance-verifying synchronizer, and the
standalone checker that each Mech vendors. Domain schemas, provider profiles,
prompts, adapters, and data remain owned by their Mech.

The claw repository is public. Public status was reverified on 2026-08-25, so
public Mech CI can read a pinned raw GitHub revision without credentials.

## Authority contract

`src/kg_microbe_governance/vendored_artifacts.json` is the only artifact list.
Every row declares:

- a stable artifact identifier;
- its canonical claw path and consumer-relative target path;
- all-five or capability-scoped applicability;
- a SHA-256 digest; and
- the Git owner-executable-bit contract and safe write permissions.

The manifest's five consumer identities and package paths are checked against
`src/kg_microbe_fleet/fleet.yaml`. Edison capture is checked against the
`edison_key_discovery` capability rather than an independent repository list.
Unsafe paths, duplicate JSON keys, duplicate expanded targets, unknown
consumers, missing package resources, and checksum drift are rejected.

Each Mech stores one full 40-character claw commit in
`scripts/.vendored_canon_ref`. The vendored checker downloads the manifest and
payloads from exactly that revision, validates manifest checksums, then compares
the local paths byte-for-byte, checks their owner-executable bits, and rejects
group/other-writable governed files and pins. It also
requires the exact Git worktree root and verifies every origin fetch and push
URL against the selected consumer. A branch name, tag, abbreviated SHA,
multiple-line pin, or Mech repository as authority is not accepted. Claw never
pins itself.

## Synchronizing a Mech

Run the installed command from claw. It validates that `--target-root` is the
exact Git worktree root and that its `origin` matches the selected manifest
consumer. Before planning or writing, it fetches the manifest and every payload
from the supplied immutable claw revision and requires those bytes to match the
installed package. A typo, nonexistent commit, or package/ref mismatch is
therefore rejected before the target changes. These bounded public-GitHub
fetches use no model, research provider, credential, or paid API. Dry-run is the
default:

```bash
uv run kg-microbe-governance sync \
  --repository traitmech \
  --target-root /path/to/TraitMech-worktree \
  --ref <full-claw-commit>
```

Review the `WOULD_WRITE` rows, then explicitly apply the same plan:

```bash
uv run kg-microbe-governance sync \
  --repository traitmech \
  --target-root /path/to/TraitMech-worktree \
  --ref <full-claw-commit> \
  --apply
```

Apply mode also requires a clean target worktree. It serializes cooperating
writers with a stable lock in Git metadata, replans under that lock, snapshots
every changed target, stages the entire set beside its destinations, and creates
rollback anchors before the first promotion. Promotions use same-directory
atomic operations, fsync, and set-wide post-write verification; ordinary
exceptions and interrupts restore the prior bytes, modes, and inodes and remove
directories created by the transaction. If a non-cooperating process writes
third-party bytes observed during recovery, those bytes and the rollback anchor
are preserved and the command reports incomplete recovery rather than
overwriting them. Governed paths hidden by Git ignore rules, pre-existing untracked targets,
Git-environment routing overrides, and unsupported safe-dirfd/flock platforms
are rejected. The command never deletes unmanaged files.

Once every promoted target passes exact post-write verification, the operation
has reached its commit point. Rollback anchors are then cleanup debris, so a
cleanup error is reported as an already-committed synchronization and never
triggers an impossible partial rollback. A locked snapshot plus a second Git
preflight binds preparation to the state used for the apply plan; a target that
appears after that snapshot is preserved and rejected.

POSIX cannot make fifteen paths simultaneously visible or stop an editor that
ignores the advisory lock in a final compare/rename interval, including during
promotion or rollback. Such a writer can win the narrow interval after the last
observable comparison. Run apply only in the dedicated clean worktrees required
by this rollout. The implementation detects observed pre-promotion and recovery
changes, uses no-clobber creation for formerly absent targets, and provides
strong rollback for cooperating callers; crash- or power-loss recovery would
require a durable journal and is not claimed here.
`check` is read-only and returns nonzero on drift:

```bash
uv run kg-microbe-governance check \
  --repository traitmech \
  --target-root /path/to/TraitMech-worktree \
  --ref <full-claw-commit>
```

Inside a Mech, CI may continue invoking the thin launcher:

```bash
bash scripts/check_vendored_sync.sh
```

That launcher is the only supported executable entry point. The Python payload
is deliberately non-executable, and the launcher runs it in Python isolated mode
so sibling files cannot shadow standard-library imports. Fetch failures
remain retryable exit 1 results for compatibility with the existing Mech retry
workflows; local pin/identity/manifest precondition failures use exit 2. Tests
replace its fetch function with local fixtures, so the test suite is offline and
no provider, model, credential, or paid API is involved.

Each public fetch has a five-second total deadline and an 8 MiB response cap.
The largest consumer performs one manifest plus fourteen artifact fetches, so
three worst-case attempts plus the existing two five-second retry delays remain
within a five-minute workflow timeout (235 seconds before runner overhead).

## Phase 1 coordinated rollout

Authority cannot be flipped in one commit because downstream repositories need
an already-public immutable claw revision to pin. The fleet manifest therefore
models two fail-closed states:

1. `transition`: claw publishes canonical bytes while CultureMech remains the
   temporary legacy comparison hub for consumers not yet migrated.
2. `authoritative`: all five Mechs are consumers of claw, no Mech hub exists,
   and `legacy_hub` is forbidden.

The rollout order is:

1. Merge and review the claw bootstrap commit.
2. Record its full merge commit SHA.
3. Create clean worktrees from each Mech's current `origin/main`.
4. Run the synchronizer with that exact SHA for all five Mechs, including
   CultureMech; update each workflow/contract so the complete manifest set and
   pin are gating.
5. Merge the five downstream PRs only after their offline and schema tests pass.
6. Fetch each downstream `origin/main`, check out clean worktrees at those exact
   remote-tracking commits, then run the claw fleet audit against the reviewed
   bootstrap SHA. Require missing-file, byte-drift, safe mode, identity,
   applicability, committed-HEAD, and pin checks to pass:

   ```bash
   uv run kg-microbe-governance fleet-audit \
     --ref <full-bootstrap-claw-commit> \
     --target-root culturemech=/path/to/CultureMech-worktree \
     --target-root mediaingredientmech=/path/to/MediaIngredientMech-worktree \
     --target-root communitymech=/path/to/CommunityMech-worktree \
     --target-root traitmech=/path/to/TraitMech-worktree \
     --target-root proteintraitsmech=/path/to/ProteinTraitsMech-worktree
   ```

   The audit requires exactly the five manifest keys, distinct exact Git roots,
   clean trees, `HEAD == refs/remotes/origin/main`, the same expected pin in all
   five, and a successful pinned checker for every capability-scoped artifact.
   It binds the bootstrap ref byte-for-byte to the installed claw manifest and
   payloads, then reads every governed artifact and pin directly from each
   repository's `HEAD` tree (including Git executable modes); ignored files and
   `skip-worktree` flags therefore cannot substitute working-tree bytes.
7. Before deleting compatibility mirrors, complete and review this executable
   migration checklist:
   - repoint the `kg_microbe_history` default/help path, `shared.history`
     package-data declaration, history tests/workflow, and history docs;
   - preserve an equivalent canonical ID-label behavioral job, then repoint its
     working directory plus the Pytest/Ruff exclusions and
     `scripts/audit_idlabel_fleet.sh`;
   - replace the transitional mirror-byte test and
     `tests/test_fleet_governance_mirror.py` contract;
   - account for every file under `shared/history`, `shared/idlabel`, and
     `shared/spoke`, plus the root operational copies of
     `tests/test_skill_frontmatter.py` and `prompts/backlog-loop-goal.md`; and
   - add a no-reference/no-reintroduction guard for all retired paths.
8. Merge the final claw flip to `authoritative`, remove the compatibility
   mirrors and CultureMech-hub audit, and reject their reintroduction.

The legacy checker launcher is excluded from the compatibility mirror during
this window. Its replacement intentionally has different bytes, so comparing
it to the old CultureMech launcher would make every incremental rollout order
fail. Existing consumers continue enforcing their old pin until migrated; the
new five-Mech pin audit is the gate for the replacement before the final flip.

The downstream PRs include companion changes beyond generated bytes:

| Mech | Required rollout companion |
|---|---|
| CultureMech | Add the claw-consumer vendored gate and replace the legacy static checker contract. |
| MediaIngredientMech | Update vendored workflow authority text while preserving exit-1 retry and exit-2 precondition semantics. |
| CommunityMech | Update vendored workflow authority text while preserving exit-1 retry and exit-2 precondition semantics. |
| TraitMech | Update vendored workflow authority text while preserving exit-1 retry and exit-2 precondition semantics. |
| ProteinTraitsMech | Replace the old shell `FILES`/`MAPPED` parser contract and add retry semantics to its combined workflow. |

Do not update canonical payload wording while changing authority. The bootstrap
uses the already-converged bytes so the migration is behavior-neutral. A later
pinned release can evolve a shared contract through the same rollout rail.
Consequently, some copied schema comments still name the old three/four-Mech or
private-hub context; that is recorded compatibility debt, not current authority
documentation, and changing it belongs in a later all-five pinned release.

## Rollback

Before the final flip, a downstream PR can be reverted to its former
CultureMech pin without changing claw. After the final flip, rollback means
pinning all five Mechs to the previous reviewed claw commit; do not reinstate a
Mech authority or use a mutable branch. The canonical bytes remain recoverable
from every reviewed claw commit.
