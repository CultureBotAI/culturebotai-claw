"""Tests for the scheduled-job status report.

The report exists because "latest run: success" hides the three ways a cron
job fails quietly: a disabled workflow, runs GitHub dropped or started late,
and a repository the loop never reached. Each test is driven by an input where
the two sides of one of those distinctions differ. Everything runs offline:
`gh` is injected and the clock is fixed.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cron_status as cs  # noqa: E402

NOW = dt.datetime(2026, 11, 5, 5, 28, tzinfo=dt.UTC)


def day(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


# ------------------------------------------------------------------ cron --
@pytest.mark.parametrize("expression,per_day,description", [
    ("41 6 * * *", 1, "daily 06:41"),
    ("23 * * * *", 24, "hourly at :23"),
    ("7,22,37,52 * * * *", 96, "every 15 min"),
    ("*/20 9-17 * * *", 27, "`*/20 9-17 * * *`"),
    ("5/15 * * * *", 96, "every 15 min"),
])
def test_cron_ticks_per_day_and_description(expression, per_day, description):
    cron = cs.Cron.parse(expression)
    assert len(cron.ticks_on(day("2026-11-04"))) == per_day
    assert cron.describe() == description


def test_step_from_a_start_value_runs_to_the_field_maximum():
    assert cs.Cron.parse("5/15 * * * *").minutes == {5, 20, 35, 50}


def test_weekday_restriction_and_sunday_as_seven():
    weekdays = cs.Cron.parse("0 7 * * 1-5")
    assert weekdays.runs_on(day("2026-11-02")) and not weekdays.runs_on(day("2026-11-07"))  # Mon / Sat
    assert cs.Cron.parse("0 0 * * 7").runs_on(day("2026-11-08"))  # Sunday
    assert cs.Cron.parse("0 0 * * SUN").runs_on(day("2026-11-08"))


def test_day_of_month_and_weekday_combine_with_or_when_both_are_restricted():
    cron = cs.Cron.parse("0 0 1 * 1")
    assert cron.runs_on(day("2026-11-01"))  # the 1st, a Sunday
    assert cron.runs_on(day("2026-11-02"))  # a Monday, not the 1st
    assert not cron.runs_on(day("2026-11-03"))
    only_dom = cs.Cron.parse("0 0 1 * *")
    assert not only_dom.runs_on(day("2026-11-02"))


@pytest.mark.parametrize("expression", ["61 * * * *", "* * * *", "0 0 * * 8", "*/0 * * * *", "5-1 * * * *",
                                        "x * * * *"])
def test_invalid_cron_is_rejected(expression):
    with pytest.raises(cs.CronError):
        cs.Cron.parse(expression)


def test_last_and_next_tick():
    cron = cs.Cron.parse("41 6 * * *")
    started = dt.datetime(2026, 11, 4, 14, 51, tzinfo=dt.UTC)
    assert cron.last_tick(started) == dt.datetime(2026, 11, 4, 6, 41, tzinfo=dt.UTC)
    assert cron.next_tick(NOW) == dt.datetime(2026, 11, 5, 6, 41, tzinfo=dt.UTC)


# ------------------------------------------------------------- assessing --
def run(created: str, conclusion: str = "success") -> dict:
    return {"created_at": created, "status": "completed", "conclusion": conclusion,
            "html_url": f"https://example.invalid/{created}"}


def daily_status(state: str = "active") -> cs.WorkflowStatus:
    return cs.WorkflowStatus("CultureBotAI/culturebotai-claw", "audit", ".github/workflows/a.yaml", state,
                             ["41 6 * * *"])


def daily_runs(late_hours: float = 8, conclusion: str = "success") -> list[dict]:
    runs = []
    for offset in range(1, 7):
        tick = dt.datetime(2026, 11, 5, 6, 41, tzinfo=dt.UTC) - dt.timedelta(days=offset)
        runs.append(run((tick + dt.timedelta(hours=late_hours)).isoformat().replace("+00:00", "Z")))
    runs.sort(key=lambda item: item["created_at"])
    runs[-1]["conclusion"] = conclusion
    return runs


def test_on_schedule_daily_job_counts_per_day_and_needs_no_attention():
    status = daily_status()
    cs.assess(status, daily_runs(), NOW, 7)
    assert status.runs_per_day == [1, 1, 1, 1, 1, 1, 0]
    assert status.expected_per_day == [1, 1, 1, 1, 1, 1, 0]  # today's 06:41 has not come yet
    assert status.expected_due == 6
    assert status.late_minutes_at_least == 8 * 60
    assert status.next_tick == "2026-11-05T06:41:00+00:00"
    assert status.attention == []


@pytest.mark.parametrize("late_hours,flagged", [(11.9, False), (12.5, True)])
def test_lateness_is_flagged_only_beyond_the_grace_period(late_hours, flagged):
    status = daily_status()
    cs.assess(status, daily_runs(late_hours), NOW, 7)
    assert any("late" in flag for flag in status.attention) is flagged


def test_latest_failure_is_flagged_but_a_success_is_not():
    failed, passed = daily_status(), daily_status()
    cs.assess(failed, daily_runs(conclusion="failure"), NOW, 7)
    cs.assess(passed, daily_runs(conclusion="success"), NOW, 7)
    assert "latest run failure" in failed.attention
    assert passed.attention == []


def test_disabled_workflow_is_flagged_even_with_good_history():
    status = daily_status("disabled_inactivity")
    cs.assess(status, daily_runs(), NOW, 7)
    assert any("disabled_inactivity" in flag for flag in status.attention)


def test_silence_is_not_health():
    status = daily_status()
    cs.assess(status, [], NOW, 7)
    assert "no scheduled run in the window" in status.attention
    assert status.latest is None


def test_dropped_runs_are_flagged_against_ticks_older_than_the_grace_period():
    status = cs.WorkflowStatus("r/r", "pages", ".github/workflows/p.yaml", "active", ["7,22,37,52 * * * *"])
    sparse = [run(f"2026-11-0{d}T0{h}:09:00Z") for d in range(1, 5) for h in (1, 5)]
    cs.assess(status, sparse, NOW, 7)
    assert any(flag.startswith("GitHub dropped runs: 8 of") for flag in status.attention)
    dense = cs.WorkflowStatus("r/r", "pages", ".github/workflows/p.yaml", "active", ["0 */6 * * *"])
    cs.assess(dense, [run(f"2026-10-{d:02d}T{h:02d}:05:00Z") for d in (30, 31) for h in (0, 6, 12, 18)]
              + [run(f"2026-11-{d:02d}T{h:02d}:05:00Z") for d in (1, 2, 3, 4) for h in (0, 6, 12, 18)]
              + [run("2026-11-05T00:05:00Z")], NOW, 7)
    assert not any("dropped" in flag for flag in dense.attention)


# --------------------------------------------------------------- reading --
def workflow_file(text: str) -> str:
    return json.dumps({"content": base64.b64encode(text.encode()).decode()})


SCHEDULED = "on:\n  schedule:\n    - cron: '41 6 * * *'\n  workflow_dispatch:\njobs: {}\n"
UNSCHEDULED = "on: [push]\njobs: {}\n"


def _created_filter(endpoint: str):
    from urllib.parse import unquote

    created = unquote(endpoint.split("&created=", 1)[1])
    if created.startswith(">="):
        return lambda run: run["created_at"][:10] >= created[2:]
    return lambda run: run["created_at"][:10] == created


def fake_gh(workflows: list[dict], files: dict[str, str], runs: dict[int, list[dict]],
            failing: set[str] = frozenset(), window_total: int | None = None):
    """A gh stand-in. `window_total` overrides the window query's total_count, to model the API cap."""
    def gh(args: list[str]) -> str:
        endpoint = next(arg for arg in args if arg.startswith("repos/"))
        if any(part in endpoint for part in failing):
            raise RuntimeError(f"HTTP 404: {endpoint}")
        if endpoint.endswith("/actions/workflows"):
            return "\n".join(json.dumps(workflow) for workflow in workflows)
        if "/contents/" in endpoint:
            return files[endpoint.split("/contents/", 1)[1]]
        workflow_id = int(endpoint.split("/actions/workflows/", 1)[1].split("/", 1)[0])
        selected = [item for item in runs.get(workflow_id, []) if _created_filter(endpoint)(item)]
        if args[args.index("--jq") + 1] == ".total_count":
            if window_total is not None and "%3E%3D" in endpoint:
                return str(window_total)
            return str(len(selected))
        return "\n".join(json.dumps(item) for item in selected)
    return gh


