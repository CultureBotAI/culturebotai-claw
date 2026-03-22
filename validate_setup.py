#!/usr/bin/env python3
"""
Setup Validation Script for KG-Microbe OpenClaw Orchestration

Run this script to verify that the orchestration layer is properly installed
and configured.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

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
        ("openclaw", "2026.3.12"),
        ("anthropic", "0.85.0"),
        ("click", "8.0.0"),
        ("rich", "13.0.0"),
        ("gitpython", "3.1.0"),
        ("yaml", None),  # PyYAML
        ("watchdog", "3.0.0"),
        ("dotenv", None),  # python-dotenv
    ]

    all_passed = True
    for package, min_version in packages:
        try:
            if package == "yaml":
                import yaml
                print(f"  {check_mark(True)} PyYAML installed")
            elif package == "dotenv":
                import dotenv
                print(f"  {check_mark(True)} python-dotenv installed")
            else:
                module = __import__(package)
                version = getattr(module, "__version__", "unknown")
                print(f"  {check_mark(True)} {package} v{version}")
        except ImportError:
            print(f"  {check_mark(False)} {package} NOT INSTALLED")
            all_passed = False

    return all_passed

def validate_environment():
    """Validate environment variables."""
    print_header("2. Environment Configuration")

    required_vars = [
        "CULTUREMECH_ROOT",
        "MEDIAINGREDIENTMECH_ROOT",
        "COMMUNITYMECH_ROOT",
        "OPENCLAW_MODE",
        "OPENCLAW_LOG_LEVEL",
    ]

    optional_vars = [
        "ANTHROPIC_API_KEY",
    ]

    all_passed = True

    print("\n  Required Variables:")
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"  {check_mark(True)} {var} = {value[:50]}...")
        else:
            print(f"  {check_mark(False)} {var} NOT SET")
            all_passed = False

    print("\n  Optional Variables:")
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            if "KEY" in var or "SECRET" in var:
                print(f"  {check_mark(True)} {var} = {'*' * 20}... (hidden)")
            else:
                print(f"  {check_mark(True)} {var} = {value[:50]}...")
        else:
            print(f"  {check_mark(False)} {var} NOT SET (optional)")

    return all_passed

def validate_repositories():
    """Validate repository paths exist."""
    print_header("3. Repository Paths")

    repos = {
        "CultureMech": os.getenv("CULTUREMECH_ROOT"),
        "MediaIngredientMech": os.getenv("MEDIAINGREDIENTMECH_ROOT"),
        "CommunityMech": os.getenv("COMMUNITYMECH_ROOT"),
    }

    all_passed = True
    for repo_name, repo_path in repos.items():
        if not repo_path:
            print(f"  {check_mark(False)} {repo_name}: Path not set")
            all_passed = False
            continue

        path = Path(repo_path)
        if path.exists():
            # Check for justfile
            justfile = path / "justfile"
            if justfile.exists():
                print(f"  {check_mark(True)} {repo_name}: {repo_path} (justfile found)")
            else:
                print(f"  {check_mark(True)} {repo_name}: {repo_path} (no justfile)")
        else:
            print(f"  {check_mark(False)} {repo_name}: {repo_path} (NOT FOUND)")
            all_passed = False

    return all_passed

def validate_structure():
    """Validate directory structure."""
    print_header("4. Directory Structure")

    base_dir = Path(__file__).parent

    required_dirs = [
        "agents",
        "agents/code_development",
        "agents/data_pipeline",
        "agents/build_deployment",
        "agents/dev_workflow",
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
        "openclaw_config.yaml",
        ".env",
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

    return all_passed

def validate_agents():
    """Validate agent configurations."""
    print_header("6. Agent Configurations")

    base_dir = Path(__file__).parent
    agents_dir = base_dir / "agents"

    agent_files = list(agents_dir.rglob("*.yaml"))

    if not agent_files:
        print(f"  {check_mark(False)} No agent configurations found")
        return False

    for agent_file in sorted(agent_files):
        rel_path = agent_file.relative_to(agents_dir)
        print(f"  {check_mark(True)} {rel_path}")

    print(f"\n  Total agents: {len(agent_files)}")
    return True

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
        from cli.main import cli
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
            print(f"    Try: uv pip install -e .")
            return False
    except Exception as e:
        print(f"  {check_mark(False)} CLI import error: {str(e)}")
        return False

def main():
    """Run all validations."""
    print("\n" + "=" * 70)
    print("  KG-Microbe OpenClaw Orchestration - Setup Validation")
    print("=" * 70)

    results = {
        "Installation": validate_installation(),
        "Environment": validate_environment(),
        "Repositories": validate_repositories(),
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
