"""The unified index uses live MIM records and preserves curated nonidentities."""

import importlib.util
from pathlib import Path

import pytest
import yaml

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_unified_ingredient_mapping.py"
_SPEC = importlib.util.spec_from_file_location("unified_mim_index_builder", _SCRIPT)
b = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(b)


def _write(root, filename, identifier, preferred, status="MAPPED", **extra):
    path = root / "data/ingredients" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "identifier": identifier,
        "preferred_term": preferred,
        "mapping_status": status,
        **extra,
    }))


@pytest.mark.parametrize("excluded_path", [
    "mapped/backups/Backup.yaml",
    "unmapped/backups/Backup.yaml",
    "archive/Backup.yaml",
    "Loose.yaml",
])
def test_only_direct_mapped_and_unmapped_records_are_loaded(tmp_path, excluded_path):
    _write(tmp_path, "mapped/Live.yaml", "CHEBI:1", "live ingredient")
    _write(tmp_path, "unmapped/Unknown.yaml", "UNMAPPED_1", "unknown ingredient", "UNMAPPED")
    _write(tmp_path, excluded_path, "CHEBI:2", "backup ingredient")

    names, chebi, ontology = b.load_mim_index(tmp_path)

    assert set(names) == {"live ingredient", "unknown ingredient"}
    assert names["unknown ingredient"]["mapping_status"] == "UNMAPPED"
    assert set(chebi) == {"CHEBI:1"}
    assert "CHEBI:2" not in ontology


@pytest.mark.parametrize("retired_filename", ["Nano.yaml", "Z_Nano.yaml"])
@pytest.mark.parametrize("aliases_copied_to_winner", [False, True])
def test_retired_labels_resolve_to_the_active_representative(
    tmp_path, retired_filename, aliases_copied_to_winner,
):
    aliases = ["NaNO", "NaNO3(CAS: 7631-99-4)"]
    _write(
        tmp_path, f"mapped/{retired_filename}", "NCIT:C54713", aliases[0], "REJECTED",
        representative="CHEBI:63005",
        ontology_mapping={"ontology_id": "NCIT:C54713", "ontology_label": "Nano"},
        kg_microbe_node_id="NCIT:C54713",
        synonyms=[aliases[1]],
    )
    _write(
        tmp_path, "mapped/Nano3.yaml", "CHEBI:63005", "NaNO3",
        ontology_mapping={"ontology_id": "CHEBI:63005", "ontology_label": "sodium nitrate"},
        kg_microbe_node_id="CHEBI:63005",
        chemical_properties={"cas_rn": "7631-99-4"},
        synonyms=aliases if aliases_copied_to_winner else [],
    )

    indexes = b.load_mim_index(tmp_path)
    names, chebi, ontology = indexes
    active = names[b._normalize("NaNO3")]
    for alias in aliases:
        assert names[b._normalize(alias)] is active
        assert b.resolve_mim_record(alias, "NCIT:C54713", *indexes) is active
    assert chebi["CHEBI:63005"] is active
    assert ontology["CHEBI:63005"] is active
    assert "NCIT:C54713" not in ontology
    assert all(r["mapping_status"] != "REJECTED" for index in indexes for r in index.values())
    row = b.build_unified_rows(
        {aliases[0]: {"term_id": "NCIT:C54713", "count": 1, "example_media": []}},
        *indexes,
    )[0]
    assert row["mim_id"] == row["chebi_id"] == row["kg_microbe_node_id"] == "CHEBI:63005"
    assert row["cas_rn"] == "7631-99-4"
    assert row["mapping_status"] == "MAPPED"


def test_legacy_merge_uses_the_live_identifier_without_reviving_rejected_labels(tmp_path):
    _write(
        tmp_path, "mapped/A_Retired.yaml", "CHEBI:1", "legacy label", "REJECTED",
        curation_history=[{"action": "MERGED_INTO", "new_status": "REJECTED"}],
        ontology_mapping={"ontology_id": "CHEBI:99", "ontology_label": "stale ontology label"},
        synonyms=[
            "legacy synonym", "withdrawn alias", "Role: Carbon source",
            {"synonym_text": "locally rejected", "synonym_type": "REJECTED_LABEL"},
        ],
    )
    _write(
        tmp_path, "mapped/Z_Active.yaml", "CHEBI:1", "active ingredient",
        synonyms=[{"synonym_text": "withdrawn alias", "synonym_type": "REJECTED_LABEL"}],
    )

    names, chebi, ontology = b.load_mim_index(tmp_path)

    for alias in ("legacy label", "legacy synonym"):
        assert names[alias] is chebi["CHEBI:1"]
        assert names[alias]["mapping_status"] == "MAPPED"
    assert "CHEBI:99" not in ontology
    for excluded in ("withdrawn alias", "locally rejected", "role: carbon source", "stale ontology label"):
        assert excluded not in names
        assert excluded not in chebi["CHEBI:1"]["synonyms"]


