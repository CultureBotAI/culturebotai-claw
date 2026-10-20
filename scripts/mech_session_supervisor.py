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
    return json.loads(path.read_text())


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
    if re.search(r"esc to interrupt|\b(?:messages?|tasks?) queued\b|\bqueued (?:messages?|tasks?)\b|"
                 r"alt\+m to send immediately|Press up to edit queued messages|"
                 r"\b[1-9]\d* (?:background )?task\(s\)|\b[1-9]\d* background tasks?\b|"
                 r"\bbackground tasks?:\s*[1-9]\d*|^\s*● .* running\s*$", footer, re.I | re.M):
        return "busy, background, or queued terminal state"
    return None


def normalize_github(url: str) -> str:
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?", url.strip())
    if not match:
        raise SupervisorError("Unrecognized GitHub origin")
    return match.group(1).casefold()


def validate_config(config: dict, *, resolve_repositories: bool = True) -> dict:
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
                      "process_identity", "workflow_prompt_path", "stages", "default_branch", "initial_goal_identity"):
            if not target.get(field):
                raise SupervisorError(f"{key}: missing {field}")
        if target.get("initial_stage") not in range(0, 5):
            raise SupervisorError(f"{key}: initial_stage must be 0 through 4")
        if not isinstance(target["pid"], int) or target["pid"] <= 0:
            raise SupervisorError(f"{key}: invalid PID")
        initial = target["initial_goal_identity"]
        if (not isinstance(initial, dict) or initial.get("conversation_id") != target["native_session_id"]
                or not initial.get("started_at") or type(initial.get("start_step_index")) is not int):
            raise SupervisorError(f"{key}: initial goal identity is incomplete")
        if not re.fullmatch(r"/dev/ttys\d+", target["tty"]):
            raise SupervisorError(f"{key}: invalid TTY")
        if {stage.get("stage") for stage in target["stages"]} != {1, 2, 3, 4}:
            raise SupervisorError(f"{key}: exactly four stages required")
        if len(target["stages"]) != 4:
            raise SupervisorError(f"{key}: duplicate stages")
        for stage in target["stages"]:
            if not isinstance(stage.get("goal_text"), str) or not stage["goal_text"].strip():
                raise SupervisorError(f"{key}: stage goal_text missing")
            if not stage.get("skill_paths"):
                raise SupervisorError(f"{key}: stage skill_paths missing")
        if not Path(target["root"]).is_absolute():
            raise SupervisorError(f"{key}: repository root must be absolute")
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


def new_ledger(config: dict, target: dict) -> dict:
    return {"schema_version": 1, "run_id": config["run_id"],
            "repository_key": target["repository_key"], "stage": target["initial_stage"],
            "adopted_goal": None, "awaiting_goal": False, "actions": {},
            "completed_stages": [], "phase": "assessment", "created_at": now()}


def action_id(ledger: dict, kind: str) -> str:
    # Text can be amended by agy; stable native start identity is intentional.
    return digest([ledger["run_id"], ledger["repository_key"], ledger["stage"],
                   ledger["adopted_goal"], kind])[:24]


