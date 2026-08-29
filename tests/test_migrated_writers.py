"""The migrated corpus writers stage into a transaction instead of writing.

Phase 3 item 5. Each of these called the shared, non-atomic
`write_yaml(path, record)` in a per-record loop, so a failure part-way through
left an unknown subset of MediaIngredientMech modified with no recovery path
(#156). They now route through `ValidatedWriteTransaction`.

The registry (`src/kg_microbe_write/writers.yaml`) is the authority for which
scripts these are; parametrizing over it means a newly-migrated writer is
covered here automatically rather than by remembering to add it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from kg_microbe_write import ValidatedWriteTransaction, load_registry

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MIGRATED = sorted(
    path for path, entry in load_registry().items() if entry.uses_transaction
)


def _load(path: str):
    sys.path.insert(0, str(SCRIPTS))
    name = f"_migrated_{Path(path).stem}"
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_registry_records_at_least_one_migrated_writer():
    """Guards the parametrization: an empty list would skip everything below."""
    assert MIGRATED, "no writer is registered as using the transaction"


@pytest.mark.parametrize("script", MIGRATED)
def test_a_migrated_writer_stages_instead_of_writing(script, tmp_path):
    """Staging must not touch the file; only the commit may."""
    module = _load(script)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    target = corpus / "record.yaml"
    target.write_text("identifier: CHEBI:1\n", encoding="utf-8")

    module._TRANSACTION = ValidatedWriteTransaction(corpus)
    module._staged_write(target, {"identifier": "CHEBI:1", "added": "yes"})

    assert target.read_text(encoding="utf-8") == "identifier: CHEBI:1\n"

    result = module._TRANSACTION.commit(apply=True)

    assert result.touched == 1
    assert "added" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("script", MIGRATED)
def test_a_migrated_writer_refuses_to_write_without_an_open_transaction(
    script, tmp_path
):
    """A stray call outside a run must fail loudly rather than write directly."""
    module = _load(script)
    module._TRANSACTION = None

    with pytest.raises(RuntimeError, match="no write transaction"):
        module._staged_write(tmp_path / "x.yaml", {"identifier": "CHEBI:1"})


@pytest.mark.parametrize("script", MIGRATED)
def test_a_migrated_writer_no_longer_imports_the_shared_helper(script):
    """The point of the migration: it must not be able to write directly."""
    source = (ROOT / script).read_text(encoding="utf-8")

    assert "_staged_write(" in source
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("write_yaml("), line
