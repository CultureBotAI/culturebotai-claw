"""Exit-status and validation tests for the public Click CLI."""

from pathlib import Path

from click.testing import CliRunner
from git import Repo

from cli.main import cli


def _write_verified_config(tmp_path, monkeypatch, extra_lines=()):
    repositories = {
        "culturemech": ("CULTUREMECH_ROOT", "CultureBotAI/CultureMech"),
        "mediaingredientmech": (
            "MEDIAINGREDIENTMECH_ROOT",
            "CultureBotAI/MediaIngredientMech",
        ),
        "communitymech": ("COMMUNITYMECH_ROOT", "CultureBotAI/CommunityMech"),
    }
    lines = [*extra_lines, "repositories:"]
    for name, (environment_variable, identity) in repositories.items():
        path = tmp_path / name
        repo = Repo.init(path, mkdir=True)
        repo.create_remote("origin", f"https://github.com/{identity}.git")
        monkeypatch.setenv(environment_variable, str(path))
        lines.extend((f"  {name}:", f"    path: ${{{environment_variable}}}"))
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


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


def test_config_validate_rejects_unknown_top_level_key(tmp_path, monkeypatch):
    config_path = _write_verified_config(
        tmp_path, monkeypatch, extra_lines=("plugnis: {}",)
    )

    result = CliRunner().invoke(
        cli, ["config", "validate", "--config-file", str(config_path)]
    )

    assert result.exit_code != 0
    assert "Unknown top-level configuration keys: plugnis" in result.output


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


def test_status_does_not_report_an_unresolved_repository_as_verified(
    tmp_path, monkeypatch
):
    """`status` must assert membership in the validated set, not absence of an
    error.

    Its display list is a call-time manifest read while the registry is frozen
    at import, so the two can diverge. A key present only in the display list
    is in neither `errors` nor `paths`; inferring "verified" from absence of an
    error then reports a repository that was never resolved, never opened, and
    never identity-checked as good — fail-open in the preflight command.
    """

    from kg_microbe_fleet import load_fleet_manifest

    shipped = (
        Path(__file__).resolve().parents[1] / "conf" / "fleet.yaml"
    ).read_text(encoding="utf-8")
    # A repository the frozen DEFAULT_REPOSITORIES cannot know about.
    diverged = tmp_path / "fleet.yaml"
    diverged.write_text(
        shipped
        + "\n".join(
            [
                "  ghostmech:",
                "    display_name: GhostMech",
                "    github: CultureBotAI/GhostMech",
                "    environment_variable: GHOSTMECH_ROOT",
                "    vendored_role: spoke",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(diverged))
    for mech in load_fleet_manifest().mechs.values():
        monkeypatch.delenv(mech.environment_variable, raising=False)

    result = CliRunner().invoke(cli, ["status"])

    assert "GhostMech" in result.output, "the diverged key should be displayed"
    ghost_row = [line for line in result.output.splitlines() if "GhostMech" in line]
    assert ghost_row and "✓ Verified" not in ghost_row[0], (
        f"unresolved repository reported as verified: {ghost_row}"
    )