def decide(ledger: dict, observation: dict) -> dict:
    """Pure next-action reducer. A send is never evidence of completion."""
    if observation.get("error"):
        return {"phase": "unavailable", "reason": observation["error"]}
    if ledger["stage"] > 4:
        return {"phase": "pipeline_complete"}
    if not observation.get("ready"):
        return {"phase": "waiting", "reason": observation.get("readiness_reason", "not ready")}
    if observation.get("goal_state") == "cancelled":
        return {"phase": "blocked", "reason": "native goal is cancelled; cannot infer continuation intent"}
    if ledger.get("awaiting_goal"):
        if observation.get("goal_identity") != ledger["adopted_goal"]:
            return {"phase": "blocked", "reason": "a different native goal appeared before next-goal dispatch"}
        prior = ledger["completed_stages"][-1] if ledger["completed_stages"] else {}
        override = (prior.get("completion_authority") == "verified_receipt_override"
                    and prior.get("goal_identity") == ledger["adopted_goal"]
                    and observation.get("goal_state") == "active")
        if observation.get("goal_state") != "completed" and not override:
            return {"phase": "blocked", "reason": "previous native goal is not completed"}
        kind = "start_goal"
    elif not ledger.get("adopted_goal"):
        return {"phase": "blocked", "reason": "no authoritative current goal; assessment required"}
    elif observation.get("goal_identity") != ledger["adopted_goal"]:
        return {"phase": "blocked", "reason": "native goal identity changed without a matching dispatched goal"}
    else:
        # One initial/resumption instruction owns its entire closure. Do not
        # repeatedly nudge an accepted instruction that has not produced proof.
        prior = [a for a in ledger["actions"].values()
                 if a["stage"] == ledger["stage"] and a["kind"] in {"assess_and_finalize", "finalize", "repair_closure"}
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
            and progress.get("stage") == ledger["stage"]
            and progress.get("phase", "").lower() in {"blocked", "prerequisite_blocked", "requires_intervention"}):
        return {"phase": "requires_intervention", "reason": "agent reports blocked: " + progress.get("summary", reason)}
    if not observation.get("ready") or observation.get("goal_identity") != ledger["adopted_goal"]:
        return {"phase": "waiting", "reason": reason}
    if observation.get("goal_state") == "cancelled":
        return {"phase": "blocked", "reason": "native goal is cancelled; cannot infer continuation intent"}
    # A definitive pre-send rejection cannot acquire native acceptance. It
    # neither supersedes the last delivered instruction nor consumes a repair.
    actions = [action for action in ledger["actions"].values()
               if action["stage"] == ledger["stage"] and action["state"] != "not-sent"]
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
    accepted = any(action["state"] == "accepted" and action["stage"] == ledger["stage"]
                   and action.get("accepted_goal_identity", action.get("goal_identity")) == ledger["adopted_goal"]
                   for action in ledger["actions"].values())
    if (target.get("allow_receipt_completion_override") is True
            and observation.get("goal_state") == "active" and accepted):
        return "verified_receipt_override"
    raise SupervisorError("native goal is not completed; no explicit audited receipt-override policy applies")


def stage_profile(target: dict, stage: int) -> dict:
    return next(item for item in target["stages"] if item["stage"] == stage)


def message_for(target: dict, ledger: dict, decision: dict, repository_runtime: Path) -> str:
    marker = "MECH-WORKFLOW-" + decision["action_id"]
    context = (f"[{marker}] Read {target['workflow_prompt_path']} and "
               f"{repository_runtime / 'status.json'}. Repository-local .claude/skills is the skill source of truth. "
               f"This is run {ledger['run_id']}, stage {ledger['stage']}. "
               f"Write the required structured closure receipt to {repository_runtime / 'completion.json'}. "
               "Do not start another goal: the supervisor verifies closure and chooses the next goal. ")
    if decision["action"] == "start_goal":
        profile = stage_profile(target, ledger["stage"])
        return (f"/goal {profile['goal_text']} {context} "
                "After completing this objective, run the authorized commit/push PR, adversarial review, "
                "issue creation and fixes, merge, and branch cleanup sequence; write the receipt and stop.")
    if decision["action"] == "finalize":
        return (context + "The adopted goal has native completion evidence. Verify its result and finish the "
                "authorized commit/push PR, adversarial review, issue creation and fixes, merge, and branch "
                "cleanup sequence. Reuse already completed matching steps after verifying their evidence.")
    if decision["action"] == "repair_closure":
        return (context + "Continue only unfinished work or repair the closure receipt. The independent verifier reports: "
                + decision["repair_reason"] + ". Re-read current status and existing PR/review/issues before acting; "
                "reuse proven completed steps. Preserve unrelated changes, never force cleanup, and do not start another goal.")
    return (context + "First assess the last running goal recorded in status.json. If incomplete, continue "
            "that same objective using its applicable skill; do not replace or reset it. If complete, "
            "proceed to the authorized commit/push PR, adversarial review, issue creation and fixes, "
            "merge, and branch cleanup sequence. Complete that sequence once the goal finishes.")


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


def validate_receipt(receipt: dict, ledger: dict, target: dict, runtime: Path) -> list[str]:
    """Validate claims and bound evidence before any remote verification."""
    errors = []
    for key in ("run_id", "repository_key", "stage"):
        if receipt.get(key) != ledger[key]:
            errors.append(f"receipt {key} mismatch")
    if receipt.get("schema_version") != 1 or receipt.get("goal_complete") is not True:
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
    return errors


