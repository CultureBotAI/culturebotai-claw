#!/usr/bin/env python3
"""Re-pin every Mech to the #729 evidence-rollout release, dry-run first.

Purpose: prepare one local re-pin commit per Mech for the merge commit of claw
PR #773. For each Mech it plans `kg_microbe_governance.sync_repository` against
that Mech's re-pin worktree. With --apply it then:
  - fast-forwards the worktree's branch to origin/main;
  - writes the governed artifacts and the pin;
  - adds what the sync does not manage.

What the sync does not manage:
  - NaturalProductMech re-snapshots scripts/.vendored_manifest.json from
    claw's manifest at the ref, which its own tests require (#791).
  - CellStructureMech and HabitatMech commit their known-findings ledger.
    Each commits its prepared abstract caches only where its LICENSE has no
    hosting policy. Both add the vendored runner to [tool.ruff]
    extend-exclude like their other claw-governed scripts (#788), and ignore
    the gate's workspace/reports/ output.

Dated records that name the outgoing pin are left unchanged (#795).

Inputs:
  - --ref: a full claw commit SHA;
  - --root: the scratch directory that holds repin/<mech> and adopt/<mech>
    worktrees on their feat/729-* branches;
  - --mech: optional and repeatable.

Outputs:
  - a JSON report on stdout;
  - with --apply, the written files and one local commit per Mech, made under
    the Mech's LockManager lease.
It never pushes and never opens a pull request; those are separate, reviewed
steps.

Serves: culturebotai-claw#729 / PR #773. Written 2026-11-04.

Correction (#804). The first run on 2026-11-04 also committed
CellStructureMech's 55 fetched abstracts and named #2873 as its ledger owner.
That was the first revision of CellStructureMech#3042, 7cdd3b5157. It was
force-pushed away after review: CellStructureMech's LICENSE hosts only
licence-verified text, and the old commit stays reachable on GitHub
(CellStructureMech#3067). The replacement, b6551af27c, was made by hand, and
dcf685f523 is its squash merge. It commits no abstracts, and 272
MISSING_CACHE ledger rows owned by CellStructureMech#3065.

The script now:
- refuses an adopter with no LICENSE;
- refuses untracked abstracts that would be staged under a hosting policy,
  since it commits none under such a policy (#808);
- stages only the prepared paths that exist;
- reads the ledger's owners rather than assuming them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_governance import sync_repository
from plugins.lock_manager import LockManager

CLAW_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MANIFEST = "src/kg_microbe_governance/vendored_artifacts.json"
ADOPTERS = frozenset({"cellstructuremech", "habitatmech"})
HOSTING_POLICY = re.compile(r"hosting policy|may be hosted|not hosted", re.IGNORECASE)
SNAPSHOTS = {"naturalproductmech": "scripts/.vendored_manifest.json"}
BRANCHES = {"repin": "feat/729-repin-evidence-rollout", "adopt": "feat/729-adopt-evidence-gate"}
ADOPTER_PREPARED = ("references_cache", "curation/evidence_known_findings.tsv")
RUFF_ANCHOR = '    "scripts/check_vendored_sync.py",\n'
RUFF_ENTRY = '    "scripts/run_shared_evidence_validator.py",\n'
GITIGNORE_ENTRY = "workspace/reports/"
GITIGNORE_BLOCK = (
    "\n# Shared quote gate reports (kg-microbe-evidence writes them here by default).\n"
    f"{GITIGNORE_ENTRY}\n"
)
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


class RepinError(RuntimeError):
    pass


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args], text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise RepinError(f"git {' '.join(args)} failed in {cwd}: {completed.stderr.strip()}")
    return completed.stdout


def porcelain(cwd: Path) -> list[str]:
    out = git(cwd, "status", "--porcelain=v1", "--untracked-files=all")
    return [line for line in out.splitlines() if line]


def write_atomic(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def has_hosting_policy(worktree: Path) -> bool:
    licence = worktree / "LICENSE"
    return licence.is_file() and bool(HOSTING_POLICY.search(licence.read_text(encoding="utf-8")))


def ledger_owners(worktree: Path) -> list[str]:
    """The issue column of the known-findings ledger: who owns its rows."""
    ledger = worktree / "curation" / "evidence_known_findings.tsv"
    rows = ledger.read_text(encoding="utf-8").splitlines()[1:]
    return sorted({row.split("\t")[4] for row in rows if row})


def message(key: str, ref: str, old_pin: str, changed: list[str], worktree: Path) -> str:
    release = "CultureBotAI/culturebotai-claw#773"
    tracker = "CultureBotAI/culturebotai-claw#729"
    if key in ADOPTERS:
        owners = ", ".join(ledger_owners(worktree)) or "no issue"
        caches = (
            "- references_cache/, the cited PubMed abstracts, fetched anonymously from\n"
            "  NCBI E-utilities and accepted only on a verified identity;\n"
            if "references_cache" in changed else ""
        )
        body = (
            "Adopt the shared quote gate and re-pin claw governance\n\n"
            f"Advance scripts/.vendored_canon_ref from {old_pin[:12]} to {ref}, the merge\n"
            f"of {release}, which enables evidence_reference_validation for this\n"
            f"repository ({tracker}). The sync vendors the shared runner and its\n"
            "qc-evidence workflow, which check every quoted snippet against the cited\n"
            "source's retained abstract.\n\n"
            "This commit also adds:\n"
            + caches +
            "- curation/evidence_known_findings.tsv, which records the quotes the gate\n"
            f"  cannot yet validate; its rows are owned by {owners};\n"
            "- the runner in [tool.ruff] extend-exclude, beside the other claw-governed\n"
            "  scripts, since vendored bytes are linted in claw;\n"
            f"- {GITIGNORE_ENTRY} in .gitignore, the gate's default report location.\n\n"
            "qc-evidence stays advisory: the merge-queue checker cannot yet accept the\n"
            "governed workflow's pin-derived claw checkout (CultureBotAI/culturebotai-claw#793).\n"
        )
    else:
        extra = ""
        if key in SNAPSHOTS:
            extra = (
                f"\nIt also re-snapshots {SNAPSHOTS[key]}, claw's governance manifest at\n"
                "that commit, which this repository's tests require to match the pin.\n"
            )
        body = (
            "Re-pin claw governance to the evidence rollout release\n\n"
            f"Advance scripts/.vendored_canon_ref from {old_pin[:12]} to {ref}, the merge\n"
            f"of {release}. That release retires the single-MediaIngredientMech\n"
            "canary lane and rolls the shared quote gate out to CellStructureMech and\n"
            f"HabitatMech ({tracker}). Every governed artifact this repository vendors\n"
            "is byte-identical at that commit, so the sync changes only the pin.\n"
            + extra
        )
    return body + "\nChanged: " + ", ".join(sorted(changed)) + "\n\n" + TRAILER + "\n"


def plan_one(key: str, worktree: Path, ref: str) -> dict:
    report: dict = {"mech": key, "worktree": str(worktree)}
    kind = "adopt" if key in ADOPTERS else "repin"
    branch = git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch != BRANCHES[kind]:
        raise RepinError(f"{key}: worktree is on {branch!r}, expected {BRANCHES[kind]!r}")
    git(worktree, "fetch", "--quiet", "origin")
    ahead = int(git(worktree, "rev-list", "--count", "origin/main..HEAD").strip())
    behind = int(git(worktree, "rev-list", "--count", "HEAD..origin/main").strip())
    if ahead:
        raise RepinError(f"{key}: branch carries {ahead} commit(s) not on origin/main")
    dirty = porcelain(worktree)
    allowed = ADOPTER_PREPARED if key in ADOPTERS else ()
    unexpected = [line for line in dirty if not (line.startswith("?? ") and line[3:].startswith(allowed))]
    if unexpected or (key in ADOPTERS and not dirty):
        raise RepinError(f"{key}: unexpected worktree state {dirty}")
    report.update(branch=branch, behind=behind,
                  old_pin=(worktree / "scripts/.vendored_canon_ref").read_text().strip(),
                  plan=[{"path": c.path, "reason": c.reason} for c in sync_repository(key, worktree, ref)])
    return report


def apply_one(key: str, worktree: Path, ref: str, report: dict) -> None:
    with LockManager().lock(key, "repin-evidence-729"):
        git(worktree, "merge", "--ff-only", "--quiet", "origin/main")
        prepared: list[str] = []
        staging_commit = False  # amend only a commit this run made, never upstream's tip
        if key in ADOPTERS:
            if not (worktree / "LICENSE").is_file():
                raise RepinError(f"{key}: no LICENSE; cannot tell whether abstracts may be hosted")
            # Under a hosting policy this script commits no abstracts: only the
            # untracked ones it would stage are refused. Abstracts already on
            # main landed in their own reviewed PR (#804, #808).
            untracked = git(worktree, "ls-files", "--others", "--exclude-standard", "--", "references_cache").split()
            if untracked and has_hosting_policy(worktree):
                raise RepinError(
                    f"{key}: LICENSE has a hosting policy and {len(untracked)} untracked abstract(s) would be "
                    "staged; this script commits no abstracts under such a policy. Land licence-verified "
                    "abstracts in their own reviewed PR first, and record the rest as MISSING_CACHE")
            prepared = (["references_cache"] if untracked else []) + [
                path for path in ADOPTER_PREPARED[1:] if (worktree / path).exists()]
            if prepared:
                git(worktree, "add", "--", *prepared)
            if subprocess.run(["git", "-C", str(worktree), "diff", "--cached", "--quiet"]).returncode:
                git(worktree, "commit", "--quiet", "-m", "Stage the quote gate's prepared caches and ledger")
                staging_commit = True
        if porcelain(worktree):
            raise RepinError(f"{key}: worktree is not clean before the sync")
        changes = sync_repository(key, worktree, ref, apply=True)
        paths = [change.path for change in changes]
        if key in SNAPSHOTS:
            snapshot = worktree / SNAPSHOTS[key]
            write_atomic(snapshot, subprocess.run(
                ["git", "-C", str(CLAW_ROOT), "show", f"{ref}:{CANONICAL_MANIFEST}"],
                capture_output=True, check=True).stdout)
            paths.append(SNAPSHOTS[key])
        if key in ADOPTERS:
            pyproject = worktree / "pyproject.toml"
            text = pyproject.read_text(encoding="utf-8")
            if text.count(RUFF_ANCHOR) != 1 or RUFF_ENTRY in text:
                raise RepinError(f"{key}: unexpected [tool.ruff] extend-exclude shape")
            write_atomic(pyproject, text.replace(RUFF_ANCHOR, RUFF_ANCHOR + RUFF_ENTRY).encode("utf-8"))
            gitignore = worktree / ".gitignore"
            current = gitignore.read_text(encoding="utf-8")
            if GITIGNORE_ENTRY not in current.splitlines():
                write_atomic(gitignore, (current.rstrip("\n") + "\n" + GITIGNORE_BLOCK).encode("utf-8"))
            paths += ["pyproject.toml", ".gitignore"]
        git(worktree, "add", "--", *paths)
        # Every remaining entry must be fully staged: index column M or A, and a
        # clean worktree column. Anything else is a write nobody accounted for.
        stray = [line for line in porcelain(worktree) if line[0] not in "MA" or line[1] != " "]
        if stray:
            raise RepinError(f"{key}: unaccounted changes after the sync: {stray}")
        staged = sorted(set(git(worktree, "diff", "--cached", "--name-only").split()))
        committed = staged + prepared
        text = message(key, ref, report["old_pin"], committed, worktree)
        if staging_commit:
            git(worktree, "commit", "--quiet", "--amend", "-m", text)
        else:
            git(worktree, "commit", "--quiet", "-m", text)
        if porcelain(worktree):
            raise RepinError(f"{key}: worktree not clean after the commit: {porcelain(worktree)}")
        remaining = sync_repository(key, worktree, ref)
        if remaining:
            raise RepinError(f"{key}: sync still plans {[c.path for c in remaining]} after the commit")
        report.update(commit=git(worktree, "rev-parse", "HEAD").strip(), staged=staged)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mech", action="append")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    keys = args.mech or sorted(load_fleet_manifest().mechs)
    reports, failed = [], False
    for key in keys:
        worktree = args.root / ("adopt" if key in ADOPTERS else "repin") / key
        try:
            report = plan_one(key, worktree, args.ref)
            if args.apply:
                apply_one(key, worktree, args.ref, report)
        except Exception as exc:  # report every Mech, then exit nonzero
            report = {"mech": key, "error": f"{type(exc).__name__}: {exc}"}
            failed = True
        reports.append(report)
    json.dump(reports, sys.stdout, indent=2)
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
