"""Offline acceptance and measurement contracts for the agy pressure guard."""
import copy

import pytest

from kg_microbe_workflows.port_pressure import (
    MeasurementError,
    decide,
    latch_failure,
    listener_measurement,
    normalize_config,
    parse_lsof,
    record_restart,
)

NOW = 10_000.0


def session(pid=42, key="traitmech", **changes):
    return {
        "repository_key": key, "pid": pid,
        "conversation_ids": {source: "conversation-one" for source in ("index", "supervisor", "log")},
        "verified_identity": True, "idle": True, "busy": False, "prompt": False,
        "blocked_tasks": [], **changes,
    }


def measurement(counts=None, *, host=100, **changes):
    counts = {42: 1001} if counts is None else counts
    return {"known": True, "host_listeners": host, "per_pid": counts,
            "agy_pids": list(counts), "ephemeral_low": 49152, "ephemeral_high": 65535,
            **changes}


def choose(rows=None, *, measured=None, state=None, config=None, now=NOW):
    return decide(config or {}, measured if measured is not None else measurement(),
                  [session()] if rows is None else rows, {} if state is None else state, now=now)


def socket(pid=42, command="agy", fd="4", address="127.0.0.1:50001", state="LISTEN", family="IPv4"):
    return f"p{pid}\nc{command}\nf{fd}\nt{family}\nn{address}\nTST={state}\nTQR=0\nTQS=0\n"


def command_result(stdout, *, returncode=0, stderr=""):
    return {"stdout": stdout, "returncode": returncode, "stderr": stderr}


def test_default_is_report_only_and_off_is_single_setting():
    assert normalize_config()["mode"] == "report"
    assert choose(config={"mode": "off"}, measured={"known": False})["phase"] == "off"
    assert choose(config={"mode": "off"})["candidate"] is None


@pytest.mark.parametrize("config", [
    {"mode": "apply"}, {"mode": True}, {"host_ratio": 0}, {"host_ratio": 1.01},
    {"host_ratio": float("nan")}, {"cooldown_seconds": 0}, {"hourly_cap": 0},
    {"hourly_cap": True}, {"per_pid_limit": 0}, {"hourly_capp": 3},
])
def test_invalid_settings_fail_closed(config):
    with pytest.raises(ValueError):
        normalize_config(config)
    result = choose(config=config)
    assert result["phase"] == "unknown" and result["disable_reason"]
    assert result["candidate"] is None


def test_per_pid_threshold_is_strictly_greater_than_one_thousand():
    boundary = choose(measured=measurement({42: 1000}))
    exceeded = choose(measured=measurement({42: 1001}))
    assert boundary["phase"] == "healthy" and boundary["healthy"] is True
    assert exceeded["phase"] == "candidate" and exceeded["candidate"]["pid"] == 42
    assert exceeded["healthy"] is False


def test_host_threshold_is_inclusive_and_uses_measured_range():
    below = measurement({42: 20}, host=49, ephemeral_low=100, ephemeral_high=199)
    at = measurement({42: 20}, host=50, ephemeral_low=100, ephemeral_high=199)
    assert choose(measured=below)["phase"] == "healthy"
    result = choose(measured=at)
    assert result["phase"] == "candidate"
    assert result["host_listener_ratio"] == 0.5


def test_host_pressure_does_not_spend_restart_quota_on_baseline_listener_session():
    result = choose(measured=measurement({42: 2}, host=9000))
    assert result["phase"] == "blocked" and result["candidate"] is None
    assert "baseline of 2" in result["excluded"][0]["reasons"][0]
    assert choose(measured=measurement({42: 3}, host=9000))["phase"] == "candidate"


@pytest.mark.parametrize("change", [
    {"busy": True}, {"idle": False}, {"prompt": True},
    {"busy": None}, {"idle": None}, {"prompt": None}, {"verified_identity": False},
    {"blocked_tasks": [{"task": "git push", "age_seconds": 7200, "socket_states": ["CLOSED"]}]},
])
def test_never_select_busy_prompting_unknown_or_background_session(change):
    other = session(43, "culturemech")
    result = choose([session(**change), other], measured=measurement({42: 4000, 43: 1200}))
    assert result["candidate"]["pid"] == 43
    assert result["excluded"][0]["pid"] == 42


def test_selects_only_one_largest_verified_idle_session():
    rows = [session(42, "traitmech"), session(43, "culturemech"), session(44, "habitatmech")]
    result = choose(rows, measured=measurement({42: 1001, 43: 3000, 44: 2000}))
    assert isinstance(result["candidate"], dict)
    assert result["candidate"]["pid"] == 43


