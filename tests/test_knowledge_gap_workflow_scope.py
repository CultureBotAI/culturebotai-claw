"""The kgscan workflow derives its explicit scope from the fleet manifest."""

import json
import subprocess
import sys
from pathlib import Path

import yaml

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "knowledge-gap-scan.yaml"
SCOPE_DOC = ROOT / "docs" / "KGSCAN_SCOPE.md"
MATRIX_COMMAND = (
    "uv run python -m kg_microbe_fleet matrix "
    "--capability knowledge_gap_scan --setting window"
)


def test_scheduled_scan_uses_the_manifest_matrix_command():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    prepare = workflow["jobs"]["prepare"]
    scan = workflow["jobs"]["scan"]

    matrix_step = next(step for step in prepare["steps"] if step.get("id") == "matrix")
    assert MATRIX_COMMAND in matrix_step["run"]
    assert prepare["outputs"]["matrix"] == "${{ steps.matrix.outputs.matrix }}"
    assert scan["needs"] == "prepare"
    assert scan["strategy"]["matrix"] == (
        "${{ fromJSON(needs.prepare.outputs.matrix) }}"
    )
    assert "include" not in scan["strategy"]


def test_matrix_cli_matches_enabled_manifest_capability_offline():
    manifest = load_fleet_manifest()
    enabled_keys = manifest.with_capability("knowledge_gap_scan")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kg_microbe_fleet",
            "matrix",
            "--capability",
            "knowledge_gap_scan",
            "--setting",
            "window",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    matrix = json.loads(completed.stdout)
    legs = matrix["include"]

    assert tuple(leg["mech"] for leg in legs) == tuple(
        manifest.get(key).display_name for key in enabled_keys
    )
    assert tuple(leg["repository"] for leg in legs) == tuple(
        manifest.get(key).github for key in enabled_keys
    )
    assert all(leg["checkout_path"] == leg["mech"] for leg in legs)
    assert all(leg["workdir"] == leg["checkout_path"] for leg in legs)
    assert all(isinstance(leg["window"], int) and leg["window"] > 0 for leg in legs)
    assert "ProteinTraitsMech" not in {leg["mech"] for leg in legs}


def test_proteintraits_exclusion_is_documented_as_intentional():
    text = SCOPE_DOC.read_text(encoding="utf-8")
    assert "ProteinTraitsMech is intentionally excluded" in text
    assert "no `discussions` field" in text
    assert "more than 1,400 runs" in text
