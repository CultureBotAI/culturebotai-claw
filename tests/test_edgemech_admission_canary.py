"""Canary receipts cannot follow an apparent external parent into the consumer."""

import importlib.util
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "scripts/adhoc/verify_edgemech_admission_canary_20261107.py"


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location("admission_canary_helper", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_receipt_parent_symlink_into_consumer_is_rejected(helper, tmp_path):
    consumer = tmp_path / "EdgeMech"
    consumer.mkdir()
    external = tmp_path / "apparently-external"
    external.symlink_to(consumer, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        helper.receipt_path(external / "receipt.json", consumer)
    assert not (consumer / "receipt.json").exists()


def test_new_literal_receipt_outside_consumer_is_allowed(helper, tmp_path):
    consumer = tmp_path / "EdgeMech"
    consumer.mkdir()
    path = tmp_path / "new-directory/receipt.json"
    assert helper.receipt_path(path, consumer) == path
    assert not path.exists()


@pytest.mark.parametrize("kind", ["inside", "traversal", "exists", "dangling_symlink"])
def test_receipt_refuses_unsafe_or_existing_destinations(helper, tmp_path, kind):
    consumer = tmp_path / "EdgeMech"
    consumer.mkdir()
    path = tmp_path / "receipt.json"
    if kind == "inside":
        path = consumer / "receipt.json"
    elif kind == "traversal":
        path = tmp_path / "unused/../receipt.json"
    elif kind == "exists":
        path.write_text("retain existing output\n")
    else:
        path.symlink_to(tmp_path / "missing.json")
    with pytest.raises(ValueError):
        helper.receipt_path(path, consumer)
