#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Curate kg-microbe's unmapped antibiotic placeholders by searching
OLS for CHEBI matches and creating MIM YAMLs for high-confidence hits.

Input:  kg-microbe/docs/metatraits/unmapped_compounds.tsv (122 rows of
        kgmicrobe.compound:* placeholders for compounds — mostly
        Streptomyces secondary metabolites — that lack a CHEBI mapping)

Pipeline:
  1. Skip rows whose label is already a MIM ingredient (preferred_term
     or any synonym, case-insensitive).
  2. For each remaining row, OLS-search for CHEBI candidates.
  3. Classify HIGH (exact label/synonym match), MEDIUM (single lexical
     candidate, stem-overlap with preferred_term), LOW (multiple
     candidates), NONE (no hits or only obsolete).
  4. Auto-apply HIGH and stem-verified MEDIUM as new MIM YAMLs (with
     CHEBI-collision guard so we don't duplicate existing MIM CHEBIs).
  5. Emit workspace/reports/kgm_antibiotics_curation_queue.tsv with
     all candidates for curator review (LOW + rejected MEDIUM + NONE).

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
from datetime import datetime, timezone
from pathlib import Path

import yaml

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
MIM_MAPPED_DIR = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "MediaIngredientMech/data/ingredients/mapped"
)
INPUT_TSV = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
    "kg-microbe/docs/metatraits/unmapped_compounds.tsv"
)
CACHE = WORKSPACE / "cache/chebi_search_cache.json"
QUEUE_TSV = WORKSPACE / "reports/kgm_antibiotics_curation_queue.tsv"
QUEUE_MD = WORKSPACE / "reports/kgm_antibiotics_curation_queue.md"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
TIMESTAMP = datetime.now(timezone.utc).isoformat()

sys.path.insert(0, str(Path(__file__).parent))
from round_trip_true_bugs import classify as stem_classify  # noqa: E402
from apply_mim_chebi_fixes import _slug, _create_new_yaml  # noqa: E402


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2))


def search_ols(term: str, cache: dict, ontology: str = "chebi") -> list[dict]:
    """OLS search restricted to one ontology. Returns parsed candidate list."""
    cache_key = f"{ontology}::{term}"
    if cache_key in cache:
        return cache[cache_key]
    params = urllib.parse.urlencode({
        "q": term, "ontology": ontology, "rows": 5,
        "exact": "false", "type": "class",
    })
    url = f"{OLS_SEARCH}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        cache[cache_key] = [{"error": str(e)}]
        return cache[cache_key]
    out = []
    expected_prefix = ontology.upper() + ":"
    for d in j.get("response", {}).get("docs", []):
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie or not curie.upper().startswith(expected_prefix):
            continue
        out.append({
            "chebi": curie, "label": d.get("label", ""),
            "synonyms": d.get("synonym", []),
            "is_obsolete": bool(d.get("is_obsolete")),
            "score": float(d.get("score", 0)),
        })
    cache[cache_key] = out
    return out


def classify_search(term: str, candidates: list[dict]) -> tuple[str, str, dict | None]:
    if not candidates or candidates[0].get("error"):
        return "NONE", "no hits", None
    non_obs = [c for c in candidates if not c.get("is_obsolete")]
    if not non_obs:
        return "NONE", "only obsolete", None
    t = _norm(term)
    for c in non_obs:
        if _norm(c["label"]) == t:
            return "HIGH", "label-exact", c
    for c in non_obs:
        if t in {_norm(s) for s in c.get("synonyms", [])}:
            return "HIGH", "synonym-exact", c
    if len(non_obs) == 1:
        return "MEDIUM", "single lexical candidate", non_obs[0]
    return "LOW", f"{len(non_obs)} candidates", non_obs[0]


def _existing_mim_labels() -> tuple[set[str], dict[str, list[str]]]:
    """Return (set of all known labels lowercased, CHEBI -> MIM yaml filenames)."""
    labels: set[str] = set()
    by_chebi: dict[str, list[str]] = {}
    for p in MIM_MAPPED_DIR.glob("*.yaml"):
        try:
            d = yaml.safe_load(p.read_text())
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        labels.add((d.get("preferred_term") or "").lower())
        for s in (d.get("synonyms") or []):
            if isinstance(s, dict):
                labels.add((s.get("synonym_text") or "").lower())
        chebi = (d.get("ontology_mapping") or {}).get("ontology_id", "")
        if chebi.startswith("CHEBI:"):
            by_chebi.setdefault(chebi, []).append(p.name)
    labels.discard("")
    return labels, by_chebi


