"""
Classify P2.5 disagreement findings into semantic buckets so reviewers can
focus on real bugs instead of protonation-state noise.

Buckets
-------
TRUE_BUG        MIM and kg-microbe labels point at unrelated compounds
                (no shared chemical stem / token overlap). These are the
                only findings that warrant immediate curation.
PROTONATION     Same compound, different protonation state (acid vs
                conjugate base). Detected by {X-ate, X-ic acid, X(1-), ...}.
CHARGE_STATE    Same compound, explicit charge notation (e.g., X(1-), X(+)).
STEREOCHEM      Same compound, different stereochemistry (L-/D-/(R)-/(S)-/rac).
HYDRATION       Hydrate/anhydrous pair (contains hydrate / N-hydrate / anhydrous).
PARENT_CHILD    One label is an obvious parent of the other (string subset
                after normalization — e.g. "lactose" vs "beta-lactose").
ESTER_SALT      Salt/ester/acetal/amide/anion variants.
AMBIGUOUS       Residual — needs manual eyeballing.

Not a strict taxonomy — heuristic triage. The output puts every TRUE_BUG at
the top so the reviewer can start there.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
REPORT_DIR = WORKSPACE / "reports"

# Fixes applied in this session — exclude from the remaining-work view
ALREADY_FIXED_FILES = {
    "4-hydroxyphenyl_Acetic_Acid.yaml",
    "3-indolyl_Acetic_Acid.yaml",
    "Phenyl_Acetic_Acid.yaml",
    "Co_Carboxylase.yaml",
    "Dl-malate.yaml",
    "Dl-mevalonic_Acid.yaml",
    "Na2s2o3.yaml",
    "Nano3.yaml",
    "Kno3.yaml",
    "Ferric_Citrate_Monohydrate.yaml",
    "Cysteine-hcl.yaml",
    "Na2seo4.yaml",
    "Tapso.yaml",
    "Cysteine-hcl_X_H2o.yaml",
    "L-cysteine-hcl_X_H2o.yaml",
    "L-cysteine-hcl_X_H2o_2.yaml",
}


def _normalize_label(label: str) -> str:
    """Lowercase, drop whitespace and separators, drop greek/number prefixes
    we consider cosmetic for parent/child matching."""
    s = label.lower()
    s = re.sub(r"\b(alpha|beta|gamma|delta)\b", "", s)
    s = re.sub(r"\(\d*[rsrs]\)-?", "", s)  # (R)- / (S)- / (R,S)-
    s = re.sub(r"\b[dl]-", "", s)  # D-/L- / DL-
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[()\[\],+\-·]", "", s)
    return s


def _stem_tokens(label: str) -> set[str]:
    """Content tokens — used to tell "unrelated compound" from "variant."""
    # strip charge/state suffixes so biotinate ≈ biotin
    s = label.lower()
    s = re.sub(r"\([0-9]+[+\-]\)", " ", s)
    s = re.sub(r"[()\[\],]", " ", s)
    tokens = re.split(r"[\s\-/·]+", s)
    drop = {
        "",
        "acid",
        "ester",
        "salt",
        "ion",
        "ate",
        "ide",
        "anion",
        "cation",
        "hydrate",
        "anhydrous",
        "monohydrate",
        "dihydrate",
        "trihydrate",
        "tetrahydrate",
        "pentahydrate",
        "hexahydrate",
        "heptahydrate",
        "sodium",
        "potassium",
        "calcium",
        "magnesium",
        "ammonium",
        "free",
        "n",
        "alpha",
        "beta",
        "gamma",
        "l",
        "d",
        "dl",
        "r",
        "s",
        "the",
        "of",
        "and",
    }
    stems = set()
    for t in tokens:
        t = re.sub(r"^[dl]-?", "", t)
        t = re.sub(r"(ate|ic|ous|ium)$", "", t)
        if len(t) >= 4 and t not in drop:
            stems.add(t)
    return stems


