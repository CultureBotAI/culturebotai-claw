#!/usr/bin/env python3
"""
Setup Validation Script for KG-Microbe OpenClaw Orchestration

Run this script to verify that the orchestration layer is properly installed
and configured.
"""

from __future__ import annotations

import importlib
import os
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Mapping

from packaging.version import InvalidVersion, Version

from kg_microbe_agents import (
    AgentDefinitionError,
    agents_root,
    load_agent_definition,
    load_agent_definitions,
)
from kg_microbe_config import default_config_path
from kg_microbe_fleet import FleetManifest, FleetManifestError, load_fleet_manifest
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
    merged_repository_environment,
)


def print_header(text):
    """Print a formatted header."""
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print('=' * 70)

def check_mark(passed):
    """Return checkmark or X."""
    return "✓" if passed else "✗"

def validate_installation():
    """Validate Python packages are installed."""
    print_header("1. Package Installation")

    packages = [
        ("cli.main", "kg-microbe-orchestration", "0.1.0", "orchestration"),
        ("anthropic", "anthropic", "0.85.0", "anthropic"),
        ("click", "click", "8.3.1", "click"),
        ("rich", "rich", "14.3.3", "rich"),
        ("git", "gitpython", "3.1.46", "GitPython"),
        ("yaml", "PyYAML", "6.0.3", "PyYAML"),
        ("watchdog", "watchdog", "6.0.0", "watchdog"),
        ("dotenv", "python-dotenv", "1.2.2", "python-dotenv"),
    ]

    all_passed = True
    for module_name, distribution_name, min_version, label in packages:
        try:
            importlib.import_module(module_name)
            installed = distribution_version(distribution_name)
            meets_minimum = Version(installed) >= Version(min_version)
            print(
                f"  {check_mark(meets_minimum)} {label} v{installed} "
                f"(required >= {min_version})"
            )
            all_passed = all_passed and meets_minimum
        except (ImportError, PackageNotFoundError):
            print(f"  {check_mark(False)} {label} NOT INSTALLED")
            all_passed = False
        except InvalidVersion as exc:
            print(f"  {check_mark(False)} {label} has invalid version metadata: {exc}")
            all_passed = False

    return all_passed

def validate_environment(
    manifest: FleetManifest | None = None,
    environ: Mapping[str, str] | None = None,
):
    """Validate environment variables."""
    print_header("2. Environment Configuration")

    manifest = manifest or load_fleet_manifest()
    env = os.environ if environ is None else environ

    runtime_vars = [
        "OPENCLAW_MODE",
        "OPENCLAW_LOG_LEVEL",
    ]
    repository_vars = [
        mech.environment_variable for mech in manifest.mechs.values()
    ]

    optional_vars = [
        "ANTHROPIC_API_KEY",
    ]

    all_passed = True

    print("\n  Fleet Repository Roots:")
    for var in repository_vars:
        value = env.get(var)
        if value:
            print(f"  {check_mark(True)} {var} = {value[:50]}...")
        else:
            print(f"  {check_mark(False)} {var} NOT SET")
            all_passed = False

    print("\n  Required Runtime Variables:")
    for var in runtime_vars:
        value = env.get(var)
        if value:
            print(f"  {check_mark(True)} {var} = {value[:50]}...")
        else:
            print(f"  {check_mark(False)} {var} NOT SET")
            all_passed = False

    print("\n  Optional Variables:")
    for var in optional_vars:
        value = env.get(var)
        if value:
            if "KEY" in var or "SECRET" in var:
                print(f"  {check_mark(True)} {var} = {'*' * 20}... (hidden)")
            else:
                print(f"  {check_mark(True)} {var} = {value[:50]}...")
        else:
            print(f"  {check_mark(False)} {var} NOT SET (optional)")

    return all_passed

def validate_repositories(
    manifest: FleetManifest | None = None,
    environ: Mapping[str, str] | None = None,
):
    """Validate every manifest repository's checkout and GitHub identity."""
    print_header("3. Repository Paths")

    manifest = manifest or load_fleet_manifest()
    settings = RepositorySettings.from_environment(
        environ=environ,
        manifest=manifest,
    )

    all_passed = True
    for key, mech in manifest.mechs.items():
        if key in settings.unconfigured:
            print(
                f"  {check_mark(False)} {mech.display_name}: not configured; "
                f"set {mech.environment_variable}"
            )
            all_passed = False
            continue
        if key in settings.invalid:
            print(f"  {check_mark(False)} {mech.display_name}: {settings.invalid[key]}")
            all_passed = False
            continue

        target = settings.get_target(key)
        print(
            f"  {check_mark(True)} {mech.display_name}: {target.path} "
            f"(origin {mech.github})"
        )

    return all_passed

def validate_structure():
    """Validate directory structure."""
    print_header("4. Directory Structure")

    base_dir = Path(__file__).parent

    required_dirs = [
        "src/kg_microbe_agents/definitions",
        "plugins",
        "pipelines",
        "cli",
        "workspace",
    ]

    all_passed = True
    for dir_path in required_dirs:
        full_path = base_dir / dir_path
        exists = full_path.exists()
        print(f"  {check_mark(exists)} {dir_path}/")
        if not exists:
            all_passed = False

    return all_passed