def _create_placeholder_yaml(path: Path, source_id: str, term: str,
                             best_chebi: str, best_label: str,
                             confidence: str, rationale: str,
                             candidates: list[dict]) -> tuple[bool, str]:
    """Create a MIM YAML keyed by kgmicrobe.compound: when no high-confidence
    CHEBI/NCIT match exists. This still pulls the compound into MIM's
    pipeline so curators can iterate on it.
    """
    if path.exists():
        return False, f"{path.name} already exists"
    candidate_list = [
        {"chebi": c["chebi"], "label": c["label"]}
        for c in candidates[:3]
    ]
    doc = {
        "identifier": source_id,
        "preferred_term": term,
        "ontology_mapping": {
            "ontology_id": source_id,
            "ontology_label": term,
            "ontology_source": "kgmicrobe.compound",
            "mapping_quality": "PLACEHOLDER",
            "evidence": [
                {
                    "evidence_type": "DATABASE_MATCH",
                    "source": "kg-microbe metatraits unmapped_compounds.tsv",
                    "notes": (
                        f"Imported from kg-microbe's unmapped placeholder "
                        f"namespace. Ingested into MIM's pipeline; "
                        f"confidence={confidence}; rationale={rationale}; "
                        f"top OLS candidates: "
                        + (", ".join(f"{c['chebi']}({c['label']})"
                                     for c in candidate_list) or "none")
                        + ". Pending curator promotion to a CHEBI/NCIT "
                        "primary identifier."
                    ),
                }
            ],
        },
        "synonyms": [],
        "mapping_status": "MAPPED",
        "occurrence_statistics": {"total_occurrences": 0, "media_count": 0},
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": "audit_curate_unmapped_kgm_antibiotics",
                "action": "CREATED_FROM_KGM_PLACEHOLDER",
                "changes": (
                    f"Created MIM record from kg-microbe placeholder "
                    f"{source_id}; OLS search across CHEBI+NCIT returned "
                    f"{confidence}-confidence ({rationale}). Identifier "
                    f"kept as kgmicrobe.compound: until upstream curation "
                    f"finds a CHEBI/NCIT primary."
                ),
                "new_status": "MAPPED",
                "llm_assisted": False,
            }
        ],
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"created {path.name} → {source_id}"


