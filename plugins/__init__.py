"""
OpenClaw Plugins for KG-Microbe Orchestration

This package contains custom plugins that enable OpenClaw agents to interact
with existing KG-Microbe tools and infrastructure.
"""

from .just_runner import JustRunnerPlugin
from .linkml_validator import LinkMLValidatorPlugin
from .git_integration import GitIntegrationPlugin

__all__ = [
    "JustRunnerPlugin",
    "LinkMLValidatorPlugin",
    "GitIntegrationPlugin",
]
