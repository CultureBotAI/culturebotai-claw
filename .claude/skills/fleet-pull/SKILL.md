---
name: fleet-pull
description: "Preview or pull remote updates across the manifest-defined Mech checkouts. Fast-forward each clean current branch from its existing origin upstream; report dirty, detached, diverged, locked, or unconfigured repositories. Use to update local Mech clones, rather than propagate a shared code change."
metadata:
  category: cross-repo
  requires_database: false
  requires_internet: true
  version: 1.0.1
  tags: [git, pull, fleet, cross-repo]
---

# Fleet pull

Run from the CLAW checkout. `scripts/fleet_pull.py` resolves the fleet through
`src/kg_microbe_fleet/fleet.yaml` and validates configured roots and GitHub origins
through `RepositorySettings`. It loads CLAW's `.env` when present; exported
variables take precedence. Missing roots stay visible in the report.

```bash
just fleet-pull                         # offline preview
just fleet-pull --apply                 # fetch and fast-forward eligible repos
just fleet-pull --mech traitmech --apply # select one; repeat --mech for several
just fleet-pull --json                  # machine-readable preview
```

Equivalent without just:

```bash
uv run python scripts/fleet_pull.py --dry-run
uv run python scripts/fleet_pull.py --apply --json
```

## Execution

For a request to inspect or preview, run the default dry run only. For an
explicit request to pull/update checkouts, run configuration validation and the
preview first, then apply the requested scope. Existing user authorization is
sufficient; do not ask again for the action already requested. Creating this
skill alone does not imply running a live pull.

```bash
uv run openclaw-cli config validate
```

The preview is offline and uses cached remote-tracking refs. A preview's
`up_to_date` means equal to the cached ref, not verified current on GitHub.
`--apply` fetches the existing origin upstream of each eligible current branch
under `LockManager.lock`, then rechecks identity, branch, HEAD, cleanliness and
tracking before merging the fetched commit with `--ff-only`.

An active rebase is detected from its `rebase-merge` or `rebase-apply` state
directory before and after fetch. A standalone `REBASE_HEAD` commit pointer can
remain after a completed rebase; it is preserved and does not by itself block
a pull. Other operation markers and checkout safeguards still apply.

The current branch can be a feature branch. The command does not switch to main
or change upstream configuration. CLAW and kg-microbe are outside this Mech-only
scope. Do not add either implicitly.

## Interpret results

- `updated`: fast-forwarded to the reported fetched commit.
- `would_update`: cached upstream is ahead; preview only.
- `up_to_date`, `ahead`: no local update needed relative to the compared ref.
- `skipped_*`: dirty/untracked/submodule changes, detached HEAD, missing or
  non-origin/symbolic tracking, diverged history, an operation marker, or an unavailable
  lock. Preserve the checkout and report the reason.
- `not_configured`, `error`: coverage is incomplete; report the affected Mech.

Exit `0` means all selected repositories were assessed successfully. Exit `1`
means at least one was skipped or failed. Exit `2` means invalid invocation or
configuration. JSON includes the full selected denominator and one result per
repository; do not omit skipped repositories from the final summary.

Always finish with a table listing every selected repository, its branch,
result, and commit change or reason. Put successfully updated repositories
first, then all repositories that were not updated at the end (including
already-current, ahead, skipped, and failed checkouts). Include totals for
updated and not updated. The command's default output uses this order; when
using JSON, arrange the final response table the same way.

## Boundaries

The updater never stashes, resets, rebases, force-updates a local branch, pushes,
prunes, or deletes branches. It refuses to overwrite ignored files newly tracked
upstream. It does not run Git hooks or update submodule worktrees recursively.
An apply may update remote-tracking refs even if the subsequent working-tree
update is skipped or fails; rerun after inspecting the reported condition.

Fetch, merge, and status subprocess groups share a `--timeout` deadline
(1–300 seconds per repository; default 60), shorter than the repository lock
lease. Local identity validation runs through `RepositorySettings`; if it takes
past the deadline, subsequent Git mutations are refused. Locks coordinate cooperating
CLAW operations; rechecks also catch changes made during fetch by other tools.
On failure, retain user work and report the partial result. Never repair a skipped
checkout by stashing, deleting files, or overriding a lock as part of this skill.

For distributing the same change across repositories, use `cross-mech-sync`.
For branch/PR inventory, use `fleet-branch-status` or `fleet-pr-status`.
