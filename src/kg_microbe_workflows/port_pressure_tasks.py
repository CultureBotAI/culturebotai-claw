"""Observational background-task blockers for the agy port-pressure guard.

Inputs are already collected native, Terminal, process and socket snapshots.
Nothing here reads processes, sends input, or terminates work. In particular a
missing connection never means CLOSED, and a CLOSED connection never makes a
running task eligible for restart. Native tools and child processes are separate
observations because a tool description alone does not establish a PID binding.
"""
from __future__ import annotations

import ipaddress
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import PurePath
from typing import Any

ACTIVE = {"pending", "running", "generating", "waiting", "queued"}


def _epoch(value: Any) -> float | None:
    if type(value) in (float, int):
        return float(value) if math.isfinite(value) and value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.timestamp()
    return None


def _age(start: Any, now: float, source: str) -> dict[str, Any]:
    epoch = _epoch(start)
    if epoch is None or epoch > now:
        return {"age_seconds": None, "age_source": "unknown"}
    return {"age_seconds": round(now - epoch, 3), "age_source": source}


def _endpoint(value: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"\[([^]]+)\]:(\d+)|([^\[\]]+):(\d+)", value)
    if not match:
        return None
    host, port = (match[1], match[2]) if match[1] else (match[3], match[4])
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if not address.is_loopback or not 0 < int(port) <= 65535:
        return None
    return str(address), int(port)


def _unknown(source: str, reason: str) -> dict[str, Any]:
    return {"source": source, "reason": reason, "task": "unknown",
            "age_seconds": None, "age_source": "unknown",
            "socket_state": "unknown", "socket_states": [],
            "socket_evidence": [], "restart_eligible": False}


