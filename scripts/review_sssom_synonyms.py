"""
Review an SSSOM TSV's synonym assertions against independent ontology
authorities:

  1. OAK (runoak) against a local CHEBI sqlite — exact + related synonym
     predicates with OBO semantics. CHEBI only.
  2. EBI OLS4 REST API — the community-facing synonym set the target
     ontology publishes. Dispatches per-ontology (chebi, foodon, ...).

For each row we check:
  * object_label matches the authority's rdfs:label or an exact synonym.
  * every `other` label (the MIM/kg-microbe alternate surface form) is
    either already a synonym OR a defensible new candidate.
  * the `subject_label` itself, which is the MIM preferred term — if it's
    also unknown to the authority we flag it as a synonym-enrichment
    opportunity.

Output:

  workspace/reports/sssom_synonym_review.tsv   (per-row verdict)
  workspace/reports/sssom_synonym_review.md    (human summary)

Verdicts
--------
CONFIRMED         object_label and every alternate label are known to
                  OAK or OLS (mapping is well-grounded)
SYNONYM_ENRICH    at least one alternate label is NOT in either source —
                  candidate to propose upstream as a new synonym
OLS_MISMATCH      OAK and OLS disagree on the label set (CHEBI only;
                  possible stale local sqlite or out-of-sync release)
LABEL_MISMATCH    our object_label isn't the authority's rdfs:label and
                  isn't listed as an exact synonym — likely a data bug
UNKNOWN_TERM      neither OAK nor OLS resolves the term — the ID is
                  deprecated/obsolete or wrong

The script caches OLS responses in workspace/.cache/ols/{TERM}.json to
keep reruns polite; delete that directory to force a re-fetch.

Defaults to processing all rows. Pass `--limit N` to spot-check.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CLAW_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw"
)
DEFAULT_SSSOM = CLAW_ROOT / "workspace" / "reports" / "mim_ingredient_mappings.sssom.tsv"
DEFAULT_TSV_OUT = CLAW_ROOT / "workspace" / "reports" / "sssom_synonym_review.tsv"
DEFAULT_MD_OUT = CLAW_ROOT / "workspace" / "reports" / "sssom_synonym_review.md"
OLS_CACHE = CLAW_ROOT / "workspace" / ".cache" / "ols"
OAK_CACHE = CLAW_ROOT / "workspace" / ".cache" / "oak"

RUNOAK = "runoak"
OAK_INPUT = "sqlite:obo:chebi"
SSSOM_BIN = "sssom"

# Per-prefix OLS4 dispatch. Adding a prefix here makes the reviewer
# resolve it via OLS4. OAK is CHEBI-only (no local sqlite for the others).
_OLS_ONTOLOGY_BY_PREFIX: dict[str, str] = {
    "CHEBI:": "chebi",
    "FOODON:": "foodon",
    "UBERON:": "uberon",
    "ENVO:": "envo",
}
_IRI_BASE_BY_PREFIX: dict[str, str] = {
    "CHEBI:": "http://purl.obolibrary.org/obo/CHEBI_",
    "FOODON:": "http://purl.obolibrary.org/obo/FOODON_",
    "UBERON:": "http://purl.obolibrary.org/obo/UBERON_",
    "ENVO:": "http://purl.obolibrary.org/obo/ENVO_",
}


def _prefix_for(curie: str) -> str | None:
    for p in _OLS_ONTOLOGY_BY_PREFIX:
        if curie.startswith(p):
            return p
    return None
# Hard-error substrings from `sssom validate` stderr — "No attr for ..." and
# plain "WARNING:" lines are informational and do NOT block review.
_VALIDATE_ERROR_MARKERS = (
    "is not well-formed",
    "is not a valid URI or CURIE",
    "must be supplied",
)


def sssom_validate(path: Path) -> list[str]:
    """Run `sssom validate` as a preflight gate. Returns the list of
    hard-error messages (empty list = clean). JsonSchema +
    PrefixMapCompleteness + StrictCurieFormat cover the structural
    checks we care about; Shacl is skipped because sssom-py 0.4.17 has
    a known crash there."""
    try:
        proc = subprocess.run(
            [
                SSSOM_BIN, "validate",
                "-V", "JsonSchema",
                "-V", "PrefixMapCompleteness",
                "-V", "StrictCurieFormat",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return [f"sssom CLI not found on PATH (looked for '{SSSOM_BIN}')"]
    except subprocess.TimeoutExpired:
        return ["sssom validate timed out after 120s"]

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    errs = [
        ln.strip()
        for ln in combined.splitlines()
        if any(m in ln for m in _VALIDATE_ERROR_MARKERS)
    ]
    return errs


# Hydrate separator normalization — unifies the many surface forms of a
# formula → hydrate-counter link so '(MnCl2 x 4 H2O)' == '(MnCl2.4H2O)'
# == '(MnCl2·4H2O)' == '(MnCl2・4H2O)'. Operates on *already-lowercased*
# text; the \d* group captures an optional hydrate count and is
# preserved in the replacement.
_HYDRATE_SEP_RE = re.compile(
    r"\s*(?:[·・⋅∙*]|x|×|\.)\s*(\d*)\s*h\s*2\s*o",
    re.IGNORECASE,
)


def _canon_hydrate(s: str) -> str:
    return _HYDRATE_SEP_RE.sub(lambda m: f"·{m.group(1) or ''}h2o", s)


def _norm(s: str) -> str:
    """Normalizer used for set-containment: case-insensitive, collapse
    whitespace, strip trailing punctuation, canonicalize hydrate
    notation ('x 4 H2O' → '·4h2o'). CHEBI stores the dotted form; MIM
    tends to store ' x N H2O' — without this canonicalization every MIM
    hydrate label looks like a LABEL_MISMATCH even when the CHEBI side
    has the same compound as a synonym."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[.,;]+$", "", s)
    s = _canon_hydrate(s)
    return s


