"""Archived no-change closures cannot bypass reserved ordered-receipt shape."""
from __future__ import annotations

import json

import pytest
from test_progress_model import add_closure, collect, runtime, save_ledger, write

import kg_microbe_progress as progress


def rewrite_receipt(path, ledger, **changes):
    """Preserve archive/hash agreement so shape, not digest mismatch, rejects it."""
    receipt = json.loads(path.read_text())
    receipt.update(changes)
    record = ledger["completed_stages"][-1]
    record["receipt_sha256"] = progress.digest(receipt)
    destination = path.with_name(f"stage-{record['stage']}-{record['receipt_sha256'][:12]}.json")
    write(destination, receipt)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("field", ["prs", "evidence_attributions"])
@pytest.mark.parametrize("value", [None, [], {}])
def test_no_change_archive_rejects_reserved_receipt_fields(tmp_path, legacy, field, value):
    root, ledger = runtime(tmp_path, stage=2)
    path = add_closure(root, ledger, legacy=legacy)
    rewrite_receipt(path, ledger, **{field: value})
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError, match="ordered PRs"):
        collect(root)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("proofs", [None, [], {}])
def test_no_change_archive_rejects_ordered_verification_proofs(tmp_path, legacy, proofs):
    root, ledger = runtime(tmp_path, stage=2)
    add_closure(root, ledger, legacy=legacy)
    ledger["completed_stages"][-1]["verification"]["prs"] = proofs
    save_ledger(root, ledger)
    with pytest.raises(progress.ProgressError, match="no-change closure contains ordered proofs"):
        collect(root)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("number", [None, 42])
def test_unextended_no_change_and_single_pr_archives_keep_existing_projection(tmp_path, legacy, number):
    root, ledger = runtime(tmp_path, stage=2)
    path = add_closure(root, ledger, pr=number, legacy=legacy)
    original_receipt = path.read_bytes()
    history, snapshot = collect(root)
    assert snapshot["totals"]["completed_goals"] == 1
    assert snapshot["totals"]["no_change_goals"] == int(number is None)
    assert snapshot["totals"]["unique_prs"] == int(number is not None)
    assert snapshot["totals"]["merged_prs"] == int(number is not None)
    assert len(history["associations"]) == len(history["pr_events"]) == int(number is not None)
    assert collect(root, history) == (history, snapshot)
    assert path.read_bytes() == original_receipt
