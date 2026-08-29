#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Backfill `ontology_mapping` with a parent-class ontology term for
MIM records whose primary identifier is a non-ontology placeholder
(`kgmicrobe.compound:*`, `kgmicrobe.ingredient:*`, `UNMAPPED_*`,
`cas:*`).

The MIM record keeps its placeholder/registry primary identifier but
gains a NARROW_MATCH ontology mapping pointing at the most specific
applicable parent term in CHEBI / FOODON / ENVO / NCIT / MICRO / mesh
/ BTO / UBERON / GO / DOID / HP / MONDO. Downstream KGX consumers see
this as `kgmicrobe.compound:foo skos:narrowMatch CHEBI:bar` and can
build subclass edges accordingly.

Two strategies, applied in order per record:

  1. Stem-substring cascade across the broader OLS ontology set —
     accept when the normalized ontology label is a contiguous
     substring of the ingredient name AND the label has ≥ 2 alpha
     tokens (drops trivial single-word matches).
  2. PubChem CID → CHEBI xref lookup — only for cas:* records that
     already have a `chemical_properties.pubchem_cid` populated by
     the CAS-RN backfill. Walks PubChem's xref endpoint to find a
     CHEBI cross-reference if any.

The detected parent is written to `ontology_mapping.ontology_id` /
`ontology_label` / `ontology_source` with
`mapping_quality: NARROW_MATCH` and a fresh evidence entry.
The PRIMARY `identifier` is left unchanged.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))
from kg_microbe_fleet import require_mech_roots  # noqa: E402

MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients"
CACHE_PATH = REPO_ROOT / "workspace" / "cache" / "parent_terms_cache.json"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "parent_term_backfill.tsv"
OUT_MD = OUT_DIR / "parent_term_backfill.md"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
RATE_DELAY = 0.20

CASCADE = (
    ("chebi", "CHEBI:"),
    ("foodon", "FOODON:"),
    ("envo", "ENVO:"),
    ("uberon", "UBERON:"),
    ("ncit", "NCIT:"),
    ("micro", "MICRO:"),
    ("mesh", "mesh:"),
    ("bto", "BTO:"),
    ("go", "GO:"),
    ("doid", "DOID:"),
    ("hp", "HP:"),
    ("mondo", "MONDO:"),
)

_TRAILING_NUM = re.compile(r"\s*\d+\s*$")
_TRAILING_LETTER = re.compile(r"\s+[A-Z]\s*$")
_PARENS = re.compile(r"\s*\([^)]*\)\s*")
_STEREO_RE = re.compile(r"^\((?:[REZSL]|R/S|S-|R-)\)-")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def _http_json(url: str, timeout: int = 15) -> dict | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": "MIM-parent-backfill/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def normalize_variants(name: str) -> list[str]:
    """Generate name variants for cascade lookup, broadest-first."""
    out = [name.strip()]
    n = name.strip()
    for pat in (_PARENS, _TRAILING_NUM, _TRAILING_LETTER, _STEREO_RE):
        n2 = pat.sub("", n).strip()
        if n2 and n2 not in out:
            out.append(n2)
    return out


def ols_stem_or_exact(term: str, ontology: str, prefix: str) -> dict:
    """Returns the best OLS hit for term in ontology — label-exact /
    synonym-exact preferred; falls back to stem-substring (label IS a
    contiguous substring of the term, label has ≥ 2 alpha tokens)."""
    params = urllib.parse.urlencode({
        "q": term, "ontology": ontology, "rows": 8,
        "exact": "false", "type": "class",
    })
    j = _http_json(f"{OLS_SEARCH}?{params}")
    if not j:
        return {}
    n = _norm(term)
    fuzzy_top = None
    for d in j.get("response", {}).get("docs", []):
        if d.get("is_obsolete"):
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie or not curie.upper().startswith(prefix.upper()):
            continue
        label = d.get("label", "")
        l = _norm(label)
        if l == n:
            return {"id": curie, "label": label, "match": "label-exact",
                    "ontology": ontology}
        if n in {_norm(s) for s in (d.get("synonym") or [])}:
            return {"id": curie, "label": label, "match": "synonym-exact",
                    "ontology": ontology}
        # Stem rule: label has ≥ 2 alpha tokens AND is a contiguous
        # substring of the term.
        if (l and len(re.findall(r"[a-z]{2,}", l)) >= 2 and l in n
                and fuzzy_top is None):
            fuzzy_top = {"id": curie, "label": label, "match": "stem-substring",
                         "ontology": ontology}
    return fuzzy_top or {}


