"""MIM's published label-index answer outranks a recipe's stale term.id (MIM #808)."""

import csv
import importlib.util
from pathlib import Path

import pytest
import yaml

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_unified_ingredient_mapping.py"
_SPEC = importlib.util.spec_from_file_location("unified_label_index_builder", _SCRIPT)
b = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(b)

HEADER = ["label", "match_type", "identifier", "preferred_term", "ontology_id",
          "mapping_status", "ambiguity"]


def _write(root, filename, identifier, preferred, status="MAPPED", **extra):
    path = root / "data/ingredients" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "identifier": identifier, "preferred_term": preferred, "mapping_status": status, **extra,
    }))


def _label_index(root, rows):
    path = root / "docs/data/label_index.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)


@pytest.fixture
def mim(tmp_path):
    _write(tmp_path, "mapped/K2hpo4.yaml", "CHEBI:131527", "K2HPO4",
           ontology_mapping={"ontology_id": "CHEBI:131527", "ontology_label": "dipotassium phosphate"})
    _write(tmp_path, "mapped/K2hpo4_X_3_H2o.yaml", "kgmicrobe.compound:k2hpo4_x_3_h2o",
           "K2HPO4 x 3 H2O",
           ontology_mapping={"ontology_id": "CHEBI:131527", "mapping_quality": "BROAD_MATCH"})
    return tmp_path


def _rows(root, name, term_id):
    indexes = b.load_mim_index(root)
    return b.build_unified_rows(
        {name: {"term_id": term_id, "count": 3, "example_media": []}},
        *indexes, None, b.load_mim_label_index(root),
    )[0]


def test_safe_label_answer_beats_a_stale_recipe_term_id(mim):
    _label_index(mim, [["K2HPO4 x 3H2O", "synonym", "kgmicrobe.compound:k2hpo4_x_3_h2o",
                        "K2HPO4 x 3 H2O", "CHEBI:131527", "MAPPED", "unique"]])
    row = _rows(mim, "K2HPO4 x 3H2O", "CHEBI:131527")
    assert row["mim_id"] == "kgmicrobe.compound:k2hpo4_x_3_h2o"


@pytest.mark.parametrize("ambiguity", [
    "conflict:different_substances", "unresolved:partial_chemistry", "unresolved:no_chemistry",
])
def test_unsafe_label_answer_falls_back_to_the_term_id(mim, ambiguity):
    _label_index(mim, [["K2HPO4 x 3H2O", "synonym", "kgmicrobe.compound:k2hpo4_x_3_h2o",
                        "K2HPO4 x 3 H2O", "CHEBI:131527", "MAPPED", ambiguity]])
    assert _rows(mim, "K2HPO4 x 3H2O", "CHEBI:131527")["mim_id"] == "CHEBI:131527"


def test_label_answer_naming_no_live_record_is_ignored(mim):
    _label_index(mim, [["K2HPO4 x 3H2O", "synonym", "CHEBI:999999", "Gone", "CHEBI:999999",
                        "REJECTED", "unique"],
                       ["Mystery", "preferred_term", "UNMAPPED_0001", "Mystery", "",
                        "UNMAPPED", "unique"]])
    assert _rows(mim, "K2HPO4 x 3H2O", "CHEBI:131527")["mim_id"] == "CHEBI:131527"
    assert _rows(mim, "Mystery", "CHEBI:131527")["mim_id"] == "CHEBI:131527"


def test_without_a_label_index_resolution_is_unchanged(mim):
    assert _rows(mim, "K2HPO4 x 3H2O", "CHEBI:131527")["mim_id"] == "CHEBI:131527"


def test_label_keys_are_exact_up_to_case_and_unicode_normalization(mim):
    _label_index(mim, [["K2HPO4 x 3H2O", "synonym", "kgmicrobe.compound:k2hpo4_x_3_h2o",
                        "K2HPO4 x 3 H2O", "CHEBI:131527", "MAPPED", "unique"]])
    assert _rows(mim, "  k2hpo4 X 3h2o ", "CHEBI:131527")["mim_id"] == (
        "kgmicrobe.compound:k2hpo4_x_3_h2o")
    # A different spelling is not the same label; no weak matching.
    assert _rows(mim, "K2HPO4·3H2O", "CHEBI:131527")["mim_id"] == "CHEBI:131527"