WORKFLOWS = [
    {"id": 1, "name": "audit", "path": ".github/workflows/audit.yaml", "state": "active"},
    {"id": 2, "name": "tests", "path": ".github/workflows/tests.yaml", "state": "active"},
    {"id": 3, "name": "pages-build-deployment", "path": "dynamic/pages/pages-build-deployment", "state": "active"},
]
FILES = {".github/workflows/audit.yaml": workflow_file(SCHEDULED),
         ".github/workflows/tests.yaml": workflow_file(UNSCHEDULED)}


def test_only_scheduled_workflows_are_reported():
    statuses = cs.collect_repository("o/r", fake_gh(WORKFLOWS, FILES, {1: daily_runs()}), NOW, 7)
    assert [status.name for status in statuses] == ["audit"]
    assert statuses[0].crons == ["41 6 * * *"]


def test_schedule_crons_reads_pyyaml_on_as_true():
    import yaml

    assert cs.schedule_crons(yaml.safe_load(SCHEDULED)) == ["41 6 * * *"]
    assert cs.schedule_crons(yaml.safe_load(UNSCHEDULED)) == []


def main_output(capsys, gh, *argv) -> tuple[int, str]:
    status = cs.main(["--no-local", *argv], gh=gh, now=NOW)
    return status, capsys.readouterr().out


