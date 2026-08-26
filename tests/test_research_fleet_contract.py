"""Fleet contracts for the shared research profile loader and policy.

The five checked-in fixtures are deterministic snapshots of the domain-owned
focus structures. They make CI exercise the exact canonical fleet even when no
sibling Mech checkout is configured. Configured local checkouts remain a useful
optional drift audit, but are never the only evidence behind a green run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_research import (
    PolicyError,
    ProfileError,
    ResearchProfile,
    StaticProbe,
    authorize,
    build_report,
    load_profile,
    plan_stage,
)

PROFILE_RELATIVE_PATH = Path("conf") / "deep_research_provider.yaml"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "research_profiles"
PROVENANCE_PATH = FIXTURE_ROOT / "provenance.json"
NO_LOCAL_TOOLING = StaticProbe()

EXPECTED_FOCUS_STAGES = {
    "culturemech": {
        "growth_evidence": ("discovery", "synthesis", "verification"),
        "formulation": ("discovery", "synthesis", "verification"),
    },
    "mediaingredientmech": {
        "identity_mapping": ("discovery", "synthesis", "verification"),
        "functional_roles": ("discovery", "synthesis", "verification"),
    },
    "communitymech": {
        "ecological_mechanism": ("discovery", "synthesis", "verification"),
        "datasets_environment": ("discovery", "synthesis", "verification"),
    },
    "traitmech": {
        "causal_mechanism": ("discovery", "synthesis", "verification"),
        "definition_grounding": ("discovery", "synthesis", "verification"),
    },
    "proteintraitsmech": {
        "mechanism": ("discovery", "synthesis", "verification"),
        "family_grounding": ("discovery", "synthesis", "verification"),
    },
}
EXPECTED_MECH_KEYS = tuple(EXPECTED_FOCUS_STAGES)


def _fixture_paths() -> dict[str, Path]:
    return {path.stem: path for path in sorted(FIXTURE_ROOT.glob("*.yaml"))}


def _focus_stages(profile: ResearchProfile) -> dict[str, tuple[str, ...]]:
    return {focus_name: tuple(focus.stages) for focus_name, focus in profile.focuses.items()}


def _provenance() -> dict[str, dict[str, Any]]:
    document = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert set(document) == {"version", "profiles"}
    assert isinstance(document["profiles"], dict)
    return document["profiles"]


def _configured_mech_profiles() -> list[tuple[str, Path]]:
    """Return configured local profiles for the optional drift audit."""
    manifest = load_fleet_manifest()
    found = []
    for key, mech in manifest.mechs.items():
        root = os.environ.get(mech.environment_variable, "").strip()
        if not root:
            continue
        candidate = Path(root).expanduser() / PROFILE_RELATIVE_PATH
        if not candidate.is_file():
            raise AssertionError(
                f"{mech.environment_variable} is set but the research profile "
                f"does not exist: {candidate}"
            )
        found.append((key, candidate))
    return found


def test_fixture_inventory_matches_the_exact_manifest_fleet() -> None:
    manifest = load_fleet_manifest()
    assert manifest.keys == EXPECTED_MECH_KEYS
    assert set(_fixture_paths()) == set(manifest.keys)
    assert set(_provenance()) == set(manifest.keys)


@pytest.mark.parametrize("key", EXPECTED_MECH_KEYS)
def test_fixture_bytes_are_locked_to_machine_readable_provenance(key: str) -> None:
    manifest = load_fleet_manifest()
    record = _provenance()[key]
    assert set(record) == {"repository", "commit", "path", "sha256"}
    assert record["repository"] == manifest.mechs[key].github
    assert record["path"] == PROFILE_RELATIVE_PATH.as_posix()
    assert re.fullmatch(r"[0-9a-f]{40}", record["commit"])
    digest = hashlib.sha256(_fixture_paths()[key].read_bytes()).hexdigest()
    assert digest == record["sha256"]


@pytest.mark.parametrize("key", EXPECTED_MECH_KEYS)
def test_owned_profile_fixture_preserves_identity_and_focus_structure(key: str) -> None:
    manifest = load_fleet_manifest()
    profile = load_profile(_fixture_paths()[key])

    assert profile.mech == manifest.mechs[key].display_name
    assert profile.default_focus in profile.focuses
    assert _focus_stages(profile) == EXPECTED_FOCUS_STAGES[key]


@pytest.mark.parametrize("key", EXPECTED_MECH_KEYS)
def test_every_owned_focus_ranks_offline(key: str) -> None:
    profile = load_profile(_fixture_paths()[key])
    for focus_name in profile.focuses:
        report = build_report(profile, focus_name, environ={}, probe=NO_LOCAL_TOOLING)
        assert report["stages"], f"{key}/{focus_name} produced no stages"
        for stage in report["stages"]:
            assert len(stage["ranking"]) >= 1


@pytest.mark.parametrize("key", EXPECTED_MECH_KEYS)
def test_no_owned_profile_authorizes_a_call_without_configuration(key: str) -> None:
    """With no configured provider, every default-focus stage must refuse."""
    profile = load_profile(_fixture_paths()[key])
    for stage_name in profile.focus().stages:
        plan = plan_stage(
            profile,
            stage_name,
            environ={},
            probe=NO_LOCAL_TOOLING,
        )
        with pytest.raises(PolicyError, match="No provider is available"):
            authorize(plan, apply=True)


def test_configured_local_profiles_match_the_owned_contract() -> None:
    """Optionally detect downstream drift without making CI depend on siblings."""
    configured = _configured_mech_profiles()
    if not configured:
        pytest.skip("no Mech checkout is configured locally")

    manifest = load_fleet_manifest()
    for key, path in configured:
        profile = load_profile(path)
        assert profile.mech == manifest.mechs[key].display_name
        assert _focus_stages(profile) == EXPECTED_FOCUS_STAGES[key]
        assert profile == load_profile(_fixture_paths()[key])


def test_an_explicit_but_missing_local_root_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = load_fleet_manifest()
    for mech in manifest.mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    monkeypatch.setenv("CULTUREMECH_ROOT", str(tmp_path / "missing-culturemech"))
    with pytest.raises(AssertionError, match="CULTUREMECH_ROOT is set"):
        _configured_mech_profiles()


def test_a_profile_path_that_does_not_exist_raises_profile_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "conf" / "deep_research_provider.yaml")
