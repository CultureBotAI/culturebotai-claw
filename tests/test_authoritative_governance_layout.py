"""Fail closed if a retired compatibility authority is reintroduced."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _relative(*parts: str) -> str:
    return Path(*parts).as_posix()


RETIRED_PATHS = (
    _relative("shared"),
    _relative("scripts", "audit_idlabel_fleet.sh"),
    _relative("tests", "test_fleet_governance_mirror.py"),
    _relative("prompts", "backlog-loop-goal.md"),
    _relative("tests", "test_skill_frontmatter.py"),
)

# The final two names remain legitimate *downstream targets* in the canonical
# vendored-artifact manifest. Their absence as local paths is the guard; a
# repository-wide string ban would incorrectly reject the authority contract.
# The former shared subtrees and compatibility-audit files have no such live
# meaning and are rejected from operational sources as well as the filesystem.
UNIQUE_RETIRED_REFERENCES = (
    _relative("shared", "history"),
    _relative("shared", "idlabel"),
    _relative("shared", "spoke"),
    _relative("scripts", "audit_idlabel_fleet.sh"),
    _relative("tests", "test_fleet_governance_mirror.py"),
)

TEXT_SUFFIXES = {".js", ".json", ".md", ".py", ".sh", ".toml", ".yaml", ".yml"}
SCAN_ROOTS = (".claude", ".github", "docs", "scripts", "shared", "src", "tests")
ROOT_TEXT_FILES = ("CLAUDE.md", "README.md", "justfile", "pyproject.toml")


def _live_operational_text_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        scan_root = ROOT / root_name
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            if relative.parts[:2] in {("docs", "archive"), ("docs", "reviews")}:
                continue
            files.append(path)
    files.extend(ROOT / name for name in ROOT_TEXT_FILES if (ROOT / name).is_file())
    return sorted(set(files))


@pytest.mark.parametrize("relative", RETIRED_PATHS)
def test_retired_compatibility_path_is_absent(relative: str) -> None:
    path = ROOT / relative
    if path.is_dir():
        assert not any(
            candidate.is_file() for candidate in path.rglob("*")
        ), f"retired compatibility tree returned: {relative}"
    else:
        assert not path.exists(), f"retired compatibility path returned: {relative}"


def test_live_operational_sources_do_not_reference_unique_retired_paths() -> None:
    references: list[str] = []
    for path in _live_operational_text_files():
        text = path.read_text(encoding="utf-8")
        for retired in UNIQUE_RETIRED_REFERENCES:
            if retired in text:
                references.append(f"{path.relative_to(ROOT)} -> {retired}")
    assert not references, "retired compatibility references remain:\n" + "\n".join(references)
