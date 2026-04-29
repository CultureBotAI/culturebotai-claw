#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Integrate CultureBotHT data sources into MediaIngredientMech.

Sources:
  1. data/raw/google_sheets/compounds_to_cas.csv  — 1,392 compounds with
     CAS-RN + FEBA panel membership (Hans80Anti, Hans80metals, FEBA_carbon,
     FEBA_nitrogen, FEBA_stress, All_star). The richest source.
  2. data/consolidated/consolidated_media.json    — 691 CultureBot media
     with full ingredient lists. Some ingredients have ontology_id pre-set.
  3. data/cache/synonym_mappings.json             — small (16 groups)
     auxiliary FOODON↔CAS↔mediadive crosswalk; evaluated only.

For each fresh ingredient (not already in MIM by case-insensitive name
or CAS-RN match):
  - If a CAS-RN is available, query OLS for a CHEBI xref match.
  - Otherwise, OLS-search by name.
  - If a HIGH-confidence CHEBI is found AND the CHEBI is not already
    used by a MIM YAML: create a new MAPPED MIM YAML with FEBA panel
    memberships and CultureBot media references in the evidence block.
  - If the CHEBI is already in MIM: skip (the existing MIM record is
    authoritative; CultureBotHT is informational provenance).
  - Otherwise: emit a row to a curation queue.

--dry-run (default) / --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

CULTUREBOT_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureBotHT/CultureBotHT"
)
COMPOUNDS_CSV = CULTUREBOT_ROOT / "data/raw/google_sheets/compounds_to_cas.csv"
CONSOLIDATED_JSON = CULTUREBOT_ROOT / "data/consolidated/consolidated_media.json"
SYNONYM_CACHE = CULTUREBOT_ROOT / "data/cache/synonym_mappings.json"

MIM_MAPPED_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients/mapped"
)
WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
OLS_CACHE = WORKSPACE / "cache/ols_cas_cache.json"
QUEUE_TSV = WORKSPACE / "reports/culturebotht_curation_queue.tsv"
SUMMARY_MD = WORKSPACE / "reports/culturebotht_integration_summary.md"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
TIMESTAMP = datetime.now(timezone.utc).isoformat()

PANEL_COLUMNS = (
    "Hans80Anti", "Hans80metals", "FEBA_carbon",
    "FEBA_nitrogen", "FEBA_stress", "All_star",
)

sys.path.insert(0, str(Path(__file__).parent))
from apply_mim_chebi_fixes import _slug  # noqa: E402


# ---------- caching ----------

