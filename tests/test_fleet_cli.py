"""Offline contracts for fleet queries used by scripts and workflows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from git import Repo

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.__main__ import main


def test_tsv_list_has_one_identity_row_per_manifest_mech(capsys):
    manifest = load_fleet_manifest()

    assert main(["list", "--format", "tsv"]) == 0
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]

    assert len(rows) == len(manifest.keys)
    assert all(len(row) == 4 for row in rows)
    assert [row[0] for row in rows] == list(manifest.keys)
    assert [row[2] for row in rows] == [
        mech.github for mech in manifest.mechs.values()
    ]


def test_json_list_exposes_verified_schema_and_record_locations(capsys):
    manifest = load_fleet_manifest()

    assert main(["list", "--capability", "schema_sync", "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)

    assert [row["key"] for row in rows] == list(
        manifest.with_capability("schema_sync")
    )
    assert all(row["package_path"] for row in rows)
    assert all(row["schema_paths"] for row in rows)
    assert all(row["record_globs"] for row in rows)


def test_tsv_can_append_manifest_package_paths(capsys):
    manifest = load_fleet_manifest()

    assert main(["list", "--format", "tsv", "--include-package-path"]) == 0
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]

    assert all(len(row) == 5 for row in rows)
    assert [row[4] for row in rows] == [
        mech.package_path for mech in manifest.mechs.values()
    ]


def test_unknown_capability_fails_closed(capsys):
    assert main(["list", "--capability", "typo_capability"]) == 2

    assert "Unknown fleet capability" in capsys.readouterr().err


def test_knowledge_gap_matrix_is_capability_scoped_and_carries_windows(capsys):
    manifest = load_fleet_manifest()

    assert (
        main(
            [
                "matrix",
                "--capability",
                "knowledge_gap_scan",
                "--setting",
                "window",
            ]
        )
        == 0
    )
    matrix = json.loads(capsys.readouterr().out)
    rows = matrix["include"]

    assert [row["repository"] for row in rows] == [
        manifest.get(key).github
        for key in manifest.with_capability("knowledge_gap_scan")
    ]
    assert all(isinstance(row["window"], int) and row["window"] > 0 for row in rows)
    assert all(row["checkout_path"] == row["workdir"] for row in rows)


def test_scheduled_matrix_preserves_default_eligibility(tmp_path, monkeypatch, capsys):
    document = yaml.safe_load(load_fleet_manifest().source.read_text())
    document["mechs"]["dufmech"]["capabilities"]["knowledge_gap_scan"] = {
        "status": "enabled", "settings": {"window": 25, "scheduled": False},
    }
    # Model legacy absence even after the shipped fleet gains explicit opt-outs.
    for mech in document["mechs"].values():
        for declaration in mech["capabilities"].values():
            declaration.get("settings", {}).pop("scheduled", None)
    path = tmp_path / "legacy-scheduling.yaml"
    path.write_text(yaml.safe_dump(document))
    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(path))
    args = ["matrix", "--capability", "knowledge_gap_scan", "--setting", "window"]
    assert main(args) == 0
    expected = json.loads(capsys.readouterr().out)
    assert any(row["mech"] == "DUFMech" for row in expected["include"])
    assert main([*args, "--scheduled-only"]) == 0
    assert json.loads(capsys.readouterr().out) == expected


@pytest.mark.parametrize("scheduled", [True, False])
def test_explicit_scheduling_controls_only_the_live_scan_matrix(
    tmp_path, monkeypatch, capsys, scheduled,
):
    document = yaml.safe_load(load_fleet_manifest().source.read_text())
    for mech in document["mechs"].values():
        mech["capabilities"]["knowledge_gap_scan"].get("settings", {}).pop("scheduled", None)
    document["mechs"]["culturemech"]["capabilities"]["knowledge_gap_scan"] = {
        "status": "enabled", "settings": {"window": 25, "scheduled": True},
    }
    document["mechs"]["dufmech"]["capabilities"]["knowledge_gap_scan"] = {
        "status": "enabled", "settings": {"window": 25, "scheduled": scheduled},
    }
    path = tmp_path / "explicit-scheduling.yaml"
    path.write_text(yaml.safe_dump(document))
    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(path))
    args = ["matrix", "--capability", "knowledge_gap_scan", "--setting", "window"]
    assert main(args) == 0
    complete = json.loads(capsys.readouterr().out)["include"]
    assert any(r["mech"] == "DUFMech" for r in complete)
    assert main([*args, "--scheduled-only"]) == 0
    live = json.loads(capsys.readouterr().out)["include"]
    assert any(row["mech"] == "CultureMech" for row in live)
    assert live == [row for row in complete if scheduled or row["mech"] != "DUFMech"]


def test_empty_scheduled_matrix_fails_closed(tmp_path, monkeypatch, capsys):
    document = yaml.safe_load(load_fleet_manifest().source.read_text())
    for mech in document["mechs"].values():
        declaration = mech["capabilities"]["knowledge_gap_scan"]
        if declaration["status"] == "enabled":
            declaration["settings"]["scheduled"] = False
    path = tmp_path / "offline-only.yaml"
    path.write_text(yaml.safe_dump(document))
    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(path))
    assert main(["matrix", "--capability", "knowledge_gap_scan", "--scheduled-only"]) == 2
    result = capsys.readouterr()
    assert not result.out
    assert "no enabled Mechs eligible for scheduling" in result.err


@pytest.mark.parametrize("value", ["false", 0, None])
def test_scheduling_opt_out_requires_a_real_boolean(tmp_path, monkeypatch, capsys, value):
    document = yaml.safe_load(load_fleet_manifest().source.read_text())
    document["mechs"]["culturemech"]["capabilities"]["knowledge_gap_scan"]["settings"][
        "scheduled"
    ] = value
    path = tmp_path / "invalid-schedule.yaml"
    path.write_text(yaml.safe_dump(document))
    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(path))
    assert main(["matrix", "--capability", "knowledge_gap_scan", "--scheduled-only"]) == 2
    assert "must be a boolean" in capsys.readouterr().err


def test_scheduled_only_requires_a_declared_boolean_setting(capsys):
    assert main(["matrix", "--capability", "strict_validation", "--scheduled-only"]) == 2
    assert "no boolean scheduled setting" in capsys.readouterr().err


def test_live_scan_workflow_uses_explicit_scheduling_filter():
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/knowledge-gap-scan.yaml"
    document = yaml.safe_load(workflow.read_text())
    matrix_step = next(s for s in document["jobs"]["prepare"]["steps"] if s.get("id") == "matrix")
    assert "--capability knowledge_gap_scan --setting window --scheduled-only" in matrix_step["run"]


def test_show_vendored_hub_fails_explicitly_for_authoritative_fleet(capsys):
    assert main(["show", "--field", "vendored_hub"]) == 2

    captured = capsys.readouterr()
    assert not captured.out
    assert "claw is authoritative" in captured.err


def test_scope_is_one_fixed_column_authoritative_capability_snapshot(capsys):
    manifest = load_fleet_manifest()

    assert main(["scope", "--capability", "id_label_validation"]) == 0
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]

    assert len(rows) == len(manifest.with_capability("id_label_validation"))
    assert all(len(row) == 6 for row in rows)
    assert [row[0] for row in rows] == list(
        manifest.with_capability("id_label_validation")
    )
    assert manifest.vendored_hub is None
    assert {row[5] for row in rows} == {"consumer"}


def test_scope_rejects_legacy_hub_requirement_after_authority_flip(capsys):
    assert (
        main(
            [
                "scope",
                "--capability",
                "vendored_sync",
                "--require-vendored-hub",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert not captured.out
    assert "claw is authoritative" in captured.err


def test_transition_override_still_supports_legacy_hub_queries(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    transition = yaml.safe_load(
        load_fleet_manifest().source.read_text(encoding="utf-8")
    )
    transition["vendored_governance"]["state"] = "transition"
    transition["vendored_governance"]["legacy_hub"] = "culturemech"
    for key, mech in transition["mechs"].items():
        is_legacy_hub = key == "culturemech"
        mech["vendored_role"] = "hub" if is_legacy_hub else "spoke"
        vendored_sync = mech["capabilities"]["vendored_sync"]
        if is_legacy_hub:
            vendored_sync["status"] = "not_applicable"
            vendored_sync["reason"] = "valid synthetic transition fixture"
    path = tmp_path / "transition-fleet.yaml"
    path.write_text(yaml.safe_dump(transition, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(path))

    assert main(["show", "--field", "vendored_hub"]) == 0
    assert capsys.readouterr().out.strip() == "culturemech"

    assert (
        main(
            [
                "scope",
                "--capability",
                "id_label_validation",
                "--require-vendored-hub",
            ]
        )
        == 0
    )
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    hub_rows = [row for row in rows if row[5] == "hub"]
    assert len(hub_rows) == 1
    assert hub_rows[0][0] == "culturemech"


def _repository(path: Path, github_identity: str) -> Path:
    path.mkdir()
    repo = Repo.init(path)
    repo.create_remote("origin", f"https://github.com/{github_identity}.git")
    return path


def test_targets_emits_only_identity_validated_roots(
    tmp_path, monkeypatch, capsys
):
    manifest = load_fleet_manifest()
    mechs = [
        manifest.get(key)
        for key in manifest.with_capability("coordination_hooks")
    ]
    for mech in manifest.mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    trusted = _repository(tmp_path / mechs[0].key, mechs[0].github)
    monkeypatch.setenv(mechs[0].environment_variable, str(trusted))

    assert main(["targets", "--capability", "coordination_hooks"]) == 0
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]

    assert len(rows) == len(mechs)
    assert all(len(row) == 5 for row in rows)
    assert rows[0][4] == str(trusted.resolve())
    assert all(not row[4] for row in rows[1:])


def test_targets_rejects_a_wrong_git_identity_before_emitting_rows(
    tmp_path, monkeypatch, capsys
):
    manifest = load_fleet_manifest()
    mech = manifest.get(manifest.with_capability("coordination_hooks")[0])
    for candidate in manifest.mechs.values():
        monkeypatch.delenv(candidate.environment_variable, raising=False)
    wrong = _repository(tmp_path / "wrong", "CultureBotAI/not-the-declared-repo")
    monkeypatch.setenv(mech.environment_variable, str(wrong))

    assert main(["targets", "--capability", "coordination_hooks"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "origin identity mismatch" in captured.err


def test_targets_rejects_a_symlinked_dotenv(tmp_path, capsys):
    actual = tmp_path / "actual.env"
    actual.write_text("CULTUREMECH_ROOT=/tmp/untrusted\n", encoding="utf-8")
    linked = tmp_path / "linked.env"
    linked.symlink_to(actual)

    assert (
        main(
            [
                "targets",
                "--capability",
                "coordination_hooks",
                "--dotenv",
                str(linked),
            ]
        )
        == 2
    )
    assert "non-symlink" in capsys.readouterr().err


def test_targets_reads_only_an_explicit_dotenv_without_printing_secrets(
    tmp_path, monkeypatch, capsys
):
    manifest = load_fleet_manifest()
    mech = manifest.get(manifest.with_capability("coordination_hooks")[0])
    for candidate in manifest.mechs.values():
        monkeypatch.delenv(candidate.environment_variable, raising=False)
    trusted = _repository(tmp_path / mech.key, mech.github)
    secret = "never-print-this-dotenv-secret"
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"{mech.environment_variable}={trusted}\nUNRELATED_SECRET={secret}\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "targets",
                "--capability",
                "coordination_hooks",
                "--dotenv",
                str(dotenv),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    rows = [line.split("\t") for line in captured.out.splitlines()]

    assert rows[0][4] == str(trusted.resolve())
    assert secret not in captured.out
    assert secret not in captured.err


def test_exported_target_overrides_explicit_dotenv(
    tmp_path, monkeypatch, capsys
):
    manifest = load_fleet_manifest()
    mech = manifest.get(manifest.with_capability("coordination_hooks")[0])
    for candidate in manifest.mechs.values():
        monkeypatch.delenv(candidate.environment_variable, raising=False)
    dotenv_target = _repository(tmp_path / "dotenv", mech.github)
    exported_target = _repository(tmp_path / "exported", mech.github)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"{mech.environment_variable}={dotenv_target}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(mech.environment_variable, str(exported_target))

    assert (
        main(
            [
                "targets",
                "--capability",
                "coordination_hooks",
                "--dotenv",
                str(dotenv),
            ]
        )
        == 0
    )
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]

    assert rows[0][4] == str(exported_target.resolve())


def test_targets_rejects_a_missing_explicit_dotenv(capsys, tmp_path):
    missing = tmp_path / "missing.env"

    assert (
        main(
            [
                "targets",
                "--capability",
                "coordination_hooks",
                "--dotenv",
                str(missing),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()

    assert not captured.out
    assert "dotenv file does not exist" in captured.err


def test_targets_rejects_a_partially_parseable_dotenv(capsys, tmp_path):
    dotenv = tmp_path / "malformed.env"
    dotenv.write_text(
        'CULTUREMECH_ROOT="unterminated\nTRAITMECH_ROOT=/would-be-partial\n',
        encoding="utf-8",
    )

    assert (
        main(
            [
                "targets",
                "--capability",
                "coordination_hooks",
                "--dotenv",
                str(dotenv),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert "dotenv file is malformed at line 1" in captured.err
