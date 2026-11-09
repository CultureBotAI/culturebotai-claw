"""Minimal native packaging preserves canonical bytes and dependency separation (#1144)."""

import hashlib
import json
import runpy
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGER = runpy.run_path(str(ROOT / "scripts/adhoc/stage_curation_distribution_20261107.py"))
VERIFIER = runpy.run_path(str(ROOT / "scripts/adhoc/verify_curation_distribution_20261107.py"))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                    "https://github.com/CultureBotAI/culturebotai-claw.git"], check=True)
    for relative in STAGER["FILES"]:
        target = root / "src" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / "src" / relative).read_bytes())
    subprocess.run(["git", "-C", str(root), "add", "src"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Contract fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return root, commit


def test_staging_preserves_pinned_bytes_and_ignores_checkout_edits(source, tmp_path):
    root, commit = source
    original = (root / "src/kg_microbe_curation/identity.py").read_bytes()
    (root / "src/kg_microbe_curation/identity.py").write_text("uncommitted mutation")
    output = tmp_path / "stage"
    manifest = STAGER["stage"](root, commit, output)
    assert (output / "src/kg_microbe_curation/identity.py").read_bytes() == original
    assert manifest["source_commit"] == commit
    assert set(manifest["files"]) == set(STAGER["FILES"])
    for relative, digest in manifest["files"].items():
        assert hashlib.sha256((output / "src" / relative).read_bytes()).hexdigest() == digest
    assert json.loads((output / "staging-manifest.json").read_bytes()) == manifest
    project = tomllib.loads((output / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == ["jsonschema>=4,<5"]
    assert project["version"] == "0.1.0+g" + commit
    assert project["optional-dependencies"]["reviews"] == [
        "PyYAML>=6,<7", "linkml>=1.10,<1.11", "linkml-runtime>=1.10,<1.11"
    ]
    assert not project.get("scripts")


def test_staging_refuses_mutable_ref_and_existing_output(source, tmp_path):
    root, commit = source
    with pytest.raises(ValueError, match="complete lowercase"):
        STAGER["stage"](root, "HEAD", tmp_path / "mutable")
    output = tmp_path / "existing"
    output.mkdir()
    (output / "sentinel").write_text("preserve")
    with pytest.raises(ValueError, match="replace"):
        STAGER["stage"](root, commit, output)
    assert (output / "sentinel").read_text() == "preserve"


def test_staging_refuses_wrong_origin_and_symlink_parent(source, tmp_path):
    root, commit = source
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        STAGER["stage"](root, commit, alias / "stage")
    subprocess.run(["git", "-C", str(root), "remote", "set-url", "origin",
                    "https://example.invalid/other"], check=True)
    with pytest.raises(ValueError, match="canonical CLAW"):
        STAGER["stage"](root, commit, tmp_path / "wrong")


def test_staging_refuses_canonical_symlink_blob(source, tmp_path):
    root, _ = source
    path = root / "src/kg_microbe_curation/native.py"
    path.unlink()
    path.symlink_to("identity.py")
    subprocess.run(["git", "-C", str(root), "add", "src"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Contract fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Symlink fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    with pytest.raises(ValueError, match="regular source"):
        STAGER["stage"](root, commit, tmp_path / "wrong")
    assert not (tmp_path / "wrong").exists()


@pytest.fixture
def staged_installation(source, tmp_path, monkeypatch):
    root, commit = source
    output = tmp_path / "installed"
    manifest = STAGER["stage"](root, commit, output)
    metadata = VERIFIER["importlib"].metadata
    original = metadata.distribution

    class Distribution:
        version = manifest["version"]

        def locate_file(self, relative):
            return output / "src" / relative

    def distribution(name):
        if name == "kg-microbe-orchestration":
            raise metadata.PackageNotFoundError(name)
        if name == "kg-microbe-curation-contracts":
            return Distribution()
        return original(name)

    monkeypatch.setattr(metadata, "distribution", distribution)
    digest = hashlib.sha256((output / "staging-manifest.json").read_bytes()).hexdigest()
    return output, commit, digest


def test_installation_verifier_rejects_substituted_provenance(staged_installation):
    _, commit, _ = staged_installation
    with pytest.raises(ValueError, match="provenance differs"):
        VERIFIER["verify"](commit, "0" * 64)


def test_installation_verifier_rejects_changed_canonical_module(staged_installation):
    output, commit, digest = staged_installation
    (output / "src/kg_microbe_curation/native.py").write_text("substituted")
    with pytest.raises(ValueError, match="canonical contract bytes differ"):
        VERIFIER["verify"](commit, digest)


def test_installation_verifier_rejects_source_tree_shadowing(staged_installation):
    _, commit, digest = staged_installation
    with pytest.raises(ValueError, match="shadowed"):
        VERIFIER["verify"](commit, digest)


def test_installation_verifier_rejects_overlapping_distribution(monkeypatch):
    monkeypatch.setattr(VERIFIER["importlib"].metadata, "distribution", lambda name: object())
    with pytest.raises(ValueError, match="Overlapping"):
        VERIFIER["verify"]("a" * 40, "b" * 64)


@pytest.mark.parametrize("shadow", ["kg_microbe_reviews", "kg_microbe_governance.artifacts.scripts.record_review"])
def test_optional_review_support_module_shadowing_is_rejected(tmp_path, monkeypatch, shadow):
    files = {name: "a" * 64 for name in STAGER["FILES"]}

    class Distribution:
        def locate_file(self, relative):
            return tmp_path / "installed" / relative

    def imported(name):
        relative = next(path for path in files if path.endswith(".py") and (
            path.removesuffix("/__init__.py") if path.endswith("/__init__.py")
            else path.removesuffix(".py")
        ).replace("/", ".") == name)
        root = "shadow" if name == shadow else "installed"
        return SimpleNamespace(__file__=str(tmp_path / root / relative))

    monkeypatch.setattr(VERIFIER["importlib"], "import_module", imported)
    with pytest.raises(ValueError, match="shadowed"):
        VERIFIER["verify_import_origins"](Distribution(), files, reviews=True)


def test_native_only_and_review_modes_are_incompatible():
    with pytest.raises(ValueError, match="mutually exclusive"):
        VERIFIER["verify"]("a" * 40, "b" * 64, native_only=True, reviews=True)
