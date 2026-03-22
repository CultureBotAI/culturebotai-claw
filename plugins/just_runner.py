"""
JustRunner Plugin for OpenClaw

This plugin enables OpenClaw agents to execute justfile recipes across
the three KG-Microbe repositories.
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

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
        self.allowed_recipes = self.config.get("allowed_recipes", [])
        self.repo_paths = self._load_repo_paths()

    def _load_repo_paths(self) -> Dict[str, Path]:
        """Load repository paths from environment variables."""
        return {
            "culturemech": Path(os.getenv("CULTUREMECH_ROOT", "")),
            "mediaingredientmech": Path(os.getenv("MEDIAINGREDIENTMECH_ROOT", "")),
            "communitymech": Path(os.getenv("COMMUNITYMECH_ROOT", "")),
        }

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
        # Validate repository
        if repo not in self.repo_paths:
            return {
                "success": False,
                "error": f"Unknown repository: {repo}",
                "repo": repo,
                "recipe": recipe,
            }

        repo_path = self.repo_paths[repo]
        if not repo_path.exists():
            return {
                "success": False,
                "error": f"Repository path does not exist: {repo_path}",
                "repo": repo,
                "recipe": recipe,
            }

        # Validate recipe is allowed (if allowlist is configured)
        if self.allowed_recipes and recipe not in self.allowed_recipes:
            logger.warning(f"Recipe '{recipe}' not in allowed list, proceeding anyway")

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
        if repo not in self.repo_paths:
            return {
                "success": False,
                "error": f"Unknown repository: {repo}",
            }

        repo_path = self.repo_paths[repo]
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
            repos = list(self.repo_paths.keys())

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
