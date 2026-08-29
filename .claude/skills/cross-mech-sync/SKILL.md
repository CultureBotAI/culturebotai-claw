---
name: cross-mech-sync
description: Propagate a change, fix, vendored file, or invariant across the manifest-defined Mech fleet safely and completely — query applicable repositories from kg_microbe_fleet, establish ground truth from origin/main, sync via isolated git worktrees, verify, PR+merge, and keep tracking artifacts aligned. NOT for the domain data-pipeline sync (identifiers/CHEBI/KG matches) — that's cross-repo-sync.
category: integration
requires_database: false
requires_internet: true
version: 1.0.0
tags: [sync, cross-repo, cross-mech, fleet, vendored, byte-identical, worktree, pin, invariant]
reference-root: mech
---

# Cross-Mech Sync Skill

## Overview

A repeatable, **non-disruptive** procedure for landing the same change across the
Mech repos and leaving every copy + tracking artifact consistent. Use it whenever
a change must exist in more than one Mech, including:

- A **shared vendored file** that must stay byte-identical (for example, the
  ID↔label validator, helpers, and behavioral tests declared by claw's canonical
  governance manifest).
- A **data correction that fans out** — a wrong value in a source repo that also
  lives in derived artifacts (HTML pages, UMAP, SSSOM) and downstream repos
  (e.g. the boric-acid `CHEBI:33134`→`CHEBI:33118` fix: CultureMech YAML → MIM
  unified TSV → kg-microbe reviewed TSV + unified SSSOM + regenerated HTML/UMAP).
- A **convention/invariant** (a justfile recipe, a CI guard, a `NEXT_TASKS.md`).

For the standard *data-pipeline* sync (unified mapping, CHEBI backfill, KG-node
matches) use **`cross-repo-sync`** instead — that's a different job.

## The repositories

Never type a repository list into the procedure. Resolve the current identity,
display name, and root environment variable from the packaged manifest:

```bash
uv run python -m kg_microbe_fleet list --format tsv
# key<TAB>display_name<TAB>owner/repository<TAB>ROOT_ENVIRONMENT_VARIABLE
```

Use `--capability <name>` whenever the artifact is capability-scoped. An empty
or unknown capability is an error, not permission to fall back to a remembered
list. Repositories outside this output are downstream systems, not implicit
fleet members, and require an explicit task-specific decision.

```bash
uv run python -m kg_microbe_fleet list --capability <CAPABILITY> --format tsv
```

`list` is for declarative inventory. Before reading from or writing to local
checkout paths, use `targets --capability <CAPABILITY>` instead; it emits the
same four identity fields plus an identity-validated absolute root (or an empty
root for an unconfigured Mech) and fails before output on any Git mismatch.

This workflow fetches immutable Git objects and opens, checks, and merges GitHub
PRs, so `requires_internet: true` is intentional. A local inventory can be
prepared offline, but it is not a completed cross-Mech sync.

## The five rules (learned the hard way)

1. **Ground truth = `origin/main`, never the working copy or NEXT_TASKS notes.**
   Working trees sit on other agents' feature branches; `NEXT_TASKS.md` entries
   drift from reality (one claimed "CommunityMech has no validator copy" long
   after it had been vendored). Read the real bytes:
   `git show origin/main:<path> | shasum -a 256`.

2. **Never switch a repo's branch to commit.** Repos routinely have concurrent
   agents mid-work (uncommitted tracked changes). Commit through an **isolated
   git worktree off `origin/main`** (see Workflow). Switching/​stashing their
   branch is the one thing that can wreck another agent's session.

3. **Use the declared authority.** For a claw-governed artifact, canonical bytes
   come only from `src/kg_microbe_governance/vendored_artifacts.json` at the full
   commit in `scripts/.vendored_canon_ref`; consumer majority is evidence of
   deployment state, never authority. For an unmanaged convention, establish
   ground truth explicitly before choosing a version. Never average or re-derive
   byte-governed content.

4. **Sync is incomplete until the derived artifacts are too.** A source fix that
   leaves stale HTML/UMAP/SSSOM is a half-fix. After the source change, sweep
   every repo for the old value and regenerate (or surgically correct) the
   generated outputs. `grep -rl "<old value>"` across each repo, excluding the
   legitimate cases (e.g. a vendored ontology snapshot where the id is correct).

