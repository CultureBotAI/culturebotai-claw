"""Adversarial, offline contracts for persisted deep-research results.

The ``LIVE`` records in this module are synthetic terminal data.  They never
construct a provider client, invoke a model, start a subprocess, or access the
network.  Provider availability and every output byte are injected fixtures.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from yaml.resolver import BaseResolver

import kg_microbe_research.records as research_records
from kg_microbe_research import (
    ResearchRecordError,
    StaticAvailability,
    StaticProbe,
    build_dry_run_result,
    new_result_path,
    sha256_bytes,
    validate_result,
    write_result,
)

PROFILE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "research_profiles" / "culturemech.yaml"
)
FIXED_NOW = datetime(2026, 8, 25, 12, 34, 56, tzinfo=timezone.utc)
FIXED_TIMESTAMP = "2026-08-25T12:34:56Z"
OFFLINE_AVAILABILITY = StaticAvailability(
    {"asta": ("available", "injected offline availability attestation")}
)
NO_LOCAL_TOOLING = StaticProbe()


def _dry_record(
    tmp_path: Path,
    *,
    availability: StaticAvailability = OFFLINE_AVAILABILITY,
    environ: dict[str, str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Build a complete three-stage plan without provider execution."""

    repository_root = tmp_path / "CultureMech"
    profile_path = repository_root / "conf" / "deep_research_provider.yaml"
    target_path = repository_root / "data" / "targets" / "medium.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_bytes(PROFILE_FIXTURE.read_bytes())
    target_path.write_text(
        "id: MEDIUM:offline\nlabel: Offline adversarial medium\n",
        encoding="utf-8",
    )
    record = build_dry_run_result(
        repository_root=repository_root,
        profile_path=profile_path,
        target_path=target_path,
        target_id="MEDIUM:offline",
        target_label="Offline adversarial medium",
        target_type="medium",
        question="Which exact source-backed growth claims are safe to curate?",
        availability=availability,
        environ=environ or {"ASTA_API_KEY": "offline-placeholder-never-used"},
        probe=NO_LOCAL_TOOLING,
        now=FIXED_NOW,
        short_id="adversarial",
    )
    return repository_root, record


def _artifact(
    repository_root: Path,
    *,
    artifact_id: str,
    run_id: str,
    role: str,
    filename: str,
    content: bytes,
    media_type: str,
    external_id: str | None = None,
) -> dict[str, Any]:
    path = repository_root / "research" / "artifacts" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    artifact: dict[str, Any] = {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "role": role,
        "path": path.relative_to(repository_root).as_posix(),
        "media_type": media_type,
        "sha256": sha256_bytes(content),
        "size_bytes": len(content),
    }
    if external_id is not None:
        artifact["external_id"] = external_id
    return artifact