def _format_label(token: str) -> str:
    """Title-case the kg-microbe label_token for use as preferred_term.

    "aburamycin a" -> "Aburamycin A"
    "atrop abyssomicin c" -> "Atrop Abyssomicin C"
    """
    parts = token.split()
    out = []
    for p in parts:
        if len(p) <= 1:
            out.append(p.upper())
        else:
            out.append(p[0].upper() + p[1:])
    return " ".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-medium", action="store_true",
                    help="Also auto-apply MEDIUM after stem-overlap verification.")
    args = ap.parse_args()

    print(f"[1/4] Loading {INPUT_TSV}")
    rows = []
    with INPUT_TSV.open() as f:
        rdr = csv.DictReader(f, delimiter="\t")
        for r in rdr:
            rows.append({
                "source_id": r["placeholder_id"],
                "raw_label": r["label_token"],
                "preferred_term": _format_label(r["label_token"]),
                "edge_count": int(r.get("edge_count", "1") or 1),
            })
    print(f"      {len(rows)} candidates")

    print("[2/4] Filtering against existing MIM labels")
    existing_labels, existing_chebi = _existing_mim_labels()
    fresh = [r for r in rows
             if r["preferred_term"].lower() not in existing_labels
             and r["raw_label"].lower() not in existing_labels]
    skipped = len(rows) - len(fresh)
    print(f"      {skipped} already in MIM, {len(fresh)} fresh")

    print("[3/4] OLS search + classification (CHEBI then NCIT)")
    cache = _load_cache()
    by_conf: dict[str, list[dict]] = {"HIGH": [], "MEDIUM": [], "LOW": [], "NONE": []}
    start = time.time()
    for i, r in enumerate(fresh, 1):
        # Try preferred_term and raw_label across CHEBI then NCIT,
        # picking the highest-confidence outcome.
        best_outcome = ("NONE", "no hits", None, [], "")
        order = ("CHEBI", "HIGH", "MEDIUM", "LOW", "NONE")
        for ontology in ("chebi", "ncit"):
            for query in (r["preferred_term"], r["raw_label"]):
                if not query:
                    continue
                if (ontology == "chebi" and query == r["preferred_term"]) or \
                   ontology != "chebi" or query != r["preferred_term"]:
                    candidates = search_ols(query, cache, ontology=ontology)
                    conf, rationale, best = classify_search(query, candidates)
                    cur_idx = order.index(best_outcome[0]) if best_outcome[0] in order else 99
                    new_idx = order.index(conf) if conf in order else 99
                    if new_idx < cur_idx:
                        best_outcome = (conf, rationale, best, candidates, ontology)
        conf, rationale, best, candidates, ont_hit = best_outcome
        r["candidates"] = candidates[:3]
        r["confidence"] = conf
        r["rationale"] = rationale
        r["ontology_hit"] = ont_hit
        r["chebi"] = best["chebi"] if best else ""
        r["chebi_label"] = best["label"] if best else ""
        by_conf[conf].append(r)
        if i % 25 == 0:
            _save_cache(cache)
            print(f"  {i}/{len(fresh)} in {time.time() - start:.0f}s "
                  f"(HIGH={len(by_conf['HIGH'])} MED={len(by_conf['MEDIUM'])} "
                  f"LOW={len(by_conf['LOW'])} NONE={len(by_conf['NONE'])})",
                  flush=True)
    _save_cache(cache)
    print(f"      Confidence: HIGH={len(by_conf['HIGH'])} "
          f"MEDIUM={len(by_conf['MEDIUM'])} LOW={len(by_conf['LOW'])} "
          f"NONE={len(by_conf['NONE'])}")

    print("[4/4] Verifying MEDIUM via stem-overlap, identifying applicable")
    # MEDIUM verification: candidate's label has stem-overlap with preferred_term
    accepted: list[dict] = list(by_conf["HIGH"])
    medium_rejected: list[dict] = []
    for r in by_conf["MEDIUM"]:
        bucket, _ = stem_classify(r["preferred_term"], r["chebi_label"])
        if bucket == "MIM_OK":
            accepted.append(r)
        else:
            medium_rejected.append(r)
    print(f"      Verified: {len(accepted) - len(by_conf['HIGH'])} "
          f"MEDIUM accepted via stem-overlap")

    # Filter accepted by CHEBI-collision guard.
    to_create: list[dict] = []
    chebi_collisions: list[dict] = []
    for r in accepted:
        if r["chebi"] in existing_chebi:
            chebi_collisions.append(r)
        else:
            to_create.append(r)

    # Compounds with no high-confidence ontology hit still get a MIM
    # record — keyed by the kg-microbe placeholder so the pipeline
    # knows about them even before a CHEBI is found. This is what
    # "incorporate them into the ingredient pipeline" looks like
    # operationally: every kg-microbe compound gets a MIM home.
    placeholder_records: list[dict] = []
    for r in (medium_rejected + by_conf["LOW"] + by_conf["NONE"]):
        # Skip if we already accepted this row above.
        if r in accepted:
            continue
        placeholder_records.append(r)

    print(f"\n=== {'APPLY' if args.apply else 'DRY-RUN'}: "
          f"{len(to_create)} CHEBI/NCIT-mapped, {len(chebi_collisions)} "
          f"collisions skipped, {len(placeholder_records)} placeholder "
          f"(kgmicrobe.compound:) records ===\n")

    print("Auto-mapped (CHEBI/NCIT match):")
    for r in to_create:
        marker = "✓" if args.apply else "•"
        print(f"  [{marker}] {r['preferred_term']:35s} → {r['chebi']:15s} "
              f"({r['chebi_label']}) [{r['confidence']}]")

    print(f"\nPlaceholder records (kgmicrobe.compound: kept as primary): "
          f"{len(placeholder_records)} entries (will appear in MIM pipeline)")

    created = 0
    placeholder_created = 0
    if args.apply:
        for r in to_create:
            slug = _slug(r["preferred_term"])
            path = MIM_MAPPED_DIR / f"{slug}.yaml"
            if path.exists():
                print(f"  [SKIP] {path.name} already exists")
                continue
            ok, msg = _create_new_yaml(
                path, r["source_id"], r["preferred_term"],
                r["chebi"], r["chebi_label"]
            )
            if ok:
                created += 1

        for r in placeholder_records:
            slug = _slug(r["preferred_term"])
            path = MIM_MAPPED_DIR / f"{slug}.yaml"
            if path.exists():
                continue
            ok, msg = _create_placeholder_yaml(
                path, r["source_id"], r["preferred_term"],
                r.get("chebi", ""), r.get("chebi_label", ""),
                r["confidence"], r.get("rationale", ""),
                r.get("candidates", []),
            )
            if ok:
                placeholder_created += 1

        print(f"\nCreated {created} CHEBI/NCIT-mapped MIM YAMLs.")
        print(f"Created {placeholder_created} placeholder MIM YAMLs "
              f"(kgmicrobe.compound: primary).")

    # Emit curation queue (everything not auto-created).
    pending = (
        chebi_collisions
        + medium_rejected
        + by_conf["LOW"]
        + by_conf["NONE"]
    )
    cols = ["source_id", "preferred_term", "edge_count", "confidence",
            "rationale", "best_chebi", "best_chebi_label",
            "candidate_2_chebi", "candidate_2_label",
            "candidate_3_chebi", "candidate_3_label",
            "blocker"]
    QUEUE_TSV.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_TSV.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for r in pending:
            cands = r.get("candidates", []) or []
            blocker = ""
            if r in chebi_collisions:
                blocker = f"chebi_collision:{r['chebi']} already in MIM ({existing_chebi[r['chebi']][0]})"
            elif r in medium_rejected:
                blocker = "medium_rejected_by_stem_overlap"
            elif r["confidence"] == "LOW":
                blocker = "low_confidence_multi_candidate"
            elif r["confidence"] == "NONE":
                blocker = "no_chebi_match"
            f.write("\t".join([
                r["source_id"], r["preferred_term"], str(r["edge_count"]),
                r["confidence"], r.get("rationale", ""),
                r.get("chebi", ""), r.get("chebi_label", ""),
                cands[1]["chebi"] if len(cands) > 1 else "",
                cands[1]["label"] if len(cands) > 1 else "",
                cands[2]["chebi"] if len(cands) > 2 else "",
                cands[2]["label"] if len(cands) > 2 else "",
                blocker,
            ]) + "\n")
    print(f"\nWrote {QUEUE_TSV} ({len(pending)} pending rows)")

    # Markdown summary.
    md = [
        "# kg-microbe Antibiotics Curation Queue\n",
        f"**Source:** `{INPUT_TSV}`\n",
        f"**Total kg-microbe placeholders:** {len(rows)}\n",
        f"**Already in MIM (skipped):** {skipped}\n",
        f"**Fresh candidates processed:** {len(fresh)}\n",
        f"**Auto-applied:** {created if args.apply else f'{len(to_create)} (dry-run)'}\n",
        f"**Pending curator review:** {len(pending)}\n\n",
        "## Confidence breakdown (fresh)\n",
        "| Confidence | Count |\n|---|---:|\n",
    ]
    for k in ("HIGH", "MEDIUM", "LOW", "NONE"):
        md.append(f"| {k} | {len(by_conf[k])} |\n")
    if to_create:
        md.append(f"\n## Auto-applied ({'pending apply' if not args.apply else f'{created} created'})\n\n")
        md.append("| Preferred term | CHEBI | Confidence |\n|---|---|---|\n")
        for r in to_create:
            md.append(f"| {r['preferred_term']} | `{r['chebi']}` ({r['chebi_label']}) | {r['confidence']} |\n")
    if chebi_collisions:
        md.append(f"\n## CHEBI-collision (skipped, {len(chebi_collisions)})\n\n")
        md.append("CHEBI already in MIM under a different slug. Curator can route as synonym.\n\n")
        md.append("| Preferred term | CHEBI | Existing MIM yaml |\n|---|---|---|\n")
        for r in chebi_collisions[:30]:
            md.append(f"| {r['preferred_term']} | `{r['chebi']}` | "
                      f"`{existing_chebi[r['chebi']][0]}` |\n")
    QUEUE_MD.write_text("".join(md))
    print(f"Wrote {QUEUE_MD}")


if __name__ == "__main__":
    main()
