"""Explicit native goal context for the shared freshness gate.

This module verifies an operator-pinned boundary; it never discovers a thread
from a terminal title or resume-last, installs hooks, sends input or completes a
goal. Native observations and ordinary closure verification remain the trusted
coordinator's responsibility. A freshness receipt has no completion authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import WorkflowError, _validator, load_document
from .freshness import verify_saved_receipt
from .freshness_contract import contract_sha256, repository_identity

LIMIT = 1_000_000
NATIVE_POLICY = Path(__file__).parent / "templates/native-repository-freshness-v1.yaml"
NATIVE_SCHEMA = Path(__file__).parent / "schema/native-repository-freshness-v1.yaml"
IDENTITY_FIELDS = {"client", "session_id", "goal_id", "binary_sha256"}
CLOSURE_REQUIREMENTS = frozenset(
    {
        "exact_head_review",
        "evidence_verification",
        "issue_resolution",
        "cleanup_verification",
        "publication_verification",
        "no_change_verification",
    }
)


class NativeFreshnessError(WorkflowError):
    """No native boundary authority can be established; preserve all state."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise NativeFreshnessError(reason)


def shape(value: Any, fields: set[str] | frozenset[str], reason: str) -> dict:
    require(isinstance(value, dict) and set(value) == fields, reason)
    return value


def sha(value: Any, width: int = 64) -> str:
    require(
        isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(width) + "}", value) is not None,
        "native digest must be complete lowercase hex",
    )
    return value


def text(value: Any) -> str:
    require(
        isinstance(value, str)
        and bool(value)
        and len(value) <= 512
        and not any(ord(c) < 32 or ord(c) == 127 for c in value),
        "unsafe native identity text",
    )
    return value


def path(value: Any) -> Path:
    require(isinstance(value, str), "native path must be explicit text")
    result = Path(value)
    require(
        result.is_absolute() and result.resolve() == result, "native path aliases another location"
    )
    return result


def read_regular(value: Path, *, limit: int = LIMIT) -> bytes:
    value = path(str(value))
    try:
        descriptor = os.open(value, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(info.st_mode) and info.st_size <= limit,
                "native input is not a bounded regular file",
            )
            raw = stream.read(limit + 1)
        require(len(raw) <= limit, "native input exceeds byte bound")
        return raw
    except OSError as exc:
        raise NativeFreshnessError("native input unavailable") from exc


def unique_pairs(items: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "duplicate native JSON key")
        result[key] = value
    return result


def read_reference(reference: Any, *, limit: int = LIMIT) -> dict:
    shape(reference, {"path", "sha256"}, "native reference shape differs")
    raw = read_regular(path(reference["path"]), limit=limit)
    require(
        hashlib.sha256(raw).hexdigest() == sha(reference["sha256"]),
        "native reference digest differs",
    )
    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise NativeFreshnessError("native reference is not valid JSON") from exc
    require(isinstance(value, dict), "native reference must name an object")
    return value


def validate_shape(value: dict, class_name: str) -> None:
    errors = list(_validator(read_regular(NATIVE_SCHEMA).decode(), class_name).iter_errors(value))
    require(not errors, "native structured contract shape differs")


def identity(value: Any) -> dict:
    shape(value, IDENTITY_FIELDS, "native identity fields differ")
    require(value["client"] == "codex", "native client is not supported")
    for field in ("session_id", "goal_id"):
        text(value[field])
        require(
            value[field].strip() == value[field]
            and value[field].lower() not in {"last", "--last", "unknown", "unverified", "none"},
            "native identity is inferred or unverified",
        )
    sha(value["binary_sha256"])
    return value


