"""CLI contracts for the five-Mech governance pin audit."""

from pathlib import Path

import kg_microbe_governance.fleet_audit as fleet_audit
from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_governance.__main__ import main
from kg_microbe_governance.fleet_audit import (
    FleetAuditResult,
    RepositoryAuditResult,
)

REF = "a" * 40


def _successful_result(roots: dict[str, Path], expected_ref: str) -> FleetAuditResult:
    repositories = tuple(
        RepositoryAuditResult(
            key=key,
            github=f"CultureBotAI/{key}",
            root=root,
            head="b" * 40,
            origin_main="b" * 40,
            pin=expected_ref,
            expected_artifacts=14,
            checked_artifacts=14,
            issues=(),
        )
        for key, root in roots.items()
    )
    return FleetAuditResult(expected_ref, repositories)


def test_fleet_audit_cli_parses_repeated_roots_and_reports_success(
    monkeypatch, capsys
) -> None:
    captured: dict[str, object] = {}

    def fake_audit(roots: dict[str, Path], expected_ref: str) -> FleetAuditResult:
        captured["roots"] = roots
        captured["ref"] = expected_ref
        return _successful_result(roots, expected_ref)

    monkeypatch.setattr(fleet_audit, "audit_fleet_pins", fake_audit)
    roots = {
        key: Path("/tmp") / key for key, mech in load_fleet_manifest().mechs.items()
        if mech.vendored_role == "consumer"
    }
    arguments = ["fleet-audit", "--ref", REF]
    for key, root in roots.items():
        arguments.extend(["--target-root", f"{key}={root}"])
    assert main(arguments) == 0
    assert captured == {"roots": roots, "ref": REF}
    assert f"OK: all {len(captured['roots'])} Mechs match" in capsys.readouterr().out


def test_fleet_audit_cli_rejects_malformed_or_duplicate_root_values(capsys) -> None:
    assert main(
        ["fleet-audit", "--ref", REF, "--target-root", "missing-separator"]
    ) == 2
    assert "MECH=/exact/worktree/path" in capsys.readouterr().err

    assert main(
        [
            "fleet-audit",
            "--ref",
            REF,
            "--target-root",
            "culturemech=/tmp/one",
            "--target-root",
            "culturemech=/tmp/two",
        ]
    ) == 2
    assert "Duplicate --target-root" in capsys.readouterr().err
