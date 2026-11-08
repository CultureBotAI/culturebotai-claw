"""Explicit historical closure plans; never observe a terminal or send input.

The operator record is a trusted human-attestation boundary, not a signature.
Its exact byte digest, independent review and all live facts must agree. Drafts
are inspectable but never executable. The global supervisor STOP is preserved.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from kg_microbe_write import ValidatedWriteTransaction

IMPLEMENTATION_PATHS = (
    "scripts/mech_session_supervisor.py", "scripts/mech_session_native.py",
    "scripts/mech_goal_reconcile.py", "src/kg_microbe_workflows/reconciliation.py",
    "src/kg_microbe_workflows/closure.py",
)
FINGERPRINTS = ("config_sha256", "ledger_sha256", "completion_sha256",
                "pr_associations_sha256", "infra_notebook_sha256", "native_evidence_sha256")
KEYS = {"schema_version", "operation", "record_status", "assessed_at", "expires_at",
        "requested_by", "reason", "repository_key", "run_id", "cycle", "stage",
        "parent_version", "workflow_sha256", "historical_goal_identity", "current_goal_identity",
        "fingerprints", "required_infra_tasks", "external_pr", "review", "prerequisites",
        "reconciliation_sha256", "implementation_commit", "implementation_sha256"}


class ReconciliationError(ValueError):
    """Missing or changed authority; preserve state and stop."""


def require(ok: Any, reason: str) -> None:
    if not ok:
        raise ReconciliationError(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def object_keys(value: Any, keys: set[str], label: str) -> None:
    require(isinstance(value, dict) and set(value) == keys, f"{label}: fields differ from closed contract")


def hex_value(value: Any, size: int, label: str) -> None:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(size) + "}", value), label)


def timestamp(value: Any) -> datetime:
    require(isinstance(value, str), "timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReconciliationError("invalid timestamp") from error
    require(parsed.tzinfo is not None, "timestamp must be timezone-aware")
    return parsed


def validate_record(record: dict, *, reviewed: bool = False) -> None:
    object_keys(record, KEYS, "operator record")
    require(record["schema_version"] == "1.0.0", "unsupported operator record version")
    require(record["operation"] in {"close_historical_goal", "release_boundary"}, "unsupported operation")
    require(record["record_status"] in {"draft", "reviewed"}, "invalid record status")
    require(not reviewed or record["record_status"] == "reviewed", "draft record has no execution authority")
    is_reviewed = record["record_status"] == "reviewed"
    for key in ("requested_by", "reason", "repository_key", "run_id", "parent_version"):
        require(isinstance(record[key], str) and record[key].strip(), f"{key} must be nonblank")
    require(re.fullmatch(r"[a-z][a-z0-9_-]*", record["repository_key"]), "invalid repository key")
    for key in ("cycle", "stage"):
        require(type(record[key]) is int and record[key] > 0, f"invalid {key}")
    hex_value(record["workflow_sha256"], 64, "invalid workflow digest")
    for key in ("historical_goal_identity", "current_goal_identity"):
        identity = record[key]
        object_keys(identity, {"conversation_id", "started_at", "start_step_index"}, key)
        require(isinstance(identity["conversation_id"], str) and identity["conversation_id"], "missing conversation")
        require(type(identity["start_step_index"]) is int and identity["start_step_index"] >= 0, "invalid goal step")
        timestamp(identity["started_at"])
    old, current = record["historical_goal_identity"], record["current_goal_identity"]
    require(old["conversation_id"] == current["conversation_id"] and old["start_step_index"] < current["start_step_index"]
            and timestamp(old["started_at"]) < timestamp(current["started_at"]), "native goal identities are not ordered")
    start, end = timestamp(record["assessed_at"]), timestamp(record["expires_at"])
    require(start < end <= start + timedelta(hours=24), "assessment validity must be bounded to 24 hours")
    object_keys(record["fingerprints"], set(FINGERPRINTS), "fingerprints")
    for name, value in record["fingerprints"].items():
        if value is not None or is_reviewed:
            hex_value(value, 64, f"invalid {name}")
    for key in ("required_infra_tasks", "prerequisites"):
        require(isinstance(record[key], list) and all(isinstance(v, str) and v.strip() for v in record[key]), f"invalid {key}")
        require(len(record[key]) == len(set(record[key])), f"duplicate {key}")
    require(record["required_infra_tasks"], "required infrastructure intake cannot be empty")
    require(not is_reviewed or not record["prerequisites"], "reviewed record has unmet prerequisites")
    object_keys(record["external_pr"], {"number", "head_sha", "merge_commit_sha"}, "external PR")
    require(type(record["external_pr"]["number"]) is int and record["external_pr"]["number"] > 0, "invalid external PR")
    for key in ("head_sha", "merge_commit_sha"):
        hex_value(record["external_pr"][key], 40, "invalid external PR commit")
    if record["review"] is not None or is_reviewed:
        object_keys(record["review"], {"reviewer", "artifact", "sha256"}, "independent review")
        require(isinstance(record["review"]["reviewer"], str) and record["review"]["reviewer"].strip()
                and record["review"]["reviewer"] != record["requested_by"], "review must be independent")
        require(isinstance(record["review"]["artifact"], str) and record["review"]["artifact"], "review artifact missing")
        hex_value(record["review"]["sha256"], 64, "review digest missing")
    if record["operation"] == "close_historical_goal":
        require(record["reconciliation_sha256"] is None, "closure cannot name a prior reconciliation")
    else:
        hex_value(record["reconciliation_sha256"], 64, "release needs exact reconciliation digest")
    if record["implementation_commit"] is not None or is_reviewed:
        hex_value(record["implementation_commit"], 40, "implementation commit missing")
    object_keys(record["implementation_sha256"], set(IMPLEMENTATION_PATHS), "implementation pins")
    for value in record["implementation_sha256"].values():
        if value is not None or is_reviewed:
            hex_value(value, 64, "implementation digest missing")


def regular_bytes(path: Path, *, boundary: Path | None = None) -> bytes:
    require(path.is_absolute(), "input path must be absolute")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlinked input is forbidden")
    if boundary is not None:
        require(path.resolve().is_relative_to(boundary.resolve()), "input escapes allowed boundary")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= 16_000_000, "input is not a bounded regular file")
        return stream.read()


def decode(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda value: require(False, "nonfinite JSON number"))
    require(isinstance(result, dict), "JSON input must be an object")
    return result


def boundary_goal(ledger: dict) -> dict | None:
    """Recognize only a verified/released boundary in this exact next stage."""
    boundary = ledger.get("historical_goal_boundary")
    if boundary is None:
        return None
    object_keys(boundary, {"assessment_sha256", "current_goal_identity", "cycle", "stage", "released_by"}, "historical boundary")
    entry = ledger.get("historical_reconciliations", {}).get(boundary["assessment_sha256"])
    require(isinstance(entry, dict), "historical boundary has no audit entry")
    record = entry["assessment"]
    require(canonical(record) == boundary["assessment_sha256"], "historical assessment digest changed")
    validate_record(record, reviewed=True)
    require(record["operation"] == "close_historical_goal", "boundary requires historical closure")
    require(ledger.get("awaiting_goal") is True and record["cycle"] == ledger["cycle"] == boundary["cycle"]
            and record["stage"] + 1 == ledger["stage"] == boundary["stage"]
            and record["workflow_sha256"] == ledger["workflow"]["sha256"]
            and record["run_id"] == ledger["run_id"] and record["repository_key"] == ledger["repository_key"]
            and record["parent_version"] == ledger["parent_version"]
            and record["historical_goal_identity"] == ledger["adopted_goal"]
            and record["current_goal_identity"] == boundary["current_goal_identity"], "historical boundary context changed")
    require(isinstance(ledger.get("completed_stages"), list) and ledger["completed_stages"], "historical closure is missing")
    closed = ledger["completed_stages"][-1]
    require(closed.get("reconciliation_sha256") == boundary["assessment_sha256"]
            and closed.get("goal_identity") == record["historical_goal_identity"]
            and closed.get("stage") == record["stage"] and closed.get("cycle") == record["cycle"], "historical closure attribution changed")
    release = boundary["released_by"]
    if release is None:
        raise ReconciliationError("historical next-goal boundary awaits separate operator release")
    release_record = ledger.get("historical_releases", {}).get(release)
    require(isinstance(release_record, dict) and canonical(release_record) == release, "release audit missing or changed")
    validate_record(release_record, reviewed=True)
    require(release_record["operation"] == "release_boundary" and release_record["reconciliation_sha256"] == boundary["assessment_sha256"]
            and release_record["current_goal_identity"] == boundary["current_goal_identity"]
            and release_record["cycle"] == ledger["cycle"] and release_record["stage"] == ledger["stage"]
            and all(release_record[key] == record[key] for key in
                    ("run_id", "repository_key", "parent_version", "workflow_sha256", "historical_goal_identity", "external_pr", "required_infra_tasks")), "release context changed")
    return boundary["current_goal_identity"]


def fingerprints(config_path: Path, directory: Path, target: dict, native_proof: dict) -> dict:
    paths = {"config_sha256": config_path, "ledger_sha256": directory / "ledger.json",
             "completion_sha256": directory / "completion.json", "pr_associations_sha256": directory / "pr-associations.jsonl",
             "infra_notebook_sha256": Path(target["root"]) / "INFRA_TASKS.md"}
    return {**{key: sha(regular_bytes(path)) for key, path in paths.items()}, "native_evidence_sha256": canonical(native_proof)}


def prepare(supervisor: Any, helpers: Any, config_path: Path, record_path: Path,
            approved_sha256: str | None = None, *, apply: bool = False) -> dict:
    """Caller holds supervisor/input locks and retains STOP; no Terminal API used."""
    raw = regular_bytes(record_path)
    record = decode(raw)
    validate_record(record, reviewed=True)
    record_id = canonical(record)
    if apply:
        require(approved_sha256 == sha(raw), "apply requires the exact approved operator-record byte digest")
    clock = datetime.now(timezone.utc)
    require(timestamp(record["assessed_at"]) <= clock < timestamp(record["expires_at"]), "operator assessment expired or from future")
    review = record["review"]
    artifact = record_path.parent / review["artifact"]
    require(sha(regular_bytes(artifact, boundary=record_path.parent)) == review["sha256"], "independent review artifact changed")
    for relative, expected in record["implementation_sha256"].items():
        require(sha(regular_bytes(helpers.ROOT / relative)) == expected, "implementation source changed")
    def git(*args):
        return supervisor.runner(["git", "-C", str(helpers.ROOT), *args]).stdout.strip()
    require(git("rev-parse", "HEAD") == record["implementation_commit"], "implementation commit changed")
    require(not git("status", "--porcelain=v1", "--untracked-files=all"), "implementation checkout is not clean")
    target = next((t for t in supervisor.config["targets"] if t["repository_key"] == record["repository_key"]), None)
    if target is None:
        raise ReconciliationError("repository is not configured")
    directory = supervisor.directory(target)
    ledger = decode(regular_bytes(directory / "ledger.json"))
    prior_map = "historical_reconciliations" if record["operation"] == "close_historical_goal" else "historical_releases"
    if record_id in ledger.get(prior_map, {}):
        prior = ledger[prior_map][record_id]
        require((prior.get("assessment") if prior_map == "historical_reconciliations" else prior) == record, "reconciliation audit changed")
        return {"status": "already_applied", "record_sha256": sha(raw), "reconciliation_sha256": record_id, "sent_input": False}
    require(ledger["schema_version"] == 2 and ledger["run_id"] == record["run_id"] == supervisor.config["run_id"]
            and ledger["cycle"] == record["cycle"] and ledger["stage"] == record["stage"]
            and ledger["parent_version"] == record["parent_version"]
            and ledger["workflow"]["sha256"] == record["workflow_sha256"]
            and helpers.digest(ledger["workflow"]["effective"]) == record["workflow_sha256"]
            and ledger["adopted_goal"] == record["historical_goal_identity"]
            and target["native_session_id"] == record["current_goal_identity"]["conversation_id"], "operator context differs from retained ledger")
    require(not ledger.get("policy_notification_required"), "policy handoff is pending")
    def prove():
        return supervisor.native.reconciliation_evidence(target["root"], target["native_session_id"],
                                                         record["historical_goal_identity"], record["current_goal_identity"])
    proof = prove()
    expected = record["fingerprints"]
    require(fingerprints(config_path, directory, target, proof) == expected, "live fingerprint differs from approved assessment")
    original = copy.deepcopy(ledger)
    outputs: dict[Path, dict] = {}

    def check_workflow(*, capture_missing=True):
        # Reuse every ordinary pin/archive guard without its eager writes.
        # Matching snapshots are immutable inputs, not rewrite candidates.
        previous_write = supervisor.write
        def capture(path, value):
            if path.exists() or path.is_symlink():
                require(decode(regular_bytes(path, boundary=directory)) == value,
                        "pinned workflow snapshot changed")
            else:
                require(capture_missing, "workflow snapshot disappeared before ledger commit")
                outputs[path] = copy.deepcopy(value)
        supervisor.write = capture
        try:
            supervisor.check_workflow(target, original)
        finally:
            supervisor.write = previous_write

    check_workflow()
    if record["operation"] == "close_historical_goal":
        require(not ledger.get("awaiting_goal") and "historical_goal_boundary" not in ledger, "historical closure is not eligible")
        stages = ledger["workflow"]["effective"]["stages"]
        require(helpers.workflow_stage_key(ledger) == "resolve_review_findings"
                and next((s["key"] for s in stages if s["stage"] == ledger["stage"] + 1), None) == "infrastructure",
                "only review-remediation to infrastructure reconciliation is supported")
        receipt = decode(regular_bytes(directory / "completion.json"))
        from kg_microbe_workflows.closure import multi_pr_members
        members = multi_pr_members(receipt)
        require(members and len(members) >= 2, "historical closure requires the ordinary ordered receipt")
        require(not helpers.validate_receipt(receipt, ledger, target, directory), "ordinary receipt validation failed")
        require(record["external_pr"]["number"] not in {p["number"] for p in members}, "external work cannot receive stage credit")
        verification = helpers.verify_remote_receipt(receipt, ledger, target, supervisor.runner, runtime=directory)
        external = record["external_pr"]
        remote = json.loads(supervisor.runner(["gh", "api", f"repos/{target['github_repository']}/pulls/{external['number']}"]).stdout)
        require(remote.get("merged") is True and remote.get("head", {}).get("sha") == external["head_sha"]
                and remote.get("merge_commit_sha") == external["merge_commit_sha"]
                and remote.get("base", {}).get("repo", {}).get("full_name", "").casefold() == target["github_repository"].casefold(),
                "external PR evidence differs")
        # Ordinary advance is reused, but all its writes are captured until every
        # prerequisite and fresh native/fingerprint recheck has succeeded.
        previous_write = supervisor.write
        supervisor.write = lambda path, value: outputs.__setitem__(path, copy.deepcopy(value))
        try:
            ledger = supervisor.advance(target, ledger, receipt, verification, "reviewed_historical_native_completion")
        finally:
            supervisor.write = previous_write
        scope = ledger["infra_scope"]
        pending = {t["task_id"] for t in scope["tasks"] if t["status"] != "resolved"}
        require(set(record["required_infra_tasks"]) <= pending, "required intake is missing from the actual frozen notebook")
        notebook = Path(target["root"]) / "INFRA_TASKS.md"
        committed = supervisor.runner(["git", "-C", target["root"], "show", "HEAD:INFRA_TASKS.md"]).stdout.encode()
        require(committed == regular_bytes(notebook), "frozen intake is not the current committed notebook")
        ledger["completed_stages"][-1]["reconciliation_sha256"] = record_id
        ledger.setdefault("historical_reconciliations", {})[record_id] = {"assessment": record, "native_evidence": proof,
                                                                       "external_pr_verification": {"number": external["number"], "head_sha": remote["head"]["sha"],
                                                                           "merge_commit_sha": remote["merge_commit_sha"], "merged": True}}
        ledger["historical_goal_boundary"] = {"assessment_sha256": record_id,
            "current_goal_identity": record["current_goal_identity"], "cycle": ledger["cycle"], "stage": ledger["stage"], "released_by": None}
        ledger.update(phase="blocked", blocked_reason="historical next-goal boundary awaits separate operator release")
    else:
        boundary = ledger.get("historical_goal_boundary")
        if not isinstance(boundary, dict):
            raise ReconciliationError("release has no held reconciliation")
        require(boundary.get("assessment_sha256") == record["reconciliation_sha256"]
                and boundary.get("released_by") is None, "release does not match a held reconciliation")
        ledger.setdefault("historical_releases", {})[record_id] = record
        boundary["released_by"] = record_id
        require(boundary_goal(ledger) == record["current_goal_identity"], "invalid released boundary")
        ledger.update(phase="assessment", blocked_reason=None)
    # All effects are still in memory. Retained actions/old closure prefix and
    # active workflow are unchanged; no other session is in the write set.
    require(ledger["actions"] == original["actions"] and ledger["workflow"] == original["workflow"]
            and ledger["adopted_goal"] == original["adopted_goal"]
            and ledger["completed_stages"][:len(original["completed_stages"])] == original["completed_stages"], "protected history changed")
    check_workflow()
    require(fingerprints(config_path, directory, target, prove()) == expected, "live facts changed during verification")
    result = {"status": "applied" if apply else "dry_run", "record_sha256": sha(raw), "reconciliation_sha256": record_id,
              "operation": record["operation"], "from_stage": original["stage"], "to_stage": ledger["stage"],
              "ledger_before_sha256": expected["ledger_sha256"], "ledger_after_sha256": canonical(ledger), "sent_input": False}
    audit = directory / "operator-reconciliations" / record_id / "audit.json"
    outputs[audit] = {"result": {**result, "status": "prepared"},
                      "commit_point": "atomic ledger replacement", "assessment": record, "native_evidence": proof}
    for path in outputs:
        require(path.resolve().is_relative_to(directory) and not path.exists() and not path.is_symlink(), "append-only reconciliation output exists or escapes")
    if apply:
        regular_bytes(supervisor.runtime / "STOP")
        # Append-only supporting files first. A partial write cannot publish a
        # closure: the sole authoritative ledger replacement is the commit point.
        transaction = ValidatedWriteTransaction(directory, journal_dir=directory / "operator-reconciliations" / record_id / "journal")
        for path, value in outputs.items():
            transaction.stage(path, json.dumps(value, indent=2, sort_keys=True) + "\n")
        transaction.commit(apply=True)
        check_workflow(capture_missing=False)
        require(fingerprints(config_path, directory, target, prove()) == expected, "live facts changed before ledger commit; hold for reviewed recovery")
        regular_bytes(supervisor.runtime / "STOP")
        helpers.atomic_json(directory / "ledger.json", ledger, boundary=supervisor.runtime)
    return result