def _completed_raw_record(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Create a valid raw result with one completed synthetic run per stage."""

    repository_root, record = _dry_record(tmp_path)
    record = deepcopy(record)
    record["status"] = "COMPLETED"
    record["assessment_status"] = "NOT_ASSESSED"
    artifacts: list[dict[str, Any]] = list(record["artifacts"])
    for index, run in enumerate(record["runs"], start=1):
        run.update(
            {
                "provider": run["requested_provider"],
                "mode": "LIVE",
                "status": "COMPLETED",
                "provider_called": True,
                "live_authorized": True,
                "usage_authorized": True,
                "usage_authorization_method": "EXPLICIT_ACKNOWLEDGEMENT",
                "started_at": FIXED_TIMESTAMP,
                "completed_at": FIXED_TIMESTAMP,
            }
        )
        artifacts.append(
            _artifact(
                repository_root,
                artifact_id=f"report-{index}",
                run_id=run["run_id"],
                role="REPORT",
                filename=f"report-{index}.md",
                content=(
                    f"# Offline report {index}\n\n"
                    "Raw provider-shaped output retained before assessment.\n"
                ).encode(),
                media_type="text/markdown",
            )
        )
    record["artifacts"] = artifacts
    record["citations"] = [
        {
            "citation_id": "citation-shared",
            "run_id": record["runs"][0]["run_id"],
            "raw_reference": "Unassessed provider reference PMID 12345678",
        }
    ]
    return repository_root, record


def _assessed_record(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Add independently checkable per-finding evidence to a raw result."""

    repository_root, record = _completed_raw_record(tmp_path)
    record = deepcopy(record)
    run_id = record["runs"][0]["run_id"]
    source = (
        b"The checked source supports the first synthetic finding.\n"
        b"The checked source supports the second, distinct synthetic finding.\n"
        b"No explicit organism-medium evidence was found in this checked source.\n"
    )
    validation = b'{"normalized_reference":"PMID:12345678","resolved":true}\n'
    record["artifacts"].extend(
        [
            _artifact(
                repository_root,
                artifact_id="source-snapshot",
                run_id=run_id,
                role="SOURCE_SNAPSHOT",
                filename="source.txt",
                content=source,
                media_type="text/plain",
                external_id="PMID:12345678",
            ),
            _artifact(
                repository_root,
                artifact_id="reference-validation",
                run_id=run_id,
                role="REFERENCE_VALIDATION",
                filename="reference-validation.json",
                content=validation,
                media_type="application/json",
            ),
        ]
    )
    record["citations"][0].update(
        {
            "normalized_reference": "PMID:12345678",
            "validation_status": "VERIFIED",
            "validation_artifact_id": "reference-validation",
            "validated_by": "offline deterministic identifier fixture",
            "validated_at": FIXED_TIMESTAMP,
        }
    )
    record["assessment_status"] = "ASSESSED"
    record["assessment_scope"] = (
        "The first synthetic finding against the retained source snapshot."
    )
    record["evidence"] = [
        {
            "evidence_id": "evidence-first",
            "finding_id": "finding-first",
            "run_id": run_id,
            "citation_id": "citation-shared",
            "source_artifact_id": "source-snapshot",
            "evidence_source": "PRIMARY_LITERATURE",
            "relevance": "ON_TOPIC",
            "support_level": "SUPPORT",
            "verification_method": "EXACT_TEXT_MATCH",
            "snippet": "The checked source supports the first synthetic finding.",
            "rationale": "The checksum-bound source states the claim exactly.",
            "assessed_by": "offline deterministic assessor fixture",
            "assessed_at": FIXED_TIMESTAMP,
        }
    ]
    record["findings"] = [
        {
            "finding_id": "finding-first",
            "statement": "The first synthetic finding has direct source support.",
            "disposition": "SUPPORT",
            "evidence_ids": ["evidence-first"],
            "rationale": "The linked per-finding assertion has an exact source match.",
        }
    ]
    return repository_root, record


def _make_first_run_unusable(record: dict[str, Any]) -> str:
    run = record["runs"][0]
    run["status"] = "UNUSABLE"
    run["error"] = "Synthetic output was off-topic; raw bytes retained for audit."
    record["status"] = "UNUSABLE"
    record["assessment_status"] = "NOT_ASSESSED"
    return run["run_id"]


def _completed_fallback_record(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Model a failed Asta attempt followed by an explicit Consensus fallback."""

    availability = StaticAvailability(
        {
            "asta": ("available", "injected Asta functional attestation"),
            "consensus": (
                "available",
                "injected Consensus functional attestation",
            ),
            "openai": ("available", "injected OpenAI functional attestation"),
        }
    )
    repository_root, record = _dry_record(
        tmp_path,
        availability=availability,
        environ={
            "ASTA_API_KEY": "offline-placeholder-never-used",
            "CONSENSUS_API_KEY": "offline-placeholder-never-used",
            "OPENAI_API_KEY": "offline-placeholder-never-used",
        },
    )
    record = deepcopy(record)
    record["status"] = "COMPLETED"
    record["assessment_status"] = "NOT_ASSESSED"
    artifacts: list[dict[str, Any]] = list(record["artifacts"])
    for index, run in enumerate(record["runs"], start=1):
        run.update(
            {
                "provider": run["requested_provider"],
                "mode": "LIVE",
                "status": "COMPLETED",
                "provider_called": True,
                "live_authorized": True,
                "usage_authorized": True,
                "usage_authorization_method": "EXPLICIT_ACKNOWLEDGEMENT",
                "started_at": FIXED_TIMESTAMP,
                "completed_at": FIXED_TIMESTAMP,
            }
        )
        artifacts.append(
            _artifact(
                repository_root,
                artifact_id=f"fallback-report-{index}",
                run_id=run["run_id"],
                role="REPORT",
                filename=f"fallback-report-{index}.md",
                content=f"# Offline terminal report {index}\n".encode(),
                media_type="text/markdown",
            )
        )

    prior = record["runs"][0]
    prior["status"] = "FAILED"
    prior["error"] = "Synthetic provider failure before fallback."
    artifacts = [
        artifact for artifact in artifacts if artifact.get("run_id") != prior["run_id"]
    ]

    fallback = deepcopy(prior)
    fallback_assignment = next(
        assignment
        for assignment in record["plan"]["stage_assignments"]
        if assignment["stage"] == fallback["stage"]
        and assignment["assignment_kind"] == "FALLBACK"
    )
    fallback.update(
        {
            "run_id": f"{prior['run_id']}-fallback",
            "attempt": 2,
            "provider": fallback_assignment["provider"],
            "provider_substitution_reason": (
                "Primary attempt failed; use the recorded ordinal-2 fallback."
            ),
            "provider_status": fallback_assignment["provider_status"],
            "provider_status_reason": fallback_assignment["provider_status_reason"],
            "relative_cost": fallback_assignment["relative_cost"],
            "billing": fallback_assignment["billing"],
            "usage_authorization_required": fallback_assignment[
                "usage_authorization_required"
            ],
            "status": "COMPLETED",
        }
    )
    fallback.pop("error")
    record["runs"].insert(1, fallback)
    artifacts.insert(
        0,
        _artifact(
            repository_root,
            artifact_id="fallback-report",
            run_id=fallback["run_id"],
            role="REPORT",
            filename="fallback-report.md",
            content=b"# Offline fallback report\n",
            media_type="text/markdown",
        ),
    )
    record["artifacts"] = artifacts
    return repository_root, record, fallback


def _structured_evidence_record(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any]]:
    repository_root, record = _assessed_record(tmp_path)
    assertion = record["evidence"][0]
    assertion["verification_method"] = "STRUCTURED_DATA_CHECK"
    assertion["locator"] = "$.growth_observations[0]"
    assertion["assessment_artifact_id"] = "evidence-assessment"
    assertion.pop("snippet")

    run_id = assertion["run_id"]
    record["artifacts"].append(
        _artifact(
            repository_root,
            artifact_id="evidence-assessment",
            run_id=run_id,
            role="EVIDENCE_ASSESSMENT",
            filename="evidence-assessment.json",
            content=b'{"locator":"$.growth_observations[0]","checked":true}\n',
            media_type="application/json",
        )
    )

    source_artifact = next(
        artifact
        for artifact in record["artifacts"]
        if artifact["artifact_id"] == "source-snapshot"
    )
    source_path = repository_root / source_artifact["path"]
    source_content = b'{"growth_observations":[{"supported":true}]}\n'
    source_path.write_bytes(source_content)
    source_artifact.update(
        {
            "media_type": "application/json",
            "sha256": sha256_bytes(source_content),
            "size_bytes": len(source_content),
        }
    )
    return repository_root, record


def _recorded_pass_change_record(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any]]:
    repository_root, record = _assessed_record(tmp_path)
    run_id = record["runs"][0]["run_id"]
    domain_schema_bytes = b"type: object\nrequired: [id]\n"
    domain_schema_path = repository_root / "schema" / "domain.yaml"
    domain_schema_path.parent.mkdir(parents=True)
    domain_schema_path.write_bytes(domain_schema_bytes)
    target_path = repository_root / record["plan"]["question"]["target"]["target_path"]
    pre_change_bytes = target_path.read_bytes()
    record["artifacts"].extend(
        [
            _artifact(
                repository_root,
                artifact_id="domain-schema",
                run_id=run_id,
                role="DOMAIN_SCHEMA",
                filename="domain-schema.yaml",
                content=domain_schema_bytes,
                media_type="application/yaml",
            ),
            _artifact(
                repository_root,
                artifact_id="pre-change-target",
                run_id=run_id,
                role="TARGET_SNAPSHOT",
                filename="pre-change-target.yaml",
                content=pre_change_bytes,
                media_type="application/yaml",
            ),
            _artifact(
                repository_root,
                artifact_id="proposed-patch",
                run_id=run_id,
                role="PATCH",
                filename="proposed.patch",
                content=b"- status: old\n+ status: supported\n",
                media_type="text/x-diff",
            ),
            _artifact(
                repository_root,
                artifact_id="domain-validation",
                run_id=run_id,
                role="DOMAIN_VALIDATION",
                filename="domain-validation.txt",
                content=b"offline fixture: schema validation passed\n",
                media_type="text/plain",
            ),
        ]
    )
    record["proposed_changes"] = [
        {
            "change_id": "change-first",
            "target_path": record["plan"]["question"]["target"]["target_path"],
            "operation": "UPDATE",
            "field_path": "/status",
            "summary": "Record the independently supported synthetic status.",
            "rationale": "The proposed patch is linked to an assessed finding.",
            "pre_change_artifact_id": "pre-change-target",
            "finding_ids": ["finding-first"],
            "patch_artifact_id": "proposed-patch",
            "domain_validation_status": "RECORDED_PASS",
            "domain_schema_artifact_id": "domain-schema",
            "domain_schema_path": domain_schema_path.relative_to(repository_root).as_posix(),
            "validation_artifact_id": "domain-validation",
            "validation_message": "Offline schema fixture reported success.",
            "validation_command": "mech-domain-validator --offline proposed.yaml",
            "validated_at": FIXED_TIMESTAMP,
        }
    ]
    return repository_root, record


def test_completed_raw_capture_can_be_saved_before_assessment(tmp_path: Path) -> None:
    repository_root, record = _completed_raw_record(tmp_path)

    validate_result(
        record,
        repository_root=repository_root,
        verify_artifacts=True,
        verify_snapshots=True,
    )

    assert record["assessment_status"] == "NOT_ASSESSED"
    assert "findings" not in record
    assert "evidence" not in record
    assert len(record["citations"]) == 1


def test_scaffolder_retains_all_eligible_providers_in_deterministic_ordinals(
    tmp_path: Path,
) -> None:
    availability = StaticAvailability(
        {
            "asta": ("available", "injected Asta functional attestation"),
            "consensus": (
                "available",
                "injected Consensus functional attestation",
            ),
        }
    )
    _, record = _dry_record(
        tmp_path,
        availability=availability,
        environ={
            "ASTA_API_KEY": "offline-placeholder-never-used",
            "CONSENSUS_API_KEY": "offline-placeholder-never-used",
        },
    )

    assignments_by_stage: dict[str, list[dict[str, Any]]] = {}
    for assignment in record["plan"]["stage_assignments"]:
        assignments_by_stage.setdefault(assignment["stage"], []).append(assignment)

    assert list(assignments_by_stage) == ["discovery", "synthesis", "verification"]
    for assignments in assignments_by_stage.values():
        assert [item["provider"] for item in assignments] == ["asta", "consensus"]
        assert [item["ordinal"] for item in assignments] == [1, 2]
        assert [item["assignment_kind"] for item in assignments] == [
            "RECOMMENDED",
            "FALLBACK",
        ]
    assert [run["requested_provider"] for run in record["runs"]] == [
        "asta",
        "asta",
        "asta",
    ]


def test_live_fallback_records_actual_provider_after_a_prior_failed_attempt(
    tmp_path: Path,
) -> None:
    repository_root, record, fallback = _completed_fallback_record(tmp_path)

    validate_result(
        record,
        repository_root=repository_root,
        verify_artifacts=True,
        verify_snapshots=True,
    )

    assert fallback["requested_provider"] == "asta"
    assert fallback["provider"] == "consensus"
    assert fallback["attempt"] == 2
    assert fallback["provider_substitution_reason"]


@pytest.mark.parametrize("field", ("provider_status", "provider_status_reason"))
def test_live_fallback_status_facts_must_match_the_actual_provider_assignment(
    tmp_path: Path,
    field: str,
) -> None:
    repository_root, record, fallback = _completed_fallback_record(tmp_path)
    primary_assignment = next(
        assignment
        for assignment in record["plan"]["stage_assignments"]
        if assignment["stage"] == fallback["stage"]
        and assignment["assignment_kind"] == "RECOMMENDED"
    )
    fallback[field] = primary_assignment[field]
    if field == "provider_status":
        fallback[field] = "configured"

    with pytest.raises(ResearchRecordError, match="provider status must match"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_live_fallback_requires_a_prior_failed_or_unusable_requested_attempt(
    tmp_path: Path,
) -> None:
    repository_root, record, fallback = _completed_fallback_record(tmp_path)
    prior = next(
        run
        for run in record["runs"]
        if run["stage"] == fallback["stage"] and run["attempt"] == 1
    )
    record["runs"].remove(prior)
    fallback["attempt"] = 1

    with pytest.raises(ResearchRecordError, match="higher-ranked provider 'asta'"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_provider_substitution_cannot_skip_an_untried_higher_ranked_fallback(
    tmp_path: Path,
) -> None:
    repository_root, record, fallback = _completed_fallback_record(tmp_path)
    later_assignment = next(
        assignment
        for assignment in record["plan"]["stage_assignments"]
        if assignment["stage"] == fallback["stage"]
        and assignment["provider"] == "openai"
    )
    fallback["provider"] = later_assignment["provider"]
    for field in (
        "provider_status",
        "provider_status_reason",
        "relative_cost",
        "billing",
        "usage_authorization_required",
    ):
        fallback[field] = later_assignment[field]

    with pytest.raises(ResearchRecordError, match="higher-ranked provider 'consensus'"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("missing-assessor", "LinkML validation failed|assessed_by"),
        ("missing-source", "LinkML validation failed|source_artifact_id"),
        ("provider-report-self-proof", "SOURCE_SNAPSHOT"),
    ),
)
def test_assessed_finding_requires_an_assessor_and_independent_source_snapshot(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    repository_root, record = _assessed_record(tmp_path)
    assertion = record["evidence"][0]
    if case == "missing-assessor":
        assertion.pop("assessed_by")
    elif case == "missing-source":
        assertion.pop("source_artifact_id")
    else:
        assertion["source_artifact_id"] = "report-1"

    with pytest.raises(ResearchRecordError, match=message):
        validate_result(
            record,
            repository_root=repository_root,
            verify_artifacts=True,
        )


def test_one_citation_can_support_distinct_per_finding_evidence_assertions(
    tmp_path: Path,
) -> None:
    repository_root, record = _assessed_record(tmp_path)
    run_id = record["runs"][0]["run_id"]
    record["evidence"].append(
        {
            "evidence_id": "evidence-second",
            "finding_id": "finding-second",
            "run_id": run_id,
            "citation_id": "citation-shared",
            "source_artifact_id": "source-snapshot",
            "evidence_source": "PRIMARY_LITERATURE",
            "relevance": "ON_TOPIC",
            "support_level": "SUPPORT",
            "verification_method": "EXACT_TEXT_MATCH",
            "snippet": (
                "The checked source supports the second, distinct synthetic finding."
            ),
            "rationale": "A different exact excerpt supports this different claim.",
            "assessed_by": "offline deterministic assessor fixture",
            "assessed_at": FIXED_TIMESTAMP,
        }
    )
    record["findings"].append(
        {
            "finding_id": "finding-second",
            "statement": "The second synthetic finding has separate direct support.",
            "disposition": "SUPPORT",
            "evidence_ids": ["evidence-second"],
            "rationale": "Its own assertion preserves its own source excerpt.",
        }
    )

    validate_result(
        record,
        repository_root=repository_root,
        verify_artifacts=True,
        verify_snapshots=True,
    )

    assert {item["citation_id"] for item in record["evidence"]} == {
        "citation-shared"
    }
    assert len({item["evidence_id"] for item in record["evidence"]}) == 2
    assert len({item["finding_id"] for item in record["evidence"]}) == 2


def test_no_evidence_is_preserved_as_an_assessed_audit_outcome(tmp_path: Path) -> None:
    repository_root, record = _assessed_record(tmp_path)
    assertion = record["evidence"][0]
    assertion.pop("citation_id")
    assertion.update(
        {
            "evidence_source": "DATABASE",
            "relevance": "ON_TOPIC",
            "support_level": "NO_EVIDENCE",
            "snippet": (
                "No explicit organism-medium evidence was found in this checked source."
            ),
            "rationale": "The checked source contains no explicit claim to promote.",
        }
    )
    record["findings"][0].update(
        {
            "statement": "No explicit growth evidence was located in the checked source.",
            "disposition": "NO_EVIDENCE",
            "rationale": "The negative search outcome remains reviewable and non-promotable.",
        }
    )

    validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_non_text_evidence_can_use_a_locator_and_assessment_artifact(
    tmp_path: Path,
) -> None:
    repository_root, record = _structured_evidence_record(tmp_path)

    validate_result(record, repository_root=repository_root, verify_artifacts=True)

    assertion = record["evidence"][0]
    assert assertion["verification_method"] == "STRUCTURED_DATA_CHECK"
    assert "snippet" not in assertion


@pytest.mark.parametrize(
    ("missing_field", "message"),
    (
        ("locator", "locator must be a non-empty string"),
        ("assessment_artifact_id", "assessment_artifact_id must resolve"),
    ),
)
def test_non_text_evidence_requires_locator_and_assessment_artifact(
    tmp_path: Path,
    missing_field: str,
    message: str,
) -> None:
    repository_root, record = _structured_evidence_record(tmp_path)
    record["evidence"][0].pop(missing_field)

    with pytest.raises(ResearchRecordError, match=message):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_recorded_pass_change_binds_patch_schema_snapshot_and_validator_output(
    tmp_path: Path,
) -> None:
    repository_root, record = _recorded_pass_change_record(tmp_path)
    target_path = repository_root / record["plan"]["question"]["target"]["target_path"]
    original_target = target_path.read_bytes()

    validate_result(
        record,
        repository_root=repository_root,
        verify_artifacts=True,
        verify_snapshots=True,
    )

    change = record["proposed_changes"][0]
    assert change["domain_validation_status"] == "RECORDED_PASS"
    assert target_path.read_bytes() == original_target


@pytest.mark.parametrize("snapshot", ("target", "domain-schema"))
def test_recorded_change_rejects_current_target_or_domain_schema_drift(
    tmp_path: Path,
    snapshot: str,
) -> None:
    repository_root, record = _recorded_pass_change_record(tmp_path)
    change = record["proposed_changes"][0]
    relative = (
        change["target_path"]
        if snapshot == "target"
        else change["domain_schema_path"]
    )
    current = repository_root / relative
    current.write_bytes(current.read_bytes() + b"# post-capture drift\n")

    with pytest.raises(ResearchRecordError, match="sha256 does not match"):
        validate_result(
            record,
            repository_root=repository_root,
            verify_artifacts=True,
            verify_snapshots=True,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("missing-domain-schema", "domain_schema_artifact_id must resolve"),
        ("missing-patch", "patch_artifact_id must resolve"),
        ("missing-pre-change", "pre_change_artifact_id must resolve"),
        ("missing-validation-output", "validation_artifact_id must resolve"),
        ("missing-command", "validation_command must be a non-empty string"),
        ("missing-time", "validated_at must be a timezone-aware"),
        ("not-run-with-pass-details", "validator details contradict NOT_RUN"),
    ),
)
def test_proposed_change_rejects_incomplete_or_contradictory_status_artifacts(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    repository_root, record = _recorded_pass_change_record(tmp_path)
    change = record["proposed_changes"][0]
    if case == "missing-domain-schema":
        record["artifacts"] = [
            item for item in record["artifacts"] if item["artifact_id"] != "domain-schema"
        ]
    elif case == "missing-patch":
        record["artifacts"] = [
            item for item in record["artifacts"] if item["artifact_id"] != "proposed-patch"
        ]
    elif case == "missing-pre-change":
        record["artifacts"] = [
            item
            for item in record["artifacts"]
            if item["artifact_id"] != "pre-change-target"
        ]
    elif case == "missing-validation-output":
        record["artifacts"] = [
            item
            for item in record["artifacts"]
            if item["artifact_id"] != "domain-validation"
        ]
    elif case == "missing-command":
        change.pop("validation_command")
    elif case == "missing-time":
        change.pop("validated_at")
    else:
        change["domain_validation_status"] = "NOT_RUN"

    with pytest.raises(ResearchRecordError, match=message):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_unusable_output_is_valid_only_when_provider_output_is_preserved(
    tmp_path: Path,
) -> None:
    repository_root, record = _completed_raw_record(tmp_path)
    unusable_run_id = _make_first_run_unusable(record)

    validate_result(record, repository_root=repository_root, verify_artifacts=True)

    record["artifacts"] = [
        artifact
        for artifact in record["artifacts"]
        if artifact.get("run_id") != unusable_run_id
    ]
    with pytest.raises(ResearchRecordError, match="must preserve its provider output"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_unusable_result_cannot_promote_assessed_findings(tmp_path: Path) -> None:
    repository_root, record = _assessed_record(tmp_path)
    record["runs"][-1]["status"] = "UNUSABLE"
    record["runs"][-1]["error"] = "Synthetic late-stage output was unusable."
    record["status"] = "UNUSABLE"

    with pytest.raises(ResearchRecordError, match="UNUSABLE result must be NOT_ASSESSED"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_completed_result_requires_a_completed_run_for_every_planned_stage(
    tmp_path: Path,
) -> None:
    repository_root, record = _completed_raw_record(tmp_path)
    omitted_run = record["runs"].pop()
    record["artifacts"] = [
        artifact
        for artifact in record["artifacts"]
        if artifact.get("run_id") != omitted_run["run_id"]
    ]

    with pytest.raises(ResearchRecordError, match="completed run for every stage"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_failed_result_requires_an_actual_failed_provider_attempt(tmp_path: Path) -> None:
    _, record = _dry_record(tmp_path)
    record["status"] = "FAILED"

    with pytest.raises(ResearchRecordError, match="actual failed provider attempt"):
        validate_result(record)


def test_empty_provider_allowlist_is_rejected_as_ambiguous(tmp_path: Path) -> None:
    _, record = _dry_record(tmp_path)
    record["plan"]["provider_allowlist"] = []

    with pytest.raises(ResearchRecordError, match="absent rather than an empty"):
        validate_result(record)


@pytest.mark.parametrize(
    "hostile_result_id",
    ("../escape", "nested/result", "/absolute", "result\\windows", "result\nowned"),
)
def test_hostile_result_id_is_rejected_by_record_and_path_validation(
    tmp_path: Path,
    hostile_result_id: str,
) -> None:
    repository_root, record = _dry_record(tmp_path)
    record["result_id"] = hostile_result_id

    with pytest.raises(ResearchRecordError, match="result_id"):
        validate_result(record)
    with pytest.raises(ResearchRecordError, match="result_id"):
        new_result_path(
            repository_root,
            target_id="MEDIUM:offline",
            result_id=hostile_result_id,
        )


@pytest.mark.parametrize(
    ("field", "tampered"),
    (
        ("mech", "TraitMech"),
        ("focus_label", "tampered focus label"),
        ("evidence_policy", "accept unsupported provider prose"),
        ("source_priorities", ["provider narrative only"]),
    ),
)
def test_snapshot_verification_rejects_checksum_preserving_profile_semantic_tampering(
    tmp_path: Path,
    field: str,
    tampered: object,
) -> None:
    repository_root, record = _dry_record(tmp_path)
    record["plan"][field] = tampered

    with pytest.raises(ResearchRecordError, match=f"plan\\.{field} does not match"):
        validate_result(
            record,
            repository_root=repository_root,
            verify_snapshots=True,
        )


def test_outside_writer_rejection_creates_no_parent_directories(tmp_path: Path) -> None:
    repository_root, record = _dry_record(tmp_path)
    outside_tree = tmp_path / "outside-tree"
    destination = outside_tree / "nested" / "result.yaml"

    with pytest.raises(ResearchRecordError, match="must stay inside repository root"):
        write_result(destination, record, repository_root=repository_root)

    assert not outside_tree.exists()


def test_writer_does_not_follow_an_in_repository_symlinked_destination_parent(
    tmp_path: Path,
) -> None:
    repository_root, record = _dry_record(tmp_path)
    outside_directory = tmp_path / "outside-symlink-target"
    outside_directory.mkdir()
    runs_directory = repository_root / "research" / "runs"
    runs_directory.mkdir(parents=True)
    symlinked_parent = runs_directory / "escape"
    try:
        symlinked_parent.symlink_to(outside_directory, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - platform capability
        pytest.skip(f"directory symlinks unavailable: {exc}")
    destination = symlinked_parent / "nested" / "result.yaml"

    with pytest.raises(ResearchRecordError, match="cannot publish research result"):
        write_result(destination, record, repository_root=repository_root)

    assert list(outside_directory.iterdir()) == []
    assert not destination.exists()


def test_append_only_writer_exposes_no_overwrite_escape_hatch() -> None:
    assert {"force", "overwrite"}.isdisjoint(inspect.signature(write_result).parameters)


def test_linkml_validation_ignores_process_global_yaml_path_resolver_contamination(
    tmp_path: Path,
) -> None:
    """A foreign root resolver must not make LinkML mappings have a null tag."""

    _, record = _dry_record(tmp_path)
    original_resolvers = dict(BaseResolver.yaml_path_resolvers)
    research_records._linkml_validator.cache_clear()
    try:
        BaseResolver.add_path_resolver(None, [], dict)
        assert any(tag is None for tag in BaseResolver.yaml_path_resolvers.values())

        validate_result(record)
    finally:
        BaseResolver.yaml_path_resolvers.clear()
        BaseResolver.yaml_path_resolvers.update(original_resolvers)
        research_records._linkml_validator.cache_clear()

    assert yaml.safe_load("key: value\n") == {"key": "value"}


def test_catalogue_cost_facts_cannot_be_rewritten_consistently_across_record(
    tmp_path: Path,
) -> None:
    _, record = _dry_record(tmp_path)
    for evaluation in record["plan"]["provider_evaluations"]:
        if evaluation["provider"] == "asta":
            evaluation.update(
                {
                    "relative_cost": "very_high",
                    "billing": "unknown",
                    "usage_authorization_required": True,
                }
            )
    for assignment in record["plan"]["stage_assignments"]:
        assignment.update(
            {
                "relative_cost": "very_high",
                "billing": "unknown",
                "usage_authorization_required": True,
            }
        )
    for run in record["runs"]:
        run.update(
            {
                "relative_cost": "very_high",
                "billing": "unknown",
                "usage_authorization_required": True,
            }
        )

    with pytest.raises(ResearchRecordError, match="versioned provider catalogue"):
        validate_result(record)


def test_recommendation_cannot_omit_a_higher_ranked_available_provider(
    tmp_path: Path,
) -> None:
    availability = StaticAvailability(
        {
            "asta": ("available", "offline Asta attestation"),
            "consensus": ("available", "offline Consensus attestation"),
        }
    )
    _, record = _dry_record(
        tmp_path,
        availability=availability,
        environ={"ASTA_API_KEY": "x", "CONSENSUS_API_KEY": "x"},
    )
    record["plan"]["stage_assignments"] = [
        assignment
        for assignment in record["plan"]["stage_assignments"]
        if assignment["provider"] != "asta"
    ]
    for assignment in record["plan"]["stage_assignments"]:
        assignment["ordinal"] = 1
        assignment["assignment_kind"] = "RECOMMENDED"
    for run in record["runs"]:
        run["requested_provider"] = "consensus"
        run["provider_status_reason"] = "offline Consensus attestation"
        run["relative_cost"] = "low"

    with pytest.raises(ResearchRecordError, match="policy-eligible provider evaluation"):
        validate_result(record)


def test_direct_fallback_attempt_requires_higher_ranked_failure(tmp_path: Path) -> None:
    repository_root, record, fallback = _completed_fallback_record(tmp_path)
    prior = next(
        run
        for run in record["runs"]
        if run["stage"] == fallback["stage"] and run["attempt"] == 1
    )
    record["runs"].remove(prior)
    fallback["attempt"] = 1
    fallback["requested_provider"] = fallback["provider"]
    fallback.pop("provider_substitution_reason")

    with pytest.raises(ResearchRecordError, match="before higher-ranked provider"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_fallback_cannot_predate_the_failure_that_triggered_it(tmp_path: Path) -> None:
    repository_root, record, fallback = _completed_fallback_record(tmp_path)
    record["generated_at"] = "2026-08-25T13:00:00Z"
    prior = next(
        run
        for run in record["runs"]
        if run["stage"] == fallback["stage"] and run["attempt"] == 1
    )
    prior["started_at"] = "2026-08-25T12:34:57Z"
    prior["completed_at"] = "2026-08-25T12:34:58Z"

    with pytest.raises(ResearchRecordError, match="created before the preceding attempt"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_completed_stage_cannot_have_a_later_failed_attempt(tmp_path: Path) -> None:
    repository_root, record = _completed_raw_record(tmp_path)
    first = record["runs"][0]
    later = deepcopy(first)
    later.update(
        {
            "run_id": f"{first['run_id']}-late-failure",
            "attempt": 2,
            "status": "FAILED",
            "error": "Synthetic attempt after success.",
        }
    )
    record["runs"].insert(1, later)

    with pytest.raises(ResearchRecordError, match="after its terminal COMPLETED"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_recovered_fallback_is_completed_not_partial(tmp_path: Path) -> None:
    repository_root, record, _ = _completed_fallback_record(tmp_path)
    record["status"] = "PARTIAL"

    with pytest.raises(ResearchRecordError, match="final completed.*final failed"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_assessment_scope_distinguishes_full_partial_and_raw_results(tmp_path: Path) -> None:
    repository_root, assessed = _assessed_record(tmp_path)
    assessed.pop("assessment_scope")
    with pytest.raises(ResearchRecordError, match="assessment_scope"):
        validate_result(assessed, repository_root=repository_root, verify_artifacts=True)

    repository_root, partial = _assessed_record(tmp_path)
    partial["assessment_status"] = "PARTIALLY_ASSESSED"
    with pytest.raises(ResearchRecordError, match="at least one assessment limitation"):
        validate_result(partial, repository_root=repository_root, verify_artifacts=True)
    partial["assessment_limitations"] = ["One named database was unavailable offline."]
    validate_result(partial, repository_root=repository_root, verify_artifacts=True)

    _, raw = _completed_raw_record(tmp_path)
    raw["assessment_scope"] = "A raw capture cannot claim this boundary."
    with pytest.raises(ResearchRecordError, match="must not claim assessment scope"):
        validate_result(raw)


def test_exact_text_optional_assessment_artifact_cannot_dangle(tmp_path: Path) -> None:
    repository_root, record = _assessed_record(tmp_path)
    record["evidence"][0]["assessment_artifact_id"] = "missing-assessment"

    with pytest.raises(ResearchRecordError, match="EVIDENCE_ASSESSMENT artifact"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_finding_cannot_aggregate_support_as_wrong_statement(tmp_path: Path) -> None:
    repository_root, record = _assessed_record(tmp_path)
    contradictory = deepcopy(record["evidence"][0])
    contradictory["evidence_id"] = "evidence-contradictory"
    contradictory["support_level"] = "WRONG_STATEMENT"
    record["evidence"].append(contradictory)
    record["findings"][0]["evidence_ids"].append("evidence-contradictory")
    record["findings"][0]["disposition"] = "WRONG_STATEMENT"

    with pytest.raises(ResearchRecordError, match="disposition contradicts"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_completed_report_and_evidence_provenance_must_be_nonempty(tmp_path: Path) -> None:
    repository_root, record = _assessed_record(tmp_path)
    report = next(item for item in record["artifacts"] if item["role"] == "REPORT")
    report_path = repository_root / report["path"]
    report_path.write_bytes(b"")
    report.update({"sha256": sha256_bytes(b""), "size_bytes": 0})

    with pytest.raises(ResearchRecordError, match="has no REPORT artifact"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_embedded_inputs_survive_source_drift_but_snapshot_check_detects_it(
    tmp_path: Path,
) -> None:
    repository_root, record = _dry_record(tmp_path)
    profile_path = repository_root / record["plan"]["profile_path"]
    target_path = repository_root / record["plan"]["question"]["target"]["target_path"]
    profile_path.write_bytes(profile_path.read_bytes() + b"\n# later profile revision\n")
    target_path.write_bytes(target_path.read_bytes() + b"\n# later target revision\n")

    validate_result(record, repository_root=repository_root, verify_artifacts=True)
    with pytest.raises(ResearchRecordError, match="sha256 does not match"):
        validate_result(
            record,
            repository_root=repository_root,
            verify_artifacts=True,
            verify_snapshots=True,
        )


def test_create_change_rejects_an_existing_target_at_snapshot_verification(
    tmp_path: Path,
) -> None:
    repository_root, record = _recorded_pass_change_record(tmp_path)
    change = record["proposed_changes"][0]
    change["operation"] = "CREATE"
    change.pop("pre_change_artifact_id")

    with pytest.raises(ResearchRecordError, match="already exists.*CREATE"):
        validate_result(
            record,
            repository_root=repository_root,
            verify_artifacts=True,
            verify_snapshots=True,
        )


def test_writer_temp_collision_does_not_delete_a_preexisting_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root, record = _dry_record(tmp_path)
    destination = repository_root / "research" / "results" / "result.yaml"
    destination.parent.mkdir(parents=True)
    collision = destination.parent / ".result.yaml.tmp-collision"
    collision.write_bytes(b"preexisting bytes\n")
    monkeypatch.setattr(research_records.secrets, "token_hex", lambda _size: "collision")

    with pytest.raises(FileExistsError):
        write_result(destination, record, repository_root=repository_root)

    assert collision.read_bytes() == b"preexisting bytes\n"
    assert not destination.exists()


def _linked_assessment(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    repository_root, raw = _completed_raw_record(tmp_path)
    prior_path = repository_root / "research" / "results" / "raw.yaml"
    write_result(prior_path, raw, repository_root=repository_root)

    repository_root, assessed = _assessed_record(tmp_path)
    assessed["result_id"] = f"{assessed['result_id']}-assessment"
    assessed["generated_at"] = "2026-08-25T12:34:57Z"
    assessed["assessment_of_result_id"] = raw["result_id"]
    assessed["assessment_of_path"] = prior_path.relative_to(repository_root).as_posix()
    assessed["assessment_of_sha256"] = sha256_bytes(prior_path.read_bytes())
    return repository_root, assessed


def test_assessment_lineage_resolves_and_preserves_the_raw_capture(tmp_path: Path) -> None:
    repository_root, assessed = _linked_assessment(tmp_path)

    validate_result(assessed, repository_root=repository_root, verify_artifacts=True)

    assessed["runs"][0]["authorization_reasons"].append(
        "mutation that was not part of the raw capture"
    )
    with pytest.raises(ResearchRecordError, match="preserve every raw provider run"):
        validate_result(assessed, repository_root=repository_root, verify_artifacts=True)


def test_assessment_lineage_forbids_a_new_raw_provider_artifact(tmp_path: Path) -> None:
    repository_root, assessed = _linked_assessment(tmp_path)
    assessed["artifacts"].append(
        _artifact(
            repository_root,
            artifact_id="post-hoc-provider-report",
            run_id=assessed["runs"][0]["run_id"],
            role="REPORT",
            filename="post-hoc-provider-report.md",
            content=b"Post-hoc bytes that were not in the raw capture.\n",
            media_type="text/markdown",
        )
    )

    with pytest.raises(ResearchRecordError, match="may add only assessment"):
        validate_result(assessed, repository_root=repository_root, verify_artifacts=True)


def test_assessment_lineage_forbids_a_new_provider_native_citation(tmp_path: Path) -> None:
    repository_root, assessed = _linked_assessment(tmp_path)
    assessed["citations"].append(
        {
            "citation_id": "post-hoc-provider-citation",
            "run_id": assessed["runs"][0]["run_id"],
            "raw_reference": "Reference not present in the raw provider capture",
        }
    )

    with pytest.raises(ResearchRecordError, match="must not add or remove provider citations"):
        validate_result(assessed, repository_root=repository_root, verify_artifacts=True)


def test_cross_kind_lineage_cannot_create_a_direct_cycle(tmp_path: Path) -> None:
    repository_root, prior = _assessed_record(tmp_path)
    prior["result_id"] = "prior-assessed-result"
    prior["assessment_of_result_id"] = "current-correction-result"
    prior["assessment_of_path"] = "research/results/future-raw.yaml"
    prior["assessment_of_sha256"] = "0" * 64
    prior_path = repository_root / "research" / "results" / "prior-assessed.yaml"
    prior_path.parent.mkdir(parents=True, exist_ok=True)
    prior_path.write_text(research_records.result_yaml(prior), encoding="utf-8")

    _, current = _completed_raw_record(tmp_path)
    current["result_id"] = "current-correction-result"
    current["generated_at"] = "2026-08-25T12:34:57Z"
    current["supersedes_result_id"] = prior["result_id"]
    current["supersedes_path"] = prior_path.relative_to(repository_root).as_posix()
    current["supersedes_sha256"] = sha256_bytes(prior_path.read_bytes())

    with pytest.raises(ResearchRecordError, match="direct lineage cycle"):
        validate_result(current, repository_root=repository_root, verify_artifacts=True)


def test_raw_result_forbids_an_orphan_evidence_assessment_artifact(tmp_path: Path) -> None:
    repository_root, raw = _completed_raw_record(tmp_path)
    raw["artifacts"].append(
        _artifact(
            repository_root,
            artifact_id="orphan-evidence-assessment",
            run_id=raw["runs"][0]["run_id"],
            role="EVIDENCE_ASSESSMENT",
            filename="orphan-evidence-assessment.json",
            content=b'{"assessment":"not actually declared"}\n',
            media_type="application/json",
        )
    )

    with pytest.raises(ResearchRecordError, match="NOT_ASSESSED.*assessment-only"):
        validate_result(raw, repository_root=repository_root, verify_artifacts=True)


@pytest.mark.parametrize("field", ("title", "url", "retrieved_at"))
def test_resolved_citation_metadata_requires_resolver_provenance(
    tmp_path: Path,
    field: str,
) -> None:
    repository_root, raw = _completed_raw_record(tmp_path)
    values = {
        "title": "A title claimed without resolution",
        "url": "https://example.org/unresolved",
        "retrieved_at": FIXED_TIMESTAMP,
    }
    raw["citations"][0][field] = values[field]

    with pytest.raises(ResearchRecordError, match="resolved/validation fields"):
        validate_result(raw, repository_root=repository_root, verify_artifacts=True)


@pytest.mark.parametrize("field", ("title", "url", "retrieved_at"))
def test_unresolved_citation_cannot_claim_resolved_bibliographic_metadata(
    tmp_path: Path,
    field: str,
) -> None:
    repository_root, record = _assessed_record(tmp_path)
    citation = record["citations"][0]
    citation["validation_status"] = "NOT_FOUND"
    citation.pop("normalized_reference")
    values = {
        "title": "A title despite a failed resolver result",
        "url": "https://example.org/not-found",
        "retrieved_at": FIXED_TIMESTAMP,
    }
    citation[field] = values[field]

    with pytest.raises(ResearchRecordError, match="permitted only for VERIFIED"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


@pytest.mark.parametrize(
    ("role", "message"),
    (
        ("PATCH", "non-empty patch"),
        ("DOMAIN_SCHEMA", "non-empty schema"),
    ),
)
def test_proposed_change_requires_nonempty_patch_and_schema_artifacts(
    tmp_path: Path,
    role: str,
    message: str,
) -> None:
    repository_root, record = _recorded_pass_change_record(tmp_path)
    artifact = next(item for item in record["artifacts"] if item["role"] == role)
    artifact_path = repository_root / artifact["path"]
    artifact_path.write_bytes(b"")
    artifact.update({"sha256": sha256_bytes(b""), "size_bytes": 0})

    with pytest.raises(ResearchRecordError, match=message):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


@pytest.mark.parametrize(
    ("fixture", "artifact_role", "message"),
    (
        (_assessed_record, "REFERENCE_VALIDATION", "non-empty resolver output"),
        (_structured_evidence_record, "EVIDENCE_ASSESSMENT", "non-empty assessment output"),
    ),
)
def test_referenced_validation_artifacts_must_preserve_output(
    tmp_path: Path,
    fixture: Any,
    artifact_role: str,
    message: str,
) -> None:
    repository_root, record = fixture(tmp_path)
    artifact = next(
        item for item in record["artifacts"] if item["role"] == artifact_role
    )
    artifact_path = repository_root / artifact["path"]
    artifact_path.write_bytes(b"")
    artifact.update({"sha256": sha256_bytes(b""), "size_bytes": 0})

    with pytest.raises(ResearchRecordError, match=message):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_non_text_evidence_cannot_smuggle_an_unchecked_snippet(tmp_path: Path) -> None:
    repository_root, record = _structured_evidence_record(tmp_path)
    record["evidence"][0]["snippet"] = "A sentence absent from the structured source."

    with pytest.raises(ResearchRecordError, match="only for EXACT_TEXT_MATCH"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


@pytest.mark.parametrize("field", ("summary", "rationale", "field_path"))
def test_proposed_change_narrative_fields_must_be_nonblank(
    tmp_path: Path,
    field: str,
) -> None:
    repository_root, record = _recorded_pass_change_record(tmp_path)
    record["proposed_changes"][0][field] = "   "

    with pytest.raises(ResearchRecordError, match=field):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_live_query_remains_bound_to_the_embedded_profile_and_question(
    tmp_path: Path,
) -> None:
    repository_root, record = _assessed_record(tmp_path)
    record["plan"]["question"]["text"] = "A different question after execution."

    with pytest.raises(ResearchRecordError, match="rendered query"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)
