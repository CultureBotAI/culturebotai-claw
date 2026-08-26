"""Offline contracts for claw-authoritative vendored artifact governance."""

from __future__ import annotations

import json
import stat
import subprocess
from importlib.resources import files
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_governance import (
    GovernanceError,
    load_governance_manifest,
    plan_sync,
    sync_repository,
)
from kg_microbe_governance.__main__ import main
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    check_repository,
    parse_manifest,
    read_pin,
)

REF = "a" * 40


def _manifest_bytes() -> bytes:
    return files("kg_microbe_governance").joinpath(
        "vendored_artifacts.json"
    ).read_bytes()


def _document() -> dict[str, object]:
    return json.loads(_manifest_bytes())


def _asset_bytes(source: str) -> bytes:
    prefix = "src/kg_microbe_governance/"
    assert source.startswith(prefix)
    resource = files("kg_microbe_governance")
    for part in source.removeprefix(prefix).split("/"):
        resource = resource.joinpath(part)
    return resource.read_bytes()


def _fake_fetch(url: str) -> bytes:
    marker = f"/{REF}/"
    assert marker in url
    path = url.split(marker, 1)[1]
    if path == CANONICAL_MANIFEST_PATH:
        return _manifest_bytes()
    return _asset_bytes(path)


@pytest.fixture(autouse=True)
def _use_offline_canonical_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kg_microbe_governance.fetch_url", _fake_fetch)


def _repository(root: Path, github: str) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/{github}.git"],
        cwd=root,
        check=True,
    )
    return root


def test_shipped_manifest_is_complete_aligned_and_checksum_valid() -> None:
    manifest = load_governance_manifest()
    fleet = load_fleet_manifest()

    assert set(manifest.consumers) == set(fleet.keys)
    assert len(manifest.artifacts) == 14
    assert {
        artifact.artifact_id for artifact in manifest.artifacts
    } >= {
        "shared_mech_schema",
        "curation_history_schema",
        "provider_triage_contract",
        "edison_capture",
        "vendored_checker",
        "vendored_checker_launcher",
    }
    edison = next(
        artifact
        for artifact in manifest.artifacts
        if artifact.artifact_id == "edison_capture"
    )
    assert set(edison.consumers) == set(
        fleet.with_capability("edison_key_discovery")
    )


def test_downstream_targets_resolve_to_nested_canonical_payloads() -> None:
    """Keep Mech target names without recreating root compatibility copies."""
    artifacts = {
        artifact["id"]: artifact
        for artifact in _document()["artifacts"]
    }
    expected = {
        "id_label_validator": (
            "src/kg_microbe_governance/artifacts/scripts/validate_id_label_correspondence.py",
            "scripts/validate_id_label_correspondence.py",
        ),
        "chemical_formula_helper": (
            "src/kg_microbe_governance/artifacts/scripts/chem_formula.py",
            "scripts/chem_formula.py",
        ),
        "skill_frontmatter_contract": (
            "src/kg_microbe_governance/artifacts/tests/test_skill_frontmatter.py",
            "tests/test_skill_frontmatter.py",
        ),
        "backlog_loop_contract": (
            "src/kg_microbe_governance/artifacts/prompts/backlog-loop-goal.md",
            "prompts/backlog-loop-goal.md",
        ),
    }

    for artifact_id, (source, target) in expected.items():
        artifact = artifacts[artifact_id]
        assert artifact["source"] == source
        assert artifact["target"] == target
        assert _asset_bytes(source)


def test_manifest_rejects_duplicate_json_keys() -> None:
    with pytest.raises(GovernanceError, match="duplicate key 'version'"):
        parse_manifest(b'{"version":1,"version":1}')


@pytest.mark.parametrize("version", [True, 1.0, 2, "1"])
def test_manifest_rejects_non_exact_version(version: object) -> None:
    document = _document()
    document["version"] = version
    with pytest.raises(GovernanceError, match="version"):
        parse_manifest(json.dumps(document).encode())


def test_manifest_rejects_mech_as_canonical_authority() -> None:
    document = _document()
    document["canonical_repository"] = "CultureBotAI/CultureMech"
    with pytest.raises(GovernanceError, match="checker authority"):
        parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize("repository", ["CultureBotAI/.", "CultureBotAI/.."])
def test_manifest_rejects_consumer_path_segments(repository: str) -> None:
    document = _document()
    consumers = document["consumers"]
    assert isinstance(consumers, dict)
    consumers["culturemech"]["github"] = repository
    with pytest.raises(GovernanceError, match="owner/repository"):
        parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize("target", ["../outside", "/absolute", "scripts/*.py"])
def test_manifest_rejects_unsafe_targets(target: str) -> None:
    document = _document()
    artifacts = document["artifacts"]
    assert isinstance(artifacts, list)
    artifacts[0]["target"] = target
    with pytest.raises(
        GovernanceError,
        match="safe canonical relative path|unsafe for Git and canonical URLs",
    ):
        parse_manifest(json.dumps(document).encode())


def test_manifest_rejects_duplicate_expanded_targets() -> None:
    document = _document()
    artifacts = document["artifacts"]
    assert isinstance(artifacts, list)
    artifacts[1]["target"] = artifacts[0]["target"]
    with pytest.raises(GovernanceError, match="Conflicting targets"):
        parse_manifest(json.dumps(document).encode())


def test_packaged_loader_rejects_manifest_checksum_drift(tmp_path: Path) -> None:
    document = _document()
    artifacts = document["artifacts"]
    assert isinstance(artifacts, list)
    artifacts[0]["sha256"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document))
    with pytest.raises(GovernanceError, match="checksum drift"):
        load_governance_manifest(path)


