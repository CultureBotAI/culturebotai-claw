"""What each skill is for, and which Mechs need an adapter (#132 Phase 4).

"General" used to be five names hardcoded in a test -- invisible to anything
else, and drifting silently as skills were added. This replaces that with a
packaged declaration, loaded fail-closed in both directions: a skill on disk
that the catalogue does not name is an error, and so is a catalogue entry with
no skill.

Rendering is what makes a `mech`-scoped skill reusable. The canonical text
carries `{{ placeholders }}` filled from the manifest, so a Mech's adapter is
derived from the fleet definition rather than hand-copied and left to rot. The
applicable set comes from a capability, not a list here, because a list would
be wrong the moment a Mech gained or lost the capability.

This module renders; it does not write. Installing an adapter into a Mech
checkout is a downstream mutation and goes through the cross-repository
checklist, under approval, as its own change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from kg_microbe_fleet import FleetManifest, load_fleet_manifest

__all__ = [
    "CANONICAL_DIR",
    "SCOPES",
    "CanonicalSkill",
    "CatalogueError",
    "SkillEntry",
    "applicable_mechs",
    "canonical_text",
    "load_canonical",
    "load_catalogue",
    "render_adapter",
    "skill_placeholders",
]

CATALOGUE_PATH = Path(__file__).resolve().parent / "skills.yaml"
CANONICAL_DIR = Path(__file__).resolve().parent / "canonical"

SCOPES = ("claw", "fleet", "domain")

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class CatalogueError(RuntimeError):
    """The catalogue and the skills on disk disagree, or an entry is malformed."""


@dataclass(frozen=True)
class SkillEntry:
    """One skill living in this repository."""

    name: str
    scope: str
    reason: str


@dataclass(frozen=True)
class CanonicalSkill:
    """A template rendered into an adapter for each applicable Mech."""

    name: str
    capability: str
    reason: str


def load_catalogue(
    path: Path | None = None, skills_dir: Path | None = None
) -> dict[str, SkillEntry]:
    """Every skill, checked against what is actually on disk.

    Fail-closed both ways. A skill added without an entry would otherwise be
    silently ungoverned, and an entry left behind after a skill was deleted
    would describe nothing -- which is how the hardcoded set this replaces went
    stale without anyone noticing.
    """
    path = path or CATALOGUE_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogueError(f"cannot read skill catalogue {path}: {exc}") from exc

    if not isinstance(raw, dict) or "skills" not in raw:
        raise CatalogueError(f"{path} has no `skills` mapping")

    unknown = set(raw) - {"version", "skills", "canonical"}
    if unknown:
        raise CatalogueError(f"{path} has unknown top-level keys: {sorted(unknown)}")

    entries: dict[str, SkillEntry] = {}
    for name, spec in (raw["skills"] or {}).items():
        if not isinstance(spec, dict):
            raise CatalogueError(f"{name}: entry must be a mapping")
        extra = set(spec) - {"scope", "reason"}
        if extra:
            raise CatalogueError(f"{name}: unknown keys {sorted(extra)}")
        scope = spec.get("scope")
        if scope not in SCOPES:
            raise CatalogueError(
                f"{name}: scope {scope!r} is not one of {', '.join(SCOPES)}"
            )
        if not (spec.get("reason") or "").strip():
            raise CatalogueError(
                f"{name}: needs a reason -- a scope with no stated why is a "
                f"guess the next reader cannot check"
            )
        entries[name] = SkillEntry(name, scope, spec["reason"].strip())

    if skills_dir is None:
        skills_dir = Path(__file__).resolve().parents[2] / ".claude" / "skills"
    if skills_dir.is_dir():
        present = {p.name for p in skills_dir.iterdir() if p.is_dir()}
        missing = sorted(present - set(entries))
        if missing:
            raise CatalogueError(
                f"skills with no catalogue entry: {', '.join(missing)}"
            )
        absent = sorted(set(entries) - present)
        if absent:
            raise CatalogueError(
                f"catalogue entries with no skill: {', '.join(absent)}"
            )
    return entries


def load_canonical(
    path: Path | None = None, canonical_dir: Path | None = None
) -> dict[str, CanonicalSkill]:
    """The templates, checked against the template files on disk.

    Fail-closed both ways, like the catalogue: a template with no declaration
    is ungoverned, and a declaration with no template renders nothing while
    reading as though it renders something.
    """
    path = path or CATALOGUE_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    declared: dict[str, CanonicalSkill] = {}
    for name, spec in (raw.get("canonical") or {}).items():
        if not isinstance(spec, dict):
            raise CatalogueError(f"canonical {name}: entry must be a mapping")
        extra = set(spec) - {"capability", "reason"}
        if extra:
            raise CatalogueError(f"canonical {name}: unknown keys {sorted(extra)}")
        if not (spec.get("capability") or "").strip():
            raise CatalogueError(
                f"canonical {name}: must name the capability that decides which "
                f"Mechs get an adapter, so the set comes from the manifest"
            )
        if not (spec.get("reason") or "").strip():
            raise CatalogueError(f"canonical {name}: needs a reason")
        declared[name] = CanonicalSkill(
            name, spec["capability"].strip(), spec["reason"].strip()
        )

    canonical_dir = canonical_dir or CANONICAL_DIR
    if canonical_dir.is_dir():
        present = {p.stem for p in canonical_dir.glob("*.md")}
        missing = sorted(present - set(declared))
        if missing:
            raise CatalogueError(
                f"canonical templates with no declaration: {', '.join(missing)}"
            )
        absent = sorted(set(declared) - present)
        if absent:
            raise CatalogueError(
                f"declared canonical skills with no template: {', '.join(absent)}"
            )
    return declared


def canonical_text(name: str, canonical_dir: Path | None = None) -> str:
    path = (canonical_dir or CANONICAL_DIR) / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogueError(f"cannot read canonical skill {path}: {exc}") from exc


def applicable_mechs(
    skill: CanonicalSkill, manifest: FleetManifest | None = None
) -> list[str]:
    """The Mechs that need an adapter for this template, from the manifest."""
    manifest = manifest or load_fleet_manifest()
    return sorted(manifest.with_capability(skill.capability))


def skill_placeholders(text: str) -> set[str]:
    """Every `{{ name }}` the canonical text expects to be filled."""
    return set(_PLACEHOLDER.findall(text))


def render_adapter(
    text: str, mech_key: str, manifest: FleetManifest | None = None
) -> str:
    """Fill a canonical skill's placeholders from one Mech's manifest entry.

    An unknown placeholder raises rather than being left in the output: an
    adapter shipped with a literal `{{ typo }}` in it reads as a rendering that
    worked, and the reader has no way to tell it did not.
    """
    manifest = manifest or load_fleet_manifest()
    if mech_key not in manifest.mechs:
        raise CatalogueError(
            f"unknown Mech {mech_key!r}; the manifest declares "
            f"{', '.join(sorted(manifest.mechs))}"
        )
    mech = manifest.mechs[mech_key]

    values = {
        "mech_key": mech_key,
        "display_name": mech.display_name,
        "github": mech.github,
        "environment_variable": mech.environment_variable,
        "package_path": mech.package_path,
        "schema_paths": ", ".join(f"`{p}`" for p in mech.schema_paths),
        "record_globs": ", ".join(f"`{p}`" for p in mech.record_globs),
    }

    unknown = skill_placeholders(text) - set(values)
    if unknown:
        raise CatalogueError(
            f"{mech_key}: no manifest value for {', '.join(sorted(unknown))}; "
            f"available: {', '.join(sorted(values))}"
        )
    return _PLACEHOLDER.sub(lambda m: values[m.group(1).strip()], text)
