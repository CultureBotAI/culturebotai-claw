"""Comparable repository-health reports (#132 Phase 6, item 4).

The criterion pairs corpus reports with "repository-health" ones. A corpus
report says what the curated data looks like; this says what the repository
costs to carry -- how many files are tracked, how large, where the weight sits,
and which individual files dominate.

Measured from git, not the filesystem. Tracked content is the same on every
machine and in CI, where a working tree carries caches, build output and
whatever the last run left behind. That is #203's rule, and it is what lets one
Mech's report be compared with another's at all.

`git ls-tree -r -l HEAD` gives every blob's size in one command. The obvious
alternative -- listing files and stat-ing each -- takes one syscall per file,
which on a repository with four hundred thousand of them does not finish.
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "HealthError",
    "RepositoryReport",
    "measure",
]

DEFAULT_LARGEST = 15
DEFAULT_LARGE_FILE_BYTES = 5 * 1024 * 1024


class HealthError(RuntimeError):
    """The repository could not be measured."""


@dataclass
class RepositoryReport:
    mech: str
    tracked_files: int = 0
    tracked_bytes: int = 0
    large_file_bytes: int = DEFAULT_LARGE_FILE_BYTES
    large_files: int = 0
    by_directory: dict[str, dict[str, int]] = field(default_factory=dict)
    largest_files: list[dict[str, object]] = field(default_factory=list)
    by_extension: dict[str, dict[str, int]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """Deterministic: sorted, relative, and free of anything machine-local."""
        return {
            "mech": self.mech,
            "tracked_files": self.tracked_files,
            "tracked_bytes": self.tracked_bytes,
            "large_file_bytes": self.large_file_bytes,
            "large_files": self.large_files,
            "by_directory": dict(sorted(self.by_directory.items())),
            "by_extension": dict(sorted(self.by_extension.items())),
            "largest_files": self.largest_files,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"


def _entries(root: Path):
    """Stream (size, path) for every tracked blob at HEAD.

    Streamed rather than collected: ProteinTraitsMech tracks 431,026 files, and
    holding that listing as one string before parsing it is tens of megabytes
    for no reason.
    """
    # A repository with no commit is a real state, not an error -- `ls-tree
    # HEAD` there fails with "Not a valid object name", which would read as a
    # broken checkout.
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if resolved.returncode != 0:
        return

    try:
        process = subprocess.Popen(
            ["git", "ls-tree", "-r", "-l", "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, FileNotFoundError) as exc:  # pragma: no cover - git absent
        raise HealthError(f"cannot run git in {root}: {exc}") from exc

    assert process.stdout is not None
    for line in process.stdout:
        meta, _, path = line.rstrip("\n").partition("\t")
        parts = meta.split()
        # <mode> <type> <sha> <size>. A submodule is a `commit` with size `-`.
        if len(parts) != 4 or parts[1] != "blob" or not parts[3].isdigit():
            continue
        yield int(parts[3]), path

    process.stdout.close()
    stderr = process.stderr.read() if process.stderr else ""
    if process.stderr:
        process.stderr.close()
    if process.wait() != 0:
        raise HealthError(f"git ls-tree failed in {root}: {stderr.strip()}")


def measure(
    mech: str,
    root: Path,
    *,
    largest: int = DEFAULT_LARGEST,
    large_file_bytes: int = DEFAULT_LARGE_FILE_BYTES,
) -> RepositoryReport:
    """Report one repository's tracked weight and where it sits."""
    root = Path(root)
    if not (root / ".git").exists():
        raise HealthError(f"{root} is not a git checkout")

    report = RepositoryReport(
        mech=mech, large_file_bytes=large_file_bytes
    )
    directories: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    extensions: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    biggest: list[tuple[int, str]] = []

    for size, path in _entries(root):
        report.tracked_files += 1
        report.tracked_bytes += size
        if size >= large_file_bytes:
            report.large_files += 1

        # The top level is where growth is decided -- a directory nobody meant
        # to commit shows up here before it shows up anywhere else.
        top = path.split("/", 1)[0] if "/" in path else "(root)"
        directories[top][0] += 1
        directories[top][1] += size

        suffix = Path(path).suffix.lower() or "(none)"
        extensions[suffix][0] += 1
        extensions[suffix][1] += size

        biggest.append((size, path))
        if len(biggest) > largest * 4:
            biggest = sorted(biggest, reverse=True)[:largest]

    report.by_directory = {
        name: {"files": counts[0], "bytes": counts[1]}
        for name, counts in directories.items()
    }
    report.by_extension = {
        name: {"files": counts[0], "bytes": counts[1]}
        for name, counts in extensions.items()
    }
    # Ties broken by path, so the same repository gives the same report.
    report.largest_files = [
        {"path": path, "bytes": size}
        for size, path in sorted(biggest, key=lambda item: (-item[0], item[1]))[:largest]
    ]
    return report
