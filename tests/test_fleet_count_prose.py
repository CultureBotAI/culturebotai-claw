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
)
EXCLUDED = ("docs/archive", "docs/reviews", "docs/proposals")

# "one Mech" is not a fleet count ("a change must exist in more than one Mech"),
# so counting starts at two.
_COUNT = re.compile(
    r"\b(?:two|three|four|five|six|[2-9]|\d\d+)[- ](?:Mech|mech)",
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