5. **One coordinated release.** Change canonical payloads and checksums in a
   reviewed claw bootstrap commit, roll that immutable commit pin through every
   applicable Mech, audit the exact committed `origin/main` tips, and only then
   complete any final claw state change. Never edit a consumer copy or invent a
   per-repository pin outside that release rail.

## Workflow

### A. Prepare the validated scope

```bash
CAPABILITY="${CAPABILITY:-}"
TASK_SLUG="${TASK_SLUG:-}"
TARGET_KEY="${TARGET_KEY:-}"
set -euo pipefail
test -n "$CAPABILITY" || { echo "CAPABILITY is required" >&2; exit 2; }
case "$TASK_SLUG" in
  ""|*[!a-z0-9-]*) echo "Invalid task slug: $TASK_SLUG" >&2; exit 2 ;;
esac
ORCHESTRATION_ROOT="$(git rev-parse --show-toplevel)"
test -f "$ORCHESTRATION_ROOT/plugins/lock_manager.py"
AUDIT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cross-mech-audit.XXXXXX")"
FLEET_TSV="$AUDIT_DIR/fleet.tsv"
uv run python -m kg_microbe_fleet targets \
  --capability "$CAPABILITY" > "$FLEET_TSV"
test -s "$FLEET_TSV" || { echo "Capability scope is empty" >&2; exit 2; }

# Declare the exact governed paths as an array; never eval a path string.
PATHS=(<PATHS...>)

```

### B. Define a same-process, bounded metadata-lock runner

Use this shell function only for short shared Git metadata transitions: adding
or removing the registered worktree and deleting its local branch. The Python
process that acquires the lock remains alive while its child command runs,
checks the acquisition result, bounds the child below the lease lifetime,
terminates the child before releasing, and releases its own token in `finally`.

```bash
run_with_repo_lock() {
  resource=$1
  task_limit=$2
  shift 2
  test "$#" -gt 0 || { echo "Missing locked command" >&2; return 2; }

  OPENCLAW_ORCHESTRATION_ROOT="$ORCHESTRATION_ROOT" \
    uv run --project "$ORCHESTRATION_ROOT" python - \
      "$resource" "$task_limit" "$@" <<'PY'
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["OPENCLAW_ORCHESTRATION_ROOT"]).resolve()
sys.path.insert(0, str(root))

from plugins.lock_manager import LockManager

resource = sys.argv[1]
task_limit = int(sys.argv[2])
command = sys.argv[3:]
if not command or not 60 <= task_limit <= 86_400:
    raise SystemExit("invalid command or task limit")


def stop_on_signal(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


for handled_signal in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(handled_signal, stop_on_signal)

manager = LockManager({"my_id": f"cross-mech-sync-{os.getpid()}"})
acquired = manager.acquire_lock(
    resource,
    f"cross-mech-sync:{Path(command[0]).name}",
    timeout=task_limit + 300,
    wait=False,
)
if not acquired:
    raise SystemExit(f"could not acquire repository lock: {resource}")

exit_code = 1
child: subprocess.Popen[bytes] | None = None
try:
    try:
        child = subprocess.Popen(command)
        exit_code = child.wait(timeout=task_limit)
    except subprocess.TimeoutExpired:
        print("locked command exceeded its approved duration", file=sys.stderr)
        exit_code = 124
finally:
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    if not manager.release_lock(resource):
        print("the owned repository lock could not be released", file=sys.stderr)
        exit_code = 70

raise SystemExit(exit_code)
PY
}
```

There is no renewal protocol. Choose an explicit task bound before execution;
the lease is five minutes longer than the maximum child lifetime. Never acquire
and release through separate Python invocations. Never run edits, validation,
commit, or push under this lock: installed hooks treat any active repository
lock as blocking and have no owner-token bypass. A unique branch/worktree—not a
long lease—provides isolation for those operations.

### C. Establish ground truth under short metadata locks

Refresh each exact `origin/main` ref under the bounded metadata lock before
reading it. The lock is released before hashing and no hook-bearing edit or
commit runs beneath it.