def _proxy_states(pid: int, tcp: Mapping[int, Any], listeners: set[tuple[str, int]]) -> dict:
    observations = []
    observed_states: set[str] = set()
    rows = tcp.get(pid)
    if rows is not None and not isinstance(rows, list):
        raise ValueError("task socket inventory must contain lists or unknown values")
    for socket in rows or []:
        if not isinstance(socket, Mapping) or socket.get("pid") != pid:
            raise ValueError("task socket PID does not match its inventory owner")
        address = socket.get("address")
        if not isinstance(address, str) or address.count("->") != 1:
            continue
        local, remote = address.split("->")
        # A child socket must itself use loopback and connect to a listener
        # attributed to this agy process; another process's proxy is not ours.
        if _endpoint(local) is None or _endpoint(remote) not in listeners:
            continue
        state = socket.get("state")
        if not isinstance(state, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", state):
            continue
        observations.append({"fd": socket.get("fd"), "state": state,
                             "relation": "connection_to_agy_loopback_listener"})
        observed_states.add(state)
    states = sorted(observed_states)
    return {"socket_state": states[0] if len(states) == 1 else "multiple" if states else "unknown",
            "socket_states": states, "socket_evidence": observations}


def blocked_tasks(
    native: Mapping[str, Any], screen: str, processes: Sequence[Mapping[str, Any]],
    tcp: Mapping[int, Any], agy_pid: int, *, now: float,
) -> list[dict[str, Any]]:
    """Return task evidence that excludes this session from graceful restart.

    ``processes`` is a complete sampled process table with PID, PPID, comm and
    optional started_epoch. ``tcp`` maps each sampled PID to parsed lsof rows;
    missing/None entries mean unknown socket evidence. Invalid identities raise
    ValueError so the caller can fail closed. UI clock-only timestamps cannot
    establish an age because their date/timezone and rollover are unknown.
    """
    current = _epoch(now)
    if current is None or type(agy_pid) is not int or agy_pid <= 0:
        raise ValueError("task observation needs a valid time and agy PID")
    if not isinstance(native, Mapping) or not isinstance(screen, str):
        raise ValueError("native and Terminal task observations are malformed")
    if not isinstance(tcp, Mapping) or not isinstance(processes, (list, tuple)):
        raise ValueError("process and socket inventories are malformed")
    result: list[dict[str, Any]] = []
    tools = native.get("active_tools")
    if tools is None:
        result.append(_unknown("native_tools", "active-tool inventory unavailable"))
        tools = []
    if not isinstance(tools, list):
        raise ValueError("native active-tool inventory must be a list")
    for tool in tools:
        if not isinstance(tool, Mapping) or tool.get("status") not in ACTIVE:
            raise ValueError("native active-tool metadata is malformed")
        description = tool.get("toolSummary") or tool.get("toolAction") or tool.get("tool_name")
        result.append({**_unknown("native_tool", "native tool remains active"),
                       "task": description[:500] if isinstance(description, str) else "unknown",
                       "step_index": tool.get("step_index"), "state": tool["status"],
                       **_age(tool.get("created_at"), current, "native_created_at")})
    if not tools and native.get("native_execution_state") == "busy":
        step = native.get("last_step") or {}
        result.append({**_unknown("native_execution", "native execution remains busy"),
                       **_age(step.get("created_at"), current, "native_created_at")})

    table: dict[int, Mapping[str, Any]] = {}
    for process in processes:
        if not isinstance(process, Mapping):
            raise ValueError("process inventory entry must be an object")
        pid, ppid = process.get("pid"), process.get("ppid")
        if (type(pid) is not int or pid <= 0 or type(ppid) is not int or ppid < 0
                or pid in table or not isinstance(process.get("comm"), str)):
            raise ValueError("process inventory has an invalid or duplicate identity")
        table[pid] = process
    if agy_pid not in table:
        result.append(_unknown("process_inventory", "agy process is absent from the snapshot"))
        return result
    if PurePath(table[agy_pid]["comm"]).name != "agy":
        raise ValueError("task root is not an agy process")

    listeners: set[tuple[str, int]] = set()
    for socket in tcp.get(agy_pid) or []:
        if not isinstance(socket, Mapping) or socket.get("pid") != agy_pid:
            raise ValueError("agy listener PID does not match its inventory owner")
        if socket.get("state") == "LISTEN" and isinstance(socket.get("address"), str):
            endpoint = _endpoint(socket["address"])
            if endpoint:
                listeners.add(endpoint)
    for pid, process in sorted(table.items()):
        if pid == agy_pid:
            continue
        ancestry = [pid]
        cursor = process
        while cursor["ppid"] in table:
            parent = table[cursor["ppid"]]
            if parent["pid"] in ancestry:
                raise ValueError("process inventory contains an ancestry cycle")
            child_start, parent_start = _epoch(cursor.get("started_epoch")), _epoch(parent.get("started_epoch"))
            if child_start is not None and parent_start is not None and child_start < parent_start:
                raise ValueError("process ancestry contradicts process start times")
            ancestry.append(parent["pid"])
            if parent["pid"] == agy_pid:
                result.append({**_unknown("child_process", "live descendant remains a task blocker"),
                               "task": PurePath(process["comm"]).name, "pid": pid,
                               "ppid": process["ppid"], "ancestry": ancestry,
                               **_age(process.get("started_epoch"), current, "process_started_epoch"),
                               **_proxy_states(pid, tcp, listeners)})
                break
            cursor = parent

    footer = "\n".join(screen.replace("\r", "").splitlines()[-32:])
    running = re.findall(r"^\s*●\s+\[([^\]\n]+)\]\s+(.+?)\s+running\s*$", footer, re.M)
    for clock, task in running:
        result.append({**_unknown("terminal", "Terminal reports a running background task"),
                       "task": task[:500], "displayed_clock": clock})
    if not running and re.search(
        r"\b[1-9]\d* (?:background )?task\(s\)|\b[1-9]\d* background tasks?\b|"
        r"\bbackground tasks?:\s*[1-9]\d*|^\s*● .* running\s*$", footer, re.I | re.M,
    ):
        result.append(_unknown("terminal", "Terminal reports running/background tasks"))
    return result
