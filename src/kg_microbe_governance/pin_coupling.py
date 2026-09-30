"""Find files in a consumer that hard-code the claw pin being retired (#526).

`kg-microbe-governance sync` writes only governed paths, so a re-pin plans one
file -- `scripts/.vendored_canon_ref` -- in a consumer that is otherwise current.
A Mech can still keep its own copy of that commit elsewhere, and then the re-pin
breaks its CI while every governance check passes. Two did in the rollout to
cb83def3: MediaIngredientMech's `qc-evidence` workflow checked claw out at a
hard-coded `ref:` that a test requires to equal the pin, and NaturalProductMech
committed claw's manifest as it was at the pin.

This reads the committed tree (``origin/main`` by default, never the worktree)
for the outgoing pin in full or abbreviated to seven or more characters, in
either case. The pin
file itself is the change a re-pin makes and is not reported; ``reports/`` holds
dated records, which quote the commit they were made against. A snapshot of
claw content is not found this way -- it quotes no SHA -- so snapshot files the
governance manifest does not know are listed separately by name.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import GovernanceError, _validate_ref

# Seven is git's default `--short`, so `git log --oneline` output names a pin
# this way (#534).
MIN_ABBREVIATION = 7
DATED_RECORD_PREFIXES = ("reports/",)
_HEX_RUN = re.compile(r"[0-9a-f]{%d,40}" % MIN_ABBREVIATION)
_SNAPSHOT_NAME = re.compile(r"(^|/)\.?vendored[_-]?manifest[^/]*$", re.IGNORECASE)


@dataclass(frozen=True)
class Coupling:
    path: str
    line: int
    token: str
    kind: str  # "pin-reference" or "manifest-snapshot"


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    # git grep exits 1 for "no match"; anything above that is an error.
    if completed.returncode > 1:
        raise GovernanceError(
            f"git {' '.join(arguments[:2])} failed in {root}: {completed.stderr.strip()}"
        )
    return completed.stdout


def find_pin_couplings(
    root: Path,
    old_ref: str,
    *,
    pin_path: str,
    treeish: str = "origin/main",
) -> list[Coupling]:
    """Every committed reference to ``old_ref`` outside the pin file."""
    old_ref = _validate_ref(old_ref)
    if not _git(root, "rev-parse", "--verify", "--quiet", f"{treeish}^{{tree}}").strip():
        raise GovernanceError(f"{root} has no {treeish} to search")

    found: list[Coupling] = []
    output = _git(
        root, "grep", "-n", "-I", "-i", "-F", "-e", old_ref[:MIN_ABBREVIATION], treeish, "--"
    )
    prefix = f"{treeish}:"
    for row in output.splitlines():
        if not row.startswith(prefix):
            continue
        path, _, rest = row[len(prefix):].partition(":")
        line, _, text = rest.partition(":")
        if path == pin_path or path.startswith(DATED_RECORD_PREFIXES):
            continue
        # A hex run that merely starts with the same characters is some
        # other commit; only a prefix of the retiring pin is a reference to it.
        for token in _HEX_RUN.findall(text.lower()):
            if old_ref.startswith(token):
                found.append(Coupling(path, int(line), token, "pin-reference"))
                break

    for path in _git(root, "ls-tree", "-r", "--name-only", treeish).splitlines():
        if _SNAPSHOT_NAME.search(path) and not path.startswith(DATED_RECORD_PREFIXES):
            found.append(Coupling(path, 0, "", "manifest-snapshot"))
    return sorted(found, key=lambda c: (c.path, c.line))