def test_explicit_representative_takes_precedence_over_the_retired_identifier(tmp_path):
    _write(tmp_path, "mapped/A_Retired.yaml", "CHEBI:1", "retired", "REJECTED",
           representative="CHEBI:2")
    _write(tmp_path, "mapped/B_Other.yaml", "CHEBI:1", "old identity")
    _write(tmp_path, "mapped/C_Active.yaml", "CHEBI:2", "correct identity")

    names, _, _ = b.load_mim_index(tmp_path)

    assert names["retired"] is names["correct identity"]


def test_merge_chain_resolves_to_a_live_record(tmp_path):
    _write(tmp_path, "mapped/A.yaml", "CHEBI:1", "first alias", "REJECTED",
           representative="CHEBI:2")
    _write(tmp_path, "mapped/B.yaml", "CHEBI:2", "second alias", "REJECTED",
           representative="CHEBI:3")
    _write(tmp_path, "mapped/C.yaml", "CHEBI:3", "active ingredient")

    names, chebi, ontology = b.load_mim_index(tmp_path)

    assert names["first alias"] is names["second alias"] is names["active ingredient"]
    assert set(chebi) == set(ontology) == {"CHEBI:3"}


@pytest.mark.parametrize("representative", [None, "CHEBI:1", "CHEBI:missing"])
def test_retired_records_without_a_live_target_do_not_supply_identities(tmp_path, representative):
    _write(tmp_path, "mapped/Retired.yaml", "CHEBI:1", "retired ingredient", "REJECTED",
           representative=representative)

    names, chebi, ontology = b.load_mim_index(tmp_path)

    assert chebi == ontology == {}
    assert names["retired ingredient"]["mapping_status"] == "REJECTED"
    assert names["retired ingredient"]["mim_id"] == ""


@pytest.mark.parametrize("status", ["AMBIGUOUS", "UNMAPPED"])
@pytest.mark.parametrize("identifier", ["UNMAPPED_1", "CHEBI:99"])
def test_explicit_nonidentity_survives_alias_and_source_id_matches(tmp_path, status, identifier):
    _write(
        tmp_path, "mapped/Specific.yaml", "CHEBI:1", "specific chemical",
        synonyms=["uncertain ingredient", "uncertain alias"],
    )
    _write(
        tmp_path, "unmapped/Uncertain.yaml", identifier, "uncertain ingredient", status,
        ontology_mapping={"ontology_id": "CHEBI:2", "ontology_label": "parent class"},
        kg_microbe_node_id="CHEBI:2",
        chemical_properties={"cas_rn": "123-45-6"},
        synonyms=["uncertain alias"],
    )

    indexes = b.load_mim_index(tmp_path)
    names, chebi, ontology = indexes
    for label in ("uncertain ingredient", "uncertain alias"):
        record = names[label]
        assert record["mapping_status"] == status
        assert b.resolve_mim_record(label, "CHEBI:1", *indexes) is record
        row = b.build_unified_rows(
            {label: {"term_id": "CHEBI:1", "count": 1, "example_media": []}}, *indexes,
        )[0]
        assert row["mapping_status"] == status
        assert row["chebi_id"] == row["culturemech_term_id"] == ""
        assert row["kg_microbe_node_id"] == row["cas_rn"] == ""
        assert row["mim_id"] == (identifier if identifier.startswith("UNMAPPED") else "")
        assert "parent class" not in record["synonyms"]
    assert set(chebi) == set(ontology) == {"CHEBI:1"}


def test_a_merged_label_can_resolve_to_an_unmapped_representative(tmp_path):
    _write(tmp_path, "mapped/Retired.yaml", "CHEBI:1", "old label", "REJECTED",
           representative="UNMAPPED_1")
    _write(tmp_path, "unmapped/Active.yaml", "UNMAPPED_1", "unresolved label", "AMBIGUOUS")

    names, chebi, ontology = b.load_mim_index(tmp_path)

    assert names["old label"] is names["unresolved label"]
    assert names["old label"]["mapping_status"] == "AMBIGUOUS"
    assert chebi == ontology == {}


