#!/usr/bin/env python3
"""Classify TraitMech's quoted evidence whose citation is neither a PMID nor a DOI.

Purpose: TraitMech's disabled-capability reason must name the source adapters
its quotes need. Quote-bearing evidence items citing neither a PMID nor a DOI
are grouped by fixed URL rules: journal supplementary files (PMC open-data
supplements, Springer ESM, a /suppl path), article full text (PMC articles,
Europe PMC articles, NCBI Bookshelf), and everything else (model files, wikis,
enzyme and protocol pages, database records). Read-only and offline.
Inputs: --root, a TraitMech checkout; record glob data/traits/**/*.yaml.
Outputs: counts per class and per PMID/DOI on stdout.
Serves: culturebotai-claw#729 / #777. Written 2026-11-04.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from kg_microbe_evidence import EvidenceConfig, bears_quote, iter_evidence, normalize_doi

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
PMID = re.compile(r"PMID:\s*[0-9]+\Z", re.IGNORECASE)


def kind(reference: str) -> str:
    if PMID.fullmatch(reference):
        return "pmid"
    if normalize_doi(reference):
        return "doi"
    parts = urlsplit(reference)
    host, path = parts.netloc.lower(), parts.path
    if host == "pmc-oa-opendata.s3.amazonaws.com" or "/esm/" in path or "/suppl" in path.lower():
        return "journal supplement"
    if (host in {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"} and ("/articles/PMC" in path or path.startswith("/books/"))) \
            or (host == "europepmc.org" and path.startswith("/article/")):
        return "article full text"
    return "web or database source"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    config = EvidenceConfig.from_settings({"cache_dir": "unused", "reference_fields": ["reference"],
                                           "snippet_fields": ["snippet"]})
    counts: Counter = Counter()
    for path in sorted(args.root.glob("data/traits/**/*.yaml")):
        for _, item in iter_evidence(yaml.load(path.read_text(encoding="utf-8"), Loader=Loader), ["evidence"]):
            if bears_quote(item, config):
                counts[kind(str(item.get("reference", "")).strip())] += 1
    print(f"quote-bearing items: {sum(counts.values())}")
    for name, count in counts.most_common():
        print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
