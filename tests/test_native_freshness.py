"""Offline native context regressions; no native client or provider is invoked."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from kg_microbe_workflows import native_boundary_adapter as adapter
from kg_microbe_workflows import native_freshness as native
from kg_microbe_workflows.freshness import digest
from kg_microbe_workflows.freshness_contract import contract_sha256, load_adoption


def reference(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def case(tmp_path, monkeypatch):
    # Runtime provenance is exercised with a real venv in test_native_runtime.py.
    monkeypatch.setattr(
        adapter, "verify_runtime", lambda runtime, **kwargs: Path(runtime["python"])
    )
    root = tmp_path / "owned"
    root.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    instruction = root / "CLOSURE.md"
    instruction.write_text("Review exact head, evidence, issues and cleanup.\n")
    contract = root / "native-execution.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.1.0",
                "kind": "native_goal_execution",
                "repository_key": "claw",
                "github_repository": "CultureBotAI/culturebotai-claw",
                "closure_requirements": dict.fromkeys(native.CLOSURE_REQUIREMENTS, True),
                "instructions": [
                    {
                        "path": "CLOSURE.md",
                        "sha256": hashlib.sha256(instruction.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )
    effective = native.load_execution(contract, root=root, repository_key="claw")
    effective_ref = reference(evidence / "effective.json", effective)
    who = {
        "client": "codex",
        "session_id": "fixture-session",
        "goal_id": "fixture-goal",
        "binary_sha256": "a" * 64,
    }
    approved = {
        "record_id": "fixture-approval",
        "approved_at": "2026-01-01T00:00:00Z",
        "approved_by": "fixture-operator",
    }
    source = reference(
        evidence / "observation-source.json", {"test_only": True, "observed_goal": who}
    )
    initial = reference(
        evidence / "initial.json",
        {
            "schema_version": "1.1.0",
            "authority": "operator_verified_initial_native_boundary",
            "repository_key": "claw",
            "repository_root": str(root),
            "native_identity": who,
            "approval": approved,
            "evidence": [source],
            "no_inventory_consumed": True,
        },
    )
    adoption = {
        "schema_version": "1.1.0",
        "authority": "approved_native_boundary_adoption",
        "repository_key": "claw",
        "github_repository": "CultureBotAI/culturebotai-claw",
        "repository_root": str(root),
        "canonical_release_commit": "b" * 40,
        "contract_sha256": contract_sha256(),
        "native_contract_sha256": native.policy_sha256(),
        "native_identity": who,
        "boundary": {
            "id": "native-boundary-fixture",
            "workflow_sha256": native.execution_sha256(effective),
            "predecessor": {"kind": "initial_assessment", "reference": initial},
        },
        "approval": approved,
    }
    adoption_ref = reference(evidence / "adoption.json", adoption)
    request = {
        "schema_version": "1.1.0",
        "repository_key": "claw",
        "repository_root": str(root),
        "lock_directory": str(evidence / "locks"),
        "receipt_directory": str(evidence / "receipts"),
        "protected_roots": [],
        "adoption": adoption_ref,
        "boundary_id": "native-boundary-fixture",
        "phase": "pre_goal",
        "workflow_sha256": native.execution_sha256(effective),
        "effective_workflow": effective_ref,
        "prior_inventory": None,
        "pull_requests": [],
        "execution_context": {"kind": "native_standalone", "native_identity": who},
    }
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    observation = {
        "schema_version": "1.1.0",
        "kind": "verified_native_observation",
        "repository_key": "claw",
        "repository_root": str(root),
        "native_identity": who,
        "observed_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=30)).isoformat(),
        "state": "active",
        "prompting": False,
        "inventory_consumed": False,
        "trusted_boundary_adapter": True,
        "evidence": [source],
    }
    python = Path(sys.executable).resolve()
    release = reference(
        evidence / "release.json",
        {"source_commit": "b" * 40, "status": "verified", "test_only": True},
    )
    invocation = {
        "schema_version": "1.1.0",
        "kind": "native_freshness_invocation",
        "request": reference(evidence / "request.json", [request]),
        "observation": reference(evidence / "observation.json", observation),
        "runtime": {
            "python": str(python),
            "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
            "canonical_release_commit": "b" * 40,
            "cache_directory": str(evidence / "runtime-cache"),
            "release_proof": release,
        },
    }
    return dict(
        root=root,
        evidence=evidence,
        contract=contract,
        instruction=instruction,
        effective=effective,
        effective_ref=effective_ref,
        who=who,
        adoption=adoption,
        adoption_ref=adoption_ref,
        request=request,
        now=now,
        observation=observation,
        invocation=invocation,
    )


def test_native_context_has_no_supervisor_coordinates(case):
    result = native.request_adoption(case["request"])
    assert result["native_identity"] == case["who"]
    assert not {"cycle", "stage", "run_id"} & set(result["boundary"])
    with pytest.raises(Exception, match="fields|proposal"):
        load_adoption(
            Path(case["adoption_ref"]["path"]),
            expected_sha256=case["adoption_ref"]["sha256"],
            repository_key="claw",
            repository_root=case["root"],
            workflow_sha256=native.execution_sha256(case["effective"]),
            run_id="fabricated",
            cycle=1,
            predecessor_receipt_sha256=None,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "--last"),
        ("session_id", "unknown"),
        ("goal_id", "none"),
        ("goal_id", "fixture-other"),
        ("binary_sha256", "c" * 64),
    ],
)
def test_identity_mismatch_or_inference_holds(case, field, value):
    request = copy.deepcopy(case["request"])
    request["execution_context"]["native_identity"][field] = value
    with pytest.raises(native.NativeFreshnessError):
        native.request_adoption(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("authority", "proposal_only"),
        ("schema_version", "1.0.0"),
        ("native_contract_sha256", "0" * 64),
        ("contract_sha256", "0" * 64),
        ("github_repository", "untrusted/repo"),
    ],
)
def test_native_adoption_cannot_weaken_or_substitute_policy(case, field, value):
    record = copy.deepcopy(case["adoption"])
    record[field] = value
    request = copy.deepcopy(case["request"])
    request["adoption"] = reference(case["evidence"] / "changed-adoption.json", record)
    with pytest.raises(native.NativeFreshnessError):
        native.request_adoption(request)


def test_complete_native_sources_and_unchanged_snapshot(case):
    original = Path(case["effective_ref"]["path"]).read_bytes()
    paths = native.frozen_workflow_sources(
        case["effective_ref"],
        root=case["root"],
        key="claw",
        repository="CultureBotAI/culturebotai-claw",
        workflow_sha256=native.execution_sha256(case["effective"]),
    )
    assert set(paths) == {"native-execution.yaml", "CLOSURE.md"}
    assert Path(case["effective_ref"]["path"]).read_bytes() == original
    case["instruction"].write_text("Changed instructions!")
    with pytest.raises(native.NativeFreshnessError, match="changed"):
        native.frozen_workflow_sources(
            case["effective_ref"],
            root=case["root"],
            key="claw",
            repository="CultureBotAI/culturebotai-claw",
            workflow_sha256=native.execution_sha256(case["effective"]),
        )


def test_cannot_omit_effective_instruction_source(case):
    incomplete = copy.deepcopy(case["effective"])
    incomplete["sources"].pop()
    ref = reference(case["evidence"] / "incomplete.json", incomplete)
    with pytest.raises(native.NativeFreshnessError, match="incomplete|changed"):
        native.frozen_workflow_sources(
            ref,
            root=case["root"],
            key="claw",
            repository="CultureBotAI/culturebotai-claw",
            workflow_sha256=native.execution_sha256(incomplete),
        )


def test_snapshot_inside_checkout_holds(case):
    ref = reference(case["root"] / "snapshot.json", case["effective"])
    with pytest.raises(native.NativeFreshnessError, match="outside"):
        native.frozen_workflow_sources(
            ref,
            root=case["root"],
            key="claw",
            repository="CultureBotAI/culturebotai-claw",
            workflow_sha256=native.execution_sha256(case["effective"]),
        )


def test_instruction_symlink_or_escape_holds(case):
    case["instruction"].unlink()
    case["instruction"].symlink_to(case["contract"])
    with pytest.raises(native.NativeFreshnessError, match="aliases"):
        native.load_execution(case["contract"], root=case["root"], repository_key="claw")


def test_unknown_synthetic_boundary_fields_hold(case):
    record = copy.deepcopy(case["adoption"])
    record["boundary"].update(cycle=1, stage=1, run_id="fake")
    request = copy.deepcopy(case["request"])
    request["adoption"] = reference(case["evidence"] / "bad-context.json", record)
    with pytest.raises(native.NativeFreshnessError, match="fields|shape"):
        native.request_adoption(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "paused"),
        ("state", "failed"),
        ("prompting", True),
        ("trusted_boundary_adapter", False),
        ("inventory_consumed", True),
        ("expires_at", "2026-01-01T00:00:00Z"),
    ],
)
def test_native_observation_holds(case, field, value):
    observation = copy.deepcopy(case["observation"])
    observation[field] = value
    with pytest.raises(native.NativeFreshnessError):
        adapter.observe(observation, case["request"], now=case["now"])


def test_automatic_continuation_cannot_refreeze_consumed_inventory(case):
    observation = copy.deepcopy(case["observation"])
    observation["inventory_consumed"] = True
    with pytest.raises(native.NativeFreshnessError, match="consumed"):
        adapter.observe(observation, case["request"], now=case["now"])


def successful_runner(case, calls, *, changed_artifact=False):
    request = case["request"]
    artifact = {
        "repository_key": "claw",
        "boundary_id": request["boundary_id"],
        "execution_context": request["execution_context"],
        "effective_workflow": request["effective_workflow"],
        "adoption": request["adoption"],
        "workflow_sha256": request["workflow_sha256"],
        "completion_authority": False,
        "kind": "verified_goal_inventory",
    }
    if changed_artifact:
        artifact["boundary_id"] = "another-boundary"
    ref = reference(case["evidence"] / "result.json", artifact)

    def run(command, *, timeout):
        calls.append((command, timeout))
        return {"status": "verified", "kind": "verified_goal_inventory", "artifact": ref}

    return run


def test_adapter_requires_run_then_verify_before_inventory(case):
    calls = []
    invocation = reference(case["evidence"] / "invocation.json", case["invocation"])
    result = adapter.gate(
        invocation, apply=True, runner=successful_runner(case, calls), now=case["now"]
    )
    assert [next(part for part in call if part in {"run", "verify"}) for call, _ in calls] == [
        "run",
        "verify",
    ]
    assert calls[0][0][-1] == "--apply"
    assert result["scope"] == "inventory" and result["completion_authority"] is False
    assert result["native_input_sent"] is False and result["next_goal_authority"] is False


def test_adapter_preview_never_invokes_cli(case):
    invocation = reference(case["evidence"] / "invocation.json", case["invocation"])

    def forbidden(*args, **kwargs):
        raise AssertionError("No CLI for a preview")

    assert adapter.gate(invocation, runner=forbidden, now=case["now"])["status"] == "preview"


def test_mismatched_receipt_cannot_permit_inventory(case):
    invocation = reference(case["evidence"] / "invocation.json", case["invocation"])
    with pytest.raises(native.NativeFreshnessError, match="context"):
        adapter.gate(
            invocation,
            apply=True,
            runner=successful_runner(case, [], changed_artifact=True),
            now=case["now"],
        )


def test_failed_or_timed_out_cli_never_permits(case):
    invocation = reference(case["evidence"] / "invocation.json", case["invocation"])

    def failed(*args, **kwargs):
        raise native.NativeFreshnessError("timeout")

    with pytest.raises(native.NativeFreshnessError, match="timeout"):
        adapter.gate(invocation, apply=True, runner=failed, now=case["now"])


def test_hook_holds_do_not_approve_prompts_or_trigger_continuations():
    assert (
        adapter.hook_feedback("PreToolUse", None)["hookSpecificOutput"]["permissionDecision"]
        == "deny"
    )
    assert adapter.hook_feedback("Stop", None)["continue"] is False
    with pytest.raises(native.NativeFreshnessError):
        adapter.hook_feedback("PermissionRequest", None)
    with pytest.raises(native.NativeFreshnessError):
        adapter.hook_feedback("SessionStart", None)


def test_successful_hook_does_not_grant_permission():
    value = adapter.hook_feedback("PreToolUse", {"status": "permit", "scope": "inventory"})
    assert "permissionDecision" not in value["hookSpecificOutput"]


def saved_observation(case, name, *, phase="pre_goal", boundary=None):
    value = {
        "schema_version": "1.0.0",
        "repository_key": "claw",
        "repository": "CultureBotAI/culturebotai-claw",
        "remote": "origin",
        "boundary_id": boundary or case["request"]["boundary_id"],
        "policy_sha256": case["adoption"]["contract_sha256"],
        "default_branch": "main",
        "merge_commits": [] if phase == "pre_goal" else ["d" * 40],
        "status": "verified",
        "phase": phase,
        "apply": True,
        "verified_at": "2026-01-01T00:00:00Z",
        "checkout": str(case["root"]),
        "after": "d" * 40,
        "fetched": "d" * 40,
    }
    return {**value, "receipt": reference(case["evidence"] / name, value)}


def retained_inventory(case):
    request = case["request"]
    value = {
        "schema_version": "1.1.0",
        "kind": "verified_goal_inventory",
        "repository_key": "claw",
        "boundary_id": request["boundary_id"],
        "adoption": request["adoption"],
        "effective_workflow": request["effective_workflow"],
        "execution_context": request["execution_context"],
        "workflow_sha256": request["workflow_sha256"],
        "freshness": saved_observation(case, "saved.json"),
        "completion_authority": False,
        "head": "d" * 40,
    }
    ref = reference(case["evidence"] / "retained-inventory.json", value)
    slot = (
        Path(request["receipt_directory"])
        / "index"
        / "claw"
        / (digest(request["boundary_id"]) + ".json")
    )
    slot.parent.mkdir(parents=True)
    slot.write_text(json.dumps(ref))
    return ref


def test_same_goal_continuation_reuses_registered_evidence_without_run(case):
    inventory = retained_inventory(case)
    observation = copy.deepcopy(case["observation"])
    observation["inventory_consumed"] = True
    result = adapter.continue_inventory(
        case["invocation"]["request"],
        reference(case["evidence"] / "continued-observation.json", observation),
        inventory,
        now=case["now"],
    )
    assert result["scope"] == "retained_inventory" and result["artifact"] == inventory
    assert result["next_goal_authority"] is False
    changed = copy.deepcopy(observation)
    changed["native_identity"]["goal_id"] = "different-model-created-goal"
    with pytest.raises(native.NativeFreshnessError, match="identity"):
        adapter.continue_inventory(
            case["invocation"]["request"],
            reference(case["evidence"] / "changed-observation.json", changed),
            inventory,
            now=case["now"],
        )


def test_continuation_refuses_unregistered_inventory(case):
    inventory = retained_inventory(case)
    slot = (
        Path(case["request"]["receipt_directory"])
        / "index"
        / "claw"
        / (digest(case["request"]["boundary_id"]) + ".json")
    )
    slot.write_text(json.dumps({"path": inventory["path"], "sha256": "0" * 64}))
    observation = copy.deepcopy(case["observation"])
    observation["inventory_consumed"] = True
    with pytest.raises(native.NativeFreshnessError, match="registered"):
        adapter.continue_inventory(
            case["invocation"]["request"],
            reference(case["evidence"] / "continued-observation.json", observation),
            inventory,
            now=case["now"],
        )


@pytest.mark.parametrize("phase", ["post_merge", "no_change"])
def test_closure_freshness_never_acknowledges_or_dispatches(case, phase):
    request = copy.deepcopy(case["request"])
    request["phase"] = phase
    request["prior_inventory"] = reference(case["evidence"] / "prior.json", {"fixture": True})
    if phase == "post_merge":
        request["pull_requests"] = [
            {"number": 1, "head_sha": "c" * 40, "merge_commit_sha": "d" * 40}
        ]
    observation = copy.deepcopy(case["observation"])
    observation["state"] = "completed"
    observation["inventory_consumed"] = True
    invocation = copy.deepcopy(case["invocation"])
    invocation["request"] = reference(case["evidence"] / "closure-request.json", [request])
    invocation["observation"] = reference(
        case["evidence"] / "closure-observation.json", observation
    )
    kind = (
        "verified_post_merge_freshness" if phase == "post_merge" else "verified_no_change_freshness"
    )
    artifact = reference(
        case["evidence"] / "closure-result.json",
        {
            "kind": kind,
            "repository_key": "claw",
            "boundary_id": request["boundary_id"],
            "execution_context": request["execution_context"],
            "effective_workflow": request["effective_workflow"],
            "adoption": request["adoption"],
            "workflow_sha256": request["workflow_sha256"],
            "prior_inventory": request["prior_inventory"],
            "completion_authority": False,
        },
    )
    calls = []

    def runner(command, *, timeout):
        calls.append(command)
        return {"status": "verified", "kind": kind, "artifact": artifact}

    result = adapter.gate(
        reference(case["evidence"] / "closure-invocation.json", invocation),
        apply=True,
        runner=runner,
        now=case["now"],
    )
    assert result["scope"] == "closure_freshness_only" and result["completion_authority"] is False
    assert result["next_goal_authority"] is False and len(calls) == 1
    assert adapter.hook_feedback("Stop", result)["continue"] is False


def closure_predecessor(case, *, phase="no_change", missing_ordinary=False, same_goal=False):
    previous = {
        **case["who"],
        "goal_id": case["who"]["goal_id"] if same_goal else "previous-fixture-goal",
    }
    initial = json.loads(
        Path(case["adoption"]["boundary"]["predecessor"]["reference"]["path"]).read_text()
    )
    initial["native_identity"] = previous
    initial_ref = reference(case["evidence"] / "old-initial.json", initial)
    old_adoption = copy.deepcopy(case["adoption"])
    old_adoption["native_identity"] = previous
    old_adoption["boundary"]["id"] = "previous-boundary"
    old_adoption["boundary"]["predecessor"]["reference"] = initial_ref
    old_adoption_ref = reference(case["evidence"] / "old-adoption.json", old_adoption)
    context = {"kind": "native_standalone", "native_identity": previous}
    inventory = {
        "schema_version": "1.1.0",
        "kind": "verified_goal_inventory",
        "repository_key": "claw",
        "boundary_id": "previous-boundary",
        "adoption": old_adoption_ref,
        "execution_context": context,
        "effective_workflow": case["effective_ref"],
        "freshness": saved_observation(case, "old-observation.json", boundary="previous-boundary"),
        "workflow_sha256": case["request"]["workflow_sha256"],
        "completion_authority": False,
        "head": "d" * 40,
    }
    inventory_ref = reference(case["evidence"] / "old-inventory.json", inventory)
    fresh = {
        "schema_version": "1.1.0",
        "workflow_sha256": case["request"]["workflow_sha256"],
        "kind": "verified_no_change_freshness"
        if phase == "no_change"
        else "verified_post_merge_freshness",
        "repository_key": "claw",
        "boundary_id": "previous-boundary",
        "adoption": old_adoption_ref,
        "execution_context": context,
        "effective_workflow": case["effective_ref"],
        "prior_inventory": inventory_ref,
        "completion_authority": False,
        "head": "d" * 40,
    }
    if phase == "post_merge":
        fresh["freshness"] = saved_observation(
            case, "old-post-merge.json", phase="post_merge", boundary="previous-boundary"
        )
        fresh["merges"] = [
            {
                "number": 1,
                "merge_commit_sha": "d" * 40,
                "head_sha": "c" * 40,
                "base": "main",
                "merged_at": "2026-01-01T00:00:00Z",
            }
        ]
    fresh_ref = reference(case["evidence"] / "old-closure-freshness.json", fresh)
    evidence = reference(
        case["evidence"] / "ordinary-source.json",
        {"fixture": "independent exact-head closure review"},
    )
    proofs = dict.fromkeys(native.CLOSURE_REQUIREMENTS, evidence)
    if missing_ordinary:
        proofs.pop("exact_head_review")
    ordinary = reference(
        case["evidence"] / "ordinary.json",
        {
            "kind": "native_ordinary_closure_evidence",
            "repository_key": "claw",
            "native_identity": previous,
            "prior_inventory": inventory_ref,
            "freshness_closure": fresh_ref,
            "evidence": proofs,
        },
    )
    certificate = reference(
        case["evidence"] / "old-closure-certificate.json",
        {
            "schema_version": "1.1.0",
            "authority": "operator_verified_native_goal_closure",
            "repository_key": "claw",
            "repository_root": str(case["root"]),
            "native_identity": previous,
            "goal_status": "completed",
            "approval": case["adoption"]["approval"],
            "evidence": [evidence],
            "ordinary_closure": ordinary,
            "freshness_closure": fresh_ref,
        },
    )
    record = copy.deepcopy(case["adoption"])
    record["boundary"]["predecessor"] = {"kind": "verified_closure", "reference": certificate}
    request = copy.deepcopy(case["request"])
    request["adoption"] = reference(case["evidence"] / "next-adoption.json", record)
    return request


@pytest.mark.parametrize("phase", ["post_merge", "no_change"])
def test_native_predecessor_can_be_truthful_merge_or_no_change(case, phase):
    assert (
        native.request_adoption(closure_predecessor(case, phase=phase))["schema_version"] == "1.1.0"
    )


def test_missing_ordinary_closure_evidence_still_holds_with_freshness(case):
    with pytest.raises(native.NativeFreshnessError, match="ordinary.*incomplete"):
        native.request_adoption(closure_predecessor(case, missing_ordinary=True))


def test_predecessor_cannot_replay_current_native_goal(case):
    with pytest.raises(native.NativeFreshnessError, match="replayed"):
        native.request_adoption(closure_predecessor(case, same_goal=True))


CONTRADICTORY_OBSERVATIONS = [
    ("checkout", "/different-owned-checkout"),
    ("repository_key", "culturemech"),
    ("repository", "CultureBotAI/CultureMech"),
    ("boundary_id", "different-boundary"),
    ("policy_sha256", "0" * 64),
    ("remote", "another-remote"),
    ("phase", "wrong-phase"),
    ("status", "hold"),
    ("fetched", "e" * 40),
]


def rewrite_observation(case, artifact, field, value):
    artifact = copy.deepcopy(artifact)
    observation = artifact["freshness"]
    observation[field] = value
    saved = {k: v for k, v in observation.items() if k != "receipt"}
    observation["receipt"] = reference(case["evidence"] / "contradictory-observation.json", saved)
    return artifact


def rebind_closure_observation(case, request, *, phase, field, value):
    """Keep every hash/link valid so rejection must be semantic context binding."""
    adopted = native.read_reference(request["adoption"])
    certificate = native.read_reference(adopted["boundary"]["predecessor"]["reference"])
    fresh = native.read_reference(certificate["freshness_closure"])
    ordinary = native.read_reference(certificate["ordinary_closure"])
    if phase == "pre_goal":
        prior = native.read_reference(fresh["prior_inventory"])
        prior = rewrite_observation(case, prior, field, value)
        fresh["prior_inventory"] = reference(case["evidence"] / "contradictory-prior.json", prior)
        ordinary["prior_inventory"] = fresh["prior_inventory"]
    else:
        fresh = rewrite_observation(case, fresh, field, value)
    certificate["freshness_closure"] = reference(
        case["evidence"] / "contradictory-fresh.json", fresh
    )
    ordinary["freshness_closure"] = certificate["freshness_closure"]
    certificate["ordinary_closure"] = reference(
        case["evidence"] / "contradictory-ordinary.json", ordinary
    )
    adopted["boundary"]["predecessor"]["reference"] = reference(
        case["evidence"] / "contradictory-certificate.json", certificate
    )
    return {
        **request,
        "adoption": reference(case["evidence"] / "contradictory-adoption.json", adopted),
    }


@pytest.mark.parametrize("phase", ["pre_goal", "post_merge"])
@pytest.mark.parametrize("field,value", CONTRADICTORY_OBSERVATIONS)
def test_hash_valid_predecessor_observation_must_match_native_context(case, phase, field, value):
    request = closure_predecessor(case, phase="post_merge")
    assert native.request_adoption(request)
    request = rebind_closure_observation(case, request, phase=phase, field=field, value=value)
    with pytest.raises(native.NativeFreshnessError, match="observation"):
        native.request_adoption(request)


@pytest.mark.parametrize("field,value", CONTRADICTORY_OBSERVATIONS)
def test_hash_valid_continuation_observation_must_match_inventory(case, field, value):
    original = retained_inventory(case)
    artifact = rewrite_observation(case, native.read_reference(original), field, value)
    changed = reference(case["evidence"] / "contradictory-inventory.json", artifact)
    slot = (
        Path(case["request"]["receipt_directory"])
        / "index/claw"
        / (digest(case["request"]["boundary_id"]) + ".json")
    )
    slot.write_text(json.dumps(changed))
    observation = {**case["observation"], "inventory_consumed": True}
    with pytest.raises(native.NativeFreshnessError, match="observation"):
        adapter.continue_inventory(
            case["invocation"]["request"],
            reference(case["evidence"] / "continuation.json", observation),
            changed,
            now=case["now"],
        )


@pytest.mark.parametrize(
    "field,value", [("merge_commits", ["e" * 40]), ("default_branch", "other")]
)
def test_hash_valid_predecessor_merge_claims_match_observed_prs(case, field, value):
    request = closure_predecessor(case, phase="post_merge")
    request = rebind_closure_observation(
        case, request, phase="post_merge", field=field, value=value
    )
    with pytest.raises(native.NativeFreshnessError, match="merge observation"):
        native.request_adoption(request)
