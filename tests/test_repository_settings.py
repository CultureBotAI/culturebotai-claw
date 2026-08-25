"""Safety regression tests for cross-repository target selection."""

from pathlib import Path
from unittest.mock import patch

import pytest
from git import Repo

from kg_microbe_fleet import load_fleet_manifest
from plugins.git_integration import GitIntegrationPlugin
from plugins.ingredient_repo_synchronizer import IngredientRepoSynchronizer
from plugins.just_runner import JustRunnerPlugin
from plugins.linkml_validator import LinkMLValidatorPlugin
from plugins.repository_settings import (
    DEFAULT_REPOSITORIES,
    RepositoryConfigurationError,
    RepositorySettings,
    merged_repository_environment,
)


def make_repository(path: Path, identity: str = "CultureBotAI/CultureMech") -> Repo:
    path.mkdir()
    repo = Repo.init(path)
    repo.create_remote("origin", f"https://github.com/{identity}.git")
    return repo


def clear_repository_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in load_fleet_manifest().environment_variables().values():
        monkeypatch.delenv(variable, raising=False)


def test_deprecated_default_repository_snapshot_remains_manifest_derived() -> None:
    manifest = load_fleet_manifest()

    assert tuple(DEFAULT_REPOSITORIES) == manifest.keys
    assert {
        key: definition.expected_repository
        for key, definition in DEFAULT_REPOSITORIES.items()
    } == {key: mech.github for key, mech in manifest.mechs.items()}


def test_explicit_dotenv_rejects_duplicate_keys(tmp_path: Path) -> None:
    dotenv = tmp_path / "duplicate.env"
    dotenv.write_text(
        "CULTUREMECH_ROOT=/first\nCULTUREMECH_ROOT=/second\n",
        encoding="utf-8",
    )

    with pytest.raises(RepositoryConfigurationError, match="duplicate key"):
        merged_repository_environment(dotenv, environ={})


def test_dotenv_preserves_nested_missing_variable_for_strict_resolution(
    tmp_path: Path,
) -> None:
    dotenv = tmp_path / "nested-missing.env"
    dotenv.write_text(
        "CULTUREMECH_ROOT=${MISSING_REPRO_VAR}/repo\n",
        encoding="utf-8",
    )

    environment = merged_repository_environment(dotenv, environ={})
    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "${CULTUREMECH_ROOT}"}}},
        environ=environment,
    )

    assert environment["CULTUREMECH_ROOT"] == "${MISSING_REPRO_VAR}/repo"
    assert "culturemech" in settings.invalid
    assert "culturemech" not in settings.paths
    assert "unexpanded variable" in settings.errors["culturemech"]


def test_nested_dotenv_expansion_uses_exported_value_at_every_level(
    tmp_path: Path,
) -> None:
    repo = make_repository(tmp_path / "exported-repo")
    dotenv = tmp_path / "nested.env"
    dotenv.write_text(
        "BASE_ROOT=/untrusted/dotenv/value\n"
        "INTERMEDIATE_ROOT=${BASE_ROOT}\n"
        "CULTUREMECH_ROOT=${INTERMEDIATE_ROOT}\n",
        encoding="utf-8",
    )

    environment = merged_repository_environment(
        dotenv,
        environ={"BASE_ROOT": repo.working_tree_dir},
    )
    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "${CULTUREMECH_ROOT}"}}},
        environ=environment,
    )

    assert settings.paths["culturemech"] == Path(repo.working_tree_dir).resolve()


def test_unset_path_never_falls_back_to_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong_repo = make_repository(
        tmp_path / "orchestration", "CultureBotAI/culturebotai-claw"
    )
    monkeypatch.chdir(wrong_repo.working_tree_dir)
    clear_repository_environment(monkeypatch)

    plugin = JustRunnerPlugin({"allowed_recipes": ["validate-all"]})
    result = plugin.execute_recipe("culturemech", "validate-all", dry_run=True)

    assert result["success"] is False
    assert "CULTUREMECH_ROOT" in result["error"]
    assert "culturemech" not in plugin.repo_paths


