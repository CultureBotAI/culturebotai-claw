"""Offline structural checks for the fleet id-label audit workflow."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "id-label-canon.yaml"


def test_fleet_audit_installs_uv_before_manifest_driven_script():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["fleet-audit"]["steps"]

    uv_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses") == "astral-sh/setup-uv@v7"
    )
    audit_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("run") == "bash scripts/audit_idlabel_fleet.sh"
    )

    assert uv_index < audit_index