def test_complete_report_exits_zero(capsys):
    status, out = main_output(capsys, fake_gh(WORKFLOWS, FILES, {1: daily_runs()}), "--repo", "o/r")
    assert status == 0
    assert "| r | audit | daily 06:41 | active | 1 1 1 1 1 1 0 | 6 / 6 |" in out
    assert "INCOMPLETE" not in out


def test_unreachable_repository_is_named_and_makes_the_report_incomplete(capsys):
    gh = fake_gh(WORKFLOWS, FILES, {1: daily_runs()}, failing={"o/missing"})
    status, out = main_output(capsys, gh, "--repo", "o/r", "--repo", "o/missing")
    assert status == 1
    assert "INCOMPLETE: o/missing could not be queried" in out
    assert "| r | audit |" in out


def test_unreadable_workflow_file_is_reported_not_skipped(capsys):
    gh = fake_gh(WORKFLOWS, FILES, {}, failing={"contents/.github/workflows/audit.yaml"})
    status, out = main_output(capsys, gh, "--repo", "o/r")
    assert status == 1
    assert "not assessed: could not read the workflow file" in out
    assert "INCOMPLETE: o/r .github/workflows/audit.yaml was not assessed" in out  # #826


def test_json_output_carries_completeness(capsys):
    status, out = main_output(capsys, fake_gh(WORKFLOWS, FILES, {1: daily_runs()}), "--repo", "o/r", "--json")
    data = json.loads(out)
    assert status == 0 and data["complete"] is True
    assert data["workflows"][0]["runs_per_day"] == [1, 1, 1, 1, 1, 1, 0]


@pytest.mark.parametrize("argv", [["--days", "0"], ["--days", "91"], ["--bogus"]])
def test_bad_usage_exits_two(argv):
    assert cs.main(["--no-local", *argv], gh=fake_gh([], {}, {}), now=NOW) == 2


