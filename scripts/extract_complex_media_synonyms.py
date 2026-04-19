#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Generalized extractor: remove complex-media synonyms that got absorbed
into simple-ingredient MIM YAMLs during duplicate-CHEBI consolidation.

For each targeted MIM YAML:
  - Classify each synonym as either "pure" (stays) or "complex medium"
    (extracted to its own UNMAPPED_XXXX YAML).
  - Classification rule: a synonym is a complex medium when it contains
    any keyword from a configurable complex-media vocabulary that the
    base ingredient is NOT itself. For example:
      - base=Malt extract    → "agar" in synonym means complex medium
      - base=Trypticase peptone → "broth" or "agar" means complex medium
      - base=Agar            → handled by extract_complex_media_from_agar.py
        (anything beyond pure-agar tokens)

  - Pure-ingredient-brand qualifiers (Bacto, Difco, Oxoid, BD, BBL,
    Sigma, catalog numbers) never trigger extraction.

Targets are configured inline (see TARGETS below). Add more entries
to extend the audit to new MIM YAMLs.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

MIM_INGREDIENTS = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients"
)
MAPPED_DIR = MIM_INGREDIENTS / "mapped"
UNMAPPED_DIR = MIM_INGREDIENTS / "unmapped"

TIMESTAMP = datetime.now(timezone.utc).isoformat()

# A synonym is a complex medium if it contains ANY token from
# `medium_markers` that is NOT also in the target's `pure_tokens`.
# `pure_tokens` describes the base ingredient — everything in that set
# is allowed in synonyms without triggering extraction.
#
# Brand/catalog noise is always ignored regardless of pure_tokens.
BRAND_TOKENS = {
    "bacto", "difco", "oxoid", "bd", "bbl", "sigma", "merck",
    "nihon", "seiyaku", "nissui", "hardy", "wako", "nacalai",
    "tesque", "kyoto", "japan", "fluka", "vwr", "diffico",
    "bacto-", "bacto--", "bd--", "bd-",
    "hipolypepton", "phytone",
    "or",  # "X or Y" brand alternatives
}

CATALOG_RE = re.compile(r"\b[a-z]?[\d-]+[a-z]?\b", re.IGNORECASE)

TARGETS = [
    {
        "file": "Malt_Extract.yaml",
        "pure_tokens": {"malt", "extract", "powder"},
        "medium_markers": {"agar", "broth", "medium"},
    },
    {
        "file": "Trypticase_Peptone.yaml",
        "pure_tokens": {"trypticase", "tripticase", "peptone"},
        "medium_markers": {"soy", "soya", "agar", "broth", "tryptic", "medium", "tsb", "tsa"},
    },
]


def _norm_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _is_complex_medium(text: str, pure: set[str], markers: set[str]) -> bool:
    if not text:
        return False
    # Metadata lines stay.
    if re.match(r"^\s*(role:|properties:)", text, re.IGNORECASE):
        return False
    # If all alphabetic tokens are pure or brand/noise, not a complex medium.
    tokens = _norm_tokens(text)
    non_pure = tokens - pure - BRAND_TOKENS
    # Strip catalog-like tokens.
    non_pure = {t for t in non_pure if not CATALOG_RE.fullmatch(t)}
    if not non_pure:
        return False
    # Complex medium if any remaining token is in markers.
    return bool(non_pure & markers)


def _slug(label: str) -> str:
    cleaned = re.sub(r"[^\w\s()\-]", "", label).strip()
    parts = [p for p in re.split(r"\s+", cleaned) if p]
    return "_".join(p[0].upper() + p[1:] if p else "" for p in parts) or "Unnamed"


def _next_unmapped_id() -> int:
    max_id = 0
    for p in UNMAPPED_DIR.glob("*.yaml"):
        try:
            text = p.read_text()
        except Exception:
            continue
        m = re.search(r"identifier:\s*UNMAPPED_(\d+)", text)
        if m:
            n = int(m.group(1))
            if n > max_id:
                max_id = n
    return max_id + 1


def _make_unmapped_doc(label: str, identifier: str, source_file: str) -> dict:
    return {
        "identifier": identifier,
        "preferred_term": label,
        "synonyms": [
            {"synonym_text": label, "synonym_type": "RAW_TEXT",
             "source": f"extracted_from_{Path(source_file).stem.lower()}_yaml"}
        ],
        "mapping_status": "UNMAPPED",
        "occurrence_statistics": {
            "total_occurrences": 0, "media_count": 0,
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_extract_complex_media_synonyms",
                "action": "EXTRACTED_COMPLEX_MEDIUM",
                "changes": (
                    f"Extracted from {source_file} — '{label}' is a "
                    f"complete media formulation, not a synonym of the "
                    f"base ingredient. Pending curator re-mapping."
                ),
                "new_status": "UNMAPPED",
                "llm_assisted": False,
            }
        ],
        "notes": f"Extracted from over-conflated {source_file} synonyms",
    }


def process(target: dict, apply: bool, next_id_ref: list[int]) -> dict:
    path = MAPPED_DIR / target["file"]
    if not path.exists():
        return {"file": target["file"], "status": "MISSING"}

    doc = yaml.safe_load(path.read_text())
    pure = target["pure_tokens"]
    markers = target["medium_markers"]

    stays: list[dict] = []
    extracted: list[dict] = []
    for s in (doc.get("synonyms") or []):
        if not isinstance(s, dict):
            continue
        txt = (s.get("synonym_text", "") or "").strip()
        if _is_complex_medium(txt, pure, markers):
            extracted.append(s)
        else:
            stays.append(s)

    print(f"\n=== {target['file']} ===")
    print(f"  stays: {len(stays)} | extracted: {len(extracted)}")
    for s in extracted:
        print(f"    → {s['synonym_text']}")

    if not apply or not extracted:
        return {"file": target["file"], "stays": len(stays),
                "extracted": len(extracted), "created": 0}

    UNMAPPED_DIR.mkdir(parents=True, exist_ok=True)
    created = 0
    for s in extracted:
        slug = _slug(s["synonym_text"])
        out = UNMAPPED_DIR / f"{slug}.yaml"
        if out.exists():
            continue
        identifier = f"UNMAPPED_{next_id_ref[0]:04d}"
        next_id_ref[0] += 1
        new_doc = _make_unmapped_doc(s["synonym_text"], identifier, target["file"])
        out.write_text(yaml.safe_dump(new_doc, sort_keys=False, allow_unicode=True))
        created += 1

    doc["synonyms"] = stays
    doc.setdefault("curation_history", []).append({
        "timestamp": TIMESTAMP,
        "curator": "audit_extract_complex_media_synonyms",
        "action": "EXTRACTED_CONTAMINATING_SYNONYMS",
        "changes": (
            f"Extracted {len(extracted)} complex-medium synonyms "
            f"wrongly absorbed during duplicate-CHEBI consolidation. "
            f"Each is now its own UNMAPPED MIM record."
        ),
        "new_status": doc.get("mapping_status", "MAPPED"),
        "llm_assisted": False,
    })
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return {"file": target["file"], "stays": len(stays),
            "extracted": len(extracted), "created": created}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    next_id_ref = [_next_unmapped_id()]
    results = [process(t, args.apply, next_id_ref) for t in TARGETS]

    print("\n===== Summary =====")
    for r in results:
        print(f"  {r['file']}: extracted={r.get('extracted', '-')} "
              f"created={r.get('created', 0)}")


if __name__ == "__main__":
    main()
