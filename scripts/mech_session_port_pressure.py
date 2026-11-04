#!/usr/bin/env python3
"""Fail-closed, local-only maintenance for owned idle agy sessions (#725).

Importing this adapter performs no observation or input. The supervisor invokes
it explicitly; off is the compatibility default and report never sends input.
All action dependencies are injectable so the complete transaction is tested
without a live Terminal, agent, provider, or network service.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shlex
import time
from datetime import datetime
from pathlib import Path

from kg_microbe_workflows.port_pressure import (
    decide,
    latch_failure,
    listener_measurement,
    normalize_config,
    parse_lsof,
    record_restart,
)
from kg_microbe_workflows.port_pressure_tasks import blocked_tasks

UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
# Same prompt vocabulary as XMechBay's mac-orchestration guard, with native agy
# approval/tool menus included. There is deliberately no override path here.
PROMPT = re.compile(
    r"Sign in with|authentication required|Log in to continue|Select a login|"
    r"Trust this folder|Do you trust|trust the (?:files|contents)|"
    r"Update available|Skip until next version|Update now|"
    r"approval request|Allow command|Requesting permission|Do you want to|"
    r"Allow sandbox bypass|Confirm the command is safe|Would you like to|"
    r"Allow access to this file\?|Run this command\?|Accept changes\?|"
    r"ctrl\+k\s+approve|needs approval for|↑/↓\s*Navigate|"
    r"Queued follow-up|⇧← to answer|request_user_input|"
    r"^\s*(?:Question|Questions|QUESTION)\b|Type your answer|to submit answer|"
    r"to navigate questions|Select Model|Select Reasoning|"
    r"How's the CLI experience|^\s*\?\s+(?:Which|.*question)|"
    r"^\s*(?:Select|Choose) (?:an? option|one of the following)|"
    r"^\s*[›❯>]?\s*\d+[.)]\s+(?:Yes|No|Allow|Deny|Approve|Reject|Cancel)\b",
    re.I | re.M,
)


class GuardError(RuntimeError):
    """A failed check permanently stops this guard until operator recovery."""


def require(condition, message):
    if not condition:
        raise GuardError(message)


def raw_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def log_conversation(text):
    ids = set(re.findall(
        r'(?:conversation_id|conversationId|Conversation ID)["\s]*[=:]\s*["\']?(' + UUID + ')',
        text,
    ))
    require(len(ids) == 1, "PID-owned log conversation ID missing or ambiguous")
    return ids.pop().lower()


def model_evidence(screen, identity):
    require(isinstance(identity, dict), "restart model/effort identity is unconfigured")
    for name in ("model", "effort", "model_label", "effort_label", "agy_executable"):
        require(isinstance(identity.get(name), str) and identity[name].strip()
                and not any(c in identity[name] for c in "\0\r\n"), "invalid restart " + name)
    lines = screen.rstrip().splitlines()
    composers = [i for i, line in enumerate(lines) if line.strip() == ">"]
    footer = lines[max(composers[-1] + 1 if composers else 0, len(lines) - 9):]
    # Native model/effort are complete footer fields, never substrings of a
    # different model or effort (e.g. Pro Max or highest).
    model_lines = [line for line in footer if re.search(r"\bGemini\b", line)]
    value = model_lines[-1][model_lines[-1].index("Gemini"):].strip() if model_lines else ""
    fields = [part.strip() for part in re.split(r"[|·]", value)]
    delimited = len(fields) >= 2 and fields[:2] == [identity["model_label"], identity["effort_label"]]
    parenthesized = re.fullmatch(re.escape(identity["model_label"]) + r"\s*\("
                                + re.escape(identity["effort_label"]) + r"\)(?:\s*[|·].*)?", value)
    require(delimited or parenthesized,
            "current footer does not prove configured model and effort")
    return {key: identity[key] for key in ("model", "effort", "model_label", "effort_label")}


def fresh_output(before, after):
    """Only accept output appended after the guarded /quit input."""
    anchor = before[-1024:]
    require(len(anchor) >= 20, "insufficient shutdown screen boundary")
    offset = after.rfind(anchor)
    require(offset >= 0, "shutdown output boundary unavailable")
    return after[offset + len(anchor):]


def process_table(text):
    rows = []
    for line in text.splitlines():
        parts = line.split(None, 8)
        require(len(parts) == 9 and parts[0].isdigit() and parts[1].isdigit(),
                "unreadable process table")
        stamp = datetime.strptime(" ".join(parts[3:8]), "%a %b %d %H:%M:%S %Y").astimezone()
        rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "tty": "/dev/" + parts[2],
                     "comm": parts[8], "started_epoch": stamp.timestamp()})
    require(bool(rows), "empty process table")
    return rows


class NativeTransport:
    def __init__(self, supervisor, *, clock=time.time, sleep=time.sleep):
        self.s = supervisor
        self.clock = clock
        self.sleep = sleep
        self.helpers = supervisor._port_pressure_helpers
        self.before_quit = None
        self.binding_plan = None

    def run(self, args, **kwargs):
        return self.s.runner(args, **kwargs)

    def processes(self):
        return process_table(self.run([
            "/usr/bin/env", "LC_ALL=C", "/bin/ps", "-ax", "-o", "pid=,ppid=,tty=,lstart=,comm=",
        ]).stdout)

    def sockets(self, pid=None, *, listen=False):
        args = ["/usr/sbin/lsof", "-nP"]
        if pid is not None:
            args += ["-a", "-p", str(pid)]
        args += ["-iTCP"]
        if listen:
            args += ["-sTCP:LISTEN"]
        result = self.run(args + ["-FpcfntT"], check=False)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}

    def log_id(self, pid):
        output = self.run(["/usr/sbin/lsof", "-a", "-p", str(pid), "-Fn"]).stdout
        paths = {Path(line[1:]) for line in output.splitlines() if line.startswith("n")
                 and re.search(r"/log/cli-[^/]+\.log$", line[1:])}
        require(len(paths) == 1, "PID-owned native log missing or ambiguous")
        path = paths.pop()
        require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 64 * 1024 * 1024,
                "PID-owned log is unsafe or exceeds read bound")
        return log_conversation(path.read_text())

    def snapshot(self, target):
        result = json.loads(self.s.notifier.jxa(self.s.notifier.SNAPSHOT_JS, [target["tty"]]))
        tabs = result.get("tabs", [])
        require(len(tabs) == 1 and tabs[0]["tty"] == target["tty"], "Terminal target ambiguous")
        return tabs[0]

    def observe(self, target, processes=None):
        processes = processes if processes is not None else self.processes()
        base = self.s.observe(target, fresh=True, allow_redraw=False)
        row = {"repository_key": target["repository_key"], "pid": target["pid"],
               "verified_identity": False, "idle": False, "busy": True, "prompt": False,
               "conversation_ids": {}, "blocked_tasks": [], "observation": base}
        screen = base.get("tab", {}).get("screen", "")
        row["prompt"] = bool(PROMPT.search(screen))
        native = base.get("native", {})
        tcp = {}
        # Child process sockets are evidence about blocked work, never authority
        # to terminate it. Failure to read them remains explicitly unknown.
        descendants = {target["pid"]}
        while True:
            expanded = descendants | {p["pid"] for p in processes if p["ppid"] in descendants}
            if expanded == descendants:
                break
            descendants = expanded
        for pid in descendants:
            try:
                result = self.sockets(pid)
                tcp[pid] = parse_lsof(**{"text": result["stdout"], "returncode": result["returncode"],
                                        "stderr": result["stderr"]})
            except Exception:
                tcp[pid] = []
        row["blocked_tasks"] = blocked_tasks(native, screen, processes, tcp, target["pid"], now=self.clock())
        row["busy"] = (native.get("native_execution_state") != "idle_candidate"
                       or bool(row["blocked_tasks"]) or bool(self.helpers["busy"](screen)))
        try:
            cache = self.helpers["read_json"](Path(self.s.config.get(
                "conversation_cache_path", Path.home() / ".gemini/antigravity-cli/cache/last_conversations.json")))
            status = self.helpers["read_json"](self.s.directory(target) / "status.json")
            row["conversation_ids"] = {
                "index": cache.get(str(Path(target["root"]).resolve())),
                "supervisor": (status.get("goal_identity") or {}).get("conversation_id"),
                "log": self.log_id(target["pid"]),
            }
            require(status.get("run_id") == self.s.config["run_id"]
                    and status.get("repository_key") == target["repository_key"], "foreign supervisor status")
            require(set(row["conversation_ids"].values()) == {target["native_session_id"]},
                    "conversation ID disagreement")
            require(not base.get("error"), base.get("error", "native identity unavailable"))
            # Also exclude another agy in this cwd, even on a different TTY.
            for proc in processes:
                if Path(proc["comm"]).name == "agy" and proc["pid"] != target["pid"]:
                    require(self.s.notifier.process_cwd(proc["pid"]) != Path(target["root"]).resolve(),
                            "another agy is live in the same directory")
                    require(self.log_id(proc["pid"]) != target["native_session_id"],
                            "conversation is already live in another agy process")
            row["model_evidence"] = model_evidence(screen, target.get("port_pressure_identity"))
            row["verified_identity"] = True
            row["idle"] = base.get("ready") is True and not row["busy"] and not row["prompt"]
        except Exception as error:
            row["error"] = str(error)[:400]
        return row

    def collect(self):
        processes = self.processes()
        pids = [p["pid"] for p in processes if Path(p["comm"]).name == "agy"]
        limits = self.run(["/usr/sbin/sysctl", "-n", "net.inet.ip.portrange.first",
                           "net.inet.ip.portrange.last"]).stdout.split()
        require(len(limits) == 2 and all(v.isdigit() for v in limits), "ephemeral range unknown")
        measurement = listener_measurement(self.sockets(listen=True),
                                           {pid: self.sockets(pid, listen=True) for pid in pids},
                                           int(limits[0]), int(limits[1]))
        return measurement, [self.observe(t, processes) for t in self.s.config["targets"]]

    def preflight(self, target):
        current = self.observe(target)
        require(current["idle"] and current["verified_identity"], "session no longer verified idle")
        require(not current["prompt"] and not current["blocked_tasks"], "human prompt or background task")
        identity = target["port_pressure_identity"]
        executable = Path(identity["agy_executable"])
        require(executable.is_absolute() and executable.is_file() and os.access(executable, os.X_OK),
                "agy executable is unavailable")
        text = self.run(["/usr/sbin/lsof", "-a", "-p", str(target["pid"]), "-d", "txt", "-Fn"]).stdout
        require(any(Path(line[1:]).resolve() == executable.resolve() for line in text.splitlines()
                    if line.startswith("n")), "configured executable differs from running agy")
        self.binding_plan = binding_plan(self.s, target, self.helpers["read_json"])
        self.before_quit = current
        return current

    def quit(self, target):
        # Last acquisition of all three IDs is the penultimate operation. The
        # final interaction is /quit; there is no status message or goal replay.
        current = self.preflight(target)
        tab = current["observation"]["tab"]
        result = self.s.notifier.jxa(self.helpers["send_js"], {
            **tab, "pid": target["pid"], "identity": target["process_identity"],
            "cwd": target["root"], "message": "/quit",
        })
        require(result == "sent", "guarded /quit was not confirmed")

    def wait_exit(self, target, timeout):
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            result = self.run(["/bin/ps", "-p", str(target["pid"]), "-o", "pid=,tty=,lstart=,comm="], check=False)
            require(result.returncode in (0, 1), "old PID exit measurement failed")
            if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
                tab = self.snapshot(target)
                old_tab = self.before_quit["observation"]["tab"]
                require(all(tab[k] == old_tab[k] for k in ("window", "tab", "tty")), "Terminal binding changed")
                appended = fresh_output(old_tab["screen"], tab["screen"])
                ids = re.findall(r"\bagy\s+--conversation(?:=|\s+)[\"']?(" + UUID + ")", appended)
                require(ids == [target["native_session_id"]], "fresh printed resume ID missing or mismatched")
                require(not PROMPT.search(appended), "prompt after shutdown")
                require(re.search(r"[#$%>]\s*$", appended), "returned shell prompt unverified")
                peers = [p for p in self.processes() if p["tty"] == target["tty"]]
                require(not any(Path(p["comm"]).name == "agy" for p in peers), "live agy remains on TTY")
                shells = [p for p in peers if Path(p["comm"]).name in {"bash", "zsh", "sh"}
                          and self.s.notifier.foreground(p["pid"], target["tty"])]
                require(len(shells) == 1, "returned foreground shell ambiguous")
                shell = shells[0]
                require(self.s.notifier.process_cwd(shell["pid"]) == Path(target["root"]).resolve(),
                        "returned shell cwd changed")
                shell["identity"] = self.run(["/bin/ps", "-p", str(shell["pid"]), "-o",
                                              "pid=,tty=,lstart=,comm="]).stdout.strip()
                return {"tab": tab, "shell": shell}
            if result.stdout.strip():
                require(result.stdout.strip() == target["process_identity"], "old PID reused or identity changed")
            self.sleep(0.25)
        raise GuardError("old PID did not exit before deadline")

    def resume(self, target, returned):
        tab, shell = returned["tab"], returned["shell"]
        identity = target["port_pressure_identity"]
        require(re.fullmatch(UUID, target["native_session_id"]), "invalid explicit conversation ID")
        exited = self.run(["/bin/ps", "-p", str(target["pid"]), "-o", "pid="], check=False)
        require(exited.returncode == 1 and not exited.stdout.strip() and not exited.stderr.strip(),
                "old PID absence no longer verified")
        processes = self.processes()
        peers = [p for p in processes if Path(p["comm"]).name == "agy"]
        for peer in peers:
            require(peer["tty"] != target["tty"], "another agy occupies the resume TTY")
            require(self.s.notifier.process_cwd(peer["pid"]) != Path(target["root"]).resolve(),
                    "another agy claimed the working directory before resume")
            require(self.log_id(peer["pid"]) != target["native_session_id"],
                    "another agy claimed the conversation before resume")
        inventory = sorted(line.strip() for line in self.run([
            "/bin/ps", "-ax", "-o", "pid=,tty=,lstart=,comm=",
        ]).stdout.splitlines() if re.search(r"(?:^|\s)agy$", line.strip()))
        require({int(line.split()[0]) for line in inventory} == {p["pid"] for p in peers},
                "agy process inventory changed during resume checks")
        args = [identity["agy_executable"], "--conversation=" + target["native_session_id"],
                "--model=" + identity["model"], "--effort=" + identity["effort"]]
        result = self.s.notifier.jxa(self.helpers["send_js"], {
            **tab, "pid": shell["pid"], "identity": shell["identity"],
            "cwd": target["root"], "message": shlex.join(args), "agy_inventory": inventory,
        })
        require(result == "sent", "guarded explicit-ID resume was not confirmed")

    def wait_resumed(self, target, timeout):
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            tab = self.snapshot(target)
            original_tab = self.before_quit["observation"]["tab"]
            require(all(tab[key] == original_tab[key] for key in ("window", "tab", "tty")),
                    "owned Terminal binding changed during resume")
            # Read current output after the former shell screen; history of an
            # earlier prompt must not substitute for the resumed runtime state.
            screen = tab["screen"]
            require(not PROMPT.search(screen), "human prompt during resume")
            peers = [p for p in self.processes() if p["tty"] == target["tty"] and Path(p["comm"]).name == "agy"]
            require(len(peers) <= 1, "multiple resumed agy processes")
            if peers:
                pid = peers[0]["pid"]
                require(pid != target["pid"], "resume reused old PID")
                live = self.s.notifier.live_process(pid)
                if live and self.s.notifier.composer_reason(screen) is None:
                    require(live["pid"] == pid and live["tty"] == target["tty"],
                            "resumed PID or TTY observation changed")
                    started = datetime.strptime(live["started"], "%a %b %d %H:%M:%S %Y").astimezone().timestamp()
                    require(started == peers[0].get("started_epoch"), "resumed process start observation changed")
                    updated = {**target, "pid": pid, "tty": live["tty"], "process_identity": live["identity"]}
                    observed = self.observe(updated)
                    require(observed["idle"] and observed["verified_identity"], "resumed session is not verified idle")
                    require(observed["model_evidence"] == self.before_quit["model_evidence"], "model or effort changed")
                    result = self.sockets(pid, listen=True)
                    sockets = parse_lsof(result["stdout"], returncode=result["returncode"], stderr=result["stderr"])
                    require(sum(s["state"] == "LISTEN" and s["loopback"] for s in sockets) == 2,
                            "resumed listener count is not exactly 2")
                    require(self.s.notifier.live_process(pid) == live, "resumed process changed after listener check")
                    return {"pid": pid, "tty": live["tty"], "process_identity": live["identity"],
                            "started": live["started"], "listeners": 2}
            self.sleep(0.25)
        raise GuardError("resumed session did not become verified idle before deadline")

    def rebind(self, target, new):
        updated = {**target, "pid": new["pid"], "tty": new["tty"], "process_identity": new["process_identity"]}
        current = self.observe(updated)
        require(current["idle"] and current["verified_identity"] and not current["prompt"],
                "resumed identity or idle state changed before rebind")
        original = self.before_quit["observation"]["tab"]
        tab = current["observation"]["tab"]
        require(all(tab[key] == original[key] for key in ("window", "tab", "tty")),
                "owned Terminal binding changed before rebind")
        apply_bindings(self.s, target, new, self.binding_plan, self.helpers)


def binding_plan(supervisor, target, read_json):
    config = supervisor.config
    bindings = config.get("port_pressure", {}).get("binding_files", [])
    require({b.get("role") for b in bindings} == {"monitor", "approval"},
            "monitor and approval binding files must be explicitly configured")
    specs = [*bindings, {"role": "supervisor", "path": config.get("_config_path")}]
    plan = {}
    for spec in specs:
        path = Path(spec.get("path") or "")
        require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
                "unsafe or missing binding file")
        data = read_json(path)
        rows = data.get("targets") if isinstance(data, dict) else data
        require(isinstance(rows, list), "binding file must contain a target list")
        hits = [i for i, row in enumerate(rows) if row.get("pid") == target["pid"]]
        require(len(hits) == 1, "missing or ambiguous old PID binding")
        row = rows[hits[0]]
        require(row.get("tty") == target["tty"]
                and row.get("root", row.get("cwd")) == target["root"]
                and row.get("process_identity", row.get("identity")) == target["process_identity"],
                "old binding identity disagreement")
        if "native_session_id" in row:
            require(row["native_session_id"] == target["native_session_id"], "binding conversation ID disagreement")
        if str(path) not in plan:
            plan[str(path)] = {"path": path, "data": data, "index": hits[0], "hash": raw_hash(path), "roles": []}
        plan[str(path)]["roles"].append(spec["role"])
    return list(plan.values())


def apply_bindings(supervisor, target, new, plan, helpers):
    require(bool(plan), "binding preflight missing")
    for item in plan:
        require(raw_hash(item["path"]) == item["hash"], "binding changed during restart")
    journal = {"state": "prepared", "old_pid": target["pid"], "new_pid": new["pid"],
               "files": [{"path": str(i["path"]), "before_sha256": i["hash"], "roles": i["roles"]} for i in plan]}
    supervisor.write(supervisor.runtime / "port-pressure-rebind.json", journal)
    for item in plan:
        require(raw_hash(item["path"]) == item["hash"], "binding changed before replacement")
        data = copy.deepcopy(item["data"])
        rows = data.get("targets") if isinstance(data, dict) else data
        row = rows[item["index"]]
        row.update(pid=new["pid"], tty=new["tty"])
        for field in ("identity", "process_identity"):
            if field in row:
                row[field] = new["process_identity"]
        if "started" in row:
            row["started"] = new["started"]
        helpers["atomic_json"](item["path"], data)
        require(helpers["read_json"](item["path"]) == data, "binding replacement read-back failed")
    old_pid = target["pid"]
    target.update(pid=new["pid"], tty=new["tty"], process_identity=new["process_identity"])
    supervisor.native_cache.pop(target["repository_key"], None)
    status_path = supervisor.directory(target) / "status.json"
    status = helpers["read_json"](status_path)
    status["port_pressure_restart"] = {"old_pid": old_pid, "new_pid": new["pid"],
                                      "tty": new["tty"], "listeners": new["listeners"],
                                      "conversation_id": target["native_session_id"]}
    supervisor.write(status_path, status)
    journal["state"] = "complete"
    supervisor.write(supervisor.runtime / "port-pressure-rebind.json", journal)


class PortPressureGuard:
    def __init__(self, supervisor, *, transport=None, clock=time.time):
        self.s = supervisor
        self.clock = clock
        raw = supervisor.config.get("port_pressure", {"mode": "off"})
        self.config = normalize_config({k: v for k, v in raw.items() if k != "binding_files"})
        self.transport = transport or NativeTransport(supervisor, clock=clock)
        self.state_path = supervisor.runtime / "port-pressure-state.json"
        self.disable_path = supervisor.runtime / "port-pressure-disabled.json"

    def tick(self, *, apply=False):
        if self.config["mode"] == "off":
            return {"phase": "off", "candidate": None}
        helpers = self.s._port_pressure_helpers
        with helpers["file_lock"](self.s.runtime / "port-pressure.lock"):
            state = {}
            state_loaded = False
            report = {"mode": self.config["mode"], "observed_at": self.clock()}
            try:
                state = helpers["read_json"](self.state_path) if self.state_path.exists() or self.state_path.is_symlink() else {}
                require(isinstance(state, dict), "guard state must be an object")
                state_loaded = True
                if self.disable_path.exists() or self.disable_path.is_symlink():
                    state = latch_failure(state, "guard has a durable failure latch; operator reconciliation required", now=self.clock())
                if state.get("inflight"):
                    raise GuardError("unfinished prior restart; manual reconciliation required")
                measurement, observations = self.transport.collect()
                report.update(measurement=measurement)
                decision = decide(self.config, measurement, observations, state, now=self.clock())
                report.update(decision)
                if isinstance(report.get("candidate"), dict):
                    report["candidate"] = {k: v for k, v in report["candidate"].items() if k != "observation"}
                if decision.get("disable_reason"):
                    raise GuardError(decision["disable_reason"])
                candidate = decision.get("candidate")
                if not candidate or self.config["mode"] != "restart" or not apply:
                    self.s.write(self.s.runtime / "port-pressure-report.json", report)
                    return report
                require(not self.s.stopping(), "supervisor stop requested")
                matches = [t for t in self.s.config["targets"] if t["repository_key"] == candidate["repository_key"]
                           and t["pid"] == candidate["pid"]]
                require(len(matches) == 1, "selected target changed")
                target = matches[0]
                old_pid = target["pid"]
                with helpers["file_lock"](Path(self.s.config["input_lock_dir"]) / (Path(target["tty"]).name + ".lock")):
                    self.transport.preflight(target)
                    require(not self.s.stopping(), "supervisor stop requested")
                    state["inflight"] = {"repository_key": target["repository_key"], "pid": old_pid,
                                         "conversation_id": target["native_session_id"], "started_at": self.clock()}
                    self.s.write(self.state_path, state)
                    self.transport.quit(target)
                    returned = self.transport.wait_exit(target, 30)
                    require(not self.s.stopping(), "supervisor stop requested after exit")
                    self.transport.resume(target, returned)
                    new = self.transport.wait_resumed(target, 45)
                    self.transport.rebind(target, new)
                    state.pop("inflight", None)
                    state = record_restart(state, target["repository_key"], old_pid, new["pid"], now=self.clock())
                    self.s.write(self.state_path, state)
                    report.update(phase="restarted", old_pid=old_pid, new_pid=new["pid"], listeners=new["listeners"])
            except Exception as error:
                reason = str(error)[:500]
                if not self.disable_path.exists() and not self.disable_path.is_symlink():
                    self.s.write(self.disable_path, {"disabled": True, "reason": reason, "at": self.clock()})
                # Preserve unreadable/non-object state for recovery, including
                # quota history; never repair it by pretending this is a new run.
                if state_loaded:
                    state = latch_failure(state, reason, now=self.clock())
                    self.s.write(self.state_path, state)
                report.update(phase="disabled", disable_reason=reason, alert=reason, candidate=None)
            self.s.write(self.s.runtime / "port-pressure-report.json", report)
            return report
