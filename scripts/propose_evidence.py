#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Propose PMID + snippet candidates for a MIM ingredient (or set).

Phase 4 of the dismech-pattern port. Bridges Phase 1 (validator) by
giving curators a starter list of real PMIDs and verbatim snippets they
can paste into MIM's evidence claims.

Strategy (no LLM/provider — uses NCBI E-utilities directly):

  1. For each candidate ingredient, search PubMed with `<preferred_term>
     AND (culture OR medium OR growth)` to bias toward microbiology
     literature.
  2. Fetch top N abstracts (idempotent cache via the existing
     `references_cache/PMID_*.md` infrastructure).
  3. Extract sentences containing the ingredient name as snippet
     candidates.
  4. Emit a draft `EvidenceItem` YAML block per ingredient — curator
     reviews, edits, and pastes into the source-of-truth YAML.

The validator (Phase 1 — `validate_evidence_references.py`) then
verifies anything the curator ships actually appears in the cached
abstract.

Usage:

    python3 scripts/propose_evidence.py --slug Glucose
    python3 scripts/propose_evidence.py --yaml MediaIngredientMech/data/ingredients/mapped/Glucose.yaml
    python3 scripts/propose_evidence.py --top-occurrences 50  # batch

Output:
  workspace/reports/evidence_proposals/<slug>.md  (per-ingredient draft)
  workspace/reports/evidence_proposals/_summary.md (batch summary)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients" / "mapped"
CACHE_DIR = MIM_ROOT / "references_cache"
OUT_DIR = REPO_ROOT / "workspace" / "reports" / "evidence_proposals"

EUTILS_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
DEFAULT_RATE = 3.0
KEYED_RATE = 10.0

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


# ---------- imports we share with the fetcher ----------

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_pubmed_abstracts import (  # noqa: E402
    cache_path,
    fetch_pubmed_xml,
    parse_abstract,
    write_md,
)


# ---------- candidate selection ----------

def _load_candidate(yaml_path: Path) -> dict | None:
    try:
        with open(yaml_path) as f:
            y = yaml.safe_load(f) or {}
    except Exception:
        return None
    if not isinstance(y, dict):
        return None
    return {
        "yaml_path": str(yaml_path.relative_to(MIM_ROOT)),
        "slug": yaml_path.stem,
        "preferred_term": y.get("preferred_term") or yaml_path.stem,
        "ontology_id": ((y.get("ontology_mapping") or {}).get("ontology_id")
                        or y.get("identifier") or ""),
        "occurrences": ((y.get("occurrence_statistics") or {})
                        .get("total_occurrences", 0)),
    }


def _harvest_top_n(n: int) -> list[dict]:
    """Pick the N MIM ingredients with the highest total_occurrences
    that map to a CHEBI term (so the proposed evidence is grounded)."""
    cands: list[dict] = []
    for p in sorted(INGREDIENTS.glob("*.yaml")):
        c = _load_candidate(p)
        if not c:
            continue
        if not c["ontology_id"].startswith("CHEBI:"):
            continue
        cands.append(c)
    cands.sort(key=lambda x: -x["occurrences"])
    return cands[:n]


# ---------- PubMed esearch ----------

def esearch(query: str, retmax: int, api_key: str | None) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(retmax),
        "retmode": "json",
        "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key
    url = f"{EUTILS_SEARCH}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "MIM-evidence-proposer/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read().decode("utf-8")
    except Exception as e:
        print(f"  esearch error: {e}", file=sys.stderr)
        return []
    import json
    try:
        j = json.loads(data)
        return j["esearchresult"]["idlist"]
    except Exception:
        return []


def _build_query(term: str) -> str:
    # Bias toward microbiology / culture media context.
    return f'("{term}"[Title/Abstract]) AND (culture[All Fields] OR medium[All Fields] OR growth[All Fields] OR microbial[All Fields])'


# ---------- snippet extraction ----------

def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]


def extract_snippets(abstract: str, term: str, max_n: int = 2) -> list[str]:
    """Return up to max_n sentences from the abstract that contain the
    ingredient name (case-insensitive) — these are the curator's
    starting candidates."""
    if not abstract or not term:
        return []
    needle = term.lower()
    out: list[str] = []
    for s in _split_sentences(abstract):
        if needle in s.lower():
            out.append(s)
            if len(out) >= max_n:
                break
    return out


# ---------- per-candidate proposal ----------