```bash
while IFS=$'\t' read -r key name github root_variable repo_root; do
  test -n "$repo_root" || { echo "UNCONFIGURED: $key ($root_variable)" >&2; exit 2; }
  run_with_repo_lock "$key" 300 \
    git -C "$repo_root" fetch origin \
      refs/heads/main:refs/remotes/origin/main
  for f in "${PATHS[@]}"; do
    if ! git -C "$repo_root" cat-file -e "origin/main:$f"; then
      echo "Missing Git object: $github origin/main:$f" >&2
      exit 2
    fi
    if ! h="$(git -C "$repo_root" show "origin/main:$f" \
      | shasum -a 256 | awk '{print $1}')"; then
      echo "Could not hash: $github origin/main:$f" >&2
      exit 2
    fi
    echo "$name  ${h:0:16}  $f"
  done
done < "$FLEET_TSV"
```

Group by hash to identify deployed drift and its scope. For a governed path,
resolve the expected source, digest, applicability, and target from
`src/kg_microbe_governance/vendored_artifacts.json` at the reviewed claw pin;
do not promote the majority consumer hash to canonical. For an unmanaged path,
review the diffs and document the chosen ground truth before overwriting.
Because `set -o pipefail` is active and each object is checked with `cat-file`,
a failed fleet query, locked fetch, or missing path aborts instead of hashing
empty input.

### D. Make the change in an isolated worktree (per laggard repo)

```bash
# Resolve exactly one target from the already validated capability output.
target_row="$(awk -F '\t' -v key="$TARGET_KEY" '$1 == key' "$FLEET_TSV")"
test -n "$target_row" || { echo "Target is outside capability scope" >&2; exit 2; }
IFS=$'\t' read -r TARGET_KEY TARGET_NAME TARGET_GITHUB TARGET_ROOT_VARIABLE \
  REPO <<< "$target_row"
test -n "$REPO" || { echo "Set $TARGET_ROOT_VARIABLE" >&2; exit 2; }
case "$TARGET_GITHUB" in
  */*) ;;
  *) echo "Invalid owner/repository identity: $TARGET_GITHUB" >&2; exit 2 ;;
esac

SYNC_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cross-mech-${TARGET_KEY}.XXXXXX")"
WT="$SYNC_DIR/worktree"
OPERATION_SCRIPT="$SYNC_DIR/apply-reviewed-change.sh"
PR_BODY_FILE="$SYNC_DIR/pr-body.md"
SYNC_ID="${SYNC_DIR##*.}"
BRANCH="feat/$TASK_SLUG-$SYNC_ID"
git check-ref-format "refs/heads/$BRANCH"
touch "$OPERATION_SCRIPT"
chmod 700 "$OPERATION_SCRIPT"
"${EDITOR:?Set EDITOR to write the reviewed operation}" "$OPERATION_SCRIPT"
test -s "$OPERATION_SCRIPT" || { echo "Operation script is empty" >&2; exit 2; }
touch "$PR_BODY_FILE"
chmod 600 "$PR_BODY_FILE"
"${EDITOR:?Set EDITOR to write the PR body}" "$PR_BODY_FILE"
test -s "$PR_BODY_FILE" || { echo "PR body is empty" >&2; exit 2; }

# This short shared metadata transition is lock-owned. It completes and
# releases before any worker edit or hook can run.
run_with_repo_lock "$TARGET_KEY" 300 \
  git -C "$REPO" fetch origin \
    refs/heads/main:refs/remotes/origin/main
run_with_repo_lock "$TARGET_KEY" 300 \
  git -C "$REPO" worktree add -b "$BRANCH" "$WT" origin/main
BASE_SHA="$(git -C "$WT" rev-parse HEAD)"
test "$BASE_SHA" = "$(git -C "$REPO" rev-parse origin/main)"
```

The operation file must start with `set -euo pipefail`, take `WT` and `BRANCH`
as positional arguments, apply only the reviewed change, validate, commit, and
push the unique branch. It must not contain `eval`, interpolated user prose, a
remembered repository path, or a worktree deletion. Execute it only after the
metadata lease above has been released:

```bash
bash "$OPERATION_SCRIPT" "$WT" "$BRANCH"
```

If the command fails, preserve the unique worktree and report its exact path for
recovery. Do not remove it automatically. After a successful push, use the
manifest's `owner/repository` identity—not its display name or basename:

```bash
gh pr create -R "$TARGET_GITHUB" --base main --head "$BRANCH" \
  --title "<reviewed title>" --body-file "$PR_BODY_FILE"
PR_NUMBER="$(gh pr view -R "$TARGET_GITHUB" "$BRANCH" \
  --json number --jq .number)"
case "$PR_NUMBER" in
  ""|*[!0-9]*) echo "Could not resolve the created PR number" >&2; exit 2 ;;
esac
```

