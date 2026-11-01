"""Finite source-label holds must precede source-ID lookup and publication (#697)."""

import csv
import importlib.util
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_unified_ingredient_mapping.py"
SPEC = importlib.util.spec_from_file_location("unified_source_holds", SCRIPT)
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)

HEADER = "ingredient_name\trejected_id\tmim_id\treason\n"
IDENTITY_METADATA = ("mim_id", "chebi_id", "culturemech_term_id", "cas_rn", "kg_microbe_node_id", "synonyms")


def record(root, slug, identity, label, synonyms=()):
    path = root / "data/ingredients/mapped" / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "identifier": identity, "preferred_term": label, "mapping_status": "MAPPED",
        "ontology_mapping": {"ontology_id": identity, "ontology_label": label, "mapping_quality": "EXACT_MATCH"},
        "chemical_properties": {"cas_rn": "123-45-6"}, "kg_microbe_node_id": identity,
        "synonyms": [{"synonym_text": text, "synonym_type": "EXACT_SYNONYM"} for text in synonyms],
    }))


def ledger(root, rows):
    path = root / b.REJECTIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + rows)
    return path


def build(root, terms):
    indexes = b.load_mim_index(root)
    labels = b.load_mim_label_index(root)
    rejections = b.load_mapping_rejections(root, indexes[0], label_index=labels, live=b.live_records(*indexes))
    occurrences = {name: {"term_id": term, "count": 7, "example_media": ["CM:1", "CM:2"]}
                   for name, term in terms.items()}
    rows = b.build_unified_rows(occurrences, *indexes, rejections, labels)
    return {row["ingredient_name"]: row for row in rows}


@pytest.mark.parametrize("indexed", [True, False])
def test_source_hold_withholds_lookup_and_raw_publication(tmp_path, indexed):
    if indexed:
        record(tmp_path, "Reagent", "CHEBI:9", "Reagent", ("borrowed synonym",))
    ledger(tmp_path, "1 M reagent\tCHEBI:9\t\tReviewed preparation scope\n")
    row = build(tmp_path, {"1 M reagent": "CHEBI:9"})["1 M reagent"]
    assert row["mapping_status"] == "UNMAPPED"
    assert {field: row[field] for field in IDENTITY_METADATA} == dict.fromkeys(IDENTITY_METADATA, "")
    assert row["ingredient_name"] == "1 M reagent"
    assert row["occurrence_count"] == 7
    assert row["example_media"] == "CM:1; CM:2"


def test_distinct_source_holds_sharing_id_do_not_ban_other_labels(tmp_path):
    record(tmp_path, "Reagent", "CHEBI:9", "Reagent", ("valid synonym",))
    ledger(tmp_path, "1 M reagent\tCHEBI:9\t\tPreparation\n2 M reagent\tCHEBI:9\t\tPreparation\n")
    rows = build(tmp_path, dict.fromkeys(("1 M reagent", "2 M reagent", "Reagent"), "CHEBI:9"))
    assert rows["1 M reagent"]["mim_id"] == rows["2 M reagent"]["mim_id"] == ""
    assert rows["Reagent"]["mim_id"] == rows["Reagent"]["culturemech_term_id"] == "CHEBI:9"
    assert rows["Reagent"]["cas_rn"] == "123-45-6"
    assert "valid synonym" in rows["Reagent"]["synonyms"]


def test_empty_identity_does_not_ban_unrelated_source_only_rows(tmp_path):
    ledger(tmp_path, "1 M reagent\tCHEBI:9\t\tPreparation\n")
    rows = build(tmp_path, {"1 M reagent": "CHEBI:9", "Unreviewed label": "CHEBI:9"})
    assert rows["1 M reagent"]["mim_id"] == rows["Unreviewed label"]["mim_id"] == ""
    assert rows["1 M reagent"]["culturemech_term_id"] == ""
    assert rows["Unreviewed label"]["culturemech_term_id"] == "CHEBI:9"


def test_hold_is_specific_to_source_id_not_only_label(tmp_path):
    ledger(tmp_path, "1 M reagent\tCHEBI:9\t\tPreparation\n")
    row = build(tmp_path, {"1 M reagent": "CHEBI:10"})["1 M reagent"]
    assert row["culturemech_term_id"] == row["chebi_id"] == "CHEBI:10"


