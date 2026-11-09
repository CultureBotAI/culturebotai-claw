#!/usr/bin/env python3
"""Start, stop, and inspect the approval monitor and goal supervisor safely.

Only exact configured monitor processes are managed. Agent sessions, workflow
ledgers, prompt counts, and completion receipts are never modified.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "workspace/monitoring/config.json"
SERVICES = ("approvals", "supervisor")


class ControlError(Exception):
    """A lifecycle operation cannot be proven safe."""


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def safe_path(value: str | Path, *, directory: bool = False) -> Path:
    """Reject symlinks (including parents) and untrusted existing files."""
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ControlError(f"Path must be absolute without '..': {path}")
    for ancestor in (*reversed(path.parents), path):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ControlError(f"Symlink is not allowed: {ancestor}")
        if ancestor != path and not stat.S_ISDIR(info.st_mode):
            raise ControlError(f"Parent is not a directory: {ancestor}")
        if info.st_mode & stat.S_IWOTH and not (stat.S_ISDIR(info.st_mode) and info.st_mode & stat.S_ISVTX):
            raise ControlError(f"World-writable path is not allowed: {ancestor}")
        if ancestor == path:
            if info.st_uid != os.getuid():
                raise ControlError(f"Path is not owned by the current user: {path}")
            if directory and not stat.S_ISDIR(info.st_mode):
                raise ControlError(f"Expected a directory: {path}")
            if not directory and not stat.S_ISREG(info.st_mode):
                raise ControlError(f"Expected a regular file: {path}")
            if not directory and info.st_nlink != 1:
                raise ControlError(f"Hard-linked state file is not allowed: {path}")
    return path


def read_json(path: Path, *, missing: Any = None) -> Any:
    safe_path(path)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return missing
    except (OSError, ValueError) as error:
        raise ControlError(f"Cannot read {path}: {error}") from error


def atomic_json(path: Path, value: Any) -> None:
    safe_path(path)
    safe_path(path.parent, directory=True)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        safe_path(path)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_json(path: Path, value: Any) -> None:
    safe_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_manifest(path: Path) -> dict:
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ControlError(f"Monitor config is missing or is not a version 1 object: {path}; configure it before starting")
    safe_path(manifest.get("state_dir", ""), directory=True)
    services = manifest.get("services")
    if not isinstance(services, dict) or not services or set(services) - set(SERVICES):
        raise ControlError("services must contain approvals and/or supervisor")
    commands = set()
    paths = set()
    write_paths = set()
    protected_paths = {Path(path)}
    for name, spec in services.items():
        if not isinstance(spec, dict) or spec.get("kind") != {"approvals": "approval", "supervisor": "supervisor"}[name]:
            raise ControlError(f"Invalid service kind for {name}")
        argv = spec.get("argv")
        if (not isinstance(argv, list) or not argv or
                any(not isinstance(arg, str) or not arg or any(c in arg for c in "\0\r\n") for arg in argv)):
            raise ControlError(f"{name}: argv must be a nonempty string array")
        if not Path(argv[0]).is_absolute():
            raise ControlError(f"{name}: executable must be an absolute path")
        if Path(argv[0]).name in {"agy", "antigravity", "claude"}:
            raise ControlError(f"{name}: an agent session cannot be managed as a monitor")
        if not sys.platform.startswith("linux") and any(any(char.isspace() for char in arg) for arg in argv):
            raise ControlError(f"{name}: cannot safely identify whitespace-bearing argv on this platform")
        command = " ".join(argv)
        if command in commands:
            raise ControlError("Services cannot share a process command")
        commands.add(command)
        safe_path(spec.get("cwd", ""), directory=True)
        if Path(spec.get("stop_file", "")).name != "STOP":
            raise ControlError(f"{name}: stop_file must be named STOP")
        if Path(spec.get("log_file", "")).suffix != ".log":
            raise ControlError(f"{name}: log_file must have a .log suffix")
        write_paths.update(Path(spec[field]) for field in ("stop_file", "log_file"))
        protected_paths.update(Path(arg) for arg in argv if Path(arg).is_absolute() and Path(arg).suffix == ".py")
        if "--config" in argv and argv.index("--config") + 1 < len(argv):
            protected_paths.add(Path(argv[argv.index("--config") + 1]))
        for field in ("stop_file", "status_file", "log_file"):
            path_value = safe_path(spec.get(field, ""))
            if path_value in paths:
                raise ControlError(f"Services cannot share lifecycle files: {path_value}")
            paths.add(path_value)
        if spec.get("session_targets_file"):
            safe_path(spec["session_targets_file"])
            protected_paths.add(Path(spec["session_targets_file"]))
        hashes = spec.get("source_sha256", {})
        if not isinstance(hashes, dict):
            raise ControlError(f"{name}: source_sha256 must map absolute paths to SHA-256 hashes")
        for source, digest in hashes.items():
            safe_path(source)
            protected_paths.add(Path(source))
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ControlError(f"{name}: invalid SHA-256 digest for {source}")
        age = spec.get("heartbeat_max_age_seconds", 300)
        if isinstance(age, bool) or not isinstance(age, (int, float)) or not 1 <= age <= 3600:
            raise ControlError(f"{name}: heartbeat_max_age_seconds must be 1..3600")
    reserved = {Path(manifest["state_dir"]) / name for name in ("registry.json", "events.jsonl", "lifecycle.lock")}
    if reserved & (paths | protected_paths) or Path(path) in paths or write_paths & protected_paths:
        raise ControlError("Lifecycle files must not overwrite config, sources, session bindings, or controller state")
    return manifest


def _ps(arguments: list[str]) -> str:
    try:
        result = subprocess.run(["/bin/ps", *arguments], capture_output=True, text=True,
                                timeout=5, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ControlError(f"Cannot inspect processes: {error}") from error
    if result.returncode not in (0, 1) or (result.returncode == 1 and result.stderr.strip()):
        raise ControlError(f"Cannot inspect processes: {result.stderr.strip()}")
    return result.stdout


def parse_processes(output: str) -> dict[int, dict]:
    found = {}
    for line in output.splitlines():
        parts = line.split(None, 7)
        # pid, state, weekday, month, day, hh:mm:ss, year, command
        if len(parts) < 8 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        if "Z" in parts[1]:
            continue  # An exited child can remain a zombie until reaped.
        found[pid] = {"pid": pid, "started": " ".join(parts[2:7]), "command": parts[7]}
    return found


def process_table() -> dict[int, dict]:
    return parse_processes(_ps(["-axww", "-o", "pid=,stat=,lstart=,command="]))


def process_at(pid: int) -> dict | None:
    return parse_processes(_ps(["-ww", "-p", str(pid), "-o", "pid=,stat=,lstart=,command="])).get(pid)


def process_cwd(pid: int) -> str:
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except OSError as error:
            raise ControlError(f"Cannot verify process {pid} working directory: {error}") from error
    try:
        result = subprocess.run(["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ControlError(f"Cannot verify process {pid} working directory: {error}") from error
    paths = [line[1:] for line in result.stdout.splitlines() if line.startswith("n")]
    if result.returncode or len(paths) != 1:
        raise ControlError(f"Cannot verify process {pid} working directory")
    return paths[0]


def exact_argv(pid: int, argv: list[str]) -> bool:
    # Linux exposes argument boundaries. macOS ps exposes only the rendered
    # command, so reject whitespace-bearing arguments there rather than guess.
    if sys.platform.startswith("linux"):
        try:
            data = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0")
        except OSError as error:
            raise ControlError(f"Cannot verify process {pid} arguments: {error}") from error
        return data.split(b"\0") == [os.fsencode(arg) for arg in argv]
    if any(any(char.isspace() for char in arg) for arg in argv):
        raise ControlError("Cannot safely identify whitespace-bearing argv on this platform")
    return True


def signature(spec: dict) -> str:
    return hashlib.sha256(json.dumps({"argv": spec["argv"], "cwd": spec["cwd"]},
                                    sort_keys=True).encode()).hexdigest()


def epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return None


class Controller:
    def __init__(self, manifest: dict, timeout: float = 45):
        self.manifest = manifest
        self.state_dir = Path(manifest["state_dir"])
        self.registry_path = self.state_dir / "registry.json"
        self.events_path = self.state_dir / "events.jsonl"
        self.timeout = timeout
        self.registry: dict = {}
        self.children: dict[int, subprocess.Popen] = {}

    @contextlib.contextmanager
    def locked(self):
        safe_path(self.state_dir, directory=True)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = safe_path(self.state_dir / "lifecycle.lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ControlError("Another monitoring lifecycle operation is running") from error
            self.registry = read_json(self.registry_path, missing={"version": 1, "services": {}})
            if (not isinstance(self.registry, dict) or self.registry.get("version") != 1 or
                    not isinstance(self.registry.get("services"), dict)):
                raise ControlError("Invalid ownership registry; refusing lifecycle operation")
            yield
        finally:
            os.close(fd)

    def event(self, event: str, name: str | None = None, **details: Any) -> None:
        append_json(self.events_path, {"at": timestamp(), "event": event, "service": name, **details})

    def remember(self, name: str, proc: dict, *, source: str) -> dict:
        record = {**proc, "signature": signature(self.manifest["services"][name]),
                  "source": source, "registered_at": timestamp()}
        self.registry["services"][name] = record
        atomic_json(self.registry_path, self.registry)
        self.event("ownership-recorded", name, **record)
        return record

    def identify(self, name: str, table: dict[int, dict] | None = None) -> dict | None:
        spec = self.manifest["services"][name]
        for child in self.children.values():
            child.poll()
        table = process_table() if table is None else dict(table)
        owned = self.registry["services"].get(name)
        if owned:
            if not isinstance(owned, dict) or not isinstance(owned.get("pid"), int):
                raise ControlError(f"{name}: invalid ownership record")
            live = table.get(owned["pid"])
            if live and owned.get("started") == live["started"] and owned.get("command") != live["command"]:
                # macOS can briefly render an exiting command as '(python)' before
                # reporting Z. Confirm from a fresh PID query, never signal it.
                live = process_at(owned["pid"])
                if live is None:
                    table.pop(owned["pid"], None)
                else:
                    table[owned["pid"]] = live
            if live and (owned.get("started") != live["started"] or
                         owned.get("command") != live["command"] or
                         owned.get("signature") != signature(spec)):
                raise ControlError(f"{name}: recorded PID was reused or configuration changed; refusing to signal or launch")
        matches = [proc for proc in table.values() if proc["command"] == " ".join(spec["argv"])]
        if len(matches) > 1:
            raise ControlError(f"{name}: {len(matches)} exact process matches; refusing ambiguous ownership")
        if not matches:
            return None
        proc = matches[0]
        try:
            details_match = exact_argv(proc["pid"], spec["argv"]) and process_cwd(proc["pid"]) == spec["cwd"]
        except ControlError:
            # The process can exit after ps but before /proc or lsof is read.
            # Missing/unreadable details alone never prove exit or ownership.
            if process_at(proc["pid"]) is None:
                return None
            raise
        if not details_match:
            if process_at(proc["pid"]) is None:
                return None
            raise ControlError(f"{name}: matching command has different arguments or working directory")
        return proc

    def heartbeat(self, name: str, proc: dict | None) -> dict:
        spec = self.manifest["services"][name]
        data = read_json(Path(spec["status_file"]), missing={})
        if not isinstance(data, dict):
            return {"fresh": False, "reason": "invalid-status"}
        updated = epoch(data.get("updated_at", data.get("updated")))
        age = time.time() - updated if updated is not None else None
        fresh = bool(proc and data.get("pid") == proc["pid"] and data.get("running") is True and
                     age is not None and -5 <= age <= spec.get("heartbeat_max_age_seconds", 300))
        return {"fresh": fresh, "age_seconds": round(age, 2) if age is not None else None,
                "reported_pid": data.get("pid"), "reported_running": data.get("running"),
                "updated_at": data.get("updated_at", data.get("updated")), "data": data}

    def bindings(self, name: str, table: dict[int, dict]) -> dict:
        spec = self.manifest["services"][name]
        filename = spec.get("session_targets_file")
        if not filename and spec["kind"] == "supervisor" and "--config" in spec["argv"]:
            index = spec["argv"].index("--config") + 1
            if index < len(spec["argv"]):
                filename = spec["argv"][index]
        if not filename:
            return {"configured": None, "live": None, "stale": None, "state": "not-configured"}
        source = read_json(Path(filename))
        targets = source.get("targets") if isinstance(source, dict) else source
        if not isinstance(targets, list):
            raise ControlError(f"{name}: invalid session targets file")
        live = 0
        seen_pids = set()
        seen_ttys = set()
        for target in targets:
            if not isinstance(target, dict) or not isinstance(target.get("pid"), int):
                raise ControlError(f"{name}: invalid session target")
            if target["pid"] in seen_pids or target.get("tty") in seen_ttys:
                raise ControlError(f"{name}: duplicate session PID or TTY binding")
            seen_pids.add(target["pid"])
            seen_ttys.add(target.get("tty"))
            proc = table.get(target["pid"])
            # Match the saved process start as well as PID; old sessions must not
            # become live again just because the OS recycles a PID.
            saved = target.get("started")
            identity = " ".join(str(target.get("process_identity", target.get("identity", ""))).split())
            start_matches = bool(proc and ((saved and " ".join(str(saved).split()) == proc["started"]) or
                                           (identity and f" {proc['started']} " in f" {identity} ")))
            command_matches = bool(proc and Path(proc["command"].split()[0]).name == "agy")
            if start_matches and command_matches:
                expected_cwd = target.get("cwd", target.get("root"))
                if not expected_cwd or process_cwd(proc["pid"]) != expected_cwd:
                    continue
                # The target's complete saved ps identity also includes TTY.
                tty = target.get("tty")
                if not tty or len(identity.split()) < 2 or identity.split()[1] != Path(tty).name:
                    continue
                current_identity = " ".join(_ps(["-p", str(proc["pid"]), "-o", "pid=,tty=,lstart=,comm="]).split())
                if identity != current_identity:
                    continue
                live += 1
        return {"configured": len(targets), "live": live, "stale": len(targets) - live,
                "state": "no-live-bound-sessions" if not live else
                         "stale-session-bindings" if live < len(targets) else "bound-sessions-live"}

    def status(self, name: str, table: dict[int, dict] | None = None) -> dict:
        table = process_table() if table is None else table
        try:
            proc = self.identify(name, table)
            heartbeat = self.heartbeat(name, proc)
            bindings = self.bindings(name, table)
            data = heartbeat.pop("data", {})
            monitoring = bindings["state"]
            if (self.manifest["services"][name]["kind"] == "approval" and heartbeat["fresh"]
                    and bindings["state"] == "bound-sessions-live"):
                if data.get("active_sessions") == 0:
                    monitoring = "no-live-sessions"
                elif data.get("scan_error"):
                    monitoring = "scan-error"
                elif data.get("active_sessions", 0) != data.get("readable_sessions", 0):
                    monitoring = "unreadable-sessions"
                else:
                    monitoring = "monitoring-sessions" if data.get("active_sessions", 0) else "session-count-unknown"
            elif not heartbeat["fresh"]:
                monitoring = "not-confirmed"
            state = "running" if proc and heartbeat["fresh"] else "unhealthy" if proc else "stopped"
            return {"service": name, "state": state, "pid": proc["pid"] if proc else None,
                    "started": proc["started"] if proc else None,
                    "stop_requested": Path(self.manifest["services"][name]["stop_file"]).exists(),
                    "heartbeat": heartbeat, "bindings": bindings, "monitoring": monitoring,
                    "active_sessions": data.get("active_sessions"), "readable_sessions": data.get("readable_sessions")}
        except ControlError as error:
            return {"service": name, "state": "blocked", "error": str(error)}

    def verified_signal(self, name: str, expected: dict) -> bool:
        # Recheck immediately before signaling; never use a stale PID from disk.
        current = self.identify(name)
        if current is None:
            return False
        if any(current.get(key) != expected.get(key) for key in ("pid", "started", "command")):
            raise ControlError(f"{name}: process changed before signal")
        try:
            os.kill(current["pid"], signal.SIGTERM)
        except ProcessLookupError:
            return False
        self.event("sigterm", name, pid=current["pid"], started=current["started"])
        return True

    def stopped(self, name: str, expected: dict) -> bool:
        child = self.children.get(expected["pid"])
        if child:
            child.poll()
        current = process_at(expected["pid"])
        if current is None:
            return True
        if (current.get("pid") == expected.get("pid") and current.get("started") == expected.get("started")
                and current.get("command") != expected.get("command")):
            # ps fields are not an atomic snapshot: a live state/start may be
            # followed by an exited command description. Require a fresh query
            # to confirm absence; a persistent or reused identity still blocks.
            current = process_at(expected["pid"])
            if current is None:
                return True
        if any(current.get(key) != expected.get(key) for key in ("pid", "started", "command")):
            raise ControlError(f"{name}: process identity changed while waiting")
        return False

    def wait_stopped(self, processes: dict[str, dict], deadline: float) -> None:
        pending = dict(processes)
        while pending:
            pending = {name: proc for name, proc in pending.items() if not self.stopped(name, proc)}
            if not pending:
                return
            if time.monotonic() >= deadline:
                raise ControlError("Graceful stop timed out; no force kill performed: " + ", ".join(pending))
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def stop(self, names: list[str], deadline: float) -> None:
        # Preflight every service before changing any marker or sending signals.
        table = process_table()
        processes = {name: self.identify(name, table) for name in names}
        for name, proc in processes.items():
            if proc:
                self.remember(name, proc, source="adopted-for-stop")
            stop_file = Path(self.manifest["services"][name]["stop_file"])
            atomic_json(stop_file, {"requested_at": timestamp(), "source": "mech-monitor-control"})
            self.event("stop-requested", name, pid=proc["pid"] if proc else None)
        for name, proc in processes.items():
            if proc:
                self.verified_signal(name, proc)
        self.wait_stopped({name: proc for name, proc in processes.items() if proc}, deadline)
        for name in names:
            self.event("stopped", name)

    def start(self, names: list[str], deadline: float) -> None:
        table = process_table()
        existing = {name: self.identify(name, table) for name in names}
        for name in names:
            spec = self.manifest["services"][name]
            for field in ("stop_file", "status_file", "log_file"):
                safe_path(spec[field])
                safe_path(Path(spec[field]).parent, directory=True)
            if not Path(spec["cwd"]).is_dir() or not os.access(spec["argv"][0], os.X_OK):
                raise ControlError(f"{name}: executable or working directory is unavailable")
            # Preflight every selected service before clearing any STOP marker.
            bindings = self.bindings(name, table)
            if bindings["state"] != "bound-sessions-live":
                raise ControlError(f"{name}: {bindings['state']}; reassess and explicitly rebind live agent sessions before starting")
            for source, expected in spec.get("source_sha256", {}).items():
                safe_path(source)
                try:
                    actual = hashlib.sha256(Path(source).read_bytes()).hexdigest()
                except OSError as error:
                    raise ControlError(f"{name}: source unavailable: {source}") from error
                if actual != expected:
                    raise ControlError(f"{name}: source hash changed: {source}; review and update the manifest before starting")
        launched: dict[str, dict] = {}
        launch_intents: list[str] = []
        try:
            for name in names:
                spec = self.manifest["services"][name]
                stop_file = Path(spec["stop_file"])
                safe_path(stop_file)
                if existing[name] and stop_file.exists():
                    raise ControlError(f"{name}: stop is already requested; wait for it to exit before starting")
                if not existing[name]:
                    launch_intents.append(name)
                if stop_file.exists():
                    stop_file.unlink()
                    self.event("stop-cleared", name)
                if existing[name]:
                    self.remember(name, existing[name], source="existing")
                    self.event("already-running", name, pid=existing[name]["pid"])
                    continue
                # Recheck for a concurrent legacy launcher before spawning.
                if self.identify(name) is not None:
                    raise ControlError(f"{name}: process appeared during start; retry to adopt it")
                log_file = Path(spec["log_file"])
                log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                safe_path(log_file)
                fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
                self.event("launch-requested", name, argv=spec["argv"], cwd=spec["cwd"])
                try:
                    child = subprocess.Popen(spec["argv"], cwd=spec["cwd"], stdin=subprocess.DEVNULL,
                                             stdout=fd, stderr=subprocess.STDOUT, start_new_session=True,
                                             close_fds=True)
                finally:
                    os.close(fd)
                self.children[child.pid] = child
                proc = process_at(child.pid)
                if not proc or proc["command"] != " ".join(spec["argv"]):
                    # Popen has completed exec before returning. If the process
                    # already exited there is nothing to signal; if it exec'd
                    # something unexpected, identity cannot be proven safe.
                    child.poll()
                    raise ControlError(f"{name}: launched process exited or changed command before registration")
                launched[name] = proc
                self.remember(name, proc, source="launched")
            pending = list(names)
            while pending:
                for name in list(pending):
                    proc = self.identify(name)
                    if not proc:
                        raise ControlError(f"{name}: monitor exited during startup")
                    if self.heartbeat(name, proc)["fresh"]:
                        pending.remove(name)
                if not pending:
                    break
                if time.monotonic() >= deadline:
                    raise ControlError("Startup heartbeat timed out: " + ", ".join(pending))
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
            for name in names:
                self.event("started", name, pid=self.identify(name)["pid"])
        except (ControlError, OSError, KeyboardInterrupt) as error:
            rollback_errors = []
            for name in launch_intents:
                try:
                    atomic_json(Path(self.manifest["services"][name]["stop_file"]),
                                {"requested_at": timestamp(), "source": "failed-start-rollback"})
                except (ControlError, OSError) as rollback_error:
                    rollback_errors.append(str(rollback_error))
            for name, proc in launched.items():
                try:
                    self.verified_signal(name, proc)
                    self.event("startup-rollback", name, pid=proc["pid"])
                except (ControlError, OSError) as rollback_error:
                    rollback_errors.append(str(rollback_error))
            # Leave existing services untouched. Newly spawned processes receive
            # only graceful termination; a later status/stop can finish waiting.
            if launched and time.monotonic() < deadline:
                try:
                    self.wait_stopped(launched, deadline)
                except ControlError as rollback_error:
                    rollback_errors.append(str(rollback_error))
            suffix = "; rollback: " + "; ".join(rollback_errors) if rollback_errors else ""
            message = "Startup interrupted; new monitors were asked to stop" if isinstance(error, KeyboardInterrupt) else str(error)
            raise ControlError(message + suffix) from error

    def run(self, action: str, names: list[str]) -> dict:
        errors = []
        with self.locked():
            self.event("operation", action=action, selected=names)
            deadline = time.monotonic() + self.timeout
            try:
                if action in ("stop", "restart"):
                    self.stop(names, deadline)
                if action in ("start", "restart"):
                    self.start(names, deadline)
            except (ControlError, OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
                self.event("operation-failed", action=action, error=str(error))
            table = process_table()
            rows = [self.status(name, table) for name in names]
            errors.extend(row["error"] for row in rows if row["state"] == "blocked" and row["error"] not in errors)
            if action == "status":
                errors.extend(f"{row['service']}: running without a fresh matching heartbeat"
                              for row in rows if row["state"] == "unhealthy")
            return {"action": action, "ok": not errors, "updated_at": timestamp(),
                    "services": rows, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "start", "stop", "restart"))
    parser.add_argument("--service", choices=("all", *SERVICES), default="all")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--timeout", type=float, default=45, help="Total lifecycle wait budget, 0 < seconds <= 60")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 60:
        parser.error("--timeout must be greater than 0 and at most 60 seconds")
    try:
        manifest = load_manifest(args.config)
        names = list(manifest["services"]) if args.service == "all" else [args.service]
        if any(name not in manifest["services"] for name in names):
            raise ControlError(f"Service is not configured: {args.service}")
        result = Controller(manifest, args.timeout).run(args.action, names)
    except (ControlError, OSError, ValueError, TypeError) as error:
        result = {"action": args.action, "ok": False, "services": [], "errors": [str(error)]}
    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for row in result["services"]:
            detail = row.get("error") or f"{row['monitoring']}; PID {row['pid'] or 'none'}"
            bindings = row.get("bindings", {})
            if bindings.get("configured") is not None:
                detail += (f"; live bindings {bindings['live']}/{bindings['configured']}"
                           f", stale {bindings['stale']}")
            print(f"{row['service']}: {row['state']} ({detail})")
        for error in result["errors"]:
            print(f"Error: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
