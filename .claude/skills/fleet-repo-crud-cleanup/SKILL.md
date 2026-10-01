---
name: fleet-repo-crud-cleanup
description: Inventory and clean repository clutter across one or more Mechs, preserving research data, evidence, published pages, local work, and Git recovery state. Use for Mech cache/build cleanup, disk-space reviews, or merged-branch/worktree housekeeping. Resolves the current fleet, can include explicitly requested new Mechs, and separates read-only inventory from authorized cleanup.
metadata:
  category: cross-repo
  requires_database: false
  requires_internet: true
  version: 1.0.0
  tags: [fleet, cleanup, caches, git, worktrees]
---

# Fleet repository cleanup

Adapted from the `repo-crud-cleanup` workflow used with MicroGrowAgents. Keep its
useful distinction between regenerable clutter, expensive environments, unknown
local work, and protected evidence. A familiar directory name or ignored status
is never proof that its contents are disposable.

This is one shared skill, usable from any Mech. It resolves repositories at run
time; no per-Mech copy or hardcoded fleet list is needed. The bundled helper in
claw's `scripts/repo_crud_inventory.py` is **read-only**, including Git operations.
It produces review candidates, not an executable deletion plan. The source
skill's inventory/apply programs are not dependencies of this adaptation.

## Scope and checkout identity

For an inventory, audit, or skill-adaptation request, collect evidence and report.
For an explicit cleanup request, perform the already authorized actions after
reviewing their concrete paths. Do not ask again for that authorization. Cache
cleanup does not authorize deleting untracked research, dependency environments,
or Git history. Ask only for decisions outside the existing request, after the
inventory makes those decisions concrete. Creating or adapting this skill does
not itself authorize removing repository contents.

Locate claw through `OPENCLAW_ORCHESTRATION_ROOT` or this skill's resolved path
under its checkout. Verify its GitHub origin is CultureBotAI/culturebotai-claw.
Resolve the current published default-branch SHA, record the acquisition time,
and read claw's packaged fleet manifest at that immutable revision. Use its
loader from an isolated checkout of that revision:

```bash
uv run python -m kg_microbe_fleet list --format json
```

The complete manifest is the default denominator for "all Mechs". A capability
filter must not silently omit a repository from a cleanup inventory. Honor
explicit subsets; add claw as a separately named control-plane target only when
requested. A stale local package or an unavailable checkout does not reduce the
denominator. If published discovery fails, label the baseline and coverage
unknown instead of claiming a current complete fleet.

Resolve configured roots using `RepositorySettings.from_environment`, the same
loaded manifest, and `merged_repository_environment` with the explicitly selected
claw dotenv file when needed. Exported variables retain precedence. Call
`get_target(key)` immediately before each inventory; it rechecks Git identity.
Use configuration only to locate roots, never to choose fleet membership. Do not
print dotenv contents or credentials. Do not substitute the current directory
for an unset root or scan a similarly named directory without verifying origin.

When the request includes discovering new Mechs, enumerate the GitHub
organization with pagination and compare exact identities with the pinned
manifest. A name ending in Mech is a candidate, not sufficient evidence: inspect
the README, instructions, package/corpus, and default-branch tree. Record verified
new Mechs as **explicit additional targets**, with their evidence and maturity,
without inventing schema/capability declarations or silently editing the fleet
manifest. Full onboarding is a separate scoped change.

When cloning is authorized, first search configured roots and the established
local checkout directories, including hidden/ignored entries. Verify any found
checkout's origin and exact top level. Clone a missing repository only into a
new, unoccupied destination and verify identity afterward; preserve existing
branches and dirty work. A fresh clone can establish published layout, but it
cannot reveal clutter in an older checkout. Mark its inventory as a fresh clone.
Do not run a pull, switch, reset, stash, or cleanup merely to inspect an existing
checkout. Group linked worktrees by their Git common directory; they share refs.

## Inventory actual local state

Read each target's instructions and the data/build sections of its README. Map
its authoritative records, raw downloads, reference caches, literature, analysis
outputs, history, provenance, schema products, and Pages build/deploy inputs.
Use the current manifest's record/schema paths where available, then verify
actual repository conventions. New Mechs may have none of those contracts yet.
Read [the cleanup decisions](references/cleanup-decisions.md) for classification,
Git housekeeping, and the checks needed before changing anything.

Create a unique audit directory outside every inspected repository. From claw,
run one inventory per exact validated root; pass the corresponding manifest or
explicit-extra GitHub identity, never a guessed name:

```bash
python3 scripts/repo_crud_inventory.py \
  --repo "$TARGET_ROOT" --expected-origin "$TARGET_GITHUB" \
  --json > "$AUDIT_DIR/$TARGET_KEY.json"
```