@pytest.mark.parametrize(
    ("repository", "expected"),
    [("culturemech", 15), ("CultureBotAI/proteintraitsmech", 14)],
)
def test_sync_is_dry_run_by_default_then_applies_with_atomic_file_replacement(
    tmp_path: Path, repository: str, expected: int
) -> None:
    github = (
        "CultureBotAI/proteintraitsmech"
        if "proteintraitsmech" in repository.lower()
        else "CultureBotAI/CultureMech"
    )
    root = _repository(tmp_path / "Mech", github)

    changes = sync_repository(repository, root, REF)
    assert len(changes) == expected
    assert not (root / "scripts").exists()

    applied = sync_repository(repository, root, REF, apply=True)
    assert applied == changes
    assert plan_sync(repository, root, REF) == ()
    assert (root / "scripts/.vendored_canon_ref").read_text() == REF + "\n"
    checker = root / "scripts/check_vendored_sync.py"
    launcher = root / "scripts/check_vendored_sync.sh"
    assert not checker.stat().st_mode & stat.S_IXUSR
    assert launcher.stat().st_mode & stat.S_IXUSR
    if "proteintraitsmech" in repository.lower():
        assert not (root / "scripts/_edison_capture.py").exists()
    else:
        assert (root / "scripts/_edison_capture.py").is_file()


def test_sync_refuses_symlink_target_or_parent(tmp_path: Path) -> None:
    root = _repository(tmp_path / "Mech", "CultureBotAI/CultureMech")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "scripts").symlink_to(outside, target_is_directory=True)

    with pytest.raises(GovernanceError, match="symlink"):
        sync_repository("culturemech", root, REF, apply=True)
    assert list(outside.iterdir()) == []


def test_sync_rejects_wrong_origin_and_nested_directory(tmp_path: Path) -> None:
    wrong = _repository(tmp_path / "wrong", "CultureBotAI/TraitMech")
    with pytest.raises(GovernanceError, match="expected 'CultureBotAI/CultureMech'"):
        sync_repository("culturemech", wrong, REF, apply=True)
    assert not (wrong / "scripts").exists()

    correct = _repository(tmp_path / "correct", "CultureBotAI/CultureMech")
    nested = correct / "nested"
    nested.mkdir()
    with pytest.raises(GovernanceError, match="exact Git worktree root"):
        sync_repository("culturemech", nested, REF, apply=True)
    assert not (nested / "scripts").exists()


def test_apply_refuses_dirty_worktree_but_dry_run_remains_read_only(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path / "Mech", "CultureBotAI/CultureMech")
    (root / "user-note.txt").write_text("preserve me\n")
    assert plan_sync("culturemech", root, REF)
    with pytest.raises(GovernanceError, match="dirty target worktree"):
        sync_repository("culturemech", root, REF, apply=True)
    assert (root / "user-note.txt").read_text() == "preserve me\n"
    assert not (root / "scripts").exists()


def test_standalone_checker_uses_pin_and_remote_manifest_without_network(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path / "Mech", "CultureBotAI/proteintraitsmech")
    sync_repository("proteintraitsmech", root, REF, apply=True)

    checked, problems = check_repository(
        root, "CultureBotAI/proteintraitsmech", fetch=_fake_fetch
    )
    assert checked == 13
    assert problems == ()

    target = root / "tests/test_provider_triage_contract.py"
    target.write_text("drift\n")
    checked, problems = check_repository(
        root, "proteintraitsmech", fetch=_fake_fetch
    )
    assert checked == 13
    assert any("DRIFT: tests/test_provider_triage_contract.py" in item for item in problems)


@pytest.mark.parametrize(
    "content",
    ["", "main\n", "a" * 39 + "\n", "A" * 40 + "\n", REF + "\nextra\n"],
)
def test_pin_requires_one_full_lowercase_commit(tmp_path: Path, content: str) -> None:
    root = tmp_path / "Mech"
    pin = root / "scripts/.vendored_canon_ref"
    pin.parent.mkdir(parents=True)
    pin.write_text(content)
    with pytest.raises(GovernanceError, match="pin"):
        read_pin(root)


def test_cli_check_and_explicit_apply_contract(tmp_path: Path, capsys) -> None:
    root = _repository(tmp_path / "Mech", "CultureBotAI/CultureMech")

    assert main(
        [
            "sync",
            "--repository",
            "culturemech",
            "--target-root",
            str(root),
            "--ref",
            REF,
        ]
    ) == 0
    assert "WOULD_WRITE" in capsys.readouterr().out
    assert not (root / "scripts").exists()

    assert main(
        [
            "sync",
            "--repository",
            "culturemech",
            "--target-root",
            str(root),
            "--ref",
            REF,
            "--apply",
        ]
    ) == 0
    assert main(
        [
            "check",
            "--repository",
            "culturemech",
            "--target-root",
            str(root),
            "--ref",
            REF,
        ]
    ) == 0
    assert "OK:" in capsys.readouterr().out


def test_cli_failure_is_nonzero_and_does_not_mutate(tmp_path: Path, capsys) -> None:
    root = tmp_path / "Mech"
    root.mkdir()
    assert main(
        [
            "check",
            "--repository",
            "not-a-mech",
            "--target-root",
            str(root),
            "--ref",
            REF,
        ]
    ) == 2
    assert "Unknown Mech" in capsys.readouterr().err
    assert list(root.iterdir()) == []