def test_validator_does_not_fall_back_to_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong_repo = make_repository(
        tmp_path / "orchestration", "CultureBotAI/culturebotai-claw"
    )
    monkeypatch.chdir(wrong_repo.working_tree_dir)
    clear_repository_environment(monkeypatch)

    result = LinkMLValidatorPlugin().validate_repository("culturemech")

    assert result["valid"] is False
    assert "CULTUREMECH_ROOT" in result["error"]


def test_wrong_git_identity_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong_repo = make_repository(tmp_path / "wrong", "CultureBotAI/culturebotai-claw")
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", wrong_repo.working_tree_dir)

    plugin = GitIntegrationPlugin()
    result = plugin.get_status("culturemech")

    assert result["success"] is False
    assert "origin identity mismatch" in result["error"]
    assert "culturemech" not in plugin.repo_paths
    assert (
        "origin identity mismatch" in plugin.repository_settings.errors["culturemech"]
    )


def test_repository_identity_requires_the_expected_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spoofed_repo = make_repository(tmp_path / "spoofed")
    spoofed_repo.remote("origin").set_url(
        "https://example.test/CultureBotAI/CultureMech.git"
    )
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", spoofed_repo.working_tree_dir)

    result = GitIntegrationPlugin().get_status("culturemech")

    assert result["success"] is False
    assert "origin identity mismatch" in result["error"]


@pytest.mark.parametrize(
    "remote_url",
    [
        "file://github.com/CultureBotAI/CultureMech.git",
        "ftp://github.com/CultureBotAI/CultureMech.git",
        "https://github.com/attacker/CultureBotAI/CultureMech.git",
        "https://github.com:8443/CultureBotAI/CultureMech.git",
    ],
)
def test_repository_identity_rejects_spoofed_url_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_url: str,
) -> None:
    repo = make_repository(tmp_path / "spoofed-form")
    repo.remote("origin").set_url(remote_url)
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)

    result = GitIntegrationPlugin().get_status("culturemech")

    assert result["success"] is False
    assert "unrecognizable URL" in result["error"]


def test_repository_identity_rejects_a_foreign_push_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repository(tmp_path / "push-spoofed")
    repo.git.config(
        "--add",
        "remote.origin.pushurl",
        "https://github.com/ExampleAttacker/not-culturemech.git",
    )
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)

    result = GitIntegrationPlugin().get_status("culturemech")

    assert result["success"] is False
    assert "origin identity mismatch for push" in result["error"]


def test_repository_identity_rejects_mixed_fetch_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repository(tmp_path / "mixed-fetch")
    repo.git.config(
        "--add",
        "remote.origin.url",
        "https://github.com/ExampleAttacker/not-culturemech.git",
    )
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)

    result = GitIntegrationPlugin().get_status("culturemech")

    assert result["success"] is False
    assert "origin identity mismatch for fetch" in result["error"]


def test_repository_identity_accepts_multiple_urls_only_when_all_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repository(tmp_path / "matching-urls")
    repo.git.config(
        "--add",
        "remote.origin.url",
        "git@github.com:CultureBotAI/CultureMech.git",
    )
    repo.git.config(
        "--add",
        "remote.origin.pushurl",
        "ssh://git@github.com/CultureBotAI/CultureMech.git",
    )
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)

    settings = RepositorySettings.from_environment(
        environ={"CULTUREMECH_ROOT": repo.working_tree_dir}
    )

    assert settings.paths["culturemech"] == Path(repo.working_tree_dir).resolve()


def test_repository_identity_is_revalidated_before_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repository(tmp_path / "culturemech")
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)
    plugin = GitIntegrationPlugin()
    assert "culturemech" in plugin.repo_paths

    repo.remote("origin").set_url(
        "https://github.com/CultureBotAI/culturebotai-claw.git"
    )
    result = plugin.get_status("culturemech")

    assert result["success"] is False
    assert "origin identity mismatch" in result["error"]