def test_exported_synonyms_do_not_restore_a_curated_nonidentity(tmp_path):
    _write(tmp_path, "mapped/Specific.yaml", "CHEBI:1", "specific chemical",
           synonyms=["uncertain ingredient", "accepted alias"])
    _write(tmp_path, "unmapped/Uncertain.yaml", "UNMAPPED_1", "uncertain ingredient", "AMBIGUOUS")

    indexes = b.load_mim_index(tmp_path)
    row = b.build_unified_rows(
        {"specific chemical": {"term_id": "CHEBI:1", "count": 1, "example_media": []}},
        *indexes,
    )[0]

    assert row["synonyms"] == "accepted alias"


def test_exported_synonyms_honor_normalized_label_rejections(tmp_path):
    _write(
        tmp_path, "mapped/Active.yaml", "CHEBI:1", "active ingredient",
        synonyms=[
            "WITHDRAWN   ALIAS", "accepted alias",
            {"synonym_text": "withdrawn alias", "synonym_type": "REJECTED_LABEL"},
        ],
    )

    indexes = b.load_mim_index(tmp_path)
    row = b.build_unified_rows(
        {"active ingredient": {"term_id": "CHEBI:1", "count": 1, "example_media": []}},
        *indexes,
    )[0]

    assert "withdrawn alias" not in indexes[0]
    assert row["synonyms"] == "accepted alias"


def test_an_orphaned_merge_cannot_republish_its_source_id(tmp_path):
    _write(tmp_path, "mapped/Retired.yaml", "CHEBI:1", "retired label", "REJECTED",
           representative="CHEBI:missing")

    indexes = b.load_mim_index(tmp_path)
    row = b.build_unified_rows(
        {"retired label": {"term_id": "CHEBI:1", "count": 1, "example_media": []}},
        *indexes,
    )[0]

    assert row["mapping_status"] == "REJECTED"
    for column in ("mim_id", "chebi_id", "culturemech_term_id", "cas_rn", "kg_microbe_node_id"):
        assert row[column] == ""


@pytest.mark.parametrize("prior_merge", [False, True])
def test_a_rejection_without_merge_evidence_cannot_claim_a_live_identity(tmp_path, prior_merge):
    history = [{"action": "MERGED_INTO", "new_status": "REJECTED"}] if prior_merge else []
    history.append({"action": "REJECTED", "new_status": "REJECTED"})
    _write(tmp_path, "mapped/Invalid.yaml", "CHEBI:1", "invalid ingredient", "REJECTED",
           curation_history=history)
    _write(tmp_path, "mapped/Valid.yaml", "CHEBI:1", "valid ingredient")

    indexes = b.load_mim_index(tmp_path)
    row = b.build_unified_rows(
        {"invalid ingredient": {"term_id": "CHEBI:1", "count": 1, "example_media": []}},
        *indexes,
    )[0]

    assert indexes[1]["CHEBI:1"]["preferred_term"] == "valid ingredient"
    assert row["mapping_status"] == "REJECTED"
    assert row["mim_id"] == row["chebi_id"] == row["culturemech_term_id"] == ""


@pytest.mark.parametrize("targets", [["CHEBI:1"], ["CHEBI:3", "CHEBI:4"]])
def test_cyclic_or_conflicting_merge_chains_refuse_identity_fallback(tmp_path, targets):
    _write(tmp_path, "mapped/A.yaml", "CHEBI:1", "old label", "REJECTED",
           representative="CHEBI:2")
    for number, target in enumerate(targets):
        _write(tmp_path, f"mapped/B{number}.yaml", "CHEBI:2", f"intermediate {number}",
               "REJECTED", representative=target)
    _write(tmp_path, "mapped/C.yaml", "CHEBI:3", "first live ingredient")
    _write(tmp_path, "mapped/D.yaml", "CHEBI:4", "second live ingredient")

    indexes = b.load_mim_index(tmp_path)
    row = b.build_unified_rows(
        {"old label": {"term_id": "CHEBI:3", "count": 1, "example_media": []}},
        *indexes,
    )[0]

    assert row["mapping_status"] == "REJECTED"
    assert row["mim_id"] == row["chebi_id"] == row["culturemech_term_id"] == ""
