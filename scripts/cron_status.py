#!/usr/bin/env python3
"""Report every scheduled ("cron") job in one fixed table.

    uv run python scripts/cron_status.py [--fleet] [--repo OWNER/NAME ...]
                                         [--days N] [--no-local] [--json]
                                         [--launch-agents-dir DIR]

It covers claw's scheduled GitHub workflows; with --fleet, those of every
Mech in the fleet manifest; and this machine's own schedulers.

Why a script rather than "check the latest run": "did the cron job run?" has
three answers that look right and are not.

  * A scheduled workflow that GitHub has disabled (after 60 days without
    repository activity, or by hand) simply stops. Its run list goes quiet,
    and quiet reads as healthy.
  * GitHub starts scheduled runs late and drops many, especially frequent
    ones. Measured on this repository: daily jobs started 7-10 hours late,
    and a 15-minute job ran about 5 times a day instead of 96. A "latest run:
    success" line hides both.
  * A repository whose query fails drops out of a hand-rolled loop, so "we
    did not look" reads as "nothing scheduled there".

So every row carries:
  * the schedule;
  * the runs it should have had and the runs it had, per day;
  * how late its latest run started;
  * the workflow's state.
The report names every source it could not query.

Local schedulers are the user crontab, and the LaunchAgents with a calendar or
interval trigger in --launch-agents-dir. On macOS that is
~/Library/LaunchAgents, which the cron-status skill passes. The script never
assumes that location: without the argument it reports launchd as not checked,
rather than as empty. Claude Code session jobs (CronCreate) are not visible to
a script; the skill adds them from CronList.

Exit codes: 0 complete report; 1 a repository, workflow or local source could
not be queried; 2 bad usage, or `gh` unavailable.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONTROL_PLANE = "CultureBotAI/culturebotai-claw"
#: Ticks newer than this are not yet "missed": GitHub routinely starts
#: scheduled runs hours late (measured 7-10 h for daily jobs here).
GRACE = dt.timedelta(hours=12)
#: A start later than the grace period is flagged; earlier lateness is GitHub's
#: normal behaviour and is shown in its own column instead.
LATE = GRACE
FAILED = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}

GhRunner = Callable[[list[str]], str]


# --------------------------------------------------------------- cron -----
_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_NAMES = {
    3: {name: index for index, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)},
    4: {name: index for index, name in enumerate(("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"))},
}


class CronError(ValueError):
    pass


@dataclass(frozen=True)
class Cron:
    """A five-field cron expression, evaluated in UTC as GitHub Actions does."""

    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0 = Sunday
    days_restricted: bool
    weekdays_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> Cron:
        fields = expression.split()
        if len(fields) != 5:
            raise CronError(f"expected 5 fields: {expression!r}")
        values = [_field(text, index) for index, text in enumerate(fields)]
        weekdays = frozenset(0 if day == 7 else day for day in values[4])
        return cls(expression, values[0], values[1], values[2], values[3], weekdays,
                   not fields[2].startswith("*"), not fields[4].startswith("*"))

    def runs_on(self, day: dt.date) -> bool:
        if day.month not in self.months:
            return False
        in_days = day.day in self.days
        in_weekdays = (day.weekday() + 1) % 7 in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return in_days or in_weekdays  # cron's OR rule when both are restricted
        return in_days and in_weekdays

    def ticks_on(self, day: dt.date) -> list[dt.datetime]:
        if not self.runs_on(day):
            return []
        return [dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)
                for hour in sorted(self.hours) for minute in sorted(self.minutes)]

    def last_tick(self, at: dt.datetime, horizon_days: int = 400) -> dt.datetime | None:
        for back in range(horizon_days):
            ticks = [tick for tick in self.ticks_on(at.date() - dt.timedelta(days=back)) if tick <= at]
            if ticks:
                return ticks[-1]
        return None

    def next_tick(self, after: dt.datetime, horizon_days: int = 400) -> dt.datetime | None:
        for ahead in range(horizon_days):
            ticks = [tick for tick in self.ticks_on(after.date() + dt.timedelta(days=ahead)) if tick > after]
            if ticks:
                return ticks[0]
        return None

    def describe(self) -> str:
        per_day = len(self.minutes) * len(self.hours)
        daily = not self.days_restricted and not self.weekdays_restricted and len(self.months) == 12
        if daily and len(self.hours) == 24 and len(self.minutes) == 1:
            return f"hourly at :{min(self.minutes):02d}"
        if daily and len(self.hours) == 24:
            minutes = sorted(self.minutes)
            gaps = {b - a for a, b in zip(minutes, minutes[1:] + [minutes[0] + 60])}
            if len(gaps) == 1:
                return f"every {gaps.pop()} min"
            return f"{per_day}x daily"
        if daily and per_day == 1:
            return f"daily {min(self.hours):02d}:{min(self.minutes):02d}"
        return f"`{self.expression}`"


def _value(text: str, index: int) -> int:
    upper = text.upper()
    if upper in _NAMES.get(index, {}):
        return _NAMES[index][upper]
    if not text.isdigit():
        raise CronError(f"bad value {text!r}")
    number = int(text)
    low, high = _RANGES[index]
    if not low <= number <= high:
        raise CronError(f"value {number} outside {low}-{high}")
    return number


def _field(text: str, index: int) -> frozenset[int]:
    low, high = _RANGES[index]
    values: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"bad step {step_text!r}")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            first, last = part.split("-", 1)
            start, end = _value(first, index), _value(last, index)
            if start > end:
                raise CronError(f"backwards range {part!r}")
        else:
            start = _value(part, index)
            end = high if step != 1 else start  # "5/15" means 5-max/15
        values.update(range(start, end + 1, step))
    if index == 4 and text == "*":
        values = set(range(0, 7))
    return frozenset(values)


# ----------------------------------------------------------- workflows ----
@dataclass
class WorkflowStatus:
    repository: str
    name: str
    path: str
    state: str
    crons: list[str]
    days: list[str] = field(default_factory=list)  # oldest first
    runs_per_day: list[int] = field(default_factory=list)
    expected_per_day: list[int] = field(default_factory=list)
    expected_due: int = 0  # ticks in the window older than GRACE
    latest: dict | None = None
    started_late_minutes: int | None = None
    next_tick: str | None = None
    non_success: int = 0
    error: str | None = None
    attention: list[str] = field(default_factory=list)


def default_gh(args: list[str]) -> str:
    completed = subprocess.run(["gh", *args], text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or f"gh exited {completed.returncode}")
    return completed.stdout


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def schedule_crons(document: object) -> list[str]:
    """The cron expressions a workflow's `on.schedule` declares (PyYAML reads `on` as True)."""
    if not isinstance(document, dict):
        return []
    events = document.get("on", document.get(True))
    if not isinstance(events, dict) or not isinstance(events.get("schedule"), list):
        return []
    return [str(entry["cron"]).strip() for entry in events["schedule"]
            if isinstance(entry, dict) and entry.get("cron")]


