"""Real stable producer regressions for independently reviewed extra claims."""

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_mim_owned_name_export import builder, read_rows, sssom_artifacts
from test_mim_owned_name_export import cli as cli  # noqa: F401
from test_mim_stable_identity import stable_cli as stable_cli  # noqa: F401

NATIVE = Path(__file__).parent / "resources/additional_mim_mappings/native_contract.py.txt"
CONTRACT = builder._STABLE_PRODUCER.additional_mapping_contract(NATIVE.read_bytes(), NATIVE)
NATIVE_SSSOM_VALIDATE = builder._sssom_validate


def assertion(subject="MIM:0000002", *, status="SUPPORTED"):
    return {
        "subject_id": subject, "ontology_id": "mesh:D123456", "ontology_label": "Synthetic broader concept",
        "ontology_source": "MESH", "predicate_id": "skos:broadMatch", "review_status": status,
        "reviewed_by": "independent-synthetic-reviewer", "reviewed_at": "2026-11-14T12:00:00Z",
        "review_note": "Synthetic independently reviewed relation, not scientific approval",
        "llm_assisted": True, "mapping_justification": "semapv:ManualMappingCuration",
        "evidence": [{"evidence_type": "DATABASE_MATCH", "source": "extra-database",
                      "supports": "SUPPORT", "explanation": "Evidence for precisely this relation"}],
    }


def owner():
    return {
        "mim_id": "MIM:0000002", "identifier": "mesh:M1234567", "preferred_term": "Synthetic material",
        "mapping_status": "MAPPED", "legacy_identifiers": ["MIM:Historical_name"],
        "ontology_mapping": {"ontology_id": "mesh:M1234567", "ontology_label": "Synthetic material",
                             "ontology_source": "MESH", "mapping_quality": "EXACT_MATCH",
                             "evidence": [{"evidence_type": "DATABASE_MATCH", "source": "primary-database"}]},
        "additional_ontology_mappings": [assertion()],
        "curation_history": [{"timestamp": "2026-11-13T00:00:00Z", "curator": "primary-curator"}],
        "synonyms": [{"synonym_text": "Rejected name", "synonym_type": "REJECTED_LABEL"}],
        "notes": "Unchanged source and role holds",
    }


def emit(record, **kwargs):
    return builder._row_from_yaml(Path("Owner.yaml"), {}, {}, {}, {}, record=record, owners={},
                                  stable_subject=record["mim_id"], additional_contract=CONTRACT, **kwargs)


def test_native_contract_fixture_is_bound():
    provenance = json.loads(NATIVE.with_name("ORIGIN.json").read_bytes())
    assert hashlib.sha256(NATIVE.read_bytes()).hexdigest() == provenance["sha256"]
    assert provenance["scope"] == "Pure native MIM assertion contract; no scientific data or approval"


def test_exact_primary_and_broad_extra_have_independent_provenance_and_identity():
    record = owner()
    before = deepcopy(record)
    rows = emit(record)
    assert [(row["subject_id"], row["predicate_id"], row["object_id"]) for row in rows] == [
        ("MIM:0000002", "skos:exactMatch", "mesh:M1234567"),
        ("MIM:0000002", "skos:broadMatch", "mesh:D123456"),
    ]
    primary, extra = rows
    assert "primary-database" in primary["source"] and "extra-database" not in primary["source"]
    assert extra["source"] == "MIM:extra-database|MIM:curator=independent-synthetic-reviewer"
    assert extra["mapping_date"] == "2026-11-14" and extra["confidence"] == ""
    assert json.loads(extra["comment"].removeprefix(CONTRACT.MARKER)) == assertion()
    assert extra["other"] == extra["validation_method"] == ""
    assert all("Rejected name" not in row["other"] for row in rows)
    assert record == before  # aliases, source/role holds, history never change


@pytest.mark.parametrize("quality,predicate", [("EXACT_MATCH", "skos:exactMatch"),
                                              ("CLOSE_MATCH", "skos:closeMatch")])
def test_existing_one_grounding_and_close_only_remain_valid(quality, predicate):
    record = owner()
    record.pop("additional_ontology_mappings")
    record["ontology_mapping"]["mapping_quality"] = quality
    if quality == "CLOSE_MATCH":
        record["identifier"] = "mesh:M7654321"
    rows = emit(record)
    assert len(rows) == 1 and rows[0]["predicate_id"] == predicate


@pytest.mark.parametrize("status", ["UNMAPPED", "AMBIGUOUS", "REJECTED"])
def test_mim_only_owner_stays_without_external_assertions(status):
    record = owner()
    record.pop("additional_ontology_mappings")
    record["mapping_status"] = status
    record.pop("ontology_mapping")
    record["identifier"] = "UNMAPPED_1234"
    assert emit(record) == []


def test_withheld_proposal_preserves_disposition_and_never_inherits_support():
    record = owner()
    item = record["additional_ontology_mappings"][0]
    item["review_status"] = "WITHHOLD"
    item["evidence"][0]["supports"] = "REFUTE"
    row = emit(record)[1]
    assert json.loads(row["comment"].removeprefix(CONTRACT.MARKER))["review_status"] == "WITHHOLD"
    assert row["validation_method"] == row["confidence"] == row["other"] == ""