# --- review round (claw#571) -------------------------------------------------


def _rec(mim_id, preferred, status="MAPPED", cas="", node=None):
    return {
        "mim_id": mim_id, "preferred_term": preferred,
        "chebi_id": mim_id if mim_id.startswith("CHEBI:") and status == "MAPPED" else "",
        "cas_rn": cas, "kg_microbe_node_id": node if node is not None else mim_id,
        "mapping_status": status, "synonyms": [],
    }


def _row(label, identifier, preferred, status="MAPPED", ambiguity="unique", match="synonym"):
    return {"label": label, "match_type": match, "identifier": identifier,
            "preferred_term": preferred, "ontology_id": identifier,
            "mapping_status": status, "ambiguity": ambiguity}


def _labels(*rows):
    index = {}
    for row in rows:
        index.setdefault(b._label_key(row["label"]), row)
    return index


def _build(names, chebi, labels, name, term_id, rejections=None):
    return b.build_unified_rows(
        {name: {"term_id": term_id, "count": 1, "example_media": []}},
        names, chebi, dict(chebi), rejections, labels,
    )[0]


def test_agree_same_substance_does_not_outrank_the_recipe_term():
    """Formula agreement cannot tell stereoisomers apart: Histidine stays generic."""
    l_his, his = _rec("CHEBI:15971", "L-Histidine"), _rec("CHEBI:27570", "Histidine (any)")
    names = {"l-histidine": l_his, "histidine": l_his}
    labels = _labels(_row("Histidine", "CHEBI:15971", "L-Histidine", ambiguity="agree:same_substance"))
    row = _build(names, {"CHEBI:15971": l_his, "CHEBI:27570": his}, labels, "Histidine", "CHEBI:27570")
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:27570"


def test_records_sharing_an_identifier_keep_the_one_the_name_denotes():
    """identifier is not unique; CAS and KG node must come from the named record."""
    tryptone = _rec("MICRO:0000182", "Tryptone", cas="91079-40-2", node="MICRO:0000182")
    casamino = _rec("MICRO:0000182", "Casamino acids", cas="65072-00-6", node="CHEBI:78020")
    names = {"casamino acids": casamino, "tryptone": tryptone}  # casamino loads first
    labels = _labels(_row("Tryptone", "MICRO:0000182", "Tryptone", match="preferred_term"),
                     _row("Peptone T", "MICRO:0000182", "Tryptone"))
    named = _build(names, {}, labels, "Tryptone", "MICRO:0000178")
    assert (named["mim_id"], named["cas_rn"]) == ("MICRO:0000182", "91079-40-2")
    # Not in the name index at all: the label row's preferred_term picks the record.
    unnamed = _build(names, {}, labels, "Peptone T", "MICRO:0000178")
    assert (unnamed["cas_rn"], unnamed["kg_microbe_node_id"]) == ("91079-40-2", "MICRO:0000182")


def test_a_rejected_first_row_is_followed_to_its_live_survivor():
    survivor, stale = _rec("CHEBI:2", "New name"), _rec("CHEBI:9", "Stale")
    names = {"new name": survivor}
    labels = _labels(_row("Old name", "CHEBI:2", "Old name", status="REJECTED", match="preferred_term"))
    row = _build(names, {"CHEBI:2": survivor, "CHEBI:9": stale}, labels, "Old name", "CHEBI:9")
    assert row["mim_id"] == "CHEBI:2"