def cascade_parent(name: str) -> dict:
    """Walk the cascade across name variants, return first match."""
    for variant in normalize_variants(name):
        for ontology, prefix in CASCADE:
            hit = ols_stem_or_exact(variant, ontology, prefix)
            time.sleep(RATE_DELAY)
            if hit:
                hit["matched_via"] = variant
                return hit
    return {}


def pubchem_cid_chebi(cid: int) -> dict:
    """For a PubChem CID, look for a CHEBI cross-reference and fetch
    its label. Returns {id: CHEBI:N, label: ..., match: "pubchem-xref"}
    or {}."""
    url = (f"{PUBCHEM_BASE}/cid/{cid}/xrefs/RegistryID/JSON")
    j = _http_json(url)
    if not j:
        return {}
    info = ((j.get("InformationList") or {}).get("Information") or [{}])[0]
    regs = info.get("RegistryID") or []
    chebi_ids = [r for r in regs if isinstance(r, str) and r.startswith("CHEBI:")]
    if not chebi_ids:
        return {}
    chebi = chebi_ids[0]
    # Try to fetch the label via OLS so the YAML record has
    # human-readable context.
    label_resp = _http_json(
        f"{OLS_SEARCH}?q={urllib.parse.quote(chebi)}&ontology=chebi&rows=1")
    label = ""
    if label_resp:
        docs = label_resp.get("response", {}).get("docs", [])
        if docs:
            label = docs[0].get("label", "")
    return {"id": chebi, "label": label, "match": "pubchem-xref",
            "ontology": "chebi", "matched_via": f"pubchem CID {cid}"}


def needs_parent(record: dict) -> bool:
    ident = (record.get("identifier") or "").strip()
    if not ident.startswith(("kgmicrobe.compound:", "kgmicrobe.ingredient:",
                              "UNMAPPED_", "cas:")):
        return False
    om = record.get("ontology_mapping") or {}
    onto_id = (om.get("ontology_id") or "").strip()
    # If ontology_id is set AND it's a real ontology term (not the
    # primary self), this record already has a parent.
    if onto_id and onto_id != ident and any(
            onto_id.startswith(p) for p in
            ("CHEBI:", "FOODON:", "ENVO:", "UBERON:", "NCIT:",
             "MICRO:", "mesh:", "BTO:", "GO:", "DOID:", "HP:", "MONDO:")):
        return False
    return True


def apply_parent(record: dict, parent: dict) -> None:
    om = record.setdefault("ontology_mapping", {})
    om["ontology_id"] = parent["id"]
    om["ontology_label"] = parent.get("label", "")
    prefix = parent["id"].split(":", 1)[0].upper() if ":" in parent["id"] else ""
    om["ontology_source"] = prefix
    om["mapping_quality"] = "NARROW_MATCH"
    om.setdefault("evidence", []).append({
        "evidence_type": "DATABASE_MATCH",
        "source": (f"{prefix} via {('PubChem' if parent['match'] == 'pubchem-xref' else 'OLS')} "
                   f"({parent['match']})"),
        "notes": (f"Parent class identified via {parent['match']}; "
                  f"matched_via={parent.get('matched_via', '')!r}"),
    })
    record.setdefault("curation_history", []).append({
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "curator": "backfill_parent_terms",
        "action": f"BACKFILL_PARENT_{prefix}",
        "changes": (f"set ontology_mapping parent={parent['id']} "
                    f"({parent['match']})"),
        "llm_assisted": False,
    })


