"""Offline tests for the committed five-Mech vendored-governance audit."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

import pytest

from kg_microbe_governance import GovernanceError, load_governance_manifest
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    CanonicalFetchError,
    expand_target,
)
from kg_microbe_governance.fleet_audit import audit_fleet_pins

REF = "a" * 40


def _run(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()


def _asset_bytes(source: str) -> bytes:
    prefix = "src/kg_microbe_governance/"
    assert source.startswith(prefix)
    resource = files("kg_microbe_governance")
    for part in source.removeprefix(prefix).split("/"):
        resource = resource.joinpath(part)
    return resource.read_bytes()


def _manifest_bytes() -> bytes:
    return files("kg_microbe_governance").joinpath("vendored_artifacts.json").read_bytes()


def _fake_fetch(url: str) -> bytes:
    marker = f"/{REF}/"
    assert marker in url
    path = url.split(marker, 1)[1]
    if path == CANONICAL_MANIFEST_PATH:
        return _manifest_bytes()
    return _asset_bytes(path)


def _commit_as_origin_main(root: Path, message: str) -> str:
    _run(root, "add", "-A")
    _run(
        root,
        "-c",
        "user.name=Fleet Audit Test",
        "-c",
        "user.email=fleet-audit@example.invalid",
        "commit",
        "-qm",
        message,
    )
    head = _run(root, "rev-parse", "HEAD")
    _run(root, "update-ref", "refs/remotes/origin/main", head)
    return head


def _build_fleet(tmp_path: Path) -> dict[str, Path]:
    manifest = load_governance_manifest()
    roots: dict[str, Path] = {}
    for key, consumer in manifest.consumers.items():
        root = tmp_path / key
        root.mkdir()
        _run(root, "init", "-q")
        _run(
            root,
            "remote",
            "add",
            "origin",
            f"https://github.com/{consumer.github}.git",
        )
        for artifact in manifest.artifacts_for(consumer):
            target = root / expand_target(artifact, consumer)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_asset_bytes(artifact.source))
            target.chmod(artifact.mode)
        pin = root / manifest.pin_path
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_text(REF + "\n", encoding="ascii")
        pin.chmod(0o644)
        _commit_as_origin_main(root, "install governed files")
        roots[key] = root
    return roots


def _recording_fetch(
    calls: list[str], delegate: Callable[[str], bytes] = _fake_fetch
) -> Callable[[str], bytes]:
    def fetch(url: str) -> bytes:
        calls.append(url)
        return delegate(url)

    return fetch


def test_audit_accepts_exact_clean_merged_fleet_and_caches_canonical_fetches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _build_fleet(tmp_path)
    calls: list[str] = []
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "hostile-git-dir"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "hostile-worktree"))

    result = audit_fleet_pins(roots, REF, fetch=_recording_fetch(calls))

    assert result.ok
    assert result.issues == ()
    assert tuple(repository.key for repository in result.repositories) == tuple(roots)
    assert all(repository.head == repository.origin_main for repository in result.repositories)
    assert all(repository.pin == REF for repository in result.repositories)
    assert all(
        repository.checked_artifacts == repository.expected_artifacts
        for repository in result.repositories
    )
    assert result.for_repository("culturemech").checked_artifacts == 15
    protein = result.for_repository("proteintraitsmech")
    assert protein.checked_artifacts == 14
    assert not (protein.root / "scripts/_edison_capture.py").exists()
    assert len(calls) == len(set(calls))


def test_audit_requires_exact_root_key_set_before_inspection(tmp_path: Path) -> None:
    roots = _build_fleet(tmp_path)
    calls: list[str] = []
    roots.pop("proteintraitsmech")
    roots["unknownmech"] = tmp_path / "not-a-repository"

    result = audit_fleet_pins(roots, REF, fetch=_recording_fetch(calls))

    assert not result.ok
    assert result.repositories == ()
    assert result.fleet_issues[0].code == "root_set"
    assert "proteintraitsmech" in result.fleet_issues[0].message
    assert "unknownmech" in result.fleet_issues[0].message
    assert calls == []


def test_audit_rejects_wrong_origin_and_nested_root_without_fetching(
    tmp_path: Path,
) -> None:
    roots = _build_fleet(tmp_path)
    roots["culturemech"] = roots["traitmech"]
    nested = roots["communitymech"] / "nested"
    nested.mkdir()
    roots["communitymech"] = nested
    calls: list[str] = []

    result = audit_fleet_pins(roots, REF, fetch=_recording_fetch(calls))

    assert not result.ok
    assert result.for_repository("culturemech").issues[0].code == "repository"
    assert (
        "expected 'CultureBotAI/CultureMech'"
        in result.for_repository("culturemech").issues[0].message
    )
    assert result.for_repository("communitymech").issues[0].code == "repository"
    assert "exact Git worktree root" in result.for_repository("communitymech").issues[0].message
    assert calls == []


def test_audit_requires_clean_head_equal_to_origin_main_and_expected_pin(
    tmp_path: Path,
) -> None:
    roots = _build_fleet(tmp_path)
    (roots["culturemech"] / "untracked.txt").write_text("dirty\n")
    trait = roots["traitmech"]
    (trait / "tracked.txt").write_text("ahead\n")
    _run(trait, "add", "tracked.txt")
    _run(
        trait,
        "-c",
        "user.name=Fleet Audit Test",
        "-c",
        "user.email=fleet-audit@example.invalid",
        "commit",
        "-qm",
        "local commit not on origin main",
    )
    pin = roots["mediaingredientmech"] / "scripts/.vendored_canon_ref"
    pin.write_text("b" * 40 + "\n", encoding="ascii")
    _commit_as_origin_main(roots["mediaingredientmech"], "pin wrong claw revision")
    calls: list[str] = []

    result = audit_fleet_pins(roots, REF, fetch=_recording_fetch(calls))

    assert not result.ok
    assert result.for_repository("culturemech").issues[0].code == "worktree_not_clean"
    assert any(
        issue.code == "not_origin_main" for issue in result.for_repository("traitmech").issues
    )
    assert any(
        issue.code == "unexpected_pin"
        for issue in result.for_repository("mediaingredientmech").issues
    )
    assert calls == []


@pytest.mark.parametrize("content", ["main\n", "A" * 40 + "\n", REF + "\nextra\n"])
def test_audit_requires_strict_full_pin(
    tmp_path: Path,
    content: str,
) -> None:
    roots = _build_fleet(tmp_path)
    pin = roots["culturemech"] / "scripts/.vendored_canon_ref"
    pin.write_text(content, encoding="ascii")
    _commit_as_origin_main(roots["culturemech"], "commit malformed pin")

    result = audit_fleet_pins(roots, REF, fetch=_fake_fetch)

    assert not result.ok
    assert any(issue.code == "pin" for issue in result.for_repository("culturemech").issues)


def test_checker_reports_committed_byte_missing_and_owner_execute_drift(
    tmp_path: Path,
) -> None:
    roots = _build_fleet(tmp_path)
    culture = roots["culturemech"]
    (culture / "tests/test_provider_triage_contract.py").write_text("drift\n")
    (culture / "tests/test_skill_frontmatter.py").unlink()
    checker = culture / "scripts/check_vendored_sync.py"
    checker.chmod(0o755)
    _commit_as_origin_main(culture, "commit three governed-file failures")

    result = audit_fleet_pins(roots, REF, fetch=_fake_fetch)

    assert not result.ok
    culture_issues = result.for_repository("culturemech").issues
    assert {issue.code for issue in culture_issues} >= {
        "byte_drift",
        "missing",
        "owner_execute_mode",
    }
    assert all(
        repository.ok for repository in result.repositories if repository.key != "culturemech"
    )


def test_audit_rejects_ignored_canonical_worktree_file_missing_from_head(
    tmp_path: Path,
) -> None:
    roots = _build_fleet(tmp_path)
    culture = roots["culturemech"]
    relative = "tests/test_provider_triage_contract.py"
    exclude = culture / ".git/info/exclude"
    exclude.write_text(exclude.read_text() + relative + "\n")
    _run(culture, "rm", "--cached", relative)
    _commit_as_origin_main(culture, "remove governed path from committed tree")
    assert (culture / relative).is_file()
    assert _run(culture, "status", "--porcelain=v1", "--untracked-files=all") == ""

    result = audit_fleet_pins(roots, REF, fetch=_fake_fetch)

    assert not result.ok
    assert any(
        issue.code == "head_missing"
        for issue in result.for_repository("culturemech").issues
    )


def test_audit_compares_head_blob_even_when_skip_worktree_hides_drift(
    tmp_path: Path,
) -> None:
    roots = _build_fleet(tmp_path)
    culture = roots["culturemech"]
    relative = "tests/test_provider_triage_contract.py"
    target = culture / relative
    canonical = target.read_bytes()
    target.write_bytes(b"malicious committed bytes\n")
    _commit_as_origin_main(culture, "commit governed drift")
    target.write_bytes(canonical)
    _run(culture, "update-index", "--skip-worktree", relative)
    assert _run(culture, "status", "--porcelain=v1", "--untracked-files=all") == ""

    result = audit_fleet_pins(roots, REF, fetch=_fake_fetch)

    assert not result.ok
    assert any(
        issue.code == "head_byte_drift"
        for issue in result.for_repository("culturemech").issues
    )


def test_audit_ignores_local_git_replacement_objects(
    tmp_path: Path,
) -> None:
    roots = _build_fleet(tmp_path)
    culture = roots["culturemech"]
    good_head = _run(culture, "rev-parse", "HEAD")
    relative = "tests/test_provider_triage_contract.py"
    target = culture / relative
    canonical = target.read_bytes()
    target.write_bytes(b"malicious committed bytes\n")
    bad_head = _commit_as_origin_main(culture, "commit governed drift")
    _run(culture, "replace", bad_head, good_head)
    # With replacement processing enabled, this loads the canonical replacement
    # tree into both index and worktree while leaving the recorded HEAD SHA bad.
    _run(culture, "reset", "--hard", "HEAD")
    assert target.read_bytes() == canonical
    assert _run(culture, "status", "--porcelain=v1", "--untracked-files=all") == ""

    result = audit_fleet_pins(roots, REF, fetch=_fake_fetch)

    assert not result.ok
    assert any(
        issue.code in {"worktree_not_clean", "head_byte_drift"}
        for issue in result.for_repository("culturemech").issues
    )


def test_audit_binds_expected_ref_to_exact_installed_manifest_bytes(
    tmp_path: Path,
) -> None:
    roots = _build_fleet(tmp_path)

    def same_count_manifest_drift(url: str) -> bytes:
        marker = f"/{REF}/"
        path = url.split(marker, 1)[1]
        if path == CANONICAL_MANIFEST_PATH:
            document = json.loads(_manifest_bytes())
            document["artifacts"][0]["id"] = "renamed_vendored_checker"
            return json.dumps(document).encode()
        return _fake_fetch(url)

    result = audit_fleet_pins(roots, REF, fetch=same_count_manifest_drift)

    assert not result.ok
    assert all(
        repository.issues[0].code == "canonical_ref"
        for repository in result.repositories
    )


def test_fetch_failures_are_structured_and_never_call_a_provider(tmp_path: Path) -> None:
    roots = _build_fleet(tmp_path)
    calls: list[str] = []

    def unavailable(url: str) -> bytes:
        calls.append(url)
        raise CanonicalFetchError("offline fixture")

    result = audit_fleet_pins(roots, REF, fetch=unavailable)

    assert not result.ok
    assert all(repository.issues[0].code == "fetch" for repository in result.repositories)
    assert len(calls) == 1


def test_expected_ref_must_be_an_exact_lowercase_commit(tmp_path: Path) -> None:
    roots = _build_fleet(tmp_path)

    with pytest.raises(GovernanceError, match="40 lowercase hex"):
        audit_fleet_pins(roots, "main", fetch=_fake_fetch)


def test_audit_does_not_modify_repository_state(tmp_path: Path) -> None:
    roots = _build_fleet(tmp_path)
    before = {
        key: (
            _run(root, "rev-parse", "HEAD"),
            _run(root, "status", "--porcelain=v1", "--untracked-files=all"),
        )
        for key, root in roots.items()
    }

    result = audit_fleet_pins(roots, REF, fetch=_fake_fetch)

    after = {
        key: (
            _run(root, "rev-parse", "HEAD"),
            _run(root, "status", "--porcelain=v1", "--untracked-files=all"),
        )
        for key, root in roots.items()
    }
    assert result.ok
    assert after == before
    assert all(status == "" for _head, status in after.values())
