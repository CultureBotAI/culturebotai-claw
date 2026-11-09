"""Execute the evidence workflow's pin reader and inspect its real dataflow."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from kg_microbe_governance.workflow_pins import load_pin_contract, render_workflow

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "src/kg_microbe_governance/artifacts/workflows/qc-evidence.yaml"


def document():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def steps():
    return document()["jobs"]["qc"]["steps"]


def pin_step():
    return next(step for step in steps() if step.get("id") == "claw-pin")


def run_pin(tmp_path, pin):
    path = tmp_path / "mech/scripts/.vendored_canon_ref"
    path.parent.mkdir(parents=True)
    if pin is not None:
        path.write_bytes(pin)
    output = tmp_path / "github-output"
    result = subprocess.run(["bash", "-c", pin_step()["run"]], cwd=tmp_path,
                            capture_output=True, text=True,
                            env={**os.environ, "GITHUB_OUTPUT": str(output)}, timeout=15)
    return result, output


def test_consumer_pin_drives_claw_checkout_and_malformed_pin_has_no_output(tmp_path):
    # Distinct values prove the source is the consumer file, not a hard-coded SHA.
    for index, pin in enumerate([b"a" * 40 + b"\n", b"b" * 40]):
        root = tmp_path / str(index)
        result, output = run_pin(root, pin)
        assert result.returncode == 0, result.stderr
        assert output.read_text() == "ref=" + pin.decode().strip() + "\n"
    checkout = next(step for step in steps() if step.get("with", {}).get("path") == "claw")
    assert checkout["with"]["ref"] == "${{ steps.claw-pin.outputs.ref }}"
    assert checkout["with"]["repository"] == "CultureBotAI/culturebotai-claw"
    assert steps().index(pin_step()) < steps().index(checkout)


@pytest.mark.parametrize("pin", [None, b"main\n", b"a" * 39, b"A" * 40,
                                 b"a" * 40 + b"\nother=x", b"a" * 40 + b"\n\n"])
def test_invalid_pin_fails_before_any_checkout_output(tmp_path, pin):
    result, output = run_pin(tmp_path, pin)
    assert result.returncode != 0
    assert not output.exists()


def test_workflow_pin_reader_rejects_symlink(tmp_path):
    path = tmp_path / "mech/scripts/.vendored_canon_ref"
    path.parent.mkdir(parents=True)
    source = tmp_path / "source"
    source.write_text("a" * 40)
    path.symlink_to(source)
    output = tmp_path / "github-output"
    result = subprocess.run(["bash", "-c", pin_step()["run"]], cwd=tmp_path,
                            capture_output=True, text=True,
                            env={**os.environ, "GITHUB_OUTPUT": str(output)}, timeout=15)
    assert result.returncode != 0 and not output.exists()


def test_required_events_pins_permissions_and_exact_active_worktree():
    workflow = document()
    assert workflow["on"]["pull_request"] == ""
    assert workflow["on"]["merge_group"]["types"] == ["checks_requested"]
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert render_workflow(WORKFLOW.read_text(), load_pin_contract()) == WORKFLOW.read_text()
    checkouts = [step for step in steps() if step.get("uses", "").startswith("actions/checkout@")]
    assert {step["with"]["path"] for step in checkouts} == {"mech", "claw"}
    assert all(step["with"]["persist-credentials"] == "false" for step in checkouts)
    validation = next(step for step in steps() if "--strict" in step.get("run", ""))
    assert validation["working-directory"] == "mech"
    assert validation["env"] == {"CLAW_ROOT": "${{ github.workspace }}/claw"}
    assert validation["run"] == "uv run --project ../claw --frozen python -I scripts/run_shared_evidence_validator.py --strict"
    assert any(step.get("run") == "uv sync --project claw --locked" for step in steps())
    summary = steps()[-1]
    assert summary["if"] == "always()"
    assert "mech/workspace/reports/evidence_reference_validation.md" in summary["run"]