# ----------------------------------------------------------------- local --
def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_local_crontab_and_launch_agents(tmp_path):
    import plistlib

    (tmp_path / "interval.plist").write_bytes(plistlib.dumps({"Label": "me.backup", "StartInterval": 3600}))
    (tmp_path / "calendar.plist").write_bytes(plistlib.dumps(
        {"Label": "me.report", "StartCalendarInterval": {"Hour": 6, "Minute": 30}}))
    (tmp_path / "keepalive.plist").write_bytes(plistlib.dumps({"Label": "me.daemon", "KeepAlive": True}))

    def run_command(command):
        if command[0] == "crontab":
            return completed(stdout="# comment\n15 3 * * * /usr/local/bin/sync.sh --quiet\n")
        if command[-1] == "me.backup":
            return completed(stdout='{\n\t"LastExitStatus" = 0;\n};\n')
        return completed(returncode=113, stderr="Could not find service")

    jobs, errors = cs.collect_local(run_command, tmp_path)
    assert errors == []
    rows = {(job.source, job.job): (job.schedule, job.status) for job in jobs}
    assert rows[("crontab", "/usr/local/bin/sync.sh --quiet")] == ("15 3 * * *", "installed")
    assert rows[("launchd", "me.backup")] == ("every 1 h", "loaded, last exit 0")
    assert rows[("launchd", "me.report")] == ("Hour=6 Minute=30 (local time)", "not loaded")
    assert ("launchd", "me.daemon") not in rows  # no calendar or interval trigger


def test_no_crontab_is_not_an_error_but_a_crontab_failure_is(tmp_path):
    jobs, errors = cs.collect_local(lambda command: completed(1, stderr="crontab: no crontab for me"), tmp_path)
    assert jobs == [] and errors == []
    _, errors = cs.collect_local(lambda command: completed(1, stderr="crontab: permission denied"), tmp_path)
    assert errors == ["crontab: crontab: permission denied"]


def test_launchd_is_reported_not_checked_rather_than_empty_without_a_directory():
    calls = []

    def run_command(command):
        calls.append(command)
        return completed(1, stderr="crontab: no crontab for me")

    jobs, errors = cs.collect_local(run_command, None)
    assert jobs == [] and errors == [] and all(call[0] != "launchctl" for call in calls)
    unchecked = cs.render([], {}, [], [], ["o/r"], 7, NOW, True, launchd_checked=False)
    checked = cs.render([], {}, [], [], ["o/r"], 7, NOW, True, launchd_checked=True)
    assert "launchd | not checked" in unchecked and "no LaunchAgent" not in unchecked
    assert "no LaunchAgent with a calendar or interval trigger" in checked and "not checked" not in checked


def test_a_launch_agents_dir_that_does_not_exist_makes_the_report_incomplete(tmp_path):
    _, errors = cs.collect_local(lambda command: completed(1, stderr="no crontab for me"), tmp_path / "missing")
    assert errors and "is not a directory" in errors[0]


# ------------------------------------------------- review fixes (#821-#827) --
def test_explicit_step_of_one_expands_to_the_field_maximum():
    assert cs.Cron.parse("0 5/1 * * *").hours == frozenset(range(5, 24))
    assert cs.Cron.parse("5/1 * * * *").minutes == frozenset(range(5, 60))


@pytest.mark.parametrize("expression", ["0 0 */2 * *", "0 0 * * */2", "0 0 * 1-6 *"])
def test_a_schedule_that_skips_days_is_not_summarised_as_daily(expression):
    assert not cs.Cron.parse(expression).describe().startswith("daily")


def test_star_prefixed_weekday_combines_with_day_of_month_by_and():
    cron = cs.Cron.parse("0 0 1 * */2")  # "*/2" is star-prefixed, so AND applies
    assert cron.runs_on(day("2026-11-01"))  # the 1st, a Sunday
    assert not cron.runs_on(day("2027-01-01"))  # the 1st, but a Friday


def test_a_leap_day_schedule_has_a_next_tick():
    assert cs.Cron.parse("0 0 29 2 *").next_tick(NOW) == dt.datetime(2028, 2, 29, tzinfo=dt.UTC)


def test_lateness_is_a_lower_bound_across_crons():
    status = cs.WorkflowStatus("o/r", "two", ".github/workflows/t.yaml", "active", ["0 0 * * *", "0 12 * * *"])
    cs.assess(status, [run("2026-11-05T13:00:00Z")], dt.datetime(2026, 11, 5, 14, tzinfo=dt.UTC), 1)
    assert status.late_minutes_at_least == 60  # served 00:00 or 12:00; only "at least 60" is known
    table = cs.render([status], {}, [], [], ["o/r"], 1, NOW, False)
    assert "Created late by (at least)" in table


