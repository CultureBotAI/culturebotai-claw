#!/usr/bin/env python3
"""
Emit patch proposals for MIM ingredients that map to obsolete CHEBI terms.

Reads workspace/reports/kgm_mim_audit.tsv, selects rows where
`flags contains DEPRECATED_CHEBI` AND `bucket in {AGREE, DISAGREE}`
(the MIM side — KGM_ONLY rows are kg-microbe's use of deprecated CHEBIs
and are handled in generate_kgm_xref_patches.py), finds each successor
via `oaklib.obsoletes_migration_relationships`, and emits one patch per
MIM YAML file.

Patches do NOT modify the MIM repo directly — they go to
workspace/patches/ for later application through the lock + task system.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
WORKSPACE = REPO_ROOT / "workspace"
AUDIT_TSV = WORKSPACE / "reports/kgm_mim_audit.tsv"
PATCHES_DIR = WORKSPACE / "patches"
REPORT_DIR = WORKSPACE / "reports"
PATCH_YAML = PATCHES_DIR / "mim_deprecated_chebi_patches.yaml"
SUMMARY_MD = REPORT_DIR / "mim_deprecated_chebi_summary.md"

MIM_MAPPED_DIR = MIM_ROOT / "data/ingredients/mapped"

IAO_REPLACED_BY = "IAO:0100001"


def load_deprecated_rows() -> list[dict]:
    with AUDIT_TSV.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        return [
            r for r in reader
            if "DEPRECATED_CHEBI" in (r.get("flags") or "")
            and r.get("bucket") in ("AGREE", "DISAGREE")
        ]


def mim_id_to_yaml(mim_id: str) -> Path | None:
    """MIM:<slug> -> data/ingredients/mapped/<slug>.yaml (if it exists)."""
    if not mim_id.startswith("MIM:"):
        return None
    slug = mim_id.split(":", 1)[1]
    candidate = MIM_MAPPED_DIR / f"{slug}.yaml"
    return candidate if candidate.exists() else None


def build_patches(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (patches, skipped) — skipped includes rows with no successor or missing file."""
    from oaklib import get_adapter

    adapter = get_adapter("sqlite:obo:chebi")

    unique_chebis = sorted({r["mim_chebi"] for r in rows if r["mim_chebi"]})
    replacements: dict[str, str] = {}
    for subj, pred, obj in adapter.obsoletes_migration_relationships(unique_chebis):
        if pred == IAO_REPLACED_BY and subj not in replacements:
            replacements[subj] = obj

    patches: list[dict] = []
    skipped: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for r in rows:
        old = r["mim_chebi"]
        new = replacements.get(old)
        yaml_path = mim_id_to_yaml(r["mim_id"])

        if not new:
            skipped.append({**r, "skip_reason": "no term-replaced-by axiom in CHEBI"})
            continue
        if not yaml_path:
            skipped.append({**r, "skip_reason": f"MIM yaml not found for {r['mim_id']}"})
            continue

        new_label = adapter.label(new) or ""
        patches.append({
            "file": str(yaml_path.relative_to(MIM_MAPPED_DIR.parent.parent.parent)),
            "mim_id": r["mim_id"],
            "mim_label": r["mim_label"],
            "old_chebi": old,
            "new_chebi": new,
            "new_label": new_label,
            "proposed_curation_entry": {
                "timestamp": now,
                "curator": "audit_fix_deprecated_chebi",
                "action": "FIXED_DEPRECATED_CHEBI",
                "changes": (
                    f"Replaced deprecated {old} with successor {new} ({new_label})"
                ),
                "new_status": "MAPPED",
                "llm_assisted": False,
            },
        })

    return patches, skipped


def write_patches_yaml(path: Path, patches: list[dict]) -> None:
    """Write as a YAML-ish list using pyyaml if available, else JSON-lines.
    We avoid the pyyaml hard-dep since this file is read by a downstream
    task runner that accepts either format.
    """
    try:
        import yaml
        path.write_text(yaml.safe_dump(patches, sort_keys=False))
    except ImportError:
        path.write_text("\n".join(json.dumps(p) for p in patches) + "\n")


def write_summary(path: Path, patches: list[dict], skipped: list[dict]) -> None:
    lines = ["# MIM Deprecated CHEBI Fix Summary\n"]
    lines.append(f"**Total DEPRECATED_CHEBI MIM rows:** {len(patches) + len(skipped)}\n")
    lines.append(f"**Actionable patches:** {len(patches)}\n")
    lines.append(f"**Skipped:** {len(skipped)}\n\n")

    if patches:
        lines.append("## Proposed patches\n")
        lines.append("| MIM file | Old CHEBI | → | New CHEBI | New label |")
        lines.append("|---|---|---|---|---|")
        for p in patches:
            lines.append(
                f"| `{Path(p['file']).name}` | {p['old_chebi']} | → | "
                f"{p['new_chebi']} | {p['new_label']} |"
            )

    if skipped:
        lines.append("\n## Skipped rows\n")
        lines.append("| MIM id | CHEBI | Reason |")
        lines.append("|---|---|---|")
        for s in skipped:
            lines.append(f"| {s['mim_id']} | {s['mim_chebi']} | {s['skip_reason']} |")

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    rows = load_deprecated_rows()
    print(f"[1/3] Found {len(rows)} DEPRECATED_CHEBI MIM-side rows")

    patches, skipped = build_patches(rows)
    print(f"[2/3] Built {len(patches)} patches ({len(skipped)} skipped)")

    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_patches_yaml(PATCH_YAML, patches)
    write_summary(SUMMARY_MD, patches, skipped)
    print(f"[3/3] Wrote {PATCH_YAML}")
    print(f"      Wrote {SUMMARY_MD}")


if __name__ == "__main__":
    main()
