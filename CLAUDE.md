# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CultureBotAI-CLAW is an AI agent orchestration system for coordinating development across three interconnected microbial knowledge base repositories:

- **CultureMech**: `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech` - 10,657 culture media recipes
- **MIM** (MediaIngredientMech): `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech` - ingredients with ontology mappings (CHEBI / FOODON / NCIT / cas: / kgmicrobe.compound:)
- **CommunityMech**: `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CommunityMech/CommunityMech` - 35+ microbial communities

> **Acronym convention**: Throughout this repo (CLAUDE.md, skills, README, scripts), `MIM` is the canonical acronym for MediaIngredientMech. Use the verbose `MediaIngredientMech` only in (a) filesystem paths, (b) repository URLs, (c) environment variable names like `MEDIAINGREDIENTMECH_ROOT`, and (d) the first introduction (here) where the acronym is defined.

## Multi-Claude Coordination Architecture

**CRITICAL**: This repository uses a unique multi-Claude coordination system where multiple Claude Code sessions work concurrently across 4 repositories. Coordination happens through file-based communication, NOT API calls.

### Coordination Roles

- **Orchestration Claude** (this repository): Coordinates agents, creates tasks, manages locks, monitors progress
- **Repository Claudes** (CultureMech/MediaIngredientMech/CommunityMech): Execute work within their repository boundaries

### Lock System

Before any operation that modifies downstream repositories:

```python
from plugins.lock_manager import LockManager

lock_manager = LockManager()
if lock_manager.acquire_lock("mediaingredientmech", "operation_name"):
    # Perform operation
    lock_manager.release_lock("mediaingredientmech")
```

**Lock files**: `workspace/locks/*.lock` (auto-expire after 1 hour)

### Task-Based Communication

Create tasks for downstream Claude sessions:

```python
task_id = create_curation_task(
    workspace=Path("workspace"),
    batch_size=20,
    auto_accept_threshold=0.9,
    dry_run=False
)
# Task file created in workspace/tasks/
# Downstream Claude reads and processes it
```

## Prompts

Hand-over prompts live in `prompts/`. They are **prompts, not slash commands** — feed them to
a native command, or paste them to another agent or an independent reviewer. No frontmatter,
no wrapper, on purpose.

- **`prompts/backlog-loop-goal.md`** — review and prioritise the open issues across the
  fleet, then take the chosen one all the way: branch, work, PR, adversarial review, issues
  from that review, merge on approval, delete the branch. Feed it to the native `/goal`.

⚠️ **Do not wrap this as a custom command.** It used to live at `.claude/commands/goal.md`,
which registered a custom `/goal` and therefore SHADOWED the native one instead of feeding
it. If such a wrapper reappears, delete it rather than repointing it.
(`.claude/commands/curate.md` is fine — it has no native equivalent.)

## Development Commands

### Setup

```bash
# Install dependencies
uv sync

# Configure environment (edit .env first)
openclaw-cli config validate

# Check system status
openclaw-cli status
```

### CLI Usage

```bash
# List agents
openclaw-cli agent list

# Run agent (dry-run recommended)
openclaw-cli agent run validation_agent --dry-run

# List/test plugins
openclaw-cli plugin list
openclaw-cli plugin test just_runner
```

### Testing

```bash
# Test multi-Claude coordination
./test_coordination.py

# Test lock system
./test_lock_coordination.sh

# Run pilot test (orchestration test)
./run_pilot_test_tasks.py --batch-size 5 --dry-run
```

## Architecture

### Directory Structure

```
agents/                    # Agent definitions (YAML)
├── code_development/      # RefactoringAgent, DocumentationAgent, TestAgent
├── data_pipeline/         # ETLCoordinator, IngredientCuration, ValidationAgent
├── build_deployment/      # BuildCoordinator, ExportAgent, ReleaseAgent
└── dev_workflow/          # SchemaSyncAgent, DependencyAgent, CrossRepoValidator

plugins/                   # Custom plugins wrapping existing tools
├── just_runner.py         # Execute justfile recipes across repos
├── linkml_validator.py    # LinkML schema validation
├── oak_query.py          # Ontology Access Kit integration
├── git_integration.py     # Safe git operations
└── lock_manager.py       # Multi-Claude lock coordination

pipelines/                 # Multi-agent workflows
├── ingredient_curation_pipeline.py
└── validation_pipeline.py

workspace/                 # Runtime data (gitignored)
├── locks/                # Lock files for coordination
├── tasks/                # Task files for downstream Claudes
├── results/              # Task results from downstream Claudes
├── status/               # Status files for inter-Claude communication
└── reports/              # Generated reports

cli/                      # Click-based CLI
└── main.py              # Entry point: openclaw-cli
```

### Agent Configuration

Agents are defined in YAML (see `agents/*/*.yaml`):

```yaml
agent:
  name: validation_agent
  type: dev_workflow
  model: claude-haiku-4-5

workspace:
  allowed_paths:
    - "${CULTUREMECH_ROOT}/**/*.yaml"
  read_only: true

tools:
  - name: linkml_validator
    type: plugin
    plugin: linkml_validator

tasks:
  validate_all:
    workflow:
      - step: validate_schemas
      - step: validate_data
      - step: generate_report
```

### Plugin System

Plugins wrap existing tools and provide safe interfaces:

- **JustRunnerPlugin**: Execute justfile recipes across repositories
- **LinkMLValidatorPlugin**: Validate YAML against LinkML schemas
- **GitIntegrationPlugin**: Safe git operations (branching, status, commits)
- **OAKQueryPlugin**: Ontology term validation and search
- **LockManager**: File-based distributed locking for multi-Claude coordination

## Key Patterns

### 1. Cross-Repository Operations

Always use the orchestration layer for cross-repo operations. Never modify downstream repos directly:

```python
# ✅ CORRECT: Use plugin to execute command in downstream repo
from plugins.just_runner import JustRunnerPlugin
plugin = JustRunnerPlugin()
result = plugin.execute_recipe("culturemech", "validate-all")

# ❌ WRONG: Don't directly edit files in downstream repos
# This repo should coordinate, not execute
```

### 2. Multi-Claude Workflow

When orchestrating work for downstream Claudes:

1. Acquire lock for target repository
2. Create task file in `workspace/tasks/`
3. Monitor status files in `workspace/status/`
4. Read results from `workspace/results/`
5. Release lock

### 3. Safety Mechanisms

All operations default to safe mode:

- Read-only by default (`read_only: true` in agent configs)
- Dry-run default (`OPENCLAW_DRY_RUN_DEFAULT=true`)
- Approval required for destructive operations
- Git branches for all modifications
- Automatic backups in `workspace/.backups/`

## Configuration

### Environment Variables (.env)

```bash
ANTHROPIC_API_KEY=           # API key for programmatic LLM access
CULTUREMECH_ROOT=            # Path to CultureMech repo
MEDIAINGREDIENTMECH_ROOT=    # Path to MIM repo
COMMUNITYMECH_ROOT=          # Path to CommunityMech repo
OPENCLAW_WORKSPACE=          # Workspace directory (default: ./workspace)
```

### OpenClaw Configuration (openclaw_config.yaml)

Defines repositories, agents, plugins, and safety settings. Key sections:

- `repositories`: Paths and metadata for the 3 downstream repos
- `agents.discovery_paths`: Where to find agent YAML files
- `plugins.enabled`: Which plugins are active
- `safety`: Approval requirements and allowed operations
- `monitoring`: Logging, metrics, cost tracking

## Important Notes

1. **Never skip lock acquisition** for operations that modify downstream repositories
2. **Always release locks** in finally blocks to prevent deadlocks
3. **Check lock expiration**: Locks auto-expire after 1 hour (configurable)
4. **Use task-based communication** for coordinating downstream Claude sessions
5. **Respect repository boundaries**: Don't directly modify files in CultureMech/MediaIngredientMech/CommunityMech
6. **Hook system**: All 3 downstream repos have Claude Code hooks installed (`scripts/install_hooks.sh`)

## Common Development Workflows

### Adding a New Agent

1. Create YAML config in `agents/<type>/<name>_agent.yaml`
2. Define model, workspace, tools, and tasks
3. Test with `openclaw-cli agent run <name> --dry-run`

### Adding a New Plugin

1. Create plugin file in `plugins/<name>.py`
2. Implement plugin interface (see existing plugins)
3. Add to `openclaw_config.yaml` under `plugins.enabled`
4. Test with `openclaw-cli plugin test <name>`

### Testing Multi-Claude Coordination

1. Start orchestration: `./run_pilot_test_tasks.py --dry-run`
2. Open downstream repo in separate Claude Code session
3. Have downstream Claude process tasks from `../culturebotai-claw/workspace/tasks/`
4. Monitor results in `workspace/status/` and `workspace/results/`

## Troubleshooting

- **Lock conflicts**: Check `workspace/locks/` for stale locks. Use `scripts/check_lock.py <repo>`
- **Task failures**: Check `workspace/logs/` for detailed execution logs
- **Plugin errors**: Test individual plugins with `openclaw-cli plugin test <plugin_name>`
- **Configuration issues**: Run `openclaw-cli config validate`

## Code Review: `/dynamic-review`

`.claude/workflows/dynamic-review.js` is a **dynamic workflow** (Claude Code's script-orchestrated
multi-agent primitive) for repo-agnostic code review of a PR or branch diff. It scopes the diff and
profiles the target repo **at runtime** (reads the repo's `CLAUDE.md` + `justfile` + LinkML schema,
and an optional `.claude/review-profile.yaml`), runs that repo's **own** validators as a static gate,
reviews across dynamically-chosen dimensions (Fable 5 agents), adversarially verifies each finding,
then synthesizes a ranked report.

- **Run it**: `/dynamic-review` (current branch vs `origin/main` in the cwd repo), or pass args, e.g.
  `Run /dynamic-review on PR 90`, or `{repo, target:"PR:<n>"|"branch"|"diff:<a>..<b>"|"local", base, depth:"quick"|"standard"|"thorough", postComments}`.
- **Default = report to session.** Inline GitHub PR comments are posted only when `postComments: true`
  (uses the `gh api .../pulls/<n>/comments` + suggestion-block pattern).
- The canonical copy lives at `~/.claude/workflows/dynamic-review.js` (so `/dynamic-review` works in
  every repo); this committed copy is the version-controlled source of truth — keep the two in sync.

## Documentation References

- **Architecture**: `FINAL_ARCHITECTURE_COMPLETE.md` - Complete multi-Claude coordination design
- **Coordination**: `MULTI_CLAUDE_COORDINATION.md` - Lock protocol and communication patterns
- **Status**: `PROJECT_STATUS.md` - Current implementation status
- **Setup**: `README.md` - Installation and quick start guide