def test_unexpanded_repository_variable_is_rejected() -> None:
    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "${MISSING_ROOT}"}}},
        environ={},
    )

    assert "unexpanded variable" in settings.errors["culturemech"]
    with pytest.raises(RepositoryConfigurationError, match="unexpanded variable"):
        settings.get_target("culturemech")


def test_missing_own_root_plus_foreign_variable_is_a_fatal_defect() -> None:
    settings = RepositorySettings.from_environment(
        {
            "repositories": {
                "culturemech": {
                    "path": "${CULTUREMECH_ROOT}/${MISSPELLED_SUFFIX}"
                }
            }
        },
        environ={},
    )

    assert "culturemech" in settings.invalid
    assert "culturemech" not in settings.unconfigured
    assert "unexpanded variable" in settings.errors["culturemech"]


@pytest.mark.parametrize(
    "environment",
    [
        {"CULTUREMECH_ROOT": "${CULTUREMECH_ROOT}"},
        {
            "CULTUREMECH_ROOT": "${OTHER_ROOT}",
            "OTHER_ROOT": "${CULTUREMECH_ROOT}",
        },
    ],
)
def test_repository_variable_cycles_are_rejected(
    environment: dict[str, str],
) -> None:
    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "${CULTUREMECH_ROOT}"}}},
        environ=environment,
    )

    assert "cyclic variable expansion" in settings.errors["culturemech"]
    assert "culturemech" in settings.invalid


def test_repository_variable_expansion_depth_is_bounded() -> None:
    environment = {"CULTUREMECH_ROOT": "${EXPANSION_00}"}
    environment.update(
        {
            f"EXPANSION_{index:02d}": f"${{EXPANSION_{index + 1:02d}}}"
            for index in range(40)
        }
    )
    environment["EXPANSION_40"] = "/would/eventually/resolve"

    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "${CULTUREMECH_ROOT}"}}},
        environ=environment,
    )

    assert "exceeded 32" in settings.errors["culturemech"]
    assert "culturemech" in settings.invalid


def test_escaped_dollar_is_not_reexpanded(tmp_path: Path) -> None:
    target = RepositorySettings._resolve_target(
        name="culturemech",
        raw_path=f"{tmp_path}/$$literal",
        environment_variable="CULTUREMECH_ROOT",
        expected_repository="CultureBotAI/CultureMech",
        environ={"literal": "/unexpected/substitution"},
    )

    assert target.path == (tmp_path / "$literal").resolve()


def test_a_foreign_unexpanded_variable_is_a_defect_not_an_absent_checkout() -> None:
    """`${MISSING_ROOT}` is a typo or an undeclared dependency, so it must stay
    fatal rather than be excused as "you have not cloned this repository"."""

    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "${MISSING_ROOT}"}}},
        environ={},
    )

    assert "culturemech" not in settings.unconfigured
    assert "culturemech" in settings.invalid


def test_own_root_unset_reads_as_unconfigured_not_misconfigured() -> None:
    """`path: ${CULTUREMECH_ROOT}` with that variable unset means the
    repository is not set up here, which reaches the same state as an absent
    path by a different route."""

    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "${CULTUREMECH_ROOT}"}}},
        environ={},
    )

    assert "culturemech" in settings.unconfigured
    assert "culturemech" not in settings.invalid
    # Still reported, and still unusable: the distinction is for preflight
    # reporting only and must not open an access path.
    assert "not configured" in settings.errors["culturemech"]
    with pytest.raises(RepositoryConfigurationError, match="not configured"):
        settings.get_target("culturemech")


def test_an_absent_path_is_unconfigured_and_still_fails_closed() -> None:
    settings = RepositorySettings.from_environment({"repositories": {}}, environ={})

    assert "culturemech" in settings.unconfigured
    with pytest.raises(RepositoryConfigurationError):
        settings.open_repository("culturemech")


def test_relative_repository_path_is_rejected() -> None:
    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": "../CultureMech"}}},
        environ={},
    )

    assert "must be absolute" in settings.errors["culturemech"]


