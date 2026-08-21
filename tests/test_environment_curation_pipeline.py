"""Behavioral tests for the environment-curation orchestration boundary."""

import json
from pathlib import Path

import pytest

from pipelines.environment_curation_pipeline import (
    ApplyModeUnavailableError,
    EnvironmentCurationPipeline,
)


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
