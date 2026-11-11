"""Native coordinator freshness adapter; no terminal transport or hook installer.

Only affirmative, receipt-bound permits can be consumed by a coordinator.
Missing native identity, changed/trust-blocked hooks, command failure and absent
ordinary closure verification hold. This cannot make Codex hook coverage complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .native_freshness import (
    NativeFreshnessError,
    frozen_workflow_sources,
    identity,
    path,
    read_reference,
    read_regular,
    request_adoption,
    require,
    sha,
    shape,
    unique_pairs,
    verify_observation_context,
)
from .native_runtime import uncached_command, verify_runtime

MAX_OUTPUT = 1_000_000


def observe(record: dict, request: dict, *, now: datetime | None = None) -> None:
    shape(
        record,
        {
            "schema_version",
            "kind",
            "repository_key",
            "repository_root",
            "native_identity",
            "observed_at",
            "expires_at",
            "state",
            "prompting",
            "inventory_consumed",
            "trusted_boundary_adapter",
            "evidence",
        },
        "native observation fields differ",
    )
    require(
        record["schema_version"] == "1.1.0" and record["kind"] == "verified_native_observation",
        "native observation is not authoritative",
    )
    require(
        record["repository_key"] == request["repository_key"]
        and record["repository_root"] == request["repository_root"]
        and identity(record["native_identity"])
        == identity(request["execution_context"]["native_identity"]),
        "native observation repository or identity differs",
    )
    try:
        start = datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise NativeFreshnessError("native observation timestamp malformed") from exc
    current = now or datetime.now(timezone.utc)
    require(
        start.tzinfo is not None
        and end.tzinfo is not None
        and start.utcoffset() == timezone.utc.utcoffset(start)
        and end.utcoffset() == timezone.utc.utcoffset(end)
        and start <= current < end
        and 0 < (end - start).total_seconds() <= 60,
        "native observation stale or has an unbounded lease",
    )
    require(
        record["state"] in {"active", "completed"}
        and record["prompting"] is False
        and record["trusted_boundary_adapter"] is True,
        "native session or adapter is not ready",
    )
    require(type(record["inventory_consumed"]) is bool, "native inventory observation is ambiguous")
    if request["phase"] == "pre_goal":
        require(
            record["state"] == "active" and record["inventory_consumed"] is False,
            "new native inventory cannot replace already consumed evidence",
        )
    elif request["phase"] == "resume_inventory":
        require(
            record["state"] == "active" and record["inventory_consumed"] is True,
            "native continuation is not the same consumed inventory",
        )
    else:
        require(record["state"] == "completed", "native closure has no completed goal observation")
    require(
        isinstance(record["evidence"], list) and 1 <= len(record["evidence"]) <= 32,
        "native observation has no source proof",
    )
    for reference in record["evidence"]:
        read_reference(reference)


def run_cli(command: list[str], *, timeout: float) -> dict:
    """Bounded process transport; no command string, input, signals or auth edits."""
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeFreshnessError("shared freshness CLI failed or timed out") from exc
    require(result.returncode == 0, "shared freshness CLI held or failed")
    require(len(result.stdout.encode()) <= MAX_OUTPUT, "shared freshness CLI output exceeds bound")
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise NativeFreshnessError("shared freshness CLI returned invalid JSON") from exc
    require(isinstance(value, dict), "shared freshness CLI returned invalid result")
    return value


def _request(reference: dict) -> dict:
    shape(reference, {"path", "sha256"}, "native request reference fields differ")
    raw = read_regular(path(reference["path"]))
    require(
        hashlib.sha256(raw).hexdigest() == sha(reference["sha256"]), "native request digest differs"
    )
    try:
        requests = json.loads(raw, object_pairs_hook=unique_pairs)
    except ValueError as exc:
        raise NativeFreshnessError("native request batch is malformed") from exc
    require(
        isinstance(requests, list) and len(requests) == 1 and isinstance(requests[0], dict),
        "native invocation requires exactly one shared batch member",
    )
    return requests[0]


def _one(result: dict) -> dict:
    # The public runner emits one results member even for a single request.
    if isinstance(result.get("results"), list):
        require(
            len(result["results"]) == 1 and result.get("status") == "verified",
            "shared freshness batch is incomplete or held",
        )
        result = result["results"][0]
    require(
        isinstance(result, dict) and result.get("status") == "verified",
        "shared freshness result is not verified",
    )
    return result


def gate(
    invocation_reference: dict,
    *,
    apply: bool = False,
    runner: Callable[..., dict] = run_cli,
    now: datetime | None = None,
) -> dict:
    """Verify a coordinator-owned invocation and emit only a scoped freshness permit.

    `request_adoption` supplies the operator trust boundary. The observation must
    be freshly supplied by the reviewed native observer; this function does not
    infer it from hook text. No result dispatches or acknowledges a native goal.
    """
    invocation = read_reference(invocation_reference)
    shape(
        invocation,
        {"schema_version", "kind", "request", "observation", "runtime"},
        "native invocation fields differ",
    )
    require(
        invocation["schema_version"] == "1.1.0"
        and invocation["kind"] == "native_freshness_invocation",
        "unsupported native invocation",
    )
    request = _request(invocation["request"])
    require(request.get("schema_version") == "1.1.0", "native request cannot use supervisor schema")
    request_adoption(request)
    observation = read_reference(invocation["observation"])
    observe(observation, request, now=now)
    adoption = read_reference(request["adoption"])
    cache_directory = path(invocation["runtime"]["cache_directory"])
    require(
        not cache_directory.is_relative_to(path(request["repository_root"])),
        "runtime caches must stay outside curated checkout",
    )
    executable = verify_runtime(
        invocation["runtime"], expected_release=adoption["canonical_release_commit"]
    )
    if not apply:
        return {
            "status": "preview",
            "reason": "no_execution_authority",
            "completion_authority": False,
        }
    arguments = ["-m", "kg_microbe_workflows.freshness_cli"]
    with uncached_command(
        executable,
        [*arguments, "run", "--request", invocation["request"]["path"], "--apply"],
        cache_directory,
    ) as command:
        result = _one(runner(command, timeout=90))
    verify_runtime(invocation["runtime"], expected_release=adoption["canonical_release_commit"])
    # Re-read the exact invocation, request and fresh observer after every command.
    require(
        read_reference(invocation_reference) == invocation
        and _request(invocation["request"]) == request,
        "native invocation changed during gate",
    )
    observe(read_reference(invocation["observation"]), request, now=now)
    expected = {
        "pre_goal": "verified_goal_inventory",
        "post_merge": "verified_post_merge_freshness",
        "no_change": "verified_no_change_freshness",
    }
    require(
        request.get("phase") in expected and result.get("kind") == expected[request["phase"]],
        "native gate phase differs",
    )
    artifact = read_reference(result.get("artifact"), limit=256_000_000)
    require(
        artifact.get("repository_key") == request["repository_key"]
        and artifact.get("boundary_id") == request["boundary_id"]
        and artifact.get("execution_context") == request["execution_context"]
        and artifact.get("adoption") == request["adoption"]
        and artifact.get("workflow_sha256") == request["workflow_sha256"]
        and artifact.get("effective_workflow") == request["effective_workflow"]
        and artifact.get("completion_authority") is False,
        "native gate artifact context differs",
    )
    if request["phase"] == "pre_goal":
        with uncached_command(
            executable,
            [*arguments, "verify", "--request", invocation["request"]["path"]],
            cache_directory,
        ) as command:
            verified = _one(runner(command, timeout=30))
        require(
            verified.get("artifact") == result["artifact"],
            "inventory verification differs from registered artifact",
        )
        verify_runtime(invocation["runtime"], expected_release=adoption["canonical_release_commit"])
        observe(read_reference(invocation["observation"]), request, now=now)
    else:
        require(
            artifact.get("prior_inventory") == request["prior_inventory"],
            "native closure inventory differs",
        )
    return {
        "status": "permit",
        "scope": "inventory" if request["phase"] == "pre_goal" else "closure_freshness_only",
        "boundary_id": request["boundary_id"],
        "artifact": result["artifact"],
        "execution_context": request["execution_context"],
        "completion_authority": False,
        "native_input_sent": False,
        "next_goal_authority": False,
    }


def continue_inventory(
    request_reference: dict,
    observation_reference: dict,
    inventory_reference: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Same native goal consumes its retained inventory without refetch/refreeze.

    Feature work may have moved HEAD since initial inventory. This verifies the
    original immutable artifact and frozen execution sources, not a new source
    inventory or another goal's eligibility.
    """
    from .freshness import digest

    request = _request(request_reference)
    require(request.get("phase") == "pre_goal", "continuation requires original pre-goal request")
    request_adoption(request)
    observation = read_reference(observation_reference)
    observe(observation, {**request, "phase": "resume_inventory"}, now=now)
    artifact = read_reference(inventory_reference, limit=256_000_000)
    require(
        artifact.get("kind") == "verified_goal_inventory"
        and artifact.get("repository_key") == request["repository_key"]
        and artifact.get("boundary_id") == request["boundary_id"]
        and artifact.get("adoption") == request["adoption"]
        and artifact.get("execution_context") == request["execution_context"]
        and artifact.get("adoption") == request["adoption"]
        and artifact.get("workflow_sha256") == request["workflow_sha256"]
        and artifact.get("effective_workflow") == request["effective_workflow"],
        "native continuation inventory context differs",
    )
    slot = (
        path(request["receipt_directory"])
        / "index"
        / request["repository_key"]
        / (digest(request["boundary_id"]) + ".json")
    )
    raw = read_regular(slot)
    require(
        json.loads(raw, object_pairs_hook=unique_pairs) == inventory_reference,
        "native continuation inventory is not registered",
    )
    verify_observation_context(
        artifact,
        root=path(request["repository_root"]),
        key=request["repository_key"],
        adoption=read_reference(request["adoption"]),
        phase="pre_goal",
    )
    frozen_workflow_sources(
        request["effective_workflow"],
        root=path(request["repository_root"]),
        key=request["repository_key"],
        repository=read_reference(request["adoption"])["github_repository"],
        workflow_sha256=request["workflow_sha256"],
    )
    return {
        "status": "permit",
        "scope": "retained_inventory",
        "artifact": inventory_reference,
        "execution_context": request["execution_context"],
        "completion_authority": False,
        "next_goal_authority": False,
        "native_input_sent": False,
    }


