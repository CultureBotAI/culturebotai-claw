"""Adversarial, offline regressions for vendored-governance trust boundaries."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

import kg_microbe_governance as governance
from kg_microbe_governance import GovernanceError, plan_sync, sync_repository
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    check_repository,
    parse_manifest,
    read_pin,
)

REF = "a" * 40
UNRELATED_REF = "b" * 40
CANONICAL_RAW_PREFIX = (
    "https://raw.githubusercontent.com/CultureBotAI/culturebotai-claw/"
)


def _manifest_bytes() -> bytes:
    return files("kg_microbe_governance").joinpath(
        "vendored_artifacts.json"
    ).read_bytes()


def _document() -> dict[str, Any]:
    return json.loads(_manifest_bytes())


def _asset_bytes(source: str) -> bytes:
    prefix = "src/kg_microbe_governance/"
    assert source.startswith(prefix)
    resource = files("kg_microbe_governance")
    for part in source.removeprefix(prefix).split("/"):
        resource = resource.joinpath(part)
    return resource.read_bytes()


def _offline_fetch(url: str) -> bytes:
    prefix = f"{CANONICAL_RAW_PREFIX}{REF}/"
    assert url.startswith(prefix), f"unexpected canonical URL: {url}"
    source = url.removeprefix(prefix)
    if source == CANONICAL_MANIFEST_PATH:
        return _manifest_bytes()
    return _asset_bytes(source)


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every package-level fetch must resolve from packaged bytes."""

    monkeypatch.setattr(governance, "fetch_url", _offline_fetch)


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _repository(root: Path, github: str) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "remote", "add", "origin", f"https://github.com/{github}.git")
    return root


def _write_pin(root: Path, ref: str = REF) -> Path:
    pin = root / "scripts/.vendored_canon_ref"
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text(ref + "\n")
    return pin


@pytest.mark.parametrize("mismatch", ["manifest", "artifact"])
def test_apply_rejects_unrelated_ref_package_mismatch_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    first_source = _document()["artifacts"][0]["source"]

    def mismatched_fetch(url: str) -> bytes:
        prefix = f"{CANONICAL_RAW_PREFIX}{UNRELATED_REF}/"
        assert url.startswith(prefix), f"unexpected canonical URL: {url}"
        source = url.removeprefix(prefix)
        if source == CANONICAL_MANIFEST_PATH:
            if mismatch == "manifest":
                document = _document()
                document["consumers"]["culturemech"]["package_path"] = (
                    "src/not_the_packaged_path"
                )
                return json.dumps(document, sort_keys=True).encode()
            return _manifest_bytes()
        if mismatch == "artifact" and source == first_source:
            return b"unrelated revision payload\n"
        return _asset_bytes(source)

    monkeypatch.setattr(governance, "fetch_url", mismatched_fetch)
    with pytest.raises(GovernanceError, match="manifest does not match|checksum drift"):
        sync_repository("culturemech", root, UNRELATED_REF, apply=True)

    assert not (root / "scripts").exists()
    assert not (root / "tests").exists()
    assert not (root / "src").exists()


@pytest.mark.parametrize("assertion_source", ["argument", "environment"])
def test_checker_uses_verified_origin_not_repository_assertion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assertion_source: str,
) -> None:
    root = _repository(tmp_path / "TraitMech", "CultureBotAI/TraitMech")
    _write_pin(root)

    repository: str | None = None
    if assertion_source == "argument":
        repository = "CultureBotAI/CultureMech"
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    else:
        monkeypatch.setenv("GITHUB_REPOSITORY", "CultureBotAI/CultureMech")

    with pytest.raises(GovernanceError, match="disagrees with origin"):
        check_repository(root, repository, fetch=_offline_fetch)


def test_checker_rejects_unknown_origin_even_with_valid_repository_hint(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path / "Impostor", "example/Impostor")
    _write_pin(root)

    with pytest.raises(GovernanceError, match="Unknown Mech repository identity"):
        check_repository(root, "culturemech", fetch=_offline_fetch)


def test_checker_rejects_nested_root_even_with_matching_environment_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    nested = root / "nested"
    nested.mkdir()
    monkeypatch.setenv("GITHUB_REPOSITORY", "CultureBotAI/CultureMech")

    with pytest.raises(GovernanceError, match="exact Git worktree root"):
        check_repository(nested, fetch=_offline_fetch)


