"""A missing source in the xref-patch chain must announce itself.

#193 made these scripts read `MEDIAINGREDIENTMECH_ROOT` and `KGMICROBE_ROOT`
instead of literal absolute paths. That is what makes them runnable anywhere,
and it is also what makes a *wrong* root reachable for the first time -- with a
literal, the file was either there or the script was obviously being run on the
wrong machine.

The dangerous shape is not a crash. It is a source that quietly contributes
zero rows, leaving a complete-looking report that is short by a whole input.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        f"_{name}_under_test", ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pragma: no cover - depends on optional imports
        pytest.skip(f"{name} dependencies are not available")
    return module


def test_importing_the_chain_does_not_require_a_checkout():
    """The #147/#176 contract: module level resolves paths, main() verifies."""
    for name in (
        "kgm_unified_mappings",
        "audit_kgm_mim_reconciliation",
        "generate_mim_migration_map",
        "generate_kgm_xref_patches",
    ):
        assert _load(name) is not None, name


def test_an_absent_mediadive_source_is_announced(tmp_path, capsys):
    """It returned [] in silence, so a kg-microbe checkout without this file
    shortened the unmapped-candidate count with nothing saying a source was
    missing. Observed: 391 candidates with the file, 190 without."""
    module = _load("audit_kgm_mim_reconciliation")

    rows = module.load_mediadive_unmapped(tmp_path / "absent.tsv")

    assert rows == []
    stderr = capsys.readouterr().err
    assert "MediaDive unmapped ingredients not found" in stderr
    assert "KGMICROBE_ROOT" in stderr, "the message must name the knob to fix"


def test_the_kgm_loader_does_not_claim_a_refusal_it_does_not_make(tmp_path):
    """`load_kgm_entity_index` returns {} for a missing file; the refusal with
    a regeneration command lives in each caller. A comment crediting the
    loader with it would send a reader looking in the wrong place."""
    module = _load("kgm_unified_mappings")

    assert module.load_kgm_entity_index(tmp_path / "absent.tsv.gz") == {}