def hook_feedback(event: str, permit: dict | None) -> dict:
    """Supported hook feedback only; never approval/trust or complete coverage."""
    allowed = (
        isinstance(permit, dict)
        and permit.get("status") == "permit"
        and permit.get("scope") == "inventory"
    )
    if event == "PreToolUse":
        if allowed:
            return {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": "Native freshness inventory permit verified; ordinary permission checks still apply.",
                }
            }
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": "Native freshness boundary is held.",
            }
        }
    if event in {"UserPromptSubmit", "Stop"}:
        # A freshness receipt cannot acknowledge closure. Stop stays held until
        # the external coordinator proves ordinary closure independently.
        return {
            "continue": bool(allowed and event == "UserPromptSubmit"),
            "stopReason": "Native coordinator boundary requires verified freshness and ordinary closure.",
        }
    raise NativeFreshnessError("event is not an enforceable boundary adapter event")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify an explicit native coordinator freshness boundary"
    )
    parser.add_argument("--invocation", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = gate({"path": str(args.invocation), "sha256": args.sha256}, apply=args.apply)
    except (NativeFreshnessError, OSError, ValueError, TypeError, KeyError):
        result = {
            "status": "hold",
            "reason": "native_boundary_verification_failed",
            "completion_authority": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "permit" else 3 if result["status"] == "preview" else 2


if __name__ == "__main__":
    raise SystemExit(main())
