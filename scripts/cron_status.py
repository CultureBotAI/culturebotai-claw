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
  * how long after its tick the latest run was created. That is a lower
    bound: a run cannot tell which earlier tick it served;
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
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
from xml.parsers.expat import ExpatError

import yaml

CONTROL_PLANE = "CultureBotAI/culturebotai-claw"
#: Ticks newer than this are not yet "missed": GitHub routinely starts
#: scheduled runs hours late (measured 7-10 h for daily jobs here).
GRACE = dt.timedelta(hours=12)
#: A start later than the grace period is flagged; earlier lateness is GitHub's
#: normal behaviour and is shown in its own column instead.
LATE = GRACE
FAILED = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}
#: The runs API caps a filtered search at this many results; pagination does
#: not lift it (#821).
RUN_SEARCH_CAP = 1000
#: Long enough to find the next 29 February across a century gap (2096 to
#: 2104), so a leap-day schedule always has a next and a last tick (#823).
HORIZON_DAYS = 366 * 9
RUN_FIELDS = ".workflow_runs[] | {id, created_at, run_started_at, run_attempt, status, conclusion, html_url}"
ASSIGNMENT = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=")
#: The StartCalendarInterval keys launchd(5) defines, with their ranges (0 and
#: 7 are both Sunday). Anything else is a schedule launchd would not run (#836).
CALENDAR_KEYS = {"Minute": (0, 59), "Hour": (0, 23), "Day": (1, 31), "Weekday": (0, 7), "Month": (1, 12)}

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

    def last_tick(self, at: dt.datetime, horizon_days: int = HORIZON_DAYS) -> dt.datetime | None:
        for back in range(horizon_days):
            ticks = [tick for tick in self.ticks_on(at.date() - dt.timedelta(days=back)) if tick <= at]
            if ticks:
                return ticks[-1]
        return None

    def next_tick(self, after: dt.datetime, horizon_days: int = HORIZON_DAYS) -> dt.datetime | None:
        for ahead in range(horizon_days):
            ticks = [tick for tick in self.ticks_on(after.date() + dt.timedelta(days=ahead)) if tick > after]
            if ticks:
                return ticks[0]
        return None

    def describe(self) -> str:
        per_day = len(self.minutes) * len(self.hours)
        # Summarise as daily only when every day matches; the star-prefix flags
        # govern the DOM/DOW OR rule, not coverage ("*/2" is star-prefixed) (#823).
        daily = (self.days == frozenset(range(1, 32)) and self.weekdays == frozenset(range(7))
                 and self.months == frozenset(range(1, 13)))
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
        has_step = "/" in part  # "5/1" is a step too, even though its value is 1 (#823)
        if has_step:
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
            end = high if has_step else start  # "5/15" means 5-max/15
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
    late_minutes_at_least: int | None = None  # run creation after its nearest preceding tick
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