### E. Verify before merge

- Governed artifacts, when in scope:
  `bash scripts/check_vendored_sync.sh` → every applicable artifact and the
  immutable claw pin are current. Also run the trusted claw command against the
  exact worktree and pin when coordinating a canonical release:
  `kg-microbe-governance check --repository <key> --target-root <worktree> --ref <full-sha>`.
- Tests: `uv run pytest <the synced tests> -q`.
- CI: `gh pr view "$PR_NUMBER" -R "$TARGET_GITHUB" --json mergeable,mergeStateStatus,statusCheckRollup`
  → `MERGEABLE` / `CLEAN` and checks `SUCCESS`.
- Scope: `gh pr view "$PR_NUMBER" -R "$TARGET_GITHUB" --json files` — confirm no stray files.

Immediately before merge, close the concurrent-update window as far as local
automation can: refresh `origin/main`, verify it is an ancestor of the exact
pushed head, require GitHub checks to pass, and re-check mergeability. If `main`
advanced, rebase only this unique branch, rerun validation and CI, and repeat
review as required.

```bash
run_with_repo_lock "$TARGET_KEY" 300 \
  git -C "$WT" fetch origin \
    refs/heads/main:refs/remotes/origin/main

if ! git -C "$WT" merge-base --is-ancestor origin/main HEAD; then
  echo "origin/main advanced; rebase and rerun validation/CI" >&2
  exit 2
fi
local_head="$(git -C "$WT" rev-parse HEAD)"
remote_head="$(git -C "$REPO" ls-remote origin "refs/heads/$BRANCH" \
  | awk 'NR == 1 {print $1}')"
test -n "$remote_head"
test "$local_head" = "$remote_head"
gh pr checks -R "$TARGET_GITHUB" "$PR_NUMBER"
pr_gate="$(gh pr view -R "$TARGET_GITHUB" "$PR_NUMBER" \
  --json baseRefName,headRefName,headRefOid,headRepository,mergeable,mergeStateStatus \
  --jq '[.baseRefName,.headRefName,.headRefOid,.headRepository.nameWithOwner,.mergeable,.mergeStateStatus] | @tsv')"
IFS=$'\t' read -r pr_base pr_branch pr_head pr_head_repo pr_mergeable pr_merge_state \
  <<< "$pr_gate"
test "$pr_base" = "main"
test "$pr_branch" = "$BRANCH"
test "$pr_head" = "$local_head"
test "$pr_head_repo" = "$TARGET_GITHUB"
test "$pr_mergeable:$pr_merge_state" = "MERGEABLE:CLEAN"
```

### F. Merge + clean up

```bash
gh pr merge "$PR_NUMBER" -R "$TARGET_GITHUB" --squash --delete-branch \
  --match-head-commit "$local_head"
merged_gate="$(gh pr view -R "$TARGET_GITHUB" "$PR_NUMBER" \
  --json state,baseRefName,headRefName,headRefOid,headRepository \
  --jq '[.state,.baseRefName,.headRefName,.headRefOid,.headRepository.nameWithOwner] | @tsv')"
IFS=$'\t' read -r merged_state merged_base merged_branch merged_head merged_head_repo \
  <<< "$merged_gate"
test "$merged_state" = "MERGED"
test "$merged_base" = "main"
test "$merged_branch" = "$BRANCH"
test "$merged_head" = "$local_head"
test "$merged_head_repo" = "$TARGET_GITHUB"
# Verify the remote branch is absent. Status 2 means no matching ref; any other
# result either found the branch or failed to query the remote.
if git -C "$REPO" ls-remote --exit-code --heads origin "$BRANCH"; then
  echo "Remote branch still exists: $BRANCH" >&2
  exit 2
else
  remote_status=$?
  test "$remote_status" -eq 2 || exit "$remote_status"
fi

# Refuse cleanup if validation or the operation left uncommitted state. The
# unique mktemp path proves this is this run's worktree; removal is never forced.
test -z "$(git -C "$WT" status --porcelain)"
test "$(git -C "$WT" rev-parse HEAD)" = "$local_head"
run_with_repo_lock "$TARGET_KEY" 300 \
  git -C "$REPO" worktree remove "$WT"
run_with_repo_lock "$TARGET_KEY" 300 \
  git -C "$REPO" update-ref -d "refs/heads/$BRANCH" "$local_head"
rm -- "$OPERATION_SCRIPT" "$PR_BODY_FILE"
rmdir "$SYNC_DIR"
```

