"""
JustRunner Plugin for OpenClaw

This plugin enables OpenClaw agents to execute justfile recipes across
the three KG-Microbe repositories.
"""

import logging
import subprocess
from typing import Any, Dict, List, Optional

from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
)

logger = logging.getLogger(__name__)


class JustRunnerPlugin:
    """Plugin for executing justfile recipes in repositories."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the JustRunner plugin.

        Args:
            config: Plugin configuration
        """
        self.config = config or {}
        configured_recipes = self.config.get("allowed_recipes", [])
        if not isinstance(configured_recipes, (list, tuple, set)) or not all(
            isinstance(recipe, str) and recipe for recipe in configured_recipes
        ):
            raise ValueError("allowed_recipes must be a collection of recipe names")
        self.allowed_recipes = frozenset(configured_recipes)
        self.repository_settings = RepositorySettings.from_environment(self.config)
        # Retain this public attribute for compatibility, but expose only paths
        # which have passed configuration and Git identity validation.
        self.repo_paths = self.repository_settings.paths

    def execute_recipe(
        self,
        repo: str,
        recipe: str,
        args: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a justfile recipe in a specific repository.

        Args:
            repo: Repository name (culturemech, mediaingredientmech, communitymech)
            recipe: Recipe name to execute
            args: Optional arguments to pass to the recipe
            dry_run: If True, don't execute, just validate

        Returns:
            Dictionary with execution results
        """
        try:
            repo_path = self.repository_settings.get_target(repo).path
        except RepositoryConfigurationError as exc:
            return {
                "success": False,
                "error": str(exc),
                "repo": repo,
                "recipe": recipe,
            }

        # An absent allowlist deliberately permits nothing. Every executable
        # recipe must be explicitly authorized by the calling agent config.
        if recipe not in self.allowed_recipes:
            return {
                "success": False,
                "error": f"Recipe '{recipe}' is not allowed",
                "repo": repo,
                "recipe": recipe,
            }

        # Check if justfile exists
        justfile_path = repo_path / "justfile"
        if not justfile_path.exists():
            return {
                "success": False,
                "error": f"No justfile found in {repo_path}",
                "repo": repo,
                "recipe": recipe,
            }

        # Build command
        cmd = ["just", "-d", str(repo_path), recipe]
        if args:
            cmd.extend(args)

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "command": " ".join(cmd),
                "repo": repo,
                "recipe": recipe,
            }

        # Execute command
        logger.info(f"Executing: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": " ".join(cmd),
                "repo": repo,
                "recipe": recipe,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Command timed out after 5 minutes",
                "command": " ".join(cmd),
                "repo": repo,
                "recipe": recipe,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": " ".join(cmd),
                "repo": repo,
                "recipe": recipe,
            }

    def list_recipes(self, repo: str) -> Dict[str, Any]:
        """
        List available recipes in a repository's justfile.

        Args:
            repo: Repository name

        Returns:
            Dictionary with list of recipes and their descriptions
        """
        try:
            repo_path = self.repository_settings.get_target(repo).path
        except RepositoryConfigurationError as exc:
            return {
                "success": False,
                "error": str(exc),
            }
        cmd = ["just", "-d", str(repo_path), "--list"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            return {
                "success": result.returncode == 0,
                "recipes": result.stdout,
                "repo": repo,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "repo": repo,
            }

    def execute_multi_repo(
        self,
        recipe: str,
        repos: Optional[List[str]] = None,
        args: Optional[List[str]] = None,
        parallel: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the same recipe across multiple repositories.

        Args:
            recipe: Recipe name to execute
            repos: List of repository names (defaults to all)
            args: Optional arguments for the recipe
            parallel: If True, execute in parallel (not implemented yet)

        Returns:
            Dictionary with results from all repositories
        """
        if repos is None:
            repos = list(self.repository_settings.names)

        results = {}
        for repo in repos:
            results[repo] = self.execute_recipe(repo, recipe, args)

        return {
            "success": all(r.get("success", False) for r in results.values()),
            "results": results,
            "recipe": recipe,
        }


# Plugin registration for OpenClaw
def register_plugin():
    """Register the JustRunner plugin with OpenClaw."""
    return {
        "name": "just_runner",
        "version": "1.0.0",
        "class": JustRunnerPlugin,
        "description": "Execute justfile recipes across KG-Microbe repositories",
    }
