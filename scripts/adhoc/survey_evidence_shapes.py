#!/usr/bin/env python3
"""Survey evidence-item shapes across the Mech fleet (read-only).

Purpose: for each manifest Mech, inventory every container whose key names
evidence, the fields its items carry, how many items carry a quote-like field,
and how their citations are identified (PMID, DOI, other, none). Also counts
tracked PMID markdown caches. This sizes the per-Mech adoption work for the
shared quote gate; it is a shape inventory, not a quote-validation result.
Inputs: claw's .env (Mech roots, via --env), the fleet manifest's record_globs,
and each Mech checkout, which must be clean with HEAD == origin/main.
Outputs: JSON at --output and a summary table on stdout.
Serves: culturebotai-claw#729. Written 2026-11-03.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml

from kg_microbe_fleet import load_fleet_manifest
from plugins.repository_settings import RepositorySettings, merged_repository_environment

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
QUOTE_FIELDS = ("snippet", "excerpt", "supporting_text", "quote", "verbatim_quote",
                "supporting_quote", "source_text", "text", "statement")
REFERENCE_FIELDS = ("pmid", "doi", "reference", "reference_id", "source", "source_ref",
                    "source_id", "url", "citation", "publication", "pubmed_id", "ref")
PMID = re.compile(r"^(?:PMID:\s*)?([0-9]+)$", re.IGNORECASE)
DOI = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?10\.[0-9]{4,9}/\S+$", re.IGNORECASE)


def _selector(parts: list[str]) -> str:
    return ".".join(parts)


def _classify_reference(item: dict) -> str:
    kinds = set()
    for field in REFERENCE_FIELDS:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if field == "pmid" and PMID.fullmatch(value):
            kinds.add("pmid")
        elif value.upper().startswith("PMID:") and PMID.fullmatch(value):
            kinds.add("pmid")
        elif DOI.fullmatch(value):
            kinds.add("doi")
        else:
            kinds.add("other")
    if "pmid" in kinds:
        return "pmid"
    if "doi" in kinds:
        return "doi"
    return "other" if kinds else "none"


def _walk(node, parts, out):
    if isinstance(node, list):
        for child in node:
            _walk(child, parts[:-1] + [parts[-1] + "[]"] if parts else ["[]"], out)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if not isinstance(key, str):
            continue
        path = parts + [key]
        if "evidence" in key.lower() and value not in (None, [], ""):
            items = value if isinstance(value, list) else [value]
            selector = _selector(path)
            for item in items:
                out.append((selector, item))
        _walk(value, path, out)


def survey_file(path: str) -> tuple[str, list[tuple[str, dict]], str | None]:
    try:
        document = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=Loader)
    except Exception as exc:  # noqa: BLE001 -- reported, never dropped
        return path, [], f"{type(exc).__name__}: {exc}"[:300]
    found: list = []
    _walk(document, [], found)
    rows = []
    for selector, item in found:
        if isinstance(item, dict):
            quotes = [f for f in QUOTE_FIELDS if isinstance(item.get(f), str) and item[f].strip()]
            rows.append((selector, {"shape": "object", "fields": sorted(map(str, item)),
                                    "quote_fields": quotes, "reference": _classify_reference(item)}))
        else:
            rows.append((selector, {"shape": type(item).__name__, "fields": [], "quote_fields": [],
                                    "reference": "none"}))
    return path, rows, None


def survey_mech(key: str, root: Path, globs: tuple[str, ...], jobs: int) -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    head, origin = git("rev-parse", "HEAD"), git("rev-parse", "refs/remotes/origin/main")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    files = sorted({str(p) for g in globs for p in root.glob(g) if p.is_file()})
    caches = [p for p in git("ls-files").splitlines()
              if re.search(r"(^|/)PMID_[0-9]+\.md$", p)]
    selectors: dict[str, dict] = defaultdict(lambda: {
        "items": 0, "object_items": 0, "with_quote": 0, "fields": Counter(),
        "quote_fields": Counter(), "reference": Counter(), "quote_reference": Counter()})
    errors = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for path, rows, error in pool.map(survey_file, files, chunksize=64):
            if error:
                errors.append({"file": str(Path(path).relative_to(root)), "error": error})
            for selector, row in rows:
                s = selectors[selector]
                s["items"] += 1
                if row["shape"] == "object":
                    s["object_items"] += 1
                s["fields"].update(row["fields"])
                s["reference"][row["reference"]] += 1
                if row["quote_fields"]:
                    s["with_quote"] += 1
                    s["quote_fields"].update(row["quote_fields"])
                    s["quote_reference"][row["reference"]] += 1
    return {
        "key": key, "root": str(root), "head": head, "origin_main": origin,
        "head_is_origin_main": head == origin, "tracked_changes": dirty,
        "record_files": len(files), "tracked_pmid_caches": len(caches),
        "cache_dirs": sorted({str(Path(p).parent) for p in caches}),
        "parse_errors": errors,
        "selectors": {k: {**{f: v for f, v in s.items() if not isinstance(v, Counter)},
                          **{f: dict(v.most_common()) for f, v in s.items() if isinstance(v, Counter)}}
                      for k, s in sorted(selectors.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="claw .env naming Mech roots")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mech", action="append", help="limit to these manifest keys")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment(
        environ=merged_repository_environment(args.env), manifest=manifest)
    report = []
    for key, mech in manifest.mechs.items():
        if args.mech and key not in args.mech:
            continue
        target = settings.get_target(key)
        target.open()
        result = survey_mech(key, target.path, mech.record_globs, args.jobs)
        report.append(result)
        total = sum(s["items"] for s in result["selectors"].values())
        quoted = sum(s["with_quote"] for s in result["selectors"].values())
        qref = Counter()
        for s in result["selectors"].values():
            qref.update(s["quote_reference"])
        print(f"{key}: files={result['record_files']} evidence_items={total} with_quote={quoted} "
              f"quote_refs={dict(qref)} pmid_caches={result['tracked_pmid_caches']} "
              f"errors={len(result['parse_errors'])} head==origin/main={result['head_is_origin_main']} "
              f"dirty={result['tracked_changes']}", flush=True)
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
