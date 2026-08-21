"""
LinkML Validator Plugin for OpenClaw

This plugin enables OpenClaw agents to validate YAML data against LinkML schemas.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
)

logger = logging.getLogger(__name__)


class LinkMLValidatorPlugin:
    """Plugin for validating YAML data against LinkML schemas."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the LinkML Validator plugin.

        Args:
            config: Plugin configuration
        """
        self.config = config or {}
        self.strict_mode = self.config.get("strict_mode", True)
        self.validate_imports = self.config.get("validate_imports", True)
        self.repository_settings = RepositorySettings.from_environment(self.config)
        self.repo_paths = self.repository_settings.paths

    def validate_data(
        self,
        data_path: Path,
        schema_path: Path,
        target_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate a YAML data file against a LinkML schema.

        Args:
            data_path: Path to the YAML data file
            schema_path: Path to the LinkML schema file
            target_class: Optional target class for validation

        Returns:
            Dictionary with validation results
        """
        if not data_path.exists():
            return {
                "valid": False,
                "error": f"Data file does not exist: {data_path}",
            }

        if not schema_path.exists():
            return {
                "valid": False,
                "error": f"Schema file does not exist: {schema_path}",
            }

        # Build linkml-validate command
        cmd = ["linkml-validate", "-s", str(schema_path), str(data_path)]

        if target_class:
            cmd.extend(["-C", target_class])

        logger.info(f"Running LinkML validation: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            return {
                "valid": result.returncode == 0,
                "data_path": str(data_path),
                "schema_path": str(schema_path),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "valid": False,
                "error": "Validation timed out",
                "data_path": str(data_path),
                "schema_path": str(schema_path),
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "data_path": str(data_path),
                "schema_path": str(schema_path),
            }

    def validate_repository(
        self,
        repo: str,
        data_pattern: str = "**/*.yaml",
    ) -> Dict[str, Any]:
        """
        Validate all YAML files in a repository against its schema.

        Args:
            repo: Repository name
            data_pattern: Glob pattern for data files

        Returns:
            Dictionary with validation results for all files
        """
        try:
            repo_path = self.repository_settings.get_target(repo).path
        except RepositoryConfigurationError as exc:
            return {
                "valid": False,
                "error": str(exc),
            }

        # Find schema file
        schema_path = repo_path / "src" / "schema" / f"{repo}.yaml"
        if not schema_path.exists():
            # Try alternative schema locations
            schema_candidates = list(repo_path.glob("src/schema/*.yaml"))
            if not schema_candidates:
                return {
                    "valid": False,
                    "error": f"No schema found in {repo_path}/src/schema/",
                    "repo": repo,
                }
            schema_path = schema_candidates[0]

        # Find data files (typically in data/ directory)
        data_dir = repo_path / "data"
        if not data_dir.exists():
            return {
                "valid": False,
                "error": f"Data directory does not exist: {data_dir}",
                "repo": repo,
            }

        data_files = list(data_dir.glob(data_pattern))

        results: Dict[str, Any] = {
            "repo": repo,
            "schema": str(schema_path),
            "total_files": len(data_files),
            "files": {},
            "valid": True,
        }

        for data_file in data_files:
            file_result = self.validate_data(data_file, schema_path)
            results["files"][str(data_file)] = file_result

            if not file_result.get("valid", False):
                results["valid"] = False

        return results

    def validate_schema(self, schema_path: Path) -> Dict[str, Any]:
        """
        Validate a LinkML schema itself.

        Args:
            schema_path: Path to the schema file

        Returns:
            Dictionary with schema validation results
        """
        if not schema_path.exists():
            return {
                "valid": False,
                "error": f"Schema file does not exist: {schema_path}",
            }

        cmd = ["linkml-lint", str(schema_path)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "valid": result.returncode == 0,
                "schema_path": str(schema_path),
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except FileNotFoundError:
            # linkml-lint might not be installed, try gen-python instead
            cmd = ["gen-python", str(schema_path)]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return {
                    "valid": result.returncode == 0,
                    "schema_path": str(schema_path),
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "note": "Validated by attempting to generate Python",
                }
            except Exception as e:
                return {
                    "valid": False,
                    "error": str(e),
                    "schema_path": str(schema_path),
                }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "schema_path": str(schema_path),
            }


# Plugin registration for OpenClaw
def register_plugin():
    """Register the LinkML Validator plugin with OpenClaw."""
    return {
        "name": "linkml_validator",
        "version": "1.0.0",
        "class": LinkMLValidatorPlugin,
        "description": "Validate YAML data against LinkML schemas",
    }
