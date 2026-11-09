#!/usr/bin/env python3
"""Classify why quotes fail the shared quote gate, per Mech (read-only).

Purpose: separate validator/source limitations from curation defects before
choosing an adoption policy for culturebotai-claw#729. For every
SNIPPET_NOT_IN_SOURCE item it asks, in order: do the parts of a quote joined by
an ellipsis occur in order in the abstract ("ellipsis"); does removing
[bracketed] editorial text make it match ("brackets"); does it occur in a
full-text cache the Mech already tracks for that PMID ("full_text", files named
PMID_<n>.txt anywhere in the repository); is most of it present verbatim
("near": longest common run >= 80% of the quote); otherwise "absent".
Inputs: claw .env, the scratch PMID cache written by measure_quote_gate.py,
and the candidate profiles defined there.
Outputs: JSON at --output with counts and up to --samples examples per class.
Serves: culturebotai-claw#729. Written 2026-11-03.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_quote_gate import CANDIDATES  # noqa: E402

from kg_microbe_evidence import (  # noqa: E402
    EvidenceConfig,
    EvidenceValidator,
    iter_evidence,
    normalize,
)
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.repository_settings import (  # noqa: E402
    RepositorySettings,
    merged_repository_environment,
)

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
ELLIPSIS = re.compile(r"\s*(?:\.\s*\.\s*\.|…)\s*")
BRACKETS = re.compile(r"\[[^\]]*\]")


def _in_order(parts: list[str], body: str) -> bool:
    position = 0
    for part in parts:
        index = body.find(part, position)
        if index < 0:
            return False
        position = index + len(part)
    return True


def classify(quote: str, body: str, full_text: str | None) -> str:
    q, b = normalize(quote), normalize(body)
    parts = [p for p in (normalize(x) for x in ELLIPSIS.split(quote)) if p]
    if len(parts) > 1 and _in_order(parts, b):
        return "ellipsis"
    stripped = normalize(BRACKETS.sub(" ", quote))
    if stripped != q and stripped and all(normalize(x) in b for x in BRACKETS.split(quote) if normalize(x)):
        return "brackets"
    if full_text is not None:
        f = normalize(full_text)
        if q in f or (len(parts) > 1 and _in_order(parts, f)):
            return "full_text"
    match = SequenceMatcher(None, q, b, autojunk=False).find_longest_match(0, len(q), 0, len(b))
    if q and match.size / len(q) >= 0.8:
        return "near"
    return "absent"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mech", action="append", required=True)
    parser.add_argument("--samples", type=int, default=6)
    args = parser.parse_args()
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment(
        environ=merged_repository_environment(args.env), manifest=manifest)
    report = {}
    for key in args.mech:
        mech = manifest.get(key)
        target = settings.get_target(key)
        target.open()
        root = target.path
        config = EvidenceConfig.from_settings({"cache_dir": "references_cache", **CANDIDATES[key]})
        validator = EvidenceValidator(args.cache_root, config)
        tracked = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True,
                                 text=True, check=True).stdout.splitlines()
        full = {Path(p).name[5:-4]: root / p for p in tracked
                if re.fullmatch(r"PMID_[0-9]+\.txt", Path(p).name)}
        counts: Counter = Counter()
        by_record: Counter = Counter()
        samples: dict[str, list] = defaultdict(list)
        files = sorted({p for g in mech.record_globs for p in root.glob(g) if p.is_file()})
        for path in files:
            document = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
            for location, item in iter_evidence(document, config.evidence_fields):
                result = validator.check_item(item)
                if result.verdict != "SNIPPET_NOT_IN_SOURCE":
                    continue
                pmid = result.reference[5:]
                body = validator._source(pmid).body
                quote = next(item[f] for f in config.snippet_fields
                             if isinstance(item.get(f), str) and item[f].strip())
                text = full[pmid].read_text(encoding="utf-8", errors="replace") if pmid in full else None
                kind = classify(quote, body, text)
                counts[kind] += 1
                by_record[path.relative_to(root).as_posix()] += 1
                if len(samples[kind]) < args.samples:
                    samples[kind].append({"record": path.relative_to(root).as_posix(),
                                          "location": location, "reference": result.reference,
                                          "quote": quote[:400]})
        report[key] = {"mismatches": sum(counts.values()), "classes": dict(counts),
                       "records_with_mismatch": len(by_record), "full_text_caches": len(full),
                       "samples": samples}
        print(f"{key}: {sum(counts.values())} mismatches in {len(by_record)} records: {dict(counts)}",
              flush=True)
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
