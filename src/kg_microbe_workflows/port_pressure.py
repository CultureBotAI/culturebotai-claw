"""Pure measurement parsing and fail-closed selection for the agy guard.

This module never discovers processes, sends input, restarts sessions or writes
state. The supervisor supplies fresh observations and owns those operations.
Listener rows are deliberately distinct from unique occupied ephemeral ports.
"""
from __future__ import annotations

import copy
import ipaddress
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULTS: dict[str, Any] = {
    "mode": "report",
    "restart_policy": "goal_boundary_or_idle",
    "host_ratio": 0.5,
    "per_pid_limit": 1000,
    "goal_boundary_limit": 500,
    "restart_repository_keys": None,
    "cooldown_seconds": 3600,
    "hourly_cap": 2,
}
ID_SOURCES = ("index", "supervisor", "log")
TCP_STATES = {
    "BOUND", "CLOSED", "CLOSE_WAIT", "CLOSING", "ESTABLISHED", "FIN_WAIT_1",
    "FIN_WAIT_2", "IDLE", "LAST_ACK", "LISTEN", "SYN_SENT", "SYN_RCVD",
    "SYN_RECEIVED", "TIME_WAIT",
}


class MeasurementError(ValueError):
    """The supplied observation cannot establish a listener count."""


def _number(value: Any, label: str, *, minimum: float = 0) -> float:
    try:
        converted = float(value) if type(value) in (int, float) else math.nan
    except OverflowError:
        converted = math.nan
    if not math.isfinite(converted) or converted < minimum:
        raise ValueError(f"{label} must be a finite number >= {minimum}")
    return converted


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _pid(value: Any) -> int:
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        return int(value)
    return _integer(value, "PID", minimum=1)


