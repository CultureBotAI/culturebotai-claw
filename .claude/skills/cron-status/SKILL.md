---
name: cron-status
description: "Answer \"did the cron job run?\" or \"cron job status\" in one standard table. Runs scripts/cron_status.py over claw's scheduled GitHub workflows (or, with --fleet, every manifest Mech's) plus this machine's crontab and user LaunchAgents. Each row gives the schedule, runs per day against the runs due, how long after its tick the latest scheduled run was created (a lower bound), and the workflow's state. Then add Claude Code session jobs from CronList. Read-only: it never dispatches, re-runs, enables or disables anything."
category: cross-repo
requires_database: false
requires_internet: true
version: 1.0.0
tags: [cron, schedule, github-actions, launchd, status, fleet, read-only, reporting]
---

# Cron job status

## Purpose

Answer one question, the same way every time: **did the scheduled jobs run, and
on time?**

"Latest run: success" is not that answer. A scheduled job fails quietly in three
ways, and the table shows each one:

- **Disabled.** GitHub stops scheduling a workflow after 60 days without
  repository activity, or when someone disables it. Its run list just goes quiet.
- **Late or dropped.** GitHub starts scheduled runs late and drops many,
  especially frequent ones. On claw, daily jobs routinely start about 8 hours
  late, and a 15-minute job runs about 5 times a day instead of 96.
- **Not looked at.** A repository whose query failed must not read as "nothing
  scheduled there".

## Run it

```bash
uv run python scripts/cron_status.py --launch-agents-dir ~/Library/LaunchAgents          # claw + local schedulers
uv run python scripts/cron_status.py --fleet --launch-agents-dir ~/Library/LaunchAgents  # and every manifest Mech
uv run python scripts/cron_status.py --repo CultureBotAI/TraitMech   # one repo; repeatable
uv run python scripts/cron_status.py --days 14       # longer window (1-90)
uv run python scripts/cron_status.py --no-local      # skip crontab and launchd
uv run python scripts/cron_status.py --json          # machine-readable
```

Exit codes:
- `0`: complete report.
- `1`: a repository, a workflow file or a local source could not be read. The
  report names it on an `INCOMPLETE` line.
- `2`: bad usage, or `gh` missing.

**A non-zero exit means the report is incomplete**, so do not present its counts
as the whole answer.

Then call **CronList** (load it with ToolSearch `select:CronList` if it is
deferred). Add a third table, `| Claude Code job | Schedule | Recurring | Prompt (first 60 chars) |`,
or say "no Claude Code session jobs". A script cannot see these jobs, because
they live in the Claude Code session.

## Reading the table

| Column | Meaning |
|---|---|
| Schedule (UTC) | The workflow's `on.schedule` crons, summarised (`daily 06:41`, `every 15 min`, `hourly at :23`), or the raw expression. GitHub evaluates crons in UTC unless a schedule names a `timezone`. Such a workflow is reported as not assessed, which makes the report incomplete. |
| State | GitHub's workflow state. Anything but `active` (for example `disabled_inactivity`, `disabled_manually`) means GitHub will not schedule it. |
| Runs per day | Scheduled runs created on each UTC day of the window, oldest first. Today's figure is so far. |
| Due / ran | Ticks older than the 12-hour grace period, against the runs created in the window. Due counts ticks and ran counts runs. They are not matched pairs: a tick from before the window is not due, but its delayed run counts in ran if it was created inside the window. |
| Latest scheduled run | When it was created, its conclusion, and its attempt if it was re-run. Only `schedule` events count: a push run that passed afterwards does not change this column. |
| Created late by (at least) | The latest run's creation minus the nearest preceding tick. That is a lower bound: a run does not record which tick it served, and it may have served an earlier one. It measures GitHub's scheduler, not when a runner picked the job up. |
| Attention | Empty (`ok`), or the reasons below. |

`Attention` flags:
- a workflow that is not `active`;
- no scheduled run in the window although some were due;
- fewer than half the due runs ("GitHub dropped runs");
- a latest run that failed, was cancelled or timed out, or any non-success in
  the window;
- a run created more than 12 hours after its nearest preceding tick.

Lateness under 12 hours is GitHub's normal behaviour. It stays in its own
column, unflagged.

The local table lists crontab entries, and the LaunchAgents in `--launch-agents-dir`
with a calendar or interval trigger. The script never assumes that directory: without the
argument, it reports launchd as "not checked". The LaunchAgents are marked `loaded`, `not loaded`, or `unknown` when launchctl could not be asked (which makes the report incomplete). Most such LaunchAgents are
vendor updaters. Name any that look like the user's own jobs.

The script never guesses at a LaunchAgent it cannot read. Each of these is
named on an `INCOMPLETE` line, while the rest of the report still appears:
- a plist that does not parse;
- a missing or empty `Label`;
- a `StartInterval` that is not a positive integer;
- a `StartCalendarInterval` that launchd(5) would reject.

A LaunchAgents directory it cannot list is reported the same way, not as empty.

## Output

Always show:
- the script's tables verbatim;
- the Claude Code table;
- one to three sentences on what needs attention, citing rows.

When the user asks "did it run?" about one job, answer that first, then the
table.

Do not quote a total from an incomplete report as if it were the answer.

## Boundaries

Read-only:
- `gh api` GETs only;
- `crontab -l`;
- `launchctl list`;
- reading plists.

Never dispatch, re-run, enable or disable a workflow, or load or unload a
LaunchAgent, as part of this skill. Suggest it, and leave it to the user.
