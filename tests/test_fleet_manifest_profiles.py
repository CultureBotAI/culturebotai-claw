"""Strict profile and capability-catalogue contracts for the fleet manifest."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import (
    FleetManifestError,
    load_fleet_manifest,
    parse_fleet_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "src" / "kg_microbe_fleet" / "fleet.yaml"

EXPECTED_PROFILES = {
    "culturemech": (
        "src/culturemech",
        ("src/culturemech/schema/culturemech.yaml",),
        ("data/merge_yaml/merged/*.yaml",),
    ),
    "mediaingredientmech": (
        "src/mediaingredientmech",
        ("src/mediaingredientmech/schema/mediaingredientmech.yaml",),
        ("data/ingredients/**/*.yaml",),
    ),
    "communitymech": (
        "src/communitymech",
        ("src/communitymech/schema/communitymech.yaml",),
        ("kb/communities/*.yaml", "data/isolates/*.yaml"),
    ),
    "traitmech": (
        "src/traitmech",
        ("src/traitmech/schema/traitmech.yaml",),
        ("data/traits/**/*.yaml",),
    ),
    "proteintraitsmech": (
        "src/proteintraitsmech",
        ("src/proteintraitsmech/schema/proteintraitsmech.yaml",),
        ("data/traits/**/*.yaml",),
    ),
    "cellstructuremech": (
        "src/cellstructuremech",
        ("src/cellstructuremech/schema/cellstructuremech.yaml",),
        ("data/structures/**/*.yaml",),
    ),
}

EXPECTED_CAPABILITIES = {
    # Declared by #223: who keeps a download.yaml source catalogue, and why
    # the three who do not have decided against one rather than forgotten.
    "source_catalogue",
    # Declared by Phase 6 item 4: which fields each Mech tabulates, so one
    # report shape can be compared across corpora.
    "corpus_statistics",
    # Phase 6 item 1: which Mech watches its generated site's size, and why
    # the four that do not have decided rather than forgotten.
    "page_budgets",
    # Phase 6 item 1: whose published pages are checked for a title, a declared
    # language, alt text, heading order and references that resolve -- and
    # which third-party host each of them has deliberately taken on.
    "site_contract",
    # Phase 7: whose YAML-writing scripts are audited by the shared rule, and
    # why the two that are not have decided rather than forgotten.
    "writer_audit",
    "id_label_validation",
    "curation_history",
    "strict_validation",
    "schema_sync",
    "release_management",
    "build_coordination",
    "documentation",
    "testing",
    "refactoring",
    "coordination_hooks",
    "deep_research",
    "edison_key_discovery",
    "environment_coverage",
    "knowledge_gap_scan",
    "vendored_sync",
    "unmapped_inventory_input",
}

EXPECTED_ENVIRONMENT_COVERAGE_GLOBS = {
    "culturemech": ("data/merge_yaml/merged/*.yaml",),
    "mediaingredientmech": ("data/ingredients/**/*.yaml",),
    # The historical dashboard covered the isolate inventory, not the much
    # broader kb/communities corpus used by other CommunityMech consumers.
    "communitymech": ("data/isolates/*.yaml",),
}


@pytest.fixture
def document() -> dict:
    loaded = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _parse(document: dict):
    return parse_fleet_manifest(document, Path("synthetic-fleet.yaml"))


def test_shipped_profiles_are_verified_and_complete() -> None:
    manifest = load_fleet_manifest(MANIFEST_PATH)

    assert set(manifest.capability_catalogue) == EXPECTED_CAPABILITIES
    for key, (package_path, schema_paths, record_globs) in EXPECTED_PROFILES.items():
        mech = manifest.get(key)
        assert mech.package_path == package_path
        assert mech.schema_paths == schema_paths
        assert mech.record_globs == record_globs
        assert set(mech.capabilities) == EXPECTED_CAPABILITIES


def test_capability_subsets_and_settings_are_manifest_driven() -> None:
    manifest = load_fleet_manifest(MANIFEST_PATH)

    assert manifest.with_capability("knowledge_gap_scan") == (
        "culturemech",
        "mediaingredientmech",
        "communitymech",
        "traitmech",
    )
    assert manifest.with_capability("environment_coverage") == (
        "culturemech",
        "mediaingredientmech",
        "communitymech",
    )
    assert manifest.with_capability("edison_key_discovery") == (
        "culturemech",
        "mediaingredientmech",
        "communitymech",
        "traitmech",
    )
    assert {
        key: manifest.get(key).capability("knowledge_gap_scan").settings["window"]
        for key in manifest.with_capability("knowledge_gap_scan")
    } == {
        "culturemech": 300,
        "mediaingredientmech": 300,
        "communitymech": 305,
        "traitmech": 300,
    }
    assert {
        key: manifest.get(key)
        .capability("environment_coverage")
        .settings["record_globs"]
        for key in manifest.with_capability("environment_coverage")
    } == EXPECTED_ENVIRONMENT_COVERAGE_GLOBS


def test_capability_and_catalogue_settings_are_immutable() -> None:
    manifest = load_fleet_manifest(MANIFEST_PATH)
    capability = manifest.get("culturemech").capability("knowledge_gap_scan")
    assert capability is not None

    with pytest.raises(TypeError):
        capability.settings["window"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        manifest.get("culturemech").capabilities["new"] = capability  # type: ignore[index]
    with pytest.raises(TypeError):
        manifest.capability_catalogue["knowledge_gap_scan"].settings["new"] = (  # type: ignore[index]
            manifest.capability_catalogue["knowledge_gap_scan"].settings["window"]
        )
    coverage = manifest.get("communitymech").capability("environment_coverage")
    assert coverage is not None
    assert isinstance(coverage.settings["record_globs"], tuple)
    with pytest.raises(TypeError):
        coverage.settings["record_globs"][0] = "kb/communities/*.yaml"  # type: ignore[index]


def test_missing_capability_declaration_is_rejected(document: dict) -> None:
    del document["mechs"]["culturemech"]["capabilities"]["testing"]

    with pytest.raises(FleetManifestError, match="missing declarations: testing"):
        _parse(document)


def test_missing_capabilities_mapping_is_rejected(document: dict) -> None:
    del document["mechs"]["culturemech"]["capabilities"]

    with pytest.raises(FleetManifestError, match="capabilities is required"):
        _parse(document)


def test_unknown_capability_declaration_is_rejected(document: dict) -> None:
    document["mechs"]["culturemech"]["capabilities"]["testng"] = {
        "status": "enabled"
    }

    with pytest.raises(FleetManifestError, match="unknown declarations: testng"):
        _parse(document)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("package_path", "/tmp/package", "repository-relative"),
        ("package_path", "../package", "without traversal"),
        ("package_path", "src/*", "must not contain glob"),
        ("schema_paths", ["/tmp/schema.yaml"], "repository-relative"),
        ("schema_paths", ["src/schema/*.yaml"], "must not contain glob"),
        ("schema_paths", ["src/schema/schema.json"], "YAML schema"),
        ("record_globs", ["../data/*.yaml"], "without traversal"),
        ("record_globs", ["data/record.yaml"], "contain a glob"),
        ("record_globs", ["data/*.json"], "select YAML records"),
    ],
)
def test_invalid_profile_paths_are_rejected(
    document: dict, field: str, value: object, message: str
) -> None:
    document["mechs"]["culturemech"][field] = value

    with pytest.raises(FleetManifestError, match=message):
        _parse(document)


@pytest.mark.parametrize("field", ["package_path", "schema_paths", "record_globs"])
def test_required_profile_fields_cannot_be_omitted(document: dict, field: str) -> None:
    del document["mechs"]["culturemech"][field]

    with pytest.raises(FleetManifestError, match=field):
        _parse(document)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("300", "must be an integer"),
        (True, "must be an integer"),
        (0, "must be at least 1"),
    ],
)
def test_capability_setting_type_and_bounds_are_enforced(
    document: dict, value: object, message: str
) -> None:
    document["mechs"]["culturemech"]["capabilities"]["knowledge_gap_scan"][
        "settings"
    ]["window"] = value

    with pytest.raises(FleetManifestError, match=message):
        _parse(document)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_capability_numbers_are_rejected(
    document: dict, value: float
) -> None:
    catalogue = document["capability_catalogue"]["knowledge_gap_scan"]["settings"]
    catalogue["confidence"] = {"type": "number"}
    for mech in document["mechs"].values():
        mech["capabilities"]["knowledge_gap_scan"].setdefault("settings", {})[
            "confidence"
        ] = 0.5
    document["mechs"]["culturemech"]["capabilities"]["knowledge_gap_scan"][
        "settings"
    ]["confidence"] = value

    with pytest.raises(FleetManifestError, match="must be a number"):
        _parse(document)


@pytest.mark.parametrize("minimum", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_capability_minimum_is_rejected(
    document: dict, minimum: float
) -> None:
    document["capability_catalogue"]["knowledge_gap_scan"]["settings"]["window"][
        "minimum"
    ] = minimum

    with pytest.raises(FleetManifestError, match="minimum requires"):
        _parse(document)


def test_required_enabled_capability_setting_cannot_be_omitted(document: dict) -> None:
    del document["mechs"]["culturemech"]["capabilities"]["knowledge_gap_scan"][
        "settings"
    ]["window"]

    with pytest.raises(FleetManifestError, match="missing required keys: window"):
        _parse(document)


def test_unknown_capability_setting_is_rejected(document: dict) -> None:
    document["mechs"]["culturemech"]["capabilities"]["knowledge_gap_scan"][
        "settings"
    ]["windwo"] = 300

    with pytest.raises(FleetManifestError, match="unknown keys: windwo"):
        _parse(document)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("data/isolates/*.yaml", "non-empty list"),
        ([], "non-empty list"),
        ([""], "non-empty string"),
        (["data/isolates/*.yaml", "data/isolates/*.yaml"], "duplicate values"),
        (["../data/*.yaml"], "without traversal"),
        (["data/isolate.yaml"], "contain a glob"),
        (["data/*.json"], "select YAML records"),
    ],
)
def test_environment_coverage_glob_setting_is_strict(
    document: dict, value: object, message: str
) -> None:
    document["mechs"]["communitymech"]["capabilities"][
        "environment_coverage"
    ]["settings"]["record_globs"] = value

    with pytest.raises(FleetManifestError, match=message):
        _parse(document)


def test_environment_coverage_globs_must_stay_within_general_profile(
    document: dict,
) -> None:
    document["mechs"]["communitymech"]["capabilities"][
        "environment_coverage"
    ]["settings"]["record_globs"] = ["data/other/*.yaml"]

    with pytest.raises(FleetManifestError, match="must be a subset"):
        _parse(document)


def test_catalogue_is_required(document: dict) -> None:
    del document["capability_catalogue"]

    with pytest.raises(FleetManifestError, match="capability_catalogue must be a mapping"):
        _parse(document)


def test_unknown_top_level_key_is_rejected(document: dict) -> None:
    document["capability_statuses"] = ["enabled"]

    with pytest.raises(FleetManifestError, match="unknown keys: capability_statuses"):
        _parse(document)
