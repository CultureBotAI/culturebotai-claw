"""Fleet adoption and profile contracts for cached-source quote validation (#687)."""

from pathlib import Path

import pytest
import yaml

from kg_microbe_evidence import EvidenceConfig, EvidenceError
from kg_microbe_fleet import (
    FleetManifestError,
    load_fleet_manifest,
    parse_fleet_manifest,
)

MANIFEST = Path(__file__).resolve().parents[1] / "src/kg_microbe_fleet/fleet.yaml"
CAPABILITY = "evidence_reference_validation"


def _document():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _canary(document):
    return document["mechs"]["mediaingredientmech"]["capabilities"][CAPABILITY]


LEDGER = "curation/evidence_known_findings.tsv"
# The rollout release (#729): MIM's bounded canary plus two measured adopters.
EXPECTED_PROFILES = {
    "mediaingredientmech": EvidenceConfig(
        cache_dir="references_cache",
        reference_fields=("pmid", "doi", "reference"),
        snippet_fields=("snippet", "excerpt", "supporting_text"),
        evidence_fields=("evidence",),
        evidence_paths=(
            "ontology_mapping.evidence", "role_assignments[].evidence",
            "cellular_role_assignments[].evidence",
        ),
    ),
    "cellstructuremech": EvidenceConfig(
        cache_dir="references_cache", reference_fields=("reference",),
        snippet_fields=("snippet",), known_findings=LEDGER,
    ),
    "habitatmech": EvidenceConfig(
        cache_dir="references_cache", reference_fields=("reference",),
        snippet_fields=("snippet",), known_findings=LEDGER,
    ),
}


def test_every_mech_declares_quote_validation_and_exactly_the_adopters_are_enabled():
    manifest = load_fleet_manifest(MANIFEST)
    assert CAPABILITY in manifest.capability_names
    assert set(manifest.with_capability(CAPABILITY)) == set(EXPECTED_PROFILES)
    for mech in manifest.mechs.values():
        capability = mech.capability(CAPABILITY)
        assert capability is not None
        if mech.key not in EXPECTED_PROFILES:
            assert capability.status == "disabled"
            assert capability.reason


def test_enabled_manifest_settings_are_the_reviewed_evidence_profiles():
    manifest = load_fleet_manifest(MANIFEST)
    for key in manifest.with_capability(CAPABILITY):
        capability = manifest.get(key).capability(CAPABILITY)
        assert EvidenceConfig.from_settings(capability.settings) == EXPECTED_PROFILES[key]


def test_known_findings_is_a_declared_string_setting():
    document = _document()
    _canary(document)["settings"]["known_findings"] = ["curation/ledger.tsv"]
    with pytest.raises(FleetManifestError, match=CAPABILITY):
        parse_fleet_manifest(document, MANIFEST)
    _canary(document)["settings"]["known_findings"] = "../outside.tsv"
    capability = parse_fleet_manifest(document, MANIFEST).get("mediaingredientmech").capability(CAPABILITY)
    with pytest.raises(EvidenceError, match="known_findings"):
        EvidenceConfig.from_settings(capability.settings)
    _canary(document)["settings"]["known_findings"] = LEDGER
    capability = parse_fleet_manifest(document, MANIFEST).get("mediaingredientmech").capability(CAPABILITY)
    assert EvidenceConfig.from_settings(capability.settings).known_findings == LEDGER


def test_omitting_a_mech_declaration_is_not_silently_disabled():
    document = _document()
    del document["mechs"]["cmmmech"]["capabilities"][CAPABILITY]
    with pytest.raises(FleetManifestError, match=CAPABILITY):
        parse_fleet_manifest(document, MANIFEST)


@pytest.mark.parametrize("status", ["disabled", "not_applicable"])
def test_an_off_declaration_requires_its_own_reason(status):
    document = _document()
    document["mechs"]["cmmmech"]["capabilities"][CAPABILITY] = {"status": status}
    with pytest.raises(FleetManifestError, match="reason"):
        parse_fleet_manifest(document, MANIFEST)


def test_enabled_profile_requires_an_explicit_cache_directory():
    document = _document()
    del _canary(document)["settings"]["cache_dir"]
    with pytest.raises(FleetManifestError, match="missing required keys: cache_dir"):
        parse_fleet_manifest(document, MANIFEST)


@pytest.mark.parametrize(
    "settings",
    [
        {"cache_dir": ["references_cache"]},
        {"cache_dir": "references_cache", "reference_fields": "reference"},
        {"cache_dir": "references_cache", "snippet_fields": [1]},
        {"cache_dir": "references_cache", "evidence_fields": []},
        {"cache_dir": "references_cache", "snippet_fields": ["quote", "quote"]},
        {"cache_dir": "references_cache", "evidence_paths": "ontology_mapping.evidence"},
        {"cache_dir": "references_cache", "evidence_paths": [1]},
        {"cache_dir": "references_cache", "evidence_paths": []},
        {"cache_dir": "references_cache", "skip_missing": True},
    ],
)
def test_manifest_rejects_malformed_or_unknown_profile_settings(settings):
    document = _document()
    _canary(document)["settings"] = settings
    with pytest.raises(FleetManifestError, match=CAPABILITY):
        parse_fleet_manifest(document, MANIFEST)


def test_optional_field_mappings_can_be_omitted_or_override_defaults():
    document = _document()
    _canary(document)["settings"] = {"cache_dir": "sources/abstracts"}
    manifest = parse_fleet_manifest(document, MANIFEST)
    capability = manifest.get("mediaingredientmech").capability(CAPABILITY)
    assert EvidenceConfig.from_settings(capability.settings) == EvidenceConfig(
        cache_dir="sources/abstracts"
    )

    _canary(document)["settings"].update(
        reference_fields=["citation"], snippet_fields=["quote"],
        evidence_fields=["support"],
        evidence_paths=["claims[].support"],
    )
    manifest = parse_fleet_manifest(document, MANIFEST)
    capability = manifest.get("mediaingredientmech").capability(CAPABILITY)
    assert EvidenceConfig.from_settings(capability.settings) == EvidenceConfig(
        cache_dir="sources/abstracts", reference_fields=("citation",),
        snippet_fields=("quote",), evidence_fields=("support",),
        evidence_paths=("claims[].support",),
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"cache_dir": "../another-repository"},
        {"cache_dir": "/outside-the-repository"},
        {"cache_dir": "references_cache", "reference_fields": ["citation.reference"]},
        {"cache_dir": "references_cache", "evidence_paths": ["ontology_mapping..evidence"]},
        {"cache_dir": "references_cache", "evidence_paths": ["$.ontology_mapping.evidence"]},
        {"cache_dir": "references_cache", "evidence_paths": ["claims[0].evidence"]},
    ],
)
def test_profile_semantics_refuse_unsafe_paths_and_unsupported_selectors(settings):
    document = _document()
    _canary(document)["settings"] = settings
    manifest = parse_fleet_manifest(document, MANIFEST)
    capability = manifest.get("mediaingredientmech").capability(CAPABILITY)
    with pytest.raises(EvidenceError):
        EvidenceConfig.from_settings(capability.settings)