def test_a_rerun_shows_its_attempt():
    rerun = dict(run("2026-11-04T14:41:00Z"), run_attempt=2, run_started_at="2026-11-04T16:00:00Z")
    status = daily_status()
    cs.assess(status, daily_runs()[:-1] + [rerun], NOW, 7)
    assert status.latest["run_attempt"] == 2 and status.latest["run_started_at"] == "2026-11-04T16:00:00Z"
    assert "success (attempt 2)" in cs.render([status], {}, [], [], ["o/r"], 7, NOW, False)


def test_more_runs_than_the_search_cap_are_counted_per_day():
    runs = [dict(run(f"2026-11-0{d}T{h:02d}:{m:02d}:00Z"), id=f"{d}-{h}-{m}")
            for d in range(1, 5) for h in range(24) for m in (0, 30)]
    gh = fake_gh(WORKFLOWS, FILES, {1: runs}, window_total=cs.RUN_SEARCH_CAP + 1)
    fetched = cs.fetch_runs(gh, "o/r", 1, "2026-10-30", NOW.date())
    assert len(fetched) == len(runs)  # every day queried, nothing lost to the cap


def test_a_day_beyond_the_search_cap_makes_the_report_incomplete(capsys, monkeypatch):
    monkeypatch.setattr(cs, "RUN_SEARCH_CAP", 3)
    runs = [dict(run(f"2026-11-04T0{h}:00:00Z"), id=h) for h in range(5)]
    status, out = main_output(capsys, fake_gh(WORKFLOWS, FILES, {1: runs}), "--repo", "o/r")
    assert status == 1
    assert "INCOMPLETE: o/r .github/workflows/audit.yaml was not assessed" in out and "more than 3" in out


def test_a_schedule_with_a_timezone_is_not_assessed_in_utc(capsys):
    zoned = "on:\n  schedule:\n    - cron: '0 0 * * *'\n      timezone: America/Los_Angeles\njobs: {}\n"
    files = {".github/workflows/audit.yaml": workflow_file(zoned), ".github/workflows/tests.yaml": FILES[
        ".github/workflows/tests.yaml"]}
    status, out = main_output(capsys, fake_gh(WORKFLOWS, files, {1: daily_runs()}), "--repo", "o/r")
    assert status == 1
    assert "schedule timezone America/Los_Angeles is not supported yet" in out


def test_crontab_assignments_are_skipped_and_shortcuts_keep_their_command(tmp_path):
    crontab = "PATH=/bin:/usr/bin\nMAILTO=\n@daily /bin/echo one two three four five\n"
    jobs, errors = cs.collect_local(lambda command: completed(stdout=crontab), None)
    assert errors == []
    assert [(job.schedule, job.job) for job in jobs] == [("@daily", "/bin/echo one two three four five")]


def test_a_launchctl_failure_is_not_read_as_not_loaded(tmp_path):
    import plistlib

    (tmp_path / "a.plist").write_bytes(plistlib.dumps({"Label": "me.job", "StartInterval": 3600}))

    def denied(command):
        if command[0] == "crontab":
            return completed(1, stderr="crontab: no crontab for me")
        return completed(1, stderr="Permission denied")

    jobs, errors = cs.collect_local(denied, tmp_path)
    assert jobs[0].status == "unknown" and errors == ["launchctl list me.job: Permission denied"]


def test_a_missing_scheduler_binary_is_reported_not_raised(tmp_path):
    def missing(command):
        raise FileNotFoundError(command[0])

    jobs, errors = cs.collect_local(missing, None)
    assert jobs == [] and errors and errors[0].startswith("crontab:")


@pytest.mark.parametrize("plist,schedule", [
    ({"StartInterval": 30}, "every 30 s"),
    ({"StartCalendarInterval": {}}, "every minute (local time)"),
    ({"StartInterval": 3600, "StartCalendarInterval": {"Hour": 6}}, "every 1 h; Hour=6 (local time)"),
])
def test_launchd_triggers_are_rendered_in_full(plist, schedule):
    assert cs._launchd_schedule(plist) == schedule