def load_cache() -> dict:
    if CACHE_PATH.is_file():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--bucket",
                    choices=["all", "kgm-compound", "kgm-ingredient",
                             "unmapped", "cas"],
                    default="all")
    args = ap.parse_args()
    # Verify the checkout before doing work; module-level roots stay
    # plain paths so importing this file never needs one (#176).
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    print(f"Cache: {len(cache)} entries")

    targets: list[tuple[Path, dict]] = []
    for path in sorted(INGREDIENTS.rglob("*.yaml")):
        try:
            with open(path) as f:
                record = yaml.safe_load(f) or {}
        except Exception:
            continue
        if not needs_parent(record):
            continue
        ident = record.get("identifier", "")
        if args.bucket == "kgm-compound" and not ident.startswith("kgmicrobe.compound:"):
            continue
        if args.bucket == "kgm-ingredient" and not ident.startswith("kgmicrobe.ingredient:"):
            continue
        if args.bucket == "unmapped" and not ident.startswith("UNMAPPED_"):
            continue
        if args.bucket == "cas" and not ident.startswith("cas:"):
            continue
        targets.append((path, record))
    if args.limit:
        targets = targets[: args.limit]
    print(f"Records needing parent: {len(targets)} (bucket={args.bucket})")

    counts: dict[str, int] = {}
    rows: list[dict] = []

    for i, (path, record) in enumerate(targets, 1):
        ident = record.get("identifier", "")
        name = record.get("preferred_term") or path.stem

        cache_key = f"{ident}|{name}"
        if cache_key in cache:
            parent = cache[cache_key] or {}
        else:
            parent = {}
            # Strategy 1: PubChem CID → CHEBI xref (cas:* with cid)
            if ident.startswith("cas:"):
                cp = record.get("chemical_properties") or {}
                cid = cp.get("pubchem_cid")
                if cid:
                    parent = pubchem_cid_chebi(int(cid))
                    time.sleep(RATE_DELAY)
            # Strategy 2: OLS cascade
            if not parent:
                parent = cascade_parent(name)
            cache[cache_key] = parent
            if i % 10 == 0:
                save_cache(cache)

        verdict = "FOUND" if parent else "NO_HIT"
        counts[verdict] = counts.get(verdict, 0) + 1

        action = ""
        if parent and args.apply:
            apply_parent(record, parent)
            with open(path, "w") as f:
                yaml.safe_dump(record, f, default_flow_style=False,
                               allow_unicode=True, sort_keys=False)
            action = "applied"
            counts["APPLIED"] = counts.get("APPLIED", 0) + 1
        elif parent:
            action = "would_apply"

        rows.append({
            "yaml_path": str(path.relative_to(MIM_ROOT)),
            "identifier": ident,
            "preferred_term": name,
            "verdict": verdict,
            "parent_id": parent.get("id", ""),
            "parent_label": parent.get("label", ""),
            "match_type": parent.get("match", ""),
            "matched_via": parent.get("matched_via", ""),
            "action": action,
        })

        if i % 25 == 0 or verdict == "FOUND":
            tag = (f' → {parent.get("id","")} ({parent.get("ontology","")})'
                   if parent else '')
            print(f"  [{i}/{len(targets)}] {name[:50]}: {verdict}{tag}")

    save_cache(cache)

    with open(OUT_TSV, "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                               delimiter="\t")
            w.writeheader()
            w.writerows(rows)

    md = ["# Parent-term backfill\n",
          f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**",
          f"Bucket: **{args.bucket}**",
          f"Records reviewed: **{len(targets)}**\n",
          "\n## Outcomes\n", "| verdict | count |", "|---|---:|"]
    for k in sorted(counts, key=lambda x: -counts[x]):
        md.append(f"| `{k}` | {counts[k]} |")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print()
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
