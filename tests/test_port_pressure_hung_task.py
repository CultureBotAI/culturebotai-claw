"""The #802 hung-shell incident is observational evidence, never kill authority."""
from datetime import timedelta

import pytest
from test_mech_port_pressure_native_transport import START, Evidence, guard


@pytest.mark.parametrize("socket_state", [None, "CLOSED"])
@pytest.mark.parametrize("native_task_retained", [False, True])
def test_nineteen_hour_shell_and_pr_descendants_block_idle_recycling(
    tmp_path, socket_state, native_task_retained,
):
    evidence = Evidence(tmp_path)
    evidence.now = (START + timedelta(hours=20)).timestamp()
    task_started = START + timedelta(hours=1)
    evidence.add_process(101, 100, "/bin/zsh", started=task_started)
    evidence.add_process(102, 101, "/usr/bin/pr", started=task_started)
    evidence.socket_rows[100] = [
        (f"127.0.0.1:{54000 + index}", "LISTEN") for index in range(1501)
    ]
    if socket_state:
        evidence.socket_rows[102] = [("127.0.0.1:58000->127.0.0.1:54000", socket_state)]
    original_lsof = evidence.lsof_text

    def selected_sockets(pid, *, listen):
        # lsof's LISTEN filter omits a process with no matching descriptor;
        # its CLOSED connection remains visible to the separate task query.
        if listen and not any(state == "LISTEN" for _address, state in evidence.socket_rows.get(pid, [])):
            return ""
        return original_lsof(pid, listen=listen)

    evidence.lsof_text = selected_sockets
    if native_task_retained:
        evidence.native["active_tools"] = [{
            "step_index": 7, "status": "running", "tool_name": "run_command",
            "toolSummary": 'zsh -c gh pr create --body "... `PR #217` ..."',
            "created_at": task_started.isoformat(),
        }]
    # A newer completed native step and empty composer do not discharge an
    # older live subprocess. No command in the synthetic prose is executed.
    assert evidence.native["last_step"] == {"index": 9, "status": "done"}
    assert evidence.native["native_execution_state"] == "idle_candidate"
    processes_before = dict(evidence.records)
    result = guard.PortPressureGuard(
        evidence.supervisor, transport=evidence.transport, clock=lambda: evidence.now,
    ).tick(apply=True)

    assert result["phase"] == "blocked" and result["candidate"] is None
    child = next(row for row in result["blocked_tasks"] if row.get("pid") == 102)
    shell = next(row for row in result["blocked_tasks"] if row.get("pid") == 101)
    assert child["task"] == "pr" and child["ancestry"] == [102, 101, 100]
    assert shell["task"] == "zsh" and shell["ancestry"] == [101, 100]
    assert child["age_seconds"] == shell["age_seconds"] == 19 * 3600
    assert child["age_source"] == "process_started_epoch"
    assert child["socket_state"] == (socket_state or "unknown")
    assert child["socket_states"] == ([socket_state] if socket_state else [])
    assert all(row["restart_eligible"] is False for row in result["blocked_tasks"])
    if native_task_retained:
        tool = next(row for row in result["blocked_tasks"] if row["source"] == "native_tool")
        assert tool["step_index"] == 7 and tool["age_seconds"] == 19 * 3600
    assert "background task remains active" in result["excluded"][0]["reasons"]
    assert evidence.inputs == [] and evidence.records == processes_before
    assert not any("kill" in arg.casefold() for call in evidence.calls for arg in call)
