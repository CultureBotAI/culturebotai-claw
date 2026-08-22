"""Behavioral tests for the environment-curation orchestration boundary."""

import json
from pathlib import Path

import pytest

from pipelines.environment_curation_pipeline import (
    ApplyModeUnavailableError,
    EnvironmentCurationPipeline,
)
from plugins.environment_curator import EnvironmentSuggestion, EnvironmentTerm, Evidence


def _minimal_pipeline(tmp_path: Path) -> EnvironmentCurationPipeline:
    pipeline = object.__new__(EnvironmentCurationPipeline)
    pipeline.default_batch_size = 20
    pipeline.default_threshold = 0.9
    pipeline.manual_review_threshold = 0.7
    pipeline.reports_dir = tmp_path / "reports"
    pipeline.reports_dir.mkdir()
    pipeline._prioritize_candidates = lambda records, tier, size: records
    pipeline._generate_suggestions = lambda records: []
    pipeline._save_manual_review_queue = lambda suggestions: None
    return pipeline


def _suggestion(media_id: str) -> EnvironmentSuggestion:
    return EnvironmentSuggestion(
        media_id=media_id,
        media_name=f"Medium {media_id}",
        environment=EnvironmentTerm(
            preferred_term="soil",
            envo_id="ENVO:00002982",
            confidence=1.0,
        ),
        evidence=Evidence(
            reference="PMID:12345678",
            snippet="supporting evidence",
            explanation="test evidence",
        ),
        reasoning="A sufficiently detailed test rationale for the environment.",
    )


def test_apply_mode_fails_before_creating_artifacts(tmp_path):
    pipeline = _minimal_pipeline(tmp_path)

    with pytest.raises(ApplyModeUnavailableError, match="atomic writer"):
        pipeline.run([], dry_run=False)

    assert list(pipeline.reports_dir.iterdir()) == []


def test_dry_run_report_contains_final_status_and_timing(tmp_path):
    pipeline = _minimal_pipeline(tmp_path)

    result = pipeline.run([], dry_run=True)

    [report_path] = list(pipeline.reports_dir.glob("*.json"))
    report = json.loads(report_path.read_text())
    assert result["status"] == "success"
    assert report["status"] == "success"
    assert report["end_time"]
    assert report["duration_seconds"] is not None


def test_dry_run_reports_partial_failure_when_one_suggestion_errors(tmp_path):
    pipeline = _minimal_pipeline(tmp_path)
    successful = _suggestion("successful")
    broken = _suggestion("broken")
    pipeline._generate_suggestions = lambda records: [successful, broken]

    def validate_citation(suggestion):
        if suggestion.media_id == "broken":
            raise RuntimeError("citation service failed")
        suggestion.citation_valid = True
        suggestion.citation_validity_score = 1.0
        suggestion.snippet_accuracy_score = 1.0

    def validate_envo(suggestion):
        suggestion.ontology_valid = True
        suggestion.envo_correctness_score = 1.0

    def score(suggestion):
        suggestion.schema_valid = True
        suggestion.cross_consistent = True
        suggestion.reasoning_coherence_score = 1.0
        suggestion.calculate_evidence_quality_score()

    pipeline._validate_citation = validate_citation
    pipeline._validate_envo_term = validate_envo
    pipeline._score_evidence_quality = score

    result = pipeline.run([{"id": "source"}], dry_run=True)

    [report_path] = list(pipeline.reports_dir.glob("*.json"))
    report = json.loads(report_path.read_text())
    assert result["status"] == "partial_failure"
    assert [item.media_id for item in result["auto_accepted"]] == ["successful"]
    assert result["errors"] == [
        {"media_id": "broken", "error": "citation service failed"}
    ]
    assert report["status"] == "partial_failure"
    assert report["errors_count"] == 1
    assert report["end_time"]
    assert report["duration_seconds"] is not None


def test_dry_run_reports_failed_when_pipeline_setup_errors(tmp_path):
    pipeline = _minimal_pipeline(tmp_path)

    def fail_prioritization(records, tier, size):
        raise RuntimeError("candidate source unavailable")

    pipeline._prioritize_candidates = fail_prioritization

    result = pipeline.run([{"id": "source"}], dry_run=True)

    [report_path] = list(pipeline.reports_dir.glob("*.json"))
    report = json.loads(report_path.read_text())
    assert result["status"] == "failed"
    assert result["error"] == "candidate source unavailable"
    assert report["status"] == "failed"
    assert report["error"] == "candidate source unavailable"
    assert report["end_time"]
    assert report["duration_seconds"] is not None
