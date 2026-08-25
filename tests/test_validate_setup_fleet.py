"""Fleet-derived setup validation tests."""

import os
from pathlib import Path

import pytest
from git import Repo

import validate_setup
from kg_microbe_fleet import load_fleet_manifest


def _repository(path: Path, github_identity: str) -> Path:
    path.mkdir()
    repo = Repo.init(path)
    repo.create_remote("origin", f"https://github.com/{github_identity}.git")
    return path


def test_repository_validation_covers_manifest_fleet_and_checks_identity(
    tmp_path: Path,
) -> None:
    manifest = load_fleet_manifest()
    environ = {
        mech.environment_variable: str(
            _repository(tmp_path / key, mech.github)
        )
        for key, mech in manifest.mechs.items()
    }

    assert validate_setup.validate_repositories(manifest, environ) is True


def test_repository_validation_rejects_wrong_manifest_identity(
    tmp_path: Path,
    capsys,
) -> None:
    manifest = load_fleet_manifest()
    environ = {
        mech.environment_variable: str(
            _repository(
                tmp_path / key,
                (
                    "CultureBotAI/not-the-declared-repository"
                    if index == 0
                    else mech.github
                ),
            )
        )
        for index, (key, mech) in enumerate(manifest.mechs.items())
    }

    assert validate_setup.validate_repositories(manifest, environ) is False
    assert "origin identity mismatch" in capsys.readouterr().out


def test_environment_validation_derives_every_repository_root(capsys) -> None:
    manifest = load_fleet_manifest()
    environ = {
        "OPENCLAW_MODE": "local",
        "OPENCLAW_LOG_LEVEL": "INFO",
    }

    assert validate_setup.validate_environment(manifest, environ) is False
    output = capsys.readouterr().out
    for mech in manifest.mechs.values():
        assert f"{mech.environment_variable} NOT SET" in output


def test_setup_validator_contains_no_repository_environment_registry() -> None:
    source = Path(validate_setup.__file__).read_text(encoding="utf-8")
    for mech in load_fleet_manifest().mechs.values():
        assert mech.environment_variable not in source


def test_installation_validation_enforces_declared_minimum_versions(
    monkeypatch, capsys
) -> None:
    real_version = validate_setup.distribution_version

    def version_with_outdated_anthropic(distribution: str) -> str:
        if distribution == "anthropic":
            return "0.1.0"
        return real_version(distribution)

    monkeypatch.setattr(
        validate_setup, "distribution_version", version_with_outdated_anthropic
    )

    assert validate_setup.validate_installation() is False
    assert "anthropic v0.1.0 (required >= 0.85.0)" in capsys.readouterr().out


def test_agent_configuration_validation_rejects_invalid_yaml_and_shape(
    tmp_path: Path,
) -> None:
    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("agent: [\n", encoding="utf-8")
    wrong_shape = tmp_path / "wrong-shape.yaml"
    wrong_shape.write_text("agent: {}\ntasks: []\n", encoding="utf-8")

    assert "Unable to load agent" in validate_setup.agent_configuration_error(
        invalid_yaml
    )
    assert "tasks must be a mapping" in validate_setup.agent_configuration_error(
        wrong_shape
    )


def test_shipped_agent_configurations_are_parseable_and_structurally_valid(
    capsys,
) -> None:
    assert validate_setup.validate_agents() is True
    assert "Total agents:" in capsys.readouterr().out


def _setup_source_dotenv(tmp_path: Path, monkeypatch, document: str) -> Path:
    source_root = tmp_path / "source-checkout"
    source_root.mkdir()
    script = source_root / "validate_setup.py"
    script.write_text("# test path marker\n", encoding="utf-8")
    (source_root / ".env").write_text(document, encoding="utf-8")
    monkeypatch.setattr(validate_setup, "__file__", str(script))
    return source_root


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            'CULTUREMECH_ROOT=/parseable\nBROKEN="unterminated\n'
            "TRAITMECH_ROOT=/would-be-partial\n",
            "malformed at line 2",
        ),
        (
            "CULTUREMECH_ROOT=/first\nCULTUREMECH_ROOT=/second\n",
            "duplicate key 'CULTUREMECH_ROOT'",
        ),
    ],
)
def test_main_rejects_ambiguous_project_dotenv_before_validation(
    tmp_path, monkeypatch, capsys, document, message
) -> None:
    _setup_source_dotenv(tmp_path, monkeypatch, document)
    called = False

    def unexpected_validation():
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(validate_setup, "validate_installation", unexpected_validation)

    assert validate_setup.main() == 1
    output = capsys.readouterr().out
    assert message in output
    assert "ALL CHECKS PASSED" not in output
    assert called is False


def test_main_uses_one_export_precedence_environment_snapshot(
    tmp_path, monkeypatch
) -> None:
    manifest = load_fleet_manifest()
    first_variable = next(iter(manifest.mechs.values())).environment_variable
    _setup_source_dotenv(
        tmp_path,
        monkeypatch,
        f"{first_variable}=/from-dotenv\nOPENCLAW_MODE=from-dotenv\n",
    )
    monkeypatch.setenv(first_variable, "/from-export")
    snapshots = []

    def capture_environment(_manifest, environ):
        snapshots.append(environ)
        return True

    monkeypatch.setattr(validate_setup, "validate_installation", lambda: True)
    monkeypatch.setattr(validate_setup, "validate_environment", capture_environment)
    monkeypatch.setattr(validate_setup, "validate_repositories", capture_environment)
    for name in (
        "validate_structure",
        "validate_files",
        "validate_agents",
        "validate_plugins",
        "validate_cli",
    ):
        monkeypatch.setattr(validate_setup, name, lambda: True)

    assert validate_setup.main() == 0
    assert len(snapshots) == 2
    assert snapshots[0] is snapshots[1]
    assert snapshots[0][first_variable] == "/from-export"
    assert snapshots[0]["OPENCLAW_MODE"] == "from-dotenv"
    assert os.environ[first_variable] == "/from-export"
