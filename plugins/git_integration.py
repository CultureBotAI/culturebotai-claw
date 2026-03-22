"""
Git Integration Plugin for OpenClaw

This plugin enables OpenClaw agents to perform safe git operations.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging
from git import Repo, GitCommandError

logger = logging.getLogger(__name__)


class GitIntegrationPlugin:
    """Plugin for safe git operations in repositories."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the Git Integration plugin.

        Args:
            config: Plugin configuration
        """
        self.config = config or {}
        self.auto_commit = self.config.get("auto_commit", False)
        self.branch_prefix = self.config.get("branch_prefix", "agent/")
        self.repo_paths = self._load_repo_paths()

    def _load_repo_paths(self) -> Dict[str, Path]:
        """Load repository paths from environment variables."""
        return {
            "culturemech": Path(os.getenv("CULTUREMECH_ROOT", "")),
            "mediaingredientmech": Path(os.getenv("MEDIAINGREDIENTMECH_ROOT", "")),
            "communitymech": Path(os.getenv("COMMUNITYMECH_ROOT", "")),
        }

    def _get_repo(self, repo_name: str) -> Optional[Repo]:
        """
        Get a GitPython Repo object for a repository.

        Args:
            repo_name: Repository name

        Returns:
            Repo object or None if not found
        """
        if repo_name not in self.repo_paths:
            logger.error(f"Unknown repository: {repo_name}")
            return None

        repo_path = self.repo_paths[repo_name]
        if not repo_path.exists():
            logger.error(f"Repository path does not exist: {repo_path}")
            return None

        try:
            return Repo(repo_path)
        except Exception as e:
            logger.error(f"Failed to open git repository at {repo_path}: {e}")
            return None

    def create_branch(
        self,
        repo_name: str,
        branch_name: str,
        from_branch: str = "main",
    ) -> Dict[str, Any]:
        """
        Create a new git branch.

        Args:
            repo_name: Repository name
            branch_name: Name for the new branch
            from_branch: Base branch to create from

        Returns:
            Dictionary with operation results
        """
        repo = self._get_repo(repo_name)
        if repo is None:
            return {"success": False, "error": "Failed to open repository"}

        # Add prefix if not already present
        if not branch_name.startswith(self.branch_prefix):
            branch_name = f"{self.branch_prefix}{branch_name}"

        try:
            # Check if branch already exists
            if branch_name in [b.name for b in repo.branches]:
                return {
                    "success": False,
                    "error": f"Branch already exists: {branch_name}",
                    "repo": repo_name,
                }

            # Create new branch
            new_branch = repo.create_head(branch_name, from_branch)
            new_branch.checkout()

            return {
                "success": True,
                "branch": branch_name,
                "repo": repo_name,
                "current_branch": repo.active_branch.name,
            }

        except GitCommandError as e:
            return {
                "success": False,
                "error": str(e),
                "repo": repo_name,
            }

    def get_status(self, repo_name: str) -> Dict[str, Any]:
        """
        Get git status for a repository.

        Args:
            repo_name: Repository name

        Returns:
            Dictionary with status information
        """
        repo = self._get_repo(repo_name)
        if repo is None:
            return {"success": False, "error": "Failed to open repository"}

        try:
            return {
                "success": True,
                "repo": repo_name,
                "branch": repo.active_branch.name,
                "is_dirty": repo.is_dirty(),
                "untracked_files": repo.untracked_files,
                "modified_files": [item.a_path for item in repo.index.diff(None)],
                "staged_files": [item.a_path for item in repo.index.diff("HEAD")],
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "repo": repo_name,
            }

    def commit_changes(
        self,
        repo_name: str,
        message: str,
        files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Commit changes to a repository.

        Args:
            repo_name: Repository name
            message: Commit message
            files: Optional list of files to commit (None = all changes)

        Returns:
            Dictionary with commit results
        """
        repo = self._get_repo(repo_name)
        if repo is None:
            return {"success": False, "error": "Failed to open repository"}

        try:
            # Add files
            if files:
                repo.index.add(files)
            else:
                repo.git.add(A=True)

            # Commit
            commit = repo.index.commit(message)

            return {
                "success": True,
                "repo": repo_name,
                "commit_sha": commit.hexsha[:8],
                "message": message,
                "files_changed": len(commit.stats.files),
            }

        except GitCommandError as e:
            return {
                "success": False,
                "error": str(e),
                "repo": repo_name,
            }

    def get_recent_commits(
        self,
        repo_name: str,
        count: int = 10,
        since: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get recent commits from a repository.

        Args:
            repo_name: Repository name
            count: Number of commits to retrieve
            since: Optional date/tag to get commits since

        Returns:
            Dictionary with commit information
        """
        repo = self._get_repo(repo_name)
        if repo is None:
            return {"success": False, "error": "Failed to open repository"}

        try:
            commits = []
            for commit in list(repo.iter_commits(max_count=count)):
                commits.append({
                    "sha": commit.hexsha[:8],
                    "author": str(commit.author),
                    "date": commit.committed_datetime.isoformat(),
                    "message": commit.message.strip(),
                })

            return {
                "success": True,
                "repo": repo_name,
                "commits": commits,
                "count": len(commits),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "repo": repo_name,
            }

    def get_diff(
        self,
        repo_name: str,
        commit1: Optional[str] = None,
        commit2: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get diff between commits or working directory.

        Args:
            repo_name: Repository name
            commit1: First commit (None = working directory)
            commit2: Second commit (None = HEAD)

        Returns:
            Dictionary with diff information
        """
        repo = self._get_repo(repo_name)
        if repo is None:
            return {"success": False, "error": "Failed to open repository"}

        try:
            if commit1 and commit2:
                diff = repo.git.diff(commit1, commit2)
            elif commit1:
                diff = repo.git.diff(commit1)
            else:
                diff = repo.git.diff()

            return {
                "success": True,
                "repo": repo_name,
                "diff": diff,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "repo": repo_name,
            }


# Plugin registration for OpenClaw
def register_plugin():
    """Register the Git Integration plugin with OpenClaw."""
    return {
        "name": "git_integration",
        "version": "1.0.0",
        "class": GitIntegrationPlugin,
        "description": "Safe git operations for agent-managed code changes",
    }
