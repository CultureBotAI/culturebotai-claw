"""Safety tests for the experimental unified ingredient pipeline."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from git import Repo

from pipelines.unified_ingredient_mapping_pipeline import (
    ApplyModeUnavailableError,
    UnifiedIngredientMappingPipeline,
)
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
)


def _repository(path, identity):
    repo = Repo.init(path, mkdir=True)
    repo.create_remote("origin", f"https://github.com/{identity}.git")
    return repo


def test_apply_mode_is_rejected_before_pipeline_side_effects():
    pipeline = object.__new__(UnifiedIngredientMappingPipeline)
    pipeline._revalidate_repository_targets = Mock()

    with pytest.raises(ApplyModeUnavailableError, match="not yet atomic"):
        pipeline.run(dry_run=False)

    pipeline._revalidate_repository_targets.assert_called_once_with()


def test_repository_identity_is_revalidated_at_run_time(tmp_path):
    culturemech = _repository(tmp_path / "culturemech", "CultureBotAI/CultureMech")
    mim = _repository(
        tmp_path / "mediaingredientmech", "CultureBotAI/MediaIngredientMech"
    )
    settings = RepositorySettings.from_environment(
        {
            "repositories": {
                "culturemech": {"path": culturemech.working_tree_dir},
                "mediaingredientmech": {"path": mim.working_tree_dir},
            }
        },
        environ={},
    )
    pipeline = object.__new__(UnifiedIngredientMappingPipeline)
    pipeline.repository_settings = settings
    pipeline.synchronizer = SimpleNamespace(repository_settings=settings)

    culturemech.remote("origin").set_url(
        "https://github.com/CultureBotAI/culturebotai-claw.git"
    )

    with pytest.raises(RepositoryConfigurationError, match="origin identity mismatch"):
        pipeline.run(dry_run=True)
