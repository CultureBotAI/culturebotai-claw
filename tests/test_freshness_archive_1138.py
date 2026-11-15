"""Offline integrity gates for the issue-1252 provenance-only repair."""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLOSEOUT = ROOT / "scripts/adhoc/repository-freshness-closeout-20261115"
HELPER = CLOSEOUT / "verify_release.py"
spec = importlib.util.spec_from_file_location("freshness_archive_1138", HELPER)
assert spec and spec.loader
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.fixture
def archive(tmp_path):
    for relative in (verifier.CANDIDATE, verifier.CLOSEOUT):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    return tmp_path


def receipt():
    return json.loads((CLOSEOUT / "verification.json").read_text())


def test_preserved_archive_and_receipt_binding():
    verifier.validate_receipt(ROOT, receipt())
    assert receipt()["historical_candidate"]["fleet_provenance"]["manifest"]["equal"] is False


@pytest.mark.parametrize("name", ["contract.yaml", "schema.yaml", "SKILL.md", "proposal.json"])
def test_changed_archive_rejected(archive, name):
    path = archive / verifier.CANDIDATE / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(verifier.VerificationError, match="historical candidate changed"):
        verifier.verify_archive_files(archive)


def test_hidden_extra_archive_file_rejected(archive):
    (archive / verifier.CANDIDATE / ".unreported").write_text("unreported")
    with pytest.raises(verifier.VerificationError, match="including hidden"):
        verifier.verify_archive_files(archive)


def test_symlink_archive_rejected(archive):
    path = archive / verifier.CANDIDATE / "contract.yaml"
    path.unlink()
    path.symlink_to(ROOT / verifier.CANDIDATE / "contract.yaml")
    with pytest.raises(verifier.VerificationError, match="historical candidate changed"):
        verifier.verify_archive_files(archive)


def test_changed_helper_rejected(archive):
    helper = archive / verifier.CLOSEOUT / "verify_release.py"
    helper.write_bytes(helper.read_bytes() + b"\n# changed\n")
    with pytest.raises(verifier.VerificationError, match="helper hash differs"):
        verifier.validate_receipt(archive, receipt())


@pytest.mark.parametrize("change", ["authority", "manifest", "payload"])
def test_false_receipt_claim_rejected(change):
    value = copy.deepcopy(receipt())
    if change == "authority":
        value["adopted"] = True
    elif change == "manifest":
        value["historical_candidate"]["fleet_provenance"]["manifest"]["equal"] = True
    else:
        value["canonical_publication"]["payloads"].pop(next(iter(verifier.PAYLOADS)))
    with pytest.raises(verifier.VerificationError):
        verifier.validate_receipt(ROOT, value)


def test_receipt_writer_refuses_overwrite_and_active_path(archive):
    existing = archive / verifier.CLOSEOUT / "verification.json"
    with pytest.raises(verifier.VerificationError, match="already exists"):
        verifier.write_receipt(existing, receipt(), archive)
    with pytest.raises(verifier.VerificationError, match="dedicated closeout"):
        verifier.write_receipt(archive / "active.json", receipt(), archive)
    assert not (archive / "active.json").exists()


@pytest.mark.parametrize("old,new,node", [
    ("and sha256(observed[1]) == expected", "and True",
     "test_changed_archive_rejected[contract.yaml]"),
    ('value.get("helper_sha256") == sha256((root / CLOSEOUT / "verify_release.py").read_bytes())',
     'value.get("helper_sha256") == value.get("helper_sha256")', "test_changed_helper_rejected"),
])
def test_mutation_guard_is_distinguishing(tmp_path, old, new, node):
    """A fresh pytest process must fail after one production guard is removed."""
    program = r'''
import pathlib, sys, types
import pytest
helper, old, new, node = sys.argv[1:]
source = pathlib.Path(helper).read_text()
assert source.count(old) == 1
mutant = types.ModuleType("archive_mutation")
mutant.__file__ = helper
exec(compile(source.replace(old, new), helper, "exec"), mutant.__dict__)
class Plugin:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            item.module.verifier = mutant
raise SystemExit(pytest.main([node, "-q"], plugins=[Plugin()]))
'''
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "fresh-bytecode")
    result = subprocess.run(
        [sys.executable, "-c", program, str(HELPER), old, new,
         f"tests/test_freshness_archive_1138.py::{node}"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "DID NOT RAISE" in result.stdout, result.stdout + result.stderr
