#!/usr/bin/env python3
"""Prepare EdgeMech's reviewed scaffold; CLAW #766/#767, 2026-11-07.

Inputs: canonical fleet manifest and explicit empty feature worktree.
Outputs: additive fleet registration or a guarded native scaffold/lease receipt.
No credentials, providers or scientific records are read or changed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from kg_microbe_fleet import load_fleet_manifest, parse_fleet_manifest
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositorySettings

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "feat/storage-adapters-766-767-20261107"
CLAW_PIN = "1b5391d083ba85ac94e5279c3cba25ac4fde243c"


def register() -> None:
    """Add an honest initially-disabled declaration without rewriting other Mechs."""
    path = ROOT / "src/kg_microbe_fleet/fleet.yaml"
    manifest = load_fleet_manifest(path)
    if "edgemech" in manifest.mechs:
        raise ValueError("EdgeMech is already registered; review rather than replace")
    capabilities = {
        key: {
            "status": "disabled",
            "reason": "Initial integration scaffold; this fleet capability has not been verified.",
        }
        for key in manifest.capability_names
    }
    capabilities["vendored_sync"] = {"status": "enabled"}
    capabilities["unmapped_inventory_input"] = {
        "status": "not_applicable",
        "reason": "External edge accounting is not a culture-medium ingredient corpus.",
    }
    declaration = {
        "edgemech": {
            "display_name": "EdgeMech",
            "github": "CultureBotAI/EdgeMech",
            "environment_variable": "EDGEMECH_ROOT",
            "package_path": "src/edgemech",
            "schema_paths": ["src/edgemech/schema/edgemech.yaml"],
            "record_globs": ["curation/packets/*.yaml"],
            "vendored_role": "consumer",
            "capabilities": capabilities,
        }
    }
    block = yaml.safe_dump(declaration, sort_keys=False)
    path.write_text(path.read_text() + "\n" + "".join("  " + line for line in block.splitlines(True)))
    parse_fleet_manifest(yaml.safe_load(path.read_text()), path)
    env_path = ROOT / ".env.example"
    env_path.write_text(env_path.read_text() + "\nEDGEMECH_ROOT=/absolute/path/to/EdgeMech\n")
    config_path = ROOT / "src/kg_microbe_config/openclaw_config.yaml"
    config_path.write_text(config_path.read_text().replace(
        "\nagents:\n",
        '\n  edgemech:\n    path: ${EDGEMECH_ROOT}\n    type: python\n'
        '    package_manager: uv\n    task_runner: just\n'
        '    description: "Release-occurrence accounting and inherited review eligibility"\n\nagents:\n',
        1,
    ))


def target(root: Path):
    """Resolve the exact feature checkout through the canonical registry."""
    settings = RepositorySettings.from_environment(environ={"EDGEMECH_ROOT": str(root)})
    result = settings.get_target("edgemech")
    repo = result.open()
    if Path(repo.working_tree_dir).resolve() != root.resolve() or repo.active_branch.name != BRANCH:
        raise ValueError("Unexpected EdgeMech worktree or branch")
    return result


def scaffold(root: Path) -> None:
    """Create only absent scaffold files under a validated, locked repository."""
    resolved = target(root)
    files = {
        ".gitignore": ".venv/\n__pycache__/\n*.py[cod]\n.pytest_cache/\n.coverage\nhtmlcov/\n.ruff_cache/\nworkspace/\nbuild/\ndist/\n*.egg-info/\n.env\n",
        "AGENTS.md": "# EdgeMech agreements\n\nKeep shared identities, review semantics and artifact schemas in pinned CLAW.\nBulk graphs, Parquet and full histories stay outside Git under workspace/.\nNever infer scientific approval from transport validity, endpoints or inherited review.\nPreserve exact source rows, occurrence multiplicity and input/evidence identities.\nUse branch/PR/read-only adversarial review/issues; merges require explicit approval.\nCanary the actual production path and inspect persisted artifacts before batches.\nHelpers belong in scripts/adhoc/ and accompany their results in Git.\nRun focused tests during iteration and the complete suite on the final candidate.\n",
        "README.md": "# EdgeMech\n\nRelease-occurrence accounting and inherited native-review eligibility for KG-Microbe.\n\nEdgeMech keeps bulk rows and decision histories in immutable external Parquet artifacts and queries them with DuckDB. Shared contracts are owned by CultureBotAI/culturebotai-claw. Scientific records and decisions remain in their native Mechs.\n\nDevelopment scope: CLAW issues #766 and #767. No live curation worker, published site, or scientific approval is implied.\n",
        "pyproject.toml": f'''[project]
name = "edgemech"
version = "0.1.0"
description = "Pinned release-occurrence storage and native review eligibility"
readme = "README.md"
requires-python = ">=3.11,<3.15"
dependencies = [
  "duckdb==2.0.0",
  "pyarrow==26.0.1",
  "pyyaml==6.0.3",
  "kg-microbe-orchestration @ git+https://github.com/CultureBotAI/culturebotai-claw.git@{CLAW_PIN}",
]

[project.optional-dependencies]
dev = ["pytest>=9,<10", "ruff==0.16.3"]

[project.scripts]
edgemech = "edgemech.__main__:main"

[build-system]
requires = ["setuptools>=81,<82"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
edgemech = ["schema/*.yaml", "contract-pins.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I"]
''',
        "src/edgemech/__init__.py": '"""EdgeMech: transport and eligibility never imply scientific approval."""\n',
        "src/edgemech/schema/edgemech.yaml": "id: https://w3id.org/culturebotai/edgemech/routing\nname: edgemech_routing\nprefixes:\n  linkml: https://w3id.org/linkml/\n  edgemech: https://w3id.org/culturebotai/edgemech/\ndefault_prefix: edgemech\nimports: [linkml:types]\nclasses:\n  RoutingRule:\n    description: Owner routing only; canonical curation schemas remain in CLAW.\n    attributes:\n      owner:\n        range: string\n        required: true\n      scope:\n        range: string\n        required: true\n",
        "conf/routing.yaml": "version: 1\ncontract: kg-microbe-curation/v1\ndefault: unresolved\nroutes:\n  - owner: mediaingredientmech\n    scope: exact ingredient mapping identity; no organism-growth inference\n  - owner: traitmech\n    scope: scoped organism observations; generic mechanisms are not assay evidence\n  - owner: habitatmech\n    scope: distinguish isolation, association, characteristic habitat and causal explanation\n  - owner: taxonmech\n    scope: versioned rank and identity mappings; broad/close is not exact\n",
    }
    with LockManager().lock("edgemech", "scaffold-766"):
        resolved.open()
        for relative, content in files.items():
            path = root / relative
            if path.exists() or path.is_symlink():
                raise ValueError(f"Refusing existing scaffold file: {relative}")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as handle:
                handle.write(content)
    print(json.dumps({"root": str(root), "branch": BRANCH, "files": sorted(files)}))


def hold(root: Path) -> None:
    """Hold a team source-edit lease until the controller closes stdin or releases it."""
    resolved = target(root)
    with LockManager().lock("edgemech", "milestones-766-767-source-edit"):
        resolved.open()
        print(json.dumps({"status": "lease-held", "pid": os.getpid(), "root": str(root)}), flush=True)
        for line in sys.stdin:
            if line.strip() == "release":
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["register", "scaffold", "hold"])
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.operation == "register":
        register()
    elif args.root is None:
        parser.error("--root required")
    elif args.operation == "scaffold":
        scaffold(args.root.resolve(strict=True))
    else:
        hold(args.root.resolve(strict=True))
