# Quick Start Guide

## Installation Complete ✅

The OpenClaw orchestration layer for KG-Microbe has been successfully installed!

**Location**: `/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw`

---

## Immediate Next Steps

### 1. Add Your Anthropic API Key (Required)

Edit the `.env` file and add your API key:

```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
nano .env  # or use your preferred editor
```

Add your key:
```bash
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
```

### 2. Verify Installation

Run the validation script:
```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
.venv/bin/python validate_setup.py
```

### 3. Test the CLI

```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw

# Check system status
.venv/bin/openclaw-cli status

# List available agents
.venv/bin/openclaw-cli agent list

# List available plugins
.venv/bin/openclaw-cli plugin list

# Test a plugin
.venv/bin/openclaw-cli plugin test just_runner

# Show configuration
.venv/bin/openclaw-cli config show
```

### 4. (Optional) Add to Your PATH

To use `openclaw-cli` without the `.venv/bin/` prefix:

```bash
# Add to your ~/.bashrc or ~/.zshrc
export PATH="/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/.venv/bin:$PATH"

# Then reload your shell
source ~/.bashrc  # or source ~/.zshrc
```

After this, you can use just:
```bash
openclaw-cli status
```

---

## What Was Installed

### Agents (2)
- **ValidationAgent** - Schema and ontology validation across all repos
- **DocumentationAgent** - Generate docs, update READMEs, create API documentation

### Plugins (3)
- **JustRunnerPlugin** - Execute justfile recipes across repositories
- **LinkMLValidatorPlugin** - Validate YAML data against LinkML schemas
- **GitIntegrationPlugin** - Safe git operations for agent-managed changes

### CLI Commands
- `agent list/run` - Manage and execute agents
- `pipeline list/run` - Manage and execute pipelines
- `plugin list/test` - Manage plugins
- `config show/validate` - Configuration management
- `status` - Show system status

---

## Testing the Setup

### Test 1: Check System Status
```bash
.venv/bin/openclaw-cli status
```

**Expected output**: All three repos found (CultureMech, MediaIngredientMech, CommunityMech), 2 agents, 3 plugins

### Test 2: List Justfile Recipes
Using the JustRunnerPlugin, you can list recipes in any repo:

```python
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw
.venv/bin/python -c "
from dotenv import load_dotenv
load_dotenv()
from plugins.just_runner import JustRunnerPlugin
plugin = JustRunnerPlugin()
result = plugin.list_recipes('culturemech')
print(result['recipes'] if result['success'] else 'Error')
"
```

### Test 3: Check Git Status
```python
.venv/bin/python -c "
from dotenv import load_dotenv
load_dotenv()
from plugins.git_integration import GitIntegrationPlugin
plugin = GitIntegrationPlugin()
result = plugin.get_status('culturemech')
print('Current branch:', result.get('branch'))
print('Is dirty:', result.get('is_dirty'))
"
```

---

## Directory Overview

```
culturebotai-claw/
├── .env                          ← ADD YOUR API KEY HERE
├── openclaw_config.yaml          ← Main configuration
├── README.md                     ← Full documentation
├── QUICKSTART.md                 ← This file
├── WEEK1_COMPLETION.md          ← What was completed
├── validate_setup.py            ← Validation script
│
├── agents/                       ← Agent definitions
│   ├── code_development/
│   │   └── documentation_agent.yaml
│   └── dev_workflow/
│       └── validation_agent.yaml
│
├── plugins/                      ← Custom plugins
│   ├── just_runner.py
│   ├── linkml_validator.py
│   └── git_integration.py
│
├── cli/                          ← CLI interface
│   └── main.py
│
└── workspace/                    ← Agent workspaces (gitignored)
```

---

## Common Tasks

### Check if a Plugin Works
```bash
.venv/bin/openclaw-cli plugin test just_runner
.venv/bin/openclaw-cli plugin test linkml_validator
.venv/bin/openclaw-cli plugin test git_integration
```

### View Current Configuration
```bash
.venv/bin/openclaw-cli config show
```

### Validate Configuration
```bash
.venv/bin/openclaw-cli config validate
```

### List All Agents
```bash
.venv/bin/openclaw-cli agent list
```

---

## Week 2-3 Preview

Coming next:
1. **ETLCoordinatorAgent** - Automate cross-repo data flows
2. **IngredientCurationAgent** - LLM-assisted ingredient mapping
3. **NetworkRepairAgent** - Wrap existing network repair code
4. **Ingredient Curation Pipeline** - End-to-end automation
5. **OAKQueryPlugin** - Ontology Access Kit integration

---

## Troubleshooting

### "Command not found: openclaw-cli"
Use the full path: `.venv/bin/openclaw-cli` or add to PATH (see step 4 above)

### "ANTHROPIC_API_KEY not set"
Edit `.env` and add your API key

### "Repository not found"
Check that the paths in `.env` are correct:
```bash
.venv/bin/openclaw-cli config show
```

### Plugin test fails
Make sure `.env` is loaded. Run validation:
```bash
.venv/bin/python validate_setup.py
```

---

## Resources

- **Full Documentation**: `README.md`
- **Week 1 Summary**: `WEEK1_COMPLETION.md`
- **Main Plan**: See `.claude/` directory in parent repos
- **Agent Configurations**: `agents/` directory
- **Plugin Source**: `plugins/` directory

---

## Support

For issues:
1. Run the validation script: `.venv/bin/python validate_setup.py`
2. Check configuration: `.venv/bin/openclaw-cli config validate`
3. Review README.md for detailed documentation
4. Check WEEK1_COMPLETION.md for implementation details

---

**Status**: Week 1 Foundation Complete ✅

**Ready for**: Week 2-3 Core Agent Implementation

---

## Quick Reference Card

```bash
# Navigate to orchestration directory
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw

# Activate virtual environment (not needed - use .venv/bin/ prefix)
# OR add to PATH in step 4 above

# Validate setup
.venv/bin/python validate_setup.py

# Show status
.venv/bin/openclaw-cli status

# List agents
.venv/bin/openclaw-cli agent list

# List plugins
.venv/bin/openclaw-cli plugin list

# Test plugin
.venv/bin/openclaw-cli plugin test just_runner

# Show config
.venv/bin/openclaw-cli config show

# Validate config
.venv/bin/openclaw-cli config validate
```

**Don't forget**: Add your Anthropic API key to `.env`!
