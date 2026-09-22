"""Adversarial cases for retired records and ontology parent lookups."""

import importlib.util
from pathlib import Path

import pytest
import yaml

_SPEC = importlib.util.spec_from_file_location(
    "review_unified_builder",
    Path(__file__).resolve().parents[1] / "scripts/build_unified_ingredient_mapping.py",
)
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


def _record(root, filename, identifier, preferred, status="MAPPED", **extra):
    category = "unmapped" if status in {"UNMAPPED", "AMBIGUOUS"} else "mapped"
    path = root / "data" / "ingredients" / category / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "identifier": identifier,
                "preferred_term": preferred,
                "mapping_status": status,
                **extra,
            }
        ),
        encoding="utf-8",
    )


def _row(root, name, source_id=""):
    names, chebi, ontology = builder.load_mim_index(root)
    return builder.build_unified_rows(
        {name: {"term_id": source_id, "count": 1, "example_media": []}},
        names,
        chebi,
        ontology,
    )[0]


@pytest.mark.parametrize("status", ["UNMAPPED", "AMBIGUOUS"])
def test_explicit_nonidentity_beats_a_conflicting_active_preferred_label(
    tmp_path, status
):
    _record(tmp_path, "A.yaml", "CHEBI:10", "ambiguous preparation")
    _record(tmp_path, "Z.yaml", "UNMAPPED_1", "ambiguous preparation", status)
    row = _row(tmp_path, "ambiguous preparation", "CHEBI:10")
    assert row["mapping_status"] == status
    assert row["chebi_id"] == row["culturemech_term_id"] == ""
    assert row["kg_microbe_node_id"] == row["cas_rn"] == ""


@pytest.mark.parametrize("conflicting_live_record", [False, True])
def test_retired_primary_id_cannot_survive_or_hijack_a_resolved_alias(
    tmp_path,
    conflicting_live_record,
):
    _record(
        tmp_path,
        "Nano.yaml",
        "NCIT:C54713",
        "NaNO",
        "REJECTED",
        representative="CHEBI:63005",
    )
    _record(tmp_path, "Nano3.yaml", "CHEBI:63005", "sodium nitrate")
    if conflicting_live_record:
        _record(tmp_path, "Prefix.yaml", "NCIT:C54713", "nano prefix")
    indexes = builder.load_mim_index(tmp_path)
    assert builder.resolve_mim_record("NaNO", "NCIT:C54713", *indexes) is indexes[0]["nano"]
    row = _row(tmp_path, "NaNO", "NCIT:C54713")
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:63005"
    assert row["mapping_status"] == "MAPPED"
    assert row["culturemech_term_id"] == ""


def test_chain_of_retired_aliases_suppresses_the_source_primary(tmp_path):
    _record(
        tmp_path,
        "A.yaml",
        "NCIT:old",
        "old label",
        "REJECTED",
        representative="OTHER:intermediate",
    )
    _record(
        tmp_path,
        "B.yaml",
        "OTHER:intermediate",
        "middle label",
        "REJECTED",
        representative="CHEBI:63005",
    )
    _record(tmp_path, "C.yaml", "CHEBI:63005", "sodium nitrate")
    row = _row(tmp_path, "old label", "NCIT:old")
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:63005"
    assert row["culturemech_term_id"] == ""


@pytest.mark.parametrize("quality", ["NARROW_MATCH", "CLOSE_MATCH", "BROAD_MATCH"])
def test_ontology_parent_cannot_select_a_different_preparation(tmp_path, quality):
    parent = {
        "ontology_id": "NCIT:C29321",
        "ontology_label": "phosphate buffer",
        "mapping_quality": quality,
    }
    _record(
        tmp_path,
        "A.yaml",
        "kgmicrobe.ingredient:potassium_buffer",
        "potassium phosphate buffer",
        ontology_mapping=parent,
    )
    _record(
        tmp_path,
        "Z.yaml",
        "kgmicrobe.ingredient:sodium_buffer",
        "sodium phosphate buffer",
        ontology_mapping=parent,
    )
    row = _row(tmp_path, "sodium phosphate buffer", "NCIT:C29321")
    assert row["mim_id"] == "kgmicrobe.ingredient:sodium_buffer"
    assert "phosphate buffer" not in row["synonyms"].split("|")
    assert (
        builder.resolve_mim_record(
            "potassium phosphate buffer",
            "kgmicrobe.ingredient:potassium_buffer",
            *builder.load_mim_index(tmp_path),
        )["mim_id"]
        == "kgmicrobe.ingredient:potassium_buffer"
    )


@pytest.mark.parametrize(
    "quality", ["EXACT_MATCH", "SYNONYM_MATCH", "LEXICAL_MATCH", ""]
)
def test_exact_ontology_alias_still_resolves_without_a_name_match(tmp_path, quality):
    _record(
        tmp_path,
        "Record.yaml",
        "cas:123-45-6",
        "a curated compound",
        ontology_mapping={
            "ontology_id": "CHEBI:123",
            "ontology_label": "compound",
            "mapping_quality": quality,
        },
    )
    names, chebi, ontology = builder.load_mim_index(tmp_path)
    record = builder.resolve_mim_record(
        "unknown source label", "CHEBI:123", names, chebi, ontology
    )
    assert record["mim_id"] == "cas:123-45-6"
    assert "compound" in record["synonyms"]


def test_retirement_applies_to_each_active_label_sharing_the_target_id(tmp_path):
    _record(tmp_path, "A.yaml", "CHEBI:63005", "NaNO3")
    _record(tmp_path, "B.yaml", "CHEBI:63005", "sodium nitrate")
    _record(
        tmp_path,
        "Old.yaml",
        "NCIT:C54713",
        "NaNO",
        "REJECTED",
        representative="CHEBI:63005",
    )
    _record(tmp_path, "Prefix.yaml", "NCIT:C54713", "nano prefix")
    row = _row(tmp_path, "sodium nitrate", "NCIT:C54713")
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:63005"
    assert row["culturemech_term_id"] == ""
    actual_prefix = _row(tmp_path, "nano prefix", "NCIT:C54713")
    assert (
        actual_prefix["mim_id"] == actual_prefix["culturemech_term_id"] == "NCIT:C54713"
    )
