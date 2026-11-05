"""Scope controls prevent ingredient review from approving biological edges."""

import argparse
import importlib.util
import os
import py_compile
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/run_mim_reuse_canary.py"
SPEC = importlib.util.spec_from_file_location("mim_reuse_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


@pytest.fixture
def mapping():
    """Synthetic data exercise scope; these are not scientific approvals."""
    row = {
        "subject_id": "MIM:fixture",
        "predicate_id": "skos:exactMatch",
        "object_id": "CHEBI:15377",
        "other": "specific supplied form",
    }
    decision = {"row_sha256": canary.payload_digest(row), "disposition": "SUPPORTED"}
    dependency = "a" * 64
    request = {"kind": "mim_mapping_payload", "payload": row, "dependency_sha256": dependency}
    return row, decision, request, dependency


def test_exact_mapping_reuse_is_not_a_new_scientific_review(mapping):
    result = canary.classify_reuse(*mapping)
    assert result["eligible_for_reuse"] is True
    assert result["independent_scientific_review"] is False
    assert result["biological_claim_approved"] is False


def test_same_endpoint_does_not_approve_growth(mapping):
    row, decision, _, dependency = mapping
    request = {
        "kind": "biological_claim",
        "subject": "fixture:organism",
        "predicate": "fixture:grows_on",
        "object": row["object_id"],
        "dependency_sha256": dependency,
    }
    result = canary.classify_reuse(row, decision, request, dependency)
    assert result["outcome"] == "endpoint_only"
    assert result["eligible_for_reuse"] is False
    assert result["biological_claim_approved"] is False


def test_native_withhold_is_preserved_for_identical_payload(mapping):
    row, decision, request, dependency = mapping
    result = canary.classify_reuse(row, dict(decision, disposition="WITHHOLD"), request, dependency)
    assert result["outcome"] == "native_withheld_mapping"
    assert result["eligible_for_reuse"] is False


def test_same_triple_different_form_cannot_borrow_review(mapping):
    row, decision, request, dependency = mapping
    result = canary.classify_reuse(
        row, decision, dict(request, payload=dict(row, other="other form")), dependency
    )
    assert result["outcome"] == "scope_mismatch"
    assert result["eligible_for_reuse"] is False


def test_changed_evidence_dependency_invalidates_unchanged_mapping(mapping):
    row, decision, request, dependency = mapping
    result = canary.classify_reuse(
        row, decision, dict(request, dependency_sha256="b" * 64), dependency
    )
    assert result["outcome"] == "stale_dependencies"
    assert result["eligible_for_reuse"] is False


def test_receipt_is_complete_and_cannot_overwrite_existing_result(tmp_path):
    output = tmp_path / "receipt.json"
    report = {"status": "fixture", "actual_kg_edges_approved": 0}
    canary.publish_new(output, report)
    saved = output.read_bytes()
    assert canary.read_json(saved) == report
    with pytest.raises(FileExistsError):
        canary.publish_new(output, {"status": "replacement"})
    assert output.read_bytes() == saved
    assert list(tmp_path.glob(".mim-canary-*")) == []


@pytest.fixture
def runtime_args(tmp_path):
    """Tiny validator modules exercise imports only, never fabricate a scientific PASS."""
    root = tmp_path / "kg"
    for relative in canary.VALIDATORS.values():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic validator for runtime-origin tests.\n")
    for relative in ("kg_microbe/__init__.py", "kg_microbe/utils/__init__.py"):
        (root / relative).write_text("")
    # Real KG scripts is a namespace package; do not give this fixture an __init__.
    return argparse.Namespace(
        kg_root=root,
        kg_python=Path(sys.executable).absolute(),
        bundle=tmp_path / "unused-bundle",
        archive=tmp_path / "unused-archive",
        kg_manifest=tmp_path / "unused-manifest",
        output=tmp_path / "must-not-exist.json",
        runtime_probe=False,
    )


def test_child_uses_selected_checkout_instead_of_ambient_pythonpath(runtime_args, monkeypatch):
    foreign = runtime_args.kg_root.parent / "ambient"
    (foreign / "scripts").mkdir(parents=True)
    (foreign / "scripts/__init__.py").write_text("raise RuntimeError('ambient package imported')\n")
    monkeypatch.setenv("PYTHONPATH", str(foreign))
    report = canary.run_child(runtime_args, probe_only=True)
    provenance = report["runtime_provenance"]
    assert provenance["before"] == provenance["after"]
    interpreter = provenance["before"]["interpreter"]
    assert interpreter["executable"] == str(runtime_args.kg_python)
    assert interpreter["version"] == sys.version
    for name, relative in canary.VALIDATORS.items():
        actual = provenance["before"]["validators"][name]
        path = (runtime_args.kg_root / relative).resolve()
        assert actual == {
            "path": str(path),
            "spec_origin": str(path),
            "sha256": canary.digest(path.read_bytes()),
        }
    assert "status" not in report
    assert not runtime_args.output.exists()


def test_child_rejects_actual_foreign_validator_origins(runtime_args):
    foreign = runtime_args.kg_root.parent / "foreign-scripts"
    foreign.mkdir()
    for name in ("mim_reviewed_release.py", "refresh_reviewed_mim.py"):
        # Identical bytes isolate origin checking from the independent hash check.
        (foreign / name).write_bytes((runtime_args.kg_root / "scripts" / name).read_bytes())
    # Simulate a site/import hook installing a regular scripts package even though
    # the requested checkout contains the expected namespace-package source files.
    (runtime_args.kg_root / "kg_microbe/__init__.py").write_text(
        "import sys, types\n"
        "package = types.ModuleType('scripts')\n"
        f"package.__path__ = [{str(foreign)!r}]\n"
        "sys.modules['scripts'] = package\n"
    )
    with pytest.raises(subprocess.CalledProcessError) as failure:
        canary.run_child(runtime_args, probe_only=True)
    assert "Imported validator origin or source hash differs" in failure.value.stderr
    assert not runtime_args.output.exists()


def test_child_rejects_source_changed_during_import(runtime_args):
    changing = runtime_args.kg_root / "scripts/refresh_reviewed_mim.py"
    (runtime_args.kg_root / "kg_microbe/utils/review_claims.py").write_text(
        "from pathlib import Path\n"
        f"path = Path({str(changing)!r})\n"
        "path.write_text(path.read_text() + '# changed during import\\n')\n"
    )
    with pytest.raises(subprocess.CalledProcessError) as failure:
        canary.run_child(runtime_args, probe_only=True)
    assert "Imported validator origin or source hash differs" in failure.value.stderr
    assert not runtime_args.output.exists()


def test_source_changed_during_validation_is_rejected(runtime_args, monkeypatch):
    expected = canary.source_snapshot(runtime_args.kg_root)
    modules = {}
    for name, binding in expected["validators"].items():
        module = ModuleType(name)
        module.__file__ = binding["path"]
        module.__spec__ = SimpleNamespace(origin=binding["path"])
        modules[name] = module
    monkeypatch.setattr(canary.importlib, "import_module", modules.__getitem__)

    def changed_validation(args, loaded):
        assert loaded == modules
        path = args.kg_root / "scripts/refresh_reviewed_mim.py"
        path.write_text(path.read_text() + "# changed after validator import\n")
        return {}

    monkeypatch.setattr(canary, "validate_review", changed_validation)
    with pytest.raises(ValueError, match="Imported validator origin or source hash differs"):
        canary.validate(runtime_args, expected)
    assert not runtime_args.output.exists()


@pytest.mark.parametrize("changed", ["validator", "launcher"])
def test_parent_rejects_source_drift_after_child_returns(runtime_args, monkeypatch, changed):
    # Use a disposable launcher copy so the repository helper is never changed.
    launcher = runtime_args.kg_root.parent / "launcher.py"
    launcher.write_bytes(SCRIPT.read_bytes())
    monkeypatch.setattr(canary, "__file__", str(launcher))
    run = subprocess.run

    def changed_run(*args, **kwargs):
        result = run(*args, **kwargs)
        path = (
            launcher
            if changed == "launcher"
            else runtime_args.kg_root / next(iter(canary.VALIDATORS.values()))
        )
        path.write_text(path.read_text() + "# changed after child returned\n")
        return result

    monkeypatch.setattr(canary.subprocess, "run", changed_run)
    with pytest.raises(ValueError, match="source changed during execution"):
        canary.run_child(runtime_args, probe_only=True)
    assert not runtime_args.output.exists()


def test_child_reads_changed_source_despite_timestamp_valid_bytecode(runtime_args, monkeypatch):
    path = runtime_args.kg_root / "kg_microbe/utils/review_claims.py"
    old = "#" + "x" * 69 + "\n"
    new = "raise RuntimeError('fresh source was executed')\n".ljust(len(old) - 1) + "\n"
    assert len(old.encode()) == len(new.encode())
    path.write_text(old)
    original_stat = path.stat()
    py_compile.compile(
        str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP
    )
    path.write_text(new)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    # Remove ambient cache settings so the stale adjacent cache is the counterexample.
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    with pytest.raises(subprocess.CalledProcessError) as failure:
        canary.run_child(runtime_args, probe_only=True)
    assert "fresh source was executed" in failure.value.stderr
    assert not runtime_args.output.exists()


def test_runtime_rejects_a_different_interpreter(runtime_args):
    expected = canary.source_snapshot(runtime_args.kg_root)
    runtime = {
        "interpreter": {
            "executable": "/different/python",
            "version": sys.version,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        },
        "validators": {},
    }
    with pytest.raises(ValueError, match="unexpected Python interpreter"):
        canary.verify_runtime(runtime, runtime_args, expected)


def test_child_rejects_an_interpreter_wrapper_reporting_another_executable(runtime_args):
    wrapper = runtime_args.kg_root.parent / "python-wrapper"
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    wrapper.chmod(0o700)
    runtime_args.kg_python = wrapper
    with pytest.raises(subprocess.CalledProcessError) as failure:
        canary.run_child(runtime_args, probe_only=True)
    assert "unexpected Python interpreter" in failure.value.stderr
    assert not runtime_args.output.exists()
