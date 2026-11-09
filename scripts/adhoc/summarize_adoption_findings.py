#!/usr/bin/env python3
"""Summarize an adopting Mech's residual quote findings for its backlog issue.

Purpose: describe, for curators, what the shared gate still reports after an
adopter's abstracts are cached: counts by verdict, how many records carry them,
and what kind of mismatch each SNIPPET_NOT_IN_SOURCE is -- the paper's title
used as a quote ("title"), most of the quote present verbatim ("near": longest
common run >= 80%), or not found ("absent": usually full text or paraphrase).
Read-only.
Inputs: --mech and --root (the adopter worktree with its fetched caches); the
profile from prepare_evidence_adoption.PROFILES.
Outputs: JSON at --output and a summary on stdout.
Serves: culturebotai-claw#729. Written 2026-11-04.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_evidence_adoption import PROFILES  # noqa: E402

from kg_microbe_evidence import EvidenceConfig, normalize, validate_corpus  # noqa: E402
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402

TITLE = re.compile(r"^\*\*Title:\*\* (.+)$", re.MULTILINE)


def kind(quote: str, cache_text: str, body: str) -> str:
    title = TITLE.search(cache_text)
    q = normalize(quote)
    if title and q and q in normalize(title.group(1)):
        return "title"
    b = normalize(body)
    match = SequenceMatcher(None, q, b, autojunk=False).find_longest_match(0, len(q), 0, len(b))
    return "near" if q and match.size / len(q) >= 0.8 else "absent"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mech", required=True, choices=sorted(PROFILES))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import yaml

    from kg_microbe_evidence import iter_evidence, parse_cache_text
    mech = load_fleet_manifest().get(args.mech)
    root = args.root.resolve()
    settings = {k: v for k, v in PROFILES[args.mech].items() if k != "known_findings"}
    config = EvidenceConfig.from_settings(settings)
    report = validate_corpus(root, mech.record_globs, config)
    quotes: dict[tuple[str, str], str] = {}
    for record in {r["record"] for r in report["results"] if r["verdict"] == "SNIPPET_NOT_IN_SOURCE"}:
        document = yaml.safe_load((root / record).read_text(encoding="utf-8"))
        for location, item in iter_evidence(document, config.evidence_fields):
            if isinstance(item, dict) and isinstance(item.get("snippet"), str):
                quotes[(record, location)] = item["snippet"]
    verdicts: Counter = Counter()
    mismatch: Counter = Counter()
    records: dict[str, Counter] = defaultdict(Counter)
    for row in report["results"]:
        if row["verdict"] in {"OK", "NO_QUOTE"}:
            continue
        verdicts[row["verdict"]] += 1
        records[row["record"]][row["verdict"]] += 1
        if row["verdict"] == "SNIPPET_NOT_IN_SOURCE":
            text = (root / row["cache_path"]).read_text(encoding="utf-8")
            kind_name = row["reference"].split(":", 1)
            body = parse_cache_text(text, kind_name[0], kind_name[1])
            mismatch[kind(quotes[(row["record"], row["location"])], text, body)] += 1
    out = {"mech": args.mech, "quote_bearing_items": report["quote_bearing_items"],
           "ok": report["verdicts"]["OK"], "findings": dict(verdicts),
           "mismatch_kinds": dict(mismatch), "records_with_findings": len(records),
           "top_records": [{"record": r, **dict(c)} for r, c in
                           sorted(records.items(), key=lambda kv: -sum(kv[1].values()))[:10]]}
    print(json.dumps({k: v for k, v in out.items() if k != "top_records"}))
    args.output.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