def validate_files():
    """Validate required files exist."""
    print_header("5. Configuration Files")

    base_dir = Path(__file__).parent

    required_files = [
        ".env.example",
        "pyproject.toml",
        "README.md",
        ".gitignore",
    ]

    all_passed = True
    for file_path in required_files:
        full_path = base_dir / file_path
        exists = full_path.exists()
        if exists:
            size = full_path.stat().st_size
            print(f"  {check_mark(exists)} {file_path} ({size} bytes)")
        else:
            print(f"  {check_mark(exists)} {file_path} (NOT FOUND)")
            all_passed = False

    config_path = default_config_path()
    config_exists = config_path.is_file()
    print(
        f"  {check_mark(config_exists)} "
        f"{config_path.relative_to(base_dir) if config_exists else config_path}"
    )
    all_passed = all_passed and config_exists

    return all_passed

def agent_configuration_error(agent_file: Path) -> str | None:
    """Return a concise defect for one agent YAML, or ``None`` when usable."""

    try:
        load_agent_definition(agent_file)
    except AgentDefinitionError as exc:
        return str(exc)
    return None


def validate_agents():
    """Parse agent configurations and validate their minimum structure."""
    print_header("6. Agent Configurations")

    agents_dir = agents_root()

    agent_files = list(agents_dir.rglob("*.yaml"))

    if not agent_files:
        print(f"  {check_mark(False)} No agent configurations found")
        return False

    try:
        definitions = load_agent_definitions()
    except AgentDefinitionError as exc:
        print(f"  {check_mark(False)} Packaged agent catalogue - {exc}")
        return False

    definitions_by_path = {definition.path: definition for definition in definitions}
    all_passed = True
    for agent_file in sorted(agent_files):
        rel_path = agent_file.relative_to(agents_dir)
        if agent_file not in definitions_by_path:
            print(f"  {check_mark(False)} {rel_path} - missing from agent catalogue")
            all_passed = False
            continue
        print(f"  {check_mark(True)} {rel_path}")

    print(f"\n  Total agents: {len(agent_files)}")
    return all_passed

def validate_plugins():
    """Validate plugin implementations."""
    print_header("7. Plugin Implementations")

    base_dir = Path(__file__).parent
    plugins_dir = base_dir / "plugins"

    plugin_files = [f for f in plugins_dir.glob("*.py") if not f.name.startswith("__")]

    if not plugin_files:
        print(f"  {check_mark(False)} No plugins found")
        return False

    all_passed = True
    for plugin_file in sorted(plugin_files):
        # Try to import and register
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(plugin_file.stem, plugin_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                if hasattr(module, "register_plugin"):
                    plugin_info = module.register_plugin()
                    print(f"  {check_mark(True)} {plugin_file.name} - {plugin_info['description']}")
                else:
                    print(f"  {check_mark(False)} {plugin_file.name} - Missing register_plugin()")
                    all_passed = False
        except Exception as e:
            print(f"  {check_mark(False)} {plugin_file.name} - Error: {str(e)[:50]}")
            all_passed = False

    return all_passed

def validate_cli():
    """Validate CLI is available."""
    print_header("8. CLI Availability")

    try:
        importlib.import_module("cli.main")
        print(f"  {check_mark(True)} CLI module importable")

        # Check if openclaw-cli command exists
        import subprocess
        result = subprocess.run(
            ["which", "openclaw-cli"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(f"  {check_mark(True)} openclaw-cli command available")
            print(f"    Location: {result.stdout.strip()}")
            return True
        else:
            print(f"  {check_mark(False)} openclaw-cli command not in PATH")
            print("    Try: uv pip install -e .")
            return False
    except Exception as e:
        print(f"  {check_mark(False)} CLI import error: {str(e)}")
        return False

def main():
    """Run all validations."""
    # Load only this checkout's explicit dotenv. Never search from the caller's
    # current directory, where an unrelated file could redirect repository roots.
    dotenv_path = Path(__file__).resolve().parent / ".env"
    selected_dotenv = (
        dotenv_path if dotenv_path.exists() or dotenv_path.is_symlink() else None
    )
    try:
        environ = merged_repository_environment(
            selected_dotenv,
            environ=os.environ,
        )
    except RepositoryConfigurationError as exc:
        print(f"\n  {check_mark(False)} Project environment is invalid: {exc}")
        return 1
    print("\n" + "=" * 70)
    print("  KG-Microbe OpenClaw Orchestration - Setup Validation")
    print("=" * 70)

    try:
        manifest = load_fleet_manifest()
    except FleetManifestError as exc:
        print(f"\n  {check_mark(False)} Fleet manifest is invalid: {exc}")
        return 1

    results = {
        "Installation": validate_installation(),
        "Environment": validate_environment(manifest, environ),
        "Repositories": validate_repositories(manifest, environ),
        "Structure": validate_structure(),
        "Files": validate_files(),
        "Agents": validate_agents(),
        "Plugins": validate_plugins(),
        "CLI": validate_cli(),
    }

    # Summary
    print_header("Validation Summary")

    all_passed = True
    for category, passed in results.items():
        print(f"  {check_mark(passed)} {category}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("  ✓ ALL CHECKS PASSED")
        print("  Week 1 setup is complete and ready for use!")
        print("\n  Next steps:")
        print("  1. Add your Anthropic API key to .env")
        print("  2. Run: openclaw-cli status")
        print("  3. Run: openclaw-cli agent list")
        print("  4. Proceed to Week 2 implementation")
    else:
        print("  ✗ SOME CHECKS FAILED")
        print("  Please review the failures above and fix them.")
        print("\n  Common fixes:")
        print("  1. Run: uv pip install -e .")
        print("  2. Check .env file has correct paths")
        print("  3. Ensure all repositories exist at specified paths")
    print("=" * 70 + "\n")

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
