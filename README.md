# KG-Microbe OpenClaw Orchestration

AI agent orchestration layer for coordinating development across three interconnected microbial knowledge base repositories:

- **CultureMech**: 10,657 culture media recipes from 10 international sources
- **MediaIngredientMech**: LLM-assisted curation system for 1,131 ingredients with ontology mappings
- **CommunityMech**: Microbial community modeling (35+ communities) with ecological interactions

## Overview

This orchestration layer uses [OpenClaw](https://pypi.org/project/openclaw/) to coordinate AI coding agents for:

- **Data pipeline automation** (ingredient curation, validation, cross-repo data flows)
- **Code development** (refactoring, documentation, testing)
- **Build coordination** (multi-repo releases, synchronized versioning)
- **Development workflows** (schema sync, dependency updates, integration testing)

## Installation

### Prerequisites

- Python 3.10+
- uv package manager
- `just` task runner installed
- Git
- Anthropic API key

### Setup

1. **Clone or navigate to this directory:**
   ```bash
   cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Configure environment:**
   Edit `.env` and add your Anthropic API key:
   ```bash
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   The repository paths are pre-configured, but verify they're correct:
   ```bash
   openclaw-cli config show
   ```

4. **Validate configuration:**
   ```bash
   openclaw-cli config validate
   ```

5. **Check system status:**
   ```bash
   openclaw-cli status
   ```

## Available Agents

### Code Development Agents
- **DocumentationAgent** (Haiku) - Generate schema docs, update READMEs, create API documentation
- **RefactoringAgent** (Sonnet) - Code refactoring, pattern detection [Coming in Week 2]
- **TestAgent** (Sonnet) - Generate tests, run pytest, analyze coverage [Coming in Week 2]

### Data Pipeline Agents
- **ValidationAgent** (Haiku) - Schema and ontology validation
- **IngredientCurationAgent** (Sonnet) - LLM-assisted ontology mapping [Coming in Week 2]
- **ETLCoordinatorAgent** (Sonnet) - Cross-repo data flows [Coming in Week 2]
- **NetworkRepairAgent** (Opus) - Network integrity auditing [Coming in Week 2]

### Build & Deployment Agents
- **BuildCoordinatorAgent** (Haiku) - Multi-repo builds, justfile execution [Coming in Week 3]
- **ExportAgent** (Haiku) - Browser exports, KGX files [Coming in Week 3]
- **ReleaseAgent** (Sonnet) - Version management, coordinated releases [Coming in Week 3]

### Development Workflow Agents
- **SchemaSyncAgent** (Haiku) - Schema change propagation [Coming in Week 3]
- **DependencyAgent** (Haiku) - Dependency updates, security checks [Coming in Week 3]
- **CrossRepoValidatorAgent** (Sonnet) - Integration testing [Coming in Week 3]

## Quick Start

### List Available Agents
```bash
openclaw-cli agent list
```

### Run Validation Agent (Dry Run)
```bash
openclaw-cli agent run validation_agent --dry-run
```

### List Available Plugins
```bash
openclaw-cli plugin list
```

### Test a Plugin
```bash
openclaw-cli plugin test just_runner
```

## Plugins

The orchestration system includes custom plugins that wrap existing tools:

### JustRunnerPlugin
Executes justfile recipes across all three repositories.

**Example usage:**
```python
from plugins.just_runner import JustRunnerPlugin

plugin = JustRunnerPlugin()
result = plugin.execute_recipe("culturemech", "validate-all")
```

### LinkMLValidatorPlugin
Validates YAML data against LinkML schemas.

**Example usage:**
```python
from plugins.linkml_validator import LinkMLValidatorPlugin

plugin = LinkMLValidatorPlugin()
result = plugin.validate_repository("mediaingredientmech")
```

### GitIntegrationPlugin
Safe git operations (branching, committing, status).

**Example usage:**
```python
from plugins.git_integration import GitIntegrationPlugin

plugin = GitIntegrationPlugin()
result = plugin.create_branch("communitymech", "feature/network-repair")
```

### OAKQueryPlugin
Ontology Access Kit integration [Coming in Week 2]

## Directory Structure

```
culturebotai-claw/
├── openclaw_config.yaml          # Main OpenClaw configuration
├── .env                          # Environment variables
├── pyproject.toml                # Dependencies
├── README.md                     # This file
│
├── agents/                       # Agent definitions (YAML)
│   ├── code_development/         # RefactoringAgent, DocumentationAgent, TestAgent
│   ├── data_pipeline/            # ETLCoordinator, IngredientCuration, Validation
│   ├── build_deployment/         # BuildCoordinator, Export, Release
│   └── dev_workflow/             # SchemaSync, Dependency, CrossRepoValidator
│
├── pipelines/                    # Multi-agent pipelines
│   ├── ingredient_curation_pipeline.py  [Coming in Week 2]
│   ├── release_pipeline.py              [Coming in Week 3]
│   └── validation_pipeline.py           [Coming in Week 1]
│
├── plugins/                      # Custom OpenClaw plugins
│   ├── just_runner.py            # Execute justfile recipes
│   ├── linkml_validator.py       # LinkML validation
│   ├── git_integration.py        # Git operations
│   └── oak_query.py              # Ontology queries [Coming in Week 2]
│
├── workspace/                    # Agent workspaces (gitignored)
│   ├── shared_memory/            # Inter-agent communication
│   ├── validation_agent/         # ValidationAgent workspace
│   ├── documentation_agent/      # DocumentationAgent workspace
│   └── logs/                     # Execution logs
│
└── cli/
    └── main.py                   # Click CLI
```

## CLI Commands

### Agent Management
```bash
# List all agents
openclaw-cli agent list

# Run a specific agent
openclaw-cli agent run <agent_name> [--dry-run]
```

### Pipeline Management
```bash
# List all pipelines
openclaw-cli pipeline list

# Run a specific pipeline
openclaw-cli pipeline run <pipeline_name> [--dry-run]
```

### Plugin Management
```bash
# List all plugins
openclaw-cli plugin list

# Test a specific plugin
openclaw-cli plugin test <plugin_name>
```

### Configuration
```bash
# Show current configuration
openclaw-cli config show

# Validate configuration
openclaw-cli config validate
```

### System Status
```bash
# Show overall system status
openclaw-cli status
```

## Development Roadmap

### ✅ Week 1: Foundation (Current)
- [x] Create orchestration directory structure
- [x] Install OpenClaw and dependencies
- [x] Create main configuration files
- [x] Build ValidationAgent
- [x] Build DocumentationAgent
- [x] Create JustRunner, LinkML, and Git plugins
- [x] Create CLI interface
- [ ] Test agents on CommunityMech

### Week 2-3: Core Agents
- [ ] Implement ETLCoordinatorAgent
- [ ] Implement IngredientCurationAgent (wrap existing LLM code)
- [ ] Implement NetworkRepairAgent (wrap llm_repair.py)
- [ ] Create ingredient curation pipeline
- [ ] Create OAKQueryPlugin

### Week 4: Build & Development
- [ ] Implement BuildCoordinatorAgent
- [ ] Implement ReleaseAgent
- [ ] Implement SchemaSyncAgent
- [ ] Create multi-repo build pipeline

### Week 5: Advanced Features
- [ ] Add RefactoringAgent and TestAgent
- [ ] Implement file watching and event triggers
- [ ] Add monitoring and metrics

### Week 6: Production Hardening
- [ ] Comprehensive testing
- [ ] Complete documentation
- [ ] Safety mechanisms
- [ ] Team training

## Safety Features

The orchestration system includes multiple safety mechanisms:

1. **Read-only default**: All agents default to read-only mode
2. **Git branches**: All modifications happen in dedicated branches
3. **Approval workflows**: Critical operations require approval
4. **Automatic backups**: All write operations create timestamped backups
5. **Audit logging**: Every agent action is logged
6. **Cost tracking**: LLM API costs are monitored

## Cost Estimates

Estimated monthly costs (with proper caching):
- Ingredient Curation: ~$90/month (Sonnet, daily)
- Network Repair: ~$21/month (Opus, weekly)
- Code Refactoring: ~$5-20/month (Sonnet, as needed)
- Documentation: ~$1.20/month (Haiku, daily)
- Validation: ~$7.20/month (Haiku, hourly)
- **Total: $125-150/month**

## Support

For issues or questions:
- Check the main plan document in `.claude/` directory
- Review agent configuration in `agents/`
- Check logs in `workspace/logs/`
- Verify configuration with `openclaw-cli config validate`

## License

This orchestration layer is part of the KG-Microbe project.