def normalize_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate the policy settings; an omitted guard starts in report mode."""
    if config is not None and not isinstance(config, Mapping):
        raise ValueError("port-pressure settings must be an object")
    result = {**DEFAULTS, **(config or {})}
    if set(result) - set(DEFAULTS):
        raise ValueError("unknown port-pressure policy settings")
    if result["mode"] not in {"off", "report", "restart"}:
        raise ValueError("port-pressure mode must be off, report or restart")
    if (not isinstance(result["restart_policy"], str)
            or result["restart_policy"] not in {"goal_boundary_only", "goal_boundary_or_idle"}):
        raise ValueError("restart_policy must be goal_boundary_only or goal_boundary_or_idle")
    ratio = _number(result["host_ratio"], "host_ratio")
    if not 0 < ratio <= 1:
        raise ValueError("host_ratio must be greater than zero and at most one")
    _integer(result["per_pid_limit"], "per_pid_limit", minimum=1)
    _integer(result["goal_boundary_limit"], "goal_boundary_limit", minimum=3)
    allowed = result["restart_repository_keys"]
    if allowed is not None and (not isinstance(allowed, list)
                               or any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", key)
                                      for key in allowed)
                               or len(set(allowed)) != len(allowed)):
        raise ValueError("restart_repository_keys must be null or a list of unique repository keys")
    _number(result["cooldown_seconds"], "cooldown_seconds", minimum=1)
    _integer(result["hourly_cap"], "hourly_cap", minimum=1)
    return result


def _loopback(address: str) -> bool:
    local = address.split("->", 1)[0]
    if local.startswith("["):
        match = re.fullmatch(r"\[([^]]+)\]:([0-9]+)", local)
    else:
        match = re.fullmatch(r"(.+):([0-9]+)", local)
    if not match or not 0 <= int(match[2]) <= 65535:
        raise MeasurementError("lsof socket address is missing a numeric port")
    host = match[1]
    if host == "*":
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as error:
        raise MeasurementError("lsof socket address is not numeric") from error
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def parse_lsof(text: str, *, returncode: int = 0, stderr: str = "") -> list[dict[str, Any]]:
    """Parse ``lsof -nP ... -iTCP -FpcfntT`` without guessing missing fields.

    The caller supplies the real exit status and stderr. In particular lsof's
    exit 1 / empty output is unknown, not a verified zero. Every socket keeps
    its TCP state, including CLOSED, for observational blocked-task reports.
    """
    if type(returncode) is not int or returncode != 0 or stderr.strip():
        raise MeasurementError("lsof failed or reported incomplete visibility")
    if not isinstance(text, str) or not text.strip():
        raise MeasurementError("lsof returned no process/socket evidence")
    records: list[dict[str, Any]] = []
    process: dict[str, Any] = {}
    process_has_socket = False
    record: dict[str, Any] | None = None
    seen: set[tuple[int, str]] = set()

    def finish() -> None:
        nonlocal record, process_has_socket
        if record is None:
            return
        if any(key not in record for key in ("pid", "command", "fd", "type", "address", "state")):
            raise MeasurementError("lsof socket record is incomplete")
        if record["type"] not in {"IPv4", "IPv6"}:
            raise MeasurementError("lsof TCP record has an unsupported address family")
        if record["state"] not in TCP_STATES:
            raise MeasurementError("lsof TCP state is malformed")
        identity = (record["pid"], record["fd"])
        if identity in seen:
            raise MeasurementError("lsof repeated a process/file descriptor")
        seen.add(identity)
        record["loopback"] = _loopback(record["address"])
        records.append(record)
        process_has_socket = True
        record = None

    for line in text.replace("\0", "\n").splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            finish()
            if process and not process_has_socket:
                raise MeasurementError("lsof process has no socket evidence")
            try:
                process = {"pid": _pid(value)}
                process_has_socket = False
            except ValueError as error:
                raise MeasurementError("lsof process ID is malformed") from error
        elif field == "c":
            if not process or "command" in process or record is not None or not value:
                raise MeasurementError("lsof command has no unambiguous process")
            process["command"] = value
        elif field == "f":
            finish()
            if set(process) != {"pid", "command"} or not re.fullmatch(r"[0-9]+[a-zA-Z]*", value):
                raise MeasurementError("lsof socket has no unambiguous process/file descriptor")
            record = {**process, "fd": value}
        elif field in {"t", "n"}:
            key = {"t": "type", "n": "address"}[field]
            if record is None or key in record or not value:
                raise MeasurementError("lsof socket field is missing or repeated")
            record[key] = value
        elif field == "T":
            if record is None or "=" not in value:
                raise MeasurementError("lsof TCP details have no socket")
            key, detail = value.split("=", 1)
            if key == "ST":
                if "state" in record or not detail:
                    raise MeasurementError("lsof TCP state is missing or repeated")
                record["state"] = detail
        else:
            raise MeasurementError("unexpected lsof field; require -FpcfntT TCP output")
    finish()
    if not records or not process_has_socket:
        raise MeasurementError("lsof returned no socket records")
    return records


def listener_measurement(
    host_output: Mapping[str, Any],
    pid_outputs: Mapping[int | str, Mapping[str, Any]],
    ephemeral_low: int,
    ephemeral_high: int,
) -> dict[str, Any]:
    """Build counts from actual command results, retaining failures as unknown.

    ``pid_outputs`` contains one result for every discovered agy process,
    including processes outside the configured supervisor targets. Host counts
    include all TCP LISTEN rows; agy counts include only loopback LISTEN rows.
    Neither count is a unique-port occupancy measurement.
    """
    result: dict[str, Any] = {
        "known": False, "host_listeners": None, "per_pid": {}, "agy_pids": [],
        "ephemeral_low": ephemeral_low, "ephemeral_high": ephemeral_high,
        "host_listener_ratio": None,
    }

    def parse(output: Mapping[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(output, Mapping) or not {"stdout", "returncode", "stderr"} <= set(output):
            raise MeasurementError("command result is missing stdout, stderr or exit status")
        if not isinstance(output.get("stdout"), str) or not isinstance(output.get("stderr"), str):
            raise MeasurementError("command result is not textual")
        return parse_lsof(output["stdout"], returncode=output["returncode"], stderr=output["stderr"])

    try:
        low = _integer(ephemeral_low, "ephemeral_low", minimum=1)
        high = _integer(ephemeral_high, "ephemeral_high", minimum=low)
        if high > 65535:
            raise MeasurementError("ephemeral port range exceeds TCP port bounds")
        if not isinstance(pid_outputs, Mapping):
            raise MeasurementError("per-PID command results must be an object")
        pids = [_pid(pid) for pid in pid_outputs]
        if len(set(pids)) != len(pids):
            raise MeasurementError("duplicate PID command results")
        result["agy_pids"] = sorted(pids)
        host = parse(host_output)
        result["host_listeners"] = sum(row["state"] == "LISTEN" for row in host)
        for key, output in pid_outputs.items():
            pid = _pid(key)
            rows = parse(output)
            if any(row["pid"] != pid or row["command"] != "agy" for row in rows):
                raise MeasurementError("per-PID output does not identify exactly the requested agy")
            result["per_pid"][str(pid)] = sum(
                row["state"] == "LISTEN" and row["loopback"] for row in rows
            )
        result["host_listener_ratio"] = result["host_listeners"] / (high - low + 1)
        result["known"] = True
    except (ValueError, TypeError, KeyError) as error:
        result["error"] = str(error)
    return result


def _history(state: Mapping[str, Any], now: float) -> list[dict[str, Any]]:
    if type(state.get("disabled", False)) is not bool:
        raise ValueError("guard disabled flag is invalid")
    raw = state.get("restart_history", [])
    if not isinstance(raw, list):
        raise ValueError("restart history is not a list")
    history = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("repository_key"), str) or not entry["repository_key"]:
            raise ValueError("restart history has an invalid session identity")
        completed = _number(entry.get("completed_at"), "restart completion time")
        if completed > now:
            raise ValueError("restart history is in the future; clock continuity is unknown")
        history.append(entry)
    return history


def decide(
    config: Mapping[str, Any], measurement: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]], state: Mapping[str, Any], *, now: float,
    boundary: Mapping[str, Any] | None = None,
    excluded_repository_keys: Sequence[str] = (),
) -> dict[str, Any]:
    """Report at most one eligible restart; no state or input object is mutated."""
    result: dict[str, Any] = {
        "phase": "unknown", "healthy": None, "candidate": None,
        "triggers": [], "excluded": [], "blocked_tasks": [], "disable_reason": None,
    }
    try:
        if not isinstance(sessions, Sequence) or isinstance(sessions, (str, bytes)):
            raise ValueError("session observations must be a list")
        for session in sessions:
            if not isinstance(session, Mapping):
                raise ValueError("session observation must be an object")
            tasks = session.get("blocked_tasks", [])
            if not isinstance(tasks, list) or any(not isinstance(task, Mapping) for task in tasks):
                raise ValueError("background task observations must be a list of objects")
            for task in tasks:
                result["blocked_tasks"].append({
                    **copy.deepcopy(task), "repository_key": session.get("repository_key"),
                    "session_pid": session.get("pid"),
                })
        if not isinstance(state, Mapping) or not isinstance(measurement, Mapping):
            raise ValueError("guard state and measurement must be objects")
        settings = normalize_config(config)
        if (not isinstance(excluded_repository_keys, (list, tuple))
                or any(not isinstance(key, str) for key in excluded_repository_keys)):
            raise ValueError("per-tick excluded repository keys are invalid")
        if boundary is not None:
            if (not isinstance(boundary, Mapping) or not isinstance(boundary.get("repository_key"), str)
                    or not boundary["repository_key"]):
                raise ValueError("goal boundary target is invalid")
            boundary_pid = _pid(boundary.get("pid"))
            if sum(session.get("repository_key") == boundary["repository_key"]
                   and session.get("pid") == boundary_pid for session in sessions) != 1:
                raise ValueError("goal boundary target is missing or ambiguous")
        timestamp = _number(now, "current time")
        if settings["mode"] == "off":
            result["phase"] = "off"
            return result
        if state.get("disabled") is True:
            failure = state.get("failure")
            reason = failure.get("reason") if isinstance(failure, Mapping) else None
            result.update(phase="disabled", disable_reason=reason or "guard is latched off")
            return result
        history = _history(state, timestamp)
        allowed = settings["restart_repository_keys"]
        if boundary is not None and allowed is not None and boundary["repository_key"] not in allowed:
            result.update(phase="off", reason="goal-boundary target is outside restart_repository_keys")
            return result
        if measurement.get("known") is not True:
            raise ValueError("listener measurement is unknown: " + str(measurement.get("error", "missing observation")))
        host = _integer(measurement.get("host_listeners"), "host listener count")
        low = _integer(measurement.get("ephemeral_low"), "ephemeral_low", minimum=1)
        high = _integer(measurement.get("ephemeral_high"), "ephemeral_high", minimum=low)
        if high > 65535:
            raise ValueError("ephemeral port range exceeds TCP port bounds")
        raw_counts = measurement.get("per_pid")
        if not isinstance(raw_counts, Mapping):
            raise ValueError("per-PID listener measurement is unavailable")
        counts = {_pid(pid): _integer(count, "per-PID listener count") for pid, count in raw_counts.items()}
        if len(counts) != len(raw_counts):
            raise ValueError("per-PID listener measurement has duplicate process identities")
        raw_discovered = measurement.get("agy_pids", list(counts))
        if not isinstance(raw_discovered, (list, tuple)):
            raise ValueError("discovered agy process identities must be a list")
        discovered = {_pid(pid) for pid in raw_discovered}
        if len(discovered) != len(raw_discovered):
            raise ValueError("discovered agy process identities are duplicated")
        if discovered != set(counts):
            raise ValueError("listener count is missing for a discovered agy process")
        if any(_pid(session.get("pid")) not in counts for session in sessions):
            raise ValueError("listener count is missing for a configured session")
        keys: set[str] = set()
        seen_pids: set[int] = set()
        eligible = []
        for session in sessions:
            pid = _pid(session.get("pid"))
            key = session.get("repository_key")
            if not isinstance(key, str) or not key or key in keys or pid in seen_pids:
                raise ValueError("configured sessions have ambiguous identities")
            keys.add(key)
            seen_pids.add(pid)
            identities = session.get("conversation_ids")
            if not isinstance(identities, Mapping):
                raise ValueError(f"{key}: conversation IDs are unavailable")
            values = [identities.get(source) for source in ID_SOURCES]
            present = {value for value in values if isinstance(value, str) and value}
            if len(present) > 1:
                raise ValueError(f"{key}: conversation-ID mismatch")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{key}: all three conversation IDs are required")
            reasons = []
            if key in excluded_repository_keys:
                reasons.append("workflow dispatch was attempted in this supervisor tick")
            if allowed is not None and key not in allowed:
                reasons.append("repository is outside restart_repository_keys")
            if session.get("verified_identity") is not True:
                reasons.append("process identity is not verified")
            if session.get("idle") is not True:
                reasons.append("session is not verified idle")
            if session.get("busy") is not False:
                reasons.append("session is busy or activity is unknown")
            if session.get("prompt") is not False:
                reasons.append("session is prompting or prompt state is unknown")
            if session.get("blocked_tasks"):
                reasons.append("background task remains active")
            if counts[pid] <= 2:
                reasons.append("no reclaimable leaked listeners above the baseline of 2")
            if session.get("error"):
                raise ValueError(f"{key}: observation failed: {session['error']}")
            previous = [row["completed_at"] for row in history if row["repository_key"] == key]
            if previous and timestamp - max(previous) < settings["cooldown_seconds"]:
                reasons.append("session cooldown")
            if reasons:
                result["excluded"].append({"repository_key": key, "pid": pid, "reasons": reasons})
            else:
                eligible.append({**copy.deepcopy(session), "listeners": counts[pid]})
        ratio = host / (high - low + 1)
        result["host_listener_ratio"] = ratio
        if ratio >= settings["host_ratio"]:
            result["triggers"].append("host listener ratio at or above threshold")
        offenders = sorted(pid for pid, count in counts.items() if count > settings["per_pid_limit"])
        if offenders:
            result["triggers"].append("agy process above per-PID listener limit")
        result["offender_pids"] = offenders
        result["unmanaged_offender_pids"] = [pid for pid in offenders if pid not in seen_pids]
        if boundary is not None:
            # Goal-boundary maintenance belongs only to the completed session.
            # An unrelated host/per-PID offender cannot redirect this operation.
            result["triggers"] = []
            if counts[boundary_pid] >= settings["goal_boundary_limit"]:
                result["triggers"].append("completed goal at or above goal-boundary listener threshold")
            eligible = [session for session in eligible if session["pid"] == boundary_pid
                        and session["repository_key"] == boundary["repository_key"]]
            result["boundary"] = {"repository_key": boundary["repository_key"], "pid": boundary_pid}
        if not result["triggers"]:
            result.update(phase="healthy", healthy=True)
            return result
        result["healthy"] = False
        if boundary is None and settings["restart_policy"] == "goal_boundary_only":
            result.update(phase="blocked", policy_hold="goal-boundary-only policy requires a verified goal boundary")
            return result
        if sum(timestamp - row["completed_at"] < 3600 for row in history) >= settings["hourly_cap"]:
            result["phase"] = "limited"
            result["limit_reason"] = "hourly restart cap"
            return result
        # A per-PID-only trigger cannot justify recycling unrelated quiet sessions.
        if boundary is None and ratio < settings["host_ratio"]:
            eligible = [session for session in eligible if session["pid"] in offenders]
        if not eligible:
            result["phase"] = "blocked"
            return result
        result.update(phase="candidate", candidate=max(eligible, key=lambda row: (row["listeners"], -row["pid"])))
        return result
    except (ValueError, TypeError, KeyError) as error:
        result.update(phase="unknown", healthy=None, candidate=None, disable_reason=str(error))
        return result


def latch_failure(state: Mapping[str, Any], reason: str, *, now: float) -> dict[str, Any]:
    """Return a durable-state value that remembers the first failure only."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("failure reason is required")
    timestamp = _number(now, "failure time")
    result = copy.deepcopy(dict(state))
    if result.get("disabled") is not True:
        result.update(disabled=True, failure={"reason": reason, "at": timestamp})
    return result


def record_restart(
    state: Mapping[str, Any], repository_key: str, pid: int, new_pid: int, *, now: float,
) -> dict[str, Any]:
    """Record a verified completed restart, preserving earlier cooldown history."""
    timestamp = _number(now, "restart time")
    history = _history(state, timestamp)
    if state.get("disabled") is True:
        raise ValueError("cannot record a restart while the guard is disabled")
    if not isinstance(repository_key, str) or not repository_key:
        raise ValueError("restart session identity is required")
    if _pid(pid) == _pid(new_pid):
        raise ValueError("a restart must establish a new process")
    result = copy.deepcopy(dict(state))
    result["restart_history"] = copy.deepcopy(history) + [{
        "repository_key": repository_key, "pid": pid, "new_pid": new_pid,
        "completed_at": timestamp,
    }]
    return result