def test_git_dir_and_work_tree_environment_cannot_reroute_repository_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intended = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    attacker = _repository(tmp_path / "TraitMech", "CultureBotAI/TraitMech")
    monkeypatch.setenv("GIT_DIR", str(attacker / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(attacker))

    changes = plan_sync("culturemech", intended, REF)

    assert len(changes) == 16
    assert not (intended / "scripts").exists()
    assert not (attacker / "scripts").exists()


def test_sanitized_git_environment_disables_replacements_and_lazy_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "/attacker")
    monkeypatch.setenv("GIT_NO_REPLACE_OBJECTS", "0")
    monkeypatch.setenv("GIT_NO_LAZY_FETCH", "0")

    environment = governance._git_environment()

    assert "GIT_DIR" not in environment
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_NO_LAZY_FETCH"] == "1"


@pytest.mark.parametrize("mismatch_location", ["fetch", "push"])
def test_every_origin_fetch_and_push_url_must_match(
    tmp_path: Path,
    mismatch_location: str,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    mismatch = "git@github.com:CultureBotAI/TraitMech.git"
    if mismatch_location == "fetch":
        _git(root, "remote", "set-url", "--add", "origin", mismatch)
    else:
        _git(
            root,
            "remote",
            "set-url",
            "--add",
            "--push",
            "origin",
            "ssh://git@github.com/CultureBotAI/CultureMech.git",
        )
        _git(
            root,
            "remote",
            "set-url",
            "--add",
            "--push",
            "origin",
            mismatch,
        )

    with pytest.raises(GovernanceError, match="Every origin fetch and push URL"):
        plan_sync("culturemech", root, REF)
    assert not (root / "scripts").exists()


def test_equivalent_origin_fetch_and_push_url_forms_are_accepted(tmp_path: Path) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    _git(
        root,
        "remote",
        "set-url",
        "--add",
        "origin",
        "git@github.com:CultureBotAI/CultureMech.git",
    )
    _git(
        root,
        "remote",
        "set-url",
        "--add",
        "--push",
        "origin",
        "ssh://git@github.com/CultureBotAI/CultureMech.git",
    )

    assert len(plan_sync("culturemech", root, REF)) == 16


@pytest.mark.parametrize(
    "alias",
    [
        "scripts//check_vendored_sync.py",
        "scripts/./check_vendored_sync.py",
        "scripts/check_vendored_sync.py/",
    ],
)
def test_manifest_rejects_noncanonical_path_aliases(alias: str) -> None:
    document = _document()
    document["artifacts"][0]["target"] = alias

    with pytest.raises(GovernanceError, match="safe canonical relative path"):
        parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize(
    "unsafe",
    ["scripts/file name.py", "scripts/file#fragment.py", "scripts/file%2falias.py"],
)
def test_manifest_rejects_paths_unsafe_for_git_or_canonical_urls(unsafe: str) -> None:
    document = _document()
    document["artifacts"][0]["target"] = unsafe

    with pytest.raises(GovernanceError, match="unsafe for Git and canonical URLs"):
        parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize(
    "target",
    [
        "scripts/.vendored_canon_ref",
        "scripts",
        "scripts/.vendored_canon_ref/descendant",
        "SCRIPTS/.VENDORED_CANON_REF",
    ],
)
def test_manifest_rejects_pin_equal_ancestor_descendant_and_casefold_conflicts(
    target: str,
) -> None:
    document = _document()
    document["artifacts"][0]["target"] = target

    with pytest.raises(GovernanceError, match="Conflicting targets"):
        parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize(
    "target",
    [
        "TESTS/TEST_PROVIDER_TRIAGE_CONTRACT.PY",
        "tests/test_provider_triage_contract.py/descendant",
        "tests",
    ],
)
def test_manifest_rejects_portable_artifact_target_conflicts(target: str) -> None:
    document = _document()
    document["artifacts"][6]["target"] = target

    with pytest.raises(GovernanceError, match="Conflicting targets"):
        parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pin", ".GiT/governance-pin"),
        ("target", ".GIT/hooks/check"),
        ("source", "src/kg_microbe_governance/artifacts/.git/payload"),
        ("package", "src/.gIt/culturemech"),
    ],
)
def test_manifest_rejects_git_metadata_in_every_path_kind(
    field: str,
    value: str,
) -> None:
    document = _document()
    if field == "pin":
        document["pin_path"] = value
    elif field == "package":
        document["consumers"]["culturemech"]["package_path"] = value
    else:
        document["artifacts"][0][field] = value

    with pytest.raises(GovernanceError, match="Git metadata"):
        parse_manifest(json.dumps(document).encode())


