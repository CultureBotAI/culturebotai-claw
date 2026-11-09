"""Closed public coverage and public-only rollout have real negative controls."""

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import test_private_scaleup_audit as fixtures
import yaml
from test_automatic_private_audit import MetadataAPI, binding

from kg_microbe_governance import automatic_fleet_component as component
from kg_microbe_governance import automatic_private_audit as auto
from kg_microbe_governance import automatic_private_audit_cli as cli
from kg_microbe_governance import private_scaleup_audit as manual
from kg_microbe_merge_queue import workflow_errors

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/governance-fleet-audit.yaml"


@pytest.fixture
def public_report():
    source = fixtures.source.__wrapped__()
    source_manifest = manual.parse_json(source[1][manual.CANONICAL_MANIFEST_PATH])
    source_manifest["consumers"]["publicmech"] = {
        "github": "CultureBotAI/PublicMech",
        "package_path": "src/publicmech",
    }
    model = manual.parse_manifest(auto.canonical(source_manifest))
    public = MetadataAPI(source)
    bound = binding(public)
    hashes = dict(protected="a" * 64, candidate="b" * 64)
    values = dict(protected=model, candidate=model)
    count = len(model.artifacts_for(model.consumers["publicmech"]))
    row = {
        "key": "publicmech",
        "github": "CultureBotAI/PublicMech",
        "head": "f" * 40,
        "pin": "c" * 40,
        "state": "audited",
        "expected_artifacts": count,
        "checked_artifacts": count,
        "issues": [],
    }
    report = {
        "version": 1,
        "kind": "public_fleet_component",
        "parent": bound,
        "manifest_sha256": hashes,
        "public_component_ok": True,
        "full_fleet_ok": False,
        "private_required": True,
        "lanes": {
            "protected": [row],
            "candidate": [{**row, "pin": None, "state": "tracked"}],
        },
    }
    return public, bound, values, hashes, report


def test_authenticated_public_report_preserves_private_incompleteness(
    public_report, monkeypatch, tmp_path
):
    public, bound, values, hashes, report = public_report
    monkeypatch.setattr(component, "manifests", lambda *a: (values, hashes))
    monkeypatch.setattr(component, "bootstrap_refs", lambda *a: {})
    monkeypatch.setattr(
        auto,
        "artifact_bytes",
        lambda *a: (auto.canonical(report), {"created_at": "2026-11-09T00:00:01Z"}),
    )
    public.parent["run_started_at"] = "2026-11-09T00:00:00Z"
    actual = component.authenticate_report(public, tmp_path, bound)
    assert actual["full_fleet_ok"] is False
    with pytest.raises(manual.AuditError):
        component.finalize(public, tmp_path, bound, None, report=actual)


@pytest.mark.parametrize(
    "change",
    [
        "missing_state",
        "unknown_state",
        "key_only",
        "extra_field",
        "missing_row",
        "duplicate",
        "wrong_identity",
        "false_aggregate",
        "claimed_full_success",
        "wrong_manifest",
        "wrong_attempt",
        "short_count",
        "bool_count",
        "issues",
        "unproven_bootstrap",
        "private_in_public",
    ],
)
def test_real_download_boundary_refuses_malformed_success(
    public_report, monkeypatch, tmp_path, change
):
    public, bound, values, hashes, report = public_report
    row = report["lanes"]["protected"][0]
    if change == "missing_state":
        del row["state"]
    elif change == "unknown_state":
        row["state"] = "looks_fine"
    elif change == "key_only":
        report["lanes"]["protected"][0] = {"key": "publicmech"}
    elif change == "extra_field":
        row["unverified"] = True
    elif change == "missing_row":
        report["lanes"]["candidate"] = []
    elif change == "duplicate":
        report["lanes"]["candidate"].append(
            copy.deepcopy(report["lanes"]["candidate"][0])
        )
    elif change == "wrong_identity":
        row["github"] = "attacker/PublicMech"
    elif change == "false_aggregate":
        report["public_component_ok"] = False
    elif change == "claimed_full_success":
        report["full_fleet_ok"] = True
    elif change == "wrong_manifest":
        report["manifest_sha256"] = dict(hashes, candidate="0" * 64)
    elif change == "wrong_attempt":
        report["parent"] = dict(bound, run_attempt=2)
    elif change == "short_count":
        row["checked_artifacts"] -= 1
    elif change == "bool_count":
        row["expected_artifacts"] = True
    elif change == "issues":
        row["issues"] = ["failed"]
    elif change == "unproven_bootstrap":
        row.update(state="pending_bootstrap", pin=None, checked_artifacts=0)
    else:
        row["key"] = "scaleupmech"
    monkeypatch.setattr(component, "manifests", lambda *a: (values, hashes))
    monkeypatch.setattr(component, "bootstrap_refs", lambda *a: {})
    monkeypatch.setattr(
        auto,
        "artifact_bytes",
        lambda *a: (auto.canonical(report), {"created_at": "2026-11-09T00:00:01Z"}),
    )
    public.parent["run_started_at"] = "2026-11-09T00:00:00Z"
    with pytest.raises(manual.AuditError):
        component.authenticate_report(public, tmp_path, bound)


def test_public_clone_never_includes_private_identity(
    public_report, monkeypatch, tmp_path
):
    public, _, values, _, _ = public_report
    calls = []
    monkeypatch.setattr(component, "git", lambda root, *args: calls.append(args) or "")
    monkeypatch.setattr(component.coverage, "obligation", lambda model: object())
    public.get = lambda path: {
        "full_name": "CultureBotAI/PublicMech",
        "private": False,
        "default_branch": "main",
    }
    roots = component.clone_public(public, tmp_path / "clones", values)
    assert set(roots) == {"publicmech"}
    assert not any("ScaleupMech" in str(args) for args in calls)


