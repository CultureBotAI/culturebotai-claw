#!/usr/bin/env python3
"""Snapshot the kg-microbe data files claw scripts depend on into
`workspace/kgm_snapshot/`. Captures the current local kg-microbe state
without `git pull` — useful for reproducible audits and as a fallback
when KGM_ROOT is unset.

Files snapshotted (from local kg-microbe checkout, *not* fetched):

  kg-microbe/mappings/culturebotai_reviewed_ingredients.tsv
  kg-microbe/mappings/mediadive_unmapped_ingredients_to_curate.tsv
  kg-microbe/mappings/complex_ingredients.tsv.gz
  kg-microbe/mappings/kgmicrobe_proposal_placeholders.tsv
  kg-microbe/mappings/manual_mapping_audit_report.tsv
  kg-microbe/docs/metatraits/unmapped_compounds.tsv

Each snapshot is named the same as the source. A manifest.json records:
  - source path
  - source mtime
  - source size
  - source sha256
  - kg-microbe git HEAD at snapshot time
  - copy timestamp

The snapshot is gitignored (lives under workspace/) — re-run the script
to refresh.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KGM_ROOT = Path(os.environ.get(
    "KGMICROBE_ROOT",
    REPO_ROOT.parent / "kg-microbe"))
SNAPSHOT_DIR = REPO_ROOT / "workspace" / "kgm_snapshot"

# (source path relative to kg-microbe root, why claw cares)
DEPS = (
    ("mappings/culturebotai_reviewed_ingredients.tsv",
     "Authority on which ingredients are kg-microbe-side reviewed; "
     "consumed by kg-microbe-review."),
    ("mappings/mediadive_unmapped_ingredients_to_curate.tsv",
     "Mediadive-side unmapped backlog; consumed by unmapped-inventory."),
    ("mappings/complex_ingredients.tsv.gz",
     "Cross-repo complex-ingredient registry."),
    ("mappings/kgmicrobe_proposal_placeholders.tsv",
     "kg-microbe proposed-but-not-minted placeholder CURIE registry."),
    ("mappings/manual_mapping_audit_report.tsv",
     "kg-microbe-side audit of manual mappings."),
    ("docs/metatraits/unmapped_compounds.tsv",
     "kg-microbe metatraits placeholder backlog; consumed by "
     "unmapped-inventory."),
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _kgm_head() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=KGM_ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return out
    except Exception:
        return "(unknown)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied; don't write files")
    args = ap.parse_args()

    if not KGM_ROOT.is_dir():
        print(f"kg-microbe checkout not found at {KGM_ROOT}",
              file=sys.stderr)
        return 2

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    head = _kgm_head()
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    n_copied = n_missing = n_unchanged = 0

    for rel, why in DEPS:
        src = KGM_ROOT / rel
        dst = SNAPSHOT_DIR / Path(rel).name
        if not src.is_file():
            print(f"  MISSING: {rel} ({why})")
            n_missing += 1
            continue
        sha = _sha256(src)
        st = src.stat()
        existing_sha = ""
        if dst.is_file():
            try:
                existing_sha = _sha256(dst)
            except Exception:
                existing_sha = ""
        if existing_sha == sha:
            n_unchanged += 1
            print(f"  unchanged: {rel}  (sha {sha[:12]})")
        else:
            if args.dry_run:
                print(f"  WOULD COPY: {rel}  (sha {sha[:12]})")
            else:
                shutil.copy2(src, dst)
                print(f"  copied: {rel} → {dst.name} (sha {sha[:12]})")
            n_copied += 1
        manifest.append({
            "source_relative": rel,
            "source_absolute": str(src),
            "snapshot_path": str(dst.relative_to(REPO_ROOT)),
            "source_size": st.st_size,
            "source_mtime": _dt.datetime.fromtimestamp(
                st.st_mtime, _dt.timezone.utc).isoformat(timespec="seconds"),
            "source_sha256": sha,
            "purpose": why,
        })

    manifest_obj = {
        "snapshot_dir": str(SNAPSHOT_DIR.relative_to(REPO_ROOT)),
        "kgm_root": str(KGM_ROOT),
        "kgm_git_head": head,
        "snapshot_taken_at": now,
        "files": manifest,
    }
    if not args.dry_run:
        (SNAPSHOT_DIR / "manifest.json").write_text(
            json.dumps(manifest_obj, indent=2))

    print()
    print(f"  copied/updated: {n_copied}")
    print(f"  unchanged:      {n_unchanged}")
    print(f"  missing source: {n_missing}")
    print(f"  kgm HEAD:       {head[:12]}")
    print(f"  snapshot:       {SNAPSHOT_DIR.relative_to(REPO_ROOT)}")
    return 0 if n_missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
