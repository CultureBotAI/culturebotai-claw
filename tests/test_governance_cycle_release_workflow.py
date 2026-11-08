"""The candidate cannot select a canary release before trusted main adopts it."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/governance-fleet-audit.yaml"
DECLARATION = "src/kg_microbe_governance/releases/mech-cycle-v2-canary.json"


def steps():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)["jobs"]["fleet-audit"]["steps"]


@pytest.mark.parametrize("trusted", [False, True])
def test_only_trusted_checkout_selects_the_release_lane(tmp_path, trusted):
    candidate = tmp_path / "control" / DECLARATION
    candidate.parent.mkdir(parents=True)
    candidate.write_text("{}")
    if trusted:
        path = tmp_path / "fleet/trusted-claw" / DECLARATION
        path.parent.mkdir(parents=True)
        path.write_text("{}")
    output = tmp_path / "output"
    step = next(s for s in steps() if s.get("id") == "release-contract")
    result = subprocess.run(["bash", "-c", step["run"]], cwd=tmp_path,
                            env={**os.environ, "GITHUB_OUTPUT": str(output)},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"active={str(trusted).lower()}\n"


def test_exactly_one_audit_lane_runs_and_release_uses_trusted_code():
    entries = steps()
    legacy_names = {
        "Read and compare every committed fleet pin",
        "Authenticate pin against trusted claw history",
        "Audit all governed artifacts at committed main tips",
    }
    legacy = [s for s in entries if s["name"] in legacy_names]
    assert len(legacy) == 3
    assert all(s["if"] == "steps.release-contract.outputs.active != 'true'" for s in legacy)
    release = next(s for s in entries if s["name"] == "Audit the trusted bounded canary release")
    assert release["if"] == "steps.release-contract.outputs.active == 'true'"
    assert "uv run --project fleet/trusted-claw python -m kg_microbe_governance.cycle_release_audit" in release["run"]
    assert '--trusted-root "$GITHUB_WORKSPACE/fleet/trusted-claw"' in release["run"]
    assert '--target-root "$key=$GITHUB_WORKSPACE/fleet/$key"' in release["run"]
    assert "done < fleet/governance-consumers.tsv" in release["run"]
    assert "continue-on-error" not in release
    assert "|| true" not in release["run"]
    candidate = next(s for s in entries if s["name"] == "Validate candidate authority contract")
    assert "control/tests/test_governance_cycle_release_audit.py" in candidate["run"]
    assert "control/tests/test_governance_cycle_release_workflow.py" in candidate["run"]