def approval(value: Any) -> None:
    shape(value, {"record_id", "approved_at", "approved_by"}, "native approval fields differ")
    text(value["record_id"])
    text(value["approved_by"])
    try:
        when = datetime.fromisoformat(text(value["approved_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise NativeFreshnessError("native approval timestamp invalid") from exc
    require(
        when.tzinfo is not None
        and when.utcoffset() == timezone.utc.utcoffset(when)
        and when <= datetime.now(timezone.utc),
        "native approval timestamp is not past UTC",
    )


def policy_sha256() -> str:
    raw = read_regular(NATIVE_POLICY)
    policy = load_document(raw)
    expected = {
        "schema_version": "1.1.0",
        "id": "native-repository-freshness",
        "version": "1.0.0",
        "base_contract_sha256": contract_sha256(),
        "activation_boundary": "verified_native_goal_boundary",
        "reuse_inventory_within_goal": True,
        "require_predecessor_closure": True,
        "completion_authority": False,
        "candidate_authority": "proposal_only",
    }
    require(policy == expected, "native policy differs from the compatible governed extension")
    return hashlib.sha256(raw).hexdigest()


def load_execution(contract_path: Path, *, root: Path, repository_key: str) -> dict:
    """Derive the complete native execution snapshot from its closed source manifest.

    Sources are the native execution contract and every instruction it explicitly
    executes. This never manufactures a cyclic Mech profile or stage list.
    """
    root = path(str(root))
    contract_path = path(str(contract_path))
    raw = read_regular(contract_path)
    contract = load_document(raw)
    validate_shape(contract, "NativeGoalExecution")
    shape(
        contract,
        {
            "schema_version",
            "kind",
            "repository_key",
            "github_repository",
            "closure_requirements",
            "instructions",
        },
        "native execution contract fields differ",
    )
    require(
        contract["schema_version"] == "1.1.0" and contract["kind"] == "native_goal_execution",
        "unsupported native execution contract",
    )
    require(
        contract["repository_key"] == repository_key
        and contract["github_repository"] == repository_identity(repository_key),
        "native execution repository differs",
    )
    requirements = shape(
        contract["closure_requirements"],
        CLOSURE_REQUIREMENTS,
        "native ordinary closure requirements incomplete",
    )
    require(
        all(value is True for value in requirements.values()),
        "native ordinary closure requirement weakened",
    )
    instructions = contract["instructions"]
    require(
        isinstance(instructions, list) and 1 <= len(instructions) <= 32,
        "native execution requires a bounded complete instruction list",
    )
    sources = [
        {
            "path": str(contract_path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "kind": "native_execution",
        }
    ]
    sources.append(
        {
            "path": str(NATIVE_SCHEMA),
            "sha256": hashlib.sha256(read_regular(NATIVE_SCHEMA)).hexdigest(),
            "kind": "native_schema",
        }
    )
    seen = {contract_path, NATIVE_SCHEMA}
    for entry in instructions:
        shape(entry, {"path", "sha256"}, "native instruction reference fields differ")
        relative = Path(text(entry["path"]))
        require(
            not relative.is_absolute() and ".." not in relative.parts and str(relative) != ".",
            "native instruction path escapes owned checkout",
        )
        source = path(str(root / relative))
        require(
            source.is_relative_to(root) and source not in seen,
            "native instruction duplicated or outside checkout",
        )
        content = read_regular(source)
        require(
            hashlib.sha256(content).hexdigest() == sha(entry["sha256"]),
            "native instruction changed",
        )
        sources.append(
            {"path": str(source), "sha256": entry["sha256"], "kind": "native_instruction"}
        )
        seen.add(source)
    return {
        "schema_version": "1.1.0",
        "kind": "native_goal_execution",
        "repository_key": repository_key,
        "github_repository": repository_identity(repository_key),
        "closure_requirements": dict(requirements),
        "sources": sources,
    }


def execution_sha256(effective: dict) -> str:
    """Native 1.1 domain; never the supervisor workflow hash or receipt digest."""
    raw = json.dumps(effective, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(b"native-goal-execution-v1.1.0\0" + raw).hexdigest()


def verify_effective(
    reference: Any, *, root: Path, repository_key: str, expected_digest: str
) -> dict:
    effective = read_reference(reference)
    require(
        effective.get("kind") == "native_goal_execution",
        "effective contract is not native standalone",
    )
    sources = effective.get("sources")
    if not isinstance(sources, list) or not sources:
        raise NativeFreshnessError("native effective source list missing")
    contracts = [
        source
        for source in sources
        if isinstance(source, dict) and source.get("kind") == "native_execution"
    ]
    require(len(contracts) == 1, "native effective contract source is not unique")
    recomputed = load_execution(
        path(contracts[0]["path"]), root=root, repository_key=repository_key
    )
    require(
        recomputed == effective and execution_sha256(recomputed) == sha(expected_digest),
        "native effective snapshot is incomplete or changed",
    )
    return recomputed


def verify_observation_context(
    artifact: dict, *, root: Path, key: str, adoption: dict, phase: str
) -> None:
    """Authenticate an observation and bind it to its enclosing native artifact.

    This is a historical consistency check, not a new fetch or a re-freeze of
    active evidence. The enclosing approved operator record owns acceptance.
    """
    require(phase in {"pre_goal", "post_merge"}, "native observation phase unsupported")
    receipt = artifact.get("freshness")
    if not isinstance(receipt, dict):
        raise NativeFreshnessError("native observation missing")
    verify_saved_receipt(receipt)
    require(
        receipt.get("schema_version") == "1.0.0"
        and receipt.get("repository_key") == key
        and receipt.get("repository") == repository_identity(key)
        and receipt.get("checkout") == str(root)
        and receipt.get("remote") == "origin"
        and receipt.get("boundary_id") == artifact.get("boundary_id")
        and receipt.get("boundary_id") == adoption["boundary"]["id"]
        and receipt.get("policy_sha256") == adoption["contract_sha256"]
        and receipt.get("phase") == phase
        and receipt.get("status") == "verified"
        and receipt.get("apply") is True,
        "native observation context differs",
    )
    head = sha(receipt.get("after"), 40)
    require(receipt.get("fetched") == head, "native observation revision differs")
    text(receipt.get("default_branch"))
    if phase == "pre_goal":
        require(
            artifact.get("head") == head and receipt.get("merge_commits") == [],
            "native inventory observation revision or merge claims differ",
        )
    else:
        merges = artifact.get("merges")
        if not isinstance(merges, list) or not 1 <= len(merges) <= 32:
            raise NativeFreshnessError("native merge observation list missing")
        commits = []
        numbers = set()
        for merged in merges:
            shape(
                merged,
                {"number", "head_sha", "merge_commit_sha", "base", "merged_at"},
                "native merge observation fields differ",
            )
            require(
                type(merged["number"]) is int
                and merged["number"] > 0
                and merged["number"] not in numbers,
                "native merge observation number differs",
            )
            numbers.add(merged["number"])
            sha(merged["head_sha"], 40)
            commits.append(sha(merged["merge_commit_sha"], 40))
            text(merged["merged_at"])
            require(
                merged["base"] == receipt["default_branch"],
                "native merge observation default branch differs",
            )
        require(receipt.get("merge_commits") == commits, "native merge observation commits differ")


def _historical_adoption(artifact: dict, *, key: str, root: Path, previous: dict) -> dict:
    """Bind retained adoption without re-evaluating historical source files."""
    adopted = read_reference(artifact.get("adoption"), limit=65536)
    validate_shape(adopted, "NativeFreshnessAdoption")
    require(
        adopted.get("schema_version") == "1.1.0"
        and adopted.get("authority") == "approved_native_boundary_adoption"
        and adopted.get("repository_key") == key
        and adopted.get("github_repository") == repository_identity(key)
        and adopted.get("repository_root") == str(root)
        and identity(adopted.get("native_identity")) == previous
        and adopted.get("contract_sha256") == contract_sha256()
        and adopted.get("native_contract_sha256") == policy_sha256()
        and adopted.get("boundary", {}).get("id") == artifact.get("boundary_id")
        and adopted.get("boundary", {}).get("workflow_sha256") == artifact.get("workflow_sha256"),
        "native predecessor adopted context differs",
    )
    sha(adopted["canonical_release_commit"], 40)
    approval(adopted["approval"])
    effective = read_reference(artifact.get("effective_workflow"))
    require(
        execution_sha256(effective) == sha(artifact.get("workflow_sha256")),
        "native predecessor effective contract differs",
    )
    return adopted


def verify_predecessor(value: Any, *, key: str, root: Path, current_identity: dict) -> None:
    shape(value, {"kind", "reference"}, "native predecessor shape differs")
    record = read_reference(value["reference"])
    common = {
        "schema_version",
        "authority",
        "repository_key",
        "repository_root",
        "native_identity",
        "approval",
        "evidence",
    }
    if value["kind"] == "initial_assessment":
        shape(record, common | {"no_inventory_consumed"}, "native initial assessment fields differ")
        require(
            record["authority"] == "operator_verified_initial_native_boundary"
            and record["no_inventory_consumed"] is True,
            "native initial boundary not verified",
        )
        require(
            identity(record["native_identity"]) == current_identity,
            "native initial identity differs",
        )
    elif value["kind"] == "verified_closure":
        shape(
            record,
            common | {"goal_status", "freshness_closure", "ordinary_closure"},
            "native predecessor closure fields differ",
        )
        require(
            record["authority"] == "operator_verified_native_goal_closure"
            and record["goal_status"] == "completed",
            "native predecessor is not verified complete",
        )
        previous = identity(record["native_identity"])
        require(
            previous["client"] == current_identity["client"]
            and previous["session_id"] == current_identity["session_id"]
            and previous["goal_id"] != current_identity["goal_id"],
            "native predecessor identity differs or is replayed",
        )
        fresh = read_reference(record["freshness_closure"], limit=256_000_000)
        require(
            fresh.get("kind") in {"verified_post_merge_freshness", "verified_no_change_freshness"}
            and fresh.get("repository_key") == key
            and fresh.get("completion_authority") is False
            and fresh.get("execution_context")
            == {"kind": "native_standalone", "native_identity": previous},
            "native predecessor lacks closure freshness",
        )
        prior = read_reference(fresh.get("prior_inventory"), limit=256_000_000)
        require(
            prior.get("kind") == "verified_goal_inventory"
            and prior.get("boundary_id") == fresh.get("boundary_id")
            and prior.get("repository_key") == key
            and prior.get("adoption") == fresh.get("adoption")
            and prior.get("execution_context") == fresh.get("execution_context")
            and prior.get("effective_workflow") == fresh.get("effective_workflow"),
            "native predecessor inventory context differs",
        )
        require(
            prior.get("schema_version") == "1.1.0"
            and fresh.get("schema_version") == "1.1.0"
            and prior.get("completion_authority") is False
            and prior.get("workflow_sha256") == fresh.get("workflow_sha256"),
            "native predecessor artifact contract differs",
        )
        adopted = _historical_adoption(prior, key=key, root=root, previous=previous)
        verify_observation_context(prior, root=root, key=key, adoption=adopted, phase="pre_goal")
        if fresh["kind"] == "verified_post_merge_freshness":
            verify_observation_context(
                fresh, root=root, key=key, adoption=adopted, phase="post_merge"
            )
        else:
            require(
                fresh.get("head") == prior.get("head"),
                "native no-change predecessor changed its inventory head",
            )
        ordinary = read_reference(record["ordinary_closure"])
        require(
            ordinary.get("native_identity") == previous
            and ordinary.get("repository_key") == key
            and ordinary.get("kind") == "native_ordinary_closure_evidence"
            and ordinary.get("prior_inventory") == fresh.get("prior_inventory")
            and ordinary.get("freshness_closure") == record["freshness_closure"],
            "ordinary native closure evidence identity differs",
        )
        require(
            isinstance(ordinary.get("evidence"), dict)
            and set(ordinary["evidence"]) == CLOSURE_REQUIREMENTS,
            "ordinary native closure evidence incomplete",
        )
        for proof in ordinary["evidence"].values():
            read_reference(proof)
    else:
        raise NativeFreshnessError("unknown native predecessor kind")
    require(
        record["schema_version"] == "1.1.0"
        and record["repository_key"] == key
        and record["repository_root"] == str(root),
        "native predecessor repository differs",
    )
    approval(record["approval"])
    require(
        isinstance(record["evidence"], list) and 1 <= len(record["evidence"]) <= 32,
        "native predecessor has no evidence",
    )
    for proof in record["evidence"]:
        read_reference(proof)


def load_adoption(
    reference: Any,
    *,
    repository_key: str,
    root: Path,
    native_identity: Any,
    boundary_id: str,
    workflow_sha256: str,
) -> dict:
    """Validate one exact operator-approved native boundary, with no cycle fields."""
    record = read_reference(reference, limit=65536)
    validate_shape(record, "NativeFreshnessAdoption")
    shape(
        record,
        {
            "schema_version",
            "authority",
            "repository_key",
            "github_repository",
            "repository_root",
            "canonical_release_commit",
            "contract_sha256",
            "native_contract_sha256",
            "native_identity",
            "boundary",
            "approval",
        },
        "native adoption fields differ",
    )
    require(
        record["schema_version"] == "1.1.0"
        and record["authority"] == "approved_native_boundary_adoption",
        "native proposal has no adoption authority",
    )
    require(
        record["repository_key"] == repository_key
        and record["github_repository"] == repository_identity(repository_key)
        and record["repository_root"] == str(path(str(root))),
        "native adoption repository differs",
    )
    sha(record["canonical_release_commit"], 40)
    require(
        record["contract_sha256"] == contract_sha256()
        and record["native_contract_sha256"] == policy_sha256(),
        "native adoption policy differs from installed extension",
    )
    current = identity(native_identity)
    require(identity(record["native_identity"]) == current, "native adoption identity differs")
    boundary = shape(
        record["boundary"],
        {"id", "workflow_sha256", "predecessor"},
        "native boundary fields differ",
    )
    require(
        boundary["id"] == text(boundary_id) and boundary["workflow_sha256"] == sha(workflow_sha256),
        "native boundary or workflow differs",
    )
    verify_predecessor(
        boundary["predecessor"], key=repository_key, root=root, current_identity=current
    )
    approval(record["approval"])
    return record


def frozen_workflow_sources(
    reference: Any, *, root: Path, key: str, repository: str, workflow_sha256: str
) -> dict[str, str]:
    """Native counterpart of the shared CLI's complete frozen-source guard."""
    root = path(str(root))
    require(repository == repository_identity(key), "native canonical repository differs")
    shape(reference, {"path", "sha256"}, "native effective reference shape differs")
    snapshot = path(reference["path"])
    require(
        snapshot != root and not snapshot.is_relative_to(root),
        "native effective snapshot must be outside curated checkout",
    )
    effective = verify_effective(
        reference, root=root, repository_key=key, expected_digest=workflow_sha256
    )
    return {
        str(path(source["path"]).relative_to(root)): source["sha256"]
        for source in effective["sources"]
        if path(source["path"]).is_relative_to(root)
    }


def request_adoption(request: dict[str, Any]) -> dict:
    context = shape(
        request["execution_context"],
        {"kind", "native_identity"},
        "native request context fields differ",
    )
    require(context["kind"] == "native_standalone", "native request context kind differs")
    return load_adoption(
        request["adoption"],
        repository_key=request["repository_key"],
        root=path(request["repository_root"]),
        native_identity=context["native_identity"],
        boundary_id=request["boundary_id"],
        workflow_sha256=request["workflow_sha256"],
    )