def test_an_explicit_mim_nonidentity_still_beats_the_label_index():
    refusal, live = _rec("UNMAPPED_0009", "Mystery mix", status="UNMAPPED"), _rec("CHEBI:1", "One")
    names = {"mystery mix": refusal, "one": live}
    labels = _labels(_row("Mystery mix", "CHEBI:1", "One"))
    row = _build(names, {"CHEBI:1": live}, labels, "Mystery mix", "CHEBI:1")
    assert row["mim_id"] == "UNMAPPED_0009"
    assert row["chebi_id"] == row["culturemech_term_id"] == ""


def test_rejection_ledger_is_keyed_on_the_same_record_the_builder_resolves(tmp_path):
    """Ledger validation and lookup both follow the label index, so they agree."""
    beta, lactose = _rec("CHEBI:36218", "Beta-Lactose"), _rec("CHEBI:17716", "Lactose")
    names = {"lactose": beta, "milk sugar": lactose}  # name index disagrees with MIM's label ruling
    labels = _labels(_row("Lactose", "CHEBI:17716", "Lactose", match="preferred_term",
                          ambiguity="resolved:owned"))
    live = b.live_records(names)
    path = tmp_path / b.REJECTIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ingredient_name\trejected_id\tmim_id\treason\n"
                    "Lactose\tCHEBI:99999\tCHEBI:17716\tReviewed\n", encoding="utf-8")
    rejected = b.load_mapping_rejections(tmp_path, names, label_index=labels, live=live)
    row = _build(names, {"CHEBI:99999": _rec("CHEBI:99999", "Wrong")}, labels,
                 "Lactose", "CHEBI:99999", rejected)
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:17716"
    assert "CHEBI:99999" not in row.values()
    # A ledger row keyed on the name index's disagreeing record now fails closed.
    path.write_text("ingredient_name\trejected_id\tmim_id\treason\n"
                    "Lactose\tCHEBI:99999\tCHEBI:36218\tReviewed\n", encoding="utf-8")
    with pytest.raises(ValueError):
        b.load_mapping_rejections(tmp_path, names, label_index=labels, live=live)


def test_published_columns_follow_the_existing_policy():
    """A CHEBI ruling replaces chebi_id and withholds the stale same-prefix term;
    a non-CHEBI ruling keeps the recipe's CHEBI term in chebi_id (the separate
    _published_ids rule this PR leaves unchanged)."""
    anhydrous, hexa = _rec("CHEBI:34887", "NiCl2"), _rec("CHEBI:53542", "NiCl2 hexahydrate")
    names = {"nicl2": anhydrous, "nicl2 hexahydrate": hexa}
    labels = _labels(_row("NiCl2 x 6 H2O", "CHEBI:53542", "NiCl2 hexahydrate"),
                     _row("K2HPO4 x 3H2O", "kgmicrobe.compound:k2hpo4_x_3_h2o", "K2HPO4 x 3 H2O"))
    row = _build(names, {"CHEBI:34887": anhydrous}, labels, "NiCl2 x 6 H2O", "CHEBI:34887")
    assert (row["mim_id"], row["chebi_id"], row["culturemech_term_id"]) == ("CHEBI:53542", "CHEBI:53542", "")
    mint = _rec("kgmicrobe.compound:k2hpo4_x_3_h2o", "K2HPO4 x 3 H2O")
    names["k2hpo4 x 3 h2o"] = mint
    row = _build(names, {"CHEBI:131527": _rec("CHEBI:131527", "K2HPO4")}, labels,
                 "K2HPO4 x 3H2O", "CHEBI:131527")
    assert row["mim_id"] == "kgmicrobe.compound:k2hpo4_x_3_h2o"
    assert row["chebi_id"] == row["culturemech_term_id"] == "CHEBI:131527"


def test_a_label_index_missing_required_columns_fails(tmp_path):
    path = tmp_path / "docs/data/label_index.csv"
    path.parent.mkdir(parents=True)
    path.write_text("label,identifier,preferred_term,mapping_status\nA,CHEBI:1,A,MAPPED\n")
    with pytest.raises(ValueError, match="ambiguity"):
        b.load_mim_label_index(tmp_path)
