"""Actual native traversal/matcher controls for CommunityMech #476."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "supporting_reference_canary",
    ROOT / "scripts/adhoc/check_supporting_reference_annotations_20261115.py",
)
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


def test_canonical_reference_and_excerpt_annotations_preserve_optional_snippet():
    schema = yaml.safe_load(canary.SCHEMA.read_text())
    fields = schema["classes"]["SupportingReference"]["attributes"]
    assert fields["reference"]["implements"] == ["linkml:authoritative_reference"]
    assert fields["snippet"]["implements"] == ["linkml:excerpt"]
    assert fields["reference"]["required"] is True
    assert not fields["snippet"].get("required", False)
    assert not fields["reference_title"].get("implements")


@pytest.mark.parametrize("target", ["Discussion", "Dataset"])
def test_real_cli_compares_supporting_reference_and_rejects_mutation(tmp_path, target):
    output = tmp_path / target
    report = canary.run_probe(output, target)
    assert report["passed"], report
    assert [case["native_exit_code"] for case in report["cases"]] == [0, 1, 0]
    assert report["inputs_unchanged"] and not report["refused_operations"]
    assert json.loads((output / "receipt.json").read_text()) == report
    with pytest.raises(FileExistsError):
        canary.run_probe(output, target)


def test_removing_excerpt_annotation_cannot_claim_a_zero_issue_pass(tmp_path):
    schema = yaml.safe_load(canary.SCHEMA.read_text())
    schema["classes"]["SupportingReference"]["attributes"]["snippet"].pop(
        "implements", None
    )
    path = tmp_path / "unannotated.yaml"
    path.write_text(yaml.safe_dump(schema))
    report = canary.run_probe(tmp_path / "negative", schema=path)
    assert not report["passed"]
    assert all(case["events"] == [] for case in report["cases"])
    assert all(case["native_exit_code"] == 0 for case in report["cases"])
