"""
KG-Microbe OpenClaw CLI

Command-line interface for orchestrating AI coding agents across
CultureMech, MediaIngredientMech, and CommunityMech repositories.
"""

import os
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from dotenv import load_dotenv

# Add parent directory to path to import plugins
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
load_dotenv()

console = Console()


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """
    KG-Microbe OpenClaw Orchestration CLI

    Coordinate AI coding agents across three microbial knowledge base repositories:
    - CultureMech: 10,657 culture media recipes
    - MediaIngredientMech: 1,131 ingredients with ontology mappings
    - CommunityMech: 35+ microbial communities with ecological interactions
    """
    pass


@cli.group()
def agent():
    """Manage and execute agents."""
    pass


@agent.command("list")
def list_agents():
    """List all available agents."""
    agents_dir = Path(__file__).parent.parent / "agents"

    table = Table(title="Available OpenClaw Agents")
    table.add_column("Agent", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Model", style="green")
    table.add_column("Description")

    # Scan for agent YAML files
    agent_files = [f for f in agents_dir.rglob("*.yaml")]

    for agent_file in sorted(agent_files):
        agent_type = agent_file.parent.name
        agent_name = agent_file.stem

        # Try to read basic info (in production, would parse YAML properly)
        table.add_row(
            agent_name,
            agent_type,
            "Haiku/Sonnet",  # Placeholder
            f"Defined in {str(agent_file.relative_to(agents_dir))}"
        )

    console.print(table)
    console.print(f"\nTotal agents: {len(agent_files)}")


@agent.command()
@click.argument("agent_name")
@click.option("--dry-run", is_flag=True, help="Simulate execution without making changes")
def run(agent_name: str, dry_run: bool):
    """
    Run a specific agent.

    Example: openclaw-cli agent run validation_agent --dry-run
    """
    if dry_run:
        console.print(f"[yellow]DRY RUN: Would execute {agent_name}[/yellow]")
    else:
        console.print(f"[red]Not implemented yet: Agent execution requires OpenClaw SDK integration[/red]")
        console.print(f"Agent: {agent_name}")


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


@pipeline.command()
@click.argument("pipeline_name")
@click.option("--dry-run", is_flag=True, help="Simulate execution")
def run(pipeline_name: str, dry_run: bool):
    """
    Run a specific pipeline.

    Example: openclaw-cli pipeline run ingredient_curation --dry-run
    """
    if dry_run:
        console.print(f"[yellow]DRY RUN: Would execute {pipeline_name} pipeline[/yellow]")
    else:
        console.print(f"[red]Not implemented yet: Pipeline execution requires OpenClaw SDK integration[/red]")
        console.print(f"Pipeline: {pipeline_name}")


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
        console.print(f"[red]Plugin not found: {plugin_name}[/red]")
        return

    # Try to import and instantiate the plugin
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "register_plugin"):
                plugin_info = module.register_plugin()
                console.print(f"[green]✓ Plugin registered successfully[/green]")
                console.print(f"  Name: {plugin_info['name']}")
                console.print(f"  Version: {plugin_info['version']}")
                console.print(f"  Description: {plugin_info['description']}")

                # Try to instantiate
                plugin_class = plugin_info["class"]
                plugin_instance = plugin_class()
                console.print(f"[green]✓ Plugin instantiated successfully[/green]")
            else:
                console.print(f"[red]Plugin missing register_plugin() function[/red]")

    except Exception as e:
        console.print(f"[red]Error loading plugin: {e}[/red]")


@cli.group()
def config():
    """Configuration management."""
    pass


@config.command()
def show():
    """Show current configuration."""
    table = Table(title="OpenClaw Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    # Environment variables
    settings = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "[not set]")[:20] + "..." if os.getenv("ANTHROPIC_API_KEY") else "[not set]",
        "OPENCLAW_MODE": os.getenv("OPENCLAW_MODE", "local"),
        "OPENCLAW_LOG_LEVEL": os.getenv("OPENCLAW_LOG_LEVEL", "INFO"),
        "CULTUREMECH_ROOT": os.getenv("CULTUREMECH_ROOT", "[not set]"),
        "MEDIAINGREDIENTMECH_ROOT": os.getenv("MEDIAINGREDIENTMECH_ROOT", "[not set]"),
        "COMMUNITYMECH_ROOT": os.getenv("COMMUNITYMECH_ROOT", "[not set]"),
    }

    for key, value in settings.items():
        table.add_row(key, value)

    console.print(table)


@config.command()
def validate():
    """Validate configuration."""
    issues = []

    # Check API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        issues.append("ANTHROPIC_API_KEY is not set")

    # Check repository paths
    repos = {
        "CultureMech": os.getenv("CULTUREMECH_ROOT"),
        "MediaIngredientMech": os.getenv("MEDIAINGREDIENTMECH_ROOT"),
        "CommunityMech": os.getenv("COMMUNITYMECH_ROOT"),
    }

    for repo_name, repo_path in repos.items():
        if not repo_path:
            issues.append(f"{repo_name} path not set")
        elif not Path(repo_path).exists():
            issues.append(f"{repo_name} path does not exist: {repo_path}")

    if issues:
        console.print("[red]Configuration issues found:[/red]")
        for issue in issues:
            console.print(f"  [yellow]- {issue}[/yellow]")
        sys.exit(1)
    else:
        console.print("[green]✓ Configuration is valid[/green]")


@cli.command()
def status():
    """Show overall system status."""
    config_table = Table(title="System Status")
    config_table.add_column("Component", style="cyan")
    config_table.add_column("Status", style="green")

    # Check OpenClaw installation
    try:
        import openclaw
        openclaw_status = f"✓ Installed (v{openclaw.__version__})"
    except ImportError:
        openclaw_status = "✗ Not installed"

    config_table.add_row("OpenClaw", openclaw_status)

    # Check repositories
    repos = {
        "CultureMech": os.getenv("CULTUREMECH_ROOT"),
        "MediaIngredientMech": os.getenv("MEDIAINGREDIENTMECH_ROOT"),
        "CommunityMech": os.getenv("COMMUNITYMECH_ROOT"),
    }

    for repo_name, repo_path in repos.items():
        if repo_path and Path(repo_path).exists():
            status = "✓ Found"
        else:
            status = "✗ Not found"
        config_table.add_row(repo_name, status)

    console.print(config_table)

    # Count agents and plugins
    agents_dir = Path(__file__).parent.parent / "agents"
    plugins_dir = Path(__file__).parent.parent / "plugins"

    agent_count = len(list(agents_dir.rglob("*.yaml")))
    plugin_count = len([f for f in plugins_dir.glob("*.py") if not f.name.startswith("__")])

    console.print(f"\n[cyan]Agents configured: {agent_count}[/cyan]")
    console.print(f"[cyan]Plugins available: {plugin_count}[/cyan]")


if __name__ == "__main__":
    cli()
