#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Add the remaining CultureBotHT compounds to MIM as either MAPPED records
keyed by `cas:<cas-rn>` (when a CAS-RN is available but no CHEBI exists)
or UNMAPPED_NNNN records (no CAS-RN at all).

Both buckets land in MIM and participate in the curation lifecycle —
the SSSOM publishes the cas: rows; the unmapped YAMLs are visible to
curators via data/ingredients/unmapped/.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

CULTUREBOT_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureBotHT/CultureBotHT"
)
COMPOUNDS_CSV = CULTUREBOT_ROOT / "data/raw/google_sheets/compounds_to_cas.csv"
CONSOLIDATED_JSON = CULTUREBOT_ROOT / "data/consolidated/consolidated_media.json"

MIM_INGREDIENTS = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients"
)
MAPPED_DIR = MIM_INGREDIENTS / "mapped"
UNMAPPED_DIR = MIM_INGREDIENTS / "unmapped"

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
SUMMARY_MD = WORKSPACE / "reports/culturebotht_remaining_summary.md"

PANEL_COLUMNS = (
    "Hans80Anti", "Hans80metals", "FEBA_carbon",
    "FEBA_nitrogen", "FEBA_stress", "All_star",
)
TIMESTAMP = datetime.now(timezone.utc).isoformat()

sys.path.insert(0, str(Path(__file__).parent))
from apply_mim_chebi_fixes import _slug  # noqa: E402


def _build_mim_index() -> tuple[set[str], set[str], set[str]]:
    labels: set[str] = set()
    cas_set: set[str] = set()
    slugs: set[str] = set()
    for d in (MAPPED_DIR, UNMAPPED_DIR):
        for p in d.glob("*.yaml"):
            try:
                doc = yaml.safe_load(p.read_text())
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            labels.add((doc.get("preferred_term") or "").lower().strip())
            for s in doc.get("synonyms") or []:
                if isinstance(s, dict):
                    labels.add((s.get("synonym_text") or "").lower().strip())
            cas = ((doc.get("chemical_properties") or {}).get("cas_rn") or "").strip()
            if cas:
                cas_set.add(cas)
            slugs.add(p.stem.lower())
    labels.discard("")
    return labels, cas_set, slugs


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


def _make_cas_yaml(name: str, cas: str, panels: list[str],
                   media_uses: list[str], synonyms_csv: str) -> dict:
    primary = f"cas:{cas}"
    extra_synonyms = []
    if synonyms_csv:
        for s in synonyms_csv.split(";"):
            s = s.strip()
            if s and s.lower() != name.lower():
                extra_synonyms.append({
                    "synonym_text": s, "synonym_type": "EXACT_SYNONYM",
                    "source": "culturebotht",
                })
    notes = (
        f"Imported from CultureBotHT. CAS-RN {cas} present, but no CHEBI "
        f"entry exists (checked OAK CHEBI sqlite + PubChem CID synonyms). "
    )
    if panels:
        notes += f"FEBA/Hans80 panels: {', '.join(panels)}. "
    if media_uses:
        notes += (
            f"Used in {len(media_uses)} CultureBot media; samples: "
            f"{', '.join(media_uses[:3])}{'…' if len(media_uses) > 3 else ''}. "
        )
    notes += "Curator can promote to a CHEBI primary if/when CHEBI adds the term."
    return {
        "identifier": primary,
        "preferred_term": name,
        "ontology_mapping": {
            "ontology_id": primary,
            "ontology_label": name,
            "ontology_source": "CAS",
            "mapping_quality": "FALLBACK_REGISTRY",
            "evidence": [
                {
                    "evidence_type": "DATABASE_MATCH",
                    "source": "CultureBotHT",
                    "notes": notes,
                }
            ],
        },
        "synonyms": extra_synonyms,
        "mapping_status": "MAPPED",
        "occurrence_statistics": {
            "total_occurrences": len(media_uses),
            "media_count": len(media_uses),
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_add_remaining_culturebotht",
                "action": "CREATED_FROM_CAS_FALLBACK",
                "changes": (
                    f"Created with cas:{cas} as primary identifier; "
                    f"no CHEBI entry exists for this compound."
                ),
                "new_status": "MAPPED",
                "llm_assisted": False,
            }
        ],
        "chemical_properties": {
            "cas_rn": cas,
            "data_source": "CultureBotHT compounds_to_cas.csv",
            "retrieval_date": TIMESTAMP,
        },
    }