def propose_for(c: dict, retmax: int, api_key: str | None,
                rate: float) -> dict:
    """Returns {pmids: [{pmid, title, year, snippets}], cached_in: [...], skipped: bool}."""
    term = c["preferred_term"]
    pmids = esearch(_build_query(term), retmax, api_key)
    if not pmids:
        return {"pmids": [], "skipped": True, "reason": "no PubMed hits"}
    time.sleep(1.0 / rate)

    proposals: list[dict] = []
    for pmid in pmids:
        cp = cache_path(pmid)
        if not cp.exists():
            try:
                xml = fetch_pubmed_xml(pmid, api_key)
            except Exception as e:
                print(f"  PMID {pmid}: {e}", file=sys.stderr)
                continue
            data = parse_abstract(xml)
            write_md(pmid, data)
            time.sleep(1.0 / rate)
        else:
            md = cp.read_text()
            # Re-parse loosely: extract title + abstract from MD
            m_title = re.search(r"\*\*Title:\*\*\s*(.+)", md)
            m_year = re.search(r"\*\*Year:\*\*\s*(\d{4})", md)
            abstract = md.split("## Abstract\n\n", 1)[-1].strip() if "## Abstract" in md else ""
            data = {
                "title": m_title.group(1) if m_title else "",
                "year": m_year.group(1) if m_year else "",
                "abstract": abstract,
            }

        snippets = extract_snippets(data["abstract"], term, max_n=2)
        if snippets:
            proposals.append({
                "pmid": pmid,
                "title": data["title"],
                "year": data["year"],
                "snippets": snippets,
            })
    return {"pmids": proposals, "skipped": False}


# ---------- output ----------

def render_proposal_md(c: dict, result: dict) -> str:
    md: list[str] = []
    md.append(f"# Evidence proposals — {c['preferred_term']}\n")
    md.append(f"**MIM YAML:** `{c['yaml_path']}`")
    md.append(f"**Ontology ID:** `{c['ontology_id']}`")
    md.append(f"**Occurrences:** {c['occurrences']}\n")

    if result.get("skipped") or not result["pmids"]:
        md.append("_No PubMed candidates returned for this query._\n")
        return "\n".join(md)

    md.append("## Draft `MappingEvidence` blocks\n")
    md.append("Paste the most relevant block(s) into the YAML's "
              "`ontology_mapping.evidence` list, then run "
              "`just validate-evidence` to confirm snippet integrity.\n")

    for hit in result["pmids"]:
        md.append(f"### PMID:{hit['pmid']} ({hit['year']})")
        md.append(f"_{hit['title']}_\n")
        for snippet in hit["snippets"]:
            md.append("```yaml")
            md.append("- evidence_type: LITERATURE")
            md.append(f"  source: PubMed search ({c['preferred_term']!r})")
            md.append(f"  pmid: '{hit['pmid']}'")
            md.append("  supports: SUPPORT  # curator-verify")
            # YAML-safe quoting via repr; clip very long
            s = snippet[:500].replace("\n", " ").replace("'", "''")
            md.append(f"  snippet: '{s}'")
            md.append("  explanation: >-")
            md.append("    Auto-proposed; curator should rephrase or remove.")
            md.append("```")
        md.append("")

    return "\n".join(md)


# ---------- driver ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--yaml", type=Path,
                     help="single MIM ingredient YAML")
    src.add_argument("--slug", type=str,
                     help="MIM ingredient slug (e.g. Glucose); resolves to "
                          "MediaIngredientMech/data/ingredients/mapped/<slug>.yaml")
    src.add_argument("--top-occurrences", type=int, metavar="N",
                     help="batch: top N high-occurrence CHEBI ingredients")
    ap.add_argument("--retmax", type=int, default=3,
                    help="abstracts to fetch per ingredient")
    ap.add_argument("--rate", type=float, default=None,
                    help="req/s; default: 3 (or 10 with NCBI_API_KEY)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("NCBI_API_KEY")
    rate = args.rate or (KEYED_RATE if api_key else DEFAULT_RATE)

    if args.yaml:
        c = _load_candidate(args.yaml)
        candidates = [c] if c else []
    elif args.slug:
        p = INGREDIENTS / f"{args.slug}.yaml"
        c = _load_candidate(p)
        candidates = [c] if c else []
    else:
        candidates = _harvest_top_n(args.top_occurrences)

    if not candidates:
        print("No candidates resolved.")
        return 1

    summary: list[str] = []
    summary.append("# Evidence proposals — batch summary\n")
    summary.append(f"Candidates processed: **{len(candidates)}**\n")
    summary.append("| # | Slug | CHEBI | Occurrences | Hits | Output |")
    summary.append("|--:|---|---|--:|--:|---|")

    n_hits_total = 0
    for i, c in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] {c['preferred_term']} ({c['ontology_id']})")
        result = propose_for(c, args.retmax, api_key, rate)
        n_hits = sum(len(h["snippets"]) for h in result.get("pmids", []))
        n_hits_total += n_hits
        out_path = OUT_DIR / f"{c['slug']}.md"
        out_path.write_text(render_proposal_md(c, result))
        print(f"  → {n_hits} snippet candidate(s); wrote {out_path.name}")
        summary.append(
            f"| {i} | `{c['slug']}` | `{c['ontology_id']}` | "
            f"{c['occurrences']} | {n_hits} | "
            f"[`{c['slug']}.md`](./{c['slug']}.md) |")

    (OUT_DIR / "_summary.md").write_text("\n".join(summary))
    print(f"\nWrote {len(candidates)} proposal files.")
    print(f"Total snippet candidates surfaced: {n_hits_total}")
    print(f"Summary: workspace/reports/evidence_proposals/_summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
