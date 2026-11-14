"""Offline checks of the public discussion contract (claw#1212, 2026-11-14)."""
import json
import tomllib
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from kg_microbe_discussions.public_export import (
    SCHEMA,
    SCHEMA_PATH,
    PublicExportError,
    normalize_record,
    validate_item,
    validate_items,
)

# Minimal current-authority fixtures derived from retained public source pins.
# Trait: 2ccbc22ccfb8bd00c9d9ca70e11e020f818fbc18,
# data/traits/ecology/animal_pathogen.yaml, kgscan-30bcdf4a32b0.
# MIM: 24d76baa823d7fd07e8ea2596f0cca50e66392e2,
# data/ingredients/mapped/1-Kestose.yaml, kgscan-f77a72b7ddb7.
# Prompts are shortened synthetic stand-ins; classification inputs are retained.
TRAIT = {
    "id": "trait:animal_pathogen", "name": "Animal pathogen",
    "discussions": [{
        "discussion_id": "kgscan-30bcdf4a32b0", "prompt": "Are the two immune-evasion routes redundant?",
        "kind": "KNOWLEDGE_GAP", "status": "OPEN", "posed_by": "claude",
        "rationale": "The graph does not say whether the routes are alternatives or partners.",
        "notes": "Historical scanner provenance; discarded evidence is not current support.",
        "posed_date": "2026-08-17",
    }],
}
MIM = {
    "id": "CHEBI:27931", "name": "1-Kestose",
    "discussions": [{
        "discussion_id": "kgscan-f77a72b7ddb7", "prompt": "Which mechanism remains unresolved?",
        "kind": "KNOWLEDGE_GAP", "status": "OPEN", "posed_by": "kg-microbe-kgscan",
        "rationale": "Curator review required: set attaches_to, refine the prompt, and weigh the cited evidence.",
    }],
}
CONTEXT = {
    "mech": "TraitMech", "repository": "CultureBotAI/TraitMech", "revision": "a" * 40,
    "path": "data/traits/ecology/animal_pathogen.yaml", "source_sha256": "b" * 64,
    "root_config": {"id_field": "id", "name_fields": ["name"]}, "license": "CC-BY-4.0",
}


def project(doc=None, **overrides):
    return normalize_record(deepcopy(TRAIT if doc is None else doc), **{**CONTEXT, **overrides})


def test_corrected_scanner_id_is_not_current_scanner_attribution():
    item = project()[0]
    assert (item["origin"], item["review_state"], item["lane"]) == ("other", "unspecified", "recorded")
    assert item["classification_reason"] == "current_other_attribution"
    assert "posed_by" not in item and "notes" not in item
    assert item["source"]["locator"] == "discussions#kgscan-30bcdf4a32b0"


def test_native_scanner_discussion_is_a_candidate_before_artifact_ingestion():
    item = project(MIM)[0]
    assert (item["origin"], item["review_state"], item["lane"]) == ("scanner", "required", "candidate")
    assert item["classification_reason"] == "explicit_review_requirement"
    assert item["storage_mode"] == "native_record"


def test_scanner_attribution_without_phrase_stays_candidate_without_invented_review():
    doc = deepcopy(MIM)
    del doc["discussions"][0]["rationale"]
    item = project(doc)[0]
    assert (item["origin"], item["review_state"], item["lane"]) == ("scanner", "unspecified", "candidate")


def test_review_requirement_applies_to_non_scanner_attribution():
    doc = deepcopy(TRAIT)
    doc["discussions"][0]["rationale"] = "Curator\nreview REQUIRED: inspect the evidence."
    assert project(doc)[0]["lane"] == "candidate"


def test_no_attribution_or_enums_stays_unspecified():
    item = project({"id": "x", "discussions": [{"discussion_id": "d", "prompt": "Question?"}]})[0]
    assert (item["kind"], item["status"], item["origin"], item["review_state"]) == (
        "UNSPECIFIED", "UNSPECIFIED", "unspecified", "unspecified")
    assert item["record_label"] == "x"
    assert item["posed_date"] == item["resolved_date"] == ""


