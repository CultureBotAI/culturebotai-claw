"""`kg-microbe-skills inventory` -- what skills the fleet actually carries.

`catalogue` answers what claw owns: its own skills and the canonical templates
it publishes. That is half the picture. The other half is what each Mech has
independently, and it is the half that decides what is worth canonicalising
next -- a name eight repositories spell differently is a different problem
from a name three of them carry byte-identically.

Byte-identical copies are the signal this exists for. Two repositories that
arrive at the same 72 lines did not agree; one was copied from the other, and
nothing since has kept them together. That is what a canonical template with
managed regions is for, and until one exists the duplication is unmanaged.

Existence is decided by git, matching `references`: an untracked skill
directory in one developer's working tree is not something the repository
carries, and the inventory has to read the same on a laptop and in CI.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = ".claude/skills"
SKILL_FILE = "SKILL.md"


class UnreadableSkill(RuntimeError):
    """Git tracks the file and it could not be read.

    Distinct from both absences this module models on purpose -- a checkout
    that would not resolve, and a repository read and genuinely carrying
    nothing. Here the repository *does* carry the skill and the run cannot say
    what it contains, so the count above it is missing an input rather than
    measuring one. Reported and fatal, matching `kg-microbe-corpus report`
    rather than swallowing a partial failure into a clean answer (#332).
    """


@dataclass(frozen=True)
class SkillCopy:
    """One repository's copy of one skill."""

    repository: str
    digest: str
    lines: int


@dataclass(frozen=True)
class SkillGroup:
    """Every copy of one skill name, across the repositories that carry it."""

    name: str
    copies: tuple[SkillCopy, ...]
    canonical: bool

    @property
    def reach(self) -> int:
        return len(self.copies)

    @property
    def identical(self) -> tuple[str, ...]:
        """Repositories sharing a digest with at least one other.

        Reported rather than counted: which repositories are locked together
        is the actionable part, and a group can hold more than one such set.
        """
        seen: dict[str, list[str]] = {}
        for copy in self.copies:
            seen.setdefault(copy.digest, []).append(copy.repository)
        return tuple(
            sorted(
                name
                for names in seen.values()
                if len(names) > 1
                for name in names
            )
        )

    @property
    def verdict(self) -> str:
        if self.canonical:
            return "canonical"
        if self.identical:
            return "duplicated"
        if self.reach > 1:
            return "divergent"
        return "single"


def _tracked_skill_files(root: Path) -> set[str]:
    """Skill files git tracks under `.claude/skills`, as repo-relative paths."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", SKILLS_DIR],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {
        entry
        for entry in result.stdout.split("\0")
        if entry.endswith(f"/{SKILL_FILE}")
    }


def read_repository(root: Path) -> dict[str, SkillCopy]:
    """Every tracked skill in one checkout, by skill name.

    Raises `UnreadableSkill` when git tracks a skill whose bytes cannot be
    read. The digest is the point, so there is nothing to fall back to, and a
    skill silently missing from one column turns a `duplicated` verdict into a
    `divergent` one with no sign that a number is missing an input.
    """
    found: dict[str, SkillCopy] = {}
    for relative in _tracked_skill_files(root):
        name = relative.split("/")[-2]
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise UnreadableSkill(
                f"{root}: git tracks {relative} but it could not be read "
                f"({exc}); the inventory would report {name} as absent from "
                f"this repository, which is not what was measured"
            ) from exc
        found[name] = SkillCopy(
            repository="",
            digest=hashlib.sha256(raw).hexdigest()[:12],
            lines=len(raw.splitlines()),
        )
    return found


def build_inventory(
    repositories: Mapping[str, Path],
    canonical_names: Iterable[str] = (),
) -> tuple[SkillGroup, ...]:
    """Group every repository's skills by name.

    Ordered by reach and then by name, so the groups worth canonicalising
    first come first and the output of two runs is comparable.
    """
    known = set(canonical_names)
    groups: dict[str, list[SkillCopy]] = {}
    for label in sorted(repositories):
        for name, copy in read_repository(repositories[label]).items():
            groups.setdefault(name, []).append(
                SkillCopy(repository=label, digest=copy.digest, lines=copy.lines)
            )
    return tuple(
        SkillGroup(
            name=name,
            copies=tuple(groups[name]),
            canonical=name in known,
        )
        for name in sorted(groups, key=lambda n: (-len(groups[n]), n))
    )


def repositories_without_skills(
    repositories: Mapping[str, Path],
) -> tuple[str, ...]:
    """Checkouts carrying no tracked skill at all.

    Distinct from a checkout that could not be resolved. This one was read and
    genuinely has none, which is a finding about the repository rather than
    about the run.
    """
    return tuple(
        label
        for label in sorted(repositories)
        if not _tracked_skill_files(repositories[label])
    )


def format_inventory(
    groups: Iterable[SkillGroup],
    empty: Iterable[str] = (),
) -> str:
    """Deterministic text: two releases of this should diff cleanly."""
    groups = tuple(groups)
    lines: list[str] = []
    shared = [g for g in groups if g.reach > 1]
    single = [g for g in groups if g.reach == 1]

    width = max((len(g.name) for g in groups), default=0)
    lines.append(f"shared across repositories ({len(shared)})")
    for group in shared:
        where = ", ".join(
            f"{c.repository}:{c.digest[:6]}/{c.lines}L" for c in group.copies
        )
        lines.append(f"  {group.reach}x  {group.verdict:<10}  {group.name:<{width}}  {where}")
        if group.identical and not group.canonical:
            lines.append(
                f"      byte-identical in {', '.join(group.identical)}: "
                f"copied, not agreed, and nothing keeps them together"
            )
    lines.append("")
    lines.append(f"carried by one repository ({len(single)})")
    for group in single:
        copy = group.copies[0]
        lines.append(f"      {group.name:<{width}}  {copy.repository}")

    if empty := tuple(empty):
        lines.append("")
        lines.append(
            f"{len(empty)} repository(ies) carry no tracked skill at all: "
            f"{', '.join(empty)}"
        )
    return "\n".join(lines)
