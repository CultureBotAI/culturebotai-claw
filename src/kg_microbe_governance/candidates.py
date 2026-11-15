"""Explicit preparation identities, separate from deployed/public fleet membership."""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Any

from kg_microbe_fleet import load_fleet_manifest

from .artifacts.scripts.check_vendored_sync import (
    GovernanceError,
    parse_candidate_registry,
    parse_manifest,
)


def registry_bytes() -> bytes:
    return files("kg_microbe_governance").joinpath("candidates.json").read_bytes()


def load_candidates() -> dict[str, dict[str, Any]]:
    """Validate identities and every current capability decision; never enable one."""
    package = files("kg_microbe_governance")
    manifest = parse_manifest(package.joinpath("vendored_artifacts.json").read_bytes())
    candidates = parse_candidate_registry(registry_bytes(), manifest)
    fleet = load_fleet_manifest()
    private = json.loads(package.joinpath("private_audit/scaleup-v1.json").read_bytes())
    envs = {mech.environment_variable for mech in fleet.mechs.values()}
    private_key = private["repository"].rsplit("/", 1)[-1].lower()
    private_schema = next(item["target"] for item in private["artifacts"] if item["id"] == "shared_mech_schema")
    private_package = str(PurePosixPath(private_schema).parent.parent)
    for key, candidate in candidates.items():
        if key in fleet.mechs or candidate["environment_variable"] in envs:
            raise GovernanceError("Candidate overlaps a fleet key/root environment")
        if (key == private_key or candidate["github"].casefold() == private["repository"].casefold()
                or candidate["package_path"].casefold() == private_package.casefold()
                or candidate["environment_variable"] == private_key.upper() + "_ROOT"):
            raise GovernanceError("Candidate overlaps a separately governed private identity")
        if set(candidate["capabilities"]) != set(fleet.capability_catalogue):
            raise GovernanceError("Candidate must decide every current fleet capability")
        for name in ("kgx_export", "sssom_export"):
            if candidate["capabilities"][name]["status"] != "disabled":
                raise GovernanceError(f"Candidate {name} applies to every Mech and must be disabled")
    return candidates
