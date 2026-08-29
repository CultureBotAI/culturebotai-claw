"""Every skill is declared, and an adapter can be rendered for each Mech.

#132 Phase 4, items 1-3. "General" was five names hardcoded inside
`tests/test_fleet_scoped_skills.py` -- invisible to anything else and drifting
silently as skills were added, which is the shape #131 is removing everywhere
else here.

The acceptance criteria this file pins:

  - one canonical general skill can be rendered for each applicable Mech; and
  - the rendered adapter passes the shared frontmatter and reference contracts.

Rendering is not installing. Writing an adapter into a Mech checkout is a
downstream mutation and goes through the cross-repository checklist, under
approval, as its own change (#180 is the same boundary for workflows).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_skills.catalogue import (
    CANONICAL_DIR,
    SCOPES,
    CatalogueError,
    applicable_mechs,
    canonical_text,
    load_canonical,
    load_catalogue,
    render_adapter,
    skill_placeholders,
)
from kg_microbe_skills.references import check, extract_references, format_report

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"


def _write_catalogue(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "skills.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# The catalogue governs what is here, in both directions
# --------------------------------------------------------------------------


def test_every_skill_on_disk_is_declared():
    catalogue = load_catalogue()
    present = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}

    assert present == set(catalogue), (
        "the catalogue and .claude/skills must agree exactly; the hardcoded set "
        "this replaces went stale precisely because nothing checked"
    )


def test_an_undeclared_skill_is_an_error(tmp_path):
    skills = tmp_path / "skills"
    (skills / "orphan").mkdir(parents=True)
    catalogue = _write_catalogue(
        tmp_path, {"version": 1, "skills": {"other": {"scope": "claw", "reason": "x"}}}
    )

    with pytest.raises(CatalogueError, match="no catalogue entry"):
        load_catalogue(catalogue, skills_dir=skills)


def test_a_declaration_with_no_skill_is_an_error(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    catalogue = _write_catalogue(
        tmp_path, {"version": 1, "skills": {"ghost": {"scope": "claw", "reason": "x"}}}
    )

    with pytest.raises(CatalogueError, match="no skill"):
        load_catalogue(catalogue, skills_dir=skills)


@pytest.mark.parametrize("scope", ["general", "", None, "mech"])
def test_an_unrecognised_scope_is_refused(tmp_path, scope):
    """`mech` was a scope until the catalogue separated governing what lives
    here from declaring what gets rendered; leaving it accepted would keep
    both meanings alive at once."""
    skills = tmp_path / "skills"
    (skills / "s").mkdir(parents=True)
    catalogue = _write_catalogue(
        tmp_path, {"version": 1, "skills": {"s": {"scope": scope, "reason": "x"}}}
    )

    with pytest.raises(CatalogueError, match="scope"):
        load_catalogue(catalogue, skills_dir=skills)


def test_a_scope_without_a_reason_is_refused(tmp_path):
    """A classification with no stated why is a guess the next reader cannot
    check, and cannot be revisited when the skill changes."""
    skills = tmp_path / "skills"
    (skills / "s").mkdir(parents=True)
    catalogue = _write_catalogue(
        tmp_path, {"version": 1, "skills": {"s": {"scope": "claw", "reason": "  "}}}
    )

    with pytest.raises(CatalogueError, match="reason"):
        load_catalogue(catalogue, skills_dir=skills)


def test_every_declared_scope_is_one_of_the_documented_ones():
    assert {entry.scope for entry in load_catalogue().values()} <= set(SCOPES)


def test_an_unknown_key_is_refused_rather_than_ignored(tmp_path):
    skills = tmp_path / "skills"
    (skills / "s").mkdir(parents=True)
    catalogue = _write_catalogue(
        tmp_path,
        {"version": 1, "skills": {"s": {"scope": "claw", "reason": "x", "typo": 1}}},
    )

    with pytest.raises(CatalogueError, match="unknown keys"):
        load_catalogue(catalogue, skills_dir=skills)


# --------------------------------------------------------------------------
# Canonical templates
# --------------------------------------------------------------------------


def test_templates_and_declarations_agree():
    canonical = load_canonical()
    present = {p.stem for p in CANONICAL_DIR.glob("*.md")}

    assert present == set(canonical)


def test_a_canonical_skill_must_name_a_capability(tmp_path):
    """The applicable set comes from the manifest. A list written here would be
    wrong the moment a Mech gained or lost the capability."""
    directory = tmp_path / "canonical"
    directory.mkdir()
    (directory / "s.md").write_text("body", encoding="utf-8")
    catalogue = _write_catalogue(
        tmp_path, {"version": 1, "skills": {}, "canonical": {"s": {"reason": "x"}}}
    )

    with pytest.raises(CatalogueError, match="capability"):
        load_canonical(catalogue, canonical_dir=directory)


def test_a_declared_template_that_does_not_exist_is_an_error(tmp_path):
    directory = tmp_path / "canonical"
    directory.mkdir()
    catalogue = _write_catalogue(
        tmp_path,
        {
            "version": 1,
            "skills": {},
            "canonical": {"s": {"capability": "testing", "reason": "x"}},
        },
    )

    with pytest.raises(CatalogueError, match="no template"):
        load_canonical(catalogue, canonical_dir=directory)


def test_the_applicable_mechs_come_from_the_manifest():
    manifest = load_fleet_manifest()
    for skill in load_canonical().values():
        assert applicable_mechs(skill) == sorted(
            manifest.with_capability(skill.capability)
        )


# --------------------------------------------------------------------------
# Rendering — the Phase 4 acceptance criteria
# --------------------------------------------------------------------------


def _rendered() -> list[tuple[str, str, str]]:
    out = []
    for name, skill in load_canonical().items():
        text = canonical_text(name)
        for mech in applicable_mechs(skill):
            out.append((name, mech, render_adapter(text, mech)))
    return out


# The adapter is the third element and is a whole document; letting pytest
# derive an id from it puts the entire skill into every failure line.
_CASES = [pytest.param(*case, id=f"{case[0]}-{case[1]}") for case in _rendered()]


def test_there_is_something_to_render():
    """Guards every parametrization below: an empty list would pass silently."""
    assert len(_rendered()) >= 5


@pytest.mark.parametrize(("name", "mech", "adapter"), _CASES)
def test_an_adapter_renders_for_each_applicable_mech(name, mech, adapter):
    assert "{{" not in adapter and "}}" not in adapter, (
        f"{name} for {mech} still carries a placeholder; an adapter shipped "
        f"with a literal {{{{ }}}} reads as a rendering that worked"
    )


@pytest.mark.parametrize(("name", "mech", "adapter"), _CASES)
def test_a_rendered_adapter_carries_loadable_frontmatter(name, mech, adapter):
    """The same contract the fleet vendors as `test_skill_frontmatter.py`: a
    description with an unquoted `: ` or a `|` in a flow sequence loads as
    something else entirely, and only whatever reads the file finds out."""
    match = re.match(r"\A---\n(.*?)\n---\n", adapter, re.DOTALL)
    assert match, f"{name} for {mech} has no frontmatter block"

    frontmatter = yaml.safe_load(match.group(1))
    assert isinstance(frontmatter, dict)
    assert frontmatter["name"] == name
    assert isinstance(frontmatter["description"], str)
    assert frontmatter["description"].strip()


@pytest.mark.parametrize(("name", "mech", "adapter"), _CASES)
def test_a_rendered_adapter_names_the_mech_it_was_rendered_for(name, mech, adapter):
    """A template that rendered but mentioned no Mech would pass every other
    check here while being identical for all five."""
    manifest = load_fleet_manifest()
    assert manifest.mechs[mech].github in adapter


@pytest.mark.parametrize(("name", "mech", "adapter"), _CASES)
def test_a_rendered_adapter_has_no_broken_reference(tmp_path, name, mech, adapter):
    """The other Phase 4 acceptance criterion, run through the real checker.

    The adapter is written into a temporary skills tree and checked there, so
    what is verified is the rendered text rather than the template.
    """
    directory = tmp_path / ".claude" / "skills" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(adapter, encoding="utf-8")

    findings = check(tmp_path)
    broken = [f for f in findings if f.verdict in ("missing", "ambiguous")]

    assert not broken, format_report(findings)


def test_an_unknown_placeholder_refuses_rather_than_rendering_it_literally():
    with pytest.raises(CatalogueError, match="no manifest value"):
        render_adapter("uses {{ nonexistent }}", "traitmech")


def test_an_unknown_mech_is_refused():
    with pytest.raises(CatalogueError, match="unknown Mech"):
        render_adapter("body", "notamech")


def test_every_placeholder_the_templates_use_is_fillable():
    """A placeholder nothing can fill would only surface when someone rendered
    that template for that Mech."""
    for name in load_canonical():
        text = canonical_text(name)
        assert skill_placeholders(text), f"{name} has no placeholders; is it canonical?"
        render_adapter(text, "traitmech")


def test_the_template_is_not_mistaken_for_a_skill():
    """Templates live outside .claude/skills precisely because a file full of
    `{{ }}` is not a runnable skill."""
    assert not (SKILLS_DIR / "review-open-issues" / "SKILL.md").read_text(
        encoding="utf-8"
    ).count("{{")
    assert extract_references(CANONICAL_DIR / "review-open-issues.md") is not None


# --------------------------------------------------------------------------
# The CLI, and the packaging it depends on
# --------------------------------------------------------------------------


def test_the_catalogue_command_lists_every_skill_and_what_renders(capsys):
    from kg_microbe_skills.__main__ import main

    assert main(["catalogue"]) == 0

    out = capsys.readouterr().out
    for name in load_catalogue():
        assert name in out, f"{name} is missing from the listing"
    for name, skill in load_canonical().items():
        assert name in out and skill.capability in out
        for mech in applicable_mechs(skill):
            assert mech in out


def test_the_render_command_prints_an_adapter(capsys):
    from kg_microbe_skills.__main__ import main

    assert main(["render", "--skill", "review-open-issues", "--mech", "traitmech"]) == 0

    out = capsys.readouterr().out
    assert "CultureBotAI/TraitMech" in out
    assert "{{" not in out


def test_the_render_command_refuses_an_unknown_mech(capsys):
    from kg_microbe_skills.__main__ import main

    assert main(["render", "--skill", "review-open-issues", "--mech", "nope"]) == 1
    assert "unknown Mech" in capsys.readouterr().err


def test_the_render_command_refuses_without_both_arguments(capsys):
    """A nonzero exit, not a printed complaint: a CLI that reports failure only
    on stdout passes every caller that checks the status code."""
    from kg_microbe_skills.__main__ import main

    assert main(["render", "--skill", "review-open-issues"]) == 2
    assert "needs --skill and --mech" in capsys.readouterr().err


def test_catalogue_and_render_work_without_a_checkout(tmp_path, monkeypatch):
    """They read packaged data. Requiring `.claude/skills` to be somewhere above
    the working directory would make them unusable from an installed wheel,
    which is the same defect #201's canary found in `check`."""
    from kg_microbe_skills.__main__ import main

    monkeypatch.chdir(tmp_path)

    assert main(["catalogue"]) == 0
    assert main(["render", "--skill", "review-open-issues", "--mech", "traitmech"]) == 0


def test_the_catalogue_and_templates_are_declared_as_package_data():
    """They are read at runtime, so a wheel without them imports fine and
    renders nothing -- the failure appears only where the package is installed
    rather than run from a checkout."""
    import tomllib

    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = declared["tool"]["setuptools"]["package-data"]

    assert set(package_data["kg_microbe_skills"]) == {
        "skills.yaml",
        "canonical/*.md",
    }
