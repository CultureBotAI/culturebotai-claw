"""Tests for plugins.ingredient_name_normalizer."""

import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location(
    "ingredient_name_normalizer",
    pathlib.Path(__file__).parent.parent / "plugins" / "ingredient_name_normalizer.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
canonicalize_hydrate = _mod.canonicalize_hydrate


HYDRATE_VARIANTS_4H2O = [
    "MnCl2·4H2O",
    "MnCl2 x 4 H2O",
    "MnCl2 X 4 H2O",
    "MnCl2・4H2O",
    "MnCl2 · 4H2O",
    "MnCl2.4H2O",
    "MnCl2 . 4H2O",
    "MnCl2 x 4H2O",
    "MnCl2 · 4 H2O",
    "MnCl2⋅4H2O",
    "MnCl2∙4H2O",
    "MnCl2×4H2O",
]


@pytest.mark.parametrize("variant", HYDRATE_VARIANTS_4H2O)
def test_4h2o_variants_all_collapse(variant):
    assert canonicalize_hydrate(variant) == "mncl2·4h2o"


def test_anhydrous_stays_distinct_from_hydrated():
    anhydrous = canonicalize_hydrate("MnCl2")
    tetrahydrate = canonicalize_hydrate("MnCl2·4H2O")
    assert anhydrous == "mncl2"
    assert tetrahydrate == "mncl2·4h2o"
    assert anhydrous != tetrahydrate


def test_no_count_hydrate():
    for variant in ["Cysteine-HCl·H2O", "Cysteine-HCl x H2O", "Cysteine-HCl . H2O"]:
        assert canonicalize_hydrate(variant) == "cysteine-hcl·h2o"


def test_other_counts():
    assert canonicalize_hydrate("MgSO4·7H2O") == "mgso4·7h2o"
    assert canonicalize_hydrate("MgSO4 x 7 H2O") == "mgso4·7h2o"
    assert canonicalize_hydrate("Na2SO4.10H2O") == "na2so4·10h2o"
    assert canonicalize_hydrate("CaCl2·2H2O") == "cacl2·2h2o"
    assert canonicalize_hydrate("CoCl2·6H2O") == "cocl2·6h2o"
    assert canonicalize_hydrate("CoCl2 x 6 H2O") == "cocl2·6h2o"


def test_non_hydrate_names_unaffected():
    assert canonicalize_hydrate("NaCl") == "nacl"
    assert canonicalize_hydrate("Distilled water") == "distilled water"
    assert canonicalize_hydrate("Nitrilotriacetic acid (NTA)") == "nitrilotriacetic acid (nta)"
    assert canonicalize_hydrate("Hydrogen gas") == "hydrogen gas"


def test_whitespace_collapse():
    assert canonicalize_hydrate("  MnCl2  ·  4  H2O  ") == "mncl2·4h2o"


def test_nfkc_fullwidth():
    # NFKC-normalized versions of full-width characters should still match.
    assert canonicalize_hydrate("MnCl2·4H2O") == canonicalize_hydrate("ＭｎＣｌ２・４Ｈ２Ｏ")
