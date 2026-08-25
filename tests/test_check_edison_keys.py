"""Offline safety tests for Edison credential discovery."""

from pathlib import Path

import pytest
from git import Repo

from kg_microbe_fleet import load_fleet_manifest
from plugins.repository_settings import RepositoryConfigurationError
from scripts import check_edison_keys


def _clear_edison_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = load_fleet_manifest()
    for variable in check_edison_keys.KEY_VARS:
        monkeypatch.delenv(variable, raising=False)
    for mech in manifest.mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)


def _repository(path: Path, github_identity: str) -> Path:
    path.mkdir()
    repo = Repo.init(path)
    repo.create_remote("origin", f"https://github.com/{github_identity}.git")
    return path


def test_discovery_uses_only_capability_enabled_configured_roots(
    tmp_path: Path,
) -> None:
    manifest = load_fleet_manifest()
    enabled_key = manifest.with_capability(
        check_edison_keys.EDISON_DISCOVERY_CAPABILITY
    )[0]
    disabled_key = next(
        key
        for key in manifest.keys
        if not manifest.get(key).supports(
            check_edison_keys.EDISON_DISCOVERY_CAPABILITY
        )
    )
    enabled = manifest.get(enabled_key)
    disabled = manifest.get(disabled_key)
    enabled_root = tmp_path / "enabled checkout in an arbitrary location"
    disabled_root = tmp_path / "not applicable checkout"
    _repository(enabled_root, enabled.github)
    disabled_root.mkdir()
    (enabled_root / ".env").write_text("EDISON_API_KEY=eligible-secret\n")
    (disabled_root / ".env").write_text("EDISON_API_KEY=excluded-secret\n")

    candidates = check_edison_keys.discover_candidates(
        manifest,
        {
            enabled.environment_variable: str(enabled_root),
            disabled.environment_variable: str(disabled_root),
        },
    )

    assert set(candidates) == {"eligible-secret"}
    assert candidates["eligible-secret"] == [
        f"{enabled.display_name}/.env:EDISON_API_KEY"
    ]


@pytest.mark.parametrize("arguments", [[], ["--no-network"]])
def test_default_and_explicit_discovery_modes_never_authenticate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    manifest = load_fleet_manifest()
    mech = manifest.get(
        manifest.with_capability(check_edison_keys.EDISON_DISCOVERY_CAPABILITY)[0]
    )
    root = tmp_path / "checkout"
    _repository(root, mech.github)
    (root / ".env").write_text("EDISON_API_KEY=discovery-only\n")
    _clear_edison_environment(monkeypatch)
    monkeypatch.setenv(mech.environment_variable, str(root))

    def unexpected_probe(*_args: object, **_kwargs: object) -> tuple[str, str]:
        pytest.fail("default Edison discovery attempted a network authentication")

    monkeypatch.setattr(check_edison_keys, "probe", unexpected_probe)

    assert check_edison_keys.main(arguments) == 0
    output = capsys.readouterr().out
    assert "Discovery-only mode" in output
    assert "no authentication requests" in output


def test_network_authentication_requires_explicit_apply_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_fleet_manifest()
    mech = manifest.get(
        manifest.with_capability(check_edison_keys.EDISON_DISCOVERY_CAPABILITY)[0]
    )
    root = tmp_path / "checkout"
    _repository(root, mech.github)
    (root / ".env").write_text("EDISON_API_KEY=explicit-network\n")
    _clear_edison_environment(monkeypatch)
    monkeypatch.setenv(mech.environment_variable, str(root))
    calls: list[tuple[str, str]] = []

    def fake_probe(base_url: str, api_key: str) -> tuple[str, str]:
        calls.append((base_url, api_key))
        return "VALID", "offline test double"

    monkeypatch.setattr(check_edison_keys, "probe", fake_probe)

    assert check_edison_keys.main(["--apply-network"]) == 0
    assert calls == [(check_edison_keys.STAGES["prod"], "explicit-network")]


def test_discovery_rejects_a_configured_wrong_repository(
    tmp_path: Path,
) -> None:
    manifest = load_fleet_manifest()
    mech = manifest.get(
        manifest.with_capability(check_edison_keys.EDISON_DISCOVERY_CAPABILITY)[0]
    )
    root = _repository(tmp_path / "wrong", "CultureBotAI/not-the-declared-repo")
    (root / ".env").write_text("EDISON_API_KEY=must-not-be-read\n")

    with pytest.raises(RepositoryConfigurationError, match="origin identity mismatch"):
        check_edison_keys.discover_candidates(
            manifest, {mech.environment_variable: str(root)}
        )
