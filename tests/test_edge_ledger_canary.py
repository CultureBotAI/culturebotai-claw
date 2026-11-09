"""Canary receipts identify the actual consumer runtime and refuse source drift (#763)."""

import hashlib
import importlib.util
import os
import py_compile
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/adhoc/run_edge_ledger_canary.py"
SPEC = importlib.util.spec_from_file_location("edge_ledger_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


def _shadow_package(directory, *, fails=False):
    package = directory / "kg_microbe_curation"
    package.mkdir(parents=True)
    for name in canary.RUNTIME_MODULES.values():
        (package / name).write_text(
            'raise RuntimeError("ambient shadow package was imported")\n'
            if fails
            else "# Wrong installed checkout.\n"
        )
    (package / "schema").mkdir()
    (package / "schema/bundle.json").write_text("{}\n")
    return directory


def test_exact_checkout_overrides_ambient_shadow_for_probe_and_cli(tmp_path, monkeypatch):
    """A real shadow package on inherited PYTHONPATH cannot supply consumer code."""
    shadow = _shadow_package(tmp_path / "shadow", fails=True)
    monkeypatch.setenv("PYTHONPATH", str(shadow))
    environment = canary._consumer_environment(ROOT)
    assert environment["PYTHONPATH"] == os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    observed = canary._probe(ROOT, environment)
    for name, relative in canary.RUNTIME_MODULES.items():
        path = ROOT / "src/kg_microbe_curation" / relative
        assert observed["modules"][name] == {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    schema = ROOT / "src/kg_microbe_curation/schema/bundle.json"
    assert observed["schema"] == {
        "path": str(schema.resolve()),
        "sha256": hashlib.sha256(schema.read_bytes()).hexdigest(),
    }
    assert observed["interpreter"]["version"] == sys.version
    result = subprocess.run(
        [sys.executable, "-m", "kg_microbe_curation", "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "validate-bundle" in result.stdout


def test_wrong_import_origin_is_rejected_before_any_canary_artifact(tmp_path, monkeypatch):
    """A genuine child import from another checkout cannot receive a successful receipt."""
    shadow = _shadow_package(tmp_path / "wrong-installation")
    environment = {**os.environ, "PYTHONPATH": str(shadow), "PYTHONDONTWRITEBYTECODE": "1"}
    observed = canary._run([sys.executable, str(SCRIPT), "--probe-runtime"], ROOT, env=environment)
    assert Path(observed["modules"]["kg_microbe_curation"]["path"]).is_relative_to(shadow)
    producer_root = tmp_path / "kg"
    (producer_root / "kg_microbe").mkdir(parents=True)
    (producer_root / "kg_microbe/edge_snapshot.py").write_text(
        'raise AssertionError("must not execute")\n'
    )
    source = tmp_path / "source-manifest.json"
    source.write_text("{}\n")
    output = tmp_path / "canary"
    monkeypatch.setattr(canary, "_consumer_environment", lambda root: environment)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--kg-root",
            str(producer_root),
            "--kg-python",
            sys.executable,
            "--snapshot-manifest",
            str(source),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(RuntimeError, match="outside the expected checkout"):
        canary.main()
    assert not output.exists()
    assert not (output / "receipt.json").exists()


@pytest.mark.parametrize("mismatch", ["interpreter", "schema", "digest"])
def test_probe_metadata_must_match_interpreter_schema_and_code(tmp_path, mismatch):
    """Origin checks cover interpreter selection and packaged schema as well as modules."""
    observed = deepcopy(canary._probe(ROOT, canary._consumer_environment(ROOT)))
    if mismatch == "interpreter":
        observed["interpreter"]["executable"] = str(tmp_path / "different-python")
    elif mismatch == "schema":
        other = tmp_path / "bundle.json"
        other.write_bytes((ROOT / "src/kg_microbe_curation/schema/bundle.json").read_bytes())
        observed["schema"]["path"] = str(other)
    else:
        observed["modules"]["kg_microbe_curation.ledger"]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="runtime verification failed"):
        canary._verify_runtime(observed, ROOT)


@pytest.mark.parametrize("changed", ["producer.py", "source-manifest.json", "launcher.py"])
def test_changed_direct_source_or_manifest_refuses_attestation(tmp_path, changed):
    """A post-run file hash cannot silently replace the identity bound before execution."""
    paths = [tmp_path / name for name in ("producer.py", "source-manifest.json", "launcher.py")]
    for path in paths:
        path.write_text("original\n")
    expected = {path: canary._hash(path) for path in paths}
    canary._verify_file_hashes(expected)
    (tmp_path / changed).write_text("changed after execution\n")
    with pytest.raises(RuntimeError, match="executed source changed"):
        canary._verify_file_hashes(expected)


@pytest.mark.parametrize("command", ["probe", "consumer"])
def test_every_child_reads_source_despite_timestamp_valid_bytecode(tmp_path, monkeypatch, command):
    """Both attestation probes and real CLI children must ignore stale caches (#813)."""
    root = tmp_path / "checkout"
    _shadow_package(root / "src")
    package = root / "src/kg_microbe_curation"
    (package / "__main__.py").write_text(
        "from . import identity\n"
        "if __name__ == '__main__':\n"
        "    print('{\"synthetic_probe_only\": true}')\n"
    )
    path = package / "identity.py"
    original = "#" + "x" * 69 + "\n"
    changed = "raise RuntimeError('changed source was executed')\n".ljust(len(original) - 1) + "\n"
    assert len(original.encode()) == len(changed.encode())
    path.write_text(original)
    original_stat = path.stat()
    py_compile.compile(
        str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP
    )
    path.write_text(changed)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    environment = canary._consumer_environment(root)
    with pytest.raises(RuntimeError, match="changed source was executed"):
        if command == "probe":
            canary._probe(root, environment)
        else:
            canary._run([sys.executable, "-m", "kg_microbe_curation"], root, env=environment)
