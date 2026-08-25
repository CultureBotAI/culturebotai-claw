"""Installed-wheel smoke test for the canonical fleet manifest."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_packages_the_single_canonical_manifest(tmp_path: Path) -> None:
    """The installed CLI must start without a source checkout or override."""

    uv = shutil.which("uv")
    assert uv is not None, "the project test runner requires uv"
    sdist_directory = tmp_path / "sdist"
    wheel_directory = tmp_path / "wheel"
    build_environment = os.environ.copy()
    build_environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_OFFLINE": "1",
            "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
        }
    )
    build_environment.pop("KG_MICROBE_FLEET_MANIFEST", None)
    source_built = subprocess.run(
        [
            uv,
            "build",
            "--sdist",
            "--no-build-isolation",
            "--out-dir",
            str(sdist_directory),
        ],
        cwd=REPOSITORY_ROOT,
        env=build_environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert source_built.returncode == 0, source_built.stdout + source_built.stderr
    source_archives = list(sdist_directory.glob("*.tar.gz"))
    assert len(source_archives) == 1
    with tarfile.open(source_archives[0], "r:gz") as source_archive:
        source_names = {
            name.split("/", 1)[1]
            for name in source_archive.getnames()
            if "/" in name
        }
    assert "src/kg_microbe_fleet/fleet.yaml" in source_names
    assert "src/kg_microbe_config/openclaw_config.yaml" in source_names
    assert not any(name.startswith("agents/") for name in source_names)
    assert not any(name.startswith("conf/") for name in source_names)
    assert not any(name.startswith("build/") for name in source_names)

    # Build from the freshly generated source archive. An in-tree wheel build
    # can copy an ignored, stale build/lib tree and silently resurrect deleted
    # package payloads.
    built = subprocess.run(
        [
            uv,
            "build",
            "--wheel",
            "--no-build-isolation",
            "--out-dir",
            str(wheel_directory),
            str(source_archives[0]),
        ],
        cwd=REPOSITORY_ROOT,
        env=build_environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr

    wheels = list(wheel_directory.glob("*.whl"))
    assert len(wheels) == 1
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        assert "kg_microbe_fleet/fleet.yaml" in names
        assert "kg_microbe_config/openclaw_config.yaml" in names
        assert (
            "kg_microbe_agents/definitions/dev_workflow/validation_agent.yaml"
            in names
        )
        assert "conf/fleet.yaml" not in names
        assert "openclaw_config.yaml" not in names
        assert not any(name.startswith("agents/") for name in names)
        assert not any(name.startswith("conf/") for name in names)
        assert not any(name.startswith("build/") for name in names)
        entry_points_path = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = wheel.read(entry_points_path).decode("utf-8")
        assert "kg-microbe-fleet = kg_microbe_fleet.__main__:main" in entry_points
        wheel.extractall(unpacked)

    smoke_environment = os.environ.copy()
    smoke_environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(unpacked),
        }
    )
    smoke_environment.pop("KG_MICROBE_FLEET_MANIFEST", None)
    smoke_code = """
from pathlib import Path
import sys

import cli as cli_package
import kg_microbe_agents
import kg_microbe_config
import kg_microbe_fleet
import plugins
from click.testing import CliRunner
from cli.main import cli
from kg_microbe_config import default_config_path
from kg_microbe_fleet import default_manifest_path, load_fleet_manifest

unpacked = Path(sys.argv[1]).resolve()
runtime_modules = (
    cli_package,
    kg_microbe_agents,
    kg_microbe_config,
    kg_microbe_fleet,
    plugins,
)
for module in runtime_modules:
    module_path = Path(module.__file__).resolve()
    assert module_path.is_relative_to(unpacked), (module.__name__, module_path)
module_path = Path(kg_microbe_fleet.__file__).resolve()
manifest = load_fleet_manifest()
assert manifest.keys == (
    "culturemech",
    "mediaingredientmech",
    "communitymech",
    "traitmech",
    "proteintraitsmech",
)
assert default_manifest_path() == module_path.parent / "fleet.yaml"
assert default_config_path().is_relative_to(unpacked)
assert callable(cli)
runner = CliRunner()
listed = runner.invoke(cli, ["agent", "list"])
assert listed.exit_code == 0, listed.output
assert "validation_agent" in listed.output
ran = runner.invoke(cli, ["agent", "run", "validation_agent", "--dry-run"])
assert ran.exit_code == 0, ran.output
validated = runner.invoke(cli, ["config", "validate"])
assert validated.exit_code == 0, validated.output
"""
    smoked = subprocess.run(
        [sys.executable, "-c", smoke_code, str(unpacked)],
        cwd=tmp_path,
        env=smoke_environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert smoked.returncode == 0, smoked.stdout + smoked.stderr