# ---------------------------------------------------------------------------
# OAK — batched so we don't pay cold-start overhead per term
# ---------------------------------------------------------------------------

def oak_aliases_batch(chebi_ids: list[str]) -> dict[str, dict[str, set[str]]]:
    """Return {chebi: {label: set, exact: set, related: set}} via one OAK call."""
    if not chebi_ids:
        return {}
    OAK_CACHE.mkdir(parents=True, exist_ok=True)
    cache_key = OAK_CACHE / f"aliases_{abs(hash(tuple(sorted(chebi_ids)))):x}.tsv"
    if cache_key.exists():
        text = cache_key.read_text()
    else:
        proc = subprocess.run(
            [RUNOAK, "-i", OAK_INPUT, "aliases"] + chebi_ids,
            capture_output=True,
            text=True,
            timeout=300,
        )
        text = proc.stdout
        cache_key.write_text(text)

    out: dict[str, dict[str, set[str]]] = {
        c: {"label": set(), "exact": set(), "related": set()} for c in chebi_ids
    }
    for line in text.splitlines()[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        curie, pred, alias = parts[0], parts[1], parts[2]
        if curie not in out:
            continue
        if pred == "rdfs:label":
            out[curie]["label"].add(alias)
        elif pred == "oio:hasExactSynonym":
            out[curie]["exact"].add(alias)
        elif pred == "oio:hasRelatedSynonym":
            out[curie]["related"].add(alias)
    return out


# ---------------------------------------------------------------------------
# EBI OLS4 — per-term, cached, single retry
# ---------------------------------------------------------------------------

def ols_fetch(curie: str) -> dict | None:
    prefix = _prefix_for(curie)
    if prefix is None:
        return None
    ontology = _OLS_ONTOLOGY_BY_PREFIX[prefix]
    iri_base = _IRI_BASE_BY_PREFIX[prefix]
    OLS_CACHE.mkdir(parents=True, exist_ok=True)
    cached = OLS_CACHE / f"{curie.replace(':', '_')}.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text())
        except json.JSONDecodeError:
            cached.unlink()
    iri = iri_base + curie.split(":", 1)[1]
    base = f"https://www.ebi.ac.uk/ols4/api/ontologies/{ontology}/terms"
    url = f"{base}?iri={urllib.parse.quote(iri, safe='')}"
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                raw = resp.read().decode()
            data = json.loads(raw)
            cached.write_text(json.dumps(data))
            return data
        except Exception:
            if attempt == 0:
                time.sleep(1.5)
                continue
            return None


def ols_labels(data: dict | None) -> tuple[str, set[str]]:
    """Return (label, synonyms) from an OLS response."""
    if not data:
        return "", set()
    terms = (data.get("_embedded") or {}).get("terms") or []
    if not terms:
        return "", set()
    t = terms[0]
    label = t.get("label") or ""
    syns = {s for s in (t.get("synonyms") or []) if s}
    return label, syns


# ---------------------------------------------------------------------------
# Row-level logic
# ---------------------------------------------------------------------------

def _load_sssom(path: Path) -> tuple[list[str], list[dict]]:
    """Read an SSSOM TSV, skipping `#`-prefixed YAML frontmatter."""
    with path.open() as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    reader = csv.DictReader(lines, delimiter="\t")
    return list(reader.fieldnames or []), list(reader)


def _split_other(s: str) -> list[str]:
    return [a for a in (s or "").split("|") if a.strip()]


def verdict_for(
    row: dict,
    oak: dict[str, set[str]] | None,
    ols_label: str,
    ols_syns: set[str],
) -> tuple[str, dict]:
    """Classify a single mapping row; return (verdict, detail)."""
    obj_id = row["object_id"]
    obj_label = row.get("object_label", "") or ""
    subject_label = row.get("subject_label", "") or ""
    alt_labels = _split_other(row.get("other", ""))
    all_proposed = [subject_label] + alt_labels

    oak_has = oak is not None
    ols_has = bool(ols_label) or bool(ols_syns)

    if not oak_has and not ols_has:
        return "UNKNOWN_TERM", {
            "reason": f"neither OAK nor OLS resolves {obj_id}",
            "proposed": all_proposed,
        }

    oak_union = set()
    if oak:
        oak_union = oak["label"] | oak["exact"] | oak["related"]
    oak_norm = {_norm(x) for x in oak_union}
    ols_norm = {_norm(x) for x in ({ols_label} | ols_syns) if x}

    authoritative = oak_norm | ols_norm
    obj_label_ok = _norm(obj_label) in authoritative or not obj_label

    # OAK vs OLS disagreement: at least 3 labels one side has and the
    # other doesn't (allow small drift from synonym normalization)
    only_oak = oak_norm - ols_norm
    only_ols = ols_norm - oak_norm
    disagreement = oak_has and ols_has and (len(only_oak) >= 3 and len(only_ols) >= 3)

    new_candidates = [
        p for p in all_proposed if p and _norm(p) not in authoritative
    ]

    if not obj_label_ok:
        return "LABEL_MISMATCH", {
            "our_object_label": obj_label,
            "oak_label": next(iter(oak["label"]), "") if oak else "",
            "ols_label": ols_label,
            "new_candidates": new_candidates,
        }

    if disagreement:
        return "OLS_MISMATCH", {
            "only_in_oak": sorted(list(only_oak))[:6],
            "only_in_ols": sorted(list(only_ols))[:6],
            "new_candidates": new_candidates,
        }

    if new_candidates:
        return "SYNONYM_ENRICH", {
            "new_candidates": new_candidates,
            "already_in_chebi": [
                p for p in all_proposed if p and _norm(p) in authoritative
            ],
        }

    return "CONFIRMED", {"all_proposed_recognized": all_proposed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_SSSOM)
    ap.add_argument("--tsv-out", type=Path, default=DEFAULT_TSV_OUT)
    ap.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    ap.add_argument("--limit", type=int, default=0, help="only process first N rows (0 = all)")
    ap.add_argument("--oak-batch", type=int, default=40, help="chebi IDs per OAK subprocess call")
    ap.add_argument(
        "--skip-validate",
        action="store_true",
        help="skip the `sssom validate` preflight (default: on)",
    )
    args = ap.parse_args()

    if not args.skip_validate:
        print(f"Preflight: sssom validate {args.input.name} ...", file=sys.stderr)
        errors = sssom_validate(args.input)
        if errors:
            print("\nSSSOM validation FAILED (hard errors):", file=sys.stderr)
            for e in errors[:20]:
                print(f"  - {e[:200]}", file=sys.stderr)
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more", file=sys.stderr)
            print("\nRerun with --skip-validate to review anyway.", file=sys.stderr)
            sys.exit(2)
        print("  OK (no hard errors)", file=sys.stderr)

    _, rows = _load_sssom(args.input)
    if args.limit:
        rows = rows[: args.limit]

    print(f"Reviewing {len(rows)} SSSOM rows from {args.input}", file=sys.stderr)

    # OAK — batched. OAK is CHEBI-only (local sqlite); non-CHEBI rows
    # (FOODON/UBERON/ENVO) are resolved via OLS alone.
    chebi_ids = sorted({r["object_id"] for r in rows if r["object_id"].startswith("CHEBI:")})
    oak_result: dict[str, dict[str, set[str]]] = {}
    for i in range(0, len(chebi_ids), args.oak_batch):
        batch = chebi_ids[i : i + args.oak_batch]
        oak_result.update(oak_aliases_batch(batch))
        print(f"  OAK batch {i // args.oak_batch + 1}/{(len(chebi_ids) + args.oak_batch - 1) // args.oak_batch}", file=sys.stderr)

    # OLS — per term, cached. Hits whatever ontology the CURIE prefix
    # resolves to via `_OLS_ONTOLOGY_BY_PREFIX`.
    all_term_ids = sorted({r["object_id"] for r in rows if _prefix_for(r["object_id"]) is not None})
    ols_result: dict[str, tuple[str, set[str]]] = {}
    for idx, cid in enumerate(all_term_ids):
        ols_result[cid] = ols_labels(ols_fetch(cid))
        if (idx + 1) % 20 == 0:
            print(f"  OLS {idx + 1}/{len(all_term_ids)}", file=sys.stderr)

    verdicts: list[dict] = []
    counts = {}
    for row in rows:
        cid = row["object_id"]
        oak = oak_result.get(cid)
        # An OAK miss is represented as empty sets — distinguish from None
        oak_known = oak is not None and (oak["label"] or oak["exact"] or oak["related"])
        ols_label, ols_syns = ols_result.get(cid, ("", set()))
        v, detail = verdict_for(
            row,
            oak if oak_known else None,
            ols_label,
            ols_syns,
        )
        counts[v] = counts.get(v, 0) + 1
        verdicts.append(
            {
                "subject_id": row["subject_id"],
                "subject_label": row.get("subject_label", ""),
                "object_id": cid,
                "object_label": row.get("object_label", ""),
                "verdict": v,
                "new_candidates": "|".join(detail.get("new_candidates") or []),
                "only_in_oak": "|".join(detail.get("only_in_oak") or []),
                "only_in_ols": "|".join(detail.get("only_in_ols") or []),
                "notes": detail.get("reason", ""),
            }
        )

    args.tsv_out.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv_out.open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(verdicts[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(verdicts)

    md = ["# SSSOM Synonym Review\n"]
    md.append(f"- Input: `{args.input}`\n")
    md.append(f"- Rows: {len(rows)}\n")
    md.append(f"- Date: 2026-04-18\n\n## Verdict counts\n\n")
    md.append("| Verdict | Count |\n|---|---:|\n")
    for v in sorted(counts, key=lambda x: -counts[x]):
        md.append(f"| {v} | {counts[v]} |\n")
    md.append("\n## Rows needing attention\n\n")
    for bucket in ("LABEL_MISMATCH", "UNKNOWN_TERM", "OLS_MISMATCH", "SYNONYM_ENRICH"):
        sub = [v for v in verdicts if v["verdict"] == bucket]
        if not sub:
            continue
        md.append(f"### {bucket} ({len(sub)})\n\n")
        md.append("| Subject | Object | Our label | New candidates / notes |\n|---|---|---|---|\n")
        for v in sub[:30]:
            extra = v["new_candidates"] or v["notes"] or (v["only_in_oak"] + " / " + v["only_in_ols"])
            md.append(
                f"| `{v['subject_id']}` | `{v['object_id']}` | {v['object_label']} | {extra} |\n"
            )
        if len(sub) > 30:
            md.append(f"\n_... and {len(sub) - 30} more in the TSV_\n")
        md.append("\n")
    args.md_out.write_text("".join(md))

    print(f"\nTSV: {args.tsv_out}")
    print(f"MD:  {args.md_out}")
    for v in sorted(counts, key=lambda x: -counts[x]):
        print(f"  {v:16s} {counts[v]}")


if __name__ == "__main__":
    main()
