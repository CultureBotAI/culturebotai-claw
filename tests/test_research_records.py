"""Offline adversarial contracts for schema-governed research results.

Every provider fact is injected.  The synthetic ``LIVE`` record below is only a
data fixture for terminal-record validation; no provider client, subprocess, or
network path is constructed or invoked by this module.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kg_microbe_research import (
    ResearchRecordError,
    StaticAvailability,
    StaticProbe,
    build_dry_run_result,
    load_result,
    new_result_path,
    result_yaml,
    sha256_bytes,
    sha256_text,
    validate_result,
    write_result,
)

PROFILE_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "research_profiles"
PROFILE_NAMES = (
    "culturemech",
    "traitmech",
    "mediaingredientmech",
    "communitymech",
    "proteintraitsmech",
)
FIXED_NOW = datetime(2026, 8, 25, 12, 34, 56, tzinfo=timezone.utc)
FAKE_ASTA_KEY = "offline-test-key-MUST-NOT-BE-SERIALIZED"
OFFLINE_AVAILABILITY = StaticAvailability(
    {"asta": ("available", "offline fixture attestation")}
)
NO_LOCAL_TOOLING = StaticProbe()


def _build_record(
    tmp_path: Path,
    profile_name: str = "culturemech",
) -> tuple[Path, Path, Path, dict[str, Any]]:
    """Create a self-contained Mech-shaped repository and dry-run result."""

    repository_root = tmp_path / profile_name
    profile_path = repository_root / "conf" / "deep_research_provider.yaml"
    target_path = repository_root / "data" / "targets" / "fixture.yaml"
    profile_path.parent.mkdir(parents=True)
    target_path.parent.mkdir(parents=True)
    profile_path.write_bytes((PROFILE_FIXTURE_ROOT / f"{profile_name}.yaml").read_bytes())
    target_path.write_text(
        f"id: TEST:{profile_name}\nlabel: Offline {profile_name} target\n",
        encoding="utf-8",
    )

    record = build_dry_run_result(
        repository_root=repository_root,
        profile_path=profile_path,
        target_path=target_path,
        target_id=f"TEST:{profile_name}",
        target_label=f"Offline {profile_name} target",
        target_type="synthetic test record",
        question="Which source-backed facts should a curator assess for this target?",
        availability=OFFLINE_AVAILABILITY,
        environ={"ASTA_API_KEY": FAKE_ASTA_KEY},
        probe=NO_LOCAL_TOOLING,
        now=FIXED_NOW,
        short_id=profile_name,
    )
    return repository_root, profile_path, target_path, record


def _build_synthetic_live_record(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any], Path]:
    """Convert one dry-run skeleton into an entirely local terminal-data fixture."""

    repository_root, _, _, record = _build_record(tmp_path)
    record = deepcopy(record)
    record["status"] = "COMPLETED"
    record["assessment_status"] = "ASSESSED"
    record["assessment_scope"] = (
        "The single synthetic claim against the retained source snapshot."
    )
    run = record["runs"][0]
    for item in record["runs"]:
        item.update(
            {
                "provider": "asta",
                "mode": "LIVE",
                "status": "COMPLETED",
                "provider_called": True,
                "live_authorized": True,
                "usage_authorized": True,
                "usage_authorization_method": "EXPLICIT_ACKNOWLEDGEMENT",
                "started_at": "2026-08-25T12:34:56Z",
                "completed_at": "2026-08-25T12:34:56Z",
                "authorization_reasons": [
                    "synthetic offline fixture models a terminal record without execution"
                ],
            }
        )

    report_path = repository_root / "research" / "artifacts" / "report.md"
    report_path.parent.mkdir(parents=True)
    report_bytes = b"# Synthetic offline provider report\n\nA source should be checked.\n"
    report_path.write_bytes(report_bytes)
    source_path = repository_root / "research" / "artifacts" / "source.txt"
    source_bytes = b"The checked source supports this exact synthetic claim.\n"
    source_path.write_bytes(source_bytes)
    validation_path = repository_root / "research" / "artifacts" / "reference-validation.json"
    validation_bytes = b'{"normalized_reference":"PMID:12345678","resolved":true}\n'
    validation_path.write_bytes(validation_bytes)
    report_relative = report_path.relative_to(repository_root).as_posix()
    report_artifacts = [
        {
            "artifact_id": "artifact-report",
            "run_id": run["run_id"],
            "role": "REPORT",
            "path": report_relative,
            "media_type": "text/markdown",
            "sha256": sha256_bytes(report_bytes),
            "size_bytes": len(report_bytes),
        }
    ]
    for index, later_run in enumerate(record["runs"][1:], start=2):
        later_path = repository_root / "research" / "artifacts" / f"report-{index}.md"
        later_bytes = f"# Synthetic offline provider report {index}\n".encode()
        later_path.write_bytes(later_bytes)
        report_artifacts.append(
            {
                "artifact_id": f"artifact-report-{index}",
                "run_id": later_run["run_id"],
                "role": "REPORT",
                "path": later_path.relative_to(repository_root).as_posix(),
                "media_type": "text/markdown",
                "sha256": sha256_bytes(later_bytes),
                "size_bytes": len(later_bytes),
            }
        )
    record["artifacts"] = [
        *record["artifacts"],
        *report_artifacts,
        {
            "artifact_id": "artifact-source",
            "run_id": run["run_id"],
            "role": "SOURCE_SNAPSHOT",
            "path": source_path.relative_to(repository_root).as_posix(),
            "media_type": "text/plain",
            "sha256": sha256_bytes(source_bytes),
            "size_bytes": len(source_bytes),
            "external_id": "PMID:12345678",
        },
        {
            "artifact_id": "artifact-reference-validation",
            "run_id": run["run_id"],
            "role": "REFERENCE_VALIDATION",
            "path": validation_path.relative_to(repository_root).as_posix(),
            "media_type": "application/json",
            "sha256": sha256_bytes(validation_bytes),
            "size_bytes": len(validation_bytes),
        },
    ]
    record["citations"] = [
        {
            "citation_id": "citation-1",
            "run_id": run["run_id"],
            "raw_reference": "Provider citation PMID 12345678",
            "normalized_reference": "PMID:12345678",
            "validation_status": "VERIFIED",
            "validation_artifact_id": "artifact-reference-validation",
            "validated_by": "offline deterministic fixture",
            "validated_at": "2026-08-25T12:34:56Z",
        }
    ]
    record["evidence"] = [
        {
            "evidence_id": "evidence-1",
            "finding_id": "finding-1",
            "run_id": run["run_id"],
            "citation_id": "citation-1",
            "source_artifact_id": "artifact-source",
            "evidence_source": "PRIMARY_LITERATURE",
            "relevance": "ON_TOPIC",
            "support_level": "SUPPORT",
            "verification_method": "EXACT_TEXT_MATCH",
            "snippet": "The checked source supports this exact synthetic claim.",
            "rationale": "The exact text directly states the synthetic claim.",
            "assessed_by": "offline deterministic fixture",
            "assessed_at": "2026-08-25T12:34:56Z",
        }
    ]
    record["findings"] = [
        {
            "finding_id": "finding-1",
            "statement": "The synthetic claim has a matching local source excerpt.",
            "disposition": "SUPPORT",
            "evidence_ids": ["evidence-1"],
            "rationale": "The exact snippet is present in the checksum-bound report fixture.",
        }
    ]
    return repository_root, record, report_path


@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_all_fleet_profiles_build_and_validate_offline(
    tmp_path: Path,
    profile_name: str,
) -> None:
    repository_root, _, _, record = _build_record(tmp_path, profile_name)

    assert record["plan"]["mech"].casefold() == profile_name
    assert {assignment["provider"] for assignment in record["plan"]["stage_assignments"]} == {
        "asta"
    }
    assert all(run["mode"] == "DRY_RUN" for run in record["runs"])
    assert all(run["provider_called"] is False for run in record["runs"])
    validate_result(
        record,
        repository_root=repository_root,
        verify_artifacts=True,
        verify_snapshots=True,
    )


def test_builder_binds_exact_query_profile_and_target_bytes_without_credentials(
    tmp_path: Path,
) -> None:
    _, profile_path, target_path, record = _build_record(tmp_path)

    assert record["plan"]["profile_sha256"] == sha256_bytes(profile_path.read_bytes())
    assert record["plan"]["question"]["target"]["target_sha256"] == sha256_bytes(
        target_path.read_bytes()
    )
    for run in record["runs"]:
        assert run["query_sha256"] == sha256_text(run["rendered_query"])
    serialized = result_yaml(record)
    assert FAKE_ASTA_KEY not in serialized
    assert "ASTA_API_KEY=" not in serialized


@pytest.mark.parametrize("syntax", ["duplicate", "anchor", "alias"])
def test_strict_yaml_rejects_ambiguous_mapping_syntax(
    tmp_path: Path,
    syntax: str,
) -> None:
    _, _, _, record = _build_record(tmp_path)
    text = result_yaml(record)
    if syntax == "duplicate":
        text += "status: DRY_RUN\n"
    elif syntax == "anchor":
        text = text.replace("research_version: 1", "research_version: &version 1", 1)
    else:
        text = text.replace(
            f"result_id: {record['result_id']}",
            "result_id: *forbidden-alias",
            1,
        )
    path = tmp_path / f"{syntax}.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ResearchRecordError, match="strict YAML"):
        load_result(path)


def test_closed_schema_rejects_unknown_keys(tmp_path: Path) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["unrestricted_metadata"] = {"secret": "escape hatch"}

    with pytest.raises(ResearchRecordError, match="LinkML validation failed"):
        validate_result(record)


def test_semantic_validation_rejects_query_tampering(tmp_path: Path) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["runs"][0]["rendered_query"] += "\nUnbound injected instruction."

    with pytest.raises(ResearchRecordError, match="query_sha256"):
        validate_result(record)


@pytest.mark.parametrize("snapshot", ["profile", "target"])
def test_capture_time_snapshot_verification_rejects_source_drift(
    tmp_path: Path,
    snapshot: str,
) -> None:
    repository_root, profile_path, target_path, record = _build_record(tmp_path)
    changed = profile_path if snapshot == "profile" else target_path
    changed.write_bytes(changed.read_bytes() + b"\n# drift after capture\n")

    with pytest.raises(ResearchRecordError, match="sha256 does not match"):
        validate_result(
            record,
            repository_root=repository_root,
            verify_snapshots=True,
        )


def test_validator_rejects_provider_aliases_in_persisted_records(tmp_path: Path) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["plan"]["stage_assignments"][0]["provider"] = "edison"
    record["runs"][0]["requested_provider"] = "edison"

    with pytest.raises(ResearchRecordError, match="LinkML validation failed|canonical provider"):
        validate_result(record)


def test_semantic_validation_rejects_dangling_plan_ids(tmp_path: Path) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["runs"][0]["plan_id"] = "plan-does-not-exist"

    with pytest.raises(ResearchRecordError, match="does not reference plan.plan_id"):
        validate_result(record)


def test_identifiers_are_unique_across_the_entire_bundle(tmp_path: Path) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["runs"][1]["run_id"] = record["runs"][0]["run_id"]

    with pytest.raises(ResearchRecordError, match="duplicates identifier"):
        validate_result(record)


def test_semantic_validation_rejects_reversed_timestamps(tmp_path: Path) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["plan"]["created_at"] = "2026-08-25T12:35:00Z"

    with pytest.raises(ResearchRecordError, match="must not be after generated_at"):
        validate_result(record)


@pytest.mark.parametrize(
    ("field", "value"),
    (("provider_called", True), ("provider_task_id", "fabricated-task")),
)
def test_dry_run_lifecycle_contradictions_fail(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["runs"][0][field] = value

    with pytest.raises(ResearchRecordError, match="not a valid dry run"):
        validate_result(record)


def test_no_paid_plan_cannot_contain_a_metered_run(tmp_path: Path) -> None:
    _, _, _, record = _build_record(tmp_path)
    record["plan"]["no_paid"] = True

    with pytest.raises(ResearchRecordError, match="violates plan.no_paid"):
        validate_result(record)


def test_artifact_traversal_is_rejected(tmp_path: Path) -> None:
    repository_root, record, _ = _build_synthetic_live_record(tmp_path)
    report = next(item for item in record["artifacts"] if item["role"] == "REPORT")
    report["path"] = "../outside.md"

    with pytest.raises(ResearchRecordError, match="LinkML validation failed|repository-relative"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_artifact_symlink_cannot_escape_repository(tmp_path: Path) -> None:
    repository_root, record, _ = _build_synthetic_live_record(tmp_path)
    outside = tmp_path / "outside-source.md"
    outside_bytes = b"outside repository bytes\n"
    outside.write_bytes(outside_bytes)
    escape = repository_root / "research" / "artifacts" / "escape.md"
    try:
        escape.symlink_to(outside)
    except OSError as exc:  # pragma: no cover - platform capability
        pytest.skip(f"symlinks unavailable: {exc}")
    artifact = next(item for item in record["artifacts"] if item["role"] == "REPORT")
    artifact.update(
        {
            "path": escape.relative_to(repository_root).as_posix(),
            "sha256": sha256_bytes(outside_bytes),
            "size_bytes": len(outside_bytes),
        }
    )

    with pytest.raises(ResearchRecordError, match="inside repository root"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (("size_bytes", 1, "size_bytes does not match"), ("sha256", "0" * 64, "sha256 does not match")),
)
def test_artifact_size_and_hash_are_verified_against_bytes(
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    repository_root, record, _ = _build_synthetic_live_record(tmp_path)
    report = next(item for item in record["artifacts"] if item["role"] == "REPORT")
    report[field] = replacement

    with pytest.raises(ResearchRecordError, match=message):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_verified_snippet_must_occur_in_its_source_artifact(tmp_path: Path) -> None:
    repository_root, record, _ = _build_synthetic_live_record(tmp_path)
    record["evidence"][0]["snippet"] = "This sentence is absent from the source."

    with pytest.raises(ResearchRecordError, match="snippet was not found"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_unverified_reference_cannot_support_an_assessed_finding(tmp_path: Path) -> None:
    repository_root, record, _ = _build_synthetic_live_record(tmp_path)
    record["citations"][0]["validation_status"] = "NOT_FOUND"

    record["citations"][0].pop("normalized_reference")

    with pytest.raises(ResearchRecordError, match="must be independently VERIFIED"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_completed_run_requires_a_primary_report_artifact(tmp_path: Path) -> None:
    repository_root, record, _ = _build_synthetic_live_record(tmp_path)
    report = next(item for item in record["artifacts"] if item["role"] == "REPORT")
    report["role"] = "PROVIDER_RESPONSE"

    with pytest.raises(ResearchRecordError, match="has no REPORT artifact"):
        validate_result(record, repository_root=repository_root, verify_artifacts=True)


def test_atomic_writer_round_trips_refuses_clobber_and_leaves_no_temp_files(
    tmp_path: Path,
) -> None:
    repository_root, _, _, record = _build_record(tmp_path)
    destination = new_result_path(
        repository_root,
        target_id=record["plan"]["question"]["target"]["target_id"],
        result_id=record["result_id"],
    )

    assert write_result(destination, record, repository_root=repository_root) == destination
    original_bytes = destination.read_bytes()
    assert load_result(
        destination,
        repository_root=repository_root,
        verify_artifacts=True,
        verify_snapshots=True,
    ) == record

    with pytest.raises(FileExistsError, match="append-only"):
        write_result(destination, record, repository_root=repository_root)
    assert destination.read_bytes() == original_bytes
    assert list(destination.parent.glob(f".{destination.name}.tmp-*")) == []

    invalid = deepcopy(record)
    invalid["runs"][0]["rendered_query"] += "\ntampered"
    rejected = destination.with_name("rejected.yaml")
    with pytest.raises(ResearchRecordError, match="query_sha256"):
        write_result(rejected, invalid, repository_root=repository_root)
    assert not rejected.exists()
    assert list(rejected.parent.glob(f".{rejected.name}.tmp-*")) == []


def test_writer_refuses_a_destination_outside_the_repository(tmp_path: Path) -> None:
    repository_root, _, _, record = _build_record(tmp_path)
    outside = tmp_path / "outside.yaml"

    with pytest.raises(ResearchRecordError, match="must stay inside repository root"):
        write_result(outside, record, repository_root=repository_root)
    assert not outside.exists()
