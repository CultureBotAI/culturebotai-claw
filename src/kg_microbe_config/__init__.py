"""Packaged OpenClaw configuration assets."""

from pathlib import Path


def default_config_path() -> Path:
    """Return the installed default orchestration configuration."""

    return Path(__file__).resolve().with_name("openclaw_config.yaml")
