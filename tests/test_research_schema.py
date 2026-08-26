"""Load-bearing LinkML and vocabulary checks for research-result records."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import UniqueKeySafeLoader, load_fleet_manifest
from kg_microbe_research import (
    BILLING_CLASSES,
    COST_VALUE,
    PROVIDERS,
    StaticAvailability,
    StaticProbe,
    build_dry_run_result,
    default_research_schema_path,
    result_yaml,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPOSITORY_ROOT / "src/kg_microbe_research/schema/research.yaml"
PROFILE = REPOSITORY_ROOT / "tests/fixtures/research_profiles/culturemech.yaml"
GUIDE = REPOSITORY_ROOT / "docs/guides/DEEP_RESEARCH_RESULTS.md"


def _permissible_values(schema: dict, enum: str) -> set[str]:
    return set(schema["enums"][enum]["permissible_values"])


def test_default_schema_is_the_packaged_research_authority() -> None:
    assert default_research_schema_path().resolve() == SCHEMA.resolve()


def test_schema_vocabularies_cannot_drift_from_provider_and_fleet_contracts() -> None:
    schema = yaml.load(SCHEMA.read_text(encoding="utf-8"), Loader=UniqueKeySafeLoader)
    manifest = load_fleet_manifest()

    assert _permissible_values(schema, "MechEnum") == {
        mech.display_name for mech in manifest.mechs.values()
    }
    assert _permissible_values(schema, "ProviderEnum") == set(PROVIDERS)
    assert _permissible_values(schema, "BillingClassEnum") == set(BILLING_CLASSES)
    assert _permissible_values(schema, "RelativeCostEnum") == set(COST_VALUE)
    assert _permissible_values(schema, "ProviderStatusEnum") == {
        "available",
        "configured",
        "blocked",
        "unavailable",
        "stub",
    }
    assert _permissible_values(schema, "ResearchResultStatusEnum") == {
        "DRY_RUN",
        "COMPLETED",
        "PARTIAL",
        "FAILED",
        "UNUSABLE",
    }
    assert _permissible_values(schema, "ResearchAssessmentStatusEnum") == {
        "NOT_ASSESSED",
        "PARTIALLY_ASSESSED",
        "ASSESSED",
    }
    assert _permissible_values(schema, "ChangeValidationStatusEnum") == {
        "NOT_RUN",
        "RECORDED_PASS",
        "RECORDED_FAILURE",
        "ERROR",
    }


def test_schema_contains_every_phase_two_research_class() -> None:
    classes = yaml.load(SCHEMA.read_text(encoding="utf-8"), Loader=UniqueKeySafeLoader)[
        "classes"
    ]
    assert {
        "ResearchQuestion",
        "ResearchPlan",
        "ResearchProviderEvaluation",
        "ResearchStageAssignment",
        "ResearchRun",
        "ResearchCitation",
        "ResearchArtifact",
        "ResearchEvidence",
        "ResearchFinding",
        "ProposedChange",
        "ResearchResult",
    } <= set(classes)
    assert classes["ResearchResult"]["tree_root"] is True


def test_result_guide_uses_schema_statuses_and_append_only_relationship_fields() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    for status in ("DRY_RUN", "COMPLETED", "PARTIAL", "FAILED", "UNUSABLE"):
        assert f"`{status}`" in guide
    assert "`succeeded`" not in guide
    assert "`cancelled`" not in guide
    assert "supersedes_result_id" in guide
    assert "assessment_of_result_id" in guide


@pytest.mark.skipif(shutil.which("linkml-validate") is None, reason="linkml not installed")
def test_real_dry_run_skeleton_validates_with_linkml_cli(tmp_path: Path) -> None:
    """Exercise LinkML itself; Python-only checks cannot catch a wrong slot name."""

    record = build_dry_run_result(
        repository_root=REPOSITORY_ROOT,
        profile_path=PROFILE,
        target_path=REPOSITORY_ROOT / "README.md",
        target_id="schema-smoke",
        target_label="Schema smoke target",
        target_type="medium",
        question="Which evidence should be collected for this target?",
        availability=StaticAvailability(
            {"asta": ("available", "offline schema fixture")}
        ),
        environ={"ASTA_API_KEY": "offline-schema-fixture"},
        probe=StaticProbe(),
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
        short_id="schema-smoke",
    )
    result_path = tmp_path / "research.yaml"
    result_path.write_text(result_yaml(record), encoding="utf-8")

    completed = subprocess.run(
        [
            "linkml-validate",
            "--schema",
            str(SCHEMA),
            "--target-class",
            "ResearchResult",
            str(result_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
