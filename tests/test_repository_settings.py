"""Safety regression tests for cross-repository target selection."""

from pathlib import Path
from unittest.mock import patch

import pytest
from git import Repo

from plugins.git_integration import GitIntegrationPlugin
from plugins.ingredient_repo_synchronizer import IngredientRepoSynchronizer
from plugins.just_runner import JustRunnerPlugin
from plugins.linkml_validator import LinkMLValidatorPlugin
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
)

REPOSITORY_ENVIRONMENT_VARIABLES = (
    "CULTUREMECH_ROOT",
    "MEDIAINGREDIENTMECH_ROOT",
    "COMMUNITYMECH_ROOT",
)


def make_repository(path: Path, identity: str = "CultureBotAI/CultureMech") -> Repo:
    path.mkdir()
    repo = Repo.init(path)
    repo.create_remote("origin", f"https://github.com/{identity}.git")
    return repo


def clear_repository_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in REPOSITORY_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


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
