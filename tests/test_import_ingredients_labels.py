"""Chemical source labels must survive import without display-case rewriting."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_ingredients.py"
SPEC = importlib.util.spec_from_file_location("import_ingredients_for_test", SCRIPT)
assert SPEC and SPEC.loader
IMPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = IMPORT
SPEC.loader.exec_module(IMPORT)


@pytest.mark.parametrize(
    "label",
    [
        "myo-inositol",
        "cis-aconitate",
        "alpha-D-glucose",
        "beta-hydroxybutyrate",
        "D-galacturonic acid",
        "gamma-aminobutyric acid",
        "hydrogen sulfide",
    ],
)
def test_microbedecoder_preserves_chemical_case(tmp_path, monkeypatch, label: str) -> None:
    source = tmp_path / "data/transformed/microbedecoder/unmapped_labels.tsv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "label\tsource_columns\tplaceholder_curie\n"
        f"{label}\tBacDive_Metabolite_utilization\tPLACEHOLDER:1\n"
    )
    monkeypatch.setattr(IMPORT, "KGM_ROOT", tmp_path)
    candidates = list(IMPORT.src_microbedecoder())
    assert [candidate.name for candidate in candidates] == [label]


def test_kgm_unmapped_preserves_the_source_label(tmp_path, monkeypatch) -> None:
    source = tmp_path / "docs/metatraits/unmapped_compounds.tsv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "label_token\tplaceholder_id\n"
        "alpha-D-glucose\tPLACEHOLDER:1\n"
        "D-galacturonic acid\tPLACEHOLDER:2\n"
    )
    monkeypatch.setattr(IMPORT, "KGM_ROOT", tmp_path)
    assert [candidate.name for candidate in IMPORT.src_kgm_unmapped()] == [
        "alpha-D-glucose",
        "D-galacturonic acid",
    ]
