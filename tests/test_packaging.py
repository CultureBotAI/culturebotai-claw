"""Installed-package smoke tests for the shared ``src/`` utilities."""

import subprocess
import sys
from importlib.metadata import entry_points
from importlib.resources import files
from pathlib import Path

PACKAGES = (
    "kg_microbe_discussions",
    "kg_microbe_history",
    "kg_microbe_kgscan",
    "kg_microbe_qc",
    "kg_microbe_research",
)


def test_src_packages_import_without_repository_pythonpath(tmp_path):
    statement = "; ".join(f"import {package}" for package in PACKAGES)

    result = subprocess.run(
        [sys.executable, "-I", "-c", statement],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_shared_console_scripts_are_installed():
    scripts = {entry.name for entry in entry_points(group="console_scripts")}

    assert {
        "kg-microbe-discussions",
        "kg-microbe-history",
        "kg-microbe-kgscan",
        "kg-microbe-qc",
        "kg-microbe-research",
    } <= scripts


def test_dashboard_and_browser_templates_are_packaged():
    assert files("kg_microbe_qc").joinpath("templates/dashboard.html.j2").is_file()
    assert files("kg_microbe_discussions").joinpath("templates/index.html").is_file()


def test_history_default_schema_works_outside_checkout(tmp_path):
    record = tmp_path / "record.yaml"
    record.write_text(
        """history_version: 1
target: {kind: record, path: data/demo.yaml}
session:
  id: test
  timestamp: '2026-08-20T00:00:00Z'
  actors: [{type: human, name: reviewer}]
events:
  - {type: REVIEW, outcome: no_change, summary: checked, details: complete}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "kg_microbe_history",
            "validate",
            str(record),
            "--structural-only",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_packaged_history_schema_is_canonical():
    packaged = (
        files("kg_microbe_governance")
        .joinpath("artifacts/schema/history.yaml")
        .read_text(encoding="utf-8")
    )
    canonical_path = (
        Path(__file__).parents[1]
        / "src"
        / "kg_microbe_governance"
        / "artifacts"
        / "schema"
        / "history.yaml"
    )

    assert packaged == canonical_path.read_text(encoding="utf-8")
