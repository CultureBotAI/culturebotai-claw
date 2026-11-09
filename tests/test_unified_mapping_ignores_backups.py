"""The unified builder must read MIM's records, not the backups beside them.

MIM's ``save_yaml`` copies a record into a gitignored ``backups/`` directory
before overwriting it. This builder enumerated with ``rglob``, so on a machine
that had edited records it loaded each edited record twice -- 2,962 loaded from a
tree of 2,951 -- and, because its indexes are first-writer-wins over sorted
paths, the STALE copy won for any stem sorting after ``backups``. The published
snapshot then depended on the local state of whoever built it
(MediaIngredientMech#698).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "build_unified_ingredient_mapping",
    Path(__file__).parent.parent / "scripts" / "build_unified_ingredient_mapping.py",
)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

LIVE = (
    "identifier: CHEBI:30089\npreferred_term: zeta-compound\nmapping_status: MAPPED\n"
    "synonyms:\n- synonym_text: current name\n  synonym_type: EXACT_SYNONYM\n"
)
STALE = (
    "identifier: CHEBI:30089\npreferred_term: zeta-compound\nmapping_status: MAPPED\n"
    "synonyms:\n- synonym_text: WRONG stale name\n  synonym_type: EXACT_SYNONYM\n"
)


def _tree(tmp_path: Path) -> Path:
    mapped = tmp_path / "data" / "ingredients" / "mapped"
    (mapped / "backups").mkdir(parents=True)
    (tmp_path / "data" / "ingredients" / "unmapped").mkdir()
    # A lowercase stem from "c" onward sorts AFTER "backups/", which is the case
    # where the stale copy used to win the first-writer index.
    (mapped / "zeta-compound.yaml").write_text(LIVE, encoding="utf-8")
    (mapped / "backups" / "zeta-compound_20260920_175906.yaml").write_text(STALE, encoding="utf-8")
    return tmp_path


def test_the_precondition_holds():
    """Otherwise this file proves nothing: the backup must sort first."""
    assert "backups/zeta" < "zeta"


def test_backups_are_not_enumerated(tmp_path):
    files = builder._mim_record_files(_tree(tmp_path) / "data" / "ingredients")
    assert [f.name for f in files] == ["zeta-compound.yaml"]


def test_the_live_record_wins_not_its_stale_backup(tmp_path):
    name_index, _, _ = builder.load_mim_index(_tree(tmp_path))
    entries = {id(v): v for v in name_index.values()}.values()
    synonyms = {s for entry in entries for s in entry.get("synonyms", [])}
    assert "current name" in synonyms
    assert "WRONG stale name" not in synonyms, "a stale backup fed the unified index"


def test_a_missing_tree_is_empty_not_an_error(tmp_path):
    assert builder._mim_record_files(tmp_path / "absent") == []