@pytest.mark.parametrize("owner_kind", ["name", "label_index"])
def test_independent_name_owner_survives_rejected_source(tmp_path, owner_kind):
    record(tmp_path, "Reagent", "CHEBI:9", "Reagent")
    label = "1 M reagent"
    owner_label = label if owner_kind == "name" else "Reviewed preparation"
    record(tmp_path, "Owner", "CHEBI:10", owner_label, ("owned synonym",))
    if owner_kind == "label_index":
        path = tmp_path / "docs/data/label_index.csv"
        path.parent.mkdir(parents=True)
        with path.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["label", "match_type", "identifier", "preferred_term", "ontology_id", "mapping_status", "ambiguity"])
            writer.writerow([label, "synonym", "CHEBI:10", owner_label, "CHEBI:10", "MAPPED", "unique"])
    ledger(tmp_path, f"{label}\tCHEBI:9\t\tReviewed source mismatch\n")
    row = build(tmp_path, {label: "CHEBI:9"})[label]
    assert row["mim_id"] == row["chebi_id"] == row["kg_microbe_node_id"] == "CHEBI:10"
    assert row["culturemech_term_id"] == ""
    assert row["cas_rn"] == "123-45-6" and "owned synonym" in row["synonyms"]


@pytest.mark.parametrize("field", ["mim_id", "chebi_id", "kg_microbe_node_id"])
def test_source_hold_cannot_reject_independent_owners_published_id(tmp_path, field):
    owner = {"mim_id": "CHEBI:10", "chebi_id": "CHEBI:10", "kg_microbe_node_id": "CHEBI:10",
             "mapping_status": "MAPPED"}
    owner[field] = "CHEBI:9"
    ledger(tmp_path, "1 M reagent\tCHEBI:9\t\tContradiction\n")
    with pytest.raises(ValueError, match="MIM still publishes the rejected ID"):
        b.load_mapping_rejections(tmp_path, {b._normalize("1 M reagent"): owner})


def test_source_hold_uses_nfc_casefold_and_outer_trim(tmp_path):
    ledger(tmp_path, "re\u0301agent (1 M)\tCHEBI:9\t\tPreparation\n")
    row = build(tmp_path, {"  RÉAGENT (1 m)  ": "CHEBI:9"})["  RÉAGENT (1 m)  "]
    assert row["culturemech_term_id"] == ""


@pytest.mark.parametrize("held,other", [
    ("1 M reagent", "2 M reagent"), ("Reagent·H2O", "Reagent"),
    ("D-Reagent", "L-Reagent"), ("Reagent (stock)", "Reagent"),
    ("Reagent x H2O", "Reagent·H2O"), ("1 M reagent", "1  M reagent"),
])
def test_source_hold_does_not_normalize_away_qualifiers(tmp_path, held, other):
    ledger(tmp_path, f"{held}\tCHEBI:9\t\tScoped hold\n")
    row = build(tmp_path, {other: "CHEBI:9"})[other]
    assert row["culturemech_term_id"] == "CHEBI:9"


@pytest.mark.parametrize("rows", [
    "Name\tCHEBI:9\t\n", "Name\tCHEBI:9\tReason\n", "Name\tCHEBI:9\n",
    "\tCHEBI:9\t\tReason\n", "Name\t\t\tReason\n", "Name\tCHEBI:9\t\t \n",
    "Name\tCHEBI:9\t\tReason\textra\n", "Name\tCHEBI\t\tReason\n",
    "Name\tCHEBI:\t\tReason\n", "Name\t:9\t\tReason\n", "Name\tCHEBI:9 10\t\tReason\n",
    "Name\tCHEBI:9\t\tReason\n name \tCHEBI:9\t\tOther reason\n",
])
def test_source_hold_malformed_rows_fail_closed(tmp_path, rows):
    ledger(tmp_path, rows)
    with pytest.raises(ValueError):
        b.load_mapping_rejections(tmp_path, {})


def test_ledger_extra_column_is_not_a_blank_replacement(tmp_path):
    path = ledger(tmp_path, "Name\tCHEBI:9\t\tReason\tvalue\n")
    path.write_text(path.read_text().replace("reason\n", "reason\textra\n"))
    with pytest.raises(ValueError, match="expected columns"):
        b.load_mapping_rejections(tmp_path, {})


def test_identity_scoped_and_source_label_rules_coexist(tmp_path):
    record(tmp_path, "Owner", "CHEBI:10", "Reviewed reagent", ("Owned alias",))
    record(tmp_path, "Reagent", "CHEBI:9", "Reagent")
    ledger(tmp_path, "Reviewed reagent\tCHEBI:9\tCHEBI:10\tIdentity correction\n"
           "1 M reagent\tCHEBI:9\t\tPreparation scope\n")
    rows = build(tmp_path, dict.fromkeys(("Owned alias", "1 M reagent", "Reagent"), "CHEBI:9"))
    assert rows["Owned alias"]["mim_id"] == "CHEBI:10"
    assert rows["Owned alias"]["culturemech_term_id"] == ""
    assert rows["1 M reagent"]["mim_id"] == rows["1 M reagent"]["culturemech_term_id"] == ""
    assert rows["Reagent"]["mim_id"] == "CHEBI:9"
