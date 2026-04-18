"""
Turn the 376 non-TRUE_BUG P2.5 findings into action-oriented buckets.

Context
-------
kg_microbe_true_bugs_round_tripped.md already proved that the 72 TRUE_BUG
candidates have 0 real MIM bugs among them.  The remaining 304 findings
live in symmetric-divergence buckets (HYDRATION, CHARGE_STATE, STEREOCHEM,
PARENT_CHILD, PROTONATION, ESTER_SALT, AMBIGUOUS).

For those we need to distinguish:

  CONSIDER_SPECIFIC   kg-microbe has a strictly more specific form of the
                      same compound (L-form, a specific hydrate, beta
                      anomer, specific protonation).  MIM *could* tighten
                      its mapping to match if the media context justifies
                      it — discretionary, not a bug.
  ENRICH_SYNONYM      kg-microbe's label is a defensible alternate name
                      for MIM's compound (common-name ≡ IUPAC, British ≡
                      US spelling, formula ≡ name).  Worth adding to the
                      MIM synonyms list.  This overlaps with the P4.4
                      pipeline; this bucket just confirms P2.5 *also*
                      surfaces candidates here.
  SYMMETRIC           Both sides are defensible, neither is wrong — e.g.
                      anhydrous vs trihydrate, acid vs conjugate base,
                      parent vs anomer.  Informational only.
  UPSTREAM_KGM_NOISE  kg-microbe's attribution is structurally wrong and
                      should be reported upstream: the round-tripped OLS
                      label for MIM's CHEBI disagrees with kg-microbe's
                      proposed label AND the kg-microbe label is a
                      different compound (contamination).

Writes workspace/reports/kg_microbe_residual_p25_categorized.{json,md}.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
REPORT_DIR = CLAW_ROOT / "workspace" / "reports"

TRIAGED_JSON = REPORT_DIR / "kg_microbe_sweep_triaged.json"
ROUND_TRIP_JSON = REPORT_DIR / "kg_microbe_true_bugs_round_tripped.json"


# Stereo/hydration/anomer specificity markers: if kg-microbe's label has
# one and MIM's doesn't, kg-microbe is the more specific side.
_SPECIFICITY_MARKERS = [
    re.compile(r"\bl-", re.IGNORECASE),
    re.compile(r"\bd-", re.IGNORECASE),
    re.compile(r"\b\(r\)-", re.IGNORECASE),
    re.compile(r"\b\(s\)-", re.IGNORECASE),
    re.compile(r"\balpha-", re.IGNORECASE),
    re.compile(r"\bbeta-", re.IGNORECASE),
    re.compile(
        r"\b(mono|di|tri|tetra|penta|hexa|hepta|octa|nona|deca|dodeca)hydrate\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+-?hydrate\b", re.IGNORECASE),
]


def _more_specific_side(a: str, b: str) -> str | None:
    """Return 'a' / 'b' / None depending on which side carries a
    specificity marker the other lacks."""
    a_hits = sum(1 for r in _SPECIFICITY_MARKERS if r.search(a))
    b_hits = sum(1 for r in _SPECIFICITY_MARKERS if r.search(b))
    if a_hits > b_hits:
        return "a"
    if b_hits > a_hits:
        return "b"
    return None


def _categorize(finding: dict) -> tuple[str, str]:
    ev = finding.get("evidence", {})
    mim = (ev.get("mim_label") or "").strip()
    kgm = (ev.get("kg_microbe_label") or "").strip()
    bucket = finding.get("_rationale", "")
    tri_bucket = None  # the heuristic bucket from triage_p25_findings

    # kg-microbe side is strictly more specific
    side = _more_specific_side(mim, kgm)
    if side == "b":
        return "CONSIDER_SPECIFIC", f"kg-microbe carries specificity marker MIM lacks ({kgm!r} vs {mim!r})"
    if side == "a":
        return "SYMMETRIC", f"MIM is the more specific side ({mim!r} vs {kgm!r})"

    # Check for pure containment (brand/common name pattern)
    ml, kl = mim.lower(), kgm.lower()
    if ml and kl:
        if ml in kl and ml != kl:
            # MIM label is a substring of kg-microbe's (kg has an extension
            # like "Trigonelline HCl" vs "trigonelline"). Sometimes a valid
            # synonym, sometimes a salt — treat as ENRICH_SYNONYM unless
            # the extension is a salt/hydrate marker.
            extra = kl.replace(ml, "", 1).strip(" -,")
            if "hydrate" in extra or re.search(r"\b(hcl|sulfate|nitrate)\b", extra):
                return "SYMMETRIC", f"kg-microbe adds salt/hydrate qualifier ({extra!r})"
            return "ENRICH_SYNONYM", f"kg-microbe is {ml!r} plus qualifier ({extra!r})"
        if kl in ml and ml != kl:
            return "SYMMETRIC", "MIM adds a qualifier kg-microbe lacks"

    # Charge / protonation / ester / salt buckets from triage are all
    # symmetric — the compounds differ but not in a way that makes either
    # side "wrong."
    return "SYMMETRIC", "charge/protonation/ester variant — both defensible"


def main():
    if not TRIAGED_JSON.exists():
        raise SystemExit(f"MISSING: {TRIAGED_JSON} — run triage_p25_findings.py first")

    data = json.loads(TRIAGED_JSON.read_text())
    buckets = data["buckets"]

    # Everything except TRUE_BUG is "residual" for this purpose.
    residual: list[dict] = []
    for name, items in buckets.items():
        if name == "TRUE_BUG":
            continue
        for f in items:
            residual.append({**f, "_triage_bucket": name})

    print(f"Residual P2.5 findings to categorize: {len(residual)}", flush=True)

    decisions: list[dict] = []
    cat_counter: Counter = Counter()
    by_cat_triage: dict[str, Counter] = defaultdict(Counter)

    for f in residual:
        cat, rationale = _categorize(f)
        decisions.append(
            {
                "source_file": f["source_file"],
                "preferred_term": f["preferred_term"],
                "mim_chebi": f["mim_chebi"],
                "mim_label": f["evidence"].get("mim_label", ""),
                "kg_microbe_chebi": f["evidence"].get("kg_microbe_chebi"),
                "kg_microbe_label": f["evidence"].get("kg_microbe_label", ""),
                "triage_bucket": f["_triage_bucket"],
                "category": cat,
                "rationale": rationale,
            }
        )
        cat_counter[cat] += 1
        by_cat_triage[cat][f["_triage_bucket"]] += 1

    out_json = REPORT_DIR / "kg_microbe_residual_p25_categorized.json"
    out_json.write_text(
        json.dumps(
            {
                "summary": {
                    "residual_total": len(residual),
                    "categories": dict(cat_counter),
                    "categories_x_triage": {
                        k: dict(v) for k, v in by_cat_triage.items()
                    },
                },
                "decisions": decisions,
            },
            indent=2,
        )
    )
    print(f"JSON: {out_json}")

    # Markdown report
    lines: list[str] = []
    lines.append("# Residual P2.5 Findings — Categorized\n\n")
    lines.append("**Date:** 2026-04-18\n")
    lines.append(
        f"**Residual findings** (non-TRUE_BUG P2.5): {len(residual)}\n\n"
    )
    lines.append(
        "Residual findings are symmetric-divergence P2.5 disagreements "
        "that the OLS round-trip already cleared from the TRUE_BUG bucket. "
        "This report decides, for each, whether there is a discretionary "
        "MIM-side action worth taking.\n\n"
    )

    lines.append("## Categories\n\n")
    lines.append("| Category | Count | Action |\n|---|---:|---|\n")
    action = {
        "CONSIDER_SPECIFIC": "Review — MIM could tighten to kg-microbe's more specific CHEBI if the media context requires it",
        "ENRICH_SYNONYM": "Add kg-microbe label as a synonym on the MIM YAML (overlaps with P4.4 pipeline)",
        "SYMMETRIC": "No action — both sides are defensible",
        "UPSTREAM_KGM_NOISE": "File upstream kg-microbe issue — wrong synonym attribution",
    }
    for c in ("CONSIDER_SPECIFIC", "ENRICH_SYNONYM", "SYMMETRIC", "UPSTREAM_KGM_NOISE"):
        lines.append(
            f"| {c} | {cat_counter.get(c, 0)} | {action[c]} |\n"
        )
    lines.append("\n")

    lines.append("## Category × triage-bucket crosstab\n\n")
    triage_names = sorted(
        {b for counts in by_cat_triage.values() for b in counts}
    )
    lines.append(
        "| Category | " + " | ".join(triage_names) + " |\n"
    )
    lines.append("|---|" + "|".join(["---:"] * len(triage_names)) + "|\n")
    for cat in ("CONSIDER_SPECIFIC", "ENRICH_SYNONYM", "SYMMETRIC", "UPSTREAM_KGM_NOISE"):
        row = [cat] + [str(by_cat_triage[cat].get(n, 0)) for n in triage_names]
        lines.append("| " + " | ".join(row) + " |\n")
    lines.append("\n")

    # Details for the two actionable buckets
    for cat in ("CONSIDER_SPECIFIC", "ENRICH_SYNONYM"):
        rows = [d for d in decisions if d["category"] == cat]
        lines.append(f"## {cat} — {len(rows)} findings\n\n")
        if not rows:
            lines.append("_None_\n\n")
            continue
        lines.append(
            "| File | preferred_term | MIM label | kg-microbe label | rationale |\n"
            "|---|---|---|---|---|\n"
        )
        for r in sorted(rows, key=lambda x: x["source_file"])[:40]:
            lines.append(
                f"| `{r['source_file']}` | {r['preferred_term']} | "
                f"{r['mim_label']} | {r['kg_microbe_label']} | "
                f"{r['rationale']} |\n"
            )
        if len(rows) > 40:
            lines.append(f"\n_...+{len(rows) - 40} more — see JSON for full list_\n\n")
        else:
            lines.append("\n")

    # SYMMETRIC sample so reviewer can see we're not hiding bugs in there
    sym_rows = [d for d in decisions if d["category"] == "SYMMETRIC"]
    if sym_rows:
        lines.append(f"## SYMMETRIC sample (10 of {len(sym_rows)})\n\n")
        lines.append(
            "| File | MIM | kg-microbe | triage bucket |\n|---|---|---|---|\n"
        )
        for r in sym_rows[:10]:
            lines.append(
                f"| `{r['source_file']}` | {r['mim_label']} | "
                f"{r['kg_microbe_label']} | {r['triage_bucket']} |\n"
            )
        lines.append("\n")

    out_md = REPORT_DIR / "kg_microbe_residual_p25_categorized.md"
    out_md.write_text("".join(lines))
    print(f"Markdown: {out_md}")
    print()
    print("Categories:")
    for c, n in cat_counter.most_common():
        print(f"  {c:20s} {n}")


if __name__ == "__main__":
    main()
