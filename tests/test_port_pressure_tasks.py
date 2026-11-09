"""Task observations never turn a leaked/closed connection into idle authority."""
from datetime import datetime, timezone

import pytest

from kg_microbe_workflows.port_pressure_tasks import blocked_tasks

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc).timestamp()
ROOT = {"pid": 100, "ppid": 1, "comm": "agy", "started_epoch": NOW - 7200}
IDLE = {"active_tools": [], "native_execution_state": "idle_candidate"}
SCREEN = "────────────────────\n>\n────────────────────\n Gemini example · high\n"


def socket(pid, address, state):
    return {"pid": pid, "command": "agy" if pid == 100 else "git", "fd": "5u",
            "type": "IPv4", "address": address, "state": state, "loopback": True}


def test_older_running_tool_and_git_descendant_closed_socket_remain_blockers():
    native = {"active_tools": [{"step_index": 7, "status": "running", "tool_name": "run_command",
                                "toolSummary": "git push", "created_at": "2026-11-04T11:00:00Z"}],
              "last_step": {"index": 9, "status": "done"}, "native_execution_state": "idle_candidate"}
    processes = [ROOT,
                 {"pid": 101, "ppid": 100, "comm": "/bin/bash", "started_epoch": NOW - 4000},
                 {"pid": 102, "ppid": 101, "comm": "/usr/bin/git", "started_epoch": NOW - 3600},
                 {"pid": 201, "ppid": 1, "comm": "git", "started_epoch": NOW - 3600}]
    tcp = {100: [socket(100, "127.0.0.1:54000", "LISTEN")],
           102: [socket(102, "127.0.0.1:54100->127.0.0.1:54000", "CLOSED")],
           201: [socket(201, "127.0.0.1:54200->127.0.0.1:54000", "CLOSED")]}
    report = blocked_tasks(native, SCREEN, processes, tcp, 100, now=NOW)
    tool = next(row for row in report if row["source"] == "native_tool")
    assert tool["step_index"] == 7 and tool["age_seconds"] == 3600
    assert tool["socket_state"] == "unknown"  # No invented tool-to-PID join.
    child = next(row for row in report if row.get("pid") == 102)
    assert child["task"] == "git" and child["ancestry"] == [102, 101, 100]
    assert child["age_seconds"] == 3600 and child["age_source"] == "process_started_epoch"
    assert child["socket_state"] == "CLOSED" and child["socket_states"] == ["CLOSED"]
    assert child["socket_evidence"][0]["relation"] == "connection_to_agy_loopback_listener"
    assert all(row["restart_eligible"] is False and row.get("pid") != 201 for row in report)


@pytest.mark.parametrize("rows", [None, [],
    [socket(102, "127.0.0.1:54100->127.0.0.1:54999", "CLOSED")],
    [socket(102, "127.0.0.1:54100->127.0.0.2:54000", "CLOSED")],
    [socket(102, "192.0.2.2:54100->127.0.0.1:54000", "CLOSED")],
    [socket(102, "127.0.0.1:54100", "CLOSED")],
])
def test_unknown_or_unrelated_sockets_never_become_closed_proxy(rows):
    report = blocked_tasks(IDLE, SCREEN,
        [ROOT, {"pid": 102, "ppid": 100, "comm": "git", "started_epoch": None}],
        {100: [socket(100, "127.0.0.1:54000", "LISTEN")], 102: rows}, 100, now=NOW)
    assert len(report) == 1
    assert report[0]["socket_state"] == "unknown" and report[0]["socket_states"] == []
    assert report[0]["age_seconds"] is None and not report[0]["restart_eligible"]


def test_closed_connection_is_not_attributed_to_a_non_listener_agy_socket():
    report = blocked_tasks(IDLE, SCREEN,
        [ROOT, {"pid": 102, "ppid": 100, "comm": "git", "started_epoch": NOW - 30}],
        {100: [socket(100, "127.0.0.1:54000", "CLOSED")],
         102: [socket(102, "127.0.0.1:54100->127.0.0.1:54000", "CLOSED")]}, 100, now=NOW)
    assert report[0]["socket_state"] == "unknown"


def test_ipv6_endpoint_and_multiple_socket_states_are_retained():
    rows = [socket(102, "[::1]:54001->[::1]:54000", "CLOSED"),
            socket(102, "[::1]:54002->[::1]:54000", "ESTABLISHED")]
    report = blocked_tasks(IDLE, SCREEN,
        [ROOT, {"pid": 102, "ppid": 100, "comm": "git", "started_epoch": NOW - 30}],
        {100: [socket(100, "[::1]:54000", "LISTEN")], 102: rows}, 100, now=NOW)
    assert report[0]["socket_state"] == "multiple"
    assert report[0]["socket_states"] == ["CLOSED", "ESTABLISHED"]


@pytest.mark.parametrize("created", [None, "02:23", "2026-11-03T00:00:00", "2026-11-04T13:00:00Z"])
def test_native_running_task_without_authoritative_age_remains_unknown(created):
    native = {**IDLE, "active_tools": [{"status": "running", "tool_name": "run_command",
                                       "created_at": created}]}
    report = blocked_tasks(native, SCREEN, [ROOT], {}, 100, now=NOW)
    assert len(report) == 1 and report[0]["age_seconds"] is None
    assert report[0]["socket_state"] == "unknown"


def test_ui_task_without_child_retains_unknown_age_across_date_rollover():
    report = blocked_tasks(IDLE, SCREEN + "● [23:59:00] git push running\n", [ROOT], {}, 100, now=NOW)
    assert len(report) == 1 and report[0]["source"] == "terminal"
    assert report[0]["task"] == "git push" and report[0]["displayed_clock"] == "23:59:00"
    assert report[0]["age_seconds"] is None and report[0]["socket_state"] == "unknown"


def test_unknown_native_inventory_is_a_blocker_and_complete_idle_inventory_is_empty():
    assert blocked_tasks(IDLE, SCREEN, [ROOT], {}, 100, now=NOW) == []
    unknown = blocked_tasks({"native_execution_state": "idle_candidate"}, SCREEN, [ROOT], {}, 100, now=NOW)
    assert unknown[0]["reason"] == "active-tool inventory unavailable"


def test_missing_root_and_future_child_start_never_claim_idle_or_age():
    assert blocked_tasks(IDLE, SCREEN, [], {}, 100, now=NOW)[0]["source"] == "process_inventory"
    report = blocked_tasks(IDLE, SCREEN,
        [ROOT, {"pid": 102, "ppid": 100, "comm": "git", "started_epoch": NOW + 30}],
        {}, 100, now=NOW)
    assert len(report) == 1 and report[0]["age_seconds"] is None


@pytest.mark.parametrize("processes", [
    [ROOT, ROOT],
    [ROOT, {"pid": 101, "ppid": 101, "comm": "git"}],
    [ROOT, {"pid": 101, "ppid": 100, "comm": "git", "started_epoch": NOW - 9000}],
    [ROOT, "unreadable"],
])
def test_ambiguous_process_inventory_fails_closed(processes):
    with pytest.raises(ValueError):
        blocked_tasks(IDLE, SCREEN, processes, {}, 100, now=NOW)


def test_unrelated_root_process_is_not_accepted_as_agy():
    with pytest.raises(ValueError, match="not an agy"):
        blocked_tasks(IDLE, SCREEN, [{**ROOT, "comm": "unrelated"}], {}, 100, now=NOW)
