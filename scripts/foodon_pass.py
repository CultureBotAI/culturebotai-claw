#!/usr/bin/env /opt/homebrew/bin/python3.13
"""FOODON-focused resolver pass for heuristic-complex MIM ingredients.

Walks the unmapped-inventory's "complex (heuristic)" bucket — names
matching the _COMPLEX_RE pattern (yeast extract, peptone, casein,
brain heart infusion, etc.) — and searches FOODON via OLS for each.

Outcomes per row:

  HIGH       label-exact match in FOODON (auto-applicable)
  HIGH       synonym-exact match in FOODON (auto-applicable)
  MEDIUM     fuzzy match (top OLS hit but not exact)
  NONE       no FOODON candidate

For each HIGH match, the script can either:
  a) UPGRADE_MIM_PRIMARY — when the name is already a MIM record
     with a kgmicrobe.compound:* / UNMAPPED_* / placeholder primary,
     re-point the identifier to the FOODON term
  b) CREATE_MIM_YAML — when no MIM record exists yet (rare; most
     heuristic-complex names already have a MIM home)

CLI:
  --apply    write YAMLs (default: dry-run + report only)
  --high-only   only act on HIGH matches (skip MEDIUM)

Outputs:
  workspace/reports/foodon_pass.{tsv,md}
"""
from __future__ import annotations

import argparse
import csv
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
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INVENTORY_TSV = REPO_ROOT / "workspace" / "reports" / "unmapped_inventory.tsv"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "foodon_pass.tsv"
OUT_MD = OUT_DIR / "foodon_pass.md"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"
RATE_DELAY = 0.25  # 4 req/s


sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_ingredient_type import (  # noqa: E402
    _COMPLEX_RE,
    append_curation_event,
    load_yaml,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from classify_ingredient_type import dump_yaml  # noqa: E402

from kg_microbe_write import ValidatedWriteTransaction  # noqa: E402

# Staged rather than written per record: a failure part-way through a per-record
# write loop leaves an unknown subset of MediaIngredientMech modified with no
# recovery path (#156). The transaction validates the whole set first, replaces
# atomically, and journals prior contents.
_TRANSACTION = None


def _staged_write(path, record) -> None:
    """Stage a record into the run's transaction instead of writing it."""
    if _TRANSACTION is None:
        raise RuntimeError("no write transaction is open for this run")
    _TRANSACTION.stage(path, dump_yaml(record))



def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


# Tokens that contribute no discriminating signal (don't gate matches).
_STOP_TOKENS = frozenset({
    "the", "a", "an", "of", "and", "or", "in", "on", "with",
    # Domain-stop words that appear in many media names but say nothing
    # specific (a match on these alone is too generic):
    "no", "nr", "type", "grade", "form", "powder", "solution",
    "extract", "broth", "infusion", "agar",
})


def _tokens(s: str) -> set[str]:
    """Lowercase tokens (alpha runs of length ≥ 2), minus stop words."""
    return {t for t in re.findall(r"[A-Za-z]{2,}", (s or "").lower())
            if t not in _STOP_TOKENS}


def score_fuzzy_match(name: str, label: str) -> str:
    """Re-score a fuzzy-top hit using token-subset analysis.

    Returns one of: STRONG, ACCEPTABLE, WEAK.
      STRONG    — every label token appears in name AND label has ≥2
                  non-stop tokens (label is genuinely contained in
                  the name; the ≥2 floor blocks single-word labels
                  like "yeast" / "cow" / "tomato" that match overly
                  generically)
      ACCEPTABLE — every name token appears in label AND name has ≥2
                  non-stop tokens (name is contained in label)
      WEAK      — neither subset holds; only partial overlap
    """
    name_tok = _tokens(name)
    label_tok = _tokens(label)
    if not name_tok or not label_tok:
        return "WEAK"
    if label_tok.issubset(name_tok) and len(label_tok) >= 2:
        return "STRONG"
    if name_tok.issubset(label_tok) and len(name_tok) >= 2:
        return "ACCEPTABLE"
    return "WEAK"


def ols_search(term: str, ontology: str, expected_prefix: str) -> dict:
    """Generic OLS search returning the best hit for one ontology.
    expected_prefix is the CURIE prefix to filter on (CHEBI:, FOODON:,
    NCIT:, etc.). Returns {*_id: ..., label: ..., match: ...} or {}."""
    params = urllib.parse.urlencode({
        "q": term, "ontology": ontology, "rows": 8,
        "exact": "false", "type": "class",
    })
    try:
        with urllib.request.urlopen(f"{OLS_SEARCH}?{params}", timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}
    n = _norm(term)
    docs = j.get("response", {}).get("docs", [])
    fuzzy_top = None
    for d in docs:
        if d.get("is_obsolete"):
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie or not curie.upper().startswith(expected_prefix.upper()):
            continue
        label = d.get("label", "")
        if _norm(label) == n:
            return {"id": curie, "label": label, "match": "label-exact",
                    "ontology": ontology}
        if n in {_norm(s) for s in (d.get("synonym") or [])}:
            return {"id": curie, "label": label, "match": "synonym-exact",
                    "ontology": ontology}
        if fuzzy_top is None:
            fuzzy_top = {"id": curie, "label": label, "match": "fuzzy-top",
                         "ontology": ontology}
    return fuzzy_top or {}


def ols_foodon_search(term: str) -> dict:
    """Backward-compat shim — returns the legacy `foodon_id` key."""
    r = ols_search(term, "foodon", "FOODON:")
    if r and "id" in r:
        r["foodon_id"] = r["id"]
    return r


# Cascade order for NO_HIT / WEAK fallback.
#   ENVO  — environmental samples (manure, soil, seawater, sediment)
#   CHEBI — single chemicals; some food reagents (gelatin etc.) live here
#   NCIT  — pharmaceuticals and clinical reagents (catches "Beef" and similar)
#   MICRO — microbiology-domain ontology (covers peptone, tryptone, etc.)
#   mesh  — broad-domain medical/biological terms (catches branded
#           variants like Bacto-peptone, Proteose-peptone)
_FALLBACK_ONTOLOGIES = (
    ("envo", "ENVO:"),
    ("chebi", "CHEBI:"),
    ("ncit", "NCIT:"),
    ("micro", "MICRO:"),
    ("mesh", "mesh:"),
)


def build_mim_name_index() -> dict[str, list[tuple[int, Path]]]:
    """Build a normalized-name → [(score, path), ...] index over all
    MIM ingredient YAMLs. Done once up front to avoid the 99 ×
    2,349-file walk that dominated the dry-run."""
    idx: dict[str, list[tuple[int, Path]]] = {}
    for path in (MIM_ROOT / "data" / "ingredients").rglob("*.yaml"):
        try:
            with open(path) as f:
                y = yaml.safe_load(f) or {}
        except Exception:
            continue
        pt = _norm(y.get("preferred_term") or "")
        if not pt:
            continue
        ident = y.get("identifier") or ""
        score = 0
        if ident.startswith("UNMAPPED_"):
            score = 3
        elif ident.startswith("kgmicrobe.compound:"):
            score = 2
        elif ident.startswith("FOODON:"):
            score = -1
        idx.setdefault(pt, []).append((score, path))
    return idx


def find_mim_yaml_by_name(name: str,
                          idx: dict[str, list[tuple[int, Path]]]
                          ) -> Path | None:
    norm = _norm(name)
    cands = idx.get(norm) or []
    if not cands:
        return None
    cands_sorted = sorted(cands, key=lambda x: -x[0])
    return cands_sorted[0][1] if cands_sorted[0][0] > 0 else None


def upgrade_yaml(path: Path, ontology_id: str, ontology_label: str,
                 match_type: str) -> str:
    """Upgrade an existing MIM YAML's primary to a FOODON / CHEBI /
    NCIT term. The ontology is inferred from the CURIE prefix."""
    record = load_yaml(path)
    if not record:
        return "no-change"
    prev_ident = record.get("identifier")
    if prev_ident == ontology_id:
        return "no-change"
    prefix = ontology_id.split(":", 1)[0].upper() if ":" in ontology_id else ""
    record["identifier"] = ontology_id
    om = record.setdefault("ontology_mapping", {})
    om["ontology_id"] = ontology_id
    om["ontology_label"] = ontology_label
    om["ontology_source"] = prefix or "OTHER"
    om["mapping_quality"] = (
        "EXACT_MATCH" if match_type.startswith(("label-exact", "synonym-exact"))
        else "LEXICAL_MATCH")
    om.setdefault("evidence", []).append({
        "evidence_type": "DATABASE_MATCH",
        "source": f"{prefix} via OLS search",
        "notes": f"Auto-upgraded from {prev_ident!r}; match={match_type}",
    })
    record["mapping_status"] = "MAPPED"
    append_curation_event(
        record, f"AUTO_UPGRADE_TO_{prefix or 'ONTOLOGY'}",
        f"primary {prev_ident} → {ontology_id} ({match_type})")
    _staged_write(path, record)
    return "upgraded"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--high-only", action="store_true",
                    help="skip MEDIUM (fuzzy-top) matches")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    global _TRANSACTION
    _TRANSACTION = ValidatedWriteTransaction(
        MIM_ROOT,
        journal_dir=OUT_DIR / "write_journal",
    )

    if not INVENTORY_TSV.is_file():
        print("Run `just inventory-unmapped` first.", file=sys.stderr)
        return 2

    # Distinct heuristic-complex names from the inventory
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []  # (norm_key, display_name)
    with open(INVENTORY_TSV) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            name = r["name"]
            if not _COMPLEX_RE.search(name):
                continue
            n = r["norm_key"]
            if n in seen:
                continue
            seen.add(n)
            targets.append((n, name))
    if args.limit:
        targets = targets[: args.limit]
    print(f"Heuristic-complex distinct names: {len(targets)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Building MIM name index...")
    name_idx = build_mim_name_index()
    print(f"  indexed {sum(len(v) for v in name_idx.values())} records")

    rows: list[tuple[str, str, str, str, str, str]] = []
    counts: dict[str, int] = {}

    for i, (norm, name) in enumerate(targets, 1):
        # Try FOODON first
        result = ols_search(name, "foodon", "FOODON:")
        time.sleep(RATE_DELAY)

        # Compute confidence based on match type + (for fuzzy-top) token-subset
        if result and not result.get("error"):
            match = result["match"]
            if match in ("label-exact", "synonym-exact"):
                confidence = "HIGH"
            else:
                # Fuzzy-top — re-score by token overlap
                fuzz = score_fuzzy_match(name, result["label"])
                if fuzz == "STRONG":
                    confidence = "STRONG_MEDIUM"
                elif fuzz == "ACCEPTABLE":
                    confidence = "MEDIUM"
                else:
                    confidence = "WEAK_MEDIUM"
        else:
            confidence = "NO_HIT_FOODON"
            match = ""

        # Cascade to CHEBI/NCIT on FOODON miss or weak match
        cascade_used = ""
        if confidence in ("NO_HIT_FOODON", "WEAK_MEDIUM"):
            for fb_onto, fb_prefix in _FALLBACK_ONTOLOGIES:
                fb = ols_search(name, fb_onto, fb_prefix)
                time.sleep(RATE_DELAY)
                if fb and not fb.get("error"):
                    fb_match = fb["match"]
                    if fb_match in ("label-exact", "synonym-exact"):
                        result = fb
                        match = fb_match
                        confidence = "HIGH"
                        cascade_used = fb_onto
                        break
            else:
                if confidence == "NO_HIT_FOODON":
                    confidence = "NO_HIT"

        counts[confidence] = counts.get(confidence, 0) + 1

        # No usable result?
        if confidence == "NO_HIT":
            rows.append((name, "", "", confidence, "", ""))
            print(f"  [{i}/{len(targets)}] {name}: NO_HIT")
            continue

        target_id = result.get("id") or result.get("foodon_id", "")
        target_label = result.get("label", "")
        eligible_for_apply = confidence in ("HIGH", "STRONG_MEDIUM")

        target_yaml = find_mim_yaml_by_name(name, name_idx)
        if target_yaml is None:
            action = "CREATE_NEW (deferred)"
        elif args.apply and eligible_for_apply and not (
                args.high_only and confidence != "HIGH"):
            res = upgrade_yaml(target_yaml, target_id, target_label, match)
            action = "UPGRADED" if res == "upgraded" else "NO_CHANGE"
            if res == "upgraded":
                counts["UPGRADED"] = counts.get("UPGRADED", 0) + 1
        elif eligible_for_apply:
            action = "WOULD_UPGRADE"
        else:
            action = "WOULD_REVIEW"

        # Annotate the report row with cascade info if applicable
        match_label = (f"{match} ({cascade_used})" if cascade_used
                       else match)
        rows.append((name, target_id, target_label,
                     confidence, match_label,
                     (str(target_yaml.relative_to(MIM_ROOT))
                      if target_yaml else "(no MIM record)")
                     + " | " + action))
        cascade_tag = f" via {cascade_used}" if cascade_used else ""
        print(f"  [{i}/{len(targets)}] {name}: "
              f"{confidence} → {target_id}{cascade_tag} ({match})")

    # Reports
    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["name", "foodon_id", "foodon_label",
                    "confidence", "match_type", "target_yaml | action"])
        w.writerows(rows)

    md = ["# FOODON pass — heuristic-complex resolver\n",
          f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**\n",
          f"Distinct names processed: **{len(targets)}**\n",
          "\n## Verdicts\n",
          "| verdict | count |", "|---|---:|"]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        md.append(f"| `{k}` | {v} |")

    md.append("\n\n## HIGH-confidence (label/synonym exact)\n")
    md.append("| Name | Target | Label | Match | Action |")
    md.append("|---|---|---|---|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf == "HIGH":
            md.append(f"| {name} | `{fid}` | {flabel} | {match} | {action} |")

    md.append("\n\n## STRONG_MEDIUM (label tokens ⊆ name)\n")
    md.append("| Name | Target | Label | Action |")
    md.append("|---|---|---|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf == "STRONG_MEDIUM":
            md.append(f"| {name} | `{fid}` | {flabel} | {action} |")

    md.append("\n\n## MEDIUM (name tokens ⊆ label) — curator review\n")
    md.append("| Name | Target | Label | Action |")
    md.append("|---|---|---|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf == "MEDIUM":
            md.append(f"| {name} | `{fid}` | {flabel} | {action} |")

    md.append("\n\n## WEAK_MEDIUM (only partial token overlap) — likely wrong\n")
    md.append("| Name | Target | Label |")
    md.append("|---|---|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf == "WEAK_MEDIUM":
            md.append(f"| {name} | `{fid}` | {flabel} |")

    md.append("\n\n## No hit (FOODON / CHEBI / NCIT all missed)\n")
    md.append("| Name |")
    md.append("|---|")
    for name, fid, flabel, conf, match, action in rows:
        if conf == "NO_HIT":
            md.append(f"| {name} |")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print()
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:25s} {v}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"         {OUT_MD.relative_to(REPO_ROOT)}")
    _result = _TRANSACTION.commit(apply=args.apply)
    if args.apply and _result.touched:
        print(f"Wrote {_result.touched} record(s); journal: {_result.journal_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
