# GitHub Repository Setup for culturebotai-claw

## Repository Name
```
culturebotai-claw
```

## Description (Short - 350 char limit)
```
CultureBotAI-CLAW: Claude LLM Agent Workflow orchestration system for KG-Microbe repositories. Multi-agent coordination for automated ingredient curation, build management, and schema synchronization across CultureMech, MediaIngredientMech, and CommunityMech.
```

## About Section

**Topics/Tags** (add these to help discoverability):
```
claude
llm
ai-agents
workflow-orchestration
knowledge-graph
microbiology
ontology
linkml
multi-agent-system
automation
python
culture-media
microbiome
```

## README.md Header Enhancement

Add this badge section at the top of README.md:

```markdown
# CultureBotAI-CLAW

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Powered by Claude](https://img.shields.io/badge/Powered%20by-Claude%204.6-5A67D8.svg)](https://www.anthropic.com/claude)

**CLAW** = **C**laude **L**LM **A**gent **W**orkflow

Multi-agent orchestration system for automated development workflows across KG-Microbe repositories.
```

## Repository Settings

**Visibility**: Public (recommended) or Private

**Features to Enable**:
- ✅ Issues (for bug tracking and feature requests)
- ✅ Discussions (for community Q&A)
- ✅ Wiki (for extended documentation)
- ✅ Projects (for roadmap tracking)

**Branch Protection** (for main branch):
- ✅ Require pull request reviews
- ✅ Require status checks to pass
- ✅ Require branches to be up to date

## LICENSE File

Recommended: MIT License

```markdown
MIT License

Copyright (c) 2026 KG-Microbe Project

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## CONTRIBUTING.md

```markdown
# Contributing to CultureBotAI-CLAW

Thank you for your interest in contributing!

## Development Setup

1. Clone the repository
2. Install dependencies: `uv sync`
3. Configure `.env` with your settings
4. Read `QUICKSTART.md` for workflow guidance

## Adding New Agents

See `agents/` directory for examples. Each agent needs:
- YAML configuration file
- Clear task definitions
- Safety mechanisms (dry-run, backups)
- Documentation

## Code Style

- Python: Black formatting
- YAML: 2-space indentation
- Documentation: Markdown

## Testing

Run tests before submitting PR:
```bash
pytest tests/
python validate_setup.py
```

## Questions?

Open an issue or start a discussion!
```

## Pull Request Template

Create `.github/pull_request_template.md`:

```markdown
## Description

Brief description of changes

## Type of Change

- [ ] Bug fix
- [ ] New agent
- [ ] New plugin
- [ ] Documentation update
- [ ] Configuration change

## Testing

- [ ] Tested locally
- [ ] Validation passes
- [ ] Documentation updated

## Related Issues

Fixes #(issue number)
```

## Issue Templates

Create `.github/ISSUE_TEMPLATE/bug_report.md` and `feature_request.md`

## Social Preview Image

Suggested dimensions: 1280x640 pixels
Text: "CultureBotAI-CLAW" with subtitle "Multi-Agent Orchestration for KG-Microbe"

---

## Quick Commands to Push to GitHub

```bash
# After creating the GitHub repo at github.com/YOUR_USERNAME/culturebotai-claw

cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw

# Add remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/culturebotai-claw.git

# Verify remote
git remote -v

# Push to GitHub
git push -u origin main

# View on GitHub
# Visit: https://github.com/YOUR_USERNAME/culturebotai-claw
```

## Post-Push Checklist

After pushing:

1. ✅ Add repository description and topics
2. ✅ Create LICENSE file (via GitHub interface or locally)
3. ✅ Enable Issues and Discussions
4. ✅ Add CONTRIBUTING.md
5. ✅ Create issue/PR templates in `.github/`
6. ✅ Add social preview image (Settings → General → Social Preview)
7. ✅ Update repository settings (Settings → General)
8. ✅ Create initial GitHub Project for Week 6 roadmap

---

## Example GitHub URL

If hosted under user `marcin-osi`:
```
https://github.com/marcin-osi/culturebotai-claw
```

If under organization `kg-microbe`:
```
https://github.com/kg-microbe/culturebotai-claw
```
