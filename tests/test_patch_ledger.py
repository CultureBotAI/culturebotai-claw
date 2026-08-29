"""The patch ledger makes an unapplied backlog visible (#129 item 4).

`generate_kgm_xref_patches.py` proposes kg-microbe xref deltas and nothing
recorded whether anyone acted. The evidence that this matters is the artifact:
513 rows, last written 2026-04-20, untouched for four months, with no
indication anywhere that it was old or outstanding. Regenerating it against
current inputs gives 88, and the difference is itself the point: the old
artifact was built from a four-month-old workspace intermediate whose
numeric-namespace migration has since completed (#197). Nothing said either
number was stale.

This tracks; it never applies. Applying means changing kg-microbe, a separate
repository and a separate decision.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kg_microbe_patches import (
    LEDGER_VERSION,
    LedgerError,
    describe,
    fingerprint,
    load,
    record,
    staleness,
)

MOMENT = datetime(2026, 4, 20, tzinfo=timezone.utc)


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    return tmp_path / "patch_ledger.json"


def test_the_first_run_is_recorded_as_such(ledger):
    entry, verdict = record(ledger, ["a", "b"], now=MOMENT)

    assert verdict == "first-run"
    assert entry.runs == 1
    assert entry.rows == 2


def test_the_same_set_returning_is_reported_as_unapplied(ledger):
    """The state that was invisible: the same proposals coming back run after
    run means nobody has applied them."""
    record(ledger, ["a", "b"], now=MOMENT)
    entry, verdict = record(ledger, ["a", "b"], now=MOMENT + timedelta(days=130))

    assert verdict == "unchanged"
    assert entry.runs == 2
    assert entry.days_outstanding == 130
    assert "waiting on a decision" in describe(entry, verdict)


def test_a_changed_set_restarts_the_clock(ledger):
    """Something moved, so "outstanding since" is no longer the old date."""
    record(ledger, ["a", "b"], now=MOMENT)
    entry, verdict = record(ledger, ["a"], now=MOMENT + timedelta(days=5))

    assert verdict == "changed"
    assert entry.runs == 1
    assert entry.days_outstanding == 0


def test_row_order_is_not_a_change(ledger):
    """Generator output order follows dict iteration; a reordering is not a
    change to what is being proposed."""
    record(ledger, ["a", "b"], now=MOMENT)
    _, verdict = record(ledger, ["b", "a"], now=MOMENT + timedelta(days=1))

    assert verdict == "unchanged"


def test_a_different_row_is_a_change(ledger):
    """Non-vacuity: the fingerprint must not ignore content."""
    assert fingerprint(["a", "b"]) != fingerprint(["a", "c"])


def test_an_empty_set_is_recorded(ledger):
    """Zero patches is a real, good answer and must be distinguishable from
    never having run."""
    entry, verdict = record(ledger, [], now=MOMENT)

    assert verdict == "first-run"
    assert entry.rows == 0
    assert load(ledger) is not None


def test_no_ledger_yet_reads_as_none(ledger):
    assert load(ledger) is None


def test_an_unsupported_version_is_refused(ledger):
    ledger.write_text(json.dumps({"version": 999}), encoding="utf-8")

    with pytest.raises(LedgerError, match="unsupported patch ledger version"):
        load(ledger)


def test_a_malformed_entry_is_refused(ledger):
    ledger.write_text(
        json.dumps({"version": LEDGER_VERSION, "entry": {"nonsense": 1}}),
        encoding="utf-8",
    )

    with pytest.raises(LedgerError, match="malformed entry"):
        load(ledger)


def test_unreadable_json_is_refused(ledger):
    ledger.write_text("{not json", encoding="utf-8")

    with pytest.raises(LedgerError, match="cannot read"):
        load(ledger)


# --------------------------------------------------------------------------
# Staleness
# --------------------------------------------------------------------------


def test_an_input_newer_than_the_artifact_is_reported(tmp_path):
    """The committed artifact was four months older than its inputs and said
    nothing about it."""
    artifact = tmp_path / "patches.tsv"
    artifact.write_text("old\n", encoding="utf-8")
    newer = tmp_path / "input.tsv"
    newer.write_text("new\n", encoding="utf-8")
    import os
    os.utime(artifact, (0, 0))

    assert staleness(artifact, [newer]) == [newer]


def test_an_artifact_newer_than_its_inputs_is_not_stale(tmp_path):
    older = tmp_path / "input.tsv"
    older.write_text("in\n", encoding="utf-8")
    import os
    os.utime(older, (0, 0))
    artifact = tmp_path / "patches.tsv"
    artifact.write_text("out\n", encoding="utf-8")

    assert staleness(artifact, [older]) == []


def test_a_missing_artifact_is_not_reported_as_stale(tmp_path):
    """Nothing generated yet is not the same as something out of date."""
    existing = tmp_path / "input.tsv"
    existing.write_text("in\n", encoding="utf-8")

    assert staleness(tmp_path / "absent.tsv", [existing]) == []


def test_a_missing_input_is_ignored(tmp_path):
    artifact = tmp_path / "patches.tsv"
    artifact.write_text("out\n", encoding="utf-8")

    assert staleness(artifact, [tmp_path / "absent.tsv"]) == []


# --------------------------------------------------------------------------
# #195: bookkeeping must not fail a run that produced its product
# --------------------------------------------------------------------------


def test_record_stays_strict_for_callers_that_want_the_history(ledger):
    """The generator tolerates a corrupt ledger; `record` itself must not
    pretend it read one."""
    ledger.write_text("{broken", encoding="utf-8")

    with pytest.raises(LedgerError):
        record(ledger, ["a"], now=MOMENT)


def test_the_generator_survives_a_corrupt_ledger(tmp_path, monkeypatch, capsys):
    """The patches are the product; the ledger is bookkeeping. A run that wrote
    its patches must not then fail on the history file (#195)."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "_xref_patches_under_test", root / "scripts" / "generate_kgm_xref_patches.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pragma: no cover - needs kg-microbe to import
        pytest.skip("generator dependencies are not available")

    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "patch_ledger.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(module, "PATCHES_DIR", patches)
    monkeypatch.setattr(module, "OUT_TSV", patches / "p.tsv")
    monkeypatch.setattr(module, "OUT_MD", patches / "p.md")
    monkeypatch.setattr(module, "build_patches", lambda *a, **k: [])
    monkeypatch.setattr(module, "load_mim_sssom_chebi_to_mim", lambda: {})
    monkeypatch.setattr(module, "load_kgm_xrefs", lambda: {})
    monkeypatch.setattr(module, "load_migration_map", lambda: [])
    monkeypatch.setattr(module, "require_mech_roots", lambda *a, **k: {})
    # main() parses arguments now (#179 wants --help to work without a
    # checkout), so it must not inherit pytest's argv.
    monkeypatch.setattr(sys, "argv", ["generate_kgm_xref_patches.py"])

    module.main()

    assert (patches / "p.tsv").is_file(), "the product must still be written"
    assert "patch ledger unavailable" in capsys.readouterr().out


def test_an_unwritable_ledger_fails_as_a_ledger_error(tmp_path):
    """A ledger that cannot be written must fail the same way as one that
    cannot be read, so one except clause covers the bookkeeping (#195)."""
    blocked = tmp_path / "read-only"
    blocked.mkdir(mode=0o500)
    try:
        with pytest.raises(LedgerError, match="cannot write patch ledger"):
            record(blocked / "sub" / "ledger.json", ["a"], now=MOMENT)
    finally:
        blocked.chmod(0o700)


def test_staleness_covers_the_intermediate_the_patches_are_built_from(tmp_path):
    """A stale workspace intermediate silently inflates the patch set.

    The 2026-04-20 migration map carried 1,510 rows from the completed
    numeric-namespace migration and produced 571 patches; the regenerated
    13-row map produces 88. Comparing the patch file only against MIM's SSSOM
    and kg-microbe's dictionary cannot see that, because neither of those
    moved (#197).
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "generate_kgm_xref_patches.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "staleness"
    )
    inputs = {ast.unparse(element) for element in call.args[1].elts}

    assert "MIGRATION_TSV" in inputs, (
        f"staleness compares against {sorted(inputs)}; a stale MIGRATION_TSV "
        f"would go unreported"
    )
