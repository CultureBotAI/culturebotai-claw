"""Contracts a reusable workflow must hold before any Mech calls it.

#132 Phase 5 / #180. A `workflow_call` workflow is only executed by a caller,
so claw's own CI cannot run this one -- the canary is the first Mech to adopt
it, and until then the only thing claw can check is the file's shape. These
tests are therefore deliberately about structure, not behaviour, and they say
so rather than implying the workflow has been proven.

What they do catch is the class of defect that would break every caller at
once: an unpinned action, an input the callers rely on going missing, a
default that silently changes what a Mech runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "label-correspondence-reusable.yaml"

# yaml parses the bare `on:` key as the boolean True.
ON = True


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_it_is_callable(workflow):
    assert "workflow_call" in workflow[ON], (
        "a reusable workflow is reached through workflow_call; without it every "
        "caller fails to resolve the reference"
    )


def test_the_inputs_callers_depend_on_exist(workflow):
    """Removing one breaks every Mech at once, and the failure surfaces in the
    caller's repository rather than here."""
    inputs = workflow[ON]["workflow_call"]["inputs"]
    assert set(inputs) >= {
        "python-version",
        "prepare-recipe",
        "drift-report-recipe",
        "enforce-recipe",
        "drift-report-path",
    }


def test_python_version_is_required_and_the_rest_are_not(workflow):
    """The Mechs run 3.10 to 3.12, so there is no defensible default -- guessing
    one would silently run a gate under the wrong interpreter. Everything else
    has a working default so a plain corpus needs three lines to adopt this."""
    inputs = workflow[ON]["workflow_call"]["inputs"]

    assert inputs["python-version"]["required"] is True
    assert "default" not in inputs["python-version"]
    for name, spec in inputs.items():
        if name == "python-version":
            continue
        assert spec.get("required") is False, name
        assert "default" in spec, name


def test_the_prepare_step_is_skipped_when_no_recipe_is_given(workflow):
    """A Mech whose corpus is already on disk passes nothing; `just ''` would
    fail the build for a step it never asked for."""
    steps = workflow["jobs"]["label-correspondence"]["steps"]
    prepare = next(s for s in steps if s.get("name", "").startswith("Build the product"))

    assert prepare["if"] == "inputs.prepare-recipe != ''"


def test_the_drift_report_is_uploaded_even_when_the_gate_fails(workflow):
    """The artifact is triage material. Uploading it only on success would
    withhold it from exactly the runs that need it -- the same shape as #164."""
    steps = workflow["jobs"]["label-correspondence"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Upload drift report")

    assert upload["if"] == "always()"


def test_the_report_is_generated_before_the_gate_runs(workflow):
    """CultureMech generated it only on failure, which loses the passing-run
    baseline a reader compares a regression against."""
    names = [s.get("name", "") for s in workflow["jobs"]["label-correspondence"]["steps"]]

    assert names.index("Generate id-label drift report") < names.index(
        "Enforce id-label correspondence"
    )


@pytest.mark.parametrize(
    "step",
    [
        s
        for s in yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][
            "label-correspondence"
        ]["steps"]
        if "uses" in s
    ],
    ids=lambda s: s["uses"].split("@")[0],
)
def test_every_action_is_pinned_to_a_commit(step):
    """A tag is mutable. This workflow runs in five repositories, so a
    compromised or merely changed tag would move under all of them at once."""
    _, _, ref = step["uses"].partition("@")

    assert re.fullmatch(r"[0-9a-f]{40}", ref), (
        f"{step['uses']} is not pinned to a full commit SHA"
    )


def test_the_permissions_are_read_only(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_the_file_says_it_is_unproven_until_a_mech_calls_it():
    """CLAUDE.md forbids describing an experimental path as implemented because
    a configuration file exists. A reusable workflow with no caller is exactly
    that, and the header has to say so."""
    header = WORKFLOW.read_text(encoding="utf-8").split("name:")[0]

    assert "only exercised by a caller" in header or "proves nothing" in header