@pytest.mark.parametrize("field,value", [
    ("subject_id", "MIM:0000001"), ("ontology_id", "mesh:M1234567"),
    ("predicate_id", "biolink:subclass_of"), ("review_status", "UNKNOWN"),
    ("evidence", []), ("ontology_source", "CHEBI"), ("reviewed_by", ""),
])
def test_owner_target_predicate_evidence_conflicts_refuse(field, value):
    record = owner()
    record["additional_ontology_mappings"][0][field] = value
    with pytest.raises(ValueError, match="Additional ontology mapping"):
        emit(record)


def test_unsupported_or_contradicted_evidence_cannot_create_supported_row():
    record = owner()
    record["additional_ontology_mappings"][0]["evidence"][0]["supports"] = "REFUTE"
    with pytest.raises(ValueError, match="uncontradicted"):
        emit(record)


def test_legacy_or_missing_contract_never_silently_drops_extra():
    record = owner()
    for stable_subject in (None, record["mim_id"]):
        with pytest.raises(ValueError, match="captured native contract"):
            builder._row_from_yaml(Path("Owner.yaml"), {}, {}, {}, {}, record=record,
                                   owners={}, stable_subject=stable_subject)


def test_empty_additional_list_keeps_legacy_one_grounding():
    record = owner()
    record["additional_ontology_mappings"] = []
    rows = builder._row_from_yaml(Path("Owner.yaml"), {}, {}, {}, {}, record=record, owners={})
    assert len(rows) == 1 and rows[0]["object_id"] == record["identifier"]


def install(stable_cli):
    path = stable_cli["records"] / "Subject.yaml"
    record = yaml.safe_load(path.read_bytes())
    record["ontology_mapping"]["evidence"] = [{"source": "primary-database"}]
    record["additional_ontology_mappings"] = [assertion(record["mim_id"])]
    path.write_text(yaml.safe_dump(record))
    source = stable_cli["root"] / "src/mediaingredientmech/additional_mappings.py"
    source.write_bytes(NATIVE.read_bytes())
    return source, path


def test_native_candidate_cli_binds_new_contract_and_independent_extra(stable_cli):
    contract, owner_path = install(stable_cli)
    before = owner_path.read_bytes()
    output, _, manifest = stable_cli["run"]()
    rows = read_rows(output.read_bytes())
    assert len(rows) == 2
    extra = next(row for row in rows if row["object_id"] == "mesh:D123456")
    assert extra["subject_id"] == "MIM:0000002" and extra["predicate_id"] == "skos:broadMatch"
    assert extra["other"] == "" and "primary-database" not in extra["source"]
    assert owner_path.read_bytes() == before
    proof = json.loads(manifest.read_bytes())
    inputs = {entry["path"]: entry["sha256"] for entry in proof["source_inputs"]}
    assert inputs[str(contract)] == hashlib.sha256(NATIVE.read_bytes()).hexdigest()
    assert inputs[str(owner_path)] == hashlib.sha256(before).hexdigest()
    assert proof["validation_replay"].startswith("disabled")
    assert b"/ingredient/MIM_" in output.read_bytes()


def test_candidate_passes_real_sssom_schema_without_ontology_services(stable_cli, monkeypatch):
    install(stable_cli)
    monkeypatch.setattr(builder, "_sssom_validate", NATIVE_SSSOM_VALIDATE)
    monkeypatch.setattr(builder, "SSSOM_BIN", str(Path(sys.executable).parent / "sssom"))
    output, _, manifest = stable_cli["run"]()
    assert len(read_rows(output.read_bytes())) == 2
    assert json.loads(manifest.read_bytes())["external_sssom_validation"] == "passed"


@pytest.mark.parametrize("change", ["contract", "owner", "evidence", "status"])
def test_native_precommit_refuses_new_contract_or_assertion_drift(stable_cli, monkeypatch, change):
    contract, owner_path = install(stable_cli)
    paths = stable_cli["run"]()
    originals = [p.read_bytes() for p in paths]
    native = sssom_artifacts.ValidatedWriteTransaction

    class Drift(native):
        def commit(self, **kwargs):
            path = contract if change == "contract" else owner_path
            if change in {"evidence", "status"}:
                record = yaml.safe_load(path.read_bytes())
                item = record["additional_ontology_mappings"][0]
                if change == "evidence":
                    item["evidence"][0]["explanation"] = "Changed after capture"
                else:
                    item["review_status"] = "WITHHOLD"
                path.write_text(yaml.safe_dump(record))
            else:
                path.write_bytes(path.read_bytes() + b"\n# changed after capture\n")
            return super().commit(**kwargs)

    monkeypatch.setattr(sssom_artifacts, "ValidatedWriteTransaction", Drift)
    with pytest.raises(builder._load_producer("kg_microbe_write.transaction").ValidationFailed,
                       match="changed during generation"):
        stable_cli["run"]()
    assert [p.read_bytes() for p in paths] == originals
