"""Compatibility entry point for source checkouts.

Installed users should prefer the ``openclaw-cli`` console script.
"""

from cli.main import cli


if __name__ == "__main__":
    cli()