def schedule_timezones(document: object) -> list[str]:
    """Any `timezone` declared beside a cron. Those schedules are not evaluated (#822)."""
    if not isinstance(document, dict):
        return []
    events = document.get("on", document.get(True))
    if not isinstance(events, dict) or not isinstance(events.get("schedule"), list):
        return []
    return sorted({str(entry["timezone"]) for entry in events["schedule"]
                   if isinstance(entry, dict) and entry.get("timezone")})


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
        status.latest = {key: latest.get(key) for key in (
            "created_at", "run_started_at", "run_attempt", "status", "conclusion", "html_url")}
        created = _parse_time(latest["created_at"])
        # The nearest preceding tick gives a lower bound: the run may have
        # served an earlier tick of this or another cron (#824).
        previous = [tick for tick in (cron.last_tick(created) for cron in crons) if tick]
        if previous:
            status.late_minutes_at_least = int((created - max(previous)).total_seconds() // 60)
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
    late = status.late_minutes_at_least
    if late is not None and late >= LATE.total_seconds() // 60:
        flags.append(f"latest run created at least {_duration(late)} after its tick")


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
            timezones = schedule_timezones(document)
        except (RuntimeError, KeyError, ValueError, yaml.YAMLError) as exc:
            statuses.append(WorkflowStatus(repository, workflow["name"], path, workflow["state"], [],
                                           error=f"could not read the workflow file: {exc}"))
            continue
        if not crons:
            continue
        status = WorkflowStatus(repository, workflow["name"], path, workflow["state"], crons)
        if timezones:
            status.error = f"schedule timezone {', '.join(timezones)} is not supported yet; not assessed"
            statuses.append(status)
            continue
        try:
            runs = fetch_runs(gh, repository, workflow["id"], since, now.date())
            assess(status, runs, now, window_days)
        except (RuntimeError, CronError, ValueError) as exc:
            status.error = f"{type(exc).__name__}: {exc}"
        statuses.append(status)
    return statuses


def fetch_runs(gh: GhRunner, repository: str, workflow_id: int, since: str, today: dt.date) -> list[dict]:
    """Every scheduled run created since `since`, despite the search cap (#821).

    Normally one count call and one listing call suffice. When the count exceeds the cap, each day is
    queried on its own and the results are deduplicated by run id. A day that
    still exceeds the cap raises, so the report is marked incomplete rather
    than reading the cap as dropped runs.
    """
    base = f"repos/{repository}/actions/workflows/{workflow_id}/runs?event=schedule&per_page=100"

    def total(created: str) -> int:
        return int(gh(["api", f"{base}&created={quote(created)}", "--jq", ".total_count"]).strip())

    def listed(created: str) -> list[dict]:
        return _json_lines(gh(["api", "--paginate", f"{base}&created={quote(created)}", "--jq", RUN_FIELDS]))

    window = f">={since}"
    if total(window) <= RUN_SEARCH_CAP:
        return listed(window)
    runs: dict[object, dict] = {}
    day = dt.date.fromisoformat(since)
    while day <= today:
        if total(day.isoformat()) > RUN_SEARCH_CAP:
            raise RuntimeError(f"more than {RUN_SEARCH_CAP} scheduled runs on {day}; the API cannot list them all")
        for run in listed(day.isoformat()):
            runs[run.get("id", run["created_at"])] = run
        day += dt.timedelta(days=1)
    return list(runs.values())


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
    try:
        crontab = run(["crontab", "-l"])
    except OSError as exc:  # no crontab binary is a source we could not read (#825)
        crontab = None
        errors.append(f"crontab: {exc}")
    if crontab is not None and crontab.returncode == 0:
        for line in crontab.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ASSIGNMENT.match(stripped):
                continue  # comments and environment assignments are not jobs (#825)
            if stripped.startswith("@"):  # shortcuts such as daily or reboot: one token, then the command
                parts = stripped.split(None, 1)  # any whitespace, tabs included (#828)
                if len(parts) < 2:
                    errors.append(f"crontab: shortcut without a command: {stripped}")
                    continue
                jobs.append(LocalJob("crontab", parts[1].strip(), parts[0], "installed"))
                continue
            fields = stripped.split(None, 5)
            schedule = " ".join(fields[:5]) if len(fields) >= 6 else stripped
            jobs.append(LocalJob("crontab", fields[5] if len(fields) >= 6 else stripped, schedule, "installed"))
    elif crontab is not None and "no crontab" not in (crontab.stderr or "").lower():
        errors.append(f"crontab: {(crontab.stderr or '').strip() or 'exit ' + str(crontab.returncode)}")
    plists: list[Path] = []
    if agents_dir is not None and not agents_dir.is_dir():
        errors.append(f"launchd: {agents_dir} is not a directory")
    elif agents_dir is not None:
        try:
            # Path.glob swallows a directory it cannot read, which would read as
            # "no LaunchAgents"; iterdir raises (#836).
            plists = sorted(path for path in agents_dir.iterdir() if path.name.endswith(".plist"))
        except OSError as exc:
            errors.append(f"launchd: cannot list {agents_dir}: {exc}")
    for plist in plists:
        try:
            data = plistlib.loads(plist.read_bytes())
            if not isinstance(data, dict):
                raise ValueError("top level is not a dictionary")
            # A malformed trigger is this file's problem, not the report's (#834).
            schedule = _launchd_schedule(data)
            label = data.get("Label")
            if schedule and (not isinstance(label, str) or not label.strip()):
                raise ValueError(f"Label is not a non-empty string: {label!r}")  # never invented (#836)
        except (OSError, plistlib.InvalidFileException, ExpatError, ValueError, TypeError, AttributeError) as exc:
            errors.append(f"{plist.name}: {exc}")
            continue
        if not schedule:
            continue
        try:
            listed = run(["launchctl", "list", label])
        except OSError as exc:
            errors.append(f"launchctl: {exc}")
            jobs.append(LocalJob("launchd", label, schedule, "unknown"))
            continue
        if listed.returncode != 0:
            # Only launchd's not-found answer means "not loaded"; anything else
            # is a source we could not read (#825).
            if "could not find service" in (listed.stderr or "").lower():
                state = "not loaded"
            else:
                state = "unknown"
                errors.append(f"launchctl list {label}: {(listed.stderr or '').strip() or 'exit ' + str(listed.returncode)}")
        else:
            exit_line = [line for line in listed.stdout.splitlines() if "LastExitStatus" in line]
            state = "loaded" + (f", last exit {exit_line[0].split('=')[-1].strip(' ;')}" if exit_line else "")
        jobs.append(LocalJob("launchd", label, schedule, state))
    return jobs, errors


def _launchd_schedule(data: dict) -> str:
    """Both launchd triggers, which run independently: StartInterval is in seconds,
    and an empty StartCalendarInterval dictionary means every minute (#825).

    Raises ValueError for a trigger launchd(5) would not accept, rather than
    coercing or dropping it: a positive integer interval, and calendar
    dictionaries of integer CALENDAR_KEYS within their ranges (#836).
    """
    parts = []
    if "StartInterval" in data:
        seconds = data["StartInterval"]
        if not _is_integer(seconds) or seconds <= 0:
            raise ValueError(f"StartInterval is not a positive integer: {seconds!r}")
        if seconds < 60:
            parts.append(f"every {seconds} s")
        elif seconds % 60:  # keep the seconds of an interval that is not whole minutes (#828)
            parts.append(f"every {_duration(seconds // 60)} {seconds % 60} s")
        else:
            parts.append(f"every {_duration(seconds // 60)}")
    if "StartCalendarInterval" in data:
        calendar = data["StartCalendarInterval"]
        entries = calendar if isinstance(calendar, list) else [calendar]
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"StartCalendarInterval entry is not a dictionary: {entry!r}")
            for key, value in entry.items():
                if key not in CALENDAR_KEYS:
                    raise ValueError(f"StartCalendarInterval has an unknown key: {key!r}")
                low, high = CALENDAR_KEYS[key]
                if not _is_integer(value) or not low <= value <= high:
                    raise ValueError(f"StartCalendarInterval {key} is not an integer in {low}-{high}: {value!r}")
        texts = [" ".join(f"{key}={value}" for key, value in sorted(entry.items())) or "every minute"
                 for entry in entries]
        if texts:
            parts.append("; ".join(texts) + " (local time)")
    return "; ".join(parts)


