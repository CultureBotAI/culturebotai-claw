#!/usr/bin/env python3
"""Observe Mech agy sessions and dispatch the authorized, receipt-gated workflow.

Default mode only observes. --apply permits bounded Terminal messages, never Git
or GitHub mutations. Coding agents perform the work; independently checked
closure receipts gate the next goal. Runtime artifacts belong in workspace/.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
KEY = re.compile(r"[a-z][a-z0-9_-]*\Z")
BLOCKING_RECEIPTS = {"reserved", "sent", "accepted", "uncertain"}


class SupervisorError(RuntimeError):
    """A failed prerequisite; never permission to guess or continue."""


class FreshnessHold(SupervisorError):
    """Freshness uncertainty holds the boundary without spending closure repairs."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def atomic_json(path: Path, value: Any, *, boundary: Path | None = None) -> None:
    if boundary is not None and (boundary.resolve() != boundary or not path.parent.resolve().is_relative_to(boundary)):
        raise SupervisorError("runtime output parent escapes its configured boundary")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_json(path: Path) -> Any:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "r") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SupervisorError("JSON input must be a regular file")
        return json.load(stream)


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def command(args: list[str], *, timeout: int = 45, check: bool = True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise SupervisorError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()[:400]}")
    return result


def import_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise SupervisorError(f"Cannot import helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def goal_identity(native: dict) -> dict | None:
    goal = native.get("current_goal")
    if not goal or not goal.get("started_at") or not isinstance(goal.get("start_step_index"), int):
        return None
    return {"conversation_id": native["conversation_id"],
            "started_at": goal["started_at"], "start_step_index": goal["start_step_index"]}


def terminal_busy_reason(screen: str) -> str | None:
    lines = [line.rstrip() for line in screen.replace("\r", "").splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    footer = "\n".join(lines[-32:])
    # Queue wording and counts also occur in completed thoughts/replies.
    # Counts must occupy a complete status line or a middle-dot footer field.
    queue_count = re.search(
        r"(?:^|·)\s*(?:[1-9]\d* (?:messages?|tasks?) queued|"
        r"queued (?:messages?|tasks?):\s*[1-9]\d*)\s*(?=$|·)", footer, re.I | re.M,
    )
    if queue_count or re.search(r"esc to interrupt|Compacting conversation|"
                 r"alt\+m to send immediately|Press up to edit queued messages|"
                 r"\b[1-9]\d* (?:background )?task\(s\)|\b[1-9]\d* background tasks?\b|"
                 r"\bbackground tasks?:\s*[1-9]\d*|^\s*● .* running\s*$", footer, re.I | re.M):
        return "busy, background, or queued terminal state"
    return None


def confirmed_display_corruption(screen: str, reason: str | None = None) -> bool:
    """Detect distorted idle agy composers that safe row-bump redraw can refresh."""
    if reason is None:
        reason = import_file(ROOT / "scripts/mech_session_terminal.py", "supervisor_terminal").composer_reason(screen)
    if reason not in {
        "missing-composer-borders",
        "unrecognized-composer-tail",
        "composer-too-far-from-footer",
        "no-empty-composer",
    }:
        return False
    if terminal_busy_reason(screen) is not None:
        return False
    lines = [line.rstrip() for line in screen.replace("\r", "").splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    candidates = [
        i for i, line in enumerate(lines)
        if len(lines) - i <= 9
        and (
            line.strip() == ">"
            or (
                0 < i < len(lines) - 1
                and re.search(r"^\s*[^>\s].*\s+>(?:\s|$)", line)
                and all(re.search(r"[─━]{5,}", lines[j]) for j in (i - 1, i + 1))
            )
        )
    ]
    if not candidates:
        return False
    index = candidates[-1]
    if index < 1 or len(lines) - index > 9:
        return False
    for j in range(max(0, index - 20), index):
        if re.match(r"^\s*>\s*\S", lines[j]):
            between = lines[j + 1 : index]
            if not any(
                re.search(r"[─━]{5,}", line) or re.match(r"^\s*[○●▸✻⣟]", line)
                for line in between
            ):
                return False
    window = lines[max(0, index - 4):]
    if any(re.match(r"^\s*>\s*\S", line) for line in lines[index:]) or any(
        re.match(r"^\s*┃(?:\s|$)", line) for line in window
    ):
        return False
    if not any(re.search(r"[─━]{5,}", line) for line in window):
        return False
    if re.search(
        r"↑/↓\s*Navigate|(?:Accept|Allow|Run)[^\n]*\?|How's the CLI experience|"
        r"ctrl\+k\s+approve|alt\+j\s+manage|needs approval for",
        "\n".join(lines[max(0, index - 25):]),
        re.I,
    ):
        return False
    if not re.search(r"Gemini\s+\S", "\n".join(lines[index + 1:])):
        return False
    border = r"[─━═\-┌┐└┘│┃╭╮╰╯ ]+"
    for line in lines[index + 1:]:
        text = line.strip()
        if not text or text == ">" or re.fullmatch(border, text):
            continue
        if ("Gemini " in text or "esc to cancel" in text.lower()
                or re.search(
                    r"(?:\?\s+for\s+(?:shortcuts|help)|tab\s+to\s+accept|"
                    r"shift\+tab|ctrl\+\w|background task|/tasks)", text, re.I
                )):
            continue
        return False
    return True


def normalize_github(url: str) -> str:
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?", url.strip())
    if not match:
        raise SupervisorError("Unrecognized GitHub origin")
    return match.group(1).casefold()


def load_effective(config: dict, target: dict, *, next_cycle: bool = False, profile_path=None) -> dict:
    """Only the validated parent and repository profile supply workflow policy."""
    from kg_microbe_workflows import PARENT_PATH, SCHEMA_PATH, load_effective_workflow

    profile = profile_path or (target.get("workflow_next_profile_path") if next_cycle else None)
    profile = profile or target.get("workflow_profile_path")
    if not profile:
        raise SupervisorError("canonical workflow profile missing; explicit migration required")
    def source(kind: str, default: Path) -> Path:
        current = target.get(f"workflow_{kind}_path", config.get(f"workflow_{kind}_path", default))
        candidate = target.get(f"workflow_next_{kind}_path", config.get(f"workflow_next_{kind}_path", current))
        return Path(candidate if next_cycle else current)

    return load_effective_workflow(source("parent", PARENT_PATH), Path(profile),
                                  target["repository_key"], schema_path=source("schema", SCHEMA_PATH))



def native_delivery_proof(action: dict, target: dict, observation: dict) -> dict | None:
    """A transport return or marker substring is never delivery acceptance.

    Match one full user input in this exact native workspace/conversation after
    the reserved step/time. Truncation, duplicates and bounded-out observations
    hold the reservation; they never authorize retry. Historical accepted actions
    remain intact and cannot by themselves adopt a later native goal.
    """
    native = observation.get("native") or {}
    if (observation.get("error") or native.get("error")
            or native.get("conversation_id") != target["native_session_id"]
            or action.get("native_session_id") != target["native_session_id"]
            or native.get("root") != target["root"]
            or native.get("workspace_identity", {}).get("verified") is not True):
        return None
    message = action.get("message")
    boundary = action.get("native_step_index")
    reserved = action.get("reserved_epoch_ms")
    if (not isinstance(message, str) or not message
            or type(boundary) is not int or boundary < 0
            or type(reserved) is not int or reserved < 0):
        return None
    expected_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    if action.get("message_sha256", expected_hash) != expected_hash:
        return None
    evidence = native.get("user_input_evidence") or {}
    if evidence.get("schema_version") != 1 or not isinstance(evidence.get("inputs"), list):
        return None
    inputs = evidence["inputs"]
    # If the reservation predates the bounded window, an earlier duplicate may
    # have fallen out. Absence or uniqueness cannot then be established.
    if evidence.get("truncated") and (not inputs or inputs[0].get("step_index", -1) > boundary):
        return None
    matches = []
    for entry in inputs:
        index = entry.get("step_index")
        if (type(index) is not int or index <= boundary
                or entry.get("text_sha256") != expected_hash
                or entry.get("text_length") != len(message)):
            continue
        try:
            created = datetime.fromisoformat(entry["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None or created.timestamp() * 1000 < reserved:
                return None
        except (KeyError, TypeError, ValueError, AttributeError):
            return None
        matches.append(entry)
    if len(matches) != 1:
        return None
    proof = matches[0]
    if proof.get("status_number") != 3 or proof.get("supported_input_shape") is not True:
        return None
    if action.get("kind") == "start_goal":
        identity = observation.get("goal_identity") or {}
        if (proof.get("native_goal_declaration") is not True
                or identity.get("conversation_id") != target["native_session_id"]
                or identity.get("start_step_index") != proof["step_index"]
                or identity.get("started_at") != proof["created_at"]):
            return None
    elif observation.get("goal_identity") != action.get("goal_identity"):
        return None
    return {"native_step_index": proof["step_index"], "text_sha256": expected_hash,
            "created_at": proof["created_at"],
            "native_goal_declaration": proof.get("native_goal_declaration") is True}


def scoped(action: dict, ledger: dict) -> bool:
    """Legacy actions can only belong to the explicitly adopted first cycle."""
    return action.get("cycle", 1) == ledger.get("cycle", 1) and action["stage"] == ledger["stage"]


def pin_workflow(effective: dict) -> dict:
    return {"sha256": digest(effective), "effective": copy.deepcopy(effective)}


def workflow_stage_key(ledger: dict, stage: int | None = None) -> str | None:
    """Interpret positions through this cycle's immutable contract, never today's parent."""
    selected = ledger["stage"] if stage is None else stage
    stages = ledger.get("workflow", {}).get("effective", {}).get("stages", [])
    return next((item["key"] for item in stages if item["stage"] == selected), None)


def last_stage(ledger: dict) -> int:
    stages = ledger.get("workflow", {}).get("effective", {}).get("stages", [])
    return len(stages) if stages else 4


def record_stage_key(ledger: dict, record: dict) -> str | None:
    """Old records keep their original stage and evidence paths after migration."""
    if record.get("stage_key"):
        return record["stage_key"]
    evidence = record.get("goal_evidence_snapshot")
    if evidence:
        from kg_microbe_workflows import evidence_stage_key
        return evidence_stage_key(evidence)
    from kg_microbe_workflows import stage_keys_for_version
    version = ledger.get("cycle_versions", {}).get(str(record.get("cycle", 1)))
    version = version or record.get("parent_version") or "1.0.0"
    keys = stage_keys_for_version(version)
    stage = record.get("stage", 0)
    return keys[stage - 1] if 0 < stage <= len(keys) else None


def record_cycle_version(ledger: dict) -> None:
    """Enrich the ledger's cycle metadata without rewriting historical records."""
    if ledger.get("schema_version") != 2:
        return
    effective = ledger["workflow"]["effective"]
    version = effective["parent_version"]
    versions = ledger.setdefault("cycle_versions", {})
    cycle = str(ledger["cycle"])
    if cycle in versions and versions[cycle] != version:
        raise SupervisorError("cycle parent version disagrees with its pinned workflow")
    versions[cycle] = version
    ledger["parent_version"] = version
    for record in ledger["completed_stages"]:
        historical_cycle = str(record.get("cycle", 1))
        versions.setdefault(historical_cycle, record.get("parent_version", "1.0.0"))


def migrate_ledger(ledger: dict, target: dict, effective: dict) -> dict:
    """Preserve native identity and history; an exact reviewed migration authorizes adoption."""
    migration = target.get("workflow_migration") or {}
    if effective["parent_version"].split(".")[0] != "1":
        raise SupervisorError("legacy four-goal ledgers must first adopt the reviewed six-goal contract")
    if migration.get("ledger_sha256") != digest(ledger):
        raise SupervisorError("legacy ledger requires an exact reviewed migration")
    if (migration.get("goal_identity") != ledger.get("adopted_goal")
            or not migration.get("reviewed_by") or not migration.get("reason")):
        raise SupervisorError("migration must bind the adopted goal and identify its review")
    errors = artifact_errors(migration.get("review", {}),
                             [Path(target["root"]), Path(migration.get("review_root", target["root"]))], "migration review")
    if errors:
        raise SupervisorError("; ".join(errors))
    if ledger["stage"] not in range(0, 6):
        raise SupervisorError("unsupported legacy stage; explicit reassessment required")
    result = copy.deepcopy(ledger)
    result.update(schema_version=2, cycle=1, workflow=pin_workflow(effective),
                  migration={**migration, "migrated_at": now()}, phase="assessment",
                  active_profile_path=target["workflow_profile_path"], policy_notification_required=True)
    for action in result["actions"].values():
        action["cycle"] = 1
    for record in result["completed_stages"]:
        record["cycle"] = 1
    # Stage 5 previously meant 'four goals finished'. It now means stage 5;
    # absence of stage-4 review evidence blocks it, never resets an active goal.
    if result["stage"] == 5:
        result["awaiting_goal"] = True
    result["legacy_receipt_stage"] = result["stage"] if result["stage"] < 4 else None
    record_cycle_version(result)
    return result


def validate_config(config: dict, *, resolve_repositories: bool = True) -> dict:
    from kg_microbe_workflows.port_pressure import normalize_config

    pressure = config.get("port_pressure", {"mode": "off"})
    if not isinstance(pressure, dict):
        raise SupervisorError("port_pressure must be an object")
    try:
        config["port_pressure"] = normalize_config({key: value for key, value in pressure.items() if key not in {"binding_files", "controller_config_path"}})
        for key in ("binding_files", "controller_config_path"):
            if key in pressure:
                config["port_pressure"][key] = pressure[key]
    except ValueError as error:
        raise SupervisorError(str(error)) from error
    config.setdefault("native_reader_path", str(ROOT / "scripts/mech_session_native.py"))
    config.setdefault("notifier_path", str(ROOT / "scripts/mech_session_terminal.py"))
    for field in ("run_id", "runtime_dir", "native_reader_path", "notifier_path", "input_lock_dir", "targets"):
        if not config.get(field):
            raise SupervisorError(f"Configuration missing {field}")
    runtime = Path(config["runtime_dir"])
    if not runtime.is_absolute() or not runtime.resolve().is_relative_to(ROOT / "workspace"):
        raise SupervisorError("runtime_dir must be absolute and within this checkout's workspace")
    seen = set()
    for target in config["targets"]:
        key = target.get("repository_key", "")
        if not KEY.fullmatch(key) or key in seen:
            raise SupervisorError(f"Invalid or duplicate repository key: {key}")
        seen.add(key)
        for field in ("root", "github_repository", "native_session_id", "pid", "tty",
                      "process_identity", "default_branch", "initial_goal_identity"):
            if not target.get(field):
                raise SupervisorError(f"{key}: missing {field}")
        if target.get("workflow_profile_path"):
            for field in ("workflow_profile_path", "workflow_next_profile_path"):
                if target.get(field):
                    profile_path = Path(target[field])
                    if not profile_path.is_absolute() or not profile_path.resolve().is_relative_to(Path(target["root"]).resolve()):
                        raise SupervisorError(f"{key}: {field} must be absolute and inside the repository")
            existing_path = runtime / key / "ledger.json"
            existing = read_json(existing_path) if existing_path.is_file() and not existing_path.is_symlink() else {}
            if existing.get("schema_version") == 2:
                if existing.get("run_id") != config["run_id"] or existing.get("repository_key") != key:
                    raise SupervisorError(f"{key}: existing cycle belongs to another workflow")
                effective = existing.get("workflow", {}).get("effective", {})
                if digest(effective) != existing.get("workflow", {}).get("sha256"):
                    raise SupervisorError(f"{key}: pinned effective workflow checksum mismatch")
            else:
                effective = load_effective(config, target)
            if effective["github_repository"].casefold() != target["github_repository"].casefold():
                raise SupervisorError(f"{key}: workflow GitHub identity mismatch")
            target["_workflow"] = effective
            target["stages"] = effective["stages"]
        final_stage = len(target["_workflow"]["stages"]) if target.get("_workflow") else 4
        if target.get("initial_stage") not in range(0, final_stage + 1):
            raise SupervisorError(f"{key}: initial_stage must be 0 through {final_stage}")
        if not isinstance(target["pid"], int) or target["pid"] <= 0:
            raise SupervisorError(f"{key}: invalid PID")
        initial = target["initial_goal_identity"]
        if (not isinstance(initial, dict) or initial.get("conversation_id") != target["native_session_id"]
                or not initial.get("started_at") or type(initial.get("start_step_index")) is not int):
            raise SupervisorError(f"{key}: initial goal identity is incomplete")
        if not re.fullmatch(r"/dev/ttys\d+", target["tty"]):
            raise SupervisorError(f"{key}: invalid TTY")
        if {stage.get("stage") for stage in target.get("stages", [])} != set(range(1, final_stage + 1)):
            raise SupervisorError(f"{key}: exactly {final_stage} stages required")
        if len(target["stages"]) != final_stage:
            raise SupervisorError(f"{key}: duplicate stages")
        for stage in target["stages"]:
            if not isinstance(stage.get("goal_text"), str) or not stage["goal_text"].strip():
                raise SupervisorError(f"{key}: stage goal_text missing")
            if not stage.get("skill_paths"):
                raise SupervisorError(f"{key}: stage skill_paths missing")
        if not Path(target["root"]).is_absolute():
            raise SupervisorError(f"{key}: repository root must be absolute")
        adoption = target.get("freshness_adoption")
        if adoption is not None:
            if (not isinstance(adoption, dict) or set(adoption) != {"path", "sha256"}
                    or not isinstance(adoption["path"], str) or not Path(adoption["path"]).is_absolute()
                    or not isinstance(adoption["sha256"], str) or not DIGEST.fullmatch(adoption["sha256"])):
                raise SupervisorError(f"{key}: freshness_adoption needs an absolute path and exact SHA-256")
        for field in ("session_state_paths", "session_repository_roots"):
            if field in target:
                paths = target[field]
                if (not isinstance(paths, list) or len(paths) > 64
                        or any(not isinstance(path, str) or not Path(path).is_absolute()
                               or "${" in path for path in paths)
                        or len(paths) != len(set(paths))):
                    raise SupervisorError(f"{key}: {field} must list unique explicit absolute owned paths")
    allowed = config["port_pressure"]["restart_repository_keys"]
    if allowed is not None and not set(allowed) <= seen:
        raise SupervisorError("restart_repository_keys contains an unconfigured target")
    if resolve_repositories:
        sys.path.insert(0, str(ROOT))
        from kg_microbe_fleet import load_fleet_manifest
        from plugins.repository_settings import RepositorySettings, merged_repository_environment
        manifest = load_fleet_manifest(Path(config["manifest_path"])) if config.get("manifest_path") else load_fleet_manifest()
        settings = RepositorySettings.from_environment(
            environ=merged_repository_environment(Path(config.get("env_file", ROOT / ".env"))),
            manifest=manifest)
        for target in config["targets"]:
            resolved = settings.get_target(target["repository_key"])
            repo = resolved.open()
            if resolved.path.resolve() != Path(target["root"]).resolve():
                raise SupervisorError(f"{target['repository_key']}: configured root differs from verified resolver")
            if normalize_github(repo.remotes.origin.url) != target["github_repository"].casefold():
                raise SupervisorError(f"{target['repository_key']}: origin mismatch")
    return config


def durability_repository_roots(target: dict) -> list[Path]:
    """Revalidate owned standalone clones; never infer ownership from names."""
    from plugins.repository_settings import RepositoryTarget
    roots = list(dict.fromkeys([Path(target["root"]),
                               *(Path(path) for path in target.get("session_repository_roots", []))]))
    for root in roots:
        RepositoryTarget(target["repository_key"], root, target["github_repository"]).open()
    return roots


def new_ledger(config: dict, target: dict, *, runner=command) -> dict:
    ledger = {"schema_version": 1, "run_id": config["run_id"],
            "repository_key": target["repository_key"], "stage": target["initial_stage"],
            "adopted_goal": None, "awaiting_goal": False, "actions": {},
            "completed_stages": [], "phase": "assessment", "created_at": now()}
    if target.get("_workflow"):
        ledger.update(schema_version=2, cycle=1, workflow=pin_workflow(target["_workflow"]),
                      active_profile_path=target["workflow_profile_path"])
        record_cycle_version(ledger)
        if target.get("freshness_adoption") and ledger["stage"] == 1:
            # A reviewed initial boundary must precede all inventory/baseline work.
            # Merely configuring a candidate does not authorize an active goal.
            ledger["freshness_initial_pending"] = True
        elif workflow_stage_key(ledger) == "infrastructure":
            ledger["infra_scope"] = freeze_infrastructure(target)
        elif workflow_stage_key(ledger) == "open_issue_triage":
            ledger["issue_scope"] = freeze_open_issues(target, runner=runner)
    return ledger


def action_id(ledger: dict, kind: str) -> str:
    # Text can be amended by agy; stable native start identity is intentional.
    return digest([ledger["run_id"], ledger["repository_key"], ledger.get("cycle", 1), ledger["stage"],
                   ledger["adopted_goal"], kind])[:24]


def decide(ledger: dict, observation: dict) -> dict:
    """Pure next-action reducer. A send is never evidence of completion."""
    if observation.get("error"):
        return {"phase": "unavailable", "reason": observation["error"]}
    if ledger.get("schema_version") == 1 and ledger["stage"] > 4:
        return {"phase": "requires_migration", "reason": "legacy four-goal sequence needs reviewed six-goal migration"}
    if ledger["stage"] > last_stage(ledger):
        return {"phase": "blocked", "reason": "invalid stage; cannot infer a new cycle"}
    if not observation.get("ready"):
        return {"phase": "waiting", "reason": observation.get("readiness_reason", "not ready")}
    if observation.get("goal_state") == "cancelled":
        return {"phase": "blocked", "reason": "native goal is cancelled; cannot infer continuation intent"}
    if ledger.get("policy_notification_required"):
        if observation.get("goal_identity") != ledger.get("adopted_goal"):
            return {"phase": "blocked", "reason": "native goal changed before workflow migration handoff"}
        identifier = action_id(ledger, "policy_update")
        prior = ledger["actions"].get(identifier)
        if prior and prior["state"] in BLOCKING_RECEIPTS:
            return {"phase": "awaiting_native_acceptance", "reason": "workflow policy handoff requires native acceptance"}
        return {"phase": "ready_to_dispatch", "action": "policy_update", "action_id": identifier}
    if ledger.get("awaiting_goal"):
        from kg_microbe_workflows.reconciliation import ReconciliationError, boundary_goal
        try:
            expected_goal = boundary_goal(ledger) or ledger["adopted_goal"]
        except (ReconciliationError, KeyError, TypeError, ValueError) as error:
            return {"phase": "blocked", "reason": "historical dispatch boundary: " + str(error)}
        if observation.get("goal_identity") != expected_goal:
            return {"phase": "blocked", "reason": "a different native goal appeared before next-goal dispatch"}
        prior = ledger["completed_stages"][-1] if ledger["completed_stages"] else {}
        override = (prior.get("completion_authority") == "verified_receipt_override"
                    and prior.get("goal_identity") == ledger["adopted_goal"]
                    and observation.get("goal_state") == "active")
        if observation.get("goal_state") != "completed" and not override:
            return {"phase": "blocked", "reason": "previous native goal is not completed"}
        if any(scoped(action, ledger) and action["kind"] == "start_goal" and action["state"] in BLOCKING_RECEIPTS
               for action in ledger["actions"].values()):
            return {"phase": "awaiting_native_acceptance", "reason": "a matching next-goal instruction is already reserved or delivered"}
        kind = "start_goal"
    elif not ledger.get("adopted_goal"):
        return {"phase": "blocked", "reason": "no authoritative current goal; assessment required"}
    elif observation.get("goal_identity") != ledger["adopted_goal"]:
        return {"phase": "blocked", "reason": "native goal identity changed without a matching dispatched goal"}
    else:
        # One initial/resumption instruction owns its entire closure. Do not
        # repeatedly nudge an accepted instruction that has not produced proof.
        prior = [a for a in ledger["actions"].values()
                 if scoped(a, ledger) and a["kind"] in {"assess_and_finalize", "finalize", "repair_closure"}
                 and a["state"] in BLOCKING_RECEIPTS]
        if prior:
            return repair_decision(ledger, observation, "accepted instruction finished or stalled without a valid closure receipt")
        state = observation.get("goal_state")
        if state == "completed":
            kind = "finalize"
        elif state in {"active", "unknown"}:
            kind = "assess_and_finalize"
        else:
            return {"phase": "blocked", "reason": f"native goal is {state}; cannot infer continuation intent"}
    identifier = action_id(ledger, kind)
    prior = ledger["actions"].get(identifier)
    if prior and prior["state"] in BLOCKING_RECEIPTS:
        return {"phase": "awaiting_native_acceptance", "reason": "action already reserved or delivered"}
    return {"phase": "ready_to_dispatch", "action": kind, "action_id": identifier}


def repair_decision(ledger: dict, observation: dict, reason: str, receipt_hash=None) -> dict:
    """At most three repairs per stage, each tied to newly observed progress."""
    fallback = {"phase": "requires_intervention", "reason": reason}
    progress = observation.get("agent_progress") or {}
    if (progress.get("authority") == "informational_only" and progress.get("current") is True
            and progress.get("stage") == ledger["stage"] and progress.get("cycle", 1) == ledger.get("cycle", 1)
            and progress.get("phase", "").lower() in {"blocked", "prerequisite_blocked", "requires_intervention"}):
        return {"phase": "requires_intervention", "reason": "agent reports blocked: " + progress.get("summary", reason)}
    if not observation.get("ready") or observation.get("goal_identity") != ledger["adopted_goal"]:
        return {"phase": "waiting", "reason": reason}
    if observation.get("goal_state") == "cancelled":
        return {"phase": "blocked", "reason": "native goal is cancelled; cannot infer continuation intent"}
    # A definitive pre-send rejection cannot acquire native acceptance. It
    # neither supersedes the last delivered instruction nor consumes a repair.
    actions = [action for action in ledger["actions"].values()
               if scoped(action, ledger) and action["state"] != "not-sent"]
    if not actions:
        return {"phase": "closure_blocked", "reason": reason}
    last = max(actions, key=lambda action: action.get("reserved_epoch_ms", 0))
    if last["state"] != "accepted":
        return {"phase": "awaiting_native_acceptance", "reason": "reserved/sent/uncertain instruction requires reconciliation"}
    step = ((observation.get("native") or {}).get("last_step") or {}).get("index")
    previous_step = last.get("native_step_index")
    if (not isinstance(step, int) or not isinstance(previous_step, int) or step <= previous_step
            or time.time() * 1000 - last.get("reserved_epoch_ms", 0) < 60000):
        return {"phase": "awaiting_closure_receipt", "reason": "no new completed execution after the accepted instruction"}
    if len([action for action in actions if action["kind"] == "repair_closure"]) >= 3:
        fallback["reason"] = "three bounded closure repairs exhausted: " + reason
        return fallback
    context = digest([reason, step, receipt_hash])
    identifier = action_id(ledger, "repair_closure:" + context)
    if identifier in ledger["actions"] and ledger["actions"][identifier]["state"] in BLOCKING_RECEIPTS:
        return fallback
    return {"phase": "ready_to_dispatch", "action": "repair_closure", "action_id": identifier,
            "repair_reason": reason, "receipt_hash": receipt_hash, "native_step_index": step}


def completion_authority(target: dict, ledger: dict, observation: dict) -> str:
    if observation.get("goal_identity") != ledger["adopted_goal"]:
        raise SupervisorError("native goal changed before closure verification")
    if observation.get("goal_state") == "completed":
        return "native_completed"
    accepted = any(action["state"] == "accepted" and action.get("kind") != "policy_update" and scoped(action, ledger)
                   and action.get("accepted_goal_identity", action.get("goal_identity")) == ledger["adopted_goal"]
                   for action in ledger["actions"].values())
    if (target.get("allow_receipt_completion_override") is True
            and observation.get("goal_state") == "active" and accepted):
        return "verified_receipt_override"
    raise SupervisorError("native goal is not completed; no explicit audited receipt-override policy applies")


def stage_profile(target: dict, stage: int, ledger: dict | None = None) -> dict:
    effective = (ledger or {}).get("workflow", {}).get("effective", {})
    return next(item for item in effective.get("stages", target["stages"]) if item["stage"] == stage)


def message_for(target: dict, ledger: dict, decision: dict, repository_runtime: Path) -> str:
    marker = "MECH-WORKFLOW-" + decision["action_id"]
    effective = ledger.get("workflow", {}).get("effective")
    instruction = repository_runtime / "effective-workflow.json" if effective else Path(target["workflow_prompt_path"])
    register = shlex.join(["env", f"PYTHONPATH={ROOT / 'src'}", str(ROOT / ".venv/bin/python"), "-m", "kg_microbe_progress.prs",
                           "register", "--session-dir", str(repository_runtime), "--number", "NUMBER"])
    context = (f"[{marker}] Read {instruction} and {repository_runtime / 'status.json'}. "
               "Repository-local .claude/skills is the skill source of truth. "
               "Keep session state and helper scripts in the repository's gitignored .temp/ "
               "(separate clones: ~/agent-work/<repo>/), never /tmp, /private/tmp or $TMPDIR. "
               "Push each committed batch the same day even without a PR, within existing publication authorization. "
               "Report all owned clone/state paths for the supervisor inventory and record every deliverable commit in the receipt. "
               f"This is run {ledger['run_id']}, cycle {ledger.get('cycle', 1)}, stage {ledger['stage']}. "
               f"Fill status.json receipt_template with verified facts and write it to {repository_runtime / 'completion.json'}. "
               "Follow the pinned workflow stage, evidence requirements, infrastructure-note policy, and closure policy. "
               f"After prior closure is verified, update the tracked review latest index from {repository_runtime / 'verified-evidence-index.json'} in this goal. "
               "Record-review goal findings are separate from the PR adversarial review; resolve_review_findings resolves the former. "
               "For infrastructure, use the exact supervisor-frozen infra_scope content/hash/time in status.json. "
               "For open_issue_triage, use the exact supervisor-frozen issue_scope and its prior-cycle carry-forward evidence; "
               "new issues outside that inventory belong to the next cycle. "
               f"As soon as each goal PR is opened, including follow-up PRs, register it with {register}, "
               "replacing NUMBER with its PR number. Registration only records the PR-to-goal association; "
               "it does not complete a goal or replace the verified closure receipt. "
               "Do not start another goal: the supervisor verifies closure and chooses the next goal. ")
    if decision["action"] == "policy_update":
        return (context + "Your existing native goal and its identity are unchanged. Adopt the reviewed pinned workflow "
                "and its versioned review and infrastructure evidence requirements for the unfinished work. "
                "Continue the same goal; this policy handoff itself is not goal completion. "
                "Save proposed profile changes to the configured next-cycle candidate and include them in infrastructure review; "
                "do not edit the immutable runtime snapshot.")
    if decision["action"] == "start_goal":
        profile = stage_profile(target, ledger["stage"], ledger)
        return f"/goal {profile['goal_text']} {context} Finish the configured closure sequence, write the receipt, and stop."
    if decision["action"] == "finalize":
        return context + "The adopted goal has native completion evidence. Verify its result and finish the configured closure sequence. Reuse matching completed steps only after verifying their evidence."
    if decision["action"] == "repair_closure":
        return (context + "Continue only unfinished work or repair the closure receipt. The independent verifier reports: "
                + decision["repair_reason"] + ". Re-read current status and existing PR/review/issues before acting; "
                "reuse proven completed steps. Preserve unrelated changes and never force cleanup.")
    return (context + "First assess the last running goal recorded in status.json. If incomplete, continue "
            "that same objective using its applicable skill; do not replace or reset it. Once complete, "
            "finish the configured closure sequence.")


def receipt_template(ledger: dict, target: dict) -> dict:
    """Provide the machine interface; placeholders are never closure evidence."""
    template = {key: copy.deepcopy(ledger[key]) for key in ("run_id", "repository_key", "stage")}
    template.update(schema_version=ledger.get("schema_version", 1), goal_identity=copy.deepcopy(ledger["adopted_goal"]),
                    goal_complete=False, status="completed", coverage={"artifact": "", "sha256": ""},
                    review={"artifact": "", "sha256": "", "status": "pending", "head_sha": "", "remaining_findings": None},
                    validation=[{"artifact": "", "sha256": "", "command": "", "status": "pending", "head_sha": ""}],
                    issues=[], pr={"number": None, "head_sha": "", "branch": "", "base": target["default_branch"]},
                    cleanup={"checkout_ready": False, "local_branch_deleted": False, "remote_branch_deleted": False},
                    deliverable_commits=[""])
    if ledger.get("schema_version") == 2:
        from kg_microbe_workflows import evidence_directory
        template.update(cycle=ledger["cycle"], workflow_sha256=ledger["workflow"]["sha256"],
                        goal_outputs={"infra_tasks": {"path": "INFRA_TASKS.md", "sha256": ""}})
        if (workflow_stage_key(ledger) in {"record_review", "resolve_review_findings", "infrastructure", "open_issue_triage"}
                or (ledger["stage"] > 0 and stage_profile(target, ledger["stage"], ledger).get("required_outputs"))):
            template["goal_outputs"]["goal_evidence"] = {
                "path": evidence_directory(ledger["run_id"], ledger["cycle"], ledger["stage"], 1) + "/evidence.yaml",
                "sha256": ""}
    return template


def artifact_errors(item: dict, allowed_roots: list[Path], label: str) -> list[str]:
    if not isinstance(item, dict) or not isinstance(item.get("artifact"), str):
        return [f"{label}: artifact missing"]
    path = Path(item["artifact"])
    if not path.is_absolute():
        path = allowed_roots[0] / path
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in allowed_roots):
        return [f"{label}: artifact outside repository/runtime"]
    expected = item.get("sha256", "")
    if not isinstance(expected, str) or not DIGEST.fullmatch(expected):
        return [f"{label}: valid SHA256 required"]
    try:
        # O_NONBLOCK prevents FIFO opens from waiting for a writer. Inspect the
        # opened descriptor, not a racy pre-open path check, before reading it.
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(resolved, flags), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return [f"{label}: artifact must be a regular file"]
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
    except (OSError, ValueError) as error:
        return [f"{label}: artifact unreadable ({error})"]
    return [] if actual == expected else [f"{label}: artifact hash mismatch"]


def freeze_infrastructure(target: dict, *, fetched_head: str | None = None) -> dict:
    """Capture the input scope before infrastructure can change the notebook."""
    from kg_microbe_workflows import validate_infra_notebook

    path = Path(target["root"]) / "INFRA_TASKS.md"
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SupervisorError("infrastructure notebook must be a regular file")
            raw = stream.read()
    except (OSError, SupervisorError) as error:
        if fetched_head is not None:
            raise FreshnessHold("infrastructure fetched notebook is absent or not a regular file") from error
        raise
    if fetched_head is not None:
        verify_fetched_infrastructure(target, fetched_head, raw)
    notebook = validate_infra_notebook(raw, target["github_repository"])
    return {"sha256": hashlib.sha256(raw).hexdigest(), "content": raw.decode("utf-8"),
            "tasks": notebook["tasks"], "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}



def verify_fetched_infrastructure(target: dict, fetched_head: str, raw: bytes) -> None:
    """An adopted scope must be the exact regular blob in its fetched tree."""
    from kg_microbe_workflows.freshness import FreshnessError, Git

    if not isinstance(fetched_head, str) or not SHA.fullmatch(fetched_head):
        raise FreshnessHold("infrastructure scope lacks a verified fetched revision")
    try:
        entry = Git(Path(target["root"])).run(
            "ls-tree", "-z", fetched_head, "--", "INFRA_TASKS.md")
    except FreshnessError as error:
        raise FreshnessHold("infrastructure fetched blob cannot be verified") from error
    actual_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if entry not in {f"100644 blob {actual_blob}\tINFRA_TASKS.md\0",
                     f"100755 blob {actual_blob}\tINFRA_TASKS.md\0"}:
        raise FreshnessHold("infrastructure scope must match the regular INFRA_TASKS.md blob at fetched HEAD")


def freeze_open_issues(target: dict, *, runner=command) -> dict:
    """Freeze a complete, bounded read of open issues; uncertainty never means empty."""
    from kg_microbe_workflows.issue_triage import validate_issue_snapshot

    repository = target["github_repository"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SupervisorError("issue inventory needs the verified GitHub repository")
    owner, name = repository.split("/")
    frozen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff = datetime.fromisoformat(frozen_at.replace("Z", "+00:00"))
    query = """query($owner:String!,$name:String!,$cursor:String){
      repository(owner:$owner,name:$name){nameWithOwner issues(first:100,after:$cursor,
        states:OPEN,orderBy:{field:CREATED_AT,direction:ASC}){
        totalCount pageInfo{hasNextPage endCursor}
        nodes{number title updatedAt labels(first:100){totalCount nodes{name} pageInfo{hasNextPage}}}
      }}
    }"""
    items = []
    seen_numbers = set()
    seen_cursors = set()
    cursor = None
    total = None
    deadline = time.monotonic() + 60
    for page in range(1, 101):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SupervisorError("issue inventory capture exceeded its 60-second deadline")
        args = ["gh", "api", "graphql", "-f", "query=" + query,
                "-f", "owner=" + owner, "-f", "name=" + name]
        if cursor is not None:
            args += ["-f", "cursor=" + cursor]
        response = runner(args, timeout=max(1, min(45, int(remaining))))
        if response.returncode:
            raise SupervisorError("issue inventory query failed")
        try:
            payload = json.loads(response.stdout)
            if payload.get("errors"):
                raise ValueError("GraphQL errors")
            source = payload["data"]["repository"]
            if source["nameWithOwner"].casefold() != repository.casefold():
                raise ValueError("repository identity mismatch")
            connection = source["issues"]
            count, nodes, info = connection["totalCount"], connection["nodes"], connection["pageInfo"]
            if type(count) is not int or not 0 <= count <= 10000 or not isinstance(nodes, list) or len(nodes) > 100:
                raise ValueError("invalid/truncated issue count")
            if total is not None and total != count:
                raise ValueError("open issue inventory changed while paginating")
            total = count
            if type(info["hasNextPage"]) is not bool:
                raise ValueError("invalid pagination state")
            for node in nodes:
                number = node["number"]
                if type(number) is not int or number <= 0 or number in seen_numbers:
                    raise ValueError("duplicate or invalid issue number")
                updated = datetime.fromisoformat(node["updatedAt"].replace("Z", "+00:00"))
                if updated.tzinfo is None or updated > cutoff:
                    raise ValueError("issue changed after the inventory cutoff")
                labels = node["labels"]
                label_names = [label["name"] for label in labels["nodes"]]
                if (labels["pageInfo"]["hasNextPage"] is not False
                        or labels["totalCount"] != len(label_names)
                        or len(set(label_names)) != len(label_names)):
                    raise ValueError("incomplete issue labels")
                items.append({"number": number, "title": node["title"], "labels": sorted(label_names),
                              "updatedAt": node["updatedAt"]})
                seen_numbers.add(number)
            if not info["hasNextPage"]:
                if len(items) != total:
                    raise ValueError("issue inventory pagination did not cover totalCount")
                break
            cursor = info["endCursor"]
            if not nodes or not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise ValueError("invalid or repeated issue cursor")
            seen_cursors.add(cursor)
        except (KeyError, TypeError, ValueError) as error:
            raise SupervisorError("cannot freeze complete issue inventory: " + str(error)) from error
    else:
        raise SupervisorError("issue inventory exceeded its 100-page bound")
    snapshot = {"repository": repository, "frozen_at": frozen_at, "issues": sorted(items, key=lambda item: item["number"]),
                "complete": True, "total_count": total, "pages": page}
    validate_issue_snapshot(snapshot, repository)
    content = json.dumps(snapshot, sort_keys=True, indent=2) + "\n"
    return {"sha256": hashlib.sha256(content.encode()).hexdigest(), "content": content,
            "frozen_at": frozen_at, "issues": snapshot["issues"]}


def validate_frozen_issue_scope(scope: dict, target: dict) -> None:
    from kg_microbe_workflows.issue_triage import validate_issue_snapshot
    content = scope.get("content")
    if not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != scope.get("sha256"):
        raise SupervisorError("frozen issue inventory checksum mismatch")
    snapshot = json.loads(content)
    validate_issue_snapshot(snapshot, target["github_repository"])
    if scope.get("frozen_at") != snapshot["frozen_at"] or scope.get("issues") != snapshot["issues"]:
        raise SupervisorError("frozen issue scope metadata differs from its inventory")


def previous_evidence(ledger: dict, stage: int) -> dict | None:
    """Resolve findings within a cycle; carry reviews/issue groups across versions."""
    key = workflow_stage_key(ledger, stage)
    if key not in {"record_review", "resolve_review_findings", "open_issue_triage"}:
        return None
    cycle = ledger["cycle"]
    accepted = ({"record_review"} if key == "resolve_review_findings" else
                {"open_issue_triage"} if key == "open_issue_triage" else
                {"record_review", "resolve_review_findings"})
    eligible = [record for record in ledger["completed_stages"]
                if record_stage_key(ledger, record) in accepted and record.get("goal_evidence")
                and (record.get("cycle", 1) == cycle if key == "resolve_review_findings" else record.get("cycle", 1) < cycle)]
    return eligible[-1] if eligible else None


HISTORICAL_RESOLUTION_FIELDS = {
    "github_repository", "pr_number", "base", "head_sha", "merge_commit_sha", "receipt_sha256",
}


def historical_resolution_record(issue: dict, receipt: dict, ledger: dict, target: dict) -> dict:
    """Select one earlier, verified remediation closure; never another goal's PR member."""
    historical = issue.get("historical_resolution")
    if (not isinstance(historical, dict) or set(historical) != HISTORICAL_RESOLUTION_FIELDS
            or ledger.get("schema_version") != 2 or receipt.get("schema_version") != 2
            or workflow_stage_key(ledger) != "resolve_review_findings"
            or receipt.get("status") != "completed" or "prs" in receipt
            or type(historical.get("pr_number")) is not int or historical["pr_number"] <= 0
            or historical["pr_number"] == (receipt.get("pr") or {}).get("number")
            or historical.get("github_repository") != target["github_repository"]
            or historical.get("base") != target["default_branch"]
            or any(not SHA.fullmatch(str(historical.get(key, ""))) for key in ("head_sha", "merge_commit_sha"))
            or not DIGEST.fullmatch(str(historical.get("receipt_sha256", "")))):
        raise SupervisorError("historical resolution requires a completed single-PR remediation receipt and exact prior identity")
    records = [record for record in ledger.get("completed_stages", [])
               if record.get("receipt_sha256") == historical["receipt_sha256"]]
    if len(records) != 1:
        raise SupervisorError("historical resolution must bind one prior verified closure")
    record = records[0]
    verified = record.get("verification") or {}
    if (type(record.get("cycle")) is not int or not 1 <= record["cycle"] < ledger["cycle"]
            or record_stage_key(ledger, record) != "resolve_review_findings"
            or record.get("completion_authority") not in {"native_completed", "verified_receipt_override"}
            or verified.get("status") != "merged" or not verified.get("merged_at")
            or any(verified.get(key) != historical[key] for key in ("pr_number", "head_sha", "merge_commit_sha"))):
        raise SupervisorError("historical resolution differs from its earlier verified remediation closure")
    closure_time(verified["merged_at"], "historical merge")
    return record


def historical_finding_scope(issue: dict, receipt: dict, ledger: dict, target: dict,
                             evidence: dict, previous_data: dict | None) -> dict:
    """Require the same already-resolved finding group in retained bytes and this cycle's review."""
    record = historical_resolution_record(issue, receipt, ledger, target)
    descriptor = record.get("goal_evidence") or {}
    root = Path(target["root"])
    path = (root / descriptor.get("path", "")).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise SupervisorError("historical finding evidence must be a retained repository file")
    # Read once, hash and parse those bytes; a ledger snapshot alone is not evidence.
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SupervisorError("historical finding evidence must be a regular file")
        raw = stream.read()
    from kg_microbe_workflows import load_document
    retained = load_document(raw)
    if (hashlib.sha256(raw).hexdigest() != descriptor.get("sha256")
            or retained != record.get("goal_evidence_snapshot")
            or retained.get("repository_key") != ledger["repository_key"]
            or retained.get("github_repository") != target["github_repository"]
            or retained.get("run_id") != ledger["run_id"]
            or retained.get("cycle") != record["cycle"] or retained.get("stage") != record["stage"]):
        raise SupervisorError("historical finding snapshot differs from its pinned evidence or closure context")
    url = f"https://github.com/{target['github_repository']}/issues/{issue['number']}"
    current = [item for item in evidence.get("groups", []) if item.get("issue_url") == url]
    if len(current) != 1 or current[0].get("status") != "resolved":
        raise SupervisorError("historical issue must identify exactly one current resolved group")
    identities = set(current[0].get("finding_ids", []))
    old = [item for item in retained.get("groups", []) if item.get("issue_url") == url
           and item.get("status") == "resolved" and set(item.get("finding_ids", [])) == identities]
    before = {item["finding_id"]: item for item in retained.get("findings", [])}
    frozen = {item["finding_id"]: item for item in (previous_data or {}).get("findings", [])}
    after = {item["finding_id"]: item for item in evidence.get("findings", [])}
    if (len(old) != 1 or not identities or any(
            key not in before or key not in frozen or key not in after
            or any(row.get("status") != "resolved" or row.get("issue_url") != url
                   for row in (before[key], frozen[key], after[key]))
            or before[key].get("summary") != frozen[key].get("summary")
            or frozen[key].get("summary") != after[key].get("summary") for key in identities)):
        raise SupervisorError("historical resolution must carry the same already-resolved finding scope")
    return record


def verify_historical_issue_resolutions(receipt: dict, ledger: dict, target: dict,
                                        evidence: dict | None, current_live: dict, runner) -> list[dict]:
    """Fresh read-only identity, membership and ancestry checks after current-PR gates."""
    historical_issues = [issue for issue in receipt["issues"] if "historical_resolution" in issue]
    if not historical_issues:
        return []
    if not evidence:
        raise SupervisorError("historical resolutions require verified finding evidence")
    previous = previous_evidence(ledger, ledger["stage"])
    proofs = []
    github, root = target["github_repository"], target["root"]
    for issue in historical_issues:
        record = historical_finding_scope(issue, receipt, ledger, target, evidence,
                                           previous.get("goal_evidence_snapshot") if previous else None)
        historical = issue["historical_resolution"]
        prior = json.loads(runner(["gh", "api", f"repos/{github}/pulls/{historical['pr_number']}"]).stdout)
        if (prior.get("merged") is not True or not prior.get("merged_at")
                or prior.get("base", {}).get("ref") != historical["base"]
                or prior.get("base", {}).get("repo", {}).get("full_name") != github
                or (prior.get("head", {}).get("repo") or {}).get("full_name") != github
                or prior.get("head", {}).get("sha") != historical["head_sha"]
                or prior.get("merge_commit_sha") != historical["merge_commit_sha"]
                or closure_time(prior["merged_at"], "historical merge") !=
                closure_time(record["verification"]["merged_at"], "retained historical merge")
                or closure_time(prior["merged_at"], "historical merge") >=
                closure_time(current_live["merged_at"], "current merge")):
            raise SupervisorError("historical PR differs from the pinned verified merge")
        commits = bounded_api_pages(f"repos/{github}/pulls/{historical['pr_number']}/commits",
                                    lambda args: runner(args).stdout, label="historical PR commits")
        shas = {item.get("sha") for item in commits}
        count = prior.get("commits")
        if (type(count) is not int or not 1 <= count <= 250 or len(commits) != count
                or len(shas) != count or historical["head_sha"] not in shas
                or any(not isinstance(sha, str) or not SHA.fullmatch(sha) for sha in shas)
                or issue["fix_commit_sha"] not in shas):
            raise SupervisorError("historical issue fix is not in a complete pinned PR commit inventory")
        live_issue = json.loads(runner(["gh", "api", f"repos/{github}/issues/{issue['number']}"]).stdout)
        if (live_issue.get("state") != "closed" or "pull_request" in live_issue
                or live_issue.get("number") != issue["number"]
                or live_issue.get("html_url") != f"https://github.com/{github}/issues/{issue['number']}"):
            raise SupervisorError("historical issue is not actually closed in the expected repository")
        base = current_live.get("base", {}).get("sha", "")
        if not isinstance(base, str) or not SHA.fullmatch(base):
            raise SupervisorError("current PR base commit unavailable for historical ancestry")
        for descendant in (receipt["pr"]["head_sha"], base, "HEAD"):
            if runner(["git", "-C", root, "merge-base", "--is-ancestor", historical["merge_commit_sha"],
                       descendant], check=False).returncode:
                raise SupervisorError("historical merge is absent from current reviewed head/base/default checkout")
        proofs.append({**historical, "number": issue["number"], "fix_commit_sha": issue["fix_commit_sha"]})
    return proofs


def goal_output_data(receipt: dict, ledger: dict, target: dict) -> dict | None:
    if ledger.get("schema_version") != 2 or ledger["stage"] == 0:
        return None
    required_outputs = stage_profile(target, ledger["stage"], ledger).get("required_outputs") or []
    stage_key = workflow_stage_key(ledger)
    if stage_key not in {"record_review", "resolve_review_findings", "infrastructure", "open_issue_triage"} and not required_outputs:
        return None
    from kg_microbe_workflows import read_goal_evidence

    descriptor = receipt.get("goal_outputs", {}).get("goal_evidence") or {}
    root = Path(target["root"])
    errors = artifact_errors({"artifact": descriptor.get("path"), "sha256": descriptor.get("sha256")}, [root], "goal evidence")
    if errors:
        raise SupervisorError("; ".join(errors))
    previous = previous_evidence(ledger, ledger["stage"])
    if stage_key == "resolve_review_findings" and previous is None:
        raise SupervisorError("resolve_review_findings requires the exact verified record-review evidence from this cycle")
    previous_data = previous.get("goal_evidence_snapshot") if previous else None
    for artifact in historical_output_artifacts(ledger, root):
        errors = artifact_errors({"artifact": artifact["path"], "sha256": artifact["sha256"]}, [root], "archived workflow evidence")
        if errors:
            raise SupervisorError("; ".join(errors))
    expected = {**{key: ledger[key] for key in ("repository_key", "run_id", "cycle", "stage")},
                "github_repository": target["github_repository"]}
    if ledger["workflow"]["effective"]["parent_version"].split(".")[0] == "2":
        expected.update(parent_version=ledger["workflow"]["effective"]["parent_version"], stage_key=stage_key)
    data = read_goal_evidence(root / descriptor["path"], repository_root=root, previous=previous_data,
                              expected=expected,
                              required_outputs=required_outputs)
    if previous is not None and data.get("previous_evidence") != previous["goal_evidence"]:
        raise SupervisorError("goal evidence does not bind the exact previous review manifest")
    if stage_key == "infrastructure":
        scope = ledger.get("infra_scope") or {}
        snapshots = [artifact for artifact in data["artifacts"] if artifact["kind"] == "infra_snapshot"]
        if (not scope or len(snapshots) != 1 or snapshots[0]["sha256"] != scope.get("sha256")
                or data.get("scope_frozen_at") != scope.get("frozen_at")):
            raise SupervisorError("infrastructure plan must consume the supervisor-frozen notebook scope")
        from kg_microbe_workflows import read_infra_notebook
        notebook = read_infra_notebook(root / "INFRA_TASKS.md", target["github_repository"], root)
        current = {task["task_id"]: task for task in notebook["tasks"]}
        for task in data["infra_tasks"]:
            retained = current.get(task["task_id"], {})
            if retained.get("status") != task["status"] or retained.get("issue_url") != task["issue_url"]:
                raise SupervisorError("planned infrastructure tasks and issue dispositions must remain in INFRA_TASKS.md")
        for task in scope.get("tasks", []):
            if task["task_id"] not in current:
                raise SupervisorError("infrastructure history disappeared from the current notebook")
    if stage_key == "open_issue_triage":
        scope = ledger.get("issue_scope") or {}
        snapshots = [artifact for artifact in data["artifacts"] if artifact["kind"] == "issue_inventory"]
        if (not scope or len(snapshots) != 1 or snapshots[0]["sha256"] != scope.get("sha256")
                or data.get("scope_frozen_at") != scope.get("frozen_at")):
            raise SupervisorError("issue triage must consume the supervisor-frozen issue inventory")
        from kg_microbe_workflows.issue_triage import issue_triage_blockers
        blockers = issue_triage_blockers(data)
        if blockers:
            raise SupervisorError("critical/high issue prerequisites hold this goal: " + ", ".join(map(str, blockers)))
    if stage_key == "resolve_review_findings":
        expected_ids = {item["finding_id"] for item in previous_data.get("findings", [])}
        actual_ids = [finding for group in data.get("groups", []) for finding in group["finding_ids"]]
        if set(actual_ids) != expected_ids or len(actual_ids) != len(set(actual_ids)):
            raise SupervisorError("review resolution groups must cover each frozen review finding exactly once")
    for item in data.get("groups", []) + data.get("infra_tasks", []):
        if item.get("status") == "resolved":
            url = item.get("issue_url", "")
            match = re.fullmatch(r"https://github\.com/" + re.escape(target["github_repository"]) + r"/issues/([1-9]\d*)", url, re.I)
            if not match or int(match[1]) not in {issue["number"] for issue in receipt.get("issues", [])}:
                raise SupervisorError("resolved review/infra groups require matching independently verified closure issues")
    for issue in receipt.get("issues", []):
        if "historical_resolution" in issue:
            historical_finding_scope(issue, receipt, ledger, target, data, previous_data)
    return data


def historical_output_artifacts(ledger: dict, repository_root: Path) -> list[dict]:
    """Every closed report stays immutable, including prior infrastructure plans."""
    artifacts = []
    for record in ledger["completed_stages"]:
        if record.get("goal_evidence"):
            artifacts.append(record["goal_evidence"])
            from kg_microbe_workflows import evidence_artifacts
            try:
                artifacts.extend(evidence_artifacts(record["goal_evidence_snapshot"], repository_root=repository_root))
            except Exception as error:
                raise SupervisorError("archived workflow evidence: " + str(error)) from error
    return artifacts


def output_artifacts(receipt: dict, evidence: dict | None) -> list[dict]:
    outputs = receipt.get("goal_outputs") or {}
    artifacts = [outputs[key] for key in ("goal_evidence", "infra_tasks") if isinstance(outputs.get(key), dict)]
    if evidence:
        artifacts += evidence.get("artifacts", [])
    return artifacts


def verify_versioned_artifacts(receipt: dict, ledger: dict, target: dict, runner, head: str,
                               *, historical_infra_notebook: tuple[str, str] | None = None) -> None:
    if ledger.get("schema_version") != 2:
        return
    if receipt.get("schema_version") == 1 and ledger.get("legacy_receipt_stage") == ledger["stage"] and ledger["stage"] < 4:
        return
    evidence = goal_output_data(receipt, ledger, target)
    artifacts = output_artifacts(receipt, evidence) + historical_output_artifacts(ledger, Path(target["root"]))
    if evidence:
        from kg_microbe_workflows import evidence_artifacts
        previous = previous_evidence(ledger, ledger["stage"])
        artifacts += evidence_artifacts(evidence, repository_root=Path(target["root"]),
                                       previous=previous.get("goal_evidence_snapshot") if previous else None)
    seen = set()
    for artifact in artifacts:
        identity = (artifact["path"], artifact["sha256"])
        if identity in seen:
            continue
        seen.add(identity)
        if historical_infra_notebook is not None and artifact["path"] == "INFRA_TASKS.md":
            historical_sha256, current_sha256 = historical_infra_notebook
            if artifact["sha256"] != historical_sha256:
                raise SupervisorError("historical infrastructure notebook digest mismatch")
            errors = artifact_errors({"artifact": "INFRA_TASKS.md", "sha256": current_sha256},
                                     [Path(target["root"])], "versioned workflow evidence")
            if errors:
                raise SupervisorError("; ".join(errors))
            root = Path(target["root"]).resolve()
            head_res = runner(["git", "-C", str(root), "rev-parse", f"{head}:INFRA_TASKS.md"], check=False)
            actual_res = runner(["git", "-C", str(root), "hash-object", "--no-filters", "--", "INFRA_TASKS.md"], check=False)
            head_blob = head_res.stdout.strip() if head_res.returncode == 0 else ""
            actual = actual_res.stdout.strip() if actual_res.returncode == 0 else ""
            if not SHA.fullmatch(head_blob) or not SHA.fullmatch(actual) or head_blob == actual:
                raise SupervisorError("workflow evidence is not versioned at the exact reviewed final head: INFRA_TASKS.md")
            show_res = runner(["git", "-C", str(root), "show", f"{head}:INFRA_TASKS.md"], check=False)
            if show_res.returncode != 0:
                raise SupervisorError("historical infrastructure notebook unavailable at reviewed final head")
            historical_raw = show_res.stdout.encode()
            if hashlib.sha256(historical_raw).hexdigest() != historical_sha256:
                raise SupervisorError("historical infrastructure notebook bytes at reviewed final head differ from receipt")
            from kg_microbe_workflows import validate_infra_notebook
            validate_infra_notebook(historical_raw, target["github_repository"])
            continue
        errors = artifact_errors({"artifact": artifact["path"], "sha256": artifact["sha256"]}, [Path(target["root"])], "versioned workflow evidence")
        if errors:
            raise SupervisorError("; ".join(errors))
        path = Path(artifact["path"])
        root = Path(target["root"]).resolve()
        resolved = (root / path).resolve()
        if path.is_absolute() or not resolved.is_relative_to(root):
            raise SupervisorError("versioned workflow artifacts require repository-relative paths")
        relative = str(resolved.relative_to(root))
        blob = runner(["git", "-C", str(root), "rev-parse", f"{head}:{relative}"]).stdout.strip()
        actual = runner(["git", "-C", str(root), "hash-object", "--no-filters", "--", relative]).stdout.strip()
        if not SHA.fullmatch(blob) or blob != actual:
            raise SupervisorError("workflow evidence is not versioned at the exact reviewed final head: " + relative)


def validate_receipt(receipt: dict, ledger: dict, target: dict, runtime: Path,
                     *, historical_infra_notebook: tuple[str, str] | None = None) -> list[str]:
    """Validate claims and bound evidence before any remote verification."""
    errors = []
    for key in ("run_id", "repository_key", "stage"):
        if receipt.get(key) != ledger[key]:
            errors.append(f"receipt {key} mismatch")
    legacy_receipt = (ledger.get("schema_version") == 2 and receipt.get("schema_version") == 1
                      and ledger.get("cycle") == 1 and ledger.get("legacy_receipt_stage") == ledger["stage"]
                      and ledger["stage"] < 4)
    if ledger.get("schema_version") == 2 and not legacy_receipt:
        if receipt.get("cycle") != ledger["cycle"]:
            errors.append("receipt cycle mismatch")
        if receipt.get("workflow_sha256") != ledger["workflow"]["sha256"]:
            errors.append("receipt pinned workflow mismatch")
    expected_version = 1 if legacy_receipt else ledger.get("schema_version", 1)
    if receipt.get("schema_version") != expected_version or receipt.get("goal_complete") is not True:
        errors.append("receipt version/goal completion invalid")
    if receipt.get("goal_identity") != ledger.get("adopted_goal") or not ledger.get("adopted_goal"):
        errors.append("receipt goal identity mismatch")
    status = receipt.get("status")
    if status not in {"completed", "no_changes"}:
        errors.append("receipt must be completed or no_changes")
    roots = [Path(target["root"]), runtime]
    errors += artifact_errors(receipt.get("coverage", {}), roots, "coverage")
    pr = receipt.get("pr") or {}
    no_changes = receipt.get("no_changes") or {}
    head = no_changes.get("head_sha") if status == "no_changes" else pr.get("head_sha")
    if not isinstance(head, str) or not SHA.fullmatch(head):
        errors.append("valid final head SHA required")
    publication_policy = ledger.get("workflow", {}).get("effective", {}).get("session_state_policy", {})
    if "deliverable_commits" in receipt or publication_policy.get("require_origin_publication_at_closure"):
        from kg_microbe_workflows.commit_publication import PublicationError, recorded_commits
        try:
            commits = recorded_commits(receipt.get("deliverable_commits"), head=head if status == "completed" else None)
            if status == "no_changes" and commits:
                errors.append("no-change closure cannot contain deliverable commits")
        except PublicationError as error:
            errors.append(str(error))
    review = receipt.get("review") or {}
    if review.get("status") != "complete" or review.get("remaining_findings") != 0 or review.get("head_sha") != head:
        errors.append("review incomplete, has findings, or does not cover final head")
    errors += artifact_errors(review, roots, "review")
    validations = receipt.get("validation")
    if not isinstance(validations, list) or not validations:
        errors.append("validation evidence required")
    else:
        for index, validation in enumerate(validations):
            if (not isinstance(validation, dict) or not validation.get("command")
                    or validation.get("status") != "passed" or validation.get("head_sha") != head):
                errors.append(f"validation {index}: must pass at final head")
            errors += artifact_errors(validation, roots, f"validation {index}")
    issues = receipt.get("issues")
    if not isinstance(issues, list):
        errors.append("issues must be an explicit list")
    else:
        numbers = set()
        for issue in issues:
            if not isinstance(issue, dict):
                errors.append("invalid issue disposition")
                continue
            number = issue.get("number")
            if (type(number) is not int or number <= 0 or number in numbers
                    or issue.get("disposition") != "addressed"
                    or not SHA.fullmatch(str(issue.get("fix_commit_sha", "")))):
                errors.append("each issue needs unique number and addressed fix commit")
            if "historical_resolution" in issue:
                try:
                    historical_resolution_record(issue, receipt, ledger, target)
                except SupervisorError as error:
                    errors.append(str(error))
            if isinstance(number, int):
                numbers.add(number)
    if status == "no_changes":
        if (receipt.get("pr") is not None or issues != [] or not no_changes.get("explanation")
                or no_changes.get("no_goal_owned_changes") is not True
                or no_changes.get("no_open_goal_pr") is not True):
            errors.append("no-change proof incomplete")
    else:
        branch = pr.get("branch", "")
        if (type(pr.get("number")) is not int or pr["number"] <= 0 or not branch
                or branch == target["default_branch"] or branch.startswith("-")
                or pr.get("base") != target["default_branch"]):
            errors.append("PR identity/branch/base invalid")
    cleanup = receipt.get("cleanup") or {}
    if cleanup.get("checkout_ready") is not True:
        errors.append("checkout readiness not attested")
    if status == "completed" and (cleanup.get("remote_branch_deleted") is not True
                                  or cleanup.get("local_branch_deleted") is not True):
        errors.append("branch cleanup not attested")
    if ledger.get("schema_version") == 2 and not legacy_receipt:
        outputs = receipt.get("goal_outputs") or {}
        infra = outputs.get("infra_tasks") or {}
        if infra.get("path") != "INFRA_TASKS.md":
            errors.append("goal output must bind the repository INFRA_TASKS.md")
        expected_infra_sha = infra.get("sha256")
        if historical_infra_notebook is not None:
            historical_sha256, current_sha256 = historical_infra_notebook
            if infra.get("sha256") != historical_sha256:
                errors.append("historical infrastructure notebook digest mismatch")
            expected_infra_sha = current_sha256
        errors += artifact_errors({"artifact": infra.get("path"), "sha256": expected_infra_sha},
                                  [Path(target["root"])], "infrastructure notes")
        try:
            from kg_microbe_workflows import read_infra_notebook
            read_infra_notebook(Path(target["root"]) / "INFRA_TASKS.md", target["github_repository"], Path(target["root"]))
            goal_output_data(receipt, ledger, target)
        except Exception as error:
            errors.append("goal outputs: " + str(error))
    try:
        from kg_microbe_workflows.closure import multi_pr_members
        members = multi_pr_members(receipt)
        for member in members:
            if member["base"] != target["default_branch"]:
                errors.append("ordered PR base differs from configured default branch")
            errors += artifact_errors(member["review"], roots, f"PR {member['number']} review")
            for validation in member["validation"]:
                errors += artifact_errors(validation, roots, f"PR {member['number']} validation")
    except ValueError as error:
        errors.append(str(error))
    return errors


def bounded_api_pages(endpoint: str, read, *, label: str) -> list[dict]:
    """Read complete REST pages with a bounded, same-endpoint next-link chain."""
    from urllib.parse import parse_qs, urlsplit
    result = []
    for page in range(1, 101):
        raw = read(["gh", "api", "--include", f"{endpoint}?per_page=100&page={page}"]).replace("\r\n", "\n")
        try:
            headers, separator, body = raw.partition("\n\n")
            if not separator or not re.match(r"^HTTP/\S+ 200\b", headers):
                raise ValueError("pagination lacks a successful HTTP response")
            rows = json.loads(body)
            if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, dict) for row in rows):
                raise ValueError("invalid page")
            result.extend(rows)
            links = [line.split(":", 1)[1].strip() for line in headers.splitlines() if line.lower().startswith("link:")]
            if len(links) > 1:
                raise ValueError("ambiguous pagination")
            following = re.findall(r'<([^>]+)>;\s*rel="next"', links[0] if links else "")
            if not following:
                return result
            parsed = urlsplit(following[0])
            params = parse_qs(parsed.query)
            if (len(following) != 1
                    or f"{parsed.scheme}://{parsed.netloc}{parsed.path}".casefold() != f"https://api.github.com/{endpoint}".casefold()
                    or params != {"per_page": ["100"], "page": [str(page + 1)]} or not rows):
                raise ValueError("invalid next-page identity")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise SupervisorError(f"cannot verify {label}: {error}") from error
    raise SupervisorError(f"{label} inventory exceeded its 100-page bound")


def verify_triage_fix_provenance(evidence: dict, github: str, root: str, runner=command) -> dict:
    """Verify prior or current fixes without falsely assigning them to this goal PR (#862)."""
    fixed = [item for item in evidence["issue_triage"]["dispositions"] if item["status"] == "fixed"]
    if len(fixed) > 10000:
        raise SupervisorError("triage fix verification exceeds its bounded inventory")
    deadline = time.monotonic() + 180

    def read(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SupervisorError("triage fix verification exceeded its 180-second deadline")
        result = runner(args, timeout=max(1, min(45, int(remaining))))
        if result.returncode:
            raise SupervisorError("triage fix provenance query failed")
        return result.stdout

    default_head = read(["git", "-C", root, "rev-parse", "HEAD"]).strip()
    if not SHA.fullmatch(default_head):
        raise SupervisorError("triage fix provenance needs the verified default-branch head")
    prs = {}
    verified = []
    for item in fixed:
        commit = item["commit_sha"]
        matched = []
        for url in item["pr_urls"]:
            match = re.fullmatch(r"https://github\.com/" + re.escape(github) + r"/pull/([1-9]\d*)", url, re.I)
            if not match:
                raise SupervisorError("triage fix PR belongs to another repository")
            number = int(match[1])
            if number not in prs:
                try:
                    live = json.loads(read(["gh", "api", f"repos/{github}/pulls/{number}"]))
                    merge = live["merge_commit_sha"]
                    if (live.get("number") != number or live.get("merged") is not True or not live.get("merged_at")
                            or live.get("base", {}).get("repo", {}).get("full_name", "").casefold() != github.casefold()
                            or not isinstance(merge, str) or not SHA.fullmatch(merge)):
                        raise ValueError("referenced fix PR is not merged in the expected repository")
                    read(["git", "-C", root, "merge-base", "--is-ancestor", merge, default_head])
                    prs[number] = {"merge_commit_sha": merge, "commits": None}
                except (KeyError, TypeError, ValueError) as error:
                    raise SupervisorError("cannot verify triage fix PR: " + str(error)) from error
            pr = prs[number]
            if commit == pr["merge_commit_sha"]:
                matched.append(number)
                continue
            if pr["commits"] is None:
                rows = bounded_api_pages(f"repos/{github}/pulls/{number}/commits", read, label="fix PR commits")
                commits = [row.get("sha") for row in rows]
                if (any(not isinstance(value, str) or not SHA.fullmatch(value) for value in commits)
                        or len(set(commits)) != len(commits)):
                    raise SupervisorError("fix PR commit inventory is malformed or repeated")
                pr["commits"] = set(commits)
            if commit in pr["commits"]:
                matched.append(number)
        if not matched:
            raise SupervisorError(f"issue {item['number']} claimed fix commit is absent from its merged PRs")
        verified.append({"number": item["number"], "commit_sha": commit, "pr_numbers": matched})
    return {"verified_at": now(), "default_branch_head": default_head, "fixed_issues": verified}


def verify_remote_issue_triage(evidence: dict, github: str, runner=command) -> dict:
    """Check label/state claims and actual sub-issue edges, without mutating GitHub (#852)."""
    triage = evidence["issue_triage"]
    inventory = {item["number"]: item for item in triage["inventory"]}
    dispositions = {item["number"]: item for item in triage["dispositions"]}
    tracked_groups = [group for group in triage["groups"] if group.get("tracking_issue_url")]
    tracking = {int(group["tracking_issue_url"].rsplit("/", 1)[-1]): group for group in tracked_groups}
    if len(tracking) != len(tracked_groups):
        raise SupervisorError("active groups must have distinct tracking issues")
    # A duplicate URL is not evidence that the surviving issue exists (#865).
    duplicates = {item["number"]: int(item["duplicate_of"].rsplit("/", 1)[-1])
                  for item in triage["dispositions"] if item["status"] == "duplicate"}
    numbers = sorted(set(inventory) | set(tracking) | set(duplicates.values()))
    if len(numbers) > 30000:
        raise SupervisorError("triage remote verification exceeds its bounded inventory")
    owner, name = github.split("/")
    deadline = time.monotonic() + 180

    def read(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SupervisorError("triage remote verification exceeded its 180-second deadline")
        result = runner(args, timeout=max(1, min(45, int(remaining))))
        if result.returncode:
            raise SupervisorError("triage remote verification query failed")
        return result.stdout

    live = {}
    for start in range(0, len(numbers), 50):
        batch = numbers[start:start + 50]
        fields = " ".join(f"i{number}:issue(number:{number}){{__typename number state url "
                          "labels(first:100){totalCount nodes{name} pageInfo{hasNextPage}}}" for number in batch)
        query = "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){nameWithOwner " + fields + "}}"
        try:
            payload = json.loads(read(["gh", "api", "graphql", "-f", "query=" + query,
                                       "-f", "owner=" + owner, "-f", "name=" + name]))
            source = payload["data"]["repository"]
            if payload.get("errors") or source["nameWithOwner"].casefold() != github.casefold():
                raise ValueError("unavailable issue data or wrong repository")
            for number in batch:
                issue = source[f"i{number}"]
                labels = issue["labels"]
                names = [item["name"] for item in labels["nodes"]]
                if (issue["__typename"] != "Issue" or issue["number"] != number
                        or issue["url"].casefold() != f"https://github.com/{github}/issues/{number}".casefold()
                        or issue["state"] not in {"OPEN", "CLOSED"}
                        or labels["pageInfo"]["hasNextPage"] is not False or labels["totalCount"] != len(names)
                        or any(not isinstance(label, str) for label in names) or len(set(names)) != len(names)):
                    raise ValueError("invalid issue identity/state or incomplete labels")
                live[number] = {"state": issue["state"], "labels": names}
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise SupervisorError("cannot verify triage issues: " + str(error)) from error
    for number, item in inventory.items():
        issue = live[number]
        assigned = set(item["assigned_labels"])
        if ([label for label in issue["labels"] if label.startswith("severity:")] != [f"severity:{item['severity']}"]
                or not assigned <= set(issue["labels"])):
            raise SupervisorError(f"issue {number} has not received its recorded severity labels")
        terminal = dispositions[number]["status"] in {"fixed", "duplicate", "wont_fix"}
        if issue["state"] != ("CLOSED" if terminal else "OPEN"):
            raise SupervisorError(f"issue {number} live state disagrees with its triage disposition")
        if number in duplicates and item["severity"] in {"critical", "high"} and live[duplicates[number]]["state"] != "CLOSED":
            raise SupervisorError(f"critical/high duplicate {number} retains unresolved work in its surviving issue")
    for number, group in tracking.items():
        rows = bounded_api_pages(f"repos/{github}/issues/{number}/sub_issues", read, label="group sub-issues")
        observed = set()
        for child in rows:
            url = child.get("html_url")
            if not isinstance(url, str) or "pull_request" in child:
                raise SupervisorError("sub-issue is not a real issue")
            if url in observed:
                raise SupervisorError("repeated sub-issue page or identity")
            observed.add(url)
        expected_children = {f"https://github.com/{github}/issues/{child}".casefold() for child in group["sub_issue_numbers"]}
        if not expected_children <= {url.casefold() for url in observed}:
            raise SupervisorError(f"group {group['group_id']} lacks its recorded GitHub sub-issue relationships")
    return {"verified_at": now(), "issues_checked": len(inventory), "tracking_issues_checked": len(tracking),
            "duplicate_targets_checked": len(set(duplicates.values())),
            "severity_labels_verified": True, "dispositions_verified": True, "sub_issue_relationships_verified": True}


def verify_remote_receipt(receipt: dict, ledger: dict, target: dict, runner=command,
                          *, runtime: Path | None = None,
                          historical_infra_notebook: tuple[str, str] | None = None) -> dict:
    """Read-only independent checks. Query failure is never branch absence."""
    root, github = target["root"], target["github_repository"]

    def git(*args, **kwargs):
        return runner(["git", "-C", root, *args], **kwargs)

    def gh_json(*args):
        return json.loads(runner(["gh", *args]).stdout)

    if normalize_github(git("remote", "get-url", "origin").stdout) != github.casefold():
        raise SupervisorError("origin changed before closure verification")
    if git("status", "--porcelain=v1", "--untracked-files=all").stdout:
        raise SupervisorError("working tree is not clean; preserve unrelated work and finish safe cleanup")
    if git("symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip() != target["default_branch"]:
        raise SupervisorError("checkout is not on the configured default branch")
    head = receipt["no_changes"]["head_sha"] if receipt["status"] == "no_changes" else receipt["pr"]["head_sha"]
    verify_versioned_artifacts(receipt, ledger, target, runner, head,
                               historical_infra_notebook=historical_infra_notebook)
    if ledger.get("schema_version") == 2 and receipt.get("schema_version") == 2:
        from kg_microbe_workflows import read_infra_notebook, validate_infra_notebook
        notebooks = [read_infra_notebook(Path(root) / "INFRA_TASKS.md", github, Path(root))]
        if historical_infra_notebook is not None:
            hist_res = git("show", f"{head}:INFRA_TASKS.md", check=False)
            if hist_res.returncode != 0:
                raise SupervisorError("historical infrastructure notebook unavailable at reviewed final head")
            notebooks.append(validate_infra_notebook(hist_res.stdout.encode(), github))
        for notebook in notebooks:
            for task in notebook["tasks"]:
                if task.get("issue_url"):
                    number = task["issue_url"].rsplit("/", 1)[-1]
                    issue = gh_json("api", f"repos/{github}/issues/{number}")
                    if issue.get("state") not in {"open", "closed"} or "pull_request" in issue:
                        raise SupervisorError("infrastructure notebook must reference real GitHub issues")
    evidence = goal_output_data(receipt, ledger, target)
    triage_verification = (verify_remote_issue_triage(evidence, github, runner)
                          if evidence and evidence.get("stage_key") == "open_issue_triage" else None)
    if triage_verification is not None:
        triage_verification["fix_provenance"] = verify_triage_fix_provenance(evidence, github, root, runner)
    if evidence:
        for item in evidence.get("groups", []) + evidence.get("infra_tasks", []):
            if item["status"] == "deferred":
                match = re.fullmatch(r"https://github\.com/" + re.escape(github) + r"/issues/([1-9]\d*)", item["issue_url"], re.I)
                if not match:
                    raise SupervisorError("deferred item issue belongs to another repository")
                deferred_issue = gh_json("api", f"repos/{github}/issues/{match[1]}")
                if deferred_issue.get("state") != "open" or "pull_request" in deferred_issue:
                    raise SupervisorError("deferred review/infrastructure issue must remain open")
    if receipt["status"] == "no_changes":
        head = receipt["no_changes"]["head_sha"]
        if git("rev-parse", "HEAD").stdout.strip() != head:
            raise SupervisorError("no-change HEAD mismatch")
        if ledger.get("baseline_status") != "":
            raise SupervisorError("no-change claim cannot erase initially uncommitted work")
        if ledger.get("baseline_head") != head:
            raise SupervisorError("no-change baseline HEAD changed")
        # A default-branch-only query cannot rule out goal work on a feature
        # branch. Until explicit ownership inventory is available, fail closed
        # when this repository has any open PR rather than bless a false no-op.
        prs = gh_json("pr", "list", "-R", github, "--state", "open", "--limit", "1000", "--json", "number")
        if prs:
            raise SupervisorError("open PR exists for no-change branch")
        return {"verified_at": now(), "status": "no_changes", "head_sha": head,
                **({"issue_triage": triage_verification} if triage_verification is not None else {})}
    if "prs" in receipt:
        proof = verify_ordered_prs(receipt, ledger, target, runtime, evidence, runner,
                                   historical_infra_notebook=historical_infra_notebook)
    else:
        current_issues = [item for item in receipt["issues"] if "historical_resolution" not in item]
        proof, live, commits = verify_pr_member(receipt["pr"], current_issues, target, runner)
        historical = verify_historical_issue_resolutions(receipt, ledger, target, evidence, live, runner)
        if historical:
            proof["historical_issue_resolutions"] = historical
        proof["commit_publication"] = verify_receipt_publication(
            receipt, target, {item["sha"] for item in commits}, runner)
    return {**proof, **({"issue_triage": triage_verification} if triage_verification is not None else {})}


def verify_receipt_publication(receipt: dict, target: dict, verified_commits: set[str], runner=command) -> dict:
    """Use only independently verified merged members as publication authority."""
    from kg_microbe_workflows.commit_publication import recorded_commits, verify_origin_publication
    head = receipt["pr"]["head_sha"]
    deliverables = recorded_commits(receipt.get("deliverable_commits", [head]), head=head)
    return verify_origin_publication(deliverables, [Path(target["root"])], target["github_repository"],
        verified_merged_pr_commits=sorted(verified_commits), runner=runner)


def verify_pr_member(pr: dict, issues: list[dict], target: dict, runner=command, *, ordered=False):
    """The existing single-PR gates, repeated independently for every member."""
    root, github = target["root"], target["github_repository"]

    def git(*args, **kwargs):
        return runner(["git", "-C", root, *args], **kwargs)

    def gh_json(*args):
        return json.loads(runner(["gh", *args]).stdout)

    live = gh_json("api", f"repos/{github}/pulls/{pr['number']}")
    if (live.get("merged") is not True or not live.get("merged_at")
            or live.get("base", {}).get("ref") != pr["base"]
            or live.get("base", {}).get("repo", {}).get("full_name", "").casefold() != github.casefold()
            or live.get("head", {}).get("ref") != pr["branch"]
            or live.get("head", {}).get("sha") != pr["head_sha"]
            or (live.get("head", {}).get("repo") or {}).get("full_name", "").casefold() != github.casefold()):
        raise SupervisorError("PR is not actually merged at the attested repository/base/head")
    merge_commit = live.get("merge_commit_sha", "")
    if not isinstance(merge_commit, str) or not SHA.fullmatch(merge_commit):
        raise SupervisorError("valid merged commit identity unavailable")
    if git("merge-base", "--is-ancestor", merge_commit, "HEAD", check=False).returncode != 0:
        raise SupervisorError("default-branch checkout does not contain the verified merge commit")
    # gh's required-check query resolves the effective requirements; an error,
    # missing query result, or a pending/failing required check blocks progress.
    check_result = runner(["gh", "pr", "checks", "-R", github, str(pr["number"]), "--required",
                           "--json", "name,state,bucket"], check=False)
    try:
        checks = json.loads(check_result.stdout)
    except (TypeError, json.JSONDecodeError):
        checks = None
    if isinstance(checks, list) and checks:
        if check_result.returncode or any(check.get("bucket") != "pass" for check in checks):
            raise SupervisorError("required CI evidence is not passing")
    else:
        # Empty output is not proof of an empty policy. The branch itself must
        # be unprotected and effective rules must have no required-check rule.
        encoded_base = quote(pr["base"], safe="")
        rules = gh_json("api", f"repos/{github}/rules/branches/{encoded_base}")
        branch_state = gh_json("api", f"repos/{github}/branches/{encoded_base}")
        if (not isinstance(rules, list) or branch_state.get("protected") is not False
                or any(rule.get("type") == "required_status_checks" for rule in rules)):
            raise SupervisorError("required CI evidence absent and absence of requirements is unproven")
        checks = []
    declared_checks = target.get("required_checks", [])
    if declared_checks:
        all_checks = gh_json("pr", "checks", "-R", github, str(pr["number"]), "--json", "name,state,bucket")
        by_name = {check["name"]: check for check in all_checks}
        if any(name not in by_name or by_name[name].get("bucket") != "pass" for name in declared_checks):
            raise SupervisorError("repository-declared CI policy is not satisfied")
    if ordered:
        commits = bounded_api_pages(f"repos/{github}/pulls/{pr['number']}/commits",
                                    lambda args: runner(args).stdout, label="ordered PR commits")
        commit_shas = {item.get("sha") for item in commits}
        # GitHub's PR commit endpoint is capped at 250. Never mistake a
        # successful last page for a complete larger PR.
        count = live.get("commits")
        if (type(count) is not int or not 1 <= count <= 250 or len(commits) != count
                or len(commit_shas) != count or pr["head_sha"] not in commit_shas
                or any(not isinstance(sha, str) or not SHA.fullmatch(sha) for sha in commit_shas)):
            raise SupervisorError("ordered PR commit inventory is incomplete or repeated")
    else:
        pages = gh_json("api", "--paginate", "--slurp", f"repos/{github}/pulls/{pr['number']}/commits?per_page=100")
        commits = [item for page in pages for item in page]
        commit_shas = {item["sha"] for item in commits}
    for issue in issues:
        live_issue = gh_json("api", f"repos/{github}/issues/{issue['number']}")
        if (live_issue.get("state") != "closed" or "pull_request" in live_issue
                or issue["fix_commit_sha"] not in commit_shas):
            raise SupervisorError(f"issue {issue['number']} not closed with a fix in this PR")
    remote = git("ls-remote", "--exit-code", "--heads", "origin", f"refs/heads/{pr['branch']}", check=False)
    if remote.returncode != 2:
        raise SupervisorError("remote branch still exists or absence query failed")
    local = git("show-ref", "--verify", "--quiet", f"refs/heads/{pr['branch']}", check=False)
    if local.returncode != 1:
        raise SupervisorError("local branch still exists or absence query failed")
    return ({"verified_at": now(), "status": "merged", "pr_number": pr["number"],
             "head_sha": pr["head_sha"], "merge_commit_sha": live.get("merge_commit_sha"),
             "merged_at": live["merged_at"], "checks": checks}, live, commits)


def closure_time(value, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone absent")
        return parsed
    except (AttributeError, TypeError, ValueError) as error:
        raise SupervisorError(f"invalid {label} timestamp") from error


GitEntry = tuple[str, str] | None


def commit_changes(root: str, commit: str, runner) -> dict[str, tuple[GitEntry, GitEntry]]:
    """Complete non-merge, non-rename content changes at an exact commit.

    A merge's combined diff can omit paths; rename/copy attribution has multiple
    names. Refuse those ambiguous producers instead of inferring authorship.
    """
    identity = runner(["git", "-C", root, "rev-list", "--parents", "-n", "1", commit]).stdout.strip().split()
    if (not 1 <= len(identity) <= 2 or identity[0] != commit
            or any(not SHA.fullmatch(item) for item in identity)):
        raise SupervisorError("evidence/fix producer must be an exact non-merge commit")
    raw = runner(["git", "-C", root, "diff-tree", "--root", "--no-commit-id", "--raw",
                  "--no-abbrev", "-r", "-M", "-z", commit]).stdout
    parts = raw.split("\0")
    if parts[-1] != "" or len(parts) > 20001 or len(parts) % 2 != 1:
        raise SupervisorError("invalid or incomplete producer change inventory")
    changes = {}
    for index in range(0, len(parts) - 1, 2):
        meta, path = parts[index:index + 2]
        match = re.fullmatch(r":(000000|100644|100755) (000000|100644|100755) ([0-9a-f]{40}) ([0-9a-f]{40}) ([AMD])", meta)
        if (not match or not path or path in changes or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(ord(char) < 32 for char in path)):
            raise SupervisorError("ambiguous rename, merge, mode or path in producer changes")
        old = None if match[1] == "000000" and match[3] == "0" * 40 else (match[1], match[3])
        new = None if match[2] == "000000" and match[4] == "0" * 40 else (match[2], match[4])
        if ((old is not None and (old[0] == "000000" or old[1] == "0" * 40))
                or (new is not None and (new[0] == "000000" or new[1] == "0" * 40))
                or (match[5] == "A" and (old is not None or new is None))
                or (match[5] == "D" and (old is None or new is not None))
                or (match[5] == "M" and (old is None or new is None))):
            raise SupervisorError("producer entry modes, blobs and change kind disagree")
        changes[path] = (old, new)
    return changes


def tree_entry(root: str, head: str, path: str, runner) -> GitEntry:
    # Even after --, Git parses pathspec magic and globs. A literal lookup is
    # essential when absence is used as evidence that a deletion survives.
    raw = runner(["git", "-C", root, "--literal-pathspecs", "ls-tree", "-z", head, "--", path]).stdout
    if not raw:
        return None
    match = re.fullmatch(r"(100644|100755) blob ([0-9a-f]{40})\t" + re.escape(path) + "\x00", raw)
    if not match:
        raise SupervisorError("exact regular-file blob unavailable")
    return match[1], match[2]


def verify_ordered_prs(receipt: dict, ledger: dict, target: dict, runtime: Path | None,
                       evidence: dict | None, runner=command,
                       *, historical_infra_notebook: tuple[str, str] | None = None) -> dict:
    """Corroborated same-goal membership plus independent remote and Git proof."""
    from kg_microbe_progress.prs import AssociationError, require_current_pr_associations
    from kg_microbe_workflows.closure import multi_pr_members
    try:
        members = multi_pr_members(receipt)
        if runtime is None:
            raise ValueError("ordered closure requires the supervisor's session directory")
        errors = validate_receipt(receipt, ledger, target, runtime,
                                  historical_infra_notebook=historical_infra_notebook)
        if errors:
            raise ValueError("; ".join(errors))
        require_current_pr_associations(runtime, ledger, {item["number"] for item in members})
    except (AssociationError, ValueError) as error:
        raise SupervisorError(str(error)) from error
    root = target["root"]
    start = closure_time(ledger["adopted_goal"]["started_at"], "goal start")
    cutoff = closure_time(now(), "verification")
    deadline = time.monotonic() + 300

    def read(args, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SupervisorError("ordered closure verification exceeded its deadline")
        # Publication queries impose a tighter bound than ordinary member
        # verification; preserve it within the shared ordered-closure deadline.
        kwargs["timeout"] = min(kwargs.get("timeout", 45), 45, remaining)
        result = runner(args, **kwargs)
        if result.returncode and kwargs.get("check", True):
            raise SupervisorError("ordered closure query failed")
        return result

    expected = {}
    if evidence:
        current = [receipt["goal_outputs"]["goal_evidence"], *evidence["artifacts"]]
        expected = {item["path"]: item["sha256"] for item in current}
    attributed = {item["path"]: item["sha256"] for item in receipt["evidence_attributions"]}
    if attributed != expected:
        raise SupervisorError("evidence attribution set differs from exact current-stage outputs")
    proofs, commits_by_pr, changed = [], {}, {}
    previous = None
    for member in members:
        issues = [item for item in receipt["issues"] if item["pr_number"] == member["number"]]
        proof, live, commits = verify_pr_member(member, issues, target, read, ordered=True)
        if member["merge_commit_sha"] != proof["merge_commit_sha"]:
            raise SupervisorError("ordered PR merge commit differs from independently verified merge")
        created, merged = closure_time(live.get("created_at"), "PR creation"), closure_time(live.get("merged_at"), "PR merge")
        if not start <= created <= merged <= cutoff:
            raise SupervisorError("ordered PR lies outside the adopted-goal closure window")
        for sha in (member["head_sha"], member["merge_commit_sha"]):
            if read(["git", "-C", root, "cat-file", "-t", sha]).stdout.strip() != "commit":
                raise SupervisorError("ordered PR identity is not a commit")
        if previous and (closure_time(previous["merged_at"], "previous merge") > merged
                or read(["git", "-C", root, "merge-base", "--is-ancestor", previous["merge_commit_sha"],
                         member["head_sha"]], check=False).returncode != 0):
            raise SupervisorError("ordered PRs are unordered or final integration omits an earlier merge")
        commit_shas = set()
        for item in commits:
            when = closure_time((item.get("commit") or {}).get("committer", {}).get("date"), "PR commit")
            if not start <= when <= merged:
                raise SupervisorError("ordered PR commit lies outside the adopted-goal closure window")
            if read(["git", "-C", root, "merge-base", "--is-ancestor", item["sha"], member["head_sha"]], check=False).returncode:
                raise SupervisorError("PR commit is not in its reviewed head")
            commit_shas.add(item["sha"])
        commits_by_pr[member["number"]] = commit_shas
        proofs.append(proof)
        previous = proof
    final = members[-1]["head_sha"]
    for attribution in receipt["evidence_attributions"]:
        commit, path = attribution["commit_sha"], attribution["path"]
        if commit not in commits_by_pr[attribution["pr_number"]]:
            raise SupervisorError("evidence producer is not in its attributed PR")
        if commit not in changed:
            changed[commit] = commit_changes(root, commit, read)
        entries = changed[commit].get(path)
        final_entry = tree_entry(root, final, path, read)
        if (not entries or entries[1] is None or entries[1] != final_entry
                or (entries[0] is not None and entries[0][1] == entries[1][1])):
            raise SupervisorError("evidence was not produced with the final bytes by its attributed commit")
    member_by_number = {item["number"]: item for item in members}
    member_order = {item["number"]: index for index, item in enumerate(members)}
    evidence_by_path = {item["path"]: item for item in receipt["evidence_attributions"]}
    attributed_fixes = {(item["pr_number"], item["fix_commit_sha"]) for item in receipt["issues"]}
    for issue in receipt["issues"]:
        commit = issue["fix_commit_sha"]
        if commit not in changed:
            changed[commit] = commit_changes(root, commit, read)
        changes = changed[commit]
        if not changes or not any(old != new for old, new in changes.values()):
            raise SupervisorError("issue fix commit has no entry changes")
        member = member_by_number[issue["pr_number"]]
        superseded = {item["path"]: item for item in issue.get("superseded_paths", [])}
        if not superseded.keys() <= changes.keys() or superseded.keys() & expected.keys():
            raise SupervisorError("fix supersession must name original non-evidence changed paths")
        for path, (old, produced) in changes.items():
            if path in expected:
                producer = evidence_by_path[path]
                successor = producer["commit_sha"]
                if producer["pr_number"] == issue["pr_number"]:
                    ancestor = commit
                elif member_order[producer["pr_number"]] > member_order[issue["pr_number"]]:
                    ancestor = member["merge_commit_sha"]
                else:
                    raise SupervisorError("evidence supersession precedes its affected fix")
                if read(["git", "-C", root, "merge-base", "--is-ancestor", ancestor, successor], check=False).returncode:
                    raise SupervisorError("evidence producer does not descend from its affected fix")
                continue
            retained = produced
            if path in superseded:
                successor = superseded[path]
                successor_sha = successor["commit_sha"]
                if ((successor["pr_number"], successor_sha) not in attributed_fixes
                        or successor["pr_number"] != issue["pr_number"] or successor_sha == commit
                        or read(["git", "-C", root, "merge-base", "--is-ancestor", commit, successor_sha], check=False).returncode):
                    raise SupervisorError("fix successor must be another descendant attributed fix in the same PR")
                if successor_sha not in changed:
                    changed[successor_sha] = commit_changes(root, successor_sha, read)
                successor_change = changed[successor_sha].get(path)
                if (old == produced or not successor_change or successor_change[0] == successor_change[1]
                        or successor_change[1] == produced):
                    raise SupervisorError("fix supersession is unchanged, unrelated or unnecessary")
                retained = successor_change[1]
            if tree_entry(root, member["head_sha"], path, read) != retained:
                raise SupervisorError("member reviewed head does not retain the attributed fix producer entry")
            if tree_entry(root, final, path, read) != retained:
                raise SupervisorError("final integration head no longer retains an earlier reviewed fix entry")
    # Preserve squash-source publication across all verified members after
    # every membership, time-window, evidence and fix-retention gate has passed.
    publication = verify_receipt_publication(receipt, target,
        set().union(*commits_by_pr.values()), read)
    return {**proofs[-1], "prs": proofs, "evidence_attributions": copy.deepcopy(receipt["evidence_attributions"]),
            "commit_publication": publication}


SEND_JS = r'''
function run(argv) {
    const TAIL_CHARS = 64000;
    function currentTail(tab) {
        let raw = '';
        try {
            if (typeof tab.history === 'function') raw = String(tab.history() || '');
        } catch (error) { raw = ''; }
        if (!raw) raw = String(tab.contents() || '');
        return raw.length > TAIL_CHARS ? raw.slice(-TAIL_CHARS) : raw;
    }
    const expected = JSON.parse(argv[0]);
    if (!Number.isInteger(expected.pid) || expected.pid <= 0) return 'invalid-pid';
    const terminal = Application('Terminal');
    const system = Application.currentApplication(); system.includeStandardAdditions = true;
    for (const win of terminal.windows()) {
        let wid; try { wid = win.id(); } catch (error) { continue; }
        if (wid !== expected.window) continue;
        let tab;
        try {
            const tabs = win.tabs(); if (tabs.length < expected.tab) return 'tab-changed';
            tab = tabs[expected.tab - 1]; if (tab.tty() !== expected.tty) return 'tty-changed';
        } catch (error) { return 'target-unavailable'; }
        let identity, cwd, groups;
        try {
            identity = system.doShellScript('/bin/ps -p ' + expected.pid + ' -o pid=,tty=,lstart=,comm=').trim();
            cwd = system.doShellScript('/usr/sbin/lsof -a -p ' + expected.pid + ' -d cwd -Fn').split(/\r?\n|\r/).filter(x => x.startsWith('n')).map(x => x.slice(1));
            groups = system.doShellScript('/bin/ps -p ' + expected.pid + ' -o pgid=,tpgid=').trim().split(/\s+/);
        } catch (error) { return 'process-unavailable'; }
        if (identity !== expected.identity || cwd.length !== 1 || cwd[0] !== expected.cwd || groups.length !== 2 || groups[0] !== groups[1]) return 'identity-changed';
        if (expected.agy_inventory) {
            let inventory;
            try {
                inventory = system.doShellScript('/bin/ps -ax -o pid=,tty=,lstart=,comm=').split(/\r?\n|\r/)
                    .map(x => x.trim()).filter(x => /(?:^|\s)agy$/.test(x)).sort();
            } catch (error) { return 'process-inventory-unavailable'; }
            if (JSON.stringify(inventory) !== JSON.stringify(expected.agy_inventory)) return 'process-inventory-changed';
        }
        let currentScreen, expectedScreen;
        try {
            currentScreen = currentTail(tab);
            const rawExpected = String(expected.screen || '');
            expectedScreen = rawExpected.length > TAIL_CHARS ? rawExpected.slice(-TAIL_CHARS) : rawExpected;
        } catch (error) { return 'target-unavailable'; }
        if (currentScreen !== expectedScreen) return 'screen-changed';
        terminal.doScript(expected.message, {in: tab});
        return 'sent';
    }
    return 'window-closed';
}
'''

REDRAW_JS = r'''
function run(argv) {
    const TAIL_CHARS = 64000;
    function currentTail(tab) {
        let raw = '';
        try {
            if (typeof tab.history === 'function') raw = String(tab.history() || '');
        } catch (error) { raw = ''; }
        if (!raw) raw = String(tab.contents() || '');
        return raw.length > TAIL_CHARS ? raw.slice(-TAIL_CHARS) : raw;
    }
    const expected = JSON.parse(argv[0]);
    if (!Number.isInteger(expected.pid) || expected.pid <= 0) return JSON.stringify({status: 'invalid-pid'});
    const terminal = Application('Terminal');
    const system = Application.currentApplication(); system.includeStandardAdditions = true;
    for (const win of terminal.windows()) {
        let wid; try { wid = win.id(); } catch (error) { continue; }
        if (wid !== expected.window) continue;
        let tab;
        try {
            const tabs = win.tabs(); if (tabs.length < expected.tab) return JSON.stringify({status: 'tab-changed'});
            tab = tabs[expected.tab - 1]; if (tab.tty() !== expected.tty) return JSON.stringify({status: 'tty-changed'});
        } catch (error) { return JSON.stringify({status: 'target-unavailable'}); }
        let identity, cwd, groups;
        try {
            identity = system.doShellScript('/bin/ps -p ' + expected.pid + ' -o pid=,tty=,lstart=,comm=').trim();
            cwd = system.doShellScript('/usr/sbin/lsof -a -p ' + expected.pid + ' -d cwd -Fn').split(/\r?\n|\r/).filter(x => x.startsWith('n')).map(x => x.slice(1));
            groups = system.doShellScript('/bin/ps -p ' + expected.pid + ' -o pgid=,tpgid=').trim().split(/\s+/);
        } catch (error) { return JSON.stringify({status: 'process-unavailable'}); }
        if (identity !== expected.identity || cwd.length !== 1 || cwd[0] !== expected.cwd || groups.length !== 2 || groups[0] !== groups[1]) return JSON.stringify({status: 'identity-changed'});
        let currentScreen, expectedScreen, rows;
        try {
            currentScreen = currentTail(tab);
            const rawExpected = String(expected.screen || '');
            expectedScreen = rawExpected.length > TAIL_CHARS ? rawExpected.slice(-TAIL_CHARS) : rawExpected;
            rows = tab.numberOfRows();
        } catch (error) { return JSON.stringify({status: 'target-unavailable'}); }
        if (currentScreen !== expectedScreen) return JSON.stringify({status: 'screen-changed'});
        if (!Number.isInteger(rows) || rows < 5 || rows > 300) return JSON.stringify({status: 'invalid-rows'});
        try {
            tab.numberOfRows = rows + 1;
            delay(0.3);
        } finally {
            try { tab.numberOfRows = rows; } catch (error) {}
        }
        delay(0.3);
        let restoredRows, refreshedScreen;
        try {
            restoredRows = tab.numberOfRows();
            refreshedScreen = currentTail(tab);
        } catch (error) { return JSON.stringify({status: 'target-unavailable'}); }
        return JSON.stringify({status: 'redrawn', rows: rows, restoredRows: restoredRows, screen: refreshedScreen});
    }
    return JSON.stringify({status: 'window-closed'});
}
'''


class Supervisor:
    def __init__(self, config: dict, *, native=None, notifier=None, runner=command, stop_requested=None,
                 freshness_runner=None):
        self.config = config
        self.runtime = Path(config["runtime_dir"])
        self.native = native or import_file(Path(config["native_reader_path"]), "supervisor_native")
        self.notifier = notifier or import_file(Path(config["notifier_path"]), "supervisor_terminal")
        self.runner = runner
        self.stop_requested = stop_requested or (lambda: False)
        self.freshness_runner = freshness_runner
        self.native_cache: dict[str, tuple[tuple, dict]] = {}
        self._port_pressure_helpers = {
            "read_json": read_json, "atomic_json": atomic_json, "file_lock": file_lock,
            "send_js": SEND_JS, "busy": terminal_busy_reason,
        }

    def port_pressure(self, *, apply: bool = False, report_only: bool = False, boundary: dict | None = None,
                      excluded_repository_keys: tuple[str, ...] = ()) -> dict:
        from kg_microbe_workflows.port_pressure import normalize_config

        # The one-setting off switch is reread each tick, not just at startup.
        if self.config.get("_config_path"):
            source = read_json(Path(self.config["_config_path"]))
            self.config["port_pressure"] = source.get("port_pressure", {"mode": "off"})
        if report_only:
            self.config["port_pressure"] = {**self.config.get("port_pressure", {}), "mode": "report"}
        raw = self.config.get("port_pressure", {"mode": "off"})
        normalized = normalize_config({key: value for key, value in raw.items() if key not in {"binding_files", "controller_config_path"}})
        allowed = normalized["restart_repository_keys"]
        if allowed is not None and not set(allowed) <= {target["repository_key"] for target in self.config["targets"]}:
            raise SupervisorError("restart_repository_keys contains an unconfigured target")
        self.config["port_pressure"] = {**raw, **normalized}
        if normalized["mode"] == "off":
            return {"phase": "off", "candidate": None}
        adapter = import_file(ROOT / "scripts/mech_session_port_pressure.py", "supervisor_port_pressure")
        kwargs = {"apply": apply and not report_only}
        if boundary is not None:
            kwargs["boundary"] = boundary
        if excluded_repository_keys:
            kwargs["excluded_repository_keys"] = excluded_repository_keys
        return adapter.PortPressureGuard(self).tick(**kwargs)

    def stopping(self) -> bool:
        return self.stop_requested() or (self.runtime / "STOP").exists()

    def directory(self, target: dict) -> Path:
        directory = self.runtime / target["repository_key"]
        if self.runtime.resolve() != self.runtime or directory.resolve().parent != self.runtime:
            raise SupervisorError("runtime path or repository directory is a symlink/escape")
        return directory

    def save(self, target: dict, ledger: dict) -> None:
        self.write(self.directory(target) / "ledger.json", ledger)

    def write(self, path: Path, value: Any) -> None:
        atomic_json(path, value, boundary=self.runtime)

    def durability(self, target: dict) -> dict:
        """Observe known owned state only; a failed observation never means safe."""
        from kg_microbe_workflows.session_durability import observe_mech
        try:
            roots = durability_repository_roots(target)
            paths = target.get("session_state_paths")
            return observe_mech(roots, session_state_paths=None if paths is None else [Path(p) for p in paths])
        except Exception:
            # Do not retain arbitrary remote errors, credential-bearing URLs or
            # native session data in an operational alert.
            return {"schema_version": "1.0.0", "observed_at": now(), "status": "unknown",
                    "alert": True, "complete": False, "repository_count": 0,
                    "unpushed_commits": None, "at_risk_files": None, "overdue_files": None,
                    "errors": ["repository_identity_or_observation_unavailable"]}

    def freshness_adoption(self, target: dict, ledger: dict, *, predecessor: str | None = None,
                           activate: bool = False) -> dict | None:
        """Validate independent adoption without changing the frozen workflow."""
        from kg_microbe_workflows.freshness_contract import load_adoption
        configured = target.get("freshness_adoption")
        snapshot = ledger.get("repository_freshness")
        if snapshot is None and not activate:
            return None
        if not configured:
            raise FreshnessHold("adopted freshness contract is missing its immutable operator record")
        if snapshot is not None:
            if (not isinstance(snapshot, dict) or snapshot.get("adoption_sha256") != configured["sha256"]
                    or not isinstance(snapshot.get("adoption"), dict)):
                raise FreshnessHold("freshness adoption identity changed")
            old = snapshot["adoption"]
            boundary = old.get("boundary", {})
            context = {"workflow_sha256": boundary.get("workflow_sha256"),
                       "run_id": boundary.get("run_id"), "cycle": boundary.get("cycle"),
                       "predecessor_receipt_sha256": boundary.get("predecessor_receipt_sha256")}
        else:
            if ledger["stage"] != 1:
                raise FreshnessHold("freshness adoption is only permitted at a reviewed stage-1 boundary")
            context = {"workflow_sha256": ledger.get("workflow", {}).get("sha256"),
                       "run_id": ledger["run_id"], "cycle": ledger.get("cycle", 1),
                       "predecessor_receipt_sha256": predecessor}
        try:
            record = load_adoption(Path(configured["path"]), expected_sha256=configured["sha256"],
                                   repository_key=target["repository_key"], repository_root=Path(target["root"]),
                                   **context)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise FreshnessHold("freshness adoption refused: " + str(error)) from error
        if snapshot is not None and record != snapshot["adoption"]:
            raise FreshnessHold("freshness adoption snapshot differs from its immutable record")
        if snapshot is None:
            snapshot = {"schema_version": "1.0.0", "adoption_sha256": configured["sha256"],
                        "adoption": record, "policy_sha256": record["contract_sha256"]}
            ledger["repository_freshness"] = snapshot
        if snapshot.get("policy_sha256") != record["contract_sha256"]:
            raise FreshnessHold("freshness policy digest changed")
        return snapshot

    def freshness_boundary_id(self, ledger: dict, phase: str) -> str:
        return digest([ledger["run_id"], ledger["repository_key"], ledger.get("cycle", 1),
                       ledger["stage"], ledger.get("workflow", {}).get("sha256"),
                       ledger["repository_freshness"]["adoption_sha256"], phase])

    def ensure_boundary_freshness(self, target: dict, ledger: dict, *, phase: str,
                                  apply: bool, merge_commits: tuple[str, ...] = ()) -> dict:
        from kg_microbe_workflows.freshness import ensure_freshness
        from plugins.lock_manager import LockManager
        from plugins.repository_settings import RepositoryTarget
        snapshot = self.freshness_adoption(target, ledger)
        if snapshot is None:
            return {"status": "not_adopted"}
        if not apply:
            raise FreshnessHold("freshness boundary needs an authorized apply pass; observation never fetches")
        expected_goal = copy.deepcopy(ledger.get("adopted_goal"))
        if not expected_goal:
            raise FreshnessHold("freshness requires an assessed native predecessor identity")

        def owner_check():
            observed = self.observe(target, fresh=True, allow_redraw=False)
            if (self.stopping() or not observed.get("ready") or observed.get("error")
                    or observed.get("goal_identity") != expected_goal
                    or observed.get("goal_state") != "completed"):
                raise FreshnessHold("native goal is not the verified completed idle boundary")
            return {target["pid"]: " ".join(target["process_identity"].split())}

        frozen_paths = {}
        root = Path(target["root"]).resolve()
        for source in ledger.get("workflow", {}).get("effective", {}).get("sources", []):
            path = Path(source["path"])
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue  # Packaged/runtime snapshots are outside this Git tree.
            if relative in frozen_paths and frozen_paths[relative] != source["sha256"]:
                raise FreshnessHold("conflicting frozen workflow input identities")
            frozen_paths[relative] = source["sha256"]
        operation = self.freshness_runner or ensure_freshness
        try:
            input_lock = Path(self.config["input_lock_dir"]) / (Path(target["tty"]).name + ".lock")
            with file_lock(input_lock):
                report = operation(RepositoryTarget(target["repository_key"], Path(target["root"]),
                                                    target["github_repository"]), phase=phase,
                                   boundary_id=self.freshness_boundary_id(ledger, phase),
                                   policy_sha256=snapshot["policy_sha256"],
                                   locks=LockManager(),
                                   owner_check=owner_check, protected_roots=(ROOT,), merge_commits=merge_commits,
                                   frozen_paths=frozen_paths,
                                   receipt_dir=self.directory(target) / "freshness", apply=True)
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            raise FreshnessHold("repository freshness held: " + str(error)) from error
        if (not isinstance(report, dict) or report.get("status") != "verified"
                or report.get("boundary_id") != self.freshness_boundary_id(ledger, phase)
                or report.get("policy_sha256") != snapshot["policy_sha256"]
                or report.get("phase") != phase or not SHA.fullmatch(report.get("after", ""))
                or report.get("after") != report.get("fetched")):
            reason = report.get("reason", "invalid freshness proof") if isinstance(report, dict) else "invalid freshness proof"
            raise FreshnessHold("repository freshness held: " + str(reason))
        snapshot[phase] = copy.deepcopy(report)
        return report

    def verify_goal_freshness_record(self, target: dict, ledger: dict) -> dict | None:
        from kg_microbe_workflows.freshness import verify_saved_receipt
        snapshot = self.freshness_adoption(target, ledger)
        if snapshot is None:
            return None
        report = snapshot.get("pre_goal") or {}
        if (report.get("status") != "verified" or report.get("phase") != "pre_goal"
                or report.get("boundary_id") != self.freshness_boundary_id(ledger, "pre_goal")
                or report.get("policy_sha256") != snapshot["policy_sha256"]):
            raise FreshnessHold("goal lacks its exact successful pre-inventory freshness proof")
        try:
            verify_saved_receipt(report)
        except (OSError, ValueError, TypeError) as error:
            raise FreshnessHold("pre-goal immutable freshness receipt rejected: " + str(error)) from error
        return report

    def verify_pre_goal_freshness(self, target: dict, ledger: dict, *, check_remote: bool = False) -> None:
        from kg_microbe_workflows.freshness import verify_inventory_head
        from plugins.repository_settings import RepositoryTarget
        report = self.verify_goal_freshness_record(target, ledger)
        if report is None:
            return
        # The packaged verifier always re-observes the default ref. A remote
        # change after freeze is a hold, never permission to overwrite its scope.
        try:
            verify_inventory_head(RepositoryTarget(target["repository_key"], Path(target["root"]),
                                                    target["github_repository"]), report,
                                  boundary_id=self.freshness_boundary_id(ledger, "pre_goal"),
                                  policy_sha256=ledger["repository_freshness"]["policy_sha256"])
        except (OSError, ValueError, TypeError) as error:
            raise FreshnessHold("pre-goal inventory freshness held: " + str(error)) from error

    def initialize_freshness(self, target: dict, ledger: dict, observation: dict, *, apply: bool) -> dict:
        if not ledger.get("freshness_initial_pending"):
            return ledger
        if (ledger.get("stage") != 1 or ledger.get("adopted_goal") or ledger.get("actions")
                or ledger.get("completed_stages") or any(key in ledger for key in ("infra_scope", "issue_scope", "baseline_head"))
                or not observation.get("ready") or observation.get("goal_state") != "completed"
                or observation.get("goal_identity") != target["initial_goal_identity"]):
            raise FreshnessHold("initial freshness adoption requires a pristine assessed completed native boundary")
        candidate = copy.deepcopy(ledger)
        self.freshness_adoption(target, candidate, activate=True)
        candidate.update(adopted_goal=copy.deepcopy(target["initial_goal_identity"]), awaiting_goal=True)
        self.ensure_boundary_freshness(target, candidate, phase="pre_goal", apply=apply)
        self.verify_pre_goal_freshness(target, candidate)
        candidate.pop("freshness_initial_pending")
        self.freeze_stage_scope(target, candidate)
        self.baseline(target, candidate)
        return candidate

    def freeze_stage_scope(self, target: dict, ledger: dict) -> None:
        """Called only after the opted-in pre-goal gate, before native dispatch."""
        if workflow_stage_key(ledger) == "infrastructure":
            path = self.directory(target) / "cycles" / f"cycle-{ledger['cycle']:06d}" / "infra-scope.json"
            if ledger.get("repository_freshness") and path.exists():
                raise FreshnessHold("fresh stage already has an archived infrastructure scope; approved reconciliation required")
            fetched_head = None
            if ledger.get("repository_freshness"):
                fetched_head = ledger["repository_freshness"].get("pre_goal", {}).get("after")
                if fetched_head is None:
                    raise FreshnessHold("infrastructure scope lacks a verified fetched revision")
            ledger["infra_scope"] = freeze_infrastructure(target, fetched_head=fetched_head)
            self.write(path, ledger["infra_scope"])
        else:
            ledger.pop("infra_scope", None)
        if workflow_stage_key(ledger) == "open_issue_triage":
            path = self.directory(target) / "cycles" / f"cycle-{ledger['cycle']:06d}" / "issue-scope.json"
            if ledger.get("repository_freshness") and path.exists():
                raise FreshnessHold("fresh stage already has an archived inventory; approved reconciliation required")
            ledger["issue_scope"] = read_json(path) if path.exists() else freeze_open_issues(target, runner=self.runner)
            validate_frozen_issue_scope(ledger["issue_scope"], target)
            self.write(path, ledger["issue_scope"])
        else:
            ledger.pop("issue_scope", None)

    def freshness_merged_commits(self, target: dict, receipt: dict) -> tuple[str, ...]:
        """Verify actual merge identity before any synchronization; full gates follow."""
        from kg_microbe_workflows.closure import multi_pr_members
        members = multi_pr_members(receipt) if "prs" in receipt else [receipt["pr"]]
        merged = []
        for member in members:
            live = json.loads(self.runner(["gh", "api", f"repos/{target['github_repository']}/pulls/{member['number']}"]).stdout)
            if (live.get("merged") is not True or not live.get("merged_at")
                    or live.get("base", {}).get("ref") != member["base"]
                    or live.get("base", {}).get("repo", {}).get("full_name", "").casefold() != target["github_repository"].casefold()
                    or live.get("head", {}).get("ref") != member["branch"]
                    or live.get("head", {}).get("sha") != member["head_sha"]
                    or (live.get("head", {}).get("repo") or {}).get("full_name", "").casefold() != target["github_repository"].casefold()
                    or not isinstance(live.get("merge_commit_sha"), str)
                    or not SHA.fullmatch(live["merge_commit_sha"])):
                raise FreshnessHold("post-merge freshness requires the actually merged exact repository/base/head")
            merged.append(live["merge_commit_sha"])
        return tuple(merged)

    def redraw_tab(self, target: dict, tab: dict, *, lock_held: bool = False) -> dict:
        payload = {**tab, "pid": target["pid"], "identity": target["process_identity"], "cwd": target["root"]}
        lock = Path(self.config["input_lock_dir"]) / (Path(target["tty"]).name + ".lock")
        try:
            if lock_held:
                raw = self.notifier.jxa(REDRAW_JS, payload)
            else:
                with file_lock(lock):
                    raw = self.notifier.jxa(REDRAW_JS, payload)
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(parsed, dict):
                return {"status": "invalid-response"}
            return {"status": str(parsed.get("status", "unknown")),
                    "rows": parsed.get("rows"),
                    "restored_rows": parsed.get("restoredRows"),
                    "screen": parsed.get("screen")}
        except BlockingIOError:
            return {"status": "lock-busy"}
        except Exception as error:
            return {"status": "redraw-error", "error": str(error)[:300]}

    def observe(self, target: dict, *, fresh: bool = False, allow_redraw: bool = False, lock_held: bool = False) -> dict:
        observation = {"observed_at": now(), "ready": False}
        try:
            live = self.notifier.live_process(target["pid"])
            if not live or live["identity"] != target["process_identity"] or live["tty"] != target["tty"]:
                raise SupervisorError("process/start/TTY identity changed")
            peers = self.runner(["/bin/ps", "-t", Path(target["tty"]).name, "-o", "pid=,comm="]).stdout
            agy_pids = [int(parts[0]) for line in peers.splitlines()
                        if len(parts := line.strip().split(None, 1)) == 2 and parts[1] == "agy"]
            if agy_pids != [target["pid"]]:
                raise SupervisorError("multiple or missing agy processes on TTY")
            cwd = self.notifier.process_cwd(target["pid"])
            if cwd != Path(target["root"]).resolve():
                raise SupervisorError("process working directory changed")
            if not self.notifier.foreground(target["pid"], target["tty"]):
                raise SupervisorError("agy is not foreground process group")
            origin = self.runner(["git", "-C", target["root"], "remote", "get-url", "origin"]).stdout
            if normalize_github(origin) != target["github_repository"].casefold():
                raise SupervisorError("repository origin changed")
            cache_path = Path(self.config.get("conversation_cache_path", Path.home() / ".gemini/antigravity-cli/cache/last_conversations.json"))
            conversations = read_json(cache_path)
            if conversations.get(str(cwd)) != target["native_session_id"]:
                raise SupervisorError("current native conversation differs from configured session")
            cached = self.native_cache.get(target["repository_key"])
            database = Path(self.config.get("conversation_dir", Path.home() / ".gemini/antigravity-cli/conversations")) / f"{target['native_session_id']}.db"
            signature = tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns)
                              for path in [database, Path(str(database) + "-wal"), Path(str(database) + "-shm")]
                              if path.exists())
            if fresh or not cached or cached[0] != signature:
                native = self.native.inspect(target["root"], target["native_session_id"])
                self.native_cache[target["repository_key"]] = (signature, native)
            else:
                native = cached[1]
            if native.get("error"):
                raise SupervisorError(native["error"])
            observation.update(native=native, goal_identity=goal_identity(native),
                               goal_state=(native.get("current_goal") or {}).get("state", "unknown"))
            snapshot = json.loads(self.notifier.jxa(self.notifier.SNAPSHOT_JS, [target["tty"]]))
            tabs = [tab for tab in snapshot["tabs"] if tab["tty"] == target["tty"]]
            if len(tabs) != 1:
                raise SupervisorError("Terminal tab unavailable or ambiguous")
            tab = tabs[0]
            observation["tab"] = tab
            reason = self.notifier.composer_reason(tab["screen"])
            execution = native.get("native_execution_state", "unknown")
            busy = terminal_busy_reason(tab["screen"])
            if (allow_redraw and not self.stopping()
                    and execution in {"idle_candidate", "interrupted"}
                    and busy is None
                    and confirmed_display_corruption(tab["screen"], reason)):
                redrawn = self.redraw_tab(target, tab, lock_held=lock_held)
                observation["redraw"] = {k: v for k, v in redrawn.items() if k != "screen"}
                if (redrawn.get("status") == "redrawn"
                        and redrawn.get("restored_rows") == redrawn.get("rows")
                        and isinstance(redrawn.get("screen"), str)):
                    tab = {**tab, "screen": redrawn["screen"]}
                    observation["tab"] = tab
                    reason = self.notifier.composer_reason(tab["screen"])
                    busy = terminal_busy_reason(tab["screen"])
            if not reason and execution not in {"idle_candidate", "interrupted"}:
                reason = "native execution is " + execution
            if not reason and busy:
                reason = busy
            observation.update(ready=reason is None, readiness_reason=reason)
        except Exception as error:
            observation["error"] = str(error)[:700]
        return observation

    def reconcile(self, target: dict, ledger: dict, observation: dict) -> None:
        """Receipt reconciliation never infers completion from message delivery."""
        native_id = observation.get("goal_identity")
        if not ledger["adopted_goal"] and native_id:
            if native_id != target["initial_goal_identity"]:
                observation.update(error="native goal differs from the assessed initial goal; reassessment required", ready=False)
                return
            ledger["adopted_goal"] = native_id
        pending = [a for a in ledger["actions"].values() if scoped(a, ledger) and a["state"] in BLOCKING_RECEIPTS]
        for action in pending:
            adopting = ledger.get("awaiting_goal") and action.get("kind") == "start_goal"
            if action["state"] == "accepted" and not adopting:
                continue  # historical acceptance timestamps are immutable
            proof = native_delivery_proof(action, target, observation)
            if proof is None:
                continue
            if adopting and ledger.get("historical_goal_boundary") is not None:
                from kg_microbe_workflows.reconciliation import (
                    ReconciliationError,
                    boundary_goal,
                    timestamp,
                )
                try:
                    previous = boundary_goal(ledger)
                    if (not native_id or native_id["conversation_id"] != previous["conversation_id"]
                            or native_id["start_step_index"] <= previous["start_step_index"]
                            or timestamp(native_id["started_at"]) <= timestamp(previous["started_at"])):
                        continue
                except (ReconciliationError, KeyError, TypeError, ValueError):
                    continue
            if action["state"] != "accepted":
                action.update(state="accepted", accepted_at=now(), acceptance="native_exact_user_input")
            action.update(delivery_proof=proof, delivery_verified_at=now())
            if action["kind"] == "policy_update":
                ledger["policy_notification_required"] = False
            if adopting and native_id and native_id != ledger["adopted_goal"]:
                action["accepted_goal_identity"] = native_id
                ledger.update(adopted_goal=native_id, awaiting_goal=False)
                ledger.pop("historical_goal_boundary", None)

    def baseline(self, target: dict, ledger: dict) -> None:
        if ledger.get("freshness_initial_pending"):
            return
        if "baseline_head" not in ledger:
            self.verify_pre_goal_freshness(target, ledger)
            ledger["baseline_head"] = self.runner(["git", "-C", target["root"], "rev-parse", "HEAD"]).stdout.strip()
            ledger["baseline_status"] = self.runner(["git", "-C", target["root"], "status", "--porcelain=v1", "--untracked-files=all"]).stdout

    def skill_errors(self, target: dict, stage: int, ledger: dict | None = None) -> list[str]:
        if stage == 0:
            return []
        errors = []
        profile = stage_profile(target, stage, ledger)
        if profile.get("applicability") not in {None, "available", "available_via_composed_workflow",
                                               "available_with_instruction_conflict", "applicability_audit", "enabled", "not_applicable"}:
            errors.append("skill applicability unresolved: " + str(profile.get("applicability")))
        for path in profile["skill_paths"]:
            skill = Path(path)
            if not skill.is_absolute():
                skill = Path(target["root"]) / skill
            if not skill.resolve().is_relative_to((Path(target["root"]) / ".claude/skills").resolve()) or not skill.is_file():
                errors.append(f"required canonical skill missing: {path}")
        return errors

    def progress(self, target: dict, ledger: dict) -> dict | None:
        """Informational agent phase; this can never authorize a transition."""
        directory = self.directory(target)
        path = directory / "progress.json"
        if not path.exists():
            return None
        try:
            if path.is_symlink() or path.resolve().parent != directory or path.stat().st_size > 65536:
                raise SupervisorError("invalid progress file path/size")
            reported = read_json(path)
            for key in (("run_id", "repository_key", "stage", "cycle") if ledger.get("schema_version") == 2 else ("run_id", "repository_key", "stage")):
                if reported.get(key) != ledger[key]:
                    raise SupervisorError("progress identity mismatch")
            if reported.get("goal_identity") != ledger["adopted_goal"]:
                raise SupervisorError("progress goal identity mismatch")
            current = False
            try:
                stamp = datetime.fromisoformat(reported.get("updated_at", "").replace("Z", "+00:00"))
                last_dispatch = max((action.get("reserved_epoch_ms", 0) / 1000 for action in ledger["actions"].values()
                                     if scoped(action, ledger)), default=0)
                current = stamp.tzinfo is not None and last_dispatch <= stamp.timestamp() <= time.time() + 60 and time.time() - stamp.timestamp() < 86400
            except (TypeError, ValueError):
                pass
            return {"authority": "informational_only", "stage": reported["stage"], "cycle": reported.get("cycle", 1), "current": current,
                    **{key: str(reported[key])[:500]
                    for key in ("phase", "summary", "updated_at", "pr_url") if key in reported}}
        except Exception as error:
            return {"authority": "ignored", "error": str(error)[:300]}

    def goal_boundary(self, target: dict, ledger: dict, decision: dict) -> dict | None:
        """Bind maintenance to the retained verified closure, never a stage number."""
        if decision.get("action") != "start_goal" or not ledger.get("awaiting_goal"):
            return None
        records = ledger.get("completed_stages", [])
        if not records:
            return None  # Initial adoption is not a completed-goal boundary.
        closed = records[-1]
        if (closed.get("goal_identity") != ledger.get("adopted_goal")
                or closed.get("verification", {}).get("status") not in {"merged", "no_changes"}
                or closed.get("completion_authority") not in {"native_completed", "verified_receipt_override"}
                or not re.fullmatch(r"[0-9a-f]{64}", closed.get("receipt_sha256", ""))):
            raise SupervisorError("goal-boundary recycling requires the retained verified completion")
        stage = stage_profile(target, ledger["stage"], ledger)
        key = stage.get("key") if stage else None
        if not key:
            raise SupervisorError("goal-boundary recycling requires a canonical stage key")
        return {"repository_key": target["repository_key"], "pid": target["pid"],
                "action_id": decision["action_id"], "next_stage_key": key,
                "receipt_sha256": closed["receipt_sha256"],
                "completion_authority": closed["completion_authority"],
                "goal_identity": copy.deepcopy(closed["goal_identity"])}

    def boundary_maintenance(self, target: dict, ledger: dict, decision: dict) -> dict | None:
        if self.config.get("port_pressure", {"mode": "off"}).get("mode") == "off":
            return None
        allowed = self.config["port_pressure"].get("restart_repository_keys")
        if allowed is not None and target["repository_key"] not in allowed:
            return None  # Canary scope does not hold other sessions' normal goals.
        boundary = self.goal_boundary(target, ledger, decision)
        if boundary is None:
            return None
        self._port_pressure_boundary_seen = True
        fresh = self.observe(target, fresh=True, allow_redraw=False)
        fresh["agent_progress"] = self.progress(target, ledger)
        reason = None
        if decide(ledger, fresh).get("action_id") != decision.get("action_id"):
            reason = "goal prerequisite changed before boundary maintenance"
        else:
            errors = self.skill_errors(target, ledger["stage"], ledger)
            if (boundary["next_stage_key"] == "resolve_review_findings"
                    and not previous_evidence(ledger, ledger["stage"])):
                errors.append("next goal requires the verified review manifest")
            try:
                self.check_workflow(target, ledger)
            except Exception as error:
                errors.append(str(error))
            reason = "; ".join(errors) if errors else None
        if reason:
            report = {"phase": "blocked", "reason": reason}
            marker = {**boundary, **report, "updated_at": now()}
            ledger["port_pressure_boundary"] = marker
            self.save(target, ledger)
            self._port_pressure_boundary_report = marker
            return marker
        prior = ledger.get("port_pressure_boundary", {})
        if (prior.get("action_id") == boundary["action_id"]
                and prior.get("receipt_sha256") == boundary["receipt_sha256"]
                and prior.get("phase") == "restarted"
                and prior.get("new_pid") == target["pid"]
                and prior.get("process_identity") == target["process_identity"]):
            self._port_pressure_boundary_report = prior
            return prior  # A failed goal send must not spend another restart.
        if getattr(self, "_port_pressure_recycled", False):
            report = {"phase": "limited", "limit_reason": "one recycle per supervisor tick"}
        else:
            report = self.port_pressure(apply=True, boundary=boundary)
        if report["phase"] == "restarted":
            self._port_pressure_recycled = True
        marker = {**boundary, **report, "process_identity": target["process_identity"], "updated_at": now()}
        # Durable hold/restart proof survives a failed send or supervisor tick.
        ledger["port_pressure_boundary"] = marker
        self.save(target, ledger)
        self._port_pressure_boundary_report = marker
        return marker

    def dispatch(self, target: dict, ledger: dict, decision: dict) -> dict:
        if self.stopping():
            return {"state": "not-sent", "reason": "supervisor stop requested"}
        boundary = self.boundary_maintenance(target, ledger, decision)
        if boundary and boundary["phase"] not in {"off", "healthy", "restarted"}:
            return {"state": "not-sent", "reason": "goal boundary held for port-pressure maintenance",
                    "port_pressure": boundary}
        lock = Path(self.config["input_lock_dir"]) / (Path(target["tty"]).name + ".lock")
        with file_lock(lock):
            observation = self.observe(target, fresh=True, allow_redraw=True, lock_held=True)
            if self.stopping():
                return {"state": "not-sent", "reason": "supervisor stop requested"}
            observation["agent_progress"] = self.progress(target, ledger)
            if decision.get("action") == "repair_closure":
                receipt_path = self.directory(target) / "completion.json"
                if receipt_path.is_symlink():
                    return {"state": "not-sent", "reason": "completion receipt is a symlink"}
                current_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest() if receipt_path.is_file() else None
                if current_hash != decision.get("receipt_hash"):
                    return {"state": "not-sent", "reason": "receipt changed before repair instruction"}
                current = repair_decision(ledger, observation, decision["repair_reason"], current_hash)
            else:
                current = decide(ledger, observation)
            if current.get("action_id") != decision.get("action_id"):
                return {"state": "not-sent", "reason": "prerequisite changed before send"}
            errors = self.skill_errors(target, ledger["stage"], ledger)
            if workflow_stage_key(ledger) == "resolve_review_findings" and not previous_evidence(ledger, ledger["stage"]):
                errors.append("resolve_review_findings requires the verified record-review manifest")
            if errors:
                return {"state": "not-sent", "reason": "; ".join(errors)}
            if ledger.get("schema_version") == 2:
                self.check_workflow(target, ledger)
            if decision["action"] == "start_goal":
                self.verify_pre_goal_freshness(target, ledger, check_remote=True)
            prompt = (self.directory(target) / "effective-workflow.json" if ledger.get("workflow")
                      else Path(target["workflow_prompt_path"]))
            if not prompt.is_file():
                return {"state": "not-sent", "reason": "workflow instruction file missing"}
            identifier = decision["action_id"]
            from kg_microbe_workflows.instructions import (
                InstructionError,
                prepare_instruction,
                verify_instruction,
            )

            instruction = message_for(target, ledger, decision, self.directory(target))
            instruction_hash = hashlib.sha256(prompt.read_bytes()).hexdigest()
            context = {"action_id": identifier, "kind": decision["action"],
                       "run_id": ledger["run_id"], "repository_key": target["repository_key"],
                       "cycle": ledger.get("cycle", 1), "stage": ledger["stage"],
                       "stage_key": workflow_stage_key(ledger),
                       "native_session_id": target["native_session_id"],
                       "reservation_goal_identity": copy.deepcopy(ledger["adopted_goal"]),
                       "instruction_sha256": instruction_hash,
                       "workflow_sha256": ledger.get("workflow", {}).get("sha256")}
            try:
                delivery = prepare_instruction(self.directory(target), context, instruction)
            except (InstructionError, OSError) as error:
                # Definite preparation failure precedes reservation and input.
                return {"state": "not-sent", "reason": "instruction preparation refused: " + str(error)}
            action = {"id": identifier, "kind": decision["action"], "stage": ledger["stage"], "cycle": ledger.get("cycle", 1),
                      "marker": "MECH-WORKFLOW-" + identifier, "state": "reserved", "reserved_at": now(),
                      "reserved_epoch_ms": int(time.time() * 1000), "native_session_id": target["native_session_id"],
                      "goal_identity": ledger["adopted_goal"], **delivery,
                      "native_step_index": ((observation.get("native") or {}).get("last_step") or {}).get("index"),
                      "instruction_sha256": instruction_hash}
            ledger["actions"][identifier] = action
            self.save(target, ledger)  # durable intent before any terminal input
            try:
                if self.stopping():
                    action.update(state="not-sent", outcome="stop-requested", updated_at=now())
                else:
                    try:
                        verify_instruction(self.directory(target), action["instruction_artifact"])
                    except (InstructionError, OSError) as error:
                        action.update(state="not-sent", outcome="instruction-artifact-rejected",
                                      error=str(error), updated_at=now())
                        self.save(target, ledger)
                        return action
                    result = self.notifier.jxa(SEND_JS, {**observation["tab"], "pid": target["pid"],
                        "identity": target["process_identity"], "cwd": target["root"], "message": action["message"]})
                    # Terminal returning proves only that the transport was
                    # invoked: it may leave a partial unsent composer. Keep a
                    # blocking uncertain reservation until native exact-input
                    # reconciliation, never retry or append Enter automatically.
                    action.update(state="uncertain" if result == "sent" else "not-sent", outcome=result, updated_at=now())
            except Exception as error:
                action.update(state="uncertain", error=str(error)[:500], updated_at=now())
            self.save(target, ledger)
            return action

    def check_workflow(self, target: dict, ledger: dict) -> None:
        effective = ledger["workflow"]["effective"]
        if digest(effective) != ledger["workflow"]["sha256"]:
            raise SupervisorError("pinned workflow snapshot changed")
        queued = target.get("workflow_next_profile_path")
        candidate_replaces_active = bool(queued and Path(queued).resolve() == Path(ledger["active_profile_path"]).resolve())
        from kg_microbe_workflows import LEGACY_PARENT_PATH, LEGACY_SCHEMA_PATH
        retained = {"parent": LEGACY_PARENT_PATH, "schema": LEGACY_SCHEMA_PATH}
        for source in effective.get("sources", []):
            # A candidate may replace repository-local inputs, never the already
            # validated immutable effective contract. Core release replacement
            # can use only a retained byte-identical legacy source.
            if candidate_replaces_active and source["kind"] not in retained:
                continue
            errors = artifact_errors({"artifact": source["path"], "sha256": source["sha256"]},
                                     [Path(source["path"]).parent], "pinned workflow input")
            if errors and source["kind"] in retained:
                fallback = retained[source["kind"]]
                errors = artifact_errors({"artifact": str(fallback), "sha256": source["sha256"]},
                                         [fallback.parent], "retained pinned core input")
            if errors:
                raise SupervisorError("pinned workflow inputs changed during the active cycle: " + "; ".join(errors))
        path = self.directory(target) / "effective-workflow.json"
        snapshot = {"cycle": ledger["cycle"], "workflow_sha256": ledger["workflow"]["sha256"],
                    "effective": ledger["workflow"]["effective"]}
        if path.exists() and read_json(path) != snapshot:
            previous = read_json(path)
            if previous.get("cycle", ledger["cycle"]) >= ledger["cycle"]:
                raise SupervisorError("pinned instruction snapshot changed")
        self.write(path, snapshot)
        archive = self.directory(target) / "cycles" / f"cycle-{ledger['cycle']:06d}" / "effective-workflow.json"
        if archive.exists() and read_json(archive) != snapshot:
            raise SupervisorError("archived cycle instruction snapshot changed")
        self.write(archive, snapshot)
        if workflow_stage_key(ledger) == "open_issue_triage" and not ledger.get("freshness_initial_pending"):
            scope = ledger.get("issue_scope") or {}
            validate_frozen_issue_scope(scope, target)
            scope_path = archive.parent / "issue-scope.json"
            if scope_path.exists() and read_json(scope_path) != scope:
                raise SupervisorError("archived issue inventory changed")
            self.write(scope_path, scope)

    def advance(self, target: dict, ledger: dict, receipt: dict, verification: dict, authority: str, *, apply: bool = False) -> dict:
        closed_stage = ledger["stage"]
        advanced = copy.deepcopy(ledger)
        record = {"stage": closed_stage, "cycle": ledger.get("cycle", 1), "goal_identity": ledger["adopted_goal"],
                  "receipt_sha256": digest(receipt), "verification": verification, "completion_authority": authority}
        if ledger.get("schema_version") == 2:
            evidence = goal_output_data(receipt, ledger, target)
            record["workflow_sha256"] = ledger["workflow"]["sha256"]
            record["parent_version"] = ledger["workflow"]["effective"]["parent_version"]
            record["stage_key"] = workflow_stage_key(ledger)
            if evidence:
                record["goal_evidence"] = copy.deepcopy(receipt["goal_outputs"]["goal_evidence"])
                record["goal_evidence_snapshot"] = evidence
        if ledger.get("repository_freshness"):
            record["repository_freshness"] = copy.deepcopy(ledger["repository_freshness"])
        advanced["completed_stages"].append(record)
        record_cycle_version(advanced)
        if ledger.get("schema_version") == 2 and closed_stage == last_stage(ledger):
            effective = load_effective(self.config, target, next_cycle=True)
            current = ledger["workflow"]["effective"]
            parent_fields = ("parent_id", "parent_version", "parent_sha256", "schema_sha256", "parent_repository", "parent_revision")
            migration = None
            if any(effective[field] != current[field] for field in parent_fields):
                migration = self.verify_parent_migration(target, ledger, effective)
                advanced.setdefault("parent_migrations", []).append(migration)
            candidate = target.get("workflow_next_profile_path") or target["workflow_profile_path"]
            head = receipt.get("pr", {}).get("head_sha") if receipt["status"] == "completed" else receipt["no_changes"]["head_sha"]
            self.verify_next_profile(target, effective, candidate, head, migration=migration)
            advanced.update(cycle=ledger["cycle"] + 1, stage=1, awaiting_goal=True,
                            workflow=pin_workflow(effective), active_profile_path=candidate)
            record_cycle_version(advanced)
        else:
            advanced.update(stage=closed_stage + 1, awaiting_goal=closed_stage < last_stage(ledger))
        if (target.get("freshness_adoption") and not advanced.get("repository_freshness")
                and closed_stage == last_stage(ledger)):
            self.freshness_adoption(target, advanced, predecessor=digest(receipt), activate=True)
        if advanced.get("repository_freshness"):
            self.ensure_boundary_freshness(target, advanced, phase="pre_goal", apply=apply)
            self.verify_pre_goal_freshness(target, advanced)
        self.freeze_stage_scope(target, advanced)
        for key in ("baseline_head", "baseline_status", "legacy_receipt_stage"):
            advanced.pop(key, None)
        self.baseline(target, advanced)
        path = self.directory(target) / "receipts" / f"cycle-{ledger.get('cycle', 1):06d}" / f"stage-{closed_stage}-{digest(receipt)[:12]}.json"
        self.write(path, receipt)
        return advanced

    def verify_parent_migration(self, target: dict, ledger: dict, effective: dict) -> dict:
        """A reviewed exact-pair migration may activate only at final closure."""
        current = ledger["workflow"]["effective"]
        migration = target.get("workflow_parent_migration") or {}
        if (workflow_stage_key(ledger) != "infrastructure"
                or current["parent_version"].split(".")[0] != "1"
                or effective["parent_version"] != "2.0.0"
                or effective["parent_id"] != current["parent_id"]
                or effective["parent_repository"] != current["parent_repository"]):
            raise SupervisorError("next-cycle parent provenance changed outside the supported six-to-seven boundary migration")
        if (migration.get("from_sha256") != ledger["workflow"]["sha256"]
                or migration.get("to_sha256") != digest(effective)
                or not isinstance(migration.get("reviewed_by"), str) or not migration["reviewed_by"].strip()
                or not isinstance(migration.get("reason"), str) or not migration["reason"].strip()):
            raise SupervisorError("next-cycle parent provenance changed; an exact reviewed shared-contract migration is required")
        errors = artifact_errors(migration.get("review", {}), [Path(target["root"])], "parent migration review")
        if errors:
            raise SupervisorError("; ".join(errors))
        return {**copy.deepcopy(migration), "from_cycle": ledger["cycle"], "to_cycle": ledger["cycle"] + 1,
                "from_parent_version": current["parent_version"], "to_parent_version": effective["parent_version"],
                "activated_at": now()}

    def verify_next_profile(self, target: dict, effective: dict, candidate: str, head: str, *, migration=None) -> None:
        if (effective["repository_key"] != target["repository_key"]
                or effective["github_repository"].casefold() != target["github_repository"].casefold()):
            raise SupervisorError("next-cycle profile repository identity differs from its verified target")
        root = Path(target["root"]).resolve()
        inputs = [{"path": candidate, "sha256": effective["profile_sha256"]}]
        inputs += [source for source in effective.get("sources", []) if source.get("kind") == "extension"]
        if migration:
            review = migration["review"]
            review_path = Path(review["artifact"])
            inputs.append({"path": str(review_path if review_path.is_absolute() else root / review_path),
                           "sha256": review["sha256"]})
            inputs += [source for source in effective.get("sources", []) if source.get("kind") in {"parent", "schema"}
                       and Path(source["path"]).resolve().is_relative_to(root)]
        for source in inputs:
            path = Path(source["path"])
            errors = artifact_errors({"artifact": str(path), "sha256": source["sha256"]}, [root], "next-cycle profile input")
            if errors:
                raise SupervisorError("; ".join(errors))
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise SupervisorError("next-cycle repository profile/extension must live inside its repository")
            relative = str(resolved.relative_to(root))
            blob = self.runner(["git", "-C", str(root), "rev-parse", f"{head}:{relative}"]).stdout.strip()
            actual = self.runner(["git", "-C", str(root), "hash-object", "--no-filters", "--", relative]).stdout.strip()
            if not SHA.fullmatch(blob) or blob != actual:
                raise SupervisorError("next-cycle profile/extension is not committed at the verified closure head")

    def sweep(self, *, apply: bool = False) -> dict:
        self._port_pressure_recycled = False
        self._port_pressure_boundary_seen = False
        self._port_pressure_boundary_report = None
        fallback_attempted = False
        # Observe pressure first, but do not let an idle-scan candidate preempt
        # a session whose verified goal boundary is established below.
        pressure = self.port_pressure(apply=False)
        initial_pressure = pressure
        if (self.config.get("port_pressure", {}).get("mode") == "restart"
                and pressure["phase"] in {"restarted", "disabled", "unknown"}):
            # A maintenance tick never sends ordinary workflow/goal text. An
            # uncertain transaction stays stopped for operator reconciliation.
            result = {"run_id": self.config["run_id"], "updated_at": now(),
                      "mode": "apply" if apply else "observe", "sessions": [],
                      "port_pressure": pressure}
            self.write(self.runtime / "dashboard.json", result)
            return result
        rows = []
        deliveries = []
        for target in self.config["targets"]:
            if self.stopping():
                break
            directory = self.directory(target)
            ledger_path = directory / "ledger.json"
            if ledger_path.is_symlink():
                raise SupervisorError("runtime ledger must not be a symlink")
            ledger = read_json(ledger_path) if ledger_path.exists() else new_ledger(self.config, target, runner=self.runner)
            if ledger.get("run_id") != self.config["run_id"] or ledger.get("repository_key") != target["repository_key"]:
                raise SupervisorError("runtime ledger belongs to another workflow")
            workflow_error = None
            try:
                if target.get("_workflow"):
                    if ledger.get("schema_version") == 1:
                        ledger = migrate_ledger(ledger, target, target["_workflow"])
                    record_cycle_version(ledger)
                    self.check_workflow(target, ledger)
                elif apply:
                    raise SupervisorError("legacy workflow is observation-only; canonical profile and reviewed migration required")
            except Exception as error:
                workflow_error = str(error)
            observation = self.observe(target, allow_redraw=bool(apply and not workflow_error))
            if workflow_error:
                observation.update(error=workflow_error, ready=False)
            if self.stopping():
                break
            freshness_error = None
            try:
                ledger = self.initialize_freshness(target, ledger, observation, apply=apply)
                self.freshness_adoption(target, ledger)
            except FreshnessHold as error:
                freshness_error = str(error)
            if not freshness_error:
                self.reconcile(target, ledger, observation)
            try:
                self.baseline(target, ledger)
            except Exception as error:
                observation.update(error=str(error)[:700], ready=False)
            observation["agent_progress"] = self.progress(target, ledger)
            receipt_path = directory / "completion.json"
            verification = None
            receipt_errors = []
            if receipt_path.exists() and ledger["stage"] <= last_stage(ledger) and not ledger.get("awaiting_goal") and not ledger.get("policy_notification_required") and not workflow_error and not freshness_error:
                try:
                    if receipt_path.is_symlink() or receipt_path.resolve().parent != directory.resolve() or not receipt_path.is_file():
                        raise SupervisorError("completion receipt is not a regular file inside this repository runtime")
                    receipt = read_json(receipt_path)
                    archived = any(record["receipt_sha256"] == digest(receipt)
                                   for record in ledger["completed_stages"])
                    receipt_errors = [] if archived else validate_receipt(receipt, ledger, target, directory)
                    if not archived and not receipt_errors and observation.get("ready"):
                        authority = completion_authority(target, ledger, observation)
                        self.verify_goal_freshness_record(target, ledger)
                        if ledger.get("repository_freshness") and receipt["status"] == "completed":
                            merges = self.freshness_merged_commits(target, receipt)
                            self.ensure_boundary_freshness(target, ledger, phase="post_merge", apply=apply, merge_commits=merges)
                        verification = verify_remote_receipt(receipt, ledger, target, self.runner, runtime=self.directory(target))
                        if ledger.get("repository_freshness"):
                            verification["repository_freshness"] = copy.deepcopy(ledger["repository_freshness"])
                        ledger = self.advance(target, ledger, receipt, verification, authority, apply=apply)
                        # Do not delete the producer's file; mismatched old receipts
                        # are ignored only while a new goal is awaiting acceptance.
                except FreshnessHold as error:
                    freshness_error = str(error)
                except Exception as error:
                    receipt_errors.append(str(error)[:700])
            decision = decide(ledger, observation)
            if freshness_error:
                decision = {"phase": "blocked", "blocker": "repository_freshness", "reason": freshness_error}
            elif receipt_errors:
                receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest() if receipt_path.is_file() and not receipt_path.is_symlink() and receipt_path.resolve().parent == directory.resolve() else None
                decision = repair_decision(ledger, observation, "; ".join(receipt_errors), receipt_hash)
            elif decision.get("action") == "repair_closure" and receipt_path.is_file():
                decision = repair_decision(ledger, observation, decision["repair_reason"], hashlib.sha256(receipt_path.read_bytes()).hexdigest())
            if decision.get("action"):
                errors = self.skill_errors(target, ledger["stage"], ledger)
                if workflow_stage_key(ledger) == "resolve_review_findings" and not previous_evidence(ledger, ledger["stage"]):
                    errors.append("resolve_review_findings requires the verified record-review manifest")
                if errors:
                    decision = {"phase": "blocked", "reason": "; ".join(errors)}
            ledger.update(phase=decision["phase"], last_observed_at=observation["observed_at"],
                          blocked_reason=decision.get("reason"))
            if not workflow_error:
                self.save(target, ledger)
                verified_outputs = [{key: record[key] for key in ("cycle", "stage", "parent_version", "stage_key", "goal_evidence", "receipt_sha256", "verification") if key in record}
                                    for record in ledger["completed_stages"] if record.get("goal_evidence")]
                if verified_outputs:
                    self.write(directory / "verified-evidence-index.json", {"authority": "verified_closure", "entries": verified_outputs})
            public_observation = {k: v for k, v in observation.items() if k not in {"tab", "native"}}
            native = observation.get("native") or {}
            status = {"run_id": ledger["run_id"], "repository_key": target["repository_key"],
                      "stage": ledger["stage"], "cycle": ledger.get("cycle", 1), "workflow_sha256": ledger.get("workflow", {}).get("sha256"),
                      "parent_version": ledger.get("parent_version"), "stage_key": workflow_stage_key(ledger),
                      "goal_identity": ledger["adopted_goal"],
                      "phase": decision["phase"], "decision": decision, "observation": public_observation,
                      "native_execution_state": native.get("native_execution_state"),
                      "current_goal": native.get("current_goal"), "last_step": native.get("last_step"),
                      "verified_evidence_index_path": str(directory / "verified-evidence-index.json"),
                      "completion_receipt_path": str(receipt_path), "verification": verification,
                      "receipt_template": receipt_template(ledger, target),
                      "effective_workflow_path": str(directory / "effective-workflow.json"),
                      "goal_evidence_schema_path": next((source["path"] for source in ledger.get("workflow", {}).get("effective", {}).get("sources", []) if source["kind"] == "schema"), None),
                      "agent_progress": self.progress(target, ledger),
                      "repository_freshness": (copy.deepcopy(ledger["repository_freshness"])
                          if ledger.get("repository_freshness") else {"status": "not_adopted",
                              "proposal_configured": bool(target.get("freshness_adoption"))}),
                      "active_profile_path": ledger.get("active_profile_path"),
                      "next_profile_path": target.get("workflow_next_profile_path"),
                      "infra_scope": ledger.get("infra_scope"),
                      "issue_scope": ledger.get("issue_scope"), "cycle_versions": ledger.get("cycle_versions", {}),
                      "completed_stages": ledger["completed_stages"], "updated_at": now()}
            status["session_durability"] = self.durability(target)
            status["updated_at"] = now()
            self.write(directory / "status.json", status)
            if apply and decision.get("action"):
                if self.config.get("port_pressure", {}).get("mode") == "off":
                    # Disabled deployments retain the existing per-target STOP
                    # and dispatch order; observation adds no maintenance lane.
                    try:
                        status["delivery"] = self.dispatch(target, ledger, decision)
                    except Exception as error:
                        status["delivery"] = {"state": "not-sent", "reason": str(error)[:700]}
                    self.write(directory / "status.json", status)
                else:
                    deliveries.append((target, ledger, decision, status))
            from kg_microbe_workflows.session_durability import public_summary
            rows.append({"repository": target["repository_key"], "stage": ledger["stage"], "cycle": ledger.get("cycle", 1),
                         "phase": decision["phase"], "reason": decision.get("reason"),
                         "goal_state": observation.get("goal_state"),
                         "agent_progress": status["agent_progress"],
                         "session_durability": public_summary(status["session_durability"]),
                         "delivery": (status.get("delivery") or {}).get("state")})
            self.write(self.runtime / "heartbeat.json", {"pid": os.getpid(), "updated_at": now(),
                "running": True, "mode": "apply" if apply else "observe", "sweep_in_progress": True,
                "repositories_observed": len(rows), "repositories_total": len(self.config["targets"])})
        # Goal starts run first irrespective of target-list order. They retain
        # their closure proof and use their own target-specific maintenance.
        deliveries.sort(key=lambda entry: entry[2].get("action") != "start_goal")
        attempted = []
        boundary_reports = []
        for target, ledger, decision, status in deliveries:
            if self.stopping():
                break
            if (decision.get("action") != "start_goal"
                    and not self._port_pressure_recycled and not fallback_attempted
                    and initial_pressure.get("phase") == "candidate"
                    and pressure.get("phase") not in {"disabled", "unknown"}):
                fallback_attempted = True
                pressure = self.port_pressure(apply=apply, excluded_repository_keys=tuple(attempted))
                self._port_pressure_recycled = pressure.get("phase") == "restarted"
                if pressure.get("phase") in {"restarted", "disabled", "unknown"}:
                    break
            try:
                attempted.append(target["repository_key"])
                self._port_pressure_boundary_report = None
                status["delivery"] = self.dispatch(target, ledger, decision)
            except Exception as error:
                status["delivery"] = {"state": "not-sent", "reason": str(error)[:700]}
            directory = self.directory(target)
            current_status = read_json(directory / "status.json")
            if current_status.get("port_pressure_restart"):
                status["port_pressure_restart"] = current_status["port_pressure_restart"]
            if ledger.get("port_pressure_boundary"):
                status["port_pressure_boundary"] = ledger["port_pressure_boundary"]
            self.write(directory / "status.json", status)
            next(row for row in rows if row["repository"] == target["repository_key"])["delivery"] = status["delivery"]["state"]
            if self._port_pressure_boundary_report:
                pressure = self._port_pressure_boundary_report
                boundary_reports.append(pressure)
            if pressure.get("phase") in {"disabled", "unknown"}:
                break
        if (apply and not self.stopping()
                and not self._port_pressure_recycled and not fallback_attempted
                and initial_pressure.get("phase") == "candidate"
                and pressure.get("phase") not in {"disabled", "unknown"}):
            pressure = self.port_pressure(apply=True, excluded_repository_keys=tuple(attempted))
            self._port_pressure_recycled = pressure.get("phase") == "restarted"
        if boundary_reports:
            pressure = {**pressure, "initial_idle_scan": initial_pressure, "goal_boundaries": boundary_reports,
                        "recycle_performed_this_tick": self._port_pressure_recycled}
        dashboard = {"run_id": self.config["run_id"], "updated_at": now(), "mode": "apply" if apply else "observe", "sessions": rows,
                     "port_pressure": pressure}
        self.write(self.runtime / "dashboard.json", dashboard)
        lines = ["# Mech session workflow", "", f"Updated: {dashboard['updated_at']}", "",
                 "| Repository | Stage | Phase | Native goal | Detail |", "|---|---:|---|---|---|"]
        for row in rows:
            detail = (row.get("reason") or row.get("delivery") or "").replace("|", "\\|").replace("\n", " ")
            progress = row.get("agent_progress") or {}
            if progress.get("authority") == "informational_only" and progress.get("phase"):
                detail += " Agent phase: " + progress["phase"].replace("|", "\\|").replace("\n", " ")
            durability = row["session_durability"]
            detail += (f" Durability {durability['status']}: "
                       f"unpushed={durability['unpushed_commits']}, "
                       f"at-risk={durability['at_risk_files']}, overdue={durability['overdue_files']}.")
            lines.append(f"| {row['repository']} | {row['stage']} | {row['phase']} | {row.get('goal_state', '')} | {detail} |")
        dashboard_path = self.runtime / "dashboard.md"
        if dashboard_path.is_symlink():
            raise SupervisorError("dashboard output must not be a symlink")
        dashboard_path.write_text("\n".join(lines) + "\n")
        self.write(self.runtime / "heartbeat.json", {"pid": os.getpid(), "updated_at": now(),
            "running": True, "mode": "apply" if apply else "observe", "sweep_in_progress": False,
            "repositories_observed": len(rows), "repositories_total": len(self.config["targets"])})
        return dashboard


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--observe", action="store_true", help="read-only observation (default)")
    mode.add_argument("--apply", action="store_true", help="submit guarded instructions at idle composers")
    mode.add_argument("--port-pressure-report", action="store_true",
                      help="only report port pressure and blocked tasks; never send session input")
    mode.add_argument("--port-pressure-restart", action="store_true",
                      help="only run the explicitly enabled maintenance guard; never dispatch goal text")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args(argv)
    if not 5 <= args.interval <= 60:
        parser.error("--interval must be between 5 and 60 seconds")
    config = validate_config(read_json(args.config))
    config["_config_path"] = str(args.config.resolve())
    stopped = False
    supervisor = Supervisor(config, stop_requested=lambda: stopped)
    guard_failed = False

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if args.port_pressure_report or args.port_pressure_restart:
        # A standalone observation must not acquire the workflow loop's lock or
        # overwrite its heartbeat. The guard owns a separate transaction lock.
        while not stopped and not supervisor.stopping():
            result = supervisor.port_pressure(report_only=args.port_pressure_report,
                                              apply=args.port_pressure_restart)
            print(json.dumps(result), flush=True)
            guard_failed = guard_failed or result.get("phase") in {"unknown", "disabled"}
            if not args.loop:
                return int(guard_failed)
            deadline = time.monotonic() + args.interval
            while not stopped and time.monotonic() < deadline:
                time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        return int(guard_failed)
    with file_lock(supervisor.runtime / "supervisor.lock"):
        try:
            while not stopped and not (supervisor.runtime / "STOP").exists():
                result = supervisor.sweep(apply=args.apply)
                print(json.dumps(result), flush=True)
                guard_failed = guard_failed or result.get("port_pressure", {}).get("phase") in {"unknown", "disabled"}
                if not args.loop:
                    break
                deadline = time.monotonic() + args.interval
                while not stopped and time.monotonic() < deadline:
                    time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        finally:
            supervisor.write(supervisor.runtime / "heartbeat.json", {"pid": os.getpid(), "updated_at": now(),
                "running": False, "mode": "apply" if args.apply else "observe"})
    return int(guard_failed)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SupervisorError, BlockingIOError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
