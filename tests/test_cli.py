"""Exit-status and validation tests for the public Click CLI."""


import pytest
from click.testing import CliRunner
from git import Repo

from cli.main import _runtime_environment, cli
from kg_microbe_fleet import load_fleet_manifest
from plugins.repository_settings import RepositoryConfigurationError


def _write_verified_config(tmp_path, monkeypatch, extra_lines=()):
    manifest = load_fleet_manifest()
    for mech in manifest.mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    lines = [*extra_lines, "repositories:"]
    for name, mech in manifest.mechs.items():
        path = tmp_path / name
        repo = Repo.init(path, mkdir=True)
        repo.create_remote("origin", f"https://github.com/{mech.github}.git")
        monkeypatch.setenv(mech.environment_variable, str(path))
        lines.extend(
            (f"  {name}:", f"    path: ${{{mech.environment_variable}}}")
        )
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def test_missing_plugin_is_nonzero():
    result = CliRunner().invoke(cli, ["plugin", "test", "does-not-exist"])

    assert result.exit_code != 0
    assert "Plugin not found" in result.output


def test_runtime_environment_never_searches_callers_current_directory(
    tmp_path, monkeypatch
):
    variable = "UNRELATED_CALLER_DOTENV_SENTINEL"
    (tmp_path / ".env").write_text(f"{variable}=must-not-load\n", encoding="utf-8")
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(tmp_path)

    assert variable not in _runtime_environment()


def _project_dotenv(tmp_path, monkeypatch, text):
    import cli.main as main

    project_root = tmp_path / "source-checkout"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (project_root / ".env").write_text(text, encoding="utf-8")
    monkeypatch.setattr(main, "PROJECT_ROOT", project_root)
    return project_root


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
def test_runtime_environment_rejects_ambiguous_project_dotenv(
    tmp_path, monkeypatch, document, message
):
    _project_dotenv(tmp_path, monkeypatch, document)

    with pytest.raises(RepositoryConfigurationError, match=message):
        _runtime_environment()


def test_runtime_environment_gives_exported_values_precedence(tmp_path, monkeypatch):
    _project_dotenv(
        tmp_path,
        monkeypatch,
        "CULTUREMECH_ROOT=/from-dotenv\n",
    )
    monkeypatch.setenv("CULTUREMECH_ROOT", "/from-export")

    assert _runtime_environment()["CULTUREMECH_ROOT"] == "/from-export"


@pytest.mark.parametrize("command", [["config", "show"], ["status"]])
def test_read_only_cli_rejects_malformed_project_dotenv(
    tmp_path, monkeypatch, command
):
    _project_dotenv(
        tmp_path,
        monkeypatch,
        'CULTUREMECH_ROOT=/would-be-partial\nBROKEN="unterminated\n',
    )

    result = CliRunner().invoke(cli, command)

    assert result.exit_code != 0
    assert "dotenv file is malformed" in result.output
    assert "Verified" not in result.output


