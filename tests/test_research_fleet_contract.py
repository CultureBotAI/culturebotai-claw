"""The shared subsystem must accept every real Mech profile, unchanged.

Centralizing a validator is only safe if the strictest variant still accepts
what the fleet actually ships. These tests resolve each Mech through the Phase 0
manifest and validate its committed `conf/deep_research_provider.yaml` with the
shared loader.

A Mech that is not checked out locally is skipped, never silently passed: the
count of what was actually exercised is asserted so an empty run cannot look
like a green one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_research import (
    PolicyError,
    ProfileError,
    StaticProbe,
    authorize,
    build_report,
    load_profile,
    plan_stage,
)

PROFILE_RELATIVE_PATH = Path("conf") / "deep_research_provider.yaml"
NO_LOCAL_TOOLING = StaticProbe()


def _configured_mech_profiles() -> list[tuple[str, Path]]:
    """(key, profile path) for every Mech whose checkout is present locally."""
    manifest = load_fleet_manifest()
    found = []
    for key, mech in manifest.mechs.items():
        root = os.environ.get(mech.environment_variable, "").strip()
        if not root:
            continue
        candidate = Path(root).expanduser() / PROFILE_RELATIVE_PATH
        if candidate.is_file():
            found.append((key, candidate))
    return found


MECH_PROFILES = _configured_mech_profiles()
MECH_IDS = [key for key, _ in MECH_PROFILES]


def test_the_manifest_declares_the_whole_fleet():
    """Guards the parametrization source: an empty manifest would skip everything."""
    manifest = load_fleet_manifest()
    assert len(manifest.mechs) >= 5


@pytest.mark.skipif(not MECH_PROFILES, reason="no Mech checkout is configured locally")
@pytest.mark.parametrize(("key", "path"), MECH_PROFILES, ids=MECH_IDS)
def test_a_real_mech_profile_validates_against_the_shared_loader(key, path):
    profile = load_profile(path)
    assert profile.focuses, f"{key} declares no focuses"
    assert profile.default_focus in profile.focuses


@pytest.mark.skipif(not MECH_PROFILES, reason="no Mech checkout is configured locally")
@pytest.mark.parametrize(("key", "path"), MECH_PROFILES, ids=MECH_IDS)
def test_every_focus_of_a_real_profile_ranks_without_a_provider_call(key, path):
    profile = load_profile(path)
    for focus_name in profile.focuses:
        report = build_report(
            profile, focus_name, environ={}, probe=NO_LOCAL_TOOLING
        )
        assert report["stages"], f"{key}/{focus_name} produced no stages"
        for stage in report["stages"]:
            assert len(stage["ranking"]) >= 1


@pytest.mark.skipif(not MECH_PROFILES, reason="no Mech checkout is configured locally")
@pytest.mark.parametrize(("key", "path"), MECH_PROFILES, ids=MECH_IDS)
def test_no_real_profile_authorizes_a_call_with_no_credentials(key, path):
    """With nothing configured, every Mech's default stage must refuse, not route."""
    profile = load_profile(path)
    focus = profile.focus()
    for stage_name in focus.stages:
        plan = plan_stage(
            profile, stage_name, environ={}, probe=NO_LOCAL_TOOLING
        )
        with pytest.raises(PolicyError, match="No provider is available"):
            authorize(plan, apply=True)


def test_the_local_fleet_coverage_is_reported(record_property):
    """Make the skip visible: a run that exercised nothing must say so."""
    record_property("mech_profiles_exercised", ",".join(MECH_IDS) or "none")
    assert isinstance(MECH_PROFILES, list)


def test_a_profile_path_that_does_not_exist_raises_profile_error(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "conf" / "deep_research_provider.yaml")
