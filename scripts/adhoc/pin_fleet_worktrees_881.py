#!/usr/bin/env python3
"""Pin a detached worktree of every Mech at the HEAD the taxon-link assessment records.

Purpose: the assessment's four scripts read the Mech checkouts named by claw's
.env and record each HEAD in their summaries. The fleet has moved on since, so
re-running a corrected script against the live checkouts changes the HEADs and
the numbers together, and a fix cannot be shown to change only what it meant
to. This creates one detached worktree per Mech at the recorded HEAD, so the
chain re-runs against the bytes the document describes.
Method: read the HEAD column of the committed summary_all_curies.md and its
TaxonMech scope line, then, under each Mech's LockManager lease, run
`git worktree add --detach DEST SHA` from the configured checkout. TaxonMech's
worktree is sparse (curation/, conf/, data/raw/): the scripts read only its
scope, merge table and taxdump pin, and its 724k record files are not needed.
Its gitignored taxdump tarball is symlinked from the live checkout, which the
pin in conf/ncbi_taxdump.yaml identifies by digest. A linked worktree shares
the checkout's origin, so RepositorySettings validates it like the original.
Inputs: claw's .env (set -a; . ./.env) for the Mech roots and the lock
workspace; --summary PATH (default: the committed summary); --dest-root DIR
(default ~/agent-work); --apply to create (a dry run by default); --remove to
remove the worktrees this script created, under the same leases, refusing a
worktree that is dirty or not at the recorded HEAD.
Outputs: the worktrees under DEST_ROOT/<Mech display name>/pin881-<sha>, and
DEST_ROOT/culturebotai-claw/pin881/env.sh with one `export <MECH>_ROOT=...`
line per Mech, to source after claw's .env so the scripts read the pins.
Serves: culturebotai-claw PR 881, review round 6 (#1067, #1068, #1069).
Written 2026-11-09.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import RepositorySettings  # noqa: E402

SUMMARY = Path(__file__).resolve().parents[2] / "docs/reviews/2026-11-06-cross-mech-taxon-links/summary_all_curies.md"
SPARSE = {"taxonmech": ["curation", "conf", "data/raw"]}


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def recorded_heads(summary: Path) -> dict[str, str]:
    heads: dict[str, str] = {}
    for line in summary.read_text(encoding="utf-8").splitlines():
        row = re.fullmatch(r"\| ([a-z]+) \| ([0-9a-f]{12}) \| .*", line)
        if row:
            heads[row.group(1)] = row.group(2)
        scope = re.search(r"curation/seed_scope\.tsv at ([0-9a-f]{12})\)", line)
        if scope:
            heads["taxonmech"] = scope.group(1)
    if not heads:
        raise SystemExit(f"no HEADs found in {summary}")
    return heads


def head_of(path: Path) -> str:
    return git("-C", str(path), "rev-parse", "--short=12", "HEAD")


def registered(root: Path, dest: Path) -> bool:
    return f"worktree {dest.resolve()}" in git("-C", str(root), "worktree", "list", "--porcelain").splitlines()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=SUMMARY)
    parser.add_argument("--dest-root", type=Path, default=Path("~/agent-work").expanduser())
    parser.add_argument("--mech", action="append", help="limit to this Mech key (repeatable); default every Mech")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="create the worktrees (dry run otherwise)")
    mode.add_argument("--remove", action="store_true", help="remove the worktrees this script created")
    args = parser.parse_args()
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment()
    heads = recorded_heads(args.summary)
    env_file = args.dest_root / "culturebotai-claw/pin881/env.sh"
    exports: list[str] = []
    failures = 0
    for key, mech in manifest.mechs.items():
        sha = heads.get(key)
        if args.mech and key not in args.mech:
            continue
        if sha is None:
            print(f"{key}: no recorded HEAD, skipped")
            continue
        root = settings.paths.get(key)
        if root is None:
            print(f"{key}: not configured ({settings.errors.get(key, 'no root')})", file=sys.stderr)
            failures += 1
            continue
        dest = args.dest_root / mech.display_name / f"pin881-{sha}"
        exports.append(f"export {mech.environment_variable}={dest}")
        if subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode:
            print(f"{key}: {sha} is not in {root} (fetch it first)", file=sys.stderr)
            failures += 1
            continue
        if args.remove:
            if not dest.exists():
                print(f"{key}: {dest} already absent")
                continue
            if not registered(root, dest):
                print(f"{key}: {dest} is not a worktree of {root}; refusing", file=sys.stderr)
                failures += 1
                continue
            with LockManager().lock(key, "pin-worktree-881-remove"):
                if head_of(dest) != sha or git("-C", str(dest), "status", "--porcelain"):
                    print(f"{key}: {dest} is dirty or not at {sha}; refusing", file=sys.stderr)
                    failures += 1
                    continue
                tar = tar_path(root) if key == "taxonmech" else None
                if tar is not None and (dest / tar).is_symlink():
                    (dest / tar).unlink()
                git("-C", str(root), "worktree", "remove", str(dest))
            print(f"{key}: removed worktree {dest}")
            continue
        if dest.exists():
            if registered(root, dest) and head_of(dest) == sha:
                print(f"{key}: already pinned at {dest}")
                continue
            print(f"{key}: {dest} exists but is not this pin; refusing", file=sys.stderr)
            failures += 1
            continue
        if not args.apply:
            print(f"{key}: would add {'sparse ' if key in SPARSE else ''}worktree {dest} at {sha} from {root}")
            continue
        with LockManager().lock(key, "pin-worktree-881"):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if key in SPARSE:
                git("-C", str(root), "worktree", "add", "--detach", "--no-checkout", str(dest), sha)
                git("-C", str(dest), "sparse-checkout", "set", "--cone", *SPARSE[key])
                git("-C", str(dest), "checkout", "--detach", sha)
                tar = tar_path(root)
                (dest / tar).parent.mkdir(parents=True, exist_ok=True)
                (dest / tar).symlink_to(root / tar)
            else:
                git("-C", str(root), "worktree", "add", "--detach", str(dest), sha)
            got = head_of(dest)
        if got != sha:
            print(f"{key}: {dest} is at {got}, not {sha}", file=sys.stderr)
            failures += 1
            continue
        print(f"{key}: pinned {dest} at {sha}")
    if args.mech:
        print(f"{len(exports)} export line(s) for the selected Mech(s); {env_file} is written only by a full --apply")
    elif args.apply:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("\n".join(exports) + "\n", encoding="utf-8")
        print(f"wrote {env_file}")
    elif args.remove and env_file.exists():
        env_file.unlink()
        print(f"removed {env_file}")
    else:
        print(f"would write {env_file}")
    return 1 if failures else 0


def tar_path(taxonmech_root: Path) -> Path:
    conf = yaml.safe_load((taxonmech_root / "conf/ncbi_taxdump.yaml").read_text(encoding="utf-8"))
    rel = Path(conf["path"])
    if rel.is_absolute() or ".." in rel.parts:
        raise SystemExit(f"taxdump path must be relative to the checkout: {rel}")
    return rel


if __name__ == "__main__":
    sys.exit(main())