def classify(mim_label: str, kgm_label: str) -> tuple[str, str]:
    """Return (bucket, rationale)."""
    if not mim_label or not kgm_label:
        return "AMBIGUOUS", "missing-label"

    m = mim_label.lower()
    k = kgm_label.lower()

    if m == k:
        return "AMBIGUOUS", "identical-labels"

    # Hydration pair
    hydr_pat = re.compile(
        r"\b(hydrate|anhydrous|monohydrate|dihydrate|trihydrate|tetrahydrate|pentahydrate|hexahydrate|heptahydrate|[0-9]+-?hydrate)\b"
    )
    if hydr_pat.search(m) != hydr_pat.search(k):
        return "HYDRATION", "hydrate-vs-anhydrous"

    # Explicit charge
    if re.search(r"\([0-9]*[+\-]\)", m) != re.search(r"\([0-9]*[+\-]\)", k):
        return "CHARGE_STATE", "charge-annotation-differs"

    # Stereochemistry
    stereo_pat = re.compile(r"\b(l|d|dl|\(r\)|\(s\))-")
    if bool(stereo_pat.search(m)) != bool(stereo_pat.search(k)):
        return "STEREOCHEM", "stereochemistry-prefix-differs"

    # Acid vs conjugate base / salt / ester
    acid_pat = re.compile(r"ic\s+acid\b")
    ate_pat = re.compile(r"\bate\b|ate$")
    if bool(acid_pat.search(m)) != bool(acid_pat.search(k)) and (
        ate_pat.search(m) or ate_pat.search(k)
    ):
        return "PROTONATION", "acid-vs-ate"

    if any(w in k for w in ("ester", "acetal", "anhydride")) and "ester" not in m:
        return "ESTER_SALT", "kgm-proposes-ester-or-anhydride"

    # Parent/child by normalized containment
    mn, kn = _normalize_label(m), _normalize_label(k)
    if mn and kn and (mn in kn or kn in mn) and mn != kn:
        return "PARENT_CHILD", "label-containment"

    # Stem overlap test — if they share a substantial content token,
    # probably the same compound family.
    sm, sk = _stem_tokens(m), _stem_tokens(k)
    shared = sm & sk
    if shared:
        return "AMBIGUOUS", f"shared-stems={sorted(shared)[:3]}"

    # No shared stems → unrelated compounds
    return "TRUE_BUG", "no-shared-content-tokens"


def main():
    src = REPORT_DIR / "kg_microbe_sweep.json"
    data = json.loads(src.read_text())
    p25 = data["p25_findings"]

    buckets = defaultdict(list)
    for f in p25:
        if f["source_file"] in ALREADY_FIXED_FILES:
            continue
        ev = f.get("evidence", {})
        b, rationale = classify(ev.get("mim_label", ""), ev.get("kg_microbe_label", ""))
        buckets[b].append({**f, "_rationale": rationale})

    counts = Counter({b: len(v) for b, v in buckets.items()})

    out_json = REPORT_DIR / "kg_microbe_sweep_triaged.json"
    out_json.write_text(
        json.dumps(
            {
                "already_fixed": sorted(ALREADY_FIXED_FILES),
                "bucket_counts": dict(counts),
                "buckets": buckets,
            },
            indent=2,
            default=list,
        )
    )
    print(f"JSON: {out_json}")

    out_md = REPORT_DIR / "kg_microbe_sweep_triaged.md"
    lines = []
    lines.append("# P2.5 Findings — Triaged\n")
    lines.append(f"**Date:** 2026-04-18\n")
    lines.append(f"**Already-fixed YAMLs excluded:** {len(ALREADY_FIXED_FILES)}\n\n")
    lines.append("## Bucket summary\n\n")
    lines.append("| Bucket | Count | Action |\n|---|---:|---|\n")
    action = {
        "TRUE_BUG": "**Fix now**",
        "HYDRATION": "Review (may be fine — hydrate distinguished by separate YAML)",
        "CHARGE_STATE": "Informational",
        "PROTONATION": "Informational",
        "STEREOCHEM": "Review (L-/D- distinctions matter biologically)",
        "ESTER_SALT": "Review",
        "PARENT_CHILD": "Review (child may be more specific)",
        "AMBIGUOUS": "Manual review",
    }
    for b in sorted(counts, key=lambda x: -counts[x]):
        lines.append(f"| {b} | {counts[b]} | {action.get(b, '')} |\n")
    lines.append("\n")

    lines.append("## TRUE_BUG (immediate fix candidates)\n\n")
    true_bugs = buckets.get("TRUE_BUG", [])
    if not true_bugs:
        lines.append("_None remaining_\n\n")
    else:
        lines.append("| File | MIM CHEBI (label) | kg-microbe proposes |\n|---|---|---|\n")
        for f in sorted(true_bugs, key=lambda x: x["source_file"]):
            ev = f["evidence"]
            lines.append(
                f"| `{f['source_file']}` | `{ev.get('mim_chebi')}` "
                f"({ev.get('mim_label')}) | `{ev.get('kg_microbe_chebi')}` "
                f"({ev.get('kg_microbe_label')}) |\n"
            )
        lines.append("\n")

    # One example from each informational bucket so the reviewer can spot-check
    for b in ("HYDRATION", "CHARGE_STATE", "PROTONATION", "STEREOCHEM", "ESTER_SALT",
              "PARENT_CHILD", "AMBIGUOUS"):
        items = buckets.get(b, [])
        if not items:
            continue
        lines.append(f"## {b} (sample 5 of {len(items)})\n\n")
        lines.append("| File | MIM | kg-microbe |\n|---|---|---|\n")
        for f in items[:5]:
            ev = f["evidence"]
            lines.append(
                f"| `{f['source_file']}` | `{ev.get('mim_chebi')}` "
                f"({ev.get('mim_label')}) | `{ev.get('kg_microbe_chebi')}` "
                f"({ev.get('kg_microbe_label')}) |\n"
            )
        lines.append("\n")

    out_md.write_text("".join(lines))
    print(f"Markdown: {out_md}")
    print()
    print("Bucket counts:")
    for b, c in counts.most_common():
        print(f"  {b:15s} {c}")


if __name__ == "__main__":
    main()
