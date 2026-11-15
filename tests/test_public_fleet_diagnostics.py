"""Closed stage/error diagnostics at the real public component CLI boundary."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from kg_microbe_governance import GovernanceError
from kg_microbe_governance import automatic_fleet_component as component
from kg_microbe_governance import automatic_private_audit_cli as cli
from kg_microbe_governance import private_scaleup_audit as manual

SHA = "a" * 40
SENTINEL = "opaque-private-response-and-credential-marker"


@pytest.fixture
def invocation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "integer", lambda name: 1)
    monkeypatch.setattr(manual, "GitHubRead", lambda token: object())
    monkeypatch.setattr(cli, "protected_runtime", lambda *args: SHA)
    monkeypatch.setattr(component.auto, "parent_binding", lambda *args, **kwargs: {"protected_main_sha": SHA})
    monkeypatch.setattr(component, "public_component", lambda *args: calls.append("component") or {"safe": True})
    output = tmp_path / "receipt.json"
    args = ["--trusted-root", str(tmp_path / "trusted"), "--workspace", str(tmp_path / "workspace"),
            "--output", str(output), "--checkout-sha", SHA]
    return args, output, calls


@pytest.mark.parametrize("stage,code,error", [
    ("configuration", "configuration_missing", manual.AuditError("configuration_missing")),
    ("protected_runtime", "producer_untrusted", manual.AuditError("producer_untrusted")),
    ("parent_binding", "source_unverified", manual.AuditError("source_unverified")),
    ("public_component", "transport_refused", manual.AuditError("transport_refused")),
    ("public_component", "subprocess_failed", subprocess.CalledProcessError(128, [SENTINEL], output=SENTINEL, stderr=SENTINEL)),
    ("public_component", "subprocess_timeout", subprocess.TimeoutExpired([SENTINEL], 1, output=SENTINEL, stderr=SENTINEL)),
    ("public_component", "governance_invalid", GovernanceError(SENTINEL)),
    ("public_component", "invalid_value", ValueError(SENTINEL)),
    ("receipt", "filesystem_error", OSError(SENTINEL)),
    ("public_component", "unexpected_failure", RuntimeError(SENTINEL)),
    ("public_component", "unexpected_failure", TypeError(SENTINEL)),
])
def test_cli_failure_reports_only_closed_stage_and_code(invocation, monkeypatch, capsys, stage, code, error):
    args, output, calls = invocation

    def fail(*args, **kwargs):
        raise error

    owner, target = {
        "configuration": (cli, "integer"),
        "protected_runtime": (cli, "protected_runtime"),
        "parent_binding": (component.auto, "parent_binding"),
        "public_component": (component, "public_component"),
        "receipt": (cli, "append_receipt"),
    }[stage]
    monkeypatch.setattr(owner, target, fail)
    assert component.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"public_fleet_component_failed stage={stage} code={code}\n"
    assert SENTINEL not in captured.err and not output.exists()
    assert calls == (["component"] if stage == "receipt" else [])


def test_invalid_output_preserves_existing_receipt_and_reports_argument_stage(invocation, capsys):
    args, output, calls = invocation
    output.write_bytes(b"retained evidence\n")
    assert component.main(args) == 2
    assert output.read_bytes() == b"retained evidence\n" and calls == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "public_fleet_component_failed stage=arguments code=invalid_arguments\n"


def test_unrecognized_error_code_cannot_leak_into_diagnostic(invocation, monkeypatch, capsys):
    error = manual.AuditError("unexpected_failure")
    error.code = SENTINEL

    def fail(*args):
        raise error

    monkeypatch.setattr(component, "public_component", fail)
    assert component.main(invocation[0]) == 2
    assert capsys.readouterr().err == "public_fleet_component_failed stage=public_component code=unexpected_failure\n"
    assert not invocation[1].exists()


def test_success_writes_receipt_and_emits_no_failure(invocation, capsys):
    args, output, calls = invocation
    assert component.main(args) == 0
    assert json.loads(output.read_bytes()) == {"safe": True} and calls == ["component"]
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == "public_fleet_component_complete_private_obligations_explicit\n"


@pytest.mark.parametrize("phase", [
    "manifest_binding", "public_metadata", "public_clone", "public_materialization",
    "source_preparation", "protected_audit", "candidate_completeness", "receipt_validation",
    "parent_recheck",
])
def test_same_code_identifies_actual_inner_phase(invocation, monkeypatch, capsys, tmp_path, phase):
    from kg_microbe_governance import cycle_release_audit

    args, output, _ = invocation
    trusted = tmp_path / "trusted"
    manifest_path = trusted / component.auto.MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(b"bound manifest")
    release_path = trusted / "src/kg_microbe_governance/releases/mech-cycle-v2-canary.json"
    release_path.parent.mkdir(parents=True)
    release_path.write_bytes(b"{}")
    consumer = SimpleNamespace(github="CultureBotAI/PublicMech", package_path="src/publicmech")
    manifest = SimpleNamespace(consumers={"publicmech": consumer}, pin_path="scripts/pin", artifacts_for=lambda c: [])
    values = {"protected": manifest, "candidate": manifest}
    monkeypatch.setattr(component, "public_component", REAL_PUBLIC_COMPONENT)
    monkeypatch.setattr(component, "manifests", lambda *a: (values, {}))
    monkeypatch.setattr(component.auto, "public_blob", lambda *a: b"bound manifest")
    monkeypatch.setattr(component.auto, "private_obligation", lambda *a: {"required": False})
    monkeypatch.setattr(component.PublicRepositoryMetadata, "get", lambda *a: {
        "full_name": consumer.github, "private": False, "default_branch": "main"})
    monkeypatch.setattr(component, "git", lambda *a: "")
    monkeypatch.setattr(component, "prepare_sources", lambda *a: None)
    monkeypatch.setattr(component.coverage, "obligation", lambda *a: None)
    monkeypatch.setattr(cycle_release_audit, "audit_release", lambda *a, **k: {"public_component_ok": True, "repositories": []})
    monkeypatch.setattr(component, "bootstrap_refs", lambda *a: {})
    monkeypatch.setattr(component, "_commit_at", lambda *a: SHA)
    monkeypatch.setattr(component, "validate_report", lambda *a: None)
    bound = {"protected_main_sha": SHA, "checkout_sha": SHA, "run_id": 1, "run_attempt": 1}
    parent_calls = []

    def parent(*args, **kwargs):
        parent_calls.append(1)
        if phase == "parent_recheck" and len(parent_calls) == 2:
            raise manual.AuditError("source_unverified")
        return bound

    monkeypatch.setattr(component.auto, "parent_binding", parent)

    def fail(*args, **kwargs):
        raise manual.AuditError("source_unverified")

    if phase in {"public_clone", "public_materialization"}:
        def git(root, *args):
            if args[0] == ("clone" if phase == "public_clone" else "checkout"):
                fail()
            return ""
        monkeypatch.setattr(component, "git", git)
    elif phase != "parent_recheck":
        owner, name = {
            "manifest_binding": (component, "manifests"),
            "public_metadata": (component.PublicRepositoryMetadata, "get"),
            "source_preparation": (component, "prepare_sources"),
            "protected_audit": (component.coverage, "obligation"),
            "candidate_completeness": (component, "_commit_at"),
            "receipt_validation": (component, "validate_report"),
        }[phase]
        monkeypatch.setattr(owner, name, fail)
    assert component.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"public_fleet_component_failed stage={phase} code=source_unverified\n"
    assert not output.exists()


REAL_PUBLIC_COMPONENT = component.public_component


def test_unrecognized_exception_stage_is_not_emitted(invocation, monkeypatch, capsys):
    error = RuntimeError(SENTINEL)
    error._public_fleet_stage = SENTINEL

    def fail(*args):
        raise error

    monkeypatch.setattr(component, "public_component", fail)
    assert component.main(invocation[0]) == 2
    assert capsys.readouterr().err == "public_fleet_component_failed stage=public_component code=unexpected_failure\n"
    assert not invocation[1].exists()
