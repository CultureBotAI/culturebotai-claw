"""
KG-Microbe OpenClaw CLI

Command-line interface for orchestrating AI coding agents across the Mech
fleet defined in ``src/kg_microbe_fleet/fleet.yaml``.
"""

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from kg_microbe_agents import (
    AgentDefinitionError,
    agents_root,
    load_agent_definitions,
    load_named_agent,
)
from kg_microbe_config import default_config_path
from kg_microbe_fleet import load_fleet_manifest
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
    merged_repository_environment,
)

console = Console()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = agents_root()
DEFAULT_CONFIG_PATH = default_config_path()


def _runtime_environment() -> dict[str, str]:
    """Merge this source checkout's explicit dotenv with exported values.

    Never search from the caller's current directory: an unrelated ``.env``
    must not redirect repository operations. Installed commands have no source
    dotenv and therefore use only their exported environment.
    """

    dotenv_path = PROJECT_ROOT / ".env"
    selected_dotenv = None
    if (PROJECT_ROOT / "pyproject.toml").is_file() and (
        dotenv_path.exists() or dotenv_path.is_symlink()
    ):
        selected_dotenv = dotenv_path
    return merged_repository_environment(selected_dotenv, environ=os.environ)


def _project_version() -> str:
    try:
        return version("kg-microbe-orchestration")
    except PackageNotFoundError:
        return "unknown"


def _pipeline_file(pipeline_name: str) -> Path | None:
    candidates = {pipeline_name, f"{pipeline_name}_pipeline"}
    matches = [PROJECT_ROOT / "pipelines" / f"{name}.py" for name in candidates]
    existing = [path for path in matches if path.exists()]
    return existing[0] if len(existing) == 1 else None


@click.group()
@click.version_option(version=_project_version())
def cli():
    """
    KG-Microbe OpenClaw Orchestration CLI

    Coordinate AI coding agents across the Mech fleet defined in
    src/kg_microbe_fleet/fleet.yaml. Run `openclaw-cli status` for the current fleet and
    which repositories are configured here.
    """
    pass


@cli.group()
def agent():
    """Manage and execute agents."""
    pass


