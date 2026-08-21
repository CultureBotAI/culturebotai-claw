"""Installed-package smoke tests for the shared ``src/`` utilities."""

import subprocess
import sys
from importlib.metadata import entry_points
from importlib.resources import files

PACKAGES = (
    "kg_microbe_discussions",
    "kg_microbe_history",
    "kg_microbe_kgscan",
    "kg_microbe_qc",
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
    } <= scripts


def test_dashboard_and_browser_templates_are_packaged():
    assert files("kg_microbe_qc").joinpath("templates/dashboard.html.j2").is_file()
    assert files("kg_microbe_discussions").joinpath("templates/index.html").is_file()