def test_identity_is_order_and_prose_independent_but_distinguishes_record_paths_and_repos():
    doc = deepcopy(TRAIT)
    second = deepcopy(doc["discussions"][0])
    second["discussion_id"] = "second"
    doc["discussions"].append(second)
    before = project(doc)
    doc["discussions"].reverse()
    doc["discussions"][0]["prompt"] = "Revised question?"
    after = project(doc, revision="c" * 40)
    assert {i["id"] for i in before} == {i["id"] for i in after}
    assert len(before[0]["id"]) == 68
    assert project(repository="CultureBotAI/OtherMech")[0]["id"] != project()[0]["id"]
    assert project(path="data/traits/another-record.yaml")[0]["id"] != project()[0]["id"]
    assert project(repository="culturebotai/traitmech")[0]["id"] == project()[0]["id"]


def test_duplicate_identity_is_rejected_both_within_record_and_bundle():
    doc = deepcopy(TRAIT)
    doc["discussions"].append(deepcopy(doc["discussions"][0]))
    with pytest.raises(PublicExportError, match="Duplicate"):
        project(doc)
    with pytest.raises(PublicExportError, match="Duplicate"):
        validate_items(project() * 2)


def test_all_native_experiment_fields_survive_without_notes_or_source_mutation():
    doc = deepcopy(TRAIT)
    experiment = {
        "experiment_id": "exp:1", "name": "Compare conditions", "description": "Description",
        "approach": "Comparison", "model_systems": ["Model"], "perturbations": ["Condition"],
        "readouts": ["Measurement"], "decision_criterion": "Discriminating observation",
        "would_support": "Supporting outcome", "would_refute": "Refuting outcome",
    }
    doc["discussions"][0]["proposed_experiments"] = [{**experiment, "notes": "private@example.invalid"}]
    original = deepcopy(doc)
    item = project(doc)[0]
    assert item["proposed_experiments"] == [experiment]
    assert doc == original
    schema = yaml.safe_load((Path(__file__).parents[1] /
                            "src/kg_microbe_governance/artifacts/schema/mech_shared.yaml").read_text())
    assert set(experiment) == set(schema["classes"]["ProposedExperiment"]["attributes"])


def test_evidence_projection_drops_snippets_notes_and_attribution_but_retains_support():
    doc = deepcopy(MIM)
    doc["discussions"][0]["evidence"] = [{
        "reference": "PMID:123", "supports": "NO_EVIDENCE", "explanation": "Context only",
        "snippet": "Do not republish this source excerpt.", "notes": "private@example.invalid",
    }, {"reference": "PMID:123"}]
    doc["discussions"][0]["posed_by"] = "person@example.invalid"
    item = project(doc)[0]
    assert item["evidence"] == [
        {"reference": "PMID:123", "supports": "NO_EVIDENCE", "explanation": "Context only"},
        {"reference": "PMID:123", "supports": "UNSPECIFIED", "explanation": ""},
    ]
    assert item["evidence_refs"] == ["PMID:123"]
    assert "example.invalid" not in json.dumps(item)


def test_aliases_require_explicit_dictionary_fields_and_allow_scalars():
    doc = deepcopy(TRAIT)
    doc["synonyms"] = ["second", {"value": "first", "notes": "private@example.invalid"}, "second"]
    config = {**CONTEXT["root_config"], "alias_fields": ["synonyms"], "alias_value_fields": ["value"]}
    assert project(doc, root_config=config)[0]["aliases"] == ["first", "second"]
    with pytest.raises(PublicExportError):
        project(doc, root_config={**config, "alias_value_fields": []})
    doc["synonyms"] = "single"
    assert project(doc, root_config=config)[0]["aliases"] == ["single"]


