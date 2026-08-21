"""Exit-status and validation tests for the public Click CLI."""

from click.testing import CliRunner
from git import Repo

from cli.main import cli


def test_missing_plugin_is_nonzero():
    result = CliRunner().invoke(cli, ["plugin", "test", "does-not-exist"])

    assert result.exit_code != 0
    assert "Plugin not found" in result.output


def test_unknown_agent_dry_run_is_nonzero():
    result = CliRunner().invoke(cli, ["agent", "run", "does-not-exist", "--dry-run"])

    assert result.exit_code != 0
    assert "Unknown or ambiguous agent" in result.output


def test_known_agent_dry_run_is_validated():
    result = CliRunner().invoke(cli, ["agent", "run", "validation_agent", "--dry-run"])

    assert result.exit_code == 0
    assert "validated validation_agent" in result.output


def test_unimplemented_agent_execution_is_nonzero():
    result = CliRunner().invoke(cli, ["agent", "run", "validation_agent"])

    assert result.exit_code != 0
    assert "not implemented" in result.output


def test_known_pipeline_dry_run_accepts_short_name():
    result = CliRunner().invoke(
        cli, ["pipeline", "run", "ingredient_curation", "--dry-run"]
    )

    assert result.exit_code == 0
    assert "ingredient_curation_pipeline.py" in result.output


def test_config_validate_rejects_malformed_yaml(tmp_path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text("repositories: [", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "Unable to load configuration" in result.output


def test_config_validate_accepts_verified_repository_roots(tmp_path, monkeypatch):
    repositories = {
        "culturemech": ("CULTUREMECH_ROOT", "CultureBotAI/CultureMech"),
        "mediaingredientmech": (
            "MEDIAINGREDIENTMECH_ROOT",
            "CultureBotAI/MediaIngredientMech",
        ),
        "communitymech": ("COMMUNITYMECH_ROOT", "CultureBotAI/CommunityMech"),
    }
    lines = ["repositories:"]
    for name, (environment_variable, identity) in repositories.items():
        path = tmp_path / name
        repo = Repo.init(path, mkdir=True)
        repo.create_remote("origin", f"https://github.com/{identity}.git")
        monkeypatch.setenv(environment_variable, str(path))
        lines.extend((f"  {name}:", f"    path: ${{{environment_variable}}}"))
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code == 0
    assert "Configuration is valid" in result.output


def test_config_validate_does_not_require_optional_api_key(tmp_path, monkeypatch):
    repositories = {
        "culturemech": ("CULTUREMECH_ROOT", "CultureBotAI/CultureMech"),
        "mediaingredientmech": (
            "MEDIAINGREDIENTMECH_ROOT",
            "CultureBotAI/MediaIngredientMech",
        ),
        "communitymech": ("COMMUNITYMECH_ROOT", "CultureBotAI/CommunityMech"),
    }
    lines = ["repositories:"]
    for name, (environment_variable, identity) in repositories.items():
        path = tmp_path / name
        repo = Repo.init(path, mkdir=True)
        repo.create_remote("origin", f"https://github.com/{identity}.git")
        monkeypatch.setenv(environment_variable, str(path))
        lines.extend((f"  {name}:", f"    path: ${{{environment_variable}}}"))
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code == 0



def test_cli_version_comes_from_project_metadata():
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_config_show_never_prints_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")

    result = CliRunner().invoke(cli, ["config", "show"])

    assert result.exit_code == 0
    assert "sk-ant-secret-value" not in result.output
    assert "configured" in result.output
