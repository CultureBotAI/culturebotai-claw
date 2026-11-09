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


def test_a_rejected_first_row_is_followed_to_its_live_survivor(tmp_path):
    _write(tmp_path, "mapped/survivor.yaml", "CHEBI:2", "New name")
    _write(tmp_path, "mapped/stale.yaml", "CHEBI:9", "Stale")
    _write(tmp_path, "mapped/retired.yaml", "CHEBI:8", "Old name", "REJECTED",
           representative="CHEBI:2")
    _label_index(tmp_path, [["Old name", "preferred_term", "CHEBI:2", "Old name", "",
                             "REJECTED", "unique"]])
    row = _rows(tmp_path, "Old name", "CHEBI:9")
    assert row["mim_id"] == "CHEBI:2"


def test_a_loose_name_refusal_applies_only_when_the_label_index_does_not_decide():
    refusal, live = _rec("UNMAPPED_0009", "Mystery mix", status="UNMAPPED"), _rec("CHEBI:1", "One")
    names = {"mystery mix": refusal, "one": live}
    # No row for the exact label: the loose-name refusal stands.
    row = _build(names, {"CHEBI:1": live}, _labels(), "Mystery mix", "CHEBI:1")
    assert row["mim_id"] == "UNMAPPED_0009"
    assert row["chebi_id"] == row["culturemech_term_id"] == ""


def test_an_exact_live_owner_beats_a_loose_name_refusal():
    """The 45-row case (11,577 occurrences): the hydrate-canonical name index
    lands on a refusal, while MIM's label index has a live owner for the exact label."""
    refusal = _rec("UNMAPPED_0042", "Na2MoO4 x 2 H2O (stock)", status="UNMAPPED")
    owner = _rec("CHEBI:75213", "Na2MoO4 x 2 H2O")
    names = {b._normalize("Na2MoO4 x 2 H2O"): refusal}
    labels = _labels(_row("Na2MoO4 x 2 H2O", "CHEBI:75213", "Na2MoO4 x 2 H2O", match="preferred_term"))
    row = _build(names | {"owner": owner}, {"CHEBI:75213": owner}, labels, "Na2MoO4 x 2 H2O", "")
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:75213"


def test_an_exact_unmapped_owner_is_mims_refusal_even_against_a_term_id():
    refusal, live = _rec("UNMAPPED_0007", "Soil extract", status="UNMAPPED"), _rec("CHEBI:1", "One")
    names = {"one": live, "soil extract (alt)": refusal}
    labels = _labels(_row("Soil extract", "UNMAPPED_0007", "Soil extract", status="UNMAPPED",
                          match="preferred_term"))
    row = _build(names, {"CHEBI:1": live}, labels, "Soil extract", "CHEBI:1")
    assert row["mim_id"] == "UNMAPPED_0007"
    assert row["chebi_id"] == row["culturemech_term_id"] == ""


@pytest.mark.parametrize("status", ["PENDING_REVIEW", "IN_PROGRESS", "NEEDS_EXPERT", "AMBIGUOUS"])
def test_an_undecided_first_row_never_rules(status):
    live, term = _rec("CHEBI:2", "Two"), _rec("CHEBI:9", "Nine")
    labels = _labels(_row("Thing", "CHEBI:2", "Two", status=status))
    row = _build({"two": live}, {"CHEBI:2": live, "CHEBI:9": term}, labels, "Thing", "CHEBI:9")
    assert row["mim_id"] == "CHEBI:9"


def test_a_tombstone_row_is_not_followed_to_a_survivor_that_rejects_the_label():
    survivor = _rec("CHEBI:32142", "Na3-citrate x 2 H2O")
    survivor["_rejected_names"] = {b._normalize("Trisodium citrate·3H2O")}
    trihydrate = _rec("CHEBI:9999", "Trisodium citrate trihydrate")
    labels = _labels(_row("Trisodium citrate·3H2O", "CHEBI:32142", "Old tombstone", status="REJECTED"))
    row = _build({"na3-citrate x 2 h2o": survivor}, {"CHEBI:32142": survivor, "CHEBI:9999": trihydrate},
                 labels, "Trisodium citrate·3H2O", "CHEBI:9999")
    assert row["mim_id"] == "CHEBI:9999"


def test_the_label_owner_beats_a_loose_name_match_with_the_same_identifier():
    bacto = _rec("MICRO:0000178", "Bacto peptone")
    bacto["synonyms"] = ["Bacto"]
    peptone = _rec("MICRO:0000178", "Peptone")
    peptone["synonyms"] = ["Peptone, generic"]
    names = {"peptone": bacto, "bacto peptone": bacto, "peptone owner": peptone}
    labels = _labels(_row("Peptone", "MICRO:0000178", "Peptone", match="preferred_term"))
    row = _build(names, {}, labels, "Peptone", "")
    assert row["synonyms"] == "Peptone, generic"


def test_label_keys_match_across_unicode_normalization_forms():
    owner = _rec("CHEBI:5", "Café extract")
    nfd = "Cafe\u0301 extract"  # decomposed e + combining acute
    labels = _labels(_row("Caf\u00e9 extract", "CHEBI:5", "Café extract", match="preferred_term"))
    row = _build({"other": owner}, {}, labels, nfd, "")
    assert row["mim_id"] == "CHEBI:5"


def test_builder_ledger_lookup_uses_the_anchor_for_a_different_prefix_rejection(tmp_path):
    """A rejected ID with a different prefix is not withheld by _published_ids,
    so only the anchor-keyed ledger lookup keeps it out of the row."""
    beta, lactose = _rec("CHEBI:36218", "Beta-Lactose"), _rec("CHEBI:17716", "Lactose")
    names = {"lactose": beta, "milk sugar": lactose}
    labels = _labels(_row("Lactose", "CHEBI:17716", "Lactose", match="preferred_term",
                          ambiguity="resolved:owned"))
    live = b.live_records(names)
    path = tmp_path / b.REJECTIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ingredient_name\trejected_id\tmim_id\treason\n"
                    "Lactose\tFOODON:00001234\tCHEBI:17716\tReviewed\n", encoding="utf-8")
    rejected = b.load_mapping_rejections(tmp_path, names, label_index=labels, live=live)
    row = _build(names, {}, labels, "Lactose", "FOODON:00001234", rejected)
    assert row["mim_id"] == "CHEBI:17716"
    assert "FOODON:00001234" not in row.values()


def test_a_term_id_retired_into_the_anchor_record_is_cleared():
    survivor = _rec("CHEBI:17716", "Lactose")
    survivor["_retired_source_ids"] = {"FOODON:00000042"}
    labels = _labels(_row("Milk sugar", "CHEBI:17716", "Lactose"))
    row = _build({"lactose": survivor}, {}, labels, "Milk sugar", "FOODON:00000042")
    assert row["mim_id"] == "CHEBI:17716"
    assert row["culturemech_term_id"] == ""


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