@agent.command("list")
def list_agents():
    """List all available agents."""
    table = Table(title="Available OpenClaw Agents")
    table.add_column("Agent", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Model", style="green")
    table.add_column("Description")

    manifest = load_fleet_manifest()
    try:
        definitions = load_agent_definitions(manifest)
    except AgentDefinitionError as exc:
        raise click.ClickException(str(exc)) from exc
    for definition in definitions:
        table.add_row(
            definition.name,
            definition.agent_type,
            definition.model,
            definition.description,
        )

    console.print(table)
    console.print(f"\nTotal agents: {len(definitions)}")


@agent.command("run")
@click.argument("agent_name")
@click.option("--dry-run", is_flag=True, help="Simulate execution without making changes")
def run_agent(agent_name: str, dry_run: bool):
    """
    Run a specific agent.

    Example: openclaw-cli agent run validation_agent --dry-run
    """
    manifest = load_fleet_manifest()
    try:
        definition = load_named_agent(agent_name, manifest)
    except AgentDefinitionError as exc:
        raise click.ClickException(str(exc)) from exc
    if not dry_run:
        raise click.ClickException(
            "Agent execution is not implemented; use --dry-run to validate the request"
        )
    console.print(
        f"[yellow]DRY RUN: validated {agent_name} "
        f"({definition.path.relative_to(AGENTS_ROOT)}) across "
        f"{len(definition.repository_keys)} manifest-scoped repositories[/yellow]"
    )


@cli.group()
def pipeline():
    """Manage and execute pipelines."""
    pass


@pipeline.command("list")
def list_pipelines():
    """List all available pipelines."""
    pipelines_dir = Path(__file__).parent.parent / "pipelines"

    table = Table(title="Available Pipelines")
    table.add_column("Pipeline", style="cyan")
    table.add_column("Description")

    pipeline_files = [f for f in pipelines_dir.glob("*.py")]

    for pipeline_file in sorted(pipeline_files):
        if pipeline_file.name == "__init__.py":
            continue
        table.add_row(
            pipeline_file.stem,
            f"Defined in {pipeline_file.name}"
        )

    console.print(table)


@pipeline.command("run")
@click.argument("pipeline_name")
@click.option("--dry-run", is_flag=True, help="Simulate execution")
def run_pipeline(pipeline_name: str, dry_run: bool):
    """
    Run a specific pipeline.

    Example: openclaw-cli pipeline run ingredient_curation --dry-run
    """
    pipeline_file = _pipeline_file(pipeline_name)
    if pipeline_file is None:
        raise click.ClickException(f"Unknown or ambiguous pipeline: {pipeline_name}")
    if not dry_run:
        raise click.ClickException(
            "Pipeline execution is not implemented; use --dry-run to validate the request"
        )
    console.print(
        f"[yellow]DRY RUN: validated {pipeline_name} "
        f"({pipeline_file.relative_to(PROJECT_ROOT)})[/yellow]"
    )


@cli.group()
def plugin():
    """Manage plugins."""
    pass


@plugin.command("list")
def list_plugins():
    """List all available plugins."""
    plugins_dir = Path(__file__).parent.parent / "plugins"

    table = Table(title="Available Plugins")
    table.add_column("Plugin", style="cyan")
    table.add_column("Version", style="green")
    table.add_column("Description")

    plugin_files = [f for f in plugins_dir.glob("*.py")]

    for plugin_file in sorted(plugin_files):
        if plugin_file.name.startswith("__"):
            continue

        table.add_row(
            plugin_file.stem,
            "1.0.0",
            f"Defined in {plugin_file.name}"
        )

    console.print(table)


@plugin.command()
@click.argument("plugin_name")
def test(plugin_name: str):
    """
    Test a specific plugin.

    Example: openclaw-cli plugin test just_runner
    """
    console.print(f"[yellow]Testing plugin: {plugin_name}[/yellow]")

    plugins_dir = Path(__file__).parent.parent / "plugins"
    plugin_file = plugins_dir / f"{plugin_name}.py"

    if not plugin_file.exists():
        raise click.ClickException(f"Plugin not found: {plugin_name}")

    # Try to import and instantiate the plugin
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "register_plugin"):
                plugin_info = module.register_plugin()
                console.print("[green]✓ Plugin registered successfully[/green]")
                console.print(f"  Name: {plugin_info['name']}")
                console.print(f"  Version: {plugin_info['version']}")
                console.print(f"  Description: {plugin_info['description']}")

                # Try to instantiate
                plugin_class = plugin_info["class"]
                plugin_class()
                console.print("[green]✓ Plugin instantiated successfully[/green]")
            else:
                raise click.ClickException("Plugin missing register_plugin() function")
        else:
            raise click.ClickException(f"Unable to load plugin module: {plugin_name}")

    except Exception as e:
        if isinstance(e, click.ClickException):
            raise
        raise click.ClickException(f"Error loading plugin: {e}") from e


@cli.group()
def config():
    """Configuration management."""
    pass


