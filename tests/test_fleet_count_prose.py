"""Maintained prose may not state a bare Mech count that the manifest contradicts.

#131 item 3. A written-out fleet size goes stale the moment the fleet changes,
and it did: the plan records that "the definition of the fleet varies between
three, four, and five Mechs" across this repository.

A count is allowed when its BASIS is stated -- a capability scope, or an
explicit scientific input set -- because then it is a claim about something
real rather than a duplicate of the manifest.

Full-fleet claims should carry no number at all: "every Mech" cannot go stale,
where "all five Mechs" silently becomes wrong the day a sixth arrives. Those
were rewritten rather than annotated.
"""

from __future__ import annotations

import re
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]

# Maintained surfaces only. Archived reports, dated reviews, and proposals are
# historical records: a count in them was true when written and rewriting it
# would falsify the record.
MAINTAINED = (
    "CLAUDE.md",
    "README.md",
    "docs/README.md",
    "docs/guides",
    ".claude/skills",
    ".claude/commands",
    # #131 item 3 says "maintained prose AND package docstrings". Leaving src/
    # out let "all five repositories" sit in the governance audit's own
    # docstrings, beside a hardcoded EXPECTED_MECH_COUNT = 5.
    "src",
    "cli",
    "plugins",
    "pipelines",
)
EXCLUDED = ("docs/archive", "docs/reviews", "docs/proposals")

# "one Mech" is not a fleet count ("a change must exist in more than one Mech"),
# so counting starts at two.
# "N repos" is the same claim as "N Mechs" and was missed by a pattern that
# only looked for the word Mech: `unmapped-inventory` said "all four repos"
# twice while its script read the set from a capability.
_NUMBER = r"(?:two|three|four|five|six|[2-9]|\d\d+)"
_COUNT = re.compile(
    # "N Mechs" is always a claim about the fleet.
    rf"\b{_NUMBER}[- ](?:Mechs?)\b"
    # "N repos" is only one when it says ALL of them. boss/SKILL.md warns
    # against "modifying two repos at once from the same worktree", which is a
    # claim about an action, not about how many exist.
    rf"|\ball\s+{_NUMBER}\s+(?:repos|repositories|checkouts)\b",
    re.IGNORECASE,
)
# A count whose basis is stated nearby is a claim about something real.
_BASIS = re.compile(
    r"capabilit|declares?\b|not_applicable|input set|manifest|enabled",
    re.IGNORECASE,
)


def _maintained_files() -> list[Path]:
    files: list[Path] = []
    for entry in MAINTAINED:
        target = ROOT / entry
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(sorted(target.rglob("*.md")))
            files.extend(sorted(target.rglob("*.py")))
    return [
        path
        for path in files
        if not any(part in str(path.relative_to(ROOT)) for part in EXCLUDED)
    ]


def test_maintained_prose_states_the_basis_of_any_mech_count():
    offenders: list[str] = []
    for path in _maintained_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if not _COUNT.search(line):
                continue
            window = "\n".join(lines[max(0, number - 4) : number + 3])
            if not _BASIS.search(window):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")

    assert not offenders, (
        "a Mech count is stated without its basis; say which capability or "
        "input set it describes, or point at the manifest:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_examines_a_non_trivial_number_of_files():
    """Otherwise a path change would silently make this pass over nothing."""
    files = _maintained_files()

    assert len(files) >= 10, f"only {len(files)} maintained files found"
    assert any(path.name == "CLAUDE.md" for path in files)


def test_the_fleet_size_the_prose_describes_is_the_manifest_size():
    """Pins the number the accurate prose uses to the manifest, so a Mech added
    or removed makes the documentation demonstrably wrong rather than quietly
    so."""
    assert len(load_fleet_manifest().mechs) == 5


def test_no_module_hardcodes_the_fleet_size_as_a_constant():
    """A count is a list of one number, and goes stale the same way.

    `EXPECTED_MECH_COUNT = 5` in the governance audit would have rejected a
    correct consumer set the day a sixth Mech was declared -- and accepted a
    wrong one of the right size before then.
    """
    pattern = re.compile(
        r"^[A-Z_]*(?:MECH|FLEET)[A-Z_]*(?:COUNT|SIZE|N)\s*=\s*\d+", re.MULTILINE
    )
    offenders = [
        f"{path.relative_to(ROOT)}: {pattern.search(text).group(0)}"
        for path in sorted((ROOT / "src").rglob("*.py"))
        if pattern.search(text := path.read_text(encoding="utf-8"))
    ]

    assert not offenders, (
        "derive the fleet size from the manifest instead:\n  "
        + "\n  ".join(offenders)
    )


def test_the_governance_manifest_covers_exactly_the_declared_fleet():
    """The invariant the hardcoded count was standing in for, and a stronger
    one: two manifests describing different fleets is the actual failure."""
    from kg_microbe_governance import load_governance_manifest
    from kg_microbe_governance.fleet_audit import expected_mechs

    assert set(load_governance_manifest().consumers) == set(expected_mechs())
