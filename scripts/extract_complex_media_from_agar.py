#!/usr/bin/env python3
"""
Decontaminate Agar.yaml: extract the complex-medium synonyms that got
absorbed during the duplicate-CHEBI consolidation pass and shouldn't be
synonyms of the pure chemical CHEBI:2509 (agar polysaccharide).

"Brucella agar", "Columbia blood agar base", "Mueller Hinton II agar",
etc. are complete media formulations that contain agar as a solidifying
ingredient among many other components. They need their own MIM records
(probably UNMAPPED pending curation) — not synonym-entries under the
chemical-agar record.

What stays as a synonym of Agar.yaml (pure-agar tokens):
  - "Bacteriological Agar", "Bacto Agar", "Noble agar", "Purified agar"
  - Parenthesized qualifiers like "(alternative)", "(for solid medium)"
  - CultureMech metadata like "Role: ..." / "Properties: ..."
  - Bare "Agar" and variants

What gets extracted into a new UNMAPPED YAML per synonym:
  - Everything else containing "agar" (implies a specific medium recipe)

--dry-run (default) / --apply
"""

from __future__ import annotations

import os
import sys
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402
MIM_MAPPED_DIR = MIM_ROOT / "data/ingredients"
MAPPED_DIR = MIM_MAPPED_DIR / "mapped"
UNMAPPED_DIR = MIM_MAPPED_DIR / "unmapped"

AGAR_YAML = MAPPED_DIR / "Agar.yaml"

TIMESTAMP = datetime.now(timezone.utc).isoformat()

# Tokens that are pure-agar qualifiers — synonym stays on Agar.yaml if
# ALL of its alphabetic tokens are in this set.
PURE_AGAR_TOKENS = {
    "agar", "agarose",
    "bacto", "bacteriological", "noble", "purified",
    "granulated", "flake", "powder", "powdered",
}

# Metadata / qualifier patterns that stay as synonyms verbatim.
METADATA_RE = re.compile(
    r"^\s*(role:|properties:|\(.*\)|\s*$)",
    re.IGNORECASE,
)


def _is_pure_agar_synonym(text: str) -> bool:
    """True if the synonym is just 'agar' with standard qualifiers."""
    if not text:
        return True  # empty stays (no-op)
    if METADATA_RE.match(text):
        return True
    # Extract alphabetic tokens, lowercase.
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    if not tokens:
        return True
    return tokens.issubset(PURE_AGAR_TOKENS)


def _slug(label: str) -> str:
    cleaned = re.sub(r"[^\w\s()\-]", "", label).strip()
    parts = [p for p in re.split(r"\s+", cleaned) if p]
    return "_".join(p[0].upper() + p[1:] if p else "" for p in parts) or "Unnamed"


def _classify_synonyms(doc: dict) -> tuple[list[dict], list[dict]]:
    """Split existing synonyms into (stays, extracted)."""
    stays: list[dict] = []
    extracted: list[dict] = []
    for s in (doc.get("synonyms") or []):
        if not isinstance(s, dict):
            continue
        txt = (s.get("synonym_text", "") or "").strip()
        if _is_pure_agar_synonym(txt):
            stays.append(s)
        else:
            extracted.append(s)
    return stays, extracted


def _next_unmapped_id() -> int:
    """Find the highest existing UNMAPPED_XXXX identifier and return next."""
    import re as _re
    max_id = 0
    for p in UNMAPPED_DIR.glob("*.yaml"):
        try:
            text = p.read_text()
        except Exception:
            continue
        m = _re.search(r"identifier:\s*UNMAPPED_(\d+)", text)
        if m:
            n = int(m.group(1))
            if n > max_id:
                max_id = n
    return max_id + 1


def _make_unmapped_yaml(syn: dict, next_id: int) -> tuple[str, dict]:
    """Build an UNMAPPED MIM YAML for a complex medium synonym."""
    label = syn["synonym_text"]
    slug = _slug(label)
    identifier = f"UNMAPPED_{next_id:04d}"
    doc = {
        "identifier": identifier,
        "preferred_term": label,
        "synonyms": [
            {
                "synonym_text": label,
                "synonym_type": "RAW_TEXT",
                "source": "extracted_from_agar_yaml",
            }
        ],
        "mapping_status": "UNMAPPED",
        "occurrence_statistics": {
            "total_occurrences": 0,
            "media_count": 0,
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_extract_complex_media_from_agar",
                "action": "EXTRACTED_COMPLEX_MEDIUM",
                "changes": (
                    f"Extracted from Agar.yaml — '{label}' is a complete "
                    f"media formulation, not a synonym of the chemical "
                    f"CHEBI:2509 (agar). Pending curator re-mapping "
                    f"(likely FOODON complex medium, or split into "
                    f"per-component ingredients)."
                ),
                "new_status": "UNMAPPED",
                "llm_assisted": False,
            }
        ],
        "notes": f"Extracted from over-conflated Agar.yaml synonyms",
    }
    return slug, doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)


    if not AGAR_YAML.exists():
        print(f"MISSING: {AGAR_YAML}")
        return

    doc = yaml.safe_load(AGAR_YAML.read_text())
    stays, extracted = _classify_synonyms(doc)

    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: "
          f"Agar.yaml synonyms: {len(stays)} stay, {len(extracted)} extracted\n")
    print("STAYS on Agar.yaml:")
    for s in stays:
        print(f"  ✓ {s['synonym_text']}")
    print("\nEXTRACTED as new UNMAPPED YAMLs:")
    for s in extracted:
        slug = _slug(s["synonym_text"])
        path = UNMAPPED_DIR / f"{slug}.yaml"
        marker = " (would overwrite)" if path.exists() else ""
        print(f"  → {path.name}{marker}")

    if not args.apply:
        print("\nDRY-RUN: no changes made. Pass --apply to execute.")
        return

    UNMAPPED_DIR.mkdir(parents=True, exist_ok=True)
    created = 0
    skipped = 0
    next_id = _next_unmapped_id()
    for s in extracted:
        slug, new_doc = _make_unmapped_yaml(s, next_id)
        path = UNMAPPED_DIR / f"{slug}.yaml"
        if path.exists():
            print(f"  [SKIP] {path.name} — already exists")
            skipped += 1
            continue
        path.write_text(yaml.safe_dump(new_doc, sort_keys=False, allow_unicode=True))
        created += 1
        next_id += 1

    # Rewrite Agar.yaml with only the pure-agar synonyms, and add a
    # curation_history entry documenting the extraction.
    doc["synonyms"] = stays
    doc.setdefault("curation_history", []).append({
        "timestamp": TIMESTAMP,
        "curator": "audit_extract_complex_media_from_agar",
        "action": "EXTRACTED_CONTAMINATING_SYNONYMS",
        "changes": (
            f"Extracted {len(extracted)} complex-medium synonyms that "
            f"were wrongly absorbed during duplicate-CHEBI consolidation. "
            f"Each is now its own UNMAPPED MIM record under "
            f"data/ingredients/unmapped/. Agar.yaml retains only pure "
            f"chemical-agar synonyms."
        ),
        "new_status": "MAPPED",
        "llm_assisted": False,
    })
    AGAR_YAML.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))

    print(f"\nDONE. Agar.yaml kept {len(stays)} synonyms; "
          f"created {created} new UNMAPPED YAMLs ({skipped} already existed).")


if __name__ == "__main__":
    main()
