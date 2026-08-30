"""What a repository costs to carry (#132 Phase 6, item 4).

The criterion pairs corpus reports with repository-health ones. A corpus report
says what the curated data looks like; this says how many files are tracked, how
large, where the weight sits, and which files dominate.

Measured from git, not the filesystem. Tracked content is the same on every
machine and in CI, where a working tree carries caches, build output and
whatever the last run left behind -- #203's rule, and what makes two Mechs'
reports comparable at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_microbe_health import HealthError, measure

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path, tracked: dict[str, int], untracked: dict[str, int] = {}) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=root, check=True, capture_output=True
    )
    run("init", "-q")
    run("config", "user.email", "t@example.invalid")
    run("config", "user.name", "t")
    for name, size in {**tracked, **untracked}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    for name in tracked:
        run("add", "--", name)
    if tracked:
        run("commit", "-qm", "seed")
    return root


def test_tracked_files_and_bytes_are_counted(tmp_path):
    root = _repo(tmp_path, {"a.txt": 10, "d/b.txt": 20})

    report = measure("m", root)

    assert report.tracked_files == 2
    assert report.tracked_bytes == 30


def test_untracked_files_are_not_counted(tmp_path):
    """A working tree carries caches and build output; CI's does not. Counting
    them would make the same repository report differently by machine."""
    root = _repo(tmp_path, {"a.txt": 10}, untracked={"build/huge.bin": 10_000})

    report = measure("m", root)

    assert report.tracked_files == 1
    assert report.tracked_bytes == 10


def test_weight_is_attributed_to_the_top_level_directory(tmp_path):
    """Where growth is decided: a directory nobody meant to commit shows up
    here before it shows up anywhere else."""
    root = _repo(tmp_path, {"data/a": 100, "data/sub/b": 50, "docs/c": 25, "top": 5})

    report = measure("m", root)

    assert report.by_directory["data"] == {"files": 2, "bytes": 150}
    assert report.by_directory["docs"] == {"files": 1, "bytes": 25}
    assert report.by_directory["(root)"] == {"files": 1, "bytes": 5}


def test_weight_is_also_attributed_by_extension(tmp_path):
    """429,271 YAML records at 2.5 KB each and one 12 MB JSON are different
    problems; a byte total alone cannot tell them apart."""
    root = _repo(tmp_path, {"a.yaml": 10, "b.yaml": 20, "c.json": 500, "d": 1})

    report = measure("m", root)

    assert report.by_extension[".yaml"] == {"files": 2, "bytes": 30}
    assert report.by_extension[".json"] == {"files": 1, "bytes": 500}
    assert report.by_extension["(none)"] == {"files": 1, "bytes": 1}


def test_the_largest_files_are_reported_biggest_first(tmp_path):
    root = _repo(tmp_path, {"a": 10, "b": 300, "c": 200})

    largest = measure("m", root, largest=2).largest_files

    assert largest == [{"path": "b", "bytes": 300}, {"path": "c", "bytes": 200}]


def test_ties_among_largest_files_are_broken_by_path(tmp_path):
    """Otherwise the same repository reports a different list run to run."""
    root = _repo(tmp_path, {"b": 100, "a": 100, "c": 100})

    largest = measure("m", root, largest=3).largest_files

    assert [f["path"] for f in largest] == ["a", "b", "c"]


def test_the_largest_list_is_correct_when_it_must_be_trimmed(tmp_path):
    """The scan keeps a bounded buffer rather than every path. An off-by-one
    there silently drops the actual biggest file."""
    root = _repo(tmp_path, {f"f{n:03}": n for n in range(1, 200)})

    largest = measure("m", root, largest=3).largest_files

    assert [f["bytes"] for f in largest] == [199, 198, 197]


def test_large_files_are_counted_against_a_threshold(tmp_path):
    root = _repo(tmp_path, {"small": 10, "big": 5_000_000, "bigger": 9_000_000})

    report = measure("m", root, large_file_bytes=5_000_000)

    assert report.large_files == 2, "a file exactly at the threshold counts"


def test_a_directory_that_is_not_a_checkout_is_refused(tmp_path):
    with pytest.raises(HealthError, match="not a git checkout"):
        measure("m", tmp_path)


def test_an_empty_repository_reports_zero_rather_than_failing(tmp_path):
    """A repository with no commit is a real state, not an error."""
    root = tmp_path / "empty"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)

    report = measure("m", root)

    assert report.tracked_files == 0
    assert report.largest_files == []


def test_the_report_is_deterministic_and_carries_no_absolute_paths(tmp_path):
    root = _repo(tmp_path, {"d/b": 2, "d/a": 1})

    first = measure("m", root).to_json()

    assert first == measure("m", root).to_json()
    assert str(root) not in first
    assert json.loads(first)["mech"] == "m"


def test_this_repository_reports_itself():
    """The end-to-end path, on a checkout that certainly exists."""
    report = measure("claw", ROOT)

    assert report.tracked_files > 100
    assert report.tracked_bytes > 0
    assert "src" in report.by_directory


def test_a_submodule_entry_is_not_counted_as_a_file(tmp_path):
    """`git ls-tree` lists a submodule as a `commit` whose size column is `-`.
    Parsing that as a blob makes the size field non-numeric, and counting it
    would add a file that has no bytes here at all -- its content lives in
    another repository."""
    root = _repo(tmp_path, {"a.txt": 10})
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/thing"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "add gitlink"], cwd=root, check=True, capture_output=True
    )

    listed = subprocess.run(
        ["git", "ls-tree", "-r", "-l", "HEAD"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    assert "160000 commit" in listed, "the fixture must actually contain a gitlink"

    report = measure("m", root)

    assert report.tracked_files == 1
    assert "vendor" not in report.by_directory
