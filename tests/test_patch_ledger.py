"""The patch ledger makes an unapplied backlog visible (#129 item 4).

`generate_kgm_xref_patches.py` proposes kg-microbe xref deltas and nothing
recorded whether anyone acted. The evidence that this matters is the artifact:
513 rows, last written 2026-04-20, untouched for four months, with no
indication anywhere that it was old or outstanding. Regenerating it against
current inputs gives 571 -- fifty-eight proposals accumulated unseen.

This tracks; it never applies. Applying means changing kg-microbe, a separate
repository and a separate decision.
"""

from __future__ import annotations

import json
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
