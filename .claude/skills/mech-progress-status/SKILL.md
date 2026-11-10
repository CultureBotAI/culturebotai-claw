---
name: mech-progress-status
description: "Report tracked Mech sequence progress in one line: Mechs, distinct PRs by state, completed goals, and completed versioned cycles. Use for a progress summary or round counts, rather than a full open-PR inventory."
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

When the caller supplies the verified local supervisor runtime, append its
saved per-Mech durability observations with `--durability-runtime PATH`.
Do not guess a runtime, edit its inventory, or start a scan to produce this
report. Missing, stale or incomplete observations remain unknown; unpublished
commits and near-cutoff files are alerts. Preserve those lines and exit-3
qualifications with the progress summary. This optional local view does not
publish private paths or change the public tracker schema. See
[durable session state](../../../docs/guides/SESSION_STATE_DURABILITY.md).

Return the command's stdout unchanged. Here `N` represents the tracked fleet size:

```text
N Mechs, 8 PRs (5 merged, 3 open), 1 completed goal, 0 completed cycles
```

Use newly read values, never this example or a previous response. The command
validates the history and snapshot together; its validator uses
`load_fleet_manifest` to require the complete canonical fleet. Counts cover explicitly tracked
activity; earlier history remains unknown. PRs are distinct repository/number
pairs, goals require verified closure, and a cycle requires every goal under its
pinned parent: six for v1 and seven for v2. Historical stage numbers retain their
original meanings; a current v2 cycle does not relabel old closures.
Closed PRs that were not merged appear separately when present.

For a tracker running a pinned release, the command uses its bundle-adjacent
`fleet.yaml` when present, or an explicit `--manifest PATH`; otherwise it uses
the checkout's packaged manifest. A mismatch is an error. Do not remove a pin
or edit the active fleet configuration to force counts through validation.

Exit 0 means fresh observations and, when requested, healthy durability results.
Exit 3 still prints verified counts but reports
stale, missing, or future-dated observations on stderr: retain that qualification
after the summary. Exit 1 means unavailable or invalid evidence; report the error
without inventing counts. Exit 2 means invalid arguments.

For each requested Mech stats answer, preserve its validated source snapshot and
the response in `workspace/reports/mech-stats/report.json`, as requested by the
user. Retain a copy of the bundle and its pinned manifest, report using that
copy with `--bundle`, and archive that same copy. Do not associate an earlier
answer with a newer publisher snapshot. Use
`scripts/mech_stats_record.py --bundle PATH --response-file PATH`,
passing `--manifest PATH` when needed. The response JSON has `source_id`,
`source`, `text_kind` (`verbatim` or `summary`), `text`, `responded_at` (known
timezone-aware message time or `null`), and `prompt` (known text or `null`). Use
a stable source ID for the particular answer so a retry cannot duplicate it.
Save full available evidence; `--observations PATH` retains supplementary PR
observations. Historical snapshots without attributable responses are recorded
without `--response-file`. Never backfill requested examples as measurements or
invent earlier response wording/timestamps. Follow the
[archive contract](../../../docs/guides/MECH_PROGRESS.md#save-stats-responses-and-historical-snapshots).

Source reporting is read-only; this archive writes only local report files.
Reporting does not refresh the collector, approve prompts, advance goals, or
change PRs. See [progress accounting](../../../docs/guides/MECH_PROGRESS.md)
for the tracking and publication contract.