def test_id_mismatch_stops_whole_guard_even_when_mismatched_session_busy():
    mismatched = session(busy=True)
    mismatched["conversation_ids"]["log"] = "different-conversation"
    result = choose([mismatched, session(43, "culturemech")], measured=measurement({42: 4000, 43: 2000}))
    assert result["phase"] == "unknown" and result["candidate"] is None
    assert "conversation-ID mismatch" in result["disable_reason"]


@pytest.mark.parametrize("source", ["index", "supervisor", "log"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_all_three_nonempty_ids_required_for_report_only_candidate(source, value):
    row = session()
    row["conversation_ids"][source] = value
    result = choose([row])
    assert result["candidate"] is None and result["disable_reason"]


@pytest.mark.parametrize("measured", [
    {"known": False, "error": "lsof denied"},
    measurement(known=False), measurement(known=None), measurement(host_listeners=None),
    measurement(per_pid={42: None}), measurement(agy_pids=[42, 43]),
    measurement(per_pid={}), measurement(ephemeral_low=None),
    measurement(ephemeral_high=70000), measurement(per_pid={42: True}),
])
def test_unknown_measurement_is_never_healthy(measured):
    result = choose(measured=measured)
    assert result["phase"] == "unknown"
    assert result["healthy"] is not True and result["candidate"] is None
    assert result["disable_reason"]


def test_unmanaged_offender_triggers_report_without_recycling_quiet_session():
    result = choose(measured=measurement({42: 2, 99: 3000}))
    assert result["phase"] == "blocked" and result["healthy"] is False
    assert result["unmanaged_offender_pids"] == [99]
    assert result["candidate"] is None


def test_busy_offender_does_not_justify_restarting_quiet_session():
    result = choose([session(busy=True), session(43, "culturemech")],
                    measured=measurement({42: 3000, 43: 2}))
    assert result["phase"] == "blocked" and result["candidate"] is None


def test_per_session_cooldown_survives_pid_change_and_expires_at_boundary():
    state = record_restart({}, "traitmech", 41, 42, now=NOW - 3599)
    assert choose(state=state)["phase"] == "blocked"
    assert choose(state=state)["excluded"][0]["reasons"] == ["session cooldown"]
    assert choose(state=state, now=NOW + 1)["candidate"]["pid"] == 42


def test_hourly_cap_counts_other_sessions_and_holds_at_boundary():
    state = {"restart_history": [
        {"repository_key": "culturemech", "completed_at": NOW - 3599},
        {"repository_key": "habitatmech", "completed_at": NOW - 10},
    ]}
    assert choose(state=state)["phase"] == "limited"
    assert choose(state=state, now=NOW + 1)["phase"] == "candidate"


@pytest.mark.parametrize("state", [
    {"disabled": "false"}, {"restart_history": {}},
    {"restart_history": [{"repository_key": "traitmech", "completed_at": NOW + 1}]},
    {"restart_history": [{"repository_key": "traitmech", "completed_at": "old"}]},
])
def test_corrupt_or_future_history_cannot_bypass_rate_limits(state):
    result = choose(state=state)
    assert result["phase"] == "unknown" and result["disable_reason"]


def test_first_failure_latches_and_cannot_be_erased_by_later_successful_observation():
    original = {"restart_history": []}
    latched = latch_failure(original, "conversation-ID mismatch", now=NOW)
    later = latch_failure(latched, "second failure", now=NOW + 10)
    assert original == {"restart_history": []}
    assert later["failure"] == {"reason": "conversation-ID mismatch", "at": NOW}
    assert choose(state=later)["phase"] == "disabled"
    with pytest.raises(ValueError, match="disabled"):
        record_restart(later, "traitmech", 41, 42, now=NOW + 20)


@pytest.mark.parametrize("state,measured", [
    ({}, {"known": False, "error": "partial lsof"}),
    ({"disabled": True, "failure": {"reason": "prior failure"}}, measurement()),
])
def test_blocked_task_age_and_closed_socket_report_survives_unknown_or_disabled(state, measured):
    task = {"task": "git push", "age_seconds": 21_000, "socket_states": ["CLOSED"]}
    row = session(busy=True, blocked_tasks=[task])
    result = choose([row], measured=measured, state=state)
    assert result["blocked_tasks"] == [{**task, "repository_key": "traitmech", "session_pid": 42}]
    assert result["candidate"] is None


def test_decision_does_not_mutate_inputs():
    inputs = ({}, measurement(), [session()], {})
    before = copy.deepcopy(inputs)
    decide(*inputs, now=NOW)
    assert inputs == before


def test_parse_lsof_preserves_closed_state_and_local_endpoint():
    rows = parse_lsof(socket(address="127.0.0.1:50001->127.0.0.1:50002", state="CLOSED", command="git"))
    assert rows == [{"pid": 42, "command": "git", "fd": "4", "type": "IPv4",
                     "address": "127.0.0.1:50001->127.0.0.1:50002", "state": "CLOSED", "loopback": True}]


@pytest.mark.parametrize("address,family,expected", [
    ("127.0.0.2:50001", "IPv4", True), ("[::1]:50001", "IPv6", True),
    ("[::ffff:127.0.0.1]:50001", "IPv6", True), ("*:50001", "IPv6", False),
    ("192.0.2.1:50001->127.0.0.1:50002", "IPv4", False),
])
def test_loopback_is_numeric_local_address_not_remote_endpoint(address, family, expected):
    assert parse_lsof(socket(address=address, family=family))[0]["loopback"] is expected


@pytest.mark.parametrize("text,code,stderr", [
    ("", 0, ""), ("", 1, ""), (socket(), 0, "lsof: partial visibility"),
    (socket(), 1, ""), ("p42\ncagy\n", 0, ""),
    (socket().replace("TST=LISTEN\n", ""), 0, ""),
    (socket().replace("LISTEN", "UNKNOWN_STATE"), 0, ""),
    (socket().replace("127.0.0.1:50001", "localhost:50001"), 0, ""),
    (socket() + "p43\ncagy\n", 0, ""), (socket() + socket(), 0, ""),
    (socket().replace("p42", "pnot-a-pid"), 0, ""),
    (socket().replace("f4", "fbad"), 0, ""),
])
def test_lsof_failures_and_partial_records_are_unknown(text, code, stderr):
    with pytest.raises(MeasurementError):
        parse_lsof(text, returncode=code, stderr=stderr)


def test_listener_counts_keep_all_host_rows_separate_from_agy_loopback_and_tcp_states():
    agy = socket() + socket(fd="5", address="*:50002") + socket(fd="6", state="CLOSED")
    other = socket(pid=99, command="server", address="192.0.2.1:8000")
    result = listener_measurement(command_result(agy + other), {42: command_result(agy)}, 49152, 65535)
    assert result["known"] is True
    assert result["host_listeners"] == 3
    assert result["per_pid"] == {"42": 1}
    assert result["host_listener_ratio"] == 3 / 16384


def test_known_zero_is_supported_only_by_positive_non_listening_socket_evidence():
    output = command_result(socket(state="CLOSED"))
    result = listener_measurement(output, {42: output}, 49152, 65535)
    assert result["known"] is True and result["host_listeners"] == 0
    assert result["per_pid"] == {"42": 0}


@pytest.mark.parametrize("pid_outputs", [
    {42: command_result("", returncode=1)},
    {42: command_result(socket(pid=43))},
    {42: command_result(socket(command="other"))},
    {42: {"stdout": socket(), "returncode": 0}},
    {42: command_result(socket()), "42": command_result(socket())},
])
def test_failed_pid_measurement_never_becomes_healthy_zero(pid_outputs):
    result = listener_measurement(command_result(socket()), pid_outputs, 49152, 65535)
    assert result["known"] is False and result["error"]
    decision = choose(measured=result)
    assert decision["healthy"] is not True and decision["disable_reason"]


@pytest.mark.parametrize("low,high", [(0, 65535), (50000, 49999), (49152, 65536), (None, 65535)])
def test_unknown_or_invalid_ephemeral_range_is_not_healthy(low, high):
    output = command_result(socket())
    result = listener_measurement(output, {42: output}, low, high)
    assert result["known"] is False


def test_unmanaged_process_measurement_failure_is_not_hidden():
    result = listener_measurement(command_result(socket()),
                                  {42: command_result(socket()), 99: command_result("", returncode=1)},
                                  49152, 65535)
    assert result["agy_pids"] == [42, 99]
    assert result["known"] is False


def test_restart_history_preserves_prior_rows_and_requires_new_pid():
    state = {"restart_history": [{"repository_key": "culturemech", "completed_at": NOW - 1}]}
    result = record_restart(state, "traitmech", 41, 42, now=NOW)
    assert len(state["restart_history"]) == 1 and len(result["restart_history"]) == 2
    assert result["restart_history"][-1]["new_pid"] == 42
    with pytest.raises(ValueError, match="new process"):
        record_restart(state, "traitmech", 42, 42, now=NOW)