@pytest.mark.parametrize("required", [False, True])
def test_cli_only_requires_app_configuration_when_private_obligation_exists(
    monkeypatch, tmp_path, required
):
    source = fixtures.source.__wrapped__()
    public = MetadataAPI(source)
    bound = binding(public)
    monkeypatch.setattr(manual, "GitHubRead", lambda token: public)
    monkeypatch.setattr(
        cli, "protected_runtime", lambda *a: bound["protected_main_sha"]
    )
    monkeypatch.setattr(auto, "private_obligation", lambda *a: {"required": required})
    monkeypatch.setattr(component, "authenticate_report", lambda *a: {})
    calls = []
    monkeypatch.setattr(
        component, "finalize", lambda *a, **k: calls.append("finalized")
    )
    monkeypatch.setenv("GITHUB_RUN_ID", str(bound["run_id"]))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", str(bound["run_attempt"]))
    monkeypatch.delenv("SCALEUP_AUDIT_EXPECTED_APP_ID", raising=False)
    code = cli.main(
        [
            "verify",
            "--trusted-root",
            str(tmp_path),
            "--checkout-sha",
            bound["checkout_sha"],
        ]
    )
    assert code == (2 if required else 0)
    assert calls == ([] if required else ["finalized"])


@pytest.mark.parametrize(
    "private,installed", [(False, False), (True, False), (False, True), (True, True)]
)
def test_actual_bootstrap_selector_requires_protected_code_for_private(
    tmp_path, private, installed
):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        s
        for s in workflow["jobs"]["fleet-audit"]["steps"]
        if s.get("id") == "automatic"
    )
    for name in ("control", "fleet/trusted-claw"):
        path = tmp_path / name / auto.MANIFEST_PATH
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"consumers": {"scaleupmech": {}} if private else {}})
        )
    if installed:
        (
            tmp_path
            / "fleet/trusted-claw/src/kg_microbe_governance/automatic_fleet_component.py"
        ).write_text("protected fixture")
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) is (installed or not private)
    if result.returncode == 0:
        assert output.read_text() == f"available={str(installed).lower()}\n"


def test_real_queue_validator_accepts_only_complete_fail_closed_aggregate():
    text = WORKFLOW.read_text()
    assert workflow_errors(text, ["fleet-audit"]) == []
    document = yaml.safe_load(text)
    for change in ("guard", "condition", "needs", "environment", "continue"):
        candidate = copy.deepcopy(document)
        job = candidate["jobs"]["verified-fleet"]
        if change == "guard":
            job["steps"][0]["run"] = "true"
        elif change == "condition":
            job["if"] = "success()"
        elif change == "needs":
            job["needs"].pop()
        elif change == "environment":
            job["steps"][0]["env"]["PUBLIC_RESULT"] = "success"
        else:
            job["continue-on-error"] = True
        assert workflow_errors(yaml.safe_dump(candidate), ["fleet-audit"])


@pytest.mark.parametrize(
    "candidate,public",
    [
        ("success", "success"),
        ("failure", "success"),
        ("success", "skipped"),
        ("cancelled", "success"),
    ],
)
def test_actual_aggregate_shell_fails_for_any_unsuccessful_component(candidate, public):
    step = yaml.safe_load(WORKFLOW.read_text())["jobs"]["verified-fleet"]["steps"][0]
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={**os.environ, "CANDIDATE_RESULT": candidate, "PUBLIC_RESULT": public},
        capture_output=True,
        timeout=10,
    )
    assert (result.returncode == 0) is (candidate == public == "success")


def test_prospective_bootstrap_requires_protected_framework(tmp_path):
    from kg_microbe_governance import GovernanceError

    with pytest.raises(GovernanceError, match="protected consumer_admission framework"):
        component.candidate_bootstrap_refs(tmp_path, {"checkout_sha": "e" * 40}, None)


def test_private_producer_has_no_candidate_execution_cache_or_broad_token():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/private-scaleup-automatic.yaml").read_text()
    )
    events = workflow.get("on", workflow.get(True))
    assert events == {
        "workflow_run": {
            "workflows": ["authoritative governance fleet audit"],
            "types": ["in_progress"],
        }
    }
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    produce = workflow["jobs"]["produce"]
    assert produce["environment"] == "scaleup-private-audit"
    assert produce["if"] == "needs.preflight.outputs.required_private == 'true'"
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            uses = step.get("uses", "")
            assert not uses.startswith(("actions/cache@", "actions/download-artifact@"))
            if uses.startswith("actions/checkout@"):
                assert step["with"]["ref"] == "${{ github.sha }}"
                assert step["with"]["persist-credentials"] is False
            if uses.startswith("astral-sh/setup-uv@"):
                assert step["with"]["enable-cache"] is False
    steps = produce["steps"]
    mint = next(i for i, step in enumerate(steps) if step.get("id") == "private-token")
    assert "--require-protected-environment" in steps[mint - 1]["run"]
    assert steps[mint]["with"] == {
        "app-id": "${{ vars.SCALEUP_AUDIT_APP_ID }}",
        "private-key": "${{ secrets.SCALEUP_AUDIT_APP_PRIVATE_KEY }}",
        "owner": "CultureBotAI",
        "repositories": "ScaleupMech",
        "permission-contents": "read",
    }
    private_steps = [
        step for step in steps if "SCALEUP_PRIVATE_READ_TOKEN" in step.get("env", {})
    ]
    assert len(private_steps) == 1 and private_steps[0]["id"] == "receipt"
    upload = steps[-1]
    assert upload["with"]["path"] == ".temp/automatic-private/receipt.json"
    assert upload["with"]["overwrite"] is False
