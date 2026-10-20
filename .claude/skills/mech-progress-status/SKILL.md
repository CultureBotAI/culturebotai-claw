---
name: mech-progress-status
description: "Report tracked Mech sequence progress in one line: Mechs, distinct PRs by state, completed goals, and completed six-goal cycles. Use for a progress summary or round counts, rather than a full open-PR inventory."
metadata:
  tags: [fleet, progress, reporting, read-only]
---

# Mech progress status

From the CLAW repository root, run:

```bash
uv run python scripts/mech_progress_status.py
```

`just mech-progress` is the same command. To read the published tracker data
through authenticated `gh` instead of the local publisher bundle:

```bash
uv run python scripts/mech_progress_status.py --published
```

Return the command's stdout unchanged. Here `N` represents the tracked fleet size:

```text
N Mechs, 8 PRs (5 merged, 3 open), 1 completed goal, 0 completed cycles
```

Use newly read values, never this example or a previous response. The command
validates the history and snapshot together; its validator uses
`load_fleet_manifest` to require the complete canonical fleet. Counts cover explicitly tracked
activity; earlier history remains unknown. PRs are distinct repository/number
pairs, goals require verified closure, and a cycle requires all six goals.
Closed PRs that were not merged appear separately when present.

For a tracker running a pinned release, the command uses its bundle-adjacent
`fleet.yaml` when present, or an explicit `--manifest PATH`; otherwise it uses
the checkout's packaged manifest. A mismatch is an error. Do not remove a pin
or edit the active fleet configuration to force counts through validation.

Exit 0 means fresh observations. Exit 3 still prints verified counts but reports
stale, missing, or future-dated observations on stderr: retain that qualification
after the summary. Exit 1 means unavailable or invalid evidence; report the error
without inventing counts. Exit 2 means invalid arguments.

This is read-only. Reporting does not refresh the collector, approve prompts,
advance goals, or change PRs. See [progress accounting](../../../docs/guides/MECH_PROGRESS.md)
for the tracking and publication contract.
