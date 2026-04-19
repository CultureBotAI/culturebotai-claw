"""
Promote the working-copy SSSOM (`workspace/reports/mim_ingredient_mappings.sssom.tsv`)
to the canonical publish location
(`MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv`).

This is stage 4 of the publish-sssom lifecycle. Run only after the first
three stages (build → validate → review) are green. This script
re-validates the working copy as its final check and exits non-zero on
any hard error.

Safety:
- Acquires the `mediaingredientmech` lock via plugins.lock_manager.LockManager
  (see CLAUDE.md "Lock System") before touching the MIM repo.
- Refuses to overwrite the published file if its row count would drop by
  more than 5 vs. the previous published copy (guards against truncation).
- Appends an audit entry to workspace/status/sssom_promotions.jsonl.

Usage:
    python scripts/publish_sssom.py --dry-run     # default: prints what would happen
    python scripts/publish_sssom.py --apply       # actually promote
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
MIM_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech"
)
WORKING_COPY = CLAW_ROOT / "workspace" / "reports" / "mim_ingredient_mappings.sssom.tsv"
PUBLISHED = MIM_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"
AUDIT_LOG = CLAW_ROOT / "workspace" / "status" / "sssom_promotions.jsonl"
LOCKS_DIR = CLAW_ROOT / "workspace" / "locks"
ROW_COUNT_DROP_LIMIT = 5

SSSOM_BIN = "sssom"


def _load_lock_manager():
    """Import plugins.lock_manager directly, bypassing plugins/__init__.py
    (which has other heavy deps we don't need here)."""
    spec = importlib.util.spec_from_file_location(
        "lock_manager", CLAW_ROOT / "plugins" / "lock_manager.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LockManager


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open() as f:
        for line in f:
            if line.startswith("#"):
                continue
            if not line.strip():
                continue
            n += 1
    # minus the header row
    return max(0, n - 1)


def _validate(path: Path) -> list[str]:
    try:
        proc = subprocess.run(
            [SSSOM_BIN, "validate",
             "-V", "JsonSchema",
             "-V", "PrefixMapCompleteness",
             "-V", "StrictCurieFormat",
             str(path)],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        return ["sssom CLI not on PATH"]
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    markers = ("is not well-formed", "is not a valid URI or CURIE", "must be supplied")
    return [ln.strip() for ln in combined.splitlines() if any(m in ln for m in markers)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write the published file")
    ap.add_argument("--dry-run", action="store_true", help="(default) print what would happen")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    if not WORKING_COPY.exists():
        print(f"Working copy missing: {WORKING_COPY}", file=sys.stderr)
        print("Run `just build-sssom` first.", file=sys.stderr)
        sys.exit(2)

    new_rows = _row_count(WORKING_COPY)
    new_hash = _sha256(WORKING_COPY)

    prev_rows = _row_count(PUBLISHED)
    prev_hash = _sha256(PUBLISHED) if PUBLISHED.exists() else ""

    if prev_rows and new_rows < prev_rows - ROW_COUNT_DROP_LIMIT:
        print(
            f"Refusing to promote: row count would drop from {prev_rows} → {new_rows} "
            f"(limit: -{ROW_COUNT_DROP_LIMIT}).",
            file=sys.stderr,
        )
        print("Investigate or override with a higher ROW_COUNT_DROP_LIMIT.", file=sys.stderr)
        sys.exit(2)

    if prev_hash and prev_hash == new_hash:
        print(f"Published file already up to date (sha256={new_hash[:12]}). Nothing to do.")
        return

    print(f"Working copy: {WORKING_COPY} ({new_rows} rows, sha256={new_hash[:12]})")
    print(f"Published:    {PUBLISHED} ({prev_rows} rows, sha256={prev_hash[:12] or 'absent'})")
    print(f"Delta:        {new_rows - prev_rows:+d} rows")

    print("\nRe-validating working copy before promotion...")
    errors = _validate(WORKING_COPY)
    if errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in errors[:20]:
            print(f"  - {e[:200]}", file=sys.stderr)
        sys.exit(2)
    print("  OK")

    if not apply:
        print("\n(dry-run) Would copy working copy to published path and log the promotion.")
        print("Pass --apply to perform the promotion.")
        return

    LockManager = _load_lock_manager()
    locker = LockManager({"locks_dir": str(LOCKS_DIR), "my_id": "publish_sssom"})
    if not locker.acquire_lock(
        "mediaingredientmech",
        operation="publish-sssom promotion",
        wait=True,
        max_wait=300,
    ):
        print("Could not acquire mediaingredientmech lock within 300s.", file=sys.stderr)
        sys.exit(2)

    try:
        PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
        PUBLISHED.write_bytes(WORKING_COPY.read_bytes())
        published_hash = _sha256(PUBLISHED)
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "working_copy": str(WORKING_COPY),
            "published": str(PUBLISHED),
            "rows": new_rows,
            "prev_rows": prev_rows,
            "sha256": published_hash,
            "prev_sha256": prev_hash,
            "validators": ["JsonSchema", "PrefixMapCompleteness", "StrictCurieFormat"],
        }
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"\nPromoted → {PUBLISHED}")
        print(f"Audit entry appended to {AUDIT_LOG}")
    finally:
        locker.release_lock("mediaingredientmech")


if __name__ == "__main__":
    main()