def assess(status: WorkflowStatus, runs: Iterable[dict], now: dt.datetime, window_days: int) -> None:
    """Fill the counts, lateness and attention flags from the scheduled runs in the window."""
    crons = [Cron.parse(expression) for expression in status.crons]
    today = now.date()
    days = [today - dt.timedelta(days=offset) for offset in range(window_days - 1, -1, -1)]
    runs = sorted(runs, key=lambda run: run["created_at"])
    by_day = {day: 0 for day in days}
    for run in runs:
        created = _parse_time(run["created_at"])
        if created.date() in by_day:
            by_day[created.date()] += 1
        if run.get("conclusion") in FAILED:
            status.non_success += 1
    status.days = [day.isoformat() for day in days]
    status.runs_per_day = [by_day[day] for day in days]
    ticks = [tick for day in days for cron in crons for tick in cron.ticks_on(day) if tick <= now]
    status.expected_per_day = [sum(1 for tick in ticks if tick.date() == day) for day in days]
    status.expected_due = sum(1 for tick in ticks if tick <= now - GRACE)
    upcoming = [tick for tick in (cron.next_tick(now) for cron in crons) if tick]
    status.next_tick = min(upcoming).isoformat() if upcoming else None
    if runs:
        latest = runs[-1]
        status.latest = {key: latest.get(key) for key in ("created_at", "status", "conclusion", "html_url")}
        created = _parse_time(latest["created_at"])
        previous = [tick for tick in (cron.last_tick(created) for cron in crons) if tick]
        if previous:
            status.started_late_minutes = int((created - max(previous)).total_seconds() // 60)
    _flag(status)


def _flag(status: WorkflowStatus) -> None:
    flags = status.attention
    if status.state != "active":
        flags.append(f"workflow {status.state}: GitHub will not schedule it")
    total = sum(status.runs_per_day)
    if status.expected_due and total == 0:
        flags.append("no scheduled run in the window")
    elif status.expected_due and total < status.expected_due / 2:
        flags.append(f"GitHub dropped runs: {total} of {status.expected_due} due")
    latest = status.latest or {}
    if latest.get("conclusion") in FAILED:
        flags.append(f"latest run {latest['conclusion']}")
    elif status.non_success:
        flags.append(f"{status.non_success} non-success run(s) in the window")
    if status.started_late_minutes is not None and status.started_late_minutes >= LATE.total_seconds() // 60:
        flags.append(f"latest started {_duration(status.started_late_minutes)} late")


def collect_repository(repository: str, gh: GhRunner, now: dt.datetime, window_days: int) -> list[WorkflowStatus]:
    """Every scheduled workflow in one repository. Raises if the workflow list cannot be read."""
    workflows = _json_lines(gh(["api", "--paginate", f"repos/{repository}/actions/workflows",
                                "--jq", ".workflows[] | {id, name, path, state}"]))
    since = (now.date() - dt.timedelta(days=window_days - 1)).isoformat()
    statuses = []
    for workflow in workflows:
        path = workflow["path"]
        if not path.startswith(".github/workflows/"):
            continue  # dynamic workflows (Pages, Dependabot) carry no schedule of ours
        try:
            content = json.loads(gh(["api", f"repos/{repository}/contents/{path}"]))
            document = yaml.safe_load(base64.b64decode(content["content"]))
            crons = schedule_crons(document)
        except (RuntimeError, KeyError, ValueError, yaml.YAMLError) as exc:
            statuses.append(WorkflowStatus(repository, workflow["name"], path, workflow["state"], [],
                                           error=f"could not read the workflow file: {exc}"))
            continue
        if not crons:
            continue
        status = WorkflowStatus(repository, workflow["name"], path, workflow["state"], crons)
        try:
            runs = _json_lines(gh([
                "api", "--paginate",
                f"repos/{repository}/actions/workflows/{workflow['id']}/runs?event=schedule&per_page=100"
                f"&created=%3E%3D{since}",
                "--jq", ".workflow_runs[] | {created_at, status, conclusion, html_url}",
            ]))
            assess(status, runs, now, window_days)
        except (RuntimeError, CronError, ValueError) as exc:
            status.error = f"{type(exc).__name__}: {exc}"
        statuses.append(status)
    return statuses


# ---------------------------------------------------------------- local ---
@dataclass
class LocalJob:
    source: str
    job: str
    schedule: str
    status: str


def collect_local(run: Callable[[list[str]], subprocess.CompletedProcess],
                  agents_dir: Path | None) -> tuple[list[LocalJob], list[str]]:
    """The crontab, plus the timed LaunchAgents in agents_dir when one is given."""
    jobs: list[LocalJob] = []
    errors: list[str] = []
    crontab = run(["crontab", "-l"])
    if crontab.returncode == 0:
        for line in crontab.stdout.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                fields = line.split(None, 5)
                schedule = " ".join(fields[:5]) if len(fields) >= 6 else line
                jobs.append(LocalJob("crontab", fields[5] if len(fields) >= 6 else line, schedule, "installed"))
    elif "no crontab" not in (crontab.stderr or "").lower():
        errors.append(f"crontab: {(crontab.stderr or '').strip() or 'exit ' + str(crontab.returncode)}")
    if agents_dir is not None and not agents_dir.is_dir():
        errors.append(f"launchd: {agents_dir} is not a directory")
    plists = sorted(agents_dir.glob("*.plist")) if agents_dir is not None and agents_dir.is_dir() else []
    for plist in plists:
        try:
            data = plistlib.loads(plist.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            errors.append(f"{plist.name}: {exc}")
            continue
        schedule = _launchd_schedule(data)
        if not schedule:
            continue
        label = data.get("Label", plist.stem)
        listed = run(["launchctl", "list", label])
        if listed.returncode != 0:
            state = "not loaded"
        else:
            exit_line = [line for line in listed.stdout.splitlines() if "LastExitStatus" in line]
            state = "loaded" + (f", last exit {exit_line[0].split('=')[-1].strip(' ;')}" if exit_line else "")
        jobs.append(LocalJob("launchd", label, schedule, state))
    return jobs, errors


def _launchd_schedule(data: dict) -> str:
    if "StartInterval" in data:
        return f"every {_duration(int(data['StartInterval']) // 60)}"
    calendar = data.get("StartCalendarInterval")
    if not calendar:
        return ""
    entries = calendar if isinstance(calendar, list) else [calendar]
    parts = []
    for entry in entries:
        text = " ".join(f"{key}={value}" for key, value in sorted(entry.items()))
        parts.append(text or "every minute")
    return "; ".join(parts) + " (local time)"


# ---------------------------------------------------------------- output --
def _parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return f"{hours // 24} d {hours % 24} h"


def render(statuses: list[WorkflowStatus], failures: dict[str, str], local: list[LocalJob],
           local_errors: list[str], queried: list[str], window_days: int, now: dt.datetime,
           include_local: bool, launchd_checked: bool = True) -> str:
    lines = [f"Scheduled jobs as of {now:%Y-%m-%d %H:%M} UTC; runs counted over the last {window_days} days "
             "(oldest → today; today counts ticks so far).", ""]
    lines += ["| Repository | Workflow | Schedule (UTC) | State | Runs per day | Due / ran | "
              "Latest scheduled run (UTC) | Started late by | Attention |",
              "|---|---|---|---|---|---|---|---|---|"]
    for status in statuses:
        repo = status.repository.split("/", 1)[1]
        if status.error:
            lines.append(f"| {repo} | {status.name} | {', '.join(status.crons) or '?'} | {status.state} "
                         f"| — | — | — | — | **not assessed: {status.error}** |")
            continue
        schedule = "; ".join(Cron.parse(expression).describe() for expression in status.crons)
        per_day = " ".join(str(count) for count in status.runs_per_day)
        latest = status.latest or {}
        when = latest.get("created_at", "")[:16].replace("T", " ") or "none"
        result = latest.get("conclusion") or latest.get("status") or ""
        late = _duration(status.started_late_minutes) if status.started_late_minutes is not None else "—"
        attention = "; ".join(status.attention) or "ok"
        lines.append(f"| {repo} | {status.name} | {schedule} | {status.state} | {per_day} | "
                     f"{status.expected_due} / {sum(status.runs_per_day)} | {when} {result} | {late} | {attention} |")
    if not statuses:
        lines.append("| — | no scheduled workflow found | | | | | | | |")
    if include_local:
        lines += ["", "| Local source | Job | Schedule | Status |", "|---|---|---|---|"]
        lines += [f"| {job.source} | {job.job} | {job.schedule} | {job.status} |" for job in local]
        if not local:
            found = "no crontab entries" + ("; no LaunchAgent with a calendar or interval trigger"
                                            if launchd_checked else "")
            lines.append(f"| — | nothing scheduled ({found}) | | |")
        if not launchd_checked:
            lines.append("| launchd | not checked: pass --launch-agents-dir (on macOS, ~/Library/LaunchAgents) | | |")
    flagged = sum(1 for status in statuses if status.attention)
    lines += ["", f"Queried {len(queried)} repositor{'y' if len(queried) == 1 else 'ies'}: "
              f"{len(statuses)} scheduled workflow(s), {flagged} needing attention."]
    for repository, error in failures.items():
        lines.append(f"INCOMPLETE: {repository} could not be queried: {error}")
    for error in local_errors:
        lines.append(f"INCOMPLETE: local scheduler source: {error}")
    return "\n".join(lines)


def fleet_repositories() -> list[str]:
    from kg_microbe_fleet import load_fleet_manifest

    return [CONTROL_PLANE] + [mech.github for mech in load_fleet_manifest().mechs.values()]


def main(argv: list[str] | None = None, gh: GhRunner | None = None, now: dt.datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fleet", action="store_true", help="also every Mech in the fleet manifest")
    parser.add_argument("--repo", action="append", default=[], help="OWNER/NAME; repeatable; replaces the default")
    parser.add_argument("--days", type=int, default=7, help="window of days to count runs over (default 7)")
    parser.add_argument("--no-local", action="store_true", help="skip crontab and launchd")
    parser.add_argument("--launch-agents-dir", type=Path,
                        help="LaunchAgents directory to read timed jobs from (on macOS, ~/Library/LaunchAgents)")
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not 1 <= args.days <= 90:
        print("--days must be between 1 and 90", file=sys.stderr)
        return 2
    if gh is None:
        if shutil.which("gh") is None:
            print("gh is not installed", file=sys.stderr)
            return 2
        gh = default_gh
    now = now or dt.datetime.now(dt.UTC)
    repositories = args.repo or (fleet_repositories() if args.fleet else [CONTROL_PLANE])
    statuses: list[WorkflowStatus] = []
    failures: dict[str, str] = {}
    for repository in repositories:
        try:
            statuses += collect_repository(repository, gh, now, args.days)
        except (RuntimeError, ValueError) as exc:
            failures[repository] = str(exc).splitlines()[0][:200]
    local: list[LocalJob] = []
    local_errors: list[str] = []
    if not args.no_local:
        local, local_errors = collect_local(
            lambda command: subprocess.run(command, text=True, capture_output=True, check=False),
            args.launch_agents_dir)
    incomplete = bool(failures or local_errors or any(status.error for status in statuses))
    if args.json:
        print(json.dumps({
            "generated_utc": now.isoformat(), "window_days": args.days, "repositories": repositories,
            "failures": failures, "workflows": [vars(status) for status in statuses],
            "local": [vars(job) for job in local], "local_errors": local_errors,
            "launchd_checked": args.launch_agents_dir is not None, "complete": not incomplete,
        }, indent=2))
    else:
        print(render(statuses, failures, local, local_errors, repositories, args.days, now, not args.no_local,
                     launchd_checked=args.launch_agents_dir is not None))
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
