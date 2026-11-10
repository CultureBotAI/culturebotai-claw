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

STAGE3_TRANSITION = "v1_protein_examples_to_record_review"
STAGE3_KEYS = (KEYS - {"external_pr"}) | {"transition", "external_prs", "native_proof_mode"}
LATER_INTAKE_KEYS = KEYS | {"later_intake"}


def stage3_record(record: dict) -> bool:
    return record.get("schema_version") == "2.0.0"


def later_intake_record(record: dict) -> bool:
    return record.get("schema_version") == "1.1.0"


def external_prs(record: dict) -> list[dict]:
    return record["external_prs"] if stage3_record(record) else [record["external_pr"]]


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
    expected_keys = (STAGE3_KEYS if stage3_record(record)
                     else LATER_INTAKE_KEYS if later_intake_record(record)
                     else KEYS)
    object_keys(record, expected_keys, "operator record")
    require(record["schema_version"] in {"1.0.0", "1.1.0", "2.0.0"}, "unsupported operator record version")
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
    if stage3_record(record):
        require(record["transition"] == STAGE3_TRANSITION and record["parent_version"] == "1.0.0",
                "unsupported stage-3 transition or parent")
        require(record["native_proof_mode"] in {"checkpoint_before_external", "retained_public_attestation"},
                "unsupported explicit stage-3 native proof mode")
        expected_stage = 3 if record["operation"] == "close_historical_goal" else 4
        require(record["stage"] == expected_stage, "stage-3 protocol has the wrong operation stage")
        require(record["required_infra_tasks"] == [], "stage-3 boundary cannot freeze infrastructure intake")
    else:
        require(record["required_infra_tasks"], "required infrastructure intake cannot be empty")
    require(not is_reviewed or not record["prerequisites"], "reviewed record has unmet prerequisites")
    if stage3_record(record):
        require(isinstance(record["external_prs"], list) and 2 <= len(record["external_prs"]) <= 16,
                "stage-3 boundary requires a bounded ordered set of external PRs")
    seen_numbers, seen_merges = set(), set()
    for external in external_prs(record):
        fields = {"number", "head_sha", "merge_commit_sha"}
        if stage3_record(record):
            fields |= {"branch", "goal_identity", "native_statement"}
        object_keys(external, fields, "external PR")
        require(type(external["number"]) is int and external["number"] > 0, "invalid external PR")
        for key in ("head_sha", "merge_commit_sha"):
            hex_value(external[key], 40, "invalid external PR commit")
        require(external["number"] not in seen_numbers and external["merge_commit_sha"] not in seen_merges,
                "duplicate external PR or merge")
        seen_numbers.add(external["number"])
        seen_merges.add(external["merge_commit_sha"])
        if stage3_record(record):
            require(external["goal_identity"] == record["current_goal_identity"], "external PR belongs to another native goal")
            require(isinstance(external["branch"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", external["branch"]),
                    "invalid external branch")
            statement = external["native_statement"]
            object_keys(statement, {"step_index", "text_sha256"}, "external native statement")
            require(type(statement["step_index"]) is int and statement["step_index"] > current["start_step_index"],
                    "external statement is not after its own native declaration")
            hex_value(statement["text_sha256"], 64, "invalid native statement digest")
    if later_intake_record(record):
        later = record["later_intake"]
        object_keys(later, {"historical_infra_notebook_sha256", "current_infra_notebook_sha256", "intake_pr"}, "later intake")
        for name in ("historical_infra_notebook_sha256", "current_infra_notebook_sha256"):
            if later[name] is not None or is_reviewed:
                hex_value(later[name], 64, f"invalid {name}")
        if later["historical_infra_notebook_sha256"] is not None and later["current_infra_notebook_sha256"] is not None:
            require(later["historical_infra_notebook_sha256"] != later["current_infra_notebook_sha256"],
                    "later intake requires distinct historical and current notebook digests")
        if later["current_infra_notebook_sha256"] is not None and record["fingerprints"].get("infra_notebook_sha256") is not None:
            require(later["current_infra_notebook_sha256"] == record["fingerprints"]["infra_notebook_sha256"],
                    "later intake current digest differs from live infra_notebook_sha256 fingerprint")
        intake_pr = later["intake_pr"]
        object_keys(intake_pr, {"number", "head_sha", "merge_commit_sha"}, "later intake PR")
        require(type(intake_pr["number"]) is int and intake_pr["number"] > 0, "invalid later intake PR")
        for key in ("head_sha", "merge_commit_sha"):
            hex_value(intake_pr[key], 40, "invalid later intake PR commit")
        require(intake_pr["number"] not in seen_numbers and intake_pr["merge_commit_sha"] not in seen_merges,
                "later intake PR duplicates external PR or merge")
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
                    ("schema_version", "run_id", "repository_key", "parent_version", "workflow_sha256", "historical_goal_identity", "required_infra_tasks"))
            and external_prs(release_record) == external_prs(record)
            and release_record.get("later_intake") == record.get("later_intake")
            and release_record.get("transition") == record.get("transition")
            and release_record.get("native_proof_mode") == record.get("native_proof_mode"), "release context changed")
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
        options = ({"external_prs": record["external_prs"], "github_repository": target["github_repository"],
                    "native_proof_mode": record["native_proof_mode"]}
                   if stage3_record(record) else {})
        return supervisor.native.reconciliation_evidence(target["root"], target["native_session_id"],
                                                         record["historical_goal_identity"], record["current_goal_identity"], **options)
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
        next_key = next((s["key"] for s in stages if s["stage"] == ledger["stage"] + 1), None)
        if stage3_record(record):
            require(helpers.workflow_stage_key(ledger) == "protein_examples" and next_key == "record_review"
                    and ledger["workflow"]["effective"]["parent_version"] == "1.0.0",
                    "stage-3 protocol requires the actual pinned v1 protein-examples to record-review transition")
        else:
            require(helpers.workflow_stage_key(ledger) == "resolve_review_findings" and next_key == "infrastructure",
                    "only review-remediation to infrastructure reconciliation is supported")
        receipt = decode(regular_bytes(directory / "completion.json"))
        from kg_microbe_workflows.closure import multi_pr_members
        members = multi_pr_members(receipt)
        if stage3_record(record):
            require(receipt.get("status") == "completed" and "prs" not in receipt and isinstance(receipt.get("pr"), dict),
                    "stage-3 historical closure requires its ordinary single-PR receipt")
            members = [receipt["pr"]]
        else:
            require(members and len(members) >= 2, "historical closure requires the ordinary ordered receipt")
        later = record["later_intake"] if later_intake_record(record) else None
        historical_infra = ((later["historical_infra_notebook_sha256"], later["current_infra_notebook_sha256"])
                            if later is not None else None)
        require(not helpers.validate_receipt(receipt, ledger, target, directory,
                                             historical_infra_notebook=historical_infra), "ordinary receipt validation failed")
        non_stage_prs = {p["number"] for p in external_prs(record)}
        if later is not None:
            non_stage_prs.add(later["intake_pr"]["number"])
        require(not non_stage_prs & {p["number"] for p in members},
                "external work cannot receive stage credit")
        verification = helpers.verify_remote_receipt(
            receipt, ledger, target, supervisor.runner, runtime=directory,
            historical_infra_notebook=historical_infra,
        )
        later_intake_verification = None
        if later is not None:
            intake_pr = later["intake_pr"]
            remote_intake = json.loads(
                supervisor.runner(["gh", "api", f"repos/{target['github_repository']}/pulls/{intake_pr['number']}"]).stdout
            )
            require(
                remote_intake.get("merged") is True
                and remote_intake.get("head", {}).get("sha") == intake_pr["head_sha"]
                and remote_intake.get("merge_commit_sha") == intake_pr["merge_commit_sha"]
                and remote_intake.get("base", {}).get("ref") == target["default_branch"]
                and remote_intake.get("base", {}).get("repo", {}).get("full_name", "").casefold()
                == target["github_repository"].casefold(),
                "later intake PR evidence differs",
            )
            def intake_ancestor(older, newer):
                return supervisor.runner(
                    ["git", "-C", target["root"], "merge-base", "--is-ancestor", older, newer],
                    check=False,
                ).returncode == 0
            require(
                intake_ancestor(verification["merge_commit_sha"], intake_pr["merge_commit_sha"])
                and intake_ancestor(intake_pr["merge_commit_sha"], "HEAD"),
                "later intake merge is unordered or absent from the default checkout",
            )
            intake_changes = helpers.commit_changes(target["root"], intake_pr["merge_commit_sha"], supervisor.runner)
            head_entry = helpers.tree_entry(target["root"], "HEAD", "INFRA_TASKS.md", supervisor.runner)
            require(
                set(intake_changes) == {"INFRA_TASKS.md"}
                and head_entry is not None
                and intake_changes["INFRA_TASKS.md"][1] == head_entry,
                "later intake commit must produce the current committed INFRA_TASKS.md",
            )
            from kg_microbe_workflows import validate_infra_notebook
            historical_raw = supervisor.runner(
                ["git", "-C", target["root"], "show", f"{receipt['pr']['head_sha']}:INFRA_TASKS.md"]
            ).stdout.encode()
            require(
                sha(historical_raw) == later["historical_infra_notebook_sha256"],
                "historical closure notebook bytes differ from approved digest",
            )
            historical_notebook = validate_infra_notebook(historical_raw, target["github_repository"])
            historical_pending = {t["task_id"] for t in historical_notebook["tasks"] if t["status"] != "resolved"}
            require(
                not (set(record["required_infra_tasks"]) <= historical_pending),
                "historical notebook already contains required intake; use 1.0.0",
            )
            later_intake_verification = {
                "number": intake_pr["number"],
                "head_sha": remote_intake["head"]["sha"],
                "merge_commit_sha": remote_intake["merge_commit_sha"],
                "merged": True,
                "historical_infra_notebook_sha256": later["historical_infra_notebook_sha256"],
                "current_infra_notebook_sha256": later["current_infra_notebook_sha256"],
            }
        external_verifications = []
        previous_external = None
        for external in external_prs(record):
            remote = json.loads(supervisor.runner(["gh", "api", f"repos/{target['github_repository']}/pulls/{external['number']}"]).stdout)
            require(remote.get("merged") is True and remote.get("head", {}).get("sha") == external["head_sha"]
                    and remote.get("merge_commit_sha") == external["merge_commit_sha"]
                    and remote.get("base", {}).get("repo", {}).get("full_name", "").casefold() == target["github_repository"].casefold(),
                    "external PR evidence differs")
            if stage3_record(record):
                require(remote.get("base", {}).get("ref") == target["default_branch"]
                        and remote.get("head", {}).get("ref") == external["branch"]
                        and remote.get("head", {}).get("repo", {}).get("full_name", "").casefold() == target["github_repository"].casefold(),
                        "external PR repository/base/branch differs")
                require(timestamp(record["current_goal_identity"]["started_at"]) <= timestamp(remote.get("created_at"))
                        <= timestamp(remote.get("merged_at")) <= timestamp(record["assessed_at"]),
                        "external PR chronology differs from its native goal")
                def ancestor(older, newer):
                    return supervisor.runner(["git", "-C", target["root"], "merge-base", "--is-ancestor", older, newer], check=False).returncode == 0
                require(ancestor(external["merge_commit_sha"], "HEAD"), "external merge is absent from the default checkout")
                if previous_external is not None:
                    require(timestamp(previous_external["merged_at"]) <= timestamp(remote["merged_at"])
                            and ancestor(previous_external["merge_commit_sha"], external["merge_commit_sha"]),
                            "external PR order is not verified")
            external_verifications.append({"number": external["number"], "head_sha": remote["head"]["sha"],
                "merge_commit_sha": remote["merge_commit_sha"], "merged": True,
                **({"goal_identity": external["goal_identity"], "native_statement": external["native_statement"],
                    "branch": external["branch"], "created_at": remote["created_at"], "merged_at": remote["merged_at"]}
                   if stage3_record(record) else {})})
            previous_external = remote
        # Ordinary advance is reused, but all its writes are captured until every
        # prerequisite and fresh native/fingerprint recheck has succeeded.
        previous_write = supervisor.write
        supervisor.write = lambda path, value: outputs.__setitem__(path, copy.deepcopy(value))
        try:
            ledger = supervisor.advance(target, ledger, receipt, verification, "reviewed_historical_native_completion")
        finally:
            supervisor.write = previous_write
        if stage3_record(record):
            require("infra_scope" not in ledger and ledger["stage"] == 4 and ledger["cycle"] == original["cycle"],
                    "stage-3 closure must hold exactly the record-review boundary")
        else:
            scope = ledger["infra_scope"]
            pending = {t["task_id"] for t in scope["tasks"] if t["status"] != "resolved"}
            require(set(record["required_infra_tasks"]) <= pending, "required intake is missing from the actual frozen notebook")
            notebook = Path(target["root"]) / "INFRA_TASKS.md"
            committed = supervisor.runner(["git", "-C", target["root"], "show", "HEAD:INFRA_TASKS.md"]).stdout.encode()
            require(committed == regular_bytes(notebook), "frozen intake is not the current committed notebook")
        ledger["completed_stages"][-1]["reconciliation_sha256"] = record_id
        entry: dict[str, Any] = {"assessment": record, "native_evidence": proof}
        if stage3_record(record):
            entry["external_pr_verifications"] = external_verifications
        else:
            entry["external_pr_verification"] = external_verifications[0]
        if later_intake_verification is not None:
            entry["later_intake_verification"] = later_intake_verification
        ledger.setdefault("historical_reconciliations", {})[record_id] = entry
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