def _is_integer(value: object) -> bool:
    """A plist integer. A plist boolean arrives as a Python bool, which is an int subclass."""
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------- output --
def _parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    days, hours = divmod(hours, 24)  # keep the leftover minutes too (#831)
    return f"{days} d {hours} h {rest} min" if rest else f"{days} d {hours} h"


class Code(str):
    """A literal value, such as a command, shown as a code span so Markdown cannot rewrite it (#833)."""


def _cell(value: object) -> str:
    """One table cell: a pipe would start a new column and a newline a new row (#831).

    A Code value is fenced with more backticks than any run inside it. GitHub's
    table parser removes the pipe's escape before reading the code span, so a
    literal backslash before a pipe survives as itself.
    """
    text = " ".join(str(value).splitlines())
    if isinstance(value, Code) and text:
        fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
        pad = " " if text.startswith("`") or text.endswith("`") else ""
        text = f"{fence}{pad}{text}{pad}{fence}"
    return text.replace("|", "\\|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def render(statuses: list[WorkflowStatus], failures: dict[str, str], local: list[LocalJob],
           local_errors: list[str], queried: list[str], window_days: int, now: dt.datetime,
           include_local: bool, launchd_checked: bool = True) -> str:
    lines = [f"Scheduled jobs as of {now:%Y-%m-%d %H:%M} UTC; runs counted over the last {window_days} days "
             "(oldest → today; today counts ticks so far).", ""]
    lines += ["| Repository | Workflow | Schedule (UTC) | State | Runs per day | Due / ran | "
              "Latest scheduled run (UTC) | Created late by (at least) | Attention |",
              "|---|---|---|---|---|---|---|---|---|"]
    for status in statuses:
        repo = status.repository.split("/", 1)[1]
        if status.error:
            lines.append(_row(repo, status.name, ", ".join(status.crons) or "?", status.state,
                              "—", "—", "—", "—", f"**not assessed: {status.error}**"))
            continue
        schedule = "; ".join(Cron.parse(expression).describe() for expression in status.crons)
        per_day = " ".join(str(count) for count in status.runs_per_day)
        latest = status.latest or {}
        when = latest.get("created_at", "")[:16].replace("T", " ") or "none"
        result = latest.get("conclusion") or latest.get("status") or ""
        if (latest.get("run_attempt") or 1) > 1:
            result += f" (attempt {latest['run_attempt']})"
        late = (_duration(status.late_minutes_at_least) if status.late_minutes_at_least is not None else "—")
        attention = "; ".join(status.attention) or "ok"
        lines.append(_row(repo, status.name, schedule, status.state, per_day,
                          f"{status.expected_due} / {sum(status.runs_per_day)}", f"{when} {result}", late, attention))
    if not statuses:
        lines.append("| — | no scheduled workflow found | | | | | | | |")
    if include_local:
        lines += ["", "| Local source | Job | Schedule | Status |", "|---|---|---|---|"]
        lines += [_row(job.source, Code(job.job), Code(job.schedule) if job.source == "crontab" else job.schedule,
                       job.status) for job in local]
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
    for status in statuses:  # a workflow that was not assessed is named too (#826)
        if status.error:
            lines.append(f"INCOMPLETE: {status.repository} {status.path} was not assessed: {status.error}")
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
