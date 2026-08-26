"""Apply the canonical downstream skill contract to claw's real layout.

The byte-governed contract lives under ``kg_microbe_governance/artifacts`` so
that each Mech can vendor it at ``tests/test_skill_frontmatter.py``.  Its path
defaults intentionally describe that downstream layout.  Claw therefore needs
this small adapter: reuse the canonical assertions without keeping a second
root-level copy, point them at claw's actual ``.claude`` tree, and validate the
canonical nested backlog prompt rather than a compatibility mirror.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "src"
    / "kg_microbe_governance"
    / "artifacts"
    / "tests"
    / "test_skill_frontmatter.py"
)
CANONICAL_BACKLOG_PROMPT = (
    ROOT
    / "src"
    / "kg_microbe_governance"
    / "artifacts"
    / "prompts"
    / "backlog-loop-goal.md"
)


def _load_contract():
    spec = importlib.util.spec_from_file_location(
        "claw_canonical_skill_frontmatter_contract", CONTRACT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    module.SKILLS_DIR = ROOT / ".claude" / "skills"
    module.COMMANDS_DIR = ROOT / ".claude" / "commands"
    module.BACKLOG_PROMPT = CANONICAL_BACKLOG_PROMPT
    module.SKILL_FILES = module._discover_skill_files()
    module.COMMAND_FILES = sorted(module.COMMANDS_DIR.glob("*.md"))
    return module


contract = _load_contract()
SKILL_FILES = contract.SKILL_FILES
COMMAND_FILES = contract.COMMAND_FILES


def test_adapter_uses_canonical_contract_and_nested_prompt() -> None:
    assert CONTRACT_PATH.is_file()
    assert CANONICAL_BACKLOG_PROMPT.is_file()
    assert contract.BACKLOG_PROMPT == CANONICAL_BACKLOG_PROMPT
    assert CANONICAL_BACKLOG_PROMPT.parent.parent.name == "artifacts"


def test_real_claw_layout_has_skills_and_commands() -> None:
    contract.test_there_are_skills_to_check()
    assert COMMAND_FILES, "found no command files under .claude/commands"


def test_real_claw_layout_does_not_shadow_builtin_goal() -> None:
    contract.test_project_does_not_shadow_the_builtin_goal_command()


def test_canonical_nested_backlog_prompt_fits_native_goal() -> None:
    contract.test_backlog_prompt_is_plain_and_fits_native_goal()


def test_canonical_frontmatter_parser_regression_cases() -> None:
    """Keep the adapter from passing if the shared parser becomes vacuous."""
    contract.test_frontmatter_rejects_a_missing_closing_fence()
    contract.test_frontmatter_ignores_a_horizontal_rule_in_the_body()
    contract.test_frontmatter_does_not_truncate_on_an_indented_dashes_line()


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda path: path.parent.name)
def test_real_skill_satisfies_canonical_contract(path: Path) -> None:
    contract.test_skill_frontmatter_has_no_duplicate_keys(path)
    contract.test_skill_frontmatter_is_valid_yaml(path)
    contract.test_skill_name_matches_its_directory(path)
    contract.test_skill_declares_a_usable_description(path)


@pytest.mark.parametrize("path", COMMAND_FILES, ids=lambda path: path.name)
def test_real_command_satisfies_canonical_contract(path: Path) -> None:
    contract.test_command_frontmatter_has_no_duplicate_keys(path)
    contract.test_command_frontmatter_is_valid_yaml(path)
    contract.test_command_declares_a_usable_description(path)