def test_apply_rejects_git_ignored_governed_target_without_writes(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    (root / ".git/info/exclude").write_text("scripts/\n")

    with pytest.raises(GovernanceError, match="ignored by Git"):
        sync_repository("culturemech", root, REF, apply=True)

    assert not (root / "scripts").exists()
    assert not (root / "tests").exists()
    assert not (root / "src").exists()


def test_apply_disables_configured_core_fsmonitor_hook(tmp_path: Path) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    marker = tmp_path / "fsmonitor-ran"
    hook = root / ".git/fsmonitor-adversarial"
    hook.write_text(
        "#!/bin/sh\n"
        f": > {shlex.quote(str(marker))}\n"
        "printf 'adversarial-token\\000'\n"
    )
    hook.chmod(0o755)
    _git(root, "config", "core.fsmonitor", str(hook))
    _git(root, "config", "core.fsmonitorHookVersion", "2")

    # Establish that this Git build executes the harmless hook when no command-line
    # override is present; otherwise the security assertion would be a false positive.
    _git(root, "status", "--porcelain=v1")
    if not marker.exists():
        pytest.skip("this Git build did not invoke the configured fsmonitor hook")
    marker.unlink()

    sync_repository("culturemech", root, REF, apply=True)

    assert not marker.exists()


@pytest.mark.parametrize(
    ("relative", "asymmetric_mode"),
    [
        ("scripts/check_vendored_sync.sh", 0o744),
        ("scripts/chem_formula.py", 0o655),
    ],
)
def test_artifact_mode_contract_tolerates_git_unrepresentable_safe_bits(
    tmp_path: Path,
    relative: str,
    asymmetric_mode: int,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    target = root / relative
    target.chmod(asymmetric_mode)

    changes = plan_sync("culturemech", root, REF)
    _checked, problems = check_repository(
        root,
        "culturemech",
        fetch=_offline_fetch,
    )

    assert all(change.path != relative for change in changes)
    assert all(not problem.startswith(f"MODE: {relative} ") for problem in problems)


@pytest.mark.parametrize(
    ("relative", "unsafe_mode"),
    [
        ("scripts/check_vendored_sync.sh", 0o775),
        ("scripts/check_vendored_sync.py", 0o664),
    ],
)
def test_artifact_mode_contract_rejects_group_or_other_writes(
    tmp_path: Path,
    relative: str,
    unsafe_mode: int,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    (root / relative).chmod(unsafe_mode)

    changes = plan_sync("culturemech", root, REF)
    _checked, problems = check_repository(
        root,
        "culturemech",
        fetch=_offline_fetch,
    )

    assert any(
        change.path == relative and "unsafe writable mode" in change.reason
        for change in changes
    )
    assert f"MODE: {relative} must not be group/other-writable" in problems


def test_pin_rejects_group_or_other_execute_bits(tmp_path: Path) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    pin = _write_pin(root)
    pin.chmod(0o654)

    with pytest.raises(GovernanceError, match="executable|mode"):
        read_pin(root)


def test_pin_rejects_group_or_other_writes(tmp_path: Path) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    pin = _write_pin(root)
    pin.chmod(0o664)

    with pytest.raises(GovernanceError, match="group/other-writable"):
        read_pin(root)


def test_pin_asymmetric_execute_bit_drift_is_reported_by_plan(tmp_path: Path) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    sync_repository("culturemech", root, REF, apply=True)
    pin = root / "scripts/.vendored_canon_ref"
    pin.chmod(0o654)

    changes = plan_sync("culturemech", root, REF)

    assert any(
        change.path == "scripts/.vendored_canon_ref" and "mode drift" in change.reason
        for change in changes
    )


def test_launcher_isolates_sibling_modules_and_fails_before_network(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    packaged_scripts = files("kg_microbe_governance").joinpath("artifacts/scripts")
    checker = scripts / "check_vendored_sync.py"
    launcher = scripts / "check_vendored_sync.sh"
    checker.write_bytes(packaged_scripts.joinpath(checker.name).read_bytes())
    launcher.write_bytes(packaged_scripts.joinpath(launcher.name).read_bytes())
    marker = tmp_path / "sibling-imported"
    (scripts / "argparse.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n"
        "raise RuntimeError('unsafe sibling import')\n"
    )

    result = subprocess.run(
        ["bash", str(launcher), "--root", str(tmp_path / "missing-root")],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "Repository root is unavailable" in result.stderr
    assert not marker.exists()


def test_apply_fails_closed_when_nofollow_flag_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    monkeypatch.delattr(governance.os, "O_NOFOLLOW")

    with pytest.raises(GovernanceError, match="Safe symlink-resistant apply.*O_NOFOLLOW"):
        sync_repository("culturemech", root, REF, apply=True)
    assert not (root / "scripts").exists()


def test_apply_fails_closed_when_required_dirfd_operation_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path / "CultureMech", "CultureBotAI/CultureMech")
    if os.rename not in os.supports_dir_fd:
        pytest.skip("os.rename already lacks dirfd support on this platform")
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd - {os.rename})

    with pytest.raises(GovernanceError, match="Safe symlink-resistant apply.*rename"):
        sync_repository("culturemech", root, REF, apply=True)
    assert not (root / "scripts").exists()