If cleanup refuses, stop and inspect. Never delete a registered or dirty
worktree merely because its path resembles an older run. The exact-old-SHA
`update-ref` deletes a reviewed unique local branch even after a squash merge,
but refuses if that ref moved after review.

### G. Keep declared bookkeeping in sync

- Update only tracking artifacts explicitly declared by the governing manifest
  or named in the task. Do not introduce or mutate a `NEXT_TASKS.md` merely
  because another Mech happens to carry one.
- Comment + close the tracking issue (often in `culturebotai-claw`); record any
  **decision** made (e.g. "TraitMech deferred — net-new adoption, not a sync").

After every scoped target is complete, remove only the audit file and directory
created by this run:

```bash
rm -- "$FLEET_TSV"
rmdir "$AUDIT_DIR"
```

## The vendored byte-identical invariant (reference)

Claw is the sole authority. Read
`src/kg_microbe_governance/vendored_artifacts.json` to determine the canonical
source, expanded Mech target, applicability, digest, and executable-bit
contract. Each Mech records one full claw commit in
`scripts/.vendored_canon_ref`; no checksum sidecar or Mech-local manifest is an
authority.

Use the installed governance commands from the reviewed claw revision:

```bash
# Dry-run is the default; add --apply only after reviewing every WOULD_WRITE row.
uv run kg-microbe-governance sync \
  --repository <mech-key> \
  --target-root <isolated-worktree> \
  --ref <full-reviewed-claw-sha>

uv run kg-microbe-governance check \
  --repository <mech-key> \
  --target-root <isolated-worktree> \
  --ref <full-reviewed-claw-sha>
```

After all downstream PRs merge, refresh every local `origin/main` and run one
`kg-microbe-governance fleet-audit` with exactly the five manifest keys and the
common full SHA. The audit requires clean exact repository roots, committed
main tips, identical pins, canonical bytes, and Git modes. See
`docs/guides/VENDORED_GOVERNANCE.md` for the bootstrap, rollout, audit, and
rollback sequence.

Repo-specific configuration is governed only when the manifest says so. For
example, `conf/id_label_targets.yaml` remains Mech-owned because it is absent
from the canonical manifest; confirm that from the manifest rather than from
memory.

## Worked examples (this is what "done" looks like)

- **Historical: claw#6 — extend the former ID/label checksum sidecar.** Before
  claw became authoritative, ground-truth showed the validator in sync while
  CommunityMech's tests drifted. The old rollout synchronized the copies and a
  three-line sidecar. That mechanism is retired; the lesson that behavioral
  contracts must travel with their implementation remains, but all new changes
  use the claw manifest, full commit pin, synchronizer, and fleet audit above.
- **Boric-acid `CHEBI:33134`→`CHEBI:33118`.** One wrong id (1H-phosphole, not boric
  acid) spanned 4 surfaces: CultureMech YAML (source) → MIM unified TSV →
  kg-microbe reviewed TSV + unified SSSOM (surgical row removal — the generator
  *seeds from its own output*, so a re-run wouldn't purge it) → regenerated
  CultureMech HTML/UMAP. Left the vendored ChEBI ontology snapshot (CultureMech's
  untracked data/kgm/) alone — 33134 = 1H-phosphole is *correct* there. Lesson: trace every surface;
  distinguish the error from legitimate uses of the same id.

## Pitfalls

- **gh `--json files` caps at ~100 entries** — a "100" count on a big regen is the
  page limit, not the true count; check `git show --stat` for the real number.
- **Generators that seed from their own previous output** (kg-microbe's
  `consolidate_chemical_mappings.py`) won't purge a stale entity on a plain re-run
  — surgically remove it, or the bad row survives via union semantics.
- **Deterministic vs. churny generators.** Confirm UMAP/render uses a fixed
  `random_state` before committing a regen, or you commit pure noise. Watch for
  per-output wall-clock timestamps that diff every file (fix the generator, then
  force a clean rebuild).
- **Bare `python` in justfile recipes** fails outside the project env — recipes
  should use `uv run python`.
- **Don't commit unrelated dirty files** the worktree picks up nothing, but the
  live tree may have `uv.lock` / cache churn — stage only the paths you changed.