@pytest.mark.parametrize("field,value", [
    ("discussion_id", ""), ("prompt", 3), ("rationale", None), ("status", "CLOSED"),
    ("kind", "UNKNOWN"), ("attaches_to", "record#node"), ("evidence", {}),
    ("proposed_experiments", ["experiment"]), ("posed_date", "2026-02-30"),
    ("posed_date", "20261114"), ("posed_date", datetime(2026, 11, 14, tzinfo=timezone.utc)),
    ("evidence", [{"reference": []}]), ("evidence", [{"reference": "PMID:1", "supports": "TRUE"}]),
])
def test_malformed_populated_records_fail_without_silent_skipping(field, value):
    doc = deepcopy(TRAIT)
    doc["discussions"][0][field] = value
    with pytest.raises(PublicExportError):
        project(doc)


def test_yaml_calendar_dates_preserved_as_iso_and_bad_records_refused():
    doc = deepcopy(TRAIT)
    doc["discussions"][0]["posed_date"] = date(2026, 11, 14)
    assert project(doc)[0]["posed_date"] == "2026-11-14"
    assert project({"id": "x"}) == project({"discussions": []}) == []
    with pytest.raises(PublicExportError):
        project({"discussions": None})
    with pytest.raises(PublicExportError):
        project({"discussions": TRAIT["discussions"]})


@pytest.mark.parametrize("override", [
    {"path": "../data/record.yaml"}, {"path": "/data/record.yaml"}, {"path": "data//record.yaml"},
    {"path": "data\\record.yaml"}, {"revision": "main"}, {"source_sha256": "unknown"},
    {"repository": "owner/repo/extra"}, {"record_url": "javascript:alert(1)"},
    {"record_url": "https://user:password@example.org/record"},
    {"record_url": "https://example.org/\nrecord"},
])
def test_unsafe_or_unpinned_source_is_refused(override):
    with pytest.raises(PublicExportError):
        project(**override)


def test_source_paths_are_encoded_and_native_locators_may_be_explicitly_replaced():
    item = project(path="data/Record name#1.yaml")[0]
    assert item["source"]["url"].endswith("/data/Record%20name%231.yaml")
    item["source"]["locator"] = "research_gaps[scope=protocol]"
    validate_item(item)


@pytest.mark.parametrize("mutate", [
    lambda i: i.update(id="gap-" + "0" * 64),
    lambda i: i.update(lane="candidate"),
    lambda i: i.update(review_state="required"),
    lambda i: i.update(storage_mode="scanner_artifact"),
    lambda i: i.update(evidence_refs=["PMID:1"]),
    lambda i: i.update(notes="extra"),
    lambda i: i["source"].update(url="https://github.com/wrong/repo/blob/main/file"),
    lambda i: i["source"].update(private="extra"),
    lambda i: i.update(prompt="Contact person@example.invalid"),
    lambda i: i.update(posed_date="2026-02-30"),
])
def test_public_validation_rejects_semantic_and_closed_shape_mutations(mutate):
    item = project()[0]
    mutate(item)
    with pytest.raises(PublicExportError):
        validate_item(item)


def test_shared_enum_and_package_resource_contract():
    root = Path(__file__).parents[1]
    schema = yaml.safe_load((root / "src/kg_microbe_governance/artifacts/schema/mech_shared.yaml").read_text())
    assert set(SCHEMA["properties"]["kind"]["enum"]) == {
        "UNSPECIFIED", *schema["enums"]["DiscussionKindEnum"]["permissible_values"]}
    assert set(SCHEMA["properties"]["status"]["enum"]) == {
        "UNSPECIFIED", *schema["enums"]["DiscussionStatusEnum"]["permissible_values"]}
    config = tomllib.loads((root / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["kg_microbe_discussions"]
    assert any(SCHEMA_PATH.match(pattern) for pattern in patterns)