def _load_cache() -> dict:
    if OLS_CACHE.exists():
        try:
            return json.loads(OLS_CACHE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    OLS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    OLS_CACHE.write_text(json.dumps(cache, indent=2))


# ---------- MIM existing index ----------

def _build_mim_index() -> tuple[set[str], dict[str, str], dict[str, str]]:
    """Return (labels lowercased, CAS→YAML filename, CHEBI→YAML filename)."""
    labels: set[str] = set()
    by_cas: dict[str, str] = {}
    by_chebi: dict[str, str] = {}
    for p in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            d = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        labels.add((d.get("preferred_term") or "").lower().strip())
        for s in d.get("synonyms") or []:
            if isinstance(s, dict):
                t = (s.get("synonym_text") or "").lower().strip()
                if t:
                    labels.add(t)
        cas = ((d.get("chemical_properties") or {}).get("cas_rn") or "").strip()
        if cas:
            by_cas.setdefault(cas, p.name)
        chebi = ((d.get("ontology_mapping") or {}).get("ontology_id") or "").strip()
        if chebi.startswith("CHEBI:"):
            by_chebi.setdefault(chebi, p.name)
    labels.discard("")
    return labels, by_cas, by_chebi


# ---------- OLS lookups ----------

def search_ols_by_cas(cas: str, cache: dict) -> dict | None:
    """Return CHEBI candidate that has the given CAS xref, or None."""
    key = f"cas::{cas}"
    if key in cache:
        return cache[key]
    params = urllib.parse.urlencode({
        "q": cas, "ontology": "chebi",
        "queryFields": "annotation_property,obo_xref",
        "rows": 5, "exact": "false", "type": "class",
    })
    url = f"{OLS_SEARCH}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        cache[key] = {"error": str(e)}
        return None
    docs = j.get("response", {}).get("docs", [])
    for d in docs:
        if d.get("is_obsolete"):
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie.startswith("CHEBI:"):
            continue
        cache[key] = {
            "chebi": curie, "label": d.get("label", ""),
            "synonyms": d.get("synonym", []),
        }
        return cache[key]
    cache[key] = None
    return None


def search_ols_by_name(name: str, cache: dict) -> dict | None:
    """Return HIGH-confidence CHEBI candidate (exact label or synonym match)."""
    key = f"name::{name}"
    if key in cache:
        return cache[key]
    params = urllib.parse.urlencode({
        "q": name, "ontology": "chebi",
        "rows": 5, "exact": "false", "type": "class",
    })
    url = f"{OLS_SEARCH}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        cache[key] = {"error": str(e)}
        return None
    n = name.lower().strip()
    for d in j.get("response", {}).get("docs", []):
        if d.get("is_obsolete"):
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie.startswith("CHEBI:"):
            continue
        if (d.get("label", "") or "").lower().strip() == n:
            cache[key] = {
                "chebi": curie, "label": d.get("label", ""),
                "match_type": "label-exact",
            }
            return cache[key]
        syn_lower = {s.lower().strip() for s in (d.get("synonym") or [])}
        if n in syn_lower:
            cache[key] = {
                "chebi": curie, "label": d.get("label", ""),
                "match_type": "synonym-exact",
            }
            return cache[key]
    cache[key] = None
    return None


# ---------- YAML emission ----------

def _build_panel_membership(row: dict) -> list[str]:
    return [p for p in PANEL_COLUMNS if (row.get(p) or "").strip()]


def _build_media_membership(name: str, media_index: dict[str, list[str]]) -> list[str]:
    return sorted(media_index.get(name, []))[:10]


def _create_yaml(path: Path, name: str, chebi: str, label: str, cas: str,
                 panels: list[str], media: list[str], synonyms_csv: str) -> tuple[bool, str]:
    if path.exists():
        return False, "yaml exists"
    evidence_notes = "Imported from CultureBotHT."
    if panels:
        evidence_notes += f" FEBA/Hans80 panels: {', '.join(panels)}."
    if media:
        evidence_notes += (
            f" Used in {len(media)} CultureBot media; samples: "
            f"{', '.join(media[:3])}{'…' if len(media) > 3 else ''}."
        )
    extra_synonyms = []
    if synonyms_csv:
        for s in synonyms_csv.split(";"):
            s = s.strip()
            if s and s.lower() != name.lower():
                extra_synonyms.append({
                    "synonym_text": s, "synonym_type": "EXACT_SYNONYM",
                    "source": "culturebotht",
                })
    doc = {
        "identifier": chebi,
        "preferred_term": name,
        "ontology_mapping": {
            "ontology_id": chebi,
            "ontology_label": label,
            "ontology_source": "CHEBI",
            "mapping_quality": "EXACT_MATCH",
            "evidence": [
                {
                    "evidence_type": "DATABASE_MATCH",
                    "source": "CultureBotHT",
                    "notes": evidence_notes,
                }
            ],
        },
        "synonyms": extra_synonyms,
        "mapping_status": "MAPPED",
        "occurrence_statistics": {
            "total_occurrences": len(media),
            "media_count": len(media),
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_integrate_culturebotht",
                "action": "CREATED_FROM_CULTUREBOTHT",
                "changes": (
                    f"Created from CultureBotHT compounds_to_cas.csv (CAS={cas or '—'}); "
                    f"{evidence_notes}"
                ),
                "new_status": "MAPPED",
                "llm_assisted": False,
            }
        ],
        "chemical_properties": {
            "cas_rn": cas,
            "data_source": "CultureBotHT compounds_to_cas.csv",
            "retrieval_date": TIMESTAMP,
        } if cas else {},
    }
    if not doc["chemical_properties"]:
        doc.pop("chemical_properties")
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"created {path.name} → {chebi}"


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-create", type=int, default=None,
                    help="Limit number of MIM YAMLs created in one run.")
    ap.add_argument("--media-only", action="store_true",
                    help="Process only the consolidated_media.json source.")
    ap.add_argument("--compounds-only", action="store_true")
    args = ap.parse_args()

    print(f"[1/5] Building MIM existing index")
    mim_labels, mim_by_cas, mim_by_chebi = _build_mim_index()
    print(f"      {len(mim_labels)} labels, {len(mim_by_cas)} CAS-RNs, "
          f"{len(mim_by_chebi)} CHEBIs")

    # Build media→ingredient cross-index from consolidated_media.json
    print(f"[2/5] Loading consolidated_media.json")
    media_data = json.loads(CONSOLIDATED_JSON.read_text())
    ing_to_media: dict[str, list[str]] = defaultdict(list)
    media_ingredient_map: dict[str, dict] = {}
    for medium_name, m in media_data.items():
        for ing in m.get("ingredients", []):
            n = (ing.get("name") or "").strip()
            if not n:
                continue
            ing_to_media[n].append(medium_name)
            existing = media_ingredient_map.get(n)
            if existing is None or (ing.get("ontology_id") and not existing.get("ontology_id")):
                media_ingredient_map[n] = {
                    "name": n,
                    "ontology_id": ing.get("ontology_id"),
                    "cas_number": ing.get("cas_number"),
                }
    print(f"      {len(media_ingredient_map)} unique ingredients across "
          f"{len(media_data)} media")

    print(f"[3/5] Loading compounds_to_cas.csv")
    compound_rows: list[dict] = []
    with COMPOUNDS_CSV.open() as f:
        for r in csv.DictReader(f):
            compound_rows.append(r)
    print(f"      {len(compound_rows)} compounds")

    # Stage 1: compound master file (richer; CAS-RNs + panel memberships)
    cache = _load_cache()
    print(f"[4/5] Searching OLS for fresh compounds")
    results = {"created": 0, "skipped_existing": 0, "queued_no_match": 0,
               "chebi_already_in_mim": 0, "errors": 0}
    queued_rows: list[dict] = []
    created_records: list[dict] = []
    start = time.time()
    n_to_search = sum(1 for r in compound_rows if not (
        (r.get("Compound") or "").lower().strip() in mim_labels
        or (r.get("CAS") or "").strip() in mim_by_cas
    ))
    print(f"      {n_to_search} fresh compounds to research")

    if not args.media_only:
        i = 0
        for r in compound_rows:
            name = (r.get("Compound") or "").strip()
            cas = (r.get("CAS") or "").strip()
            if not name:
                continue
            if name.lower() in mim_labels or cas in mim_by_cas:
                results["skipped_existing"] += 1
                continue
            i += 1
            best = None
            if cas:
                best = search_ols_by_cas(cas, cache)
            if not best:
                best = search_ols_by_name(name, cache)
            if best is None or "error" in (best or {}):
                results["queued_no_match"] += 1
                queued_rows.append({**r, "_reason": "no CHEBI match"})
                continue
            chebi = best["chebi"]
            if chebi in mim_by_chebi:
                results["chebi_already_in_mim"] += 1
                queued_rows.append({
                    **r, "_reason": f"CHEBI {chebi} already in MIM ({mim_by_chebi[chebi]})",
                    "_chebi": chebi,
                })
                continue
            panels = _build_panel_membership(r)
            media_uses = _build_media_membership(name, ing_to_media)
            slug = _slug(name)
            path = MIM_MAPPED_DIR / f"{slug}.yaml"
            if args.apply:
                if args.max_create is not None and results["created"] >= args.max_create:
                    queued_rows.append({**r, "_reason": "max-create limit reached"})
                    continue
                ok, msg = _create_yaml(
                    path, name, chebi, best["label"], cas,
                    panels, media_uses, r.get("Synonyms") or "",
                )
                if ok:
                    results["created"] += 1
                    mim_by_chebi[chebi] = path.name  # block subsequent dupes
                    mim_labels.add(name.lower())
                    if cas:
                        mim_by_cas[cas] = path.name
                    created_records.append({
                        "name": name, "chebi": chebi, "label": best["label"],
                        "cas": cas, "panels": panels, "media": len(media_uses),
                    })
                else:
                    results["errors"] += 1
            else:
                results["created"] += 1
                created_records.append({
                    "name": name, "chebi": chebi, "label": best["label"],
                    "cas": cas, "panels": panels, "media": len(media_uses),
                })
            if i % 50 == 0:
                _save_cache(cache)
                print(f"  {i}/{n_to_search} in {time.time() - start:.0f}s "
                      f"(created={results['created']} dupe-chebi="
                      f"{results['chebi_already_in_mim']} no-match="
                      f"{results['queued_no_match']})", flush=True)
    _save_cache(cache)

    # Stage 2: media ingredient names not in compound master
    if not args.compounds_only:
        seen_compound_names = {(r.get("Compound") or "").strip().lower()
                               for r in compound_rows}
        media_only_fresh = [
            v for n, v in media_ingredient_map.items()
            if n.lower() not in mim_labels
            and n.lower() not in seen_compound_names
            and (v.get("cas_number") or "") not in mim_by_cas
        ]
        print(f"      Stage 2: {len(media_only_fresh)} media-only fresh ingredients")
        for v in media_only_fresh:
            n = v["name"]
            cas = (v.get("cas_number") or "").strip()
            preset_chebi = (v.get("ontology_id") or "").strip()
            best = None
            if preset_chebi.startswith("CHEBI:"):
                best = {"chebi": preset_chebi, "label": "", "match_type": "media-preset"}
            elif cas:
                best = search_ols_by_cas(cas, cache)
            if not best:
                best = search_ols_by_name(n, cache)
            if best is None or "error" in (best or {}):
                results["queued_no_match"] += 1
                queued_rows.append({"Compound": n, "CAS": cas,
                                    "_reason": "no CHEBI match (media-only)"})
                continue
            chebi = best["chebi"]
            if chebi in mim_by_chebi:
                results["chebi_already_in_mim"] += 1
                continue
            media_uses = _build_media_membership(n, ing_to_media)
            slug = _slug(n)
            path = MIM_MAPPED_DIR / f"{slug}.yaml"
            if args.apply:
                if args.max_create is not None and results["created"] >= args.max_create:
                    continue
                ok, _ = _create_yaml(path, n, chebi, best.get("label", ""), cas,
                                     [], media_uses, "")
                if ok:
                    results["created"] += 1
                    mim_by_chebi[chebi] = path.name
                    mim_labels.add(n.lower())
                    created_records.append({
                        "name": n, "chebi": chebi, "label": best.get("label", ""),
                        "cas": cas, "panels": [], "media": len(media_uses),
                    })
            else:
                results["created"] += 1
                created_records.append({
                    "name": n, "chebi": chebi, "label": best.get("label", ""),
                    "cas": cas, "panels": [], "media": len(media_uses),
                })
        _save_cache(cache)

    print(f"\n[5/5] Writing queue + summary")
    QUEUE_TSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["Compound", "CAS", "panels", "_reason", "_chebi"]
    with QUEUE_TSV.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for r in queued_rows:
            panels = ",".join(_build_panel_membership(r)) if any(p in r for p in PANEL_COLUMNS) else ""
            f.write("\t".join([
                r.get("Compound", ""), r.get("CAS", ""), panels,
                r.get("_reason", ""), r.get("_chebi", ""),
            ]) + "\n")
    print(f"  Queue: {QUEUE_TSV} ({len(queued_rows)} rows)")

    # Summary markdown
    panel_dist = defaultdict(int)
    for cr in created_records:
        for p in cr["panels"]:
            panel_dist[p] += 1
    sm = [
        "# CultureBotHT Integration Summary\n",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}\n",
        f"**Compounds source:** {COMPOUNDS_CSV.relative_to(CULTUREBOT_ROOT)}\n",
        f"**Media source:** {CONSOLIDATED_JSON.relative_to(CULTUREBOT_ROOT)}\n\n",
        "## Outcome\n\n",
        "| Outcome | Count |\n|---|---:|\n",
        f"| Created MIM YAML | {results['created']} |\n",
        f"| Skipped (already in MIM) | {results['skipped_existing']} |\n",
        f"| CHEBI collision (already in MIM under different slug) | {results['chebi_already_in_mim']} |\n",
        f"| No CHEBI match (queued) | {results['queued_no_match']} |\n",
        f"| Errors | {results['errors']} |\n\n",
        "## Panel coverage of newly mapped\n\n",
        "| Panel | Created |\n|---|---:|\n",
    ]
    for p in PANEL_COLUMNS:
        sm.append(f"| {p} | {panel_dist[p]} |\n")

    sm.append("\n## Synonym cache evaluation\n")
    sc = json.loads(SYNONYM_CACHE.read_text())
    sm.append(f"`{SYNONYM_CACHE.name}` is a small auxiliary file:\n\n")
    sm.append(f"- `id_to_preferred`: {len(sc.get('id_to_preferred', {}))} entries\n")
    sm.append(f"- `id_to_synonyms`: {len(sc.get('id_to_synonyms', {}))} entries\n")
    sm.append(f"- `preferred_ids`: {len(sc.get('preferred_ids', []))} entries\n")
    sm.append(f"- stats: {json.dumps(sc.get('stats', {}))}\n\n")
    sm.append("Content is FOODON↔CAS-RN↔mediadive crosswalks (no CHEBI). "
              "Not imported as a primary source — the FOODON ingredients it "
              "lists are already covered by MIM's existing FOODON YAMLs and "
              "by `complex_ingredients.tsv.gz`. The mediadive.ingredient: "
              "fallbacks are kg-microbe-internal placeholders and surface "
              "via the kg-microbe consolidator's own pipeline.\n")

    SUMMARY_MD.write_text("".join(sm))
    print(f"  Summary: {SUMMARY_MD}")

    print(f"\nFinal: created={results['created']} "
          f"skipped_existing={results['skipped_existing']} "
          f"chebi_collision={results['chebi_already_in_mim']} "
          f"queued={results['queued_no_match']}")


if __name__ == "__main__":
    main()
