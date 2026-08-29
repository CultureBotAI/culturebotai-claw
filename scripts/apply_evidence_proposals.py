#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Apply propose-evidence drafts to MIM ingredient YAMLs.

Reads `workspace/reports/evidence_proposals/<slug>.md`, parses every
embedded ```yaml MappingEvidence block, validates each candidate
snippet against the cached PubMed abstract using the same NFKC +
substring logic as `scripts/validate_evidence_references.py`. Picks
the first snippet that validates. If none validate, skips the
ingredient.

Refuses to add a duplicate (same pmid already cited on this record).
Appends a curation_history entry: `action: APPLY_EVIDENCE_PROPOSAL`.

Task B of the curation follow-up plan; bridges Phase 1 (validator)
and Phase 4 (proposer) so high-confidence drafts auto-land.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
PROPOSALS_DIR = REPO_ROOT / "workspace" / "reports" / "evidence_proposals"
OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "evidence_proposals_apply.tsv"
OUT_MD = OUT_DIR / "evidence_proposals_apply.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_ingredient_type import (  # noqa: E402
    append_curation_event,
    load_yaml,
)
from validate_evidence_references import (  # noqa: E402
    load_cache,
    normalize,
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



_YAML_BLOCK_RE = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)
_TARGET_YAML_RE = re.compile(
    r"\*\*MIM YAML:\*\*\s*`(?P<path>[^`]+)`")
_PREFERRED_TERM_RE = re.compile(r"^# Evidence proposals — (?P<term>.+)$",
                                re.MULTILINE)


def parse_proposal_md(md_path: Path) -> dict:
    """Extract the target YAML path and the candidate evidence blocks."""
    text = md_path.read_text()
    m = _TARGET_YAML_RE.search(text)
    if not m:
        return {"target": None, "candidates": [], "preferred_term": ""}
    target_rel = m.group("path").strip()
    pt = _PREFERRED_TERM_RE.search(text)
    preferred_term = pt.group("term").strip() if pt else ""

    candidates: list[dict] = []
    for block in _YAML_BLOCK_RE.findall(text):
        try:
            parsed = yaml.safe_load(block)
        except Exception:
            continue
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    candidates.append(item)
        elif isinstance(parsed, dict):
            candidates.append(parsed)
    return {"target": target_rel, "candidates": candidates,
            "preferred_term": preferred_term}


def already_cited(record: dict, pmid: str) -> bool:
    om = record.get("ontology_mapping") or {}
    for ev in om.get("evidence") or []:
        if (ev.get("pmid") or "").strip() == pmid.strip():
            return True
    return False


def validate_snippet(pmid: str, snippet: str) -> tuple[bool, str]:
    """Returns (passes, reason)."""
    if not pmid or not snippet:
        return False, "missing pmid or snippet"
    cache = load_cache(pmid)
    if cache is None:
        return False, f"PMID:{pmid} not in cache"
    if normalize(snippet) in normalize(cache):
        return True, "snippet substring of cached abstract"
    return False, "snippet not in cached abstract"


def pick_validated_candidate(candidates: list[dict],
                             ingredient_yaml: dict
                             ) -> tuple[dict | None, str]:
    """Return (candidate_or_None, reason)."""
    if not candidates:
        return None, "NO_CANDIDATES"
    for cand in candidates:
        pmid = (cand.get("pmid") or "").strip()
        snippet = (cand.get("snippet") or "").strip()
        if not pmid or not snippet:
            continue
        if already_cited(ingredient_yaml, pmid):
            continue
        passes, reason = validate_snippet(pmid, snippet)
        if passes:
            return cand, reason
    return None, "NO_VALID_SNIPPET"


def normalize_supports(value: str | None) -> str:
    if not value:
        return "SUPPORT"
    # Strip inline comments like 'SUPPORT  # curator-verify'
    return str(value).split("#", 1)[0].strip().upper() or "SUPPORT"


def build_evidence_item(cand: dict, preferred_term: str) -> dict:
    return {
        "evidence_type": "LITERATURE",
        "source": (cand.get("source") or
                   "auto-applied from propose-evidence batch"),
        "pmid": str(cand.get("pmid", "")).strip(),
        "supports": normalize_supports(cand.get("supports")),
        "snippet": (cand.get("snippet") or "").strip(),
        "explanation": (
            cand.get("explanation")
            or f"PubMed-grounded supporting context for {preferred_term}; "
               "auto-applied from propose-evidence batch."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    global _TRANSACTION
    _TRANSACTION = ValidatedWriteTransaction(
        MIM_ROOT,
        journal_dir=OUT_DIR / "write_journal",
    )

    if not PROPOSALS_DIR.is_dir():
        print(f"No proposals at {PROPOSALS_DIR}", file=sys.stderr)
        return 2

    proposal_files = sorted(p for p in PROPOSALS_DIR.glob("*.md")
                            if p.name != "_summary.md")
    if args.limit:
        proposal_files = proposal_files[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, str, str, str]] = []
    counts: dict[str, int] = {}

    for prop_path in proposal_files:
        plan = parse_proposal_md(prop_path)
        target_rel = plan["target"]
        candidates = plan["candidates"]
        preferred_term = plan["preferred_term"]
        if not target_rel:
            counts["NO_TARGET"] = counts.get("NO_TARGET", 0) + 1
            rows.append((prop_path.name, "", "NO_TARGET", "", ""))
            continue
        target_path = MIM_ROOT / target_rel
        if not target_path.is_file():
            counts["TARGET_MISSING"] = counts.get("TARGET_MISSING", 0) + 1
            rows.append((prop_path.name, target_rel, "TARGET_MISSING",
                         "", ""))
            continue

        record = load_yaml(target_path)
        if not record:
            counts["TARGET_UNPARSEABLE"] = counts.get("TARGET_UNPARSEABLE", 0) + 1
            rows.append((prop_path.name, target_rel, "TARGET_UNPARSEABLE",
                         "", ""))
            continue

        cand, reason = pick_validated_candidate(candidates, record)
        if cand is None:
            counts[reason] = counts.get(reason, 0) + 1
            rows.append((prop_path.name, target_rel, reason,
                         f"{len(candidates)} candidates", ""))
            continue

        # All checks passed — apply (if --apply)
        ev = build_evidence_item(cand, preferred_term)
        if args.apply:
            om = record.setdefault("ontology_mapping", {})
            om.setdefault("evidence", []).append(ev)
            append_curation_event(
                record, "APPLY_EVIDENCE_PROPOSAL",
                f"added pmid={ev['pmid']} from propose-evidence batch")
            _staged_write(target_path, record)
            verdict = "APPLIED"
        else:
            verdict = "WOULD_APPLY"
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append((prop_path.name, target_rel, verdict,
                     ev["pmid"], ev["snippet"][:120]))

    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["proposal_file", "target_yaml", "verdict",
                    "pmid_or_count", "snippet_preview"])
        w.writerows(rows)

    md = ["# Evidence proposals — apply pass\n",
          f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**\n",
          f"Proposal files processed: **{len(proposal_files)}**\n",
          "\n## Verdicts\n",
          "| verdict | count |", "|---|---:|"]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        md.append(f"| `{k}` | {v} |")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"Proposals processed: {len(proposal_files)}")
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
