"""Claw #1192: retain existing scoped CAS identities without granting approval."""

import csv
import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_mim_owned_name_export import builder, read_rows
from test_mim_owned_name_export import cli as cli
from test_mim_stable_identity import stable_cli as stable_cli
from test_registry_retirement_proposal import owner_index

NATIVE = builder._STABLE_PRODUCER
FIXTURES = Path(__file__).parent / "resources/cas_preservation1192"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def table(rows):
    out = io.StringIO()
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(out, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


@pytest.fixture
def actual(tmp_path):
    origin = json.loads((FIXTURES / "ORIGIN.json").read_bytes())
    canonical = (FIXTURES / "canonical-cas-rows.tsv").read_bytes()
    assert sha(canonical) == origin["extracted_canonical_sha256"]
    records = {}
    for owner in origin["owners"]:
        raw = (FIXTURES / owner["fixture"]).read_bytes()
        assert sha(raw) == owner["sha256"]
        records[tmp_path / owner["path"]] = yaml.safe_load(raw)
    # This exact four-owner unit extraction uses the native owner index, not a
    # fabricated claim that it is the complete sequential mint registry.
    subjects, index = owner_index(tmp_path, records)
    return tmp_path, records, subjects, index, canonical, origin


def test_1192_four_real_cas_rows_survive_ontology_primary_without_approval(actual):
    root, records, subjects, index, canonical, origin = actual
    before = deepcopy(records)
    objects = NATIVE.compatibility_registry_objects(records, subjects, index, canonical)
    assert {obj for values in objects.values() for obj in values} == {
        "cas:14919-49-4", "cas:12054-85-2", "cas:55449-49-5", "cas:65710-07-8"
    }
    for path, record in records.items():
        rows = builder._row_from_yaml(
            path, {}, {}, {}, {}, record=record, owners={},
            stable_subject=subjects[path], registry_objects=objects[subjects[path]],
        )
        cas = next(row for row in rows if row["object_id"].startswith("cas:"))
        assert cas["object_id"] == "cas:" + record["chemical_properties"]["cas_rn"]
        assert cas["predicate_id"] == "skos:exactMatch"
        assert cas["subject_id"] == record["mim_id"]
        assert cas["object_source"] == "registry:cas"
        assert cas["validation_method"] == ""
        assert any(row["object_id"] == record["ontology_mapping"]["ontology_id"] for row in rows)
    assert origin["original_release_disposition"] == "WITHHOLD"
    assert origin["scientific_approval"] is False
    assert records == before
    assert canonical == (FIXTURES / "canonical-cas-rows.tsv").read_bytes()


@pytest.mark.parametrize("change", ["different_cas", "missing_cas", "supplied_only", "contradictory_primary", "unmapped"])
def test_1192_current_owner_conflicts_require_review_not_silent_omission(actual, change):
    root, records, subjects, index, canonical, _ = actual
    record = next(iter(records.values()))
    rn = record["chemical_properties"]["cas_rn"]
    if change == "different_cas":
        record["chemical_properties"]["cas_rn"] = "7732-18-5"
    elif change in {"missing_cas", "supplied_only"}:
        record["chemical_properties"].pop("cas_rn")
        if change == "supplied_only":
            record["supplied_form"] = [{"cas_rn": rn}]
    elif change == "contradictory_primary":
        record["identifier"] = "cas:7732-18-5"
    else:
        record["mapping_status"] = "UNMAPPED"
    with pytest.raises(ValueError, match="CAS identity.*(evidence|review)"):
        NATIVE.compatibility_registry_objects(records, subjects, index, canonical)


@pytest.mark.parametrize("rn", ["14919-49-5", "１４９１９-49-4", "014919-49-4", "14919494", "14919-49-4 extra"])
def test_1192_malformed_or_wrong_check_digit_cannot_be_corroborated(actual, rn):
    root, records, subjects, index, canonical, _ = actual
    rows = read_rows(canonical)
    rows[0]["object_id"] = "cas:" + rn
    next(iter(records.values()))["chemical_properties"]["cas_rn"] = rn
    with pytest.raises(ValueError, match="canonical CAS"):
        NATIVE.compatibility_registry_objects(records, subjects, index, table(rows))


def test_1192_no_cas_identity_minted_from_metadata_alone(actual):
    root, records, subjects, index, canonical, _ = actual
    empty = canonical.splitlines(keepends=True)[0]
    objects = NATIVE.compatibility_registry_objects(records, subjects, index, empty)
    assert all(not value for value in objects.values())
    for path, record in records.items():
        rows = builder._row_from_yaml(path, {}, {}, {}, {}, record=record, owners={},
                                      stable_subject=subjects[path], registry_objects=objects[subjects[path]])
        assert not any(row["object_id"].startswith("cas:") for row in rows)


def test_1192_local_registry_and_corroborated_cas_are_not_competing_namespaces(actual):
    root, records, subjects, index, canonical, _ = actual
    record = next(iter(records.values()))
    record["identifier"] = "kgmicrobe.compound:Curated_Form"
    objects = NATIVE.compatibility_registry_objects(records, subjects, index, canonical)
    assert objects[record["mim_id"]] == ("cas:14919-49-4", "kgmicrobe.compound:Curated_Form")
    rows = read_rows(canonical)
    rows.append({**rows[0], "object_id": "kgmicrobe.ingredient:Conflicting_Form"})
    with pytest.raises(ValueError, match="Competing registry namespaces"):
        NATIVE.compatibility_registry_objects(records, subjects, index, table(rows))
    rows[-1]["object_id"] = "kgmicrobe.compound:" + record["mim_id"].split(":")[1]
    with pytest.raises(ValueError, match="Numeric MIM suffix"):
        NATIVE.compatibility_registry_objects(records, subjects, index, table(rows))


@pytest.mark.parametrize("unowned", ["MIM:Unknown_Original", "MIM:0009999", "unowned:identifier"])
def test_1192_unowned_or_ambiguous_alias_never_selects_cas_owner(actual, unowned):
    root, records, subjects, index, canonical, _ = actual
    rows = read_rows(canonical)
    rows[0]["subject_id"] = unowned
    with pytest.raises(ValueError, match="no (current stable|stable MIM) owner"):
        NATIVE.compatibility_registry_objects(records, subjects, index, table(rows))
    for record in list(records.values())[:2]:
        record["legacy_identifiers"].append("MIM:Shared_Original")
    subjects, index = owner_index(root, records)
    rows[0]["subject_id"] = "MIM:Shared_Original"
    with pytest.raises(ValueError, match="ambiguous"):
        NATIVE.compatibility_registry_objects(records, subjects, index, table(rows))


def test_1192_renamed_current_owner_keeps_cas_through_explicit_legacy_alias(actual):
    root, records, subjects, index, canonical, _ = actual
    path, record = next(iter(records.items()))
    old_alias = next(value for value in record["legacy_identifiers"] if value.startswith("MIM:"))
    renamed = root / "data/ingredients/mapped/Completely_Renamed.yaml"
    records[renamed] = records.pop(path)
    record["preferred_term"] = "Current corrected label"
    subjects, index = owner_index(root, records)
    rows = read_rows(canonical)
    rows[0]["subject_id"] = old_alias
    objects = NATIVE.compatibility_registry_objects(records, subjects, index, table(rows))
    assert objects[record["mim_id"]] == ("cas:14919-49-4",)


def _cli_cas(stable_cli):
    owner = stable_cli["records"] / "Subject.yaml"
    record = yaml.safe_load(owner.read_bytes())
    record["chemical_properties"] = {"cas_rn": "7732-18-5"}
    owner.write_text(yaml.safe_dump(record))
    canonical = stable_cli["canonical"]
    rows = read_rows(canonical.read_bytes())
    source = next(row for row in rows if row["subject_id"] == "MIM:Subject")
    rows.append({**source, "object_id": "cas:7732-18-5", "object_label": record["preferred_term"],
                 "object_source": "registry:cas", "validation_method": "historical-cas-hold"})
    canonical.write_bytes(table(rows))
    return owner, record, canonical.read_bytes()


def test_1192_cli_preserves_captured_cas_without_stamp_transfer(stable_cli):
    owner, record, original = _cli_cas(stable_cli)
    output, _, manifest = stable_cli["run"]()
    rows = read_rows(output.read_bytes())
    cas = [row for row in rows if row["object_id"] == "cas:7732-18-5"]
    assert len(cas) == 1 and cas[0]["subject_id"] == record["mim_id"]
    assert cas[0]["predicate_id"] == "skos:exactMatch" and cas[0]["validation_method"] == ""
    evidence = json.loads(manifest.read_bytes())
    assert "cas:7732-18-5" in evidence["registry_compatibility_objects"][record["mim_id"]]
    assert stable_cli["canonical"].read_bytes() == original
    assert next(item for item in evidence["source_inputs"] if item["path"] == str(owner))["sha256"] == sha(owner.read_bytes())


def test_1192_unsupported_mapping_does_not_drop_captured_cas(stable_cli):
    owner, record, original = _cli_cas(stable_cli)
    record["ontology_mapping"]["ontology_id"] = "unsupported:term"
    owner.write_text(yaml.safe_dump(record))
    with pytest.raises(ValueError, match="CAS identity has no eligible current mapping"):
        stable_cli["run"]()
    assert stable_cli["canonical"].read_bytes() == original
    assert not stable_cli["output"].exists()
