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

## Phase 1 rollout record

Phase 1 completed through a two-commit claw migration because public downstream
CI needed an already-merged immutable claw revision before claw could retire the
old comparison layout. The reviewed bootstrap is pull request
[`#133`](https://github.com/CultureBotAI/culturebotai-claw/pull/133), merge commit
`a8f7c94d8d5ccfa0ed430e4d3c5d0dbf63af2416`.

All five downstream migrations passed their repository CI and were merged:

| Mech | Pull request | Audited `origin/main` |
|---|---:|---|
| CultureMech | [#340](https://github.com/CultureBotAI/CultureMech/pull/340) | `0422968004b99c91ed356d6ee4e38b7e93f371d5` |
| MediaIngredientMech | [#472](https://github.com/CultureBotAI/MediaIngredientMech/pull/472) | `82694054f5bbf74b5392bf8858c9962c2152a35a` |
| CommunityMech | [#683](https://github.com/CultureBotAI/CommunityMech/pull/683) | `ba596731b23b799f4baca96984ceb8f0d56874fe` |
| TraitMech | [#516](https://github.com/CultureBotAI/TraitMech/pull/516) | `3ee94eeec831d98d2a2cc1ebe2368fe3fa122f69` |
| ProteinTraitsMech | [#564](https://github.com/CultureBotAI/proteintraitsmech/pull/564) | `a70ff8f5564b77a50963daafaacc2dde013eb1a2` |

An audited SHA can be newer than the rollout PR when unrelated work reached
`main` afterward; the audit binds the current committed tip, not merely the
rollout merge.

Immediately before the authoritative flip, each detached audit worktree was
clean, had `HEAD == refs/remotes/origin/main`, and contained the full bootstrap
pin. One five-root audit then reported 14 matching artifacts for CultureMech,
MediaIngredientMech, CommunityMech, and TraitMech; ProteinTraitsMech correctly
reported its 13 applicable artifacts because Edison capture is not applicable.

`.github/workflows/governance-fleet-audit.yaml` preserves that central check
after the flip. It runs daily and on every claw pull request and main push,
sparse-checks out the public Mech mains derived from the trusted claw manifest,
and reads every pin from its committed tree. All pins must be identical and the
commit must be reachable from the exact trusted claw base/main revision before
the fleet audit runs. The job installs its governance package from that trusted
revision first so it can derive the consumers and paths; the downstream pin
supplies canonical data, never executable acceptance logic. On pull requests, a
separate candidate-validation step checks the proposed authority layout and
workflow contract while the deployed-fleet audit remains bound to the protected
base revision.

The final claw state is `authoritative`: all five Mechs are consumers, no Mech
hub exists, and `legacy_hub` is forbidden. The compatibility mirrors, duplicate
root contracts, and CultureMech-hub audit were removed only after the fleet
audit passed. Claw's maintained history CLI and ID-label behavioral workflow now
consume the packaged canonical assets directly, and tests reject operational
references that would reintroduce the retired layout.

The audit command remains the release gate for future canonical revisions:

```bash
uv run kg-microbe-governance fleet-audit \
  --ref <full-claw-commit> \
  --target-root culturemech=/path/to/CultureMech-worktree \
  --target-root mediaingredientmech=/path/to/MediaIngredientMech-worktree \
  --target-root communitymech=/path/to/CommunityMech-worktree \
  --target-root traitmech=/path/to/TraitMech-worktree \
  --target-root proteintraitsmech=/path/to/ProteinTraitsMech-worktree
```

It requires exactly the five manifest keys, distinct exact Git roots, clean
trees, `HEAD == refs/remotes/origin/main`, one expected pin, and successful
checks for every applicable artifact. It reads bytes and executable modes from
each repository's committed `HEAD`, so ignored files and `skip-worktree` flags
cannot substitute working-tree state.

Do not change canonical payload bytes as part of an authority-only migration.
A later pinned release can evolve a shared contract through the same bootstrap,
downstream rollout, exact-main audit, and final-state sequence. Some current
payload comments retain historical fleet wording; changing those bytes requires
that separate coordinated release.

## Rollback

Rollback means pinning all five Mechs to the previous reviewed claw commit; do
not reinstate a Mech authority or use a mutable branch. The canonical bytes
remain recoverable from every reviewed claw commit.
