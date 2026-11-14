#!/usr/bin/env python3
"""Fail-closed, local-only maintenance for owned idle agy sessions (#725).

Importing this adapter performs no observation or input. The supervisor invokes
it explicitly; off is the compatibility default and report never sends input.
All action dependencies are injectable so the complete transaction is tested
without a live Terminal, agent, provider, or network service.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import time
import uuid
from contextlib import contextmanager
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
from kg_microbe_workflows.port_pressure_identity import (
    validate_live_identity,
    validate_registration,
)
from kg_microbe_workflows.port_pressure_tasks import blocked_tasks

_BINDINGS_SPEC = importlib.util.spec_from_file_location(
    "port_pressure_approval_bindings", Path(__file__).with_name("mech_approval_bindings.py"))
bindings = importlib.util.module_from_spec(_BINDINGS_SPEC)
_BINDINGS_SPEC.loader.exec_module(bindings)

UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
# Same prompt vocabulary as XMechBay's mac-orchestration guard, with native agy
# approval/tool menus included. There is deliberately no override path here.
PROMPT = re.compile(
    r"Sign in with|authentication required|Log in to continue|Select (?:a )?login|not signed in|"
    r"Trust this folder|Do you trust|trust the (?:files|contents)|"
    r"Update available|Skip until next version|Update now|"
    r"approval request|Allow command|Requesting permission|Do you want to|"
    r"Allow sandbox bypass|Confirm the command is safe|Would you like to|"
    r"Allow access to this file\?|Run this command\?|Accept changes\?|"
    r"ctrl\+k\s+approve|needs approval for|↑/↓\s*Navigate|"
    r"Queued follow-up|⇧← to answer|request_user_input|"
    r"^\s*(?:Question|Questions|QUESTION)\b|Type your answer|to submit answer|"
    r"to navigate questions|Select Model|Select Reasoning|"
    r"How['’]s the CLI experience|^\s*\[0\]\s+Skip\b|^\s*\?\s+(?:Which|.*question)|"
    r"^\s*(?:Select|Choose) (?:an? option|one of the following)|"
    r"^\s*[›❯>]?\s*\d+[.)]\s+(?:Yes|No|Allow|Deny|Approve|Reject|Cancel)\b",
    re.I | re.M,
)


SIGN_IN = re.compile(r"Sign in with|authentication required|Log in to continue|Select (?:a )?login|not signed in", re.I)


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
    # A current owned native server uses this complete structured line. Do not
    # accept tool text/quoted examples, partial IDs, or choose among identities.
    ids.update(re.findall(
        r'^I[0-9]{4} [0-9:.]+\s+[0-9]+ server\.go:[0-9]+\] '
        r'GetConversationDetail: found conversation (' + UUID + r') \(active=(?:true|false)\)\s*$',
        text, re.M,
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
    model_lines = [line for line in footer if re.search(r"\bGemini\b", line)
                   and not line.strip(" │┃").startswith("Meet Gemini 4 Argon")]
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
    def __init__(self, supervisor, *, clock=time.time, sleep=time.sleep, binding_adapter=None):
        self.s = supervisor
        self.binding_adapter = binding_adapter or bindings
        self.clock = clock
        self.sleep = sleep
        self.helpers = supervisor._port_pressure_helpers
        self.before_quit = None
        self.binding_plan = None
        self.boundary = None
        self.registration = None
        self.identity_before = None
        self.identity_after = None
        self.binding_lease_held = False
        self.attempt_dir = None
        self.excluded_repository_keys = ()

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
            # Process/conversation ownership above applies to every session.
            # Excluded targets and known busy/task/prompt displays need not
            # expose the restart model footer. They cannot be selected, so
            # missing restart metadata is not a fleet identity failure.
            # Eligible idle, pre-quit and resumed sessions still prove it.
            allowed = self.s.config.get("port_pressure", {}).get("restart_repository_keys")
            restart_allowed = ((allowed is None or target["repository_key"] in allowed)
                               and target["repository_key"] not in self.excluded_repository_keys)
            if restart_allowed and not row["busy"] and not row["prompt"] and not row["blocked_tasks"]:
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

    def registered_identity(self, target):
        """Read a reviewed registration, never infer launch selectors from labels."""
        value = target.get("port_pressure_identity")
        require(isinstance(value, dict), "restart registration is unconfigured")
        evidence = value.get("evidence", {})
        path = Path(evidence.get("path", ""))
        require(path.is_absolute() and path.resolve() == path and not path.is_symlink()
                and path.is_file() and path.stat().st_size <= 1024 * 1024,
                "restart registration evidence path is unsafe or unavailable")
        try:
            return validate_registration(value, target=target, evidence_bytes=path.read_bytes())
        except ValueError as error:
            raise GuardError(str(error)) from error

    def executable_digest(self, registration):
        executable = Path(registration["agy_executable"])
        require(executable.is_absolute() and executable.resolve() == executable
                and not executable.is_symlink() and executable.is_file()
                and os.access(executable, os.X_OK), "registered agy executable is unavailable")
        before = executable.stat()
        digest = raw_hash(executable)
        after = executable.stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                "executable changed while hashing")
        require(digest == registration["executable_sha256"], "registered executable bytes changed")
        return digest

    def verify_restart_identity(self, target, screen):
        registration = self.registered_identity(target)
        if self.registration is not None:
            require(registration == self.registration, "restart registration changed during transaction")
        digest = self.executable_digest(registration)
        text = self.run(["/usr/sbin/lsof", "-a", "-p", str(target["pid"]), "-d", "txt", "-Fn"]).stdout
        require(any(line == "n" + registration["agy_executable"] for line in text.splitlines()),
                "registered executable differs from running agy")
        command = self.run(["/bin/ps", "-ww", "-p", str(target["pid"]), "-o", "command="]).stdout.strip()
        # macOS ps has no argument boundaries. Restrict this supported form to
        # four whitespace-free tokens; do not guess quoting or hidden defaults.
        argv = command.split()
        require(len(argv) == 4 and argv[2].startswith("--model=") and argv[3].startswith("--effort="),
                "current exact CLI model/effort arguments are unproven")
        model = model_evidence(screen, registration)
        live = {"pid": target["pid"], "process_identity": target["process_identity"],
                "native_session_id": target["native_session_id"], "tty": target["tty"],
                "cwd": str(self.s.notifier.process_cwd(target["pid"])),
                "agy_executable": registration["agy_executable"], "executable_sha256": digest,
                "argv": argv, "model": argv[2].partition("=")[2], "effort": argv[3].partition("=")[2],
                "model_label": model["model_label"], "effort_label": model["effort_label"]}
        try:
            validate_live_identity(registration, target=target, observation=live)
        except ValueError as error:
            raise GuardError(str(error)) from error
        require(self.s.notifier.live_process(target["pid"])["identity"] == target["process_identity"],
                "process identity changed during registration check")
        self.registration = registration
        return live

    def attempt_event(self, name, data):
        if self.attempt_dir is not None:
            bindings.create(self.attempt_dir / (name + ".json"), bindings.encoded(data))

    def preserve_attempt(self):
        """Durably retain exact pre-state before /quit can reach Terminal."""
        root = bindings.safe(self.s.runtime / "port-pressure-attempts", directory=True)
        root.mkdir(mode=0o700, exist_ok=True)
        bindings.sync_dir(root.parent)
        directory = root / uuid.uuid4().hex
        directory.mkdir(mode=0o700)
        bindings.sync_dir(root)
        manifest = {"version": 1, "created_at": self.clock(), "state": "prepared",
                    "identity": self.identity_before, "registration": self.registration,
                    "boundary": self.boundary, "before_observation": self.before_quit,
                    "bindings": {}}
        for index, (path, raw) in enumerate(self.binding_plan["before"].items()):
            name = "%02d-before" % index
            bindings.create(directory / name, raw)
            manifest["bindings"][path] = {"file": name, "sha256": hashlib.sha256(raw).hexdigest()}
        evidence = self.registration["evidence"]
        raw = Path(evidence["path"]).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == evidence["sha256"], "registration evidence changed before quit")
        bindings.create(directory / "registration-evidence.json", raw)
        bindings.create(directory / "prepared.json", bindings.encoded(manifest))
        self.attempt_dir = directory

    @contextmanager
    def transaction_lease(self):
        require(self.binding_plan is not None, "binding preflight missing")
        with self.binding_adapter.rebind_lease(self.binding_plan):
            self.binding_lease_held = True
            try:
                self.preserve_attempt()
                yield
            except BaseException as error:
                self.attempt_event("failed", {"at": self.clock(), "error": str(error)[:500]})
                raise
            else:
                self.attempt_event("finished", {"at": self.clock()})
            finally:
                self.binding_lease_held = False

    def preflight(self, target):
        current = self.observe(target)
        require(current["idle"] and current["verified_identity"], "session no longer verified idle")
        require(not current["prompt"] and not current["blocked_tasks"], "human prompt or background task")
        # Transport authorization never inherits observation-only exemptions.
        current["model_evidence"] = model_evidence(
            current["observation"]["tab"]["screen"], target.get("port_pressure_identity"))
        if self.boundary is not None:
            observed = current["observation"]
            require(observed.get("goal_identity") == self.boundary["goal_identity"],
                    "completed goal identity changed before boundary recycle")
            allowed = {"completed"}
            if self.boundary.get("completion_authority") == "verified_receipt_override":
                allowed.add("active")
            require(observed.get("goal_state") in allowed, "completed goal state changed before boundary recycle")
        policy = self.s.config.get("port_pressure", {}).get("restart_policy", "goal_boundary_or_idle")
        require(policy != "goal_boundary_only" or self.boundary is not None,
                "goal-boundary-only restart requires a verified boundary")
        self.identity_before = self.verify_restart_identity(target, current["observation"]["tab"]["screen"])
        if self.binding_lease_held:
            self.binding_adapter.check_before(self.binding_plan)
        else:
            old_plan = binding_plan(self.s, target, self.helpers["read_json"])
            controller = self.s.config.get("port_pressure", {}).get("controller_config_path")
            require(isinstance(controller, str), "resident binding reload controller is unconfigured")
            self.binding_plan = self.binding_adapter.prepare_rebind(controller, [str(i["path"]) for i in old_plan], target,
                                                        now=self.clock, input_lock_dir=self.s.config["input_lock_dir"])
        self.before_quit = current
        return current

    def quit(self, target):
        # Last acquisition of all three IDs is the penultimate operation. The
        # final interaction is /quit; there is no status message or goal replay.
        current = self.preflight(target)
        require(self.binding_lease_held, "binding lifecycle lease is required before quit")
        tab = current["observation"]["tab"]
        self.attempt_event("quit-authorized", {"at": self.clock(), "identity": self.identity_before,
                                               "observation": current})
        result = self.s.notifier.jxa(self.helpers["send_js"], {
            **tab, "pid": target["pid"], "identity": target["process_identity"],
            "cwd": target["root"], "message": "/quit",
        })
        require(result == "sent", "guarded /quit was not confirmed")
        self.attempt_event("quit-confirmed", {"at": self.clock()})

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
                self.attempt_event("exit-verified", {"at": self.clock(), "tab": tab, "shell": shell})
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
        registration = self.registered_identity(target)
        require(self.registration is not None and registration == self.registration,
                "restart registration changed before resume")
        self.executable_digest(registration)
        args = [identity["agy_executable"], "--conversation=" + target["native_session_id"],
                "--model=" + identity["model"], "--effort=" + identity["effort"]]
        self.attempt_event("resume-authorized", {"at": self.clock(), "argv": args, "registration": registration})
        result = self.s.notifier.jxa(self.helpers["send_js"], {
            **tab, "pid": shell["pid"], "identity": shell["identity"],
            "cwd": target["root"], "message": shlex.join(args), "agy_inventory": inventory,
        })
        require(result == "sent", "guarded explicit-ID resume was not confirmed")
        self.attempt_event("resume-confirmed", {"at": self.clock()})

    def wait_resumed(self, target, timeout):
        deadline = self.clock() + timeout
        signin_reread = False
        while self.clock() < deadline:
            tab = self.snapshot(target)
            original_tab = self.before_quit["observation"]["tab"]
            require(all(tab[key] == original_tab[key] for key in ("window", "tab", "tty")),
                    "owned Terminal binding changed during resume")
            # Read current output after the former shell screen; history of an
            # earlier prompt must not substitute for the resumed runtime state.
            screen = tab["screen"]
            prompt = PROMPT.search(screen)
            if prompt:
                # Auto-update startup may briefly paint a sign-in frame. Re-read
                # once, without input; persistent sign-in and all other prompts
                # still stop. Never erase prompt text from retained history.
                signin_only = bool(SIGN_IN.search(screen)) and all(
                    SIGN_IN.fullmatch(match.group()) for match in PROMPT.finditer(screen))
                if not signin_reread and signin_only:
                    signin_reread = True
                    self.sleep(min(1.0, max(0.0, (deadline - self.clock()) / 2)))
                    continue
                if signin_reread and signin_only:
                    raise GuardError("sign-in evidence remains after fresh reread; current runtime is unverified")
                raise GuardError("human prompt during resume")
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
                    resumed_model = model_evidence(
                        observed["observation"]["tab"]["screen"], target.get("port_pressure_identity"))
                    require(resumed_model == self.before_quit["model_evidence"], "model or effort changed")
                    self.identity_after = self.verify_restart_identity(
                        updated, observed["observation"]["tab"]["screen"])
                    result = self.sockets(pid, listen=True)
                    sockets = parse_lsof(result["stdout"], returncode=result["returncode"], stderr=result["stderr"])
                    require(sum(s["state"] == "LISTEN" and s["loopback"] for s in sockets) == 2,
                            "resumed listener count is not exactly 2")
                    require(self.s.notifier.live_process(pid) == live, "resumed process changed after listener check")
                    self.attempt_event("resumed-verified", {"at": self.clock(), "identity": self.identity_after})
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
        require(self.binding_lease_held, "binding lifecycle lease is required for rebind")
        self.identity_after = self.verify_restart_identity(updated, tab["screen"])
        receipt = apply_bindings(self.s, target, new, self.binding_plan, self.helpers,
                       evidence={"before_identity": self.identity_before, "after_identity": self.identity_after,
                                 "boundary": self.boundary, "attempt_directory": str(self.attempt_dir)},
                       sleep=self.sleep, binding_adapter=self.binding_adapter)
        self.attempt_event("rebind-acknowledged", {"at": self.clock(), "receipt": receipt})


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


def apply_bindings(supervisor, target, new, plan, helpers, *, evidence=None, sleep=time.sleep, binding_adapter=None):
    """Complete only after the existing resident controller adopts exact bytes."""
    adapter = binding_adapter or bindings
    receipt = adapter.install_rebind(plan, new, evidence=evidence)
    completed = adapter.await_rebind(plan, receipt, sleep=sleep)
    old_pid = target["pid"]
    target.update(pid=new["pid"], tty=new["tty"], process_identity=new["process_identity"])
    supervisor.native_cache.pop(target["repository_key"], None)
    status_path = supervisor.directory(target) / "status.json"
    status = helpers["read_json"](status_path)
    status["port_pressure_restart"] = {"old_pid": old_pid, "new_pid": new["pid"],
                                      "tty": new["tty"], "listeners": new["listeners"],
                                      "conversation_id": target["native_session_id"]}
    supervisor.write(status_path, status)
    return completed


class PortPressureGuard:
    def __init__(self, supervisor, *, transport=None, clock=time.time):
        self.s = supervisor
        self.clock = clock
        raw = supervisor.config.get("port_pressure", {"mode": "off"})
        self.config = normalize_config({k: v for k, v in raw.items() if k not in {"binding_files", "controller_config_path"}})
        allowed = self.config["restart_repository_keys"]
        require(allowed is None or set(allowed) <= {target["repository_key"] for target in supervisor.config["targets"]},
                "restart_repository_keys contains an unconfigured target")
        self.transport = transport or NativeTransport(supervisor, clock=clock)
        self.state_path = supervisor.runtime / "port-pressure-state.json"
        self.disable_path = supervisor.runtime / "port-pressure-disabled.json"

    def tick(self, *, apply=False, boundary=None, excluded_repository_keys=()):
        if self.config["mode"] == "off":
            return {"phase": "off", "candidate": None}
        helpers = self.s._port_pressure_helpers
        self.transport.boundary = boundary
        self.transport.excluded_repository_keys = excluded_repository_keys
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
                decision = decide(self.config, measurement, observations, state, now=self.clock(), boundary=boundary,
                                  excluded_repository_keys=excluded_repository_keys)
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
                    with self.transport.transaction_lease():
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