@config.command()
def show():
    """Show current configuration."""
    manifest = load_fleet_manifest()
    try:
        environ = _runtime_environment()
    except RepositoryConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc
    table = Table(title="OpenClaw Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    # Environment variables
    settings = {
        "ANTHROPIC_API_KEY": "configured" if environ.get("ANTHROPIC_API_KEY") else "not set",
        "OPENCLAW_MODE": environ.get("OPENCLAW_MODE", "local"),
        "OPENCLAW_LOG_LEVEL": environ.get("OPENCLAW_LOG_LEVEL", "INFO"),
    }
    for mech in manifest.mechs.values():
        settings[mech.environment_variable] = environ.get(
            mech.environment_variable, "[not set]"
        )

    for key, value in settings.items():
        table.add_row(key, value)

    console.print(table)


@config.command()
@click.option(
    "--config-file",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_CONFIG_PATH,
    show_default=True,
)
@click.option(
    "--require-all-repositories",
    is_flag=True,
    help=(
        "Treat a repository that has no configured path as a failure. Off by "
        "default so a checkout without every Mech cloned still validates; "
        "enable it where the full fleet is genuinely expected."
    ),
)
def validate(config_file: Path, require_all_repositories: bool):
    """Validate configuration."""
    issues = []
    absent: tuple[str, ...] = ()
    manifest = load_fleet_manifest()

    try:
        settings = RepositorySettings.from_file(
            config_file,
            environ=_runtime_environment(),
            manifest=manifest,
        )
    except RepositoryConfigurationError as exc:
        issues.append(str(exc))
    else:
        # A repository that is merely not cloned locally is not a defect in
        # this configuration; one that is configured but untrustworthy is.
        # Both remain unusable at operation time either way.
        issues.extend(settings.invalid.values())
        absent = settings.unconfigured
        if require_all_repositories:
            issues.extend(settings.errors[name] for name in absent)
            absent = ()

    if absent:
        console.print(
            f"[yellow]Not configured locally ({len(absent)}):[/yellow] "
            + ", ".join(absent)
        )
        console.print(
            "[yellow]  These are fleet members without a configured path here. "
            "Operations against them will still fail closed.[/yellow]"
        )

    if issues:
        console.print("[red]Configuration issues found:[/red]")
        for issue in issues:
            console.print(f"  [yellow]- {issue}[/yellow]")
        raise click.ClickException(
            f"Configuration validation failed with {len(issues)} issue(s)"
        )
    else:
        console.print("[green]✓ Configuration is valid[/green]")


@cli.command()
def status():
    """Show overall system status."""
    config_table = Table(title="System Status")
    config_table.add_column("Component", style="cyan")
    config_table.add_column("Status", style="green")

    config_table.add_row(
        "Orchestration package", f"✓ Installed (v{_project_version()})"
    )

    # Load one immutable fleet snapshot and inject it into the repository
    # resolver. A separately cached import-time registry used to let the status
    # display and the paths being validated disagree.
    manifest = load_fleet_manifest()
    try:
        environ = _runtime_environment()
    except RepositoryConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc
    repository_names = {
        key: mech.display_name for key, mech in manifest.mechs.items()
    }
    try:
        settings = RepositorySettings.from_file(
            DEFAULT_CONFIG_PATH,
            environ=environ,
            manifest=manifest,
        )
    except RepositoryConfigurationError as exc:
        settings = None
        repository_error = str(exc)
    else:
        repository_error = ""

    for key, display_name in repository_names.items():
        if settings is None:
            repository_status = f"✗ {repository_error}"
        elif key in settings.errors:
            repository_status = f"✗ {settings.errors[key]}"
        elif key in settings.paths:
            repository_status = "✓ Verified"
        else:
            # Defensive guard: both objects came from the same manifest, so an
            # absent key is a settings contract failure, not a verified repo.
            repository_status = f"✗ '{key}' is missing from repository settings"
        config_table.add_row(display_name, repository_status)

    console.print(config_table)

    # Count agents and plugins
    agents_dir = AGENTS_ROOT
    plugins_dir = Path(__file__).parent.parent / "plugins"

    agent_count = len(list(agents_dir.rglob("*.yaml")))
    plugin_count = len([f for f in plugins_dir.glob("*.py") if not f.name.startswith("__")])

    console.print(f"\n[cyan]Agents configured: {agent_count}[/cyan]")
    console.print(f"[cyan]Plugins available: {plugin_count}[/cyan]")


if __name__ == "__main__":
    cli()
