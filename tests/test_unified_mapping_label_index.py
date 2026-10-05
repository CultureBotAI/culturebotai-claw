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
