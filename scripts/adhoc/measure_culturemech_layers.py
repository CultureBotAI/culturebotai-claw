#!/usr/bin/env python3
"""Compare CultureMech's derived and authoritative record layers for the quote gate.

Purpose: CultureMech's manifest record_globs name data/merge_yaml/merged/, which
its AGENTS.md calls derived ("Regenerate; do not edit"); data/normalized_yaml/
is the authoritative corpus. This measures, offline and read-only, how many
quote-bearing evidence items each layer holds and how their citations split
between PMID, DOI and other sources, under the profile the rollout had proposed.
Inputs: --root, a CultureMech checkout (its working tree is read; pass a
`git archive origin/main` export to measure main exactly).
Outputs: one summary line per layer on stdout.
Serves: culturebotai-claw#729 / the review of PR #773. Written 2026-11-04.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml

from kg_microbe_evidence import EvidenceConfig, EvidenceValidator, bears_quote, iter_evidence

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
LAYERS = {"derived merged (record_globs)": "data/merge_yaml/merged/*.yaml",
          "authoritative normalized": "data/normalized_yaml/**/*.yaml"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    config = EvidenceConfig.from_settings({"cache_dir": "no_cache_measurement", "reference_fields": ["reference"],
                                           "snippet_fields": ["snippet"], "evidence_fields": ["evidence"]})
    validator = EvidenceValidator(args.root, config)
    for name, pattern in LAYERS.items():
        files = sorted(args.root.glob(pattern))
        kinds: Counter = Counter()
        quoted = 0
        for path in files:
            document = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
            for _, item in iter_evidence(document, config.evidence_fields):
                if not bears_quote(item, config):
                    continue
                quoted += 1
                verdict = validator.check_item(item)
                # No cache directory exists, so a PMID or DOI citation reports
                # MISSING_CACHE and anything else UNSUPPORTED_REFERENCE.
                kind = verdict.reference.split(":", 1)[0] if verdict.verdict == "MISSING_CACHE" else verdict.verdict
                kinds[kind] += 1
        other = kinds.get("UNSUPPORTED_REFERENCE", 0)
        share = f"{other / quoted:.1%}" if quoted else "n/a"
        print(f"{name} [{pattern}]: records={len(files)} quote_bearing={quoted} "
              f"citations={dict(kinds)} non_pmid_doi_share={share}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
