"""Recovery diagnostics must retain the original failure if a receipt is unreadable."""
import pytest

from kg_microbe_merge_queue import QueueError
from kg_microbe_merge_queue import __main__ as cli


@pytest.mark.parametrize("contents", ["truncated{", "{}", '{"repositories": null}'])
def test_apply_failure_survives_unreadable_receipt(tmp_path, monkeypatch, capsys, contents):
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    receipt = tmp_path / "receipt.json"

    def fail(*args):
        receipt.write_text(contents)
        raise QueueError("original remote write outcome unknown")

    monkeypatch.setattr(cli, "apply", fail)
    with pytest.raises(SystemExit) as error:
        cli.main(["apply", "--plan", str(plan), "--receipt", str(receipt)])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "original remote write outcome unknown" in captured.err
    assert "Could not read receipt" in captured.out