def test_config_validate_rejects_malformed_project_dotenv(
    tmp_path, monkeypatch
):
    _project_dotenv(
        tmp_path,
        monkeypatch,
        'CULTUREMECH_ROOT=/would-be-partial\nBROKEN="unterminated\n',
    )
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text("repositories: {}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "dotenv file is malformed" in result.output
    assert "Configuration is valid" not in result.output


def test_unknown_agent_dry_run_is_nonzero():
    result = CliRunner().invoke(cli, ["agent", "run", "does_not_exist", "--dry-run"])

    assert result.exit_code != 0
    assert "Unknown or ambiguous agent" in result.output


def test_agent_dry_run_rejects_glob_name_inference():
    result = CliRunner().invoke(cli, ["agent", "run", "v*", "--dry-run"])

    assert result.exit_code != 0
    assert "Invalid agent name" in result.output


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
    config_path = _write_verified_config(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code == 0
    assert "Configuration is valid" in result.output


def test_config_validate_does_not_require_optional_api_key(tmp_path, monkeypatch):
    config_path = _write_verified_config(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code == 0


def test_config_validate_rejects_unknown_top_level_key(tmp_path, monkeypatch):
    config_path = _write_verified_config(
        tmp_path, monkeypatch, extra_lines=("plugnis: {}",)
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "Unknown top-level configuration keys: plugnis" in result.output


def test_config_validate_rejects_unknown_nested_safety_key(tmp_path, monkeypatch):
    config_path = _write_verified_config(
        tmp_path,
        monkeypatch,
        extra_lines=("safety:", "  require_approval_fr: [git_push]"),
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "'safety' has unknown keys: require_approval_fr" in result.output


def test_config_validate_rejects_invalid_safety_types(tmp_path, monkeypatch):
    config_path = _write_verified_config(
        tmp_path,
        monkeypatch,
        extra_lines=("safety:", "  create_backups: yes-please"),
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "safety.create_backups" in result.output


def test_config_validate_rejects_nonfinite_and_out_of_range_policy_numbers(
    tmp_path, monkeypatch
):
    config_path = _write_verified_config(
        tmp_path,
        monkeypatch,
        extra_lines=(
            "monitoring:",
            "  max_cost_per_run: .nan",
            "performance:",
            "  parallel_agents: 0",
        ),
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "monitoring.max_cost_per_run" in result.output
    assert "performance.parallel_agents" in result.output


def test_config_validate_rejects_null_known_section(tmp_path, monkeypatch):
    config_path = _write_verified_config(
        tmp_path, monkeypatch, extra_lines=("plugins:",)
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "'plugins' must be a mapping" in result.output


def test_config_validate_rejects_invalid_pipeline_scalar(tmp_path, monkeypatch):
    config_path = _write_verified_config(
        tmp_path,
        monkeypatch,
        extra_lines=("pipelines:", "  unified:", "    batch_size: many"),
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "pipelines.unified.batch_size" in result.output


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


def _config_with_only(tmp_path, monkeypatch, keys):
    """Write a config naming only `keys`, with real verified worktrees."""
    from kg_microbe_fleet import load_fleet_manifest

    manifest = load_fleet_manifest()
    lines = ["repositories:"]
    for key in keys:
        mech = manifest.get(key)
        path = tmp_path / key
        repo = Repo.init(path, mkdir=True)
        repo.create_remote("origin", f"https://github.com/{mech.github}.git")
        monkeypatch.setenv(mech.environment_variable, str(path))
        lines.extend((f"  {key}:", f"    path: ${{{mech.environment_variable}}}"))
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def test_config_validate_reports_an_unconfigured_mech_without_failing(
    tmp_path, monkeypatch
):
    """Not having every Mech cloned is not a configuration defect.

    Before the fleet manifest, adding a repository to the registry made
    `validate` fail for anyone without that clone, because every per-repository
    error was folded into a hard failure.
    """
    from kg_microbe_fleet import load_fleet_manifest

    for mech in load_fleet_manifest().mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    config_path = _config_with_only(tmp_path, monkeypatch, ["culturemech"])

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code == 0
    assert "Not configured locally" in result.output
    assert "Configuration is valid" in result.output


def test_require_all_repositories_promotes_unconfigured_back_to_a_failure(
    tmp_path, monkeypatch
):
    from kg_microbe_fleet import load_fleet_manifest

    for mech in load_fleet_manifest().mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    config_path = _config_with_only(tmp_path, monkeypatch, ["culturemech"])

    result = CliRunner().invoke(
        cli,
        [
            "config",
            "validate",
            "--config-file",
            str(config_path),
            "--require-all-repositories",
        ],
    )

    assert result.exit_code != 0
    assert "not configured" in result.output


def test_config_validate_still_fails_on_a_genuinely_invalid_path(
    tmp_path, monkeypatch
):
    """The softening must not extend to a configured-but-untrustworthy repo."""
    from kg_microbe_fleet import load_fleet_manifest

    for mech in load_fleet_manifest().mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text(
        "repositories:\n  culturemech:\n    path: ${MISSING_ROOT}\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "unexpanded variable" in result.output


def test_status_does_not_report_an_unresolved_repository_as_verified(monkeypatch):
    """`status` must assert membership in the validated set, not absence of an
    error.

    `status` renders whatever settings it is handed. If a repository is in
    neither the error map nor the validated paths -- never resolved, never
    opened, never identity-checked -- inferring "verified" from the absence of
    an error would be fail-open in the preflight command.
    """

    import cli.main as main
    from plugins.repository_settings import RepositorySettings

    def _settings_that_resolved_nothing(*args, **kwargs):
        manifest = kwargs.get("manifest") or main.load_fleet_manifest()
        # No targets and no errors: every name is unaccounted for.
        return RepositorySettings({}, {}, tuple(manifest.keys))

    monkeypatch.setattr(
        main.RepositorySettings, "from_file", _settings_that_resolved_nothing
    )

    result = CliRunner().invoke(cli, ["status"])

    assert "✓ Verified" not in result.output, (
        "a repository that was never resolved was reported as verified:\n"
        f"{result.output}"
    )
    # Rich wraps cell text across lines, so compare on collapsed whitespace.
    collapsed = " ".join(result.output.split())
    assert "is missing from repository settings" in collapsed


def test_manifest_override_is_shared_by_registry_status_and_config_show(
    tmp_path, monkeypatch
):
    """A call-time override must not diverge from an import-time registry."""

    import copy

    import yaml

    from kg_microbe_fleet import default_manifest_path, load_fleet_manifest
    from plugins.repository_settings import RepositorySettings

    document = yaml.safe_load(default_manifest_path().read_text(encoding="utf-8"))
    ghost = copy.deepcopy(document["mechs"]["traitmech"])
    ghost.update(
        {
            "display_name": "GhostMech",
            "github": "CultureBotAI/GhostMech",
            "environment_variable": "GHOSTMECH_ROOT",
            "vendored_role": "consumer",
        }
    )
    document["mechs"]["ghostmech"] = ghost
    override = tmp_path / "fleet.yaml"
    override.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(override))
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment(environ={}, manifest=manifest)

    assert settings.names == manifest.keys
    assert "ghostmech" in settings.names
    show = CliRunner().invoke(cli, ["config", "show"])
    status = CliRunner().invoke(cli, ["status"])
    assert show.exit_code == 0 and "GHOSTMECH_ROOT" in show.output
    assert status.exit_code == 0 and "GhostMech" in status.output
