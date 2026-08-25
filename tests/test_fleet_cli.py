"""Offline contracts for fleet queries used by scripts and workflows."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_show_vendored_hub_emits_only_the_manifest_key(capsys):
    manifest = load_fleet_manifest()

    assert main(["show", "--field", "vendored_hub"]) == 0
    assert capsys.readouterr().out.strip() == manifest.vendored_hub


def test_scope_is_one_fixed_column_capability_snapshot_with_its_hub(capsys):
    manifest = load_fleet_manifest()

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

    assert len(rows) == len(manifest.with_capability("id_label_validation"))
    assert all(len(row) == 6 for row in rows)
    assert [row[0] for row in rows] == list(
        manifest.with_capability("id_label_validation")
    )
    hub_rows = [row for row in rows if row[5] == "hub"]
    assert len(hub_rows) == 1
    assert hub_rows[0][0] == manifest.vendored_hub
    assert hub_rows[0][4] == manifest.get(manifest.vendored_hub).package_path


def test_scope_fails_before_output_when_required_hub_is_outside_scope(capsys):
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
    assert "vendored hub" in captured.err
    assert "is not in capability scope" in captured.err


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