Inspect the command exit status and each report's completeness and errors.
Timeouts, unreadable paths, traversal bounds, failed Git queries, and sparse
checkouts remain explicit limitations. Never convert a failed inventory into an
empty-success row. Preserve the report when a command returns nonzero and
continue independent targets. Separate repository inventories may run in
parallel; mutations sharing a checkout, common Git directory, or generated
outputs must be serialized.

The helper includes ignored and untracked names without opening their contents.
Protected directory trees can be retained as a whole with an explicit traversal
exclusion and unmeasured size; no absence or byte-count claim applies inside
them. It does not inspect secret values, search references or checksum manifests,
prove a build is reproducible, or determine that a branch was safely merged.
It reports staged Git metadata but leaves unstaged content comparison unmeasured:
a normal Git status can execute a repository-configured content filter. Do not
run filters, hooks, or lazy object fetches merely to complete an inventory.
Metadata fingerprints are change hints, not content identity or deletion
approval. A candidate still needs the semantic review below. Do not run the
original generic apply program against this report.

Before recommending deletion, inspect every selected subtree, including hidden
and ignored descendants, without following symlinks or crossing filesystems.
Check references and checksum/download manifests using a filename-first search
that includes ignored files, then read only non-secret text relevant to the
candidate. Never feed an unrestricted recursive content search through secrets.
Record search exclusions, unreadable files, size caps, and sparse-tree limits;
incomplete evidence means keep pending review. Check the immutable Git tree too
when sparse checkout hides tracked paths. Absence of a reference is supporting
evidence only; it does not establish that a dataset or unique result is worthless.

Prepare a disposition for every reported item: cache candidate, expensive to
rebuild, untracked work, protected, or needs investigation. Retain the helper's
reason and the repository-specific evidence; a report count is not a decision.
For each proposed action record exact root/path, purpose, bytes and whether that
size is complete, rebuild inputs/command, references/pins checked, recovery path,
and authorization scope. Keep held and inaccessible items visible.

## Carry out authorized cleanup

Present the concrete selected actions and preserved items before mutating.
Read [the cleanup decisions](references/cleanup-decisions.md) for the action
checks. Existing authorization applies to its stated scope; do not add a blanket
confirmation gate or interpret silence as permission for extra items.

For every selected item, revalidate repository identity, HEAD, staged/unstaged
state, the exact path and all descendants immediately before acting. Recheck
active operations and ownership of any running writers. Stop for changed
content, new references/protection, an active writer, or incomplete evidence;
re-inventory and carry forward authorization only when the new action still
fits its original scope. A checksum computed during inventory does not protect
against later writes.

Prefer a same-filesystem quarantine for explicitly approved unique or expensive
items. Use a new session outside all checkouts, a collision-free destination,
and a durable action record before moving anything. A quarantine move frees no
space. Restore only to an absent destination after verifying both paths and the
session record; purge only when disposal of that exact session is authorized.
For reviewed regenerable caches, act on one small canary first, verify the
tracked state and kept files, then process the remaining exact selections.
Never expand a deletion to a directory merely because a child was selected.

Use claw's ownership-aware `LockManager` for short shared metadata transitions;
the acquiring process owns the lease through completion and releases in a
`finally` block. Bound the operation below the lease lifetime. Do not hold a
lease across user input or long rebuilds, or run commits/hooks beneath it.
Locks coordinate cooperating agents only; rechecks and ownership evidence still
matter. Never kill another agent or delete a lock to make cleanup proceed.

Do not use repository-wide Git clean, forced worktree removal, stash clearing,
reflog expiration, aggressive object pruning, or directory-wide shell globs as
shortcuts. Remote branch changes require their own explicit scope and verified
PR/head evidence; ordinary local crud cleanup does not authorize them. Preserve
uncertain items and complete independent authorized actions. Honor tool denials
without retrying equivalent blocked actions under different syntax.

Tracked obsolete reports or notes require a normal reviewed change, not a cache
delete. Read them fully, check callers and provenance, and retain useful content
in maintained documentation or explicitly authorized GitHub issues/comments.
Record the destination and verify it exists before deleting the source. Do not
publish private research, credentials, or local logs as a side effect of cleanup.

## Verify and report

Re-inventory affected roots and compare HEAD, tracked/index state, protected
items, and selected paths. Record partial successes and failures independently.
Run relevant existing checks when the change affects behavior; do not trigger a
paid analysis or broad regeneration just to prove a cache can be rebuilt.

Report every selected repository, its exact checkout and baseline, completeness,
proposed versus performed actions, skipped/protected items, quarantine locations,
Git ref recovery information, and validation. If files were deleted, measure
actual free-space change separately from logical file sizes; shared APFS blocks
and concurrent writers can make those numbers differ. Do not count quarantine
moves as reclaimed disk space.

Refresh published fleet membership at closeout and reconcile changes. Keep new
Mechs and unavailable roots explicit. An inventory-only run finishes with a
reviewable action ledger and no claim that cleanup occurred. Save reports under
the task's unique audit directory and link them from the session; publish issue
comments only when the user authorized that external write.
