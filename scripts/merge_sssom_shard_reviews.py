"""Merge per-shard agent review JSONL files back into the working-copy
SSSOM, stamping `validation_method` per row and producing the same
TSV/MD summaries as `review_sssom_synonyms.py`.

Each shard JSONL contains one object per row, each shape:

    {"subject_id": "...", "object_id": "...", "verdict": "CONFIRMED",
     "authorities": ["OAK", "OLS:chebi"], "notes": "..."}

Rows missing from every shard output (agent crashed or produced
incomplete output) get stamped `none|UNVERIFIED|{date}` with a
placeholder note. The SSSOM `validation_method` column stays the
compact `{authorities}|{verdict}|{date}` — notes go into the TSV/MD
summary only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the loader / writer / summary helpers from the serial reviewer.
import importlib.util


REPO_ROOT = Path(__file__).resolve().parent.parent
CLAW_ROOT = REPO_ROOT
DEFAULT_SSSOM = CLAW_ROOT / "workspace" / "reports" / "mim_ingredient_mappings.sssom.tsv"
DEFAULT_RESULTS_DIR = CLAW_ROOT / "workspace" / "results"
DEFAULT_SHARD_GLOB = "sssom_review_shard_*.jsonl"
DEFAULT_TSV_OUT = CLAW_ROOT / "workspace" / "reports" / "sssom_team_review.tsv"
DEFAULT_MD_OUT = CLAW_ROOT / "workspace" / "reports" / "sssom_team_review.md"

VALID_VERDICTS = {
    "CONFIRMED",
    "SYNONYM_ENRICH",
    "LABEL_MISMATCH",
    "OLS_MISMATCH",
    "UNKNOWN_TERM",
    "UNVERIFIED",
}


def _load_reviewer():
    spec = importlib.util.spec_from_file_location(
        "review_sssom_synonyms", CLAW_ROOT / "scripts" / "review_sssom_synonyms.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_shard_jsonl(paths: list[Path]) -> dict[tuple[str, str], dict]:
    """Load all shard outputs, keyed by (subject_id, object_id). Later
    shards overwrite earlier ones if they disagree — but shards should
    not overlap."""
    merged: dict[tuple[str, str], dict] = {}
    for p in paths:
        with p.open() as f:
            for ln_no, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError as e:
                    print(
                        f"  WARN: {p.name}:{ln_no}: invalid JSON ({e}); skipping",
                        file=sys.stderr,
                    )
                    continue
                sid = obj.get("subject_id")
                oid = obj.get("object_id")
                if not sid or not oid:
                    print(
                        f"  WARN: {p.name}:{ln_no}: missing subject_id/object_id; skipping",
                        file=sys.stderr,
                    )
                    continue
                key = (sid, oid)
                if key in merged and merged[key].get("_source") != p.name:
                    print(
                        f"  WARN: {p.name}:{ln_no}: duplicate key {key} also in "
                        f"{merged[key].get('_source')}; keeping first",
                        file=sys.stderr,
                    )
                    continue
                obj["_source"] = p.name
                merged[key] = obj
    return merged


def _stamp_row(row: dict, agent_out: dict | None, review_date: str) -> dict:
    """Produce the per-row review result dict used by both the TSV
    summary and the SSSOM stamp. Returns the dict; caller writes
    row['validation_method'] from the returned 'stamp' field."""
    if agent_out is None:
        verdict = "UNVERIFIED"
        authorities: list[str] = []
        notes = "no shard output for this row; agent never returned a verdict"
    else:
        verdict = agent_out.get("verdict") or "UNVERIFIED"
        if verdict not in VALID_VERDICTS:
            notes_extra = (
                f" [orig verdict {verdict!r} not in VALID_VERDICTS; coerced to UNVERIFIED]"
            )
            verdict = "UNVERIFIED"
        else:
            notes_extra = ""
        authorities = agent_out.get("authorities") or []
        if not isinstance(authorities, list):
            authorities = [str(authorities)]
        notes = (agent_out.get("notes") or "").strip() + notes_extra

    auth_str = "+".join(authorities) if authorities else "none"
    stamp = f"{auth_str}|{verdict}|{review_date}"
    return {
        "subject_id": row["subject_id"],
        "subject_label": row.get("subject_label", ""),
        "object_id": row["object_id"],
        "object_label": row.get("object_label", ""),
        "verdict": verdict,
        "authorities": auth_str,
        "notes": notes,
        "stamp": stamp,
    }


def _write_summary_tsv(path: Path, reviews: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["subject_id", "subject_label", "object_id", "object_label",
            "verdict", "authorities", "notes"]
    with path.open("w") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t",
                           extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(reviews)


def _write_summary_md(path: Path, reviews: list[dict], review_date: str,
                      sssom_path: Path) -> None:
    counts: dict[str, int] = {}
    for r in reviews:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    md: list[str] = []
    md.append("# SSSOM Team Review\n\n")
    md.append(f"- Input: `{sssom_path}`\n")
    md.append(f"- Rows: {len(reviews)}\n")
    md.append(f"- Date: {review_date}\n\n")
    md.append("## Verdict counts\n\n| Verdict | Count |\n|---|---:|\n")
    for v in sorted(counts, key=lambda x: -counts[x]):
        md.append(f"| {v} | {counts[v]} |\n")
    md.append("\n## Rows needing attention\n\n")
    attn_order = ("LABEL_MISMATCH", "UNKNOWN_TERM", "OLS_MISMATCH",
                  "SYNONYM_ENRICH", "UNVERIFIED")
    for bucket in attn_order:
        sub = [r for r in reviews if r["verdict"] == bucket]
        if not sub:
            continue
        md.append(f"### {bucket} ({len(sub)})\n\n")
        md.append("| Subject | Object | Our label | Notes |\n|---|---|---|---|\n")
        for r in sub[:30]:
            md.append(
                f"| `{r['subject_id']}` | `{r['object_id']}` | "
                f"{r['object_label']} | {r['notes']} |\n"
            )
        if len(sub) > 30:
            md.append(f"\n_... and {len(sub) - 30} more in the TSV_\n")
        md.append("\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(md))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_SSSOM,
                    help="working-copy SSSOM to stamp")
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--shard-glob", default=DEFAULT_SHARD_GLOB)
    ap.add_argument("--tsv-out", type=Path, default=DEFAULT_TSV_OUT)
    ap.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    ap.add_argument("--date", default=None,
                    help="override review date (YYYY-MM-DD); default: today UTC")
    args = ap.parse_args()

    reviewer = _load_reviewer()

    shard_paths = sorted(args.results_dir.glob(args.shard_glob))
    if not shard_paths:
        raise SystemExit(
            f"No shard files matched {args.results_dir}/{args.shard_glob}"
        )
    print(f"Loading {len(shard_paths)} shard files...", file=sys.stderr)
    for p in shard_paths:
        print(f"  {p.name}", file=sys.stderr)

    agent_outputs = _load_shard_jsonl(shard_paths)
    print(f"  {len(agent_outputs)} row-verdicts loaded", file=sys.stderr)

    review_date = args.date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    fieldnames, rows, header_text = reviewer._load_sssom(args.input)
    if "validation_method" not in fieldnames:
        raise SystemExit(
            f"{args.input} has no validation_method column — "
            f"rebuild with `just build-sssom` first"
        )

    reviews: list[dict] = []
    counts: dict[str, int] = {}
    for row in rows:
        key = (row["subject_id"], row["object_id"])
        agent_out = agent_outputs.get(key)
        result = _stamp_row(row, agent_out, review_date)
        row["validation_method"] = result["stamp"]
        counts[result["verdict"]] = counts.get(result["verdict"], 0) + 1
        reviews.append(result)

    reviewer._write_sssom_inplace(args.input, fieldnames, rows, header_text)
    print(f"  stamped validation_method on {len(rows)} rows of {args.input.name}",
          file=sys.stderr)

    _write_summary_tsv(args.tsv_out, reviews)
    _write_summary_md(args.md_out, reviews, review_date, args.input)

    print(f"\nTSV: {args.tsv_out}")
    print(f"MD:  {args.md_out}")
    for v in sorted(counts, key=lambda x: -counts[x]):
        print(f"  {v:16s} {counts[v]}")


if __name__ == "__main__":
    main()