def _make_unmapped_yaml(name: str, identifier: str, source: str,
                        media_uses: list[str], synonyms_csv: str) -> dict:
    extra_synonyms = []
    if synonyms_csv:
        for s in synonyms_csv.split(";"):
            s = s.strip()
            if s and s.lower() != name.lower():
                extra_synonyms.append({
                    "synonym_text": s, "synonym_type": "RAW_TEXT",
                    "source": "culturebotht",
                })
    notes = f"Imported from CultureBotHT ({source}). "
    if media_uses:
        notes += (
            f"Used in {len(media_uses)} CultureBot media; samples: "
            f"{', '.join(media_uses[:3])}{'…' if len(media_uses) > 3 else ''}. "
        )
    notes += "No CAS-RN or CHEBI mapping available; curator review needed."
    doc = {
        "identifier": identifier,
        "preferred_term": name,
        "synonyms": extra_synonyms or [
            {"synonym_text": name, "synonym_type": "RAW_TEXT",
             "source": "culturebotht"}
        ],
        "mapping_status": "UNMAPPED",
        "occurrence_statistics": {
            "total_occurrences": len(media_uses),
            "media_count": len(media_uses),
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_add_remaining_culturebotht",
                "action": "CREATED_AS_UNMAPPED",
                "changes": notes,
                "new_status": "UNMAPPED",
                "llm_assisted": False,
            }
        ],
        "notes": notes,
    }
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print(f"[1/4] Indexing existing MIM")
    labels, cas_set, slugs = _build_mim_index()
    print(f"      {len(labels)} labels, {len(cas_set)} CAS, {len(slugs)} slugs")

    # Source 1: compounds_to_cas.csv
    print(f"[2/4] Loading compounds_to_cas.csv + consolidated_media.json")
    compounds: list[dict] = []
    panel_lookup: dict[str, list[str]] = {}
    cas_lookup: dict[str, str] = {}
    syn_lookup: dict[str, str] = {}
    with COMPOUNDS_CSV.open() as f:
        for r in csv.DictReader(f):
            name = (r.get("Compound") or "").strip()
            cas = (r.get("CAS") or "").strip()
            if not name:
                continue
            compounds.append({"name": name, "cas": cas, "row": r})
            ps = [p for p in PANEL_COLUMNS if (r.get(p) or "").strip()]
            if ps:
                panel_lookup[name] = ps
            if cas:
                cas_lookup[name] = cas
            syn = (r.get("Synonyms") or "").strip()
            if syn:
                syn_lookup[name] = syn

    media_data = json.loads(CONSOLIDATED_JSON.read_text())
    media_names: set[str] = set()
    ing_to_media: dict[str, list[str]] = defaultdict(list)
    media_cas_lookup: dict[str, str] = {}
    for medium_name, m in media_data.items():
        for ing in m.get("ingredients", []):
            n = (ing.get("name") or "").strip()
            if not n:
                continue
            media_names.add(n)
            ing_to_media[n].append(medium_name)
            cn = (ing.get("cas_number") or "").strip()
            if cn and n not in media_cas_lookup:
                media_cas_lookup[n] = cn

    # Filter to fresh entries (not in MIM yet).
    cas_fresh = [c for c in compounds
                 if c["name"].lower() not in labels
                 and c["cas"]
                 and c["cas"] not in cas_set]
    no_cas_fresh = [c for c in compounds
                    if c["name"].lower() not in labels
                    and not c["cas"]]
    media_only_fresh = []
    seen_compound_names = {c["name"].lower() for c in compounds}
    for n in media_names:
        if n.lower() in labels:
            continue
        if n.lower() in seen_compound_names:
            continue
        cas = media_cas_lookup.get(n, "")
        if cas and cas in cas_set:
            continue
        media_only_fresh.append({"name": n, "cas": cas})

    print(f"      Compound master with CAS: {len(cas_fresh)}")
    print(f"      Compound master no CAS:    {len(no_cas_fresh)}")
    print(f"      Media-only fresh:          {len(media_only_fresh)}")

    UNMAPPED_DIR.mkdir(parents=True, exist_ok=True)
    next_id = _next_unmapped_id()

    # Track slugs we mint this run to avoid duplicate filenames within
    # the run.
    minted_slugs: set[str] = set()

    counts = {"cas_created": 0, "unmapped_created": 0, "skipped_dup_slug": 0,
              "skipped_dup_cas": 0}
    cas_records = []
    unmapped_records = []

    for c in cas_fresh:
        name, cas = c["name"], c["cas"]
        slug = _slug(name)
        if slug.lower() in slugs or slug.lower() in minted_slugs:
            counts["skipped_dup_slug"] += 1
            continue
        path = MAPPED_DIR / f"{slug}.yaml"
        media_uses = ing_to_media.get(name, [])
        panels = panel_lookup.get(name, [])
        synonyms_csv = syn_lookup.get(name, "")
        if args.apply:
            doc = _make_cas_yaml(name, cas, panels, media_uses, synonyms_csv)
            path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
            cas_set.add(cas)
            slugs.add(slug.lower())
            minted_slugs.add(slug.lower())
        else:
            minted_slugs.add(slug.lower())
        counts["cas_created"] += 1
        cas_records.append({"name": name, "cas": cas, "panels": panels})

    for c in no_cas_fresh + media_only_fresh:
        name = c["name"]
        # If a media-only entry has a CAS-RN, route to cas: bucket instead.
        cas = c.get("cas", "")
        if cas and cas not in cas_set:
            slug = _slug(name)
            if slug.lower() in slugs or slug.lower() in minted_slugs:
                counts["skipped_dup_slug"] += 1
                continue
            path = MAPPED_DIR / f"{slug}.yaml"
            media_uses = ing_to_media.get(name, [])
            if args.apply:
                doc = _make_cas_yaml(name, cas, [], media_uses, "")
                path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
                cas_set.add(cas)
                slugs.add(slug.lower())
                minted_slugs.add(slug.lower())
            else:
                minted_slugs.add(slug.lower())
            counts["cas_created"] += 1
            cas_records.append({"name": name, "cas": cas, "panels": []})
            continue

        slug = _slug(name)
        if slug.lower() in slugs or slug.lower() in minted_slugs:
            counts["skipped_dup_slug"] += 1
            continue
        path = UNMAPPED_DIR / f"{slug}.yaml"
        identifier = f"UNMAPPED_{next_id:04d}"
        next_id += 1
        media_uses = ing_to_media.get(name, [])
        synonyms_csv = syn_lookup.get(name, "")
        source = "compounds_to_cas.csv (no CAS-RN)" if c in no_cas_fresh \
            else "consolidated_media.json (media-only)"
        if args.apply:
            doc = _make_unmapped_yaml(
                name, identifier, source, media_uses, synonyms_csv,
            )
            path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
            slugs.add(slug.lower())
            minted_slugs.add(slug.lower())
        else:
            minted_slugs.add(slug.lower())
        counts["unmapped_created"] += 1
        unmapped_records.append({"name": name, "id": identifier, "source": source})

    print(f"\n[3/4] {'APPLY' if args.apply else 'DRY-RUN'} totals:")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    # Summary
    sm = [
        "# CultureBotHT — Remaining Compounds Added to MIM\n",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}\n",
        f"**Compounds source:** {COMPOUNDS_CSV.relative_to(CULTUREBOT_ROOT)}\n",
        f"**Media source:** {CONSOLIDATED_JSON.relative_to(CULTUREBOT_ROOT)}\n\n",
        "## Outcome\n\n",
        "| Bucket | Count | Destination |\n|---|---:|---|\n",
        f"| MAPPED w/ `cas:` primary (no CHEBI exists) | {counts['cas_created']} | "
        f"`data/ingredients/mapped/` |\n",
        f"| UNMAPPED placeholder | {counts['unmapped_created']} | "
        f"`data/ingredients/unmapped/UNMAPPED_NNNN.yaml` |\n",
        f"| Skipped (duplicate slug) | {counts['skipped_dup_slug']} | — |\n\n",
        "## Why these aren't CHEBI-mapped\n\n",
        "- **`cas:` MAPPED records**: have CAS-RN but CHEBI doesn't yet "
        "have a term for them (Sigma catalog specialties, modified peptides, "
        "novel agonists/antagonists, complex hydrates, etc.). Curators "
        "can promote to a CHEBI primary if/when CHEBI adds the term.\n",
        "- **UNMAPPED placeholders**: biological materials, mixtures, or "
        "extracted ingredients with no CAS-RN in CultureBotHT — need name-"
        "level curation. Live in `data/ingredients/unmapped/` so they're "
        "discoverable to curators without polluting the mapped/ tier.\n",
    ]
    SUMMARY_MD.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD.write_text("".join(sm))
    print(f"\n[4/4] Summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()
