"""#687: legacy imports and CLI share the identified-source quote gate."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from plugins.repository_settings import RepositoryConfigurationError, RepositorySettings

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "scripts/validate_evidence_references.py"


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    return load_script(LEGACY, "legacy_evidence_fixture")


@pytest.fixture
def cache(tmp_path):
    directory = tmp_path / "references_cache"
    directory.mkdir()
    (directory / "PMID_123.md").write_text(
        "# PMID:123\n\n**Title:** Metadata alone must not validate.\n\n"
        "## Abstract\n\nMeasured growth increased in this strain.\n\n"
        "## Curator notes\nAnnotation alone must not validate.\n"
    )
    return directory


def test_legacy_proposal_reader_rejects_metadata_only_matches(legacy, cache, monkeypatch):
    legacy.CACHE_DIR = cache
    monkeypatch.setitem(sys.modules, "validate_evidence_references", legacy)
    proposals = load_script(ROOT / "scripts/apply_evidence_proposals.py", "proposal_reader_fixture")
    assert legacy.load_cache("123") == "Measured growth increased in this strain."
    assert proposals.validate_snippet("123", "MEASURED  growth increased")[0]
    assert not proposals.validate_snippet("123", "Metadata alone must not validate.")[0]
    assert not proposals.validate_snippet("123", "Annotation alone must not validate.")[0]
    assert legacy.normalize("Ａ  measured\nRESULT") == "a measured result"


@pytest.mark.parametrize("text", [
    "# PMID:999\n## Abstract\nMeasured growth increased.\n",
    "# PMID:123\nMeasured growth increased.\n",
    "# PMID:123\n## Abstract\nMeasured\n## Abstract\nGrowth\n",
])
def test_legacy_cache_api_does_not_promote_invalid_source(legacy, cache, text):
    legacy.CACHE_DIR = cache
    (cache / "PMID_123.md").write_text(text)
    assert legacy.load_cache("123") is None


def test_legacy_cache_api_rejects_missing_path_traversal_and_symlinks(legacy, cache, tmp_path):
    legacy.CACHE_DIR = cache
    assert legacy.load_cache("999") is None
    assert legacy.load_cache("../123") is None
    source = cache / "PMID_123.md"
    outside = tmp_path / "outside.md"
    source.rename(outside)
    source.symlink_to(outside)
    assert legacy.load_cache("123") is None


def test_legacy_import_is_lazy_and_unconfigured_lookup_never_guesses(tmp_path, monkeypatch):
    import kg_microbe_fleet.roots as roots

    for mech in load_fleet_manifest().mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    monkeypatch.setattr(roots, "claw_root", lambda: tmp_path / "claw")
    monkeypatch.setattr(sys, "path", list(sys.path))
    calls = []
    original = RepositorySettings.from_environment

    def observe(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(RepositorySettings, "from_environment", observe)
    # A plausible sibling cache must not be selected without configuration.
    guessed = tmp_path / "MediaIngredientMech/references_cache"
    guessed.mkdir(parents=True)
    (guessed / "PMID_123.md").write_text("# PMID:123\n## Abstract\nGuessing is wrong.\n")
    module = load_script(LEGACY, "legacy_unconfigured_fixture")
    assert calls == []
    assert module.MIM_ROOT is None and module.CACHE_DIR is None
    with pytest.raises(RepositoryConfigurationError, match="not configured"):
        module.load_cache("123")
    assert calls == [True]


def test_legacy_cli_delegates_flags_default_mech_and_failure(legacy, monkeypatch):
    import kg_microbe_evidence.__main__ as cli

    calls = []

    def observe(arguments):
        calls.append(arguments)
        return 2

    monkeypatch.setattr(cli, "main", observe)
    assert legacy.main(["--strict", "--root", "/explicit/worktree"]) == 2
    assert calls == [["--mech", "mediaingredientmech", "--strict", "--root", "/explicit/worktree"]]


def test_bound_old_adapter_reports_stay_in_its_active_worktree(legacy, cache, monkeypatch):
    root = cache.parent
    for arguments in [
        ["init", "-q"], ["config", "user.name", "Offline fixture"],
        ["config", "user.email", "fixture@example.invalid"],
        ["remote", "add", "origin", "https://github.com/CultureBotAI/MediaIngredientMech.git"],
        ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "fixture"],
    ]:
        subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)
    record = root / "data/ingredients/mapped/item.yaml"
    record.parent.mkdir(parents=True)
    record.write_text("ontology_mapping:\n  evidence:\n  - pmid: '123'\n    snippet: Measured growth increased\n")
    # These are the exact attributes the old downstream adapter binds. Output
    # sentinels stay import-compatible; the shared CLI owns output placement.
    legacy.MIM_ROOT = root
    legacy.CACHE_DIR = cache
    legacy.INGREDIENTS = root / "data/ingredients"
    legacy.OUT_DIR = root / "workspace/reports"
    legacy.OUT_TSV = legacy.OUT_DIR / "evidence_reference_validation.tsv"
    legacy.OUT_MD = legacy.OUT_DIR / "evidence_reference_validation.md"
    assert legacy.main(["--strict"]) == 0
    report = json.loads((legacy.OUT_DIR / "evidence_reference_validation.json").read_text())
    assert report["quote_validated_items"] == 1
    assert legacy.OUT_MD.is_file() and legacy.OUT_TSV.is_file()
    record.write_text("ontology_mapping:\n  evidence:\n  - pmid: '123'\n    snippet: Metadata alone must not validate.\n")
    assert legacy.main(["--strict"]) == 2


def test_legacy_cli_rejects_nonexistent_repair_mode(legacy):
    with pytest.raises(SystemExit) as failure:
        legacy.main(["--auto-repair", "--apply"])
    assert failure.value.code == 2
