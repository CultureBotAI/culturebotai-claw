#!/usr/bin/env python3
"""
Emit patch proposals for MIM ingredients whose SSSOM object_label drifted
from CHEBI's canonical label.

Reads workspace/reports/kgm_mim_audit.tsv, selects rows where
`flags contains LABEL_DRIFT` AND `bucket in {AGREE, DISAGREE}`,
skips rows that overlap with DEPRECATED_CHEBI (handled separately),
and for each remaining row:

  1. Looks up OAK's canonical label for the CHEBI.
  2. If OAK label is None, falls back to EBI OLS4 to detect whether the
     CHEBI ID has been fully removed from CHEBI (not just obsolete).
  3. Emits one patch per MIM YAML file:
       - LABEL_UPDATE  — mechanical label swap
       - CHEBI_REMOVED — CHEBI ID no longer exists; needs re-curation
       - STALE_LOCAL   — OAK missed it but OLS has it; refresh local sqlite

Patches go to workspace/patches/. MIM repo is not touched.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
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
PATCH_YAML = PATCHES_DIR / "mim_label_drift_patches.yaml"
SUMMARY_MD = REPORT_DIR / "mim_label_drift_summary.md"

MIM_MAPPED_DIR = MIM_ROOT / "data/ingredients/mapped"

OLS_BASE = "https://www.ebi.ac.uk/ols4/api/ontologies/chebi/terms"


def load_drift_rows() -> list[dict]:
    with AUDIT_TSV.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        out = []
        for r in reader:
            flags = r.get("flags") or ""
            if "LABEL_DRIFT" not in flags:
                continue
            if "DEPRECATED_CHEBI" in flags:
                continue  # handled by fix_deprecated_chebi.py
            if r.get("bucket") not in ("AGREE", "DISAGREE"):
                continue
            out.append(r)
        return out


def mim_id_to_yaml(mim_id: str) -> Path | None:
    if not mim_id.startswith("MIM:"):
        return None
    slug = mim_id.split(":", 1)[1]
    cand = MIM_MAPPED_DIR / f"{slug}.yaml"
    return cand if cand.exists() else None


def ols_label_and_status(chebi: str) -> tuple[str | None, str]:
    """Return (label_or_None, status) where status in {ok, obsolete, missing, error}."""
    frag = chebi.replace(":", "_")
    url = f"{OLS_BASE}?iri=http://purl.obolibrary.org/obo/{frag}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            j = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "missing"
        return None, "error"
    except Exception:
        return None, "error"
    terms = j.get("_embedded", {}).get("terms", [])
    if not terms:
        return None, "missing"
    t = terms[0]
    label = t.get("label")
    return label, ("obsolete" if t.get("is_obsolete") else "ok")


def build_patches(rows: list[dict]) -> list[dict]:
    from oaklib import get_adapter
    adapter = get_adapter("sqlite:obo:chebi")

    patches: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for r in rows:
        chebi = r["mim_chebi"]
        yaml_path = mim_id_to_yaml(r["mim_id"])
        if not yaml_path:
            continue

        oak_label = adapter.label(chebi)

        if oak_label:
            kind = "LABEL_UPDATE"
            new_label = oak_label
            ols_status = None
        else:
            ols_label, ols_status = ols_label_and_status(chebi)
            time.sleep(0.2)  # polite rate limit
            if ols_label:
                kind = "STALE_LOCAL"
                new_label = ols_label
            elif ols_status == "missing":
                kind = "CHEBI_REMOVED"
                new_label = ""
            else:
                kind = "UNKNOWN"
                new_label = ""

        patches.append({
            "file": str(yaml_path.relative_to(MIM_MAPPED_DIR.parent.parent.parent)),
            "mim_id": r["mim_id"],
            "mim_label": r["mim_label"],
            "chebi": chebi,
            "current_sssom_label": r["mim_object_label"],
            "patch_kind": kind,
            "new_ontology_label": new_label,
            "ols_status": ols_status,
            "proposed_curation_entry": {
                "timestamp": now,
                "curator": "audit_fix_label_drift",
                "action": (
                    "FIXED_LABEL_DRIFT" if kind == "LABEL_UPDATE"
                    else "FLAGGED_STALE_LOCAL_CHEBI" if kind == "STALE_LOCAL"
                    else "FLAGGED_CHEBI_REMOVED" if kind == "CHEBI_REMOVED"
                    else "FLAGGED_LABEL_DRIFT_UNKNOWN"
                ),
                "changes": (
                    f"Set ontology_label='{new_label}' from OAK/OLS"
                    if new_label
                    else f"{chebi} has no resolvable label (status={ols_status}); needs re-curation"
                ),
                "new_status": "MAPPED" if new_label else "NEEDS_REVIEW",
                "llm_assisted": False,
            },
        })
    return patches


def write_patches_yaml(path: Path, patches: list[dict]) -> None:
    try:
        import yaml
        path.write_text(yaml.safe_dump(patches, sort_keys=False))
    except ImportError:
        path.write_text("\n".join(json.dumps(p) for p in patches) + "\n")


def write_summary(path: Path, patches: list[dict]) -> None:
    from collections import Counter
    kinds = Counter(p["patch_kind"] for p in patches)
    lines = ["# MIM Label Drift Fix Summary\n"]
    lines.append(f"**Total label-drift patches:** {len(patches)}\n")
    lines.append("| Kind | Count |")
    lines.append("|---|---:|")
    for k in ("LABEL_UPDATE", "STALE_LOCAL", "CHEBI_REMOVED", "UNKNOWN"):
        lines.append(f"| {k} | {kinds.get(k, 0)} |")

    lines.append("\n## Rows\n")
    lines.append("| MIM file | CHEBI | Kind | New label |")
    lines.append("|---|---|---|---|")
    for p in patches:
        lines.append(
            f"| `{Path(p['file']).name}` | {p['chebi']} | "
            f"{p['patch_kind']} | {p['new_ontology_label'] or '—'} |"
        )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    rows = load_drift_rows()
    print(f"[1/3] Found {len(rows)} LABEL_DRIFT MIM-side rows (excl. deprecated)")
    patches = build_patches(rows)
    print(f"[2/3] Built {len(patches)} patches")

    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_patches_yaml(PATCH_YAML, patches)
    write_summary(SUMMARY_MD, patches)
    print(f"[3/3] Wrote {PATCH_YAML}")
    print(f"      Wrote {SUMMARY_MD}")


if __name__ == "__main__":
    main()
