"""Synthetic ongoing regression tests for cleanup plan byte binding (#1268)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "scripts/adhoc/cycle-maintenance-20261115/provenance-v3/package_review_provenance_v3.py"
SPEC = importlib.util.spec_from_file_location("review_provenance_packager", SOURCE)
assert SPEC and SPEC.loader
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)

# The transformation recognizes the same loader/output statements as the retained
# historical helper. The fixture carries no private inventory or historical counts.
SYNTHETIC = '''import argparse,hashlib,json,os
from pathlib import Path
def main():
    p=argparse.ArgumentParser();p.add_argument('--task-root',type=Path,required=True);a=p.parse_args()
    task=a.task_root.resolve();audit=task/'cleanup';data=json.loads((audit/'inventory-20261115/summary.json').read_text())
    drift={r['root']:r for r in json.loads((audit/'owned-review-content-drift.json').read_text())}
    note="The observation recorded bash PID_FIRST, uv PID_SECOND and Python PID_THIRD using this task (3 matching open descriptors/cwds). The live collaboration census showed fixture owners running."
    (audit/'PLAN.md').write_text(note)
    value={'items':data['repositories'],'drift':drift,'plan_sha256':hashlib.sha256((audit/'PLAN.md').read_bytes()).hexdigest()}
    (audit/'ACTION-PLAN.json').write_text(json.dumps(value))
if __name__=='__main__':main()
'''.replace('PID_FIRST', 'PID' + str(1)).replace('PID_SECOND', 'PID' + str(2)).replace('PID_THIRD', 'PID' + str(3))


@pytest.fixture
def prepared(tmp_path):
    task = tmp_path / "inputs"
    inventory = task / "cleanup/inventory-20261115/summary.json"
    drift = task / "cleanup/owned-review-content-drift.json"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({"repositories": [{"root": "owned-fixture"}]}))
    drift.write_text(json.dumps([{"root": "owned-fixture", "retained": "original-evidence"}]))
    pins = {
        path.relative_to(task).as_posix(): {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in (inventory, drift)
    }
    rendered, _ = packager.plan_edit(SYNTHETIC, pins)
    return task, tmp_path / "output", inventory, drift, rendered


@pytest.mark.parametrize("selected", ["inventory", "drift"])
def test_second_read_cannot_substitute_unverified_plan_input(prepared, monkeypatch, selected):
    task, output, inventory, drift, rendered = prepared
    victim = inventory if selected == "inventory" else drift
    original_read_text = Path.read_text
    substituted_reads = []

    def substitute(path, *args, **kwargs):
        if path == victim:
            substituted_reads.append(path)
            return '{"repositories":[]}' if selected == "inventory" else '[]'
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", substitute)
    monkeypatch.setattr(sys, "argv", ["plan.py", "--task-root", str(task), "--output", str(output)])
    exec(compile(rendered, "plan.py", "exec"), {"__name__": "__main__"})
    observed = json.loads((output / "ACTION-PLAN.json").read_bytes())
    assert observed["items"] == [{"root": "owned-fixture"}]
    assert observed["drift"] == {"owned-fixture": {"root": "owned-fixture", "retained": "original-evidence"}}
    assert substituted_reads == []


@pytest.mark.parametrize("selected", ["inventory", "drift"])
def test_changed_first_read_refuses_before_creating_output(prepared, monkeypatch, selected):
    task, output, inventory, drift, rendered = prepared
    victim = inventory if selected == "inventory" else drift
    victim.write_bytes(victim.read_bytes() + b"\n")
    monkeypatch.setattr(sys, "argv", ["plan.py", "--task-root", str(task), "--output", str(output)])
    with pytest.raises(ValueError, match="inputs differ"):
        exec(compile(rendered, "plan.py", "exec"), {"__name__": "__main__"})
    assert not output.exists()
