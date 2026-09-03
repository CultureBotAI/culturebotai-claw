"""The fleet-wide skill inventory.

Every fixture here is a real git repository, because the module's contract is
that git decides what a repository carries. A fixture built from the
filesystem would pass whether or not that rule were implemented, which is the
failure mode this repository keeps finding in its own tests (#286).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kg_microbe_skills.inventory import (
    UnreadableSkill,
    build_inventory,
    format_inventory,
    read_repository,
    repositories_without_skills,
)


def _repo(root: Path, skills: dict[str, str], *, untracked: dict[str, str] | None = None) -> Path:
    """A checkout carrying `skills`, and optionally some untracked ones."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for name, body in skills.items():
        directory = root / ".claude" / "skills" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "s"],
        cwd=root,
        check=True,
    )
    for name, body in (untracked or {}).items():
        directory = root / ".claude" / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(body, encoding="utf-8")
    return root


@pytest.fixture
def fleet(tmp_path: Path) -> dict[str, Path]:
    """Three checkouts holding every case at once.

    `shared` is byte-identical in alpha and beta and different in gamma, so a
    grouping that reported "all copies" and one that reported "copies sharing a
    digest" cannot both be right. `spread` is carried by all three and no two
    alike, which is the only input separating a divergent group from a
    duplicated one -- without it both verdicts are reachable by the same
    fixture and the distinction is untested. `solo` is carried once. `both` is
    identical in two and is also canonical, the one input that separates the
    canonical verdict from the duplicated one.
    """
    return {
        "alpha": _repo(
            tmp_path / "alpha",
            {
                "shared": "same\n",
                "spread": "one\n",
                "both": "x\n",
                "solo": "only here\n",
            },
        ),
        "beta": _repo(
            tmp_path / "beta",
            {"shared": "same\n", "spread": "two\n", "both": "x\n"},
        ),
        "gamma": _repo(
            tmp_path / "gamma",
            {"shared": "different text entirely\n", "spread": "three\n"},
        ),
    }


def test_git_decides_what_a_repository_carries(tmp_path: Path):
    """An untracked skill is one developer's working tree, not the repository."""
    root = _repo(
        tmp_path / "r",
        {"tracked": "a\n"},
        untracked={"scratch": "b\n"},
    )
    assert (root / ".claude/skills/scratch/SKILL.md").is_file()
    assert sorted(read_repository(root)) == ["tracked"]


def test_identical_copies_are_named_and_divergent_ones_are_not(fleet):
    """The distinction the inventory exists for. `shared` is identical in two
    of three repositories; naming all three would be the same answer as naming
    none, so the fixture makes gamma differ."""
    groups = {g.name: g for g in build_inventory(fleet)}
    assert groups["shared"].identical == ("alpha", "beta")
    assert groups["shared"].verdict == "duplicated"

    # Same reach, same three repositories, no two alike. Only the digests
    # differ, so this is what the verdict is actually reading.
    assert groups["spread"].reach == groups["shared"].reach == 3
    assert groups["spread"].identical == ()
    assert groups["spread"].verdict == "divergent"

    assert groups["solo"].identical == ()
    assert groups["solo"].verdict == "single"


def test_a_canonical_template_outranks_the_duplication_it_explains(fleet):
    """`both` is byte-identical in two repositories either way. Declaring it
    canonical is what changes the verdict, so the two sides of this differ on
    the same input."""
    without = {g.name: g for g in build_inventory(fleet)}
    assert without["both"].verdict == "duplicated"

    with_template = {g.name: g for g in build_inventory(fleet, ["both"])}
    assert with_template["both"].verdict == "canonical"
    assert with_template["both"].identical == ("alpha", "beta")


def test_groups_come_back_by_reach_then_name(fleet):
    """Two runs have to diff cleanly, and the widest group is the one worth
    canonicalising first."""
    order = [(g.name, g.reach) for g in build_inventory(fleet)]
    assert order == [("shared", 3), ("spread", 3), ("both", 2), ("solo", 1)]


def test_a_repository_that_carries_nothing_is_a_finding(tmp_path: Path):
    """Distinct from a checkout that could not be resolved: this one was read."""
    empty = _repo(tmp_path / "empty", {})
    populated = _repo(tmp_path / "full", {"one": "a\n"})
    assert repositories_without_skills(
        {"empty": empty, "full": populated}
    ) == ("empty",)


def test_a_directory_that_is_not_a_checkout_reads_as_carrying_nothing(tmp_path: Path):
    """git ls-files fails outside a repository. Reporting that as "no skills"
    rather than raising keeps one unresolvable path from ending the run."""
    stray = tmp_path / "not-a-repo"
    (stray / ".claude" / "skills" / "s").mkdir(parents=True)
    (stray / ".claude" / "skills" / "s" / "SKILL.md").write_text("a\n")
    assert read_repository(stray) == {}


def test_the_report_says_which_repositories_are_locked_together(fleet):
    """A digest column alone makes the reader diff hex by eye."""
    report = format_inventory(build_inventory(fleet))
    assert "byte-identical in alpha, beta" in report
    assert "copied, not agreed" in report

    quiet = format_inventory(build_inventory(fleet, ["shared", "both"]))
    assert "byte-identical" not in quiet


def test_the_report_separates_shared_from_single_and_names_the_empty(fleet, tmp_path):
    report = format_inventory(
        build_inventory(fleet), repositories_without_skills({"e": _repo(tmp_path / "e", {})})
    )
    assert "shared across repositories (3)" in report
    assert "carried by one repository (1)" in report
    assert "carry no tracked skill at all: e" in report


def test_a_tracked_skill_that_cannot_be_read_is_fatal(tmp_path):
    """#332. Git says the repository carries it, so reporting it as absent
    would put a wrong number in every count above it -- a `duplicated` verdict
    becomes `divergent` with nothing saying an input went missing.

    The fixture makes the file genuinely unreadable rather than deleting it,
    because a deleted file and an unreadable one are different states and only
    one of them is this error.
    """
    root = _repo(tmp_path / "r", {"one": "a\n", "two": "b\n"})
    unreadable = root / ".claude/skills/one/SKILL.md"
    unreadable.chmod(0o000)
    try:
        with pytest.raises(UnreadableSkill) as caught:
            read_repository(root)
        assert ".claude/skills/one/SKILL.md" in str(caught.value)
        assert "one" in str(caught.value)
    finally:
        unreadable.chmod(0o644)

    # Readable again, and the skill is back: the error was about the read, not
    # about the repository's contents.
    assert sorted(read_repository(root)) == ["one", "two"]
