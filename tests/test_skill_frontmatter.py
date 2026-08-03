"""Every SKILL.md must carry loadable frontmatter.

Written after two real breakages found the same day:

  - `boss/SKILL.md` had `argument-hint: [ "curate" | "enrich" | ... ]`, an
    unquoted YAML flow sequence containing `|`. Invalid since it was added.
  - A new skill's `description` contained "Read-only: never merges", and the
    `: ` turned the rest of the line into a nested mapping.

Both are silent: the file looks fine, renders fine on GitHub, and fails only
in whatever loads it. A parse is cheap; leaving it to discovery is not.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parents[1] / ".claude" / "skills"

SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _frontmatter(path: Path) -> str:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path} does not open with a --- fence"
    parts = text.split("---\n")
    assert len(parts) >= 3, f"{path} has no closing --- fence"
    return parts[1]


def test_there_are_skills_to_check():
    """Guard the guard: a glob that matches nothing passes every test below."""
    assert len(SKILL_FILES) >= 15, f"only found {len(SKILL_FILES)} SKILL.md files"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_valid_yaml(path: Path):
    meta = yaml.safe_load(_frontmatter(path))
    assert isinstance(meta, dict), f"{path} frontmatter is not a mapping"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_name_matches_its_directory(path: Path):
    """The loader keys on the directory; a mismatched name: is a silent alias."""
    meta = yaml.safe_load(_frontmatter(path))
    assert meta.get("name") == path.parent.name


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_declares_a_usable_description(path: Path):
    """The description is what a model matches a request against."""
    meta = yaml.safe_load(_frontmatter(path))
    description = meta.get("description")
    assert isinstance(description, str) and description.strip(), (
        f"{path} has no usable description"
    )