def test_repository_path_must_be_exact_worktree_root(tmp_path: Path) -> None:
    repo = make_repository(tmp_path / "culturemech")
    subdirectory = Path(repo.working_tree_dir) / "data"
    subdirectory.mkdir()
    settings = RepositorySettings.from_environment(
        {"repositories": {"culturemech": {"path": str(subdirectory)}}},
        environ={},
    )

    assert "Git repository" in settings.errors["culturemech"] or (
        "worktree root" in settings.errors["culturemech"]
    )


def test_disallowed_recipe_is_denied_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repository(tmp_path / "culturemech")
    (Path(repo.working_tree_dir) / "justfile").write_text(
        "validate-all:\n    @true\n", encoding="utf-8"
    )
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)
    plugin = JustRunnerPlugin({"allowed_recipes": ["validate-all"]})

    with patch("plugins.just_runner.subprocess.run") as run:
        result = plugin.execute_recipe("culturemech", "delete-everything")

    assert result == {
        "success": False,
        "error": "Recipe 'delete-everything' is not allowed",
        "repo": "culturemech",
        "recipe": "delete-everything",
    }
    run.assert_not_called()


def test_missing_allowlist_denies_every_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repository(tmp_path / "culturemech")
    (Path(repo.working_tree_dir) / "justfile").write_text(
        "validate-all:\n    @true\n", encoding="utf-8"
    )
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)

    result = JustRunnerPlugin().execute_recipe(
        "culturemech", "validate-all", dry_run=True
    )

    assert result["success"] is False
    assert result["error"] == "Recipe 'validate-all' is not allowed"


def test_synchronizer_rejects_missing_repository_roots(monkeypatch):
    clear_repository_environment(monkeypatch)

    with pytest.raises(RepositoryConfigurationError, match="CULTUREMECH_ROOT"):
        IngredientRepoSynchronizer()


def test_allowed_recipe_can_be_validated_in_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repository(tmp_path / "culturemech")
    (Path(repo.working_tree_dir) / "justfile").write_text(
        "validate-all:\n    @true\n", encoding="utf-8"
    )
    clear_repository_environment(monkeypatch)
    monkeypatch.setenv("CULTUREMECH_ROOT", repo.working_tree_dir)

    result = JustRunnerPlugin({"allowed_recipes": ["validate-all"]}).execute_recipe(
        "culturemech", "validate-all", dry_run=True
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert str(Path(repo.working_tree_dir)) in result["command"]


def test_settings_load_repository_section_from_yaml(tmp_path: Path) -> None:
    repo = make_repository(tmp_path / "culturemech")
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text(
        "repositories:\n" "  culturemech:\n" "    path: ${CULTUREMECH_ROOT}\n",
        encoding="utf-8",
    )

    settings = RepositorySettings.from_file(
        config_path, environ={"CULTUREMECH_ROOT": repo.working_tree_dir}
    )

    assert settings.paths["culturemech"] == Path(repo.working_tree_dir).resolve()
    assert "mediaingredientmech" in settings.errors


def test_malformed_yaml_configuration_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text("repositories: [", encoding="utf-8")

    with pytest.raises(RepositoryConfigurationError, match="Unable to load"):
        RepositorySettings.from_file(config_path, environ={})


def test_duplicate_repository_path_key_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text(
        "repositories:\n"
        "  culturemech:\n"
        "    path: ${CULTUREMECH_ROOT}\n"
        "    path: /different/checkout\n",
        encoding="utf-8",
    )

    with pytest.raises(RepositoryConfigurationError, match="duplicate key 'path'"):
        RepositorySettings.from_file(config_path, environ={})


def test_unknown_repository_configuration_key_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "openclaw.yaml"
    config_path.write_text(
        "repositories:\n"
        "  culturemech:\n"
        "    path: ${CULTUREMECH_ROOT}\n"
        "    pakage_manager: uv\n",
        encoding="utf-8",
    )

    with pytest.raises(RepositoryConfigurationError, match="pakage_manager"):
        RepositorySettings.from_file(config_path, environ={})
