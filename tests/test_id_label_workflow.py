"""Offline structural checks for the authoritative id-label workflow."""

import json
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ID_LABEL_WORKFLOW = ROOT / ".github" / "workflows" / "id-label-canon.yaml"
FLEET_AUDIT_WORKFLOW = (
    ROOT / ".github" / "workflows" / "governance-fleet-audit.yaml"
)
FLEET_DOCUMENT = yaml.safe_load(
    (ROOT / "src" / "kg_microbe_fleet" / "fleet.yaml").read_text(
        encoding="utf-8"
    )
)
FLEET_KEYS = frozenset(FLEET_DOCUMENT["mechs"])
FLEET_IDENTITIES = {
    key: mech["github"] for key, mech in FLEET_DOCUMENT["mechs"].items()
}
GOVERNANCE_DOCUMENT = json.loads(
    (
        ROOT
        / "src"
        / "kg_microbe_governance"
        / "vendored_artifacts.json"
    ).read_text(encoding="utf-8")
)
CHECKOUT_ACTION = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
SETUP_UV_ACTION = "astral-sh/setup-uv@94527f2e458b27549849d47d273a16bec83a01e9"
CANONICAL_ID_LABEL_TESTS = {
    "tests/test_id_label_empty_adapter.py",
    "tests/test_id_label_unknown_prefix.py",
    "tests/test_id_label_plausibility.py",
}


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(path: Path, job: str) -> list[dict]:
    return _workflow(path)["jobs"][job]["steps"]


def _run_steps(path: Path, job: str) -> list[str]:
    return [step["run"] for step in _steps(path, job) if "run" in step]


def test_fleet_audit_is_scheduled_and_unfiltered() -> None:
    text = FLEET_AUDIT_WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "  pull_request:\n" in text
    assert "paths:" not in text


def test_id_label_contract_remains_a_nightly_dependency_canary() -> None:
    text = ID_LABEL_WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert 'cron: "51 6 * * *"' in text


def test_fleet_and_governance_manifests_define_the_same_consumers() -> None:
    assert set(GOVERNANCE_DOCUMENT["consumers"]) == FLEET_KEYS
    assert {
        key: consumer["github"]
        for key, consumer in GOVERNANCE_DOCUMENT["consumers"].items()
    } == FLEET_IDENTITIES


def test_fleet_audit_uses_only_immutable_local_claw_checkouts() -> None:
    checkouts = [
        step
        for step in _steps(FLEET_AUDIT_WORKFLOW, "fleet-audit")
        if step.get("uses", "").startswith("actions/checkout@")
    ]

    assert len(checkouts) == 2
    assert all(step["uses"] == CHECKOUT_ACTION for step in checkouts)
    assert all("repository" not in step.get("with", {}) for step in checkouts)
    by_path = {step["with"]["path"]: step for step in checkouts}
    assert set(by_path) == {"control", "fleet/trusted-claw"}
    assert all(
        step["with"].get("persist-credentials") is False
        for step in checkouts
    )
    trusted = by_path["fleet/trusted-claw"]["with"]
    assert trusted["fetch-depth"] == 0
    assert "github.event_name == 'pull_request'" in trusted["ref"]
    assert "github.event.pull_request.base.sha" in trusted["ref"]
    assert "github.event_name == 'push'" in trusted["ref"]
    assert "github.sha" in trusted["ref"]
    assert "|| 'main'" in trusted["ref"]


def test_runtime_mech_checkouts_and_sparse_paths_come_from_manifest() -> None:
    runs = _run_steps(FLEET_AUDIT_WORKFLOW, "fleet-audit")
    export = next(run for run in runs if "load_governance_manifest" in run)
    checkout = next(run for run in runs if "git clone" in run)
    workflow_text = FLEET_AUDIT_WORKFLOW.read_text(encoding="utf-8")

    assert "manifest.consumers.values()" in export
    assert "manifest.pin_path" in export
    assert "governance-consumers.tsv" in checkout
    assert "kg-microbe-governance list" in checkout
    assert "sparse-checkout set --no-cone" in checkout
    assert "--branch main" in checkout
    assert all(identity not in workflow_text for identity in FLEET_IDENTITIES.values())
    assert all(key not in workflow_text for key in FLEET_KEYS)


