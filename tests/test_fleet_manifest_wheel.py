"""Installed-wheel smoke for canonical fleet and governance package data."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_packages_canonical_manifests_and_payloads(tmp_path: Path) -> None:
    """Installed CLIs must start without a source checkout or override."""

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
        source_names = {name.split("/", 1)[1] for name in source_archive.getnames() if "/" in name}
    assert "src/kg_microbe_fleet/fleet.yaml" in source_names
    governance_document = json.loads(
        (REPOSITORY_ROOT / "src/kg_microbe_governance/vendored_artifacts.json").read_text(
            encoding="utf-8"
        )
    )
    assert "src/kg_microbe_governance/vendored_artifacts.json" in source_names
    for artifact in governance_document["artifacts"]:
        assert artifact["source"] in source_names
    assert "src/kg_microbe_config/openclaw_config.yaml" in source_names
    assert "src/kg_microbe_research/__init__.py" in source_names
    assert "src/kg_microbe_research/__main__.py" in source_names
    assert not any(name.startswith("agents/") for name in source_names)
    assert not any(name.startswith("conf/") for name in source_names)
    assert not any(name.startswith("build/") for name in source_names)
    assert not any(
        name == "shared" or name.startswith(("shared/", "src/shared/")) for name in source_names
    )

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
        assert "kg_microbe_governance/vendored_artifacts.json" in names
        for artifact in governance_document["artifacts"]:
            assert artifact["source"].removeprefix("src/") in names
        assert "kg_microbe_config/openclaw_config.yaml" in names
        assert "kg_microbe_research/__init__.py" in names
        assert "kg_microbe_research/__main__.py" in names
        assert "kg_microbe_agents/definitions/dev_workflow/validation_agent.yaml" in names
        assert "conf/fleet.yaml" not in names
        assert "openclaw_config.yaml" not in names
        assert not any(name.startswith("agents/") for name in names)
        assert not any(name.startswith("conf/") for name in names)
        assert not any(name.startswith("build/") for name in names)
        assert not any(name == "shared" or name.startswith("shared/") for name in names)
        entry_points_path = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = wheel.read(entry_points_path).decode("utf-8")
        assert "kg-microbe-fleet = kg_microbe_fleet.__main__:main" in entry_points
        assert "kg-microbe-governance = kg_microbe_governance.__main__:main" in entry_points
        assert "kg-microbe-history = kg_microbe_history.__main__:main" in entry_points
        assert "kg-microbe-research = kg_microbe_research.__main__:main" in entry_points
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
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import cli as cli_package
import kg_microbe_agents
import kg_microbe_config
import kg_microbe_fleet
import kg_microbe_governance
import kg_microbe_governance.fleet_audit
import kg_microbe_history
import kg_microbe_research
import kg_microbe_research.__main__
import plugins
from click.testing import CliRunner
from cli.main import cli
from kg_microbe_config import default_config_path
from kg_microbe_fleet import default_manifest_path, load_fleet_manifest
from kg_microbe_governance import load_governance_manifest
from kg_microbe_governance.__main__ import main as governance_main
from kg_microbe_history.__main__ import _default_schema_path, main as history_main
from kg_microbe_research.__main__ import (
    build_parser as build_research_parser,
    main as research_main,
)

unpacked = Path(sys.argv[1]).resolve()
runtime_modules = (
    cli_package,
    kg_microbe_agents,
    kg_microbe_config,
    kg_microbe_fleet,
    kg_microbe_governance,
    kg_microbe_governance.fleet_audit,
    kg_microbe_history,
    kg_microbe_research,
    kg_microbe_research.__main__,
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
governance = load_governance_manifest(fleet_manifest=manifest)
assert len(governance.artifacts) == 14
assert governance_main(["list", "--repository", "proteintraitsmech", "--json"]) == 0
history_schema = Path(_default_schema_path()).resolve()
assert history_schema.is_relative_to(unpacked)
assert history_schema == (
    unpacked / "kg_microbe_governance/artifacts/schema/history.yaml"
)
history_root = Path(sys.argv[2])
assert history_main([
    "new", "--history-root", str(history_root), "--kind", "record",
    "--slug", "wheel-smoke", "--target-root", "data", "--summary", "smoke",
    "--details", "validated from the unpacked wheel",
]) == 0
assert history_main(["validate", str(history_root), "--structural-only"]) == 0
assert build_research_parser().prog == "kg-microbe-research"
research_profile = history_root.parent / "wheel-research-profile.json"
research_profile.write_text(json.dumps({
    "mech": "WheelMech",
    "target": "offline wheel smoke",
    "evidence_policy": "cite every material claim",
    "default_focus": "primary",
    "focuses": {"primary": {
        "label": "Primary",
        "objective": "Exercise installed triage and policy",
        "source_priorities": [],
        "provider_adjustments": {"asta": 1},
        "stages": {"discovery": {
            "objective": "Find evidence",
            "capabilities": {"academic_search": 1},
        }},
    }},
}), encoding="utf-8")
checked_at = datetime.now(timezone.utc)
research_evidence = history_root.parent / "wheel-availability.json"
research_evidence.write_text(json.dumps({
    "version": 1,
    "providers": {"asta": {
        "status": "available",
        "reason": "offline installed-wheel fixture",
        "checked_at": checked_at.isoformat(),
        "expires_at": (checked_at + timedelta(hours=1)).isoformat(),
        "source": "installed-wheel-smoke",
        "context": "fake credential in isolated subprocess",
    }},
}), encoding="utf-8")
os.environ["ASTA_API_KEY"] = "offline-wheel-fixture"
research_args = [
    "--profile", str(research_profile),
    "--availability-evidence", str(research_evidence),
    "--stage", "discovery", "--provider", "asta", "--json",
]
assert research_main(["triage", *research_args[:4], "--json"]) == 0
assert research_main(["authorize", *research_args]) == 3
assert research_main([
    "authorize", *research_args[:-1], "--apply", "--acknowledge-usage", "--json",
]) == 0
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
        [
            sys.executable,
            "-c",
            smoke_code,
            str(unpacked),
            str(tmp_path / "wheel-history"),
        ],
        cwd=tmp_path,
        env=smoke_environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert smoked.returncode == 0, smoked.stdout + smoked.stderr
