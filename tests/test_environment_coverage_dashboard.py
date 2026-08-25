"""Offline contracts for manifest-scoped environment coverage analysis."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from git import Repo

from kg_microbe_fleet import load_fleet_manifest
from scripts import environment_coverage_dashboard as dashboard
from scripts.environment_coverage_dashboard import format_html, format_table, main


def _repository(path: Path, github_identity: str) -> Path:
    path.mkdir(parents=True)
    repo = Repo.init(path)
    repo.create_remote("origin", f"https://github.com/{github_identity}.git")
    return path


def _record_path(root: Path, pattern: str) -> Path:
    relative = pattern.replace("**/", "").replace("*", "sample")
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _clear_fleet_environment(monkeypatch) -> None:
    for mech in load_fleet_manifest().mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)


def _coverage_glob(key: str) -> str:
    capability = load_fleet_manifest().get(key).capability("environment_coverage")
    assert capability is not None
    globs = capability.settings["record_globs"]
    assert isinstance(globs, tuple)
    return globs[0]


def test_dashboard_scans_exactly_validated_environment_capability_roots(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    documents = (
        {
            "id": "medium:1",
            "name": "Example medium",
            "source_environment": [
                {"term": {"id": "ENVO:00000001", "label": "example habitat"}}
            ],
        },
        {
            "preferred_term": "Example ingredient",
            "ontology_id": "CHEBI:1",
            "environmental_context": [
                {
                    "environment_term": "ENVO:00000001",
                    "environment_label": "example habitat",
                    "relevance": "documented",
                }
            ],
        },
        {
            "id": "community:1",
            "name": "Example community",
            "environment_term": {
                "term": {"id": "ENVO:00000001", "label": "example habitat"}
            },
        },
    )
    assert len(selected) == len(documents)
    for key, document in zip(selected, documents, strict=True):
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        monkeypatch.setenv(mech.environment_variable, str(root))
        _record_path(root, _coverage_glob(key)).write_text(
            yaml.safe_dump(document), encoding="utf-8"
        )

    # A configured, trustworthy out-of-scope repository must not expand the
    # dashboard's inputs merely because it happens to contain a matching field.
    excluded_key = next(key for key in manifest.keys if key not in selected)
    excluded = manifest.get(excluded_key)
    excluded_root = _repository(tmp_path / excluded_key, excluded.github)
    monkeypatch.setenv(excluded.environment_variable, str(excluded_root))
    _record_path(excluded_root, excluded.record_globs[0]).write_text(
        yaml.safe_dump(
            {
                "id": "out-of-scope",
                "environment_term": {
                    "term": {"id": "ENVO:99999999", "label": "must not appear"}
                },
            }
        ),
        encoding="utf-8",
    )

    assert main(["--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["summary"] == {
        "total_environments": 1,
        "environments_with_communities": 1,
        "environments_with_media": 1,
        "environments_with_ingredients": 1,
        "fully_covered": 1,
        "total_communities": 1,
        "total_media": 1,
        "total_ingredients": 1,
    }
    assert report["environments"][0]["envo_id"] == "ENVO:00000001"
    assert "ENVO:99999999" not in json.dumps(report)


def test_dashboard_rejects_an_incomplete_capability_scope_before_scanning(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    for key in selected[:-1]:
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        monkeypatch.setenv(mech.environment_variable, str(root))

    assert main(["--format", "json"]) == 2
    captured = capsys.readouterr()

    assert not captured.out
    assert "target is not configured" in captured.err
    assert manifest.get(selected[-1]).environment_variable in captured.err
    assert "Scanning" not in captured.err


def test_dashboard_rejects_configured_wrong_identity_before_scanning(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    for index, key in enumerate(selected):
        mech = manifest.get(key)
        github = mech.github if index else "ExampleOrg/not-the-declared-repository"
        root = _repository(tmp_path / key, github)
        monkeypatch.setenv(mech.environment_variable, str(root))

    assert main(["--format", "json"]) == 2
    captured = capsys.readouterr()

    assert not captured.out
    assert "target is untrustworthy" in captured.err
    assert "origin identity mismatch" in captured.err
    assert "Scanning" not in captured.err


def test_dashboard_fails_instead_of_silently_omitting_malformed_records(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    for index, key in enumerate(selected):
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        monkeypatch.setenv(mech.environment_variable, str(root))
        if index == 0:
            _record_path(root, _coverage_glob(key)).write_text(
                "id: first\nid: silently-overwritten\n",
                encoding="utf-8",
            )

    assert main(["--format", "json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "inputs are incomplete" in captured.err
    assert "duplicate key 'id'" in captured.err


def test_dashboard_rejects_record_symlinks_that_redirect_reads(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    for index, key in enumerate(selected):
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        monkeypatch.setenv(mech.environment_variable, str(root))
        if index == 0:
            outside = tmp_path / "outside.yaml"
            outside.write_text("id: must-not-be-read\n", encoding="utf-8")
            record = _record_path(root, _coverage_glob(key))
            record.symlink_to(outside)

    assert main(["--format", "json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "is a symlink" in captured.err


@pytest.mark.parametrize(
    ("unsafe_kind", "message"),
    [
        ("broken_symlink", "is a symlink"),
        ("directory", "is not a regular file"),
        ("fifo", "is not a regular file"),
    ],
)
def test_dashboard_rejects_every_nonregular_glob_match_even_with_valid_records(
    tmp_path, monkeypatch, capsys, unsafe_kind, message
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    for index, key in enumerate(selected):
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        monkeypatch.setenv(mech.environment_variable, str(root))
        valid = _record_path(root, _coverage_glob(key))
        valid.write_text("id: valid-record\n", encoding="utf-8")
        if index != 0:
            continue
        unsafe = valid.with_name("unsafe.yaml")
        if unsafe_kind == "broken_symlink":
            unsafe.symlink_to(tmp_path / "missing-target.yaml")
        elif unsafe_kind == "directory":
            unsafe.mkdir()
        else:
            os.mkfifo(unsafe)

    assert main(["--format", "json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert message in captured.err


def test_dashboard_rejects_a_selected_source_with_no_matching_records(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    for index, key in enumerate(selected):
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        monkeypatch.setenv(mech.environment_variable, str(root))
        if index:
            _record_path(root, _coverage_glob(key)).write_text(
                "id: record-without-environment\n", encoding="utf-8"
            )

    assert main(["--format", "json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert f"{selected[0]}: record_globs matched no files" in captured.err


def test_dashboard_rejects_present_but_malformed_environment_fields(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    for index, key in enumerate(selected):
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        monkeypatch.setenv(mech.environment_variable, str(root))
        document: object = {"id": f"record:{index}"}
        if index == 0:
            document = {"id": "medium:bad", "source_environment": ["typo"]}
        _record_path(root, _coverage_glob(key)).write_text(
            yaml.safe_dump(document), encoding="utf-8"
        )

    assert main(["--format", "json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "source_environment[0] must be a mapping" in captured.err


def test_dashboard_reads_only_an_explicit_dotenv_with_exported_precedence(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = load_fleet_manifest()
    _clear_fleet_environment(monkeypatch)
    selected = manifest.with_capability("environment_coverage")
    dotenv_lines: list[str] = []
    for key in selected:
        mech = manifest.get(key)
        root = _repository(tmp_path / key, mech.github)
        _record_path(root, _coverage_glob(key)).write_text(
            "id: record-without-environment\n", encoding="utf-8"
        )
        dotenv_lines.append(f"{mech.environment_variable}={root}")

    # Prove exported values win over the explicitly selected project file.
    first = manifest.get(selected[0])
    exported_root = _repository(tmp_path / "exported", first.github)
    _record_path(exported_root, _coverage_glob(selected[0])).write_text(
        "id: exported-record\n", encoding="utf-8"
    )
    monkeypatch.setenv(first.environment_variable, str(exported_root))
    dotenv = tmp_path / "fleet.env"
    dotenv.write_text("\n".join(dotenv_lines) + "\n", encoding="utf-8")

    assert main(["--format", "json", "--dotenv", str(dotenv)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["total_environments"] == 0


def test_dashboard_rejects_a_symlinked_explicit_dotenv(
    tmp_path, monkeypatch, capsys
) -> None:
    _clear_fleet_environment(monkeypatch)
    target = tmp_path / "real.env"
    target.write_text("", encoding="utf-8")
    dotenv = tmp_path / "linked.env"
    dotenv.symlink_to(target)

    assert main(["--format", "json", "--dotenv", str(dotenv)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "regular, non-symlink file" in captured.err


def test_dashboard_html_escapes_record_controlled_markup() -> None:
    payload = "<script>alert('record')</script>"
    html = format_html(
        {
            "summary": {
                "total_environments": 1,
                "fully_covered": 0,
                "total_communities": 0,
                "total_media": 0,
                "total_ingredients": 0,
            },
            "environments": [
                {
                    "envo_id": payload,
                    "label": payload,
                    "community_count": 0,
                    "media_count": 0,
                    "ingredient_count": 0,
                    "coverage_score": 0,
                    "coverage_level": "none",
                }
            ],
        }
    )

    assert payload not in html
    assert "&lt;script&gt;" in html


def test_default_table_formatter_is_installed_and_renders_report() -> None:
    report = {
        "summary": {
            "total_environments": 1,
            "environments_with_communities": 1,
            "environments_with_media": 0,
            "environments_with_ingredients": 0,
            "fully_covered": 0,
            "total_communities": 2,
            "total_media": 0,
            "total_ingredients": 0,
        },
        "environments": [
            {
                "envo_id": "ENVO:00000001",
                "label": "test environment",
                "community_count": 2,
                "media_count": 0,
                "ingredient_count": 0,
                "coverage_score": 33.3,
                "coverage_level": "MINIMAL",
                "communities": [],
                "media": [],
                "ingredients": [],
            }
        ],
    }

    rendered = format_table(report)

    assert "ENVIRONMENT COVERAGE DASHBOARD" in rendered
    assert "ENVO:00000001" in rendered
    assert "test environment" in rendered


def test_dashboard_no_flag_path_selects_table_output(monkeypatch, capsys) -> None:
    report = {"summary": {}, "environments": []}
    monkeypatch.setattr(dashboard, "_coverage_sources", lambda _dotenv=None: ())
    monkeypatch.setattr(
        dashboard.EnvironmentCoverageAnalyzer,
        "analyze",
        lambda _self: report,
    )
    monkeypatch.setattr(dashboard, "format_table", lambda value: "default table")

    assert dashboard.main([]) == 0
    assert capsys.readouterr().out == "default table\n"