def test_fleet_audit_installs_and_syncs_uv_before_audit() -> None:
    steps = _steps(FLEET_AUDIT_WORKFLOW, "fleet-audit")
    uv_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses") == SETUP_UV_ACTION
    )
    sync_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("run", "").strip()
        == "uv sync --project fleet/trusted-claw --locked"
    )
    audit_index = next(
        index
        for index, step in enumerate(steps)
        if "audit_args" in step.get("run", "")
        and "kg-microbe-governance" in step.get("run", "")
    )

    assert uv_index < sync_index < audit_index


def test_fleet_audit_authenticates_unanimous_committed_pins_before_audit() -> None:
    steps = _steps(FLEET_AUDIT_WORKFLOW, "fleet-audit")
    pin_index, pin_step = next(
        (index, step)
        for index, step in enumerate(steps)
        if step.get("id") == "fleet-pin"
    )
    auth_index, auth_step = next(
        (index, step)
        for index, step in enumerate(steps)
        if "merge-base --is-ancestor" in step.get("run", "")
    )
    audit_index = next(
        index
        for index, step in enumerate(steps)
        if "audit_args" in step.get("run", "")
        and "kg-microbe-governance" in step.get("run", "")
    )

    pin_run = pin_step["run"]
    assert 'f"HEAD:{pin_path}"' in pin_run
    assert 'rb"[0-9a-f]{40}\\n?"' in pin_run
    assert "set(pins.values())" in pin_run
    assert "len(unique) != 1" in pin_run
    assert "GITHUB_OUTPUT" in pin_run
    auth_run = auth_step["run"]
    assert "fleet/trusted-claw cat-file" in auth_run
    assert "fleet/trusted-claw merge-base --is-ancestor" in auth_run
    assert pin_index < auth_index < audit_index


def test_fleet_audit_builds_cli_roots_from_every_manifest_row() -> None:
    audit = next(
        run
        for run in _run_steps(FLEET_AUDIT_WORKFLOW, "fleet-audit")
        if "audit_args" in run and "kg-microbe-governance" in run
    )
    assert "fleet-audit" in audit and "--ref" in audit
    assert "done < fleet/governance-consumers.tsv" in audit
    assert '--target-root "$key=$GITHUB_WORKSPACE/fleet/$key"' in audit
    assert all(key not in audit for key in FLEET_KEYS)


def test_fleet_audit_separately_validates_candidate_authority_contract() -> None:
    candidate = next(
        run
        for run in _run_steps(FLEET_AUDIT_WORKFLOW, "fleet-audit")
        if "uv sync --project control --locked --extra dev" in run
    )
    assert "uv run --project control --extra dev python -m pytest" in candidate
    assert "control/tests/test_fleet_manifest.py" in candidate
    assert "control/tests/test_kg_microbe_governance.py" in candidate
    assert "control/tests/test_id_label_workflow.py" in candidate
    assert "control/tests/test_authoritative_governance_layout.py" in candidate


def test_behavior_job_runs_exactly_the_three_nested_canonical_suites() -> None:
    steps = _steps(ID_LABEL_WORKFLOW, "id-label-contract")
    pytest_steps = [
        step for step in steps if "python -m pytest" in step.get("run", "")
    ]
    assert len(pytest_steps) == 1
    assert (
        pytest_steps[0].get("working-directory")
        == "src/kg_microbe_governance/artifacts"
    )
    selected = {
        token
        for token in shlex.split(pytest_steps[0]["run"].replace("\\\n", " "))
        if token.endswith(".py") and "test_id_label_" in token
    }
    assert selected == CANONICAL_ID_LABEL_TESTS


def test_workflow_has_no_legacy_hub_or_compatibility_path() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ID_LABEL_WORKFLOW, FLEET_AUDIT_WORKFLOW)
    )
    legacy_script = "scripts" + "/audit_idlabel_fleet.sh"
    retired_shared_paths = (
        "shared" + "/idlabel",
        "shared" + "/spoke",
    )

    assert legacy_script not in text
    assert "--require-vendored-hub" not in text
    assert all(path not in text for path in retired_shared_paths)