def verify_remote_receipt(receipt: dict, ledger: dict, target: dict, runner=command) -> dict:
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
        return {"verified_at": now(), "status": "no_changes", "head_sha": head}
    pr = receipt["pr"]
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
    commits = gh_json("api", "--paginate", "--slurp", f"repos/{github}/pulls/{pr['number']}/commits?per_page=100")
    commit_shas = {item["sha"] for page in commits for item in page}
    for issue in receipt["issues"]:
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
    return {"verified_at": now(), "status": "merged", "pr_number": pr["number"],
            "head_sha": pr["head_sha"], "merge_commit_sha": live.get("merge_commit_sha"),
            "merged_at": live["merged_at"], "checks": checks}


SEND_JS = r'''
function run(argv) {
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
        let currentScreen;
        try { currentScreen = tab.contents(); } catch (error) { return 'target-unavailable'; }
        if (currentScreen !== expected.screen) return 'screen-changed';
        terminal.doScript(expected.message, {in: tab});
        return 'sent';
    }
    return 'window-closed';
}
'''


class Supervisor:
    def __init__(self, config: dict, *, native=None, notifier=None, runner=command, stop_requested=None):
        self.config = config
        self.runtime = Path(config["runtime_dir"])
        self.native = native or import_file(Path(config["native_reader_path"]), "supervisor_native")
        self.notifier = notifier or import_file(Path(config["notifier_path"]), "supervisor_terminal")
        self.runner = runner
        self.stop_requested = stop_requested or (lambda: False)
        self.native_cache: dict[str, tuple[tuple, dict]] = {}

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

    def observe(self, target: dict, *, fresh: bool = False) -> dict:
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
        native_goal = (observation.get("native") or {}).get("current_goal") or {}
        if not ledger["adopted_goal"] and native_id:
            if native_id != target["initial_goal_identity"]:
                observation.update(error="native goal differs from the assessed initial goal; reassessment required", ready=False)
                return
            ledger["adopted_goal"] = native_id
        history_path = Path(self.config.get("history_path", Path.home() / ".gemini/antigravity-cli/history.jsonl"))
        pending = [a for a in ledger["actions"].values() if a["state"] in BLOCKING_RECEIPTS]
        if pending and history_path.is_file():
            with history_path.open() as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("workspace") != target["root"]:
                        continue
                    for action in pending:
                        if (action["marker"] in str(row.get("display", ""))
                                and row.get("timestamp", 0) >= action["reserved_epoch_ms"]
                                and row.get("conversationId") == target["native_session_id"]
                                and action["native_session_id"] == target["native_session_id"]):
                            action.update(state="accepted", accepted_at=now(), acceptance="native_workspace_history_marker")
        if ledger.get("awaiting_goal") and native_id and native_id != ledger["adopted_goal"]:
            for action in pending:
                if (action["kind"] == "start_goal" and action["stage"] == ledger["stage"]
                        and action["marker"] in native_goal.get("goal_text", "")):
                    action.update(state="accepted", accepted_at=now(), acceptance="native_goal_marker")
                    action["accepted_goal_identity"] = native_id
                    ledger.update(adopted_goal=native_id, awaiting_goal=False)
                    break

    def baseline(self, target: dict, ledger: dict) -> None:
        if "baseline_head" not in ledger:
            ledger["baseline_head"] = self.runner(["git", "-C", target["root"], "rev-parse", "HEAD"]).stdout.strip()
            ledger["baseline_status"] = self.runner(["git", "-C", target["root"], "status", "--porcelain=v1", "--untracked-files=all"]).stdout

    def skill_errors(self, target: dict, stage: int) -> list[str]:
        if stage == 0:
            return []
        errors = []
        profile = stage_profile(target, stage)
        if profile.get("applicability") not in {None, "available", "available_via_composed_workflow",
                                               "available_with_instruction_conflict", "applicability_audit"}:
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
            for key in ("run_id", "repository_key", "stage"):
                if reported.get(key) != ledger[key]:
                    raise SupervisorError("progress identity mismatch")
            if reported.get("goal_identity") != ledger["adopted_goal"]:
                raise SupervisorError("progress goal identity mismatch")
            current = False
            try:
                stamp = datetime.fromisoformat(reported.get("updated_at", "").replace("Z", "+00:00"))
                last_dispatch = max((action.get("reserved_epoch_ms", 0) / 1000 for action in ledger["actions"].values()
                                     if action["stage"] == ledger["stage"]), default=0)
                current = stamp.tzinfo is not None and last_dispatch <= stamp.timestamp() <= time.time() + 60 and time.time() - stamp.timestamp() < 86400
            except (TypeError, ValueError):
                pass
            return {"authority": "informational_only", "stage": reported["stage"], "current": current,
                    **{key: str(reported[key])[:500]
                    for key in ("phase", "summary", "updated_at", "pr_url") if key in reported}}
        except Exception as error:
            return {"authority": "ignored", "error": str(error)[:300]}

    def dispatch(self, target: dict, ledger: dict, decision: dict) -> dict:
        if self.stopping():
            return {"state": "not-sent", "reason": "supervisor stop requested"}
        lock = Path(self.config["input_lock_dir"]) / (Path(target["tty"]).name + ".lock")
        with file_lock(lock):
            observation = self.observe(target, fresh=True)
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
            errors = self.skill_errors(target, ledger["stage"])
            if errors:
                return {"state": "not-sent", "reason": "; ".join(errors)}
            prompt = Path(target["workflow_prompt_path"])
            if not prompt.is_file():
                return {"state": "not-sent", "reason": "workflow instruction file missing"}
            identifier = decision["action_id"]
            message = message_for(target, ledger, decision, self.directory(target))
            action = {"id": identifier, "kind": decision["action"], "stage": ledger["stage"],
                      "marker": "MECH-WORKFLOW-" + identifier, "state": "reserved", "reserved_at": now(),
                      "reserved_epoch_ms": int(time.time() * 1000), "native_session_id": target["native_session_id"],
                      "goal_identity": ledger["adopted_goal"], "message": message,
                      "native_step_index": ((observation.get("native") or {}).get("last_step") or {}).get("index"),
                      "instruction_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest()}
            ledger["actions"][identifier] = action
            self.save(target, ledger)  # durable intent before any terminal input
            try:
                if self.stopping():
                    action.update(state="not-sent", outcome="stop-requested", updated_at=now())
                else:
                    result = self.notifier.jxa(SEND_JS, {**observation["tab"], "pid": target["pid"],
                        "identity": target["process_identity"], "cwd": target["root"], "message": message})
                    action.update(state="sent" if result == "sent" else "not-sent", outcome=result, updated_at=now())
            except Exception as error:
                action.update(state="uncertain", error=str(error)[:500], updated_at=now())
            self.save(target, ledger)
            return action

    def sweep(self, *, apply: bool = False) -> dict:
        rows = []
        for target in self.config["targets"]:
            if self.stopping():
                break
            directory = self.directory(target)
            ledger_path = directory / "ledger.json"
            if ledger_path.is_symlink():
                raise SupervisorError("runtime ledger must not be a symlink")
            ledger = read_json(ledger_path) if ledger_path.exists() else new_ledger(self.config, target)
            if ledger.get("run_id") != self.config["run_id"] or ledger.get("repository_key") != target["repository_key"]:
                raise SupervisorError("runtime ledger belongs to another workflow")
            observation = self.observe(target)
            if self.stopping():
                break
            self.reconcile(target, ledger, observation)
            try:
                self.baseline(target, ledger)
            except Exception as error:
                observation.update(error=str(error)[:700], ready=False)
            observation["agent_progress"] = self.progress(target, ledger)
            receipt_path = directory / "completion.json"
            verification = None
            receipt_errors = []
            if receipt_path.exists() and ledger["stage"] <= 4 and not ledger.get("awaiting_goal"):
                try:
                    if receipt_path.is_symlink() or receipt_path.resolve().parent != directory.resolve() or not receipt_path.is_file():
                        raise SupervisorError("completion receipt is not a regular file inside this repository runtime")
                    receipt = read_json(receipt_path)
                    archived = any(record["receipt_sha256"] == digest(receipt)
                                   for record in ledger["completed_stages"])
                    receipt_errors = [] if archived else validate_receipt(receipt, ledger, target, directory)
                    if not archived and not receipt_errors and observation.get("ready"):
                        authority = completion_authority(target, ledger, observation)
                        verification = verify_remote_receipt(receipt, ledger, target, self.runner)
                        closed_stage = ledger["stage"]
                        advanced = copy.deepcopy(ledger)
                        advanced["completed_stages"].append({"stage": closed_stage, "goal_identity": ledger["adopted_goal"],
                            "receipt_sha256": digest(receipt), "verification": verification,
                            "completion_authority": authority})
                        advanced.update(stage=closed_stage + 1, awaiting_goal=closed_stage < 4)
                        advanced.pop("baseline_head", None)
                        advanced.pop("baseline_status", None)
                        self.baseline(target, advanced)
                        self.write(directory / "receipts" / f"stage-{closed_stage}-{digest(receipt)[:12]}.json", receipt)
                        # Publish the whole in-memory transition only after all
                        # fallible preparation; the ledger is saved atomically.
                        ledger = advanced
                        # Do not delete the producer's file; mismatched old receipts
                        # are ignored only while a new goal is awaiting acceptance.
                except Exception as error:
                    receipt_errors.append(str(error)[:700])
            decision = decide(ledger, observation)
            if receipt_errors:
                receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest() if receipt_path.is_file() and not receipt_path.is_symlink() and receipt_path.resolve().parent == directory.resolve() else None
                decision = repair_decision(ledger, observation, "; ".join(receipt_errors), receipt_hash)
            elif decision.get("action") == "repair_closure" and receipt_path.is_file():
                decision = repair_decision(ledger, observation, decision["repair_reason"], hashlib.sha256(receipt_path.read_bytes()).hexdigest())
            if decision.get("action"):
                errors = self.skill_errors(target, ledger["stage"])
                if errors:
                    decision = {"phase": "blocked", "reason": "; ".join(errors)}
            ledger.update(phase=decision["phase"], last_observed_at=observation["observed_at"],
                          blocked_reason=decision.get("reason"))
            self.save(target, ledger)
            public_observation = {k: v for k, v in observation.items() if k not in {"tab", "native"}}
            native = observation.get("native") or {}
            status = {"run_id": ledger["run_id"], "repository_key": target["repository_key"],
                      "stage": ledger["stage"], "goal_identity": ledger["adopted_goal"],
                      "phase": decision["phase"], "decision": decision, "observation": public_observation,
                      "native_execution_state": native.get("native_execution_state"),
                      "current_goal": native.get("current_goal"), "last_step": native.get("last_step"),
                      "completion_receipt_path": str(receipt_path), "verification": verification,
                      "agent_progress": self.progress(target, ledger),
                      "completed_stages": ledger["completed_stages"], "updated_at": now()}
            self.write(directory / "status.json", status)
            if apply and decision.get("action"):
                try:
                    status["delivery"] = self.dispatch(target, ledger, decision)
                except Exception as error:
                    status["delivery"] = {"state": "not-sent", "reason": str(error)[:700]}
                self.write(directory / "status.json", status)
            rows.append({"repository": target["repository_key"], "stage": ledger["stage"],
                         "phase": decision["phase"], "reason": decision.get("reason"),
                         "goal_state": observation.get("goal_state"),
                         "agent_progress": status["agent_progress"],
                         "delivery": (status.get("delivery") or {}).get("state")})
            self.write(self.runtime / "heartbeat.json", {"pid": os.getpid(), "updated_at": now(),
                "running": True, "mode": "apply" if apply else "observe", "sweep_in_progress": True,
                "repositories_observed": len(rows), "repositories_total": len(self.config["targets"])})
        dashboard = {"run_id": self.config["run_id"], "updated_at": now(), "mode": "apply" if apply else "observe", "sessions": rows}
        self.write(self.runtime / "dashboard.json", dashboard)
        lines = ["# Mech session workflow", "", f"Updated: {dashboard['updated_at']}", "",
                 "| Repository | Stage | Phase | Native goal | Detail |", "|---|---:|---|---|---|"]
        for row in rows:
            detail = (row.get("reason") or row.get("delivery") or "").replace("|", "\\|").replace("\n", " ")
            progress = row.get("agent_progress") or {}
            if progress.get("authority") == "informational_only" and progress.get("phase"):
                detail += " Agent phase: " + progress["phase"].replace("|", "\\|").replace("\n", " ")
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
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args(argv)
    if not 5 <= args.interval <= 60:
        parser.error("--interval must be between 5 and 60 seconds")
    config = validate_config(read_json(args.config))
    stopped = False
    supervisor = Supervisor(config, stop_requested=lambda: stopped)

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with file_lock(supervisor.runtime / "supervisor.lock"):
        try:
            while not stopped and not (supervisor.runtime / "STOP").exists():
                print(json.dumps(supervisor.sweep(apply=args.apply)), flush=True)
                if not args.loop:
                    break
                deadline = time.monotonic() + args.interval
                while not stopped and time.monotonic() < deadline:
                    time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        finally:
            supervisor.write(supervisor.runtime / "heartbeat.json", {"pid": os.getpid(), "updated_at": now(),
                "running": False, "mode": "apply" if args.apply else "observe"})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SupervisorError, BlockingIOError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
