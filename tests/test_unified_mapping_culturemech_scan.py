"""The unified builder must count what CultureMech's occurrence table counts (#604).

The builder read only each record's root ``ingredients``. CultureMech keeps
components in two more places: a solution record's root ``composition``, and
the ``composition`` of stocks written inline in ``solutions[]`` at any depth,
where CultureMech#577 moved 2,175 ingredients of 360 media. Neither reached
the unified mapping. These fixtures pin the rules of CultureMech's scanner
(``scripts/ingredient_occurrences.py``, CultureMech#605), including the one
that stops the count from doubling: a nested solution that references a record
in the same scan is left to that record (CultureMech#312).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

_spec = importlib.util.spec_from_file_location(
    "build_unified_ingredient_mapping_scan",
    Path(__file__).parent.parent / "scripts" / "build_unified_ingredient_mapping.py",
)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def _write(culturemech: Path, relative: str, record: dict) -> None:
    path = culturemech / "data" / "normalized_yaml" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")


def _counts(culturemech: Path) -> dict:
    return {name: info["count"] for name, info in builder.scan_culturemech(culturemech).items()}


def _items(*names: str) -> list:
    return [{"preferred_term": name} for name in names]


def _solution(record_id: str, solution_id: str, *names: str, **extra) -> dict:
    return {"id": record_id, "preferred_term": f"Stock {solution_id}",
            "term": {"id": solution_id, "label": f"Stock {solution_id}"},
            "composition": _items(*names), **extra}


def test_solution_record_counts_composition_not_its_placeholder_ingredients(tmp_path):
    # Every MediaDive solution record carries this one placeholder row in
    # `ingredients`; its components are in `composition`.
    _write(tmp_path, "bacterial/solution.yaml", _solution(
        "CM:2", "mediadive.solution:7", "Glucose", "Peptone",
        ingredients=_items("See source for composition"),
    ))

    assert _counts(tmp_path) == {"Glucose": 1, "Peptone": 1}


def test_record_shape_picks_exactly_one_component_field(tmp_path):
    # A MediaIngredientMech-sourced solution is SolutionRecipe-shaped as well.
    _write(tmp_path, "solutions/mim.yaml", _solution(
        "CM:3", "MediaIngredientMech:000123", "Biotin"))
    # A medium owns `ingredients`; a stray `composition` beside them is not read.
    _write(tmp_path, "bacterial/medium.yaml", {
        "id": "CM:1", "name": "Medium", "term": {"id": "mediadive.medium:1"},
        "ingredients": _items("Agar"), "composition": _items("Not a component"),
    })

    assert _counts(tmp_path) == {"Biotin": 1, "Agar": 1}


def test_inline_stocks_are_counted_at_every_depth(tmp_path):
    _write(tmp_path, "bacterial/medium.yaml", {
        "id": "CM:1", "name": "Medium", "ingredients": _items("NaCl"),
        "solutions": [
            {"preferred_term": "Salts", "composition": _items("NaCl", "KCl"),
             "solutions": [
                 {"preferred_term": "Trace", "composition": _items("ZnSO4"),
                  "solutions": [{"composition": _items("CoCl2")}]},
             ]},
            {"preferred_term": "No composition", "solutions": [
                {"preferred_term": "Vitamins", "composition": _items("Biotin")},
            ]},
        ],
    })

    scan = builder.scan_culturemech(tmp_path)

    # NaCl is added twice, once directly and once in a stock: two occurrences,
    # as in CultureMech's table.
    assert {name: info["count"] for name, info in scan.items()} == {
        "NaCl": 2, "KCl": 1, "ZnSO4": 1, "CoCl2": 1, "Biotin": 1,
    }
    assert scan["CoCl2"]["example_media"] == ["CM:1"]


@pytest.mark.parametrize("reference", [
    {"culturemech_term": {"id": "CM:2"}},
    {"term": {"id": "mediadive.solution:7"}},
    {"culturemech_term": {"id": "CM:3"}},
], ids=["culturemech_term names a solution record", "term.id of a solution record",
        "culturemech_term names a medium"])
def test_reference_to_a_scanned_record_is_left_to_that_record(tmp_path, reference):
    _write(tmp_path, "solutions/solution.yaml", _solution("CM:2", "mediadive.solution:7", "Glucose"))
    _write(tmp_path, "bacterial/base.yaml", {
        "id": "CM:3", "name": "Base medium", "ingredients": _items("Glucose"),
    })
    _write(tmp_path, "bacterial/medium.yaml", {
        "id": "CM:1", "name": "Medium", "ingredients": _items("Agar"),
        "solutions": [{
            "preferred_term": "Copy of the shared stock", **reference,
            "composition": _items("Glucose"),
            # Nothing below a reference is counted either.
            "solutions": [{"preferred_term": "Inner", "composition": _items("Peptone")}],
        }],
    })

    assert _counts(tmp_path) == {"Glucose": 2, "Agar": 1}


def test_stale_culturemech_term_falls_back_to_the_solution_term_id(tmp_path):
    _write(tmp_path, "solutions/solution.yaml", _solution("CM:2", "mediadive.solution:7", "Glucose"))
    _write(tmp_path, "bacterial/medium.yaml", {
        "id": "CM:1", "name": "Medium", "solutions": [
            # CM:404 names no scanned record, but the term.id is a scanned stock.
            {"culturemech_term": {"id": "CM:404"}, "term": {"id": "mediadive.solution:7"},
             "composition": _items("Glucose")},
            # Neither link names a scanned record: an inline stock after all.
            {"culturemech_term": {"id": "CM:405"}, "term": {"id": "mediadive.solution:8"},
             "composition": _items("Tryptone")},
        ],
    })

    assert _counts(tmp_path) == {"Glucose": 1, "Tryptone": 1}


def test_reference_is_recognised_whichever_file_sorts_first(tmp_path):
    # The medium sorts before the record it references, so deciding references
    # while reading files would count the stock's components a second time.
    _write(tmp_path, "a_medium.yaml", {
        "id": "CM:1", "name": "Medium",
        "solutions": [{"culturemech_term": {"id": "CM:2"}, "composition": _items("Glucose")}],
    })
    _write(tmp_path, "z_solution.yaml", _solution("CM:2", "mediadive.solution:7", "Glucose"))

    assert _counts(tmp_path) == {"Glucose": 1}


def test_inline_stock_supplies_a_term_id_and_follows_root_examples(tmp_path):
    _write(tmp_path, "a.yaml", {"id": "CM:1", "name": "A", "ingredients": _items("Yeast extract")})
    _write(tmp_path, "b.yaml", {
        "id": "CM:2", "name": "B", "solutions": [{"composition": [
            {"preferred_term": "Yeast extract", "term": {"id": "FOODON:03315426"}},
        ]}],
    })
    for stem in ("c", "d"):
        _write(tmp_path, f"{stem}.yaml",
               {"id": f"CM:{stem}", "name": stem, "ingredients": _items("Yeast extract")})

    info = builder.scan_culturemech(tmp_path)["Yeast extract"]

    assert info["count"] == 4
    assert info["term_id"] == "FOODON:03315426"
    # Root rows are counted while reading, inline stocks afterwards.
    assert info["example_media"] == ["CM:1", "CM:c", "CM:d"]


def test_a_mediums_grounding_outranks_a_solution_records(tmp_path):
    # The solution record sorts first and carries MediaDive's raw compound ids;
    # the media carry curated CHEBI ids, in root ingredients or in an inline stock.
    _write(tmp_path, "a_solution.yaml", {
        "id": "CM:9", "preferred_term": "Stock", "term": {"id": "mediadive.solution:7"},
        "composition": [
            {"preferred_term": "DNA", "term": {"id": "mediadive.compound:958"}},
            {"preferred_term": "Biotin", "term": {"id": "mediadive.compound:17"}},
            {"preferred_term": "Only here", "term": {"id": "mediadive.compound:1"}},
        ],
    })
    _write(tmp_path, "b_medium.yaml", {"id": "CM:1", "name": "Root", "ingredients": [
        {"preferred_term": "DNA", "term": {"id": "CHEBI:16991"}},
    ]})
    _write(tmp_path, "c_medium.yaml", {"id": "CM:2", "name": "Stocked", "solutions": [
        {"composition": [{"preferred_term": "Biotin", "term": {"id": "CHEBI:15956"}}]},
    ]})

    scan = builder.scan_culturemech(tmp_path)

    assert scan["DNA"]["term_id"] == "CHEBI:16991"
    assert scan["DNA"]["example_media"] == ["CM:1", "CM:9"]
    assert scan["Biotin"]["term_id"] == "CHEBI:15956"
    assert scan["Biotin"]["example_media"] == ["CM:2", "CM:9"]
    # With no medium to say otherwise, the solution record's own id stands.
    assert scan["Only here"] == {
        "count": 1, "term_id": "mediadive.compound:1", "example_media": ["CM:9"],
    }


def test_blank_and_non_text_names_are_not_occurrences(tmp_path):
    _write(tmp_path, "medium.yaml", {"id": "CM:1", "name": "Medium", "ingredients": [
        {"preferred_term": None}, {"preferred_term": "  "}, {"preferred_term": 5},
        {"preferred_term": " Agar "},
    ]})

    assert _counts(tmp_path) == {"Agar": 1}


@pytest.mark.parametrize("record, message", [
    ({"id": "CM:1", "name": "M", "ingredients": "Agar"}, "ingredients must be a list"),
    ({"id": "CM:1", "name": "M", "ingredients": ["Agar"]}, "ingredients/0 must be a mapping"),
    ({"id": "CM:1", "name": "M", "solutions": [{"composition": {"preferred_term": "Agar"}}]},
     "solutions/0/composition must be a list"),
    ({"id": "CM:1", "name": "M", "solutions": [{"solutions": [{"composition": ["Agar"]}]}]},
     "solutions/0/solutions/0/composition/0 must be a mapping"),
], ids=["root list", "root item", "nested list", "nested item"])
def test_malformed_components_raise_instead_of_dropping_occurrences(tmp_path, record, message):
    _write(tmp_path, "medium.yaml", record)

    with pytest.raises(ValueError, match=message) as raised:
        builder.scan_culturemech(tmp_path)
    assert "medium.yaml" in str(raised.value)
