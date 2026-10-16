"""The unified builder must count what CultureMech's occurrence table counts (#604).

The builder read only each record's root ``ingredients``. CultureMech keeps
components in two more places: a solution record's root ``composition``, and
the ``composition`` of stocks written inline in ``solutions[]`` at any depth,
where CultureMech#577 moved the components of 162 records. Neither reached the
unified mapping. These fixtures pin the rules of CultureMech's scanner
(``scripts/ingredient_occurrences.py``, CultureMech#605), including the one
that stops the count from doubling: a nested solution that references a record
in the same scan is left to that record (CultureMech#312).
"""

from __future__ import annotations

import importlib.util
import re
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
        "id": "CM:1", "name": "Medium", "ingredients": [], "solutions": [
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
        "id": "CM:1", "name": "Medium", "ingredients": [],
        "solutions": [{"culturemech_term": {"id": "CM:2"}, "composition": _items("Glucose")}],
    })
    _write(tmp_path, "z_solution.yaml", _solution("CM:2", "mediadive.solution:7", "Glucose"))

    assert _counts(tmp_path) == {"Glucose": 1}


def test_inline_stock_supplies_a_term_id_and_follows_root_examples(tmp_path):
    _write(tmp_path, "a.yaml", {"id": "CM:1", "name": "A", "ingredients": _items("Yeast extract")})
    _write(tmp_path, "b.yaml", {
        "id": "CM:2", "name": "B", "ingredients": [], "solutions": [{"composition": [
            {"preferred_term": "Yeast extract", "term": {"id": "FOODON:03315426"}},
        ]}],
    })
    for stem in ("c", "d"):
        _write(tmp_path, f"{stem}.yaml",
               {"id": f"CM:{stem}", "name": stem, "ingredients": _items("Yeast extract")})

    info = builder.scan_culturemech(tmp_path)["Yeast extract"]

    assert info["count"] == 4
    assert info["term_id"] == "FOODON:03315426"
    # Every record's root rows come before any inline stock (#609).
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
    _write(tmp_path, "c_medium.yaml", {"id": "CM:2", "name": "Stocked", "ingredients": [], "solutions": [
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


def test_a_medium_term_met_after_a_solution_term_still_wins(tmp_path):
    # The name is first met in a medium without a term, so it starts at the
    # medium's rank. A solution record's term fills the gap; a later medium's
    # term must still replace it (#606).
    _write(tmp_path, "a_medium.yaml", {
        "id": "CM:1", "name": "A", "ingredients": _items("Cysteine HCl"),
    })
    _write(tmp_path, "b_solution.yaml", {
        "id": "CM:2", "preferred_term": "S", "term": {"id": "mediadive.solution:1"},
        "composition": [{"preferred_term": "Cysteine HCl",
                         "term": {"id": "mediadive.compound:1198"}}],
    })
    _write(tmp_path, "c_medium.yaml", {"id": "CM:3", "name": "C", "ingredients": [
        {"preferred_term": "Cysteine HCl", "term": {"id": "CHEBI:91247"}},
    ]})

    assert builder.scan_culturemech(tmp_path)["Cysteine HCl"]["term_id"] == "CHEBI:91247"


@pytest.mark.parametrize("solution_shaped", [False, True], ids=["media", "solution records"])
def test_the_first_term_met_within_a_rank_wins(tmp_path, solution_shaped):
    for stem, term_id in (("a", "CHEBI:15377"), ("b", "CHEBI:33813")):
        component = [{"preferred_term": "Distilled water", "term": {"id": term_id}}]
        if solution_shaped:
            record = {"id": f"CM:{stem}", "preferred_term": stem,
                      "term": {"id": f"mediadive.solution:{stem}"}, "composition": component}
        else:
            record = {"id": f"CM:{stem}", "name": stem, "ingredients": component}
        _write(tmp_path, f"{stem}.yaml", record)

    assert builder.scan_culturemech(tmp_path)["Distilled water"]["term_id"] == "CHEBI:15377"


def test_a_solution_records_inline_stocks_keep_the_solution_rank(tmp_path):
    _write(tmp_path, "a_solution.yaml", {
        "id": "CM:9", "preferred_term": "S", "term": {"id": "mediadive.solution:7"},
        "composition": [], "solutions": [{"composition": [
            {"preferred_term": "Hemin", "term": {"id": "mediadive.compound:2"}},
        ]}],
    })
    _write(tmp_path, "b_medium.yaml", {"id": "CM:1", "name": "M", "ingredients": [], "solutions": [
        {"composition": [{"preferred_term": "Hemin", "term": {"id": "CHEBI:30413"}}]},
    ]})

    info = builder.scan_culturemech(tmp_path)["Hemin"]

    assert info["term_id"] == "CHEBI:30413"
    assert info["example_media"] == ["CM:1", "CM:9"]


def test_a_media_shaped_solution_record_still_owns_ingredients(tmp_path):
    # CultureMech curates `record_kind: SOLUTION` on stocks imported with
    # MediaRecipe shape; shape follows the upstream term.id alone.
    _write(tmp_path, "stock.yaml", {
        "id": "CM:1", "name": "Trace element solution (medium 929)",
        "record_kind": "SOLUTION", "ingredients": _items("ZnCl2"),
    })

    assert _counts(tmp_path) == {"ZnCl2": 1}


def test_a_mediums_term_id_is_not_a_reference_target(tmp_path):
    # By term.id, only a standalone solution record is a reference target.
    _write(tmp_path, "a.yaml", {
        "id": "CM:1", "name": "Base", "term": {"id": "mediadive.medium:5"},
        "ingredients": _items("Agar"),
    })
    _write(tmp_path, "b.yaml", {"id": "CM:2", "name": "Derived", "ingredients": [], "solutions": [
        {"term": {"id": "mediadive.medium:5"}, "composition": _items("Peptone")},
    ]})

    assert _counts(tmp_path) == {"Agar": 1, "Peptone": 1}


@pytest.mark.parametrize("nested", [
    {"culturemech_term": {"id": "CM:2"}, "composition": None},
    {"term": {"id": "mediadive.solution:7"}, "composition": None},
    {"culturemech_term": {"id": "CM:2"}, "solutions": [{"composition": None}]},
], ids=["culturemech_term reference", "term.id reference", "below a reference"])
def test_a_stock_named_only_by_reference_may_leave_composition_null(tmp_path, nested):
    # CultureMech's schema makes a SolutionDescriptor's composition optional
    # "when the solution is referenced by name only", and its scanner never
    # walks into a reference, so it accepts all three (#614).
    _write(tmp_path, "solution.yaml", _solution("CM:2", "mediadive.solution:7", "Glucose"))
    _write(tmp_path, "medium.yaml", {
        "id": "CM:1", "name": "M", "ingredients": _items("Agar"), "solutions": [nested],
    })

    assert _counts(tmp_path) == {"Agar": 1, "Glucose": 1}


def test_blank_and_non_text_names_are_not_occurrences(tmp_path):
    _write(tmp_path, "medium.yaml", {"id": "CM:1", "name": "Medium", "ingredients": [
        {"preferred_term": None}, {"preferred_term": "  "}, {"preferred_term": 5},
        {"preferred_term": " Agar "},
    ]})

    assert _counts(tmp_path) == {"Agar": 1}


_MEDIUM = {"id": "CM:1", "name": "M", "ingredients": []}
# A directory named like a record: reading it raises an OSError.
_DIRECTORY = object()
_REFUSED = [
    ("root list", {"medium.yaml": {**_MEDIUM, "ingredients": "Agar"}},
     "medium.yaml: ingredients must be a list (got str)"),
    ("root falsy", {"medium.yaml": {**_MEDIUM, "ingredients": {}}},
     "medium.yaml: ingredients must be a list (got dict)"),
    ("root missing", {"medium.yaml": {"id": "CM:1", "name": "M"}},
     "medium.yaml: ingredients must be a list (got missing or null)"),
    ("root item", {"medium.yaml": {**_MEDIUM, "ingredients": ["Agar"]}},
     "medium.yaml: ingredients/0 must be a mapping"),
    ("nested list", {"medium.yaml": {**_MEDIUM, "solutions": [{"composition": {"x": 1}}]}},
     "medium.yaml: solutions/0/composition must be a list (got dict)"),
    ("nested null", {"medium.yaml": {**_MEDIUM, "solutions": [{"composition": None}]}},
     "medium.yaml: solutions/0/composition must be a list (got missing or null)"),
    ("nested item", {"medium.yaml": {**_MEDIUM, "solutions": [{"solutions": [
        {"composition": ["Agar"]}]}]}},
     "medium.yaml: solutions/0/solutions/0/composition/0 must be a mapping"),
    ("solutions not a list", {"medium.yaml": {**_MEDIUM, "solutions": {"composition": []}}},
     "medium.yaml: solutions must be a list (got dict)"),
    ("solutions empty mapping", {"medium.yaml": {**_MEDIUM, "solutions": {}}},
     "medium.yaml: solutions must be a list (got dict)"),
    ("solution not a mapping", {"medium.yaml": {**_MEDIUM, "solutions": ["Stock A"]}},
     "medium.yaml: solutions/0 must be a mapping"),
    ("below a reference", {
        "solution.yaml": {"id": "CM:2", "preferred_term": "S", "term": {"id": "mediadive.solution:7"},
                          "composition": []},
        "medium.yaml": {**_MEDIUM, "solutions": [
            {"culturemech_term": {"id": "CM:2"}, "composition": "Glucose"}]},
    }, "medium.yaml: solutions/0/composition must be a list (got str)"),
    # A broken stock referenced by a medium: counting around it would drop the
    # medium's copy of its components without a word.
    ("referenced record broken", {
        "solution.yaml": {"id": "CM:2", "preferred_term": "S", "term": {"id": "mediadive.solution:7"},
                          "composition": None},
        "medium.yaml": {**_MEDIUM, "ingredients": _items("Agar"), "solutions": [
            {"culturemech_term": {"id": "CM:2"}, "composition": _items("Glucose")}]},
    }, "solution.yaml: composition must be a list (got missing or null)"),
    ("unparsable", {"medium.yaml": "id: CM:1\nname: [unclosed\n"},
     "medium.yaml: unreadable ("),
    ("not UTF-8", {"medium.yaml": b"id: CM:1\nname: Gew\xfcrz\ningredients: []\n"},
     "medium.yaml: unreadable (UnicodeDecodeError)"),
    ("not readable", {"medium.yaml": _DIRECTORY}, "medium.yaml: unreadable (IsADirectoryError)"),
    ("empty file", {"medium.yaml": ""}, "medium.yaml: the root must be a mapping (got nothing)"),
    ("root not a mapping", {"medium.yaml": "- CM:1\n"},
     "medium.yaml: the root must be a mapping (got list)"),
    ("no id", {"medium.yaml": {"name": "M", "ingredients": _items("Agar")}}, "medium.yaml: no id"),
    ("id not text", {"medium.yaml": {**_MEDIUM, "id": 123}}, "medium.yaml: no id"),
    ("repeated id", {"a.yaml": _MEDIUM, "b.yaml": {**_MEDIUM, "name": "Other"}},
     "b.yaml: id CM:1 is also used by a.yaml"),
    # CultureMech compares stripped ids, so padding does not make a new record.
    ("repeated id once stripped", {"a.yaml": _MEDIUM, "b.yaml": {**_MEDIUM, "id": "CM:1 "}},
     "b.yaml: id CM:1 is also used by a.yaml"),
]


@pytest.mark.parametrize("files, message", [case[1:] for case in _REFUSED],
                         ids=[case[0] for case in _REFUSED])
def test_records_culturemech_would_refuse_stop_the_scan(tmp_path, files, message):
    for relative, content in files.items():
        path = tmp_path / "data" / "normalized_yaml" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is _DIRECTORY:
            path.mkdir()
        elif isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            _write(tmp_path, relative, content)

    with pytest.raises(ValueError, match=re.escape(message)):
        builder.scan_culturemech(tmp_path)


def test_every_problem_is_reported_and_none_is_counted_around(tmp_path):
    _write(tmp_path, "a.yaml", {"name": "No id", "ingredients": _items("Agar")})
    _write(tmp_path, "b.yaml", {"id": "CM:2", "name": "B", "ingredients": _items("Peptone")})
    _write(tmp_path, "c.yaml", {"id": "CM:3", "name": "C", "ingredients": "Glucose"})

    with pytest.raises(ValueError) as raised:
        builder.scan_culturemech(tmp_path)

    message = str(raised.value)
    assert message.startswith("2 problem(s) under ")
    assert "a.yaml: no id" in message and "c.yaml: ingredients must be a list" in message


@pytest.mark.parametrize("make_tree", [False, True], ids=["no directory", "no records"])
def test_no_records_is_an_error_not_an_empty_mapping(tmp_path, make_tree):
    if make_tree:
        (tmp_path / "data" / "normalized_yaml" / "bacterial").mkdir(parents=True)

    with pytest.raises(ValueError, match="no CultureMech records"):
        builder.scan_culturemech(tmp_path)
