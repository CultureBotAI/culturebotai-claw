#!/usr/bin/env python3
"""Measure what the shared quote gate would report for each Mech (read-only).

Purpose: size the per-Mech adoption work for culturebotai-claw#729 with real
verdicts, not field shapes. Each Mech's records are read in place; the shared
`kg_microbe_evidence` validator checks them against a PMID abstract cache kept
OUTSIDE every Mech repository (--cache-root/references_cache), so no Mech file
is written. Candidate profiles below are measurement inputs only; they are not
manifest declarations.
Inputs: claw .env (Mech roots), candidate profiles in CANDIDATES, the scratch
cache. With --fetch, missing PMID abstracts are fetched anonymously from NCBI
E-utilities (batched, <=3 requests/s, no email or API key) and written in the
`# PMID:n` / `## Abstract` format the validator reads; without it the run is
offline and reports how many caches are missing.
Outputs: JSON at --output (verdicts per Mech and selector, unique PMIDs, PMIDs
without an abstract) and a summary on stdout.
Serves: culturebotai-claw#729. Written 2026-11-03.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml

from kg_microbe_evidence import _PMID, EvidenceConfig, EvidenceValidator, iter_evidence
from kg_microbe_fleet import load_fleet_manifest
from plugins.repository_settings import RepositorySettings, merged_repository_environment

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
# Broad candidate mappings from the shape survey: every `evidence` container,
# each Mech's native quote and citation slots. Measurement only.
CANDIDATES = {
    "culturemech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "mediaingredientmech": {"reference_fields": ["pmid", "doi", "reference"],
                            "snippet_fields": ["snippet", "excerpt", "supporting_text"]},
    "communitymech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "traitmech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "proteintraitsmech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "antibioticmech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "cellstructuremech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "habitatmech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "naturalproductmech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "taxonmech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "pathwaymech": {"reference_fields": ["reference_id"], "snippet_fields": ["quote"]},
    "dufmech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
    "cmmmech": {"reference_fields": ["source_ref"], "snippet_fields": ["snippet"]},
    "aimech": {"reference_fields": ["reference"], "snippet_fields": ["snippet"]},
}
_STATE: dict = {}


def _selector(location: str) -> str:
    import re
    relative = re.sub(r"^\$(?:\[[0-9]+\])?\.", "", location)
    return re.sub(r"\[[0-9]+\]", "[]", re.sub(r"\[[0-9]+\]$", "", relative))


def _init(cache_parent: str, settings: dict) -> None:
    config = EvidenceConfig.from_settings({"cache_dir": "references_cache", **settings})
    _STATE["config"] = config
    _STATE["validator"] = EvidenceValidator(Path(cache_parent), config)


def _check_file(path: str) -> tuple[list[tuple[str, str, str]], set[str], str | None]:
    config, validator = _STATE["config"], _STATE["validator"]
    try:
        document = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=Loader)
    except Exception as exc:  # noqa: BLE001 -- counted, never dropped
        return [], set(), f"{type(exc).__name__}: {exc}"[:200]
    rows, pmids = [], set()
    for location, item in iter_evidence(document, config.evidence_fields):
        result = validator.check_item(item)
        rows.append((_selector(location), result.verdict, result.reference))
        if result.reference.startswith("PMID:"):
            pmids.add(result.reference[5:])
        elif isinstance(item, dict):
            for field in config.reference_fields:
                value = item.get(field)
                if isinstance(value, str):
                    match = _PMID.fullmatch(value.strip())
                    if match and (field == "pmid" or value.strip().upper().startswith("PMID:")):
                        pmids.add(match.group(1))
    return rows, pmids, None


def measure(root: Path, globs: tuple[str, ...], settings: dict, cache_parent: Path, jobs: int) -> dict:
    files = sorted({str(p) for g in globs for p in root.glob(g) if p.is_file()})
    selectors: dict[str, Counter] = defaultdict(Counter)
    pmids: set[str] = set()
    errors = 0
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init,
                             initargs=(str(cache_parent), settings)) as pool:
        for rows, found, error in pool.map(_check_file, files, chunksize=128):
            errors += bool(error)
            pmids |= found
            for selector, verdict, _ in rows:
                selectors[selector][verdict] += 1
    total = Counter()
    for counts in selectors.values():
        total.update(counts)
    return {"files": len(files), "parse_errors": errors, "verdicts": dict(total),
            "selectors": {k: dict(v) for k, v in sorted(selectors.items())},
            "unique_pmids": sorted(pmids, key=int)}


def _render(pmid: str, article: ET.Element) -> str | None:
    node = article.find("MedlineCitation/Article")
    if node is None:
        return None
    parts = []
    for abstract in node.findall("Abstract/AbstractText"):
        label, text = abstract.attrib.get("Label", ""), "".join(abstract.itertext()).strip()
        parts.append(f"**{label}:** {text}" if label else text)
    if not any(p.strip() for p in parts):
        return None
    title = "".join(node.find("ArticleTitle").itertext()).strip() if node.find("ArticleTitle") is not None else ""
    lines = [f"# PMID:{pmid}", ""]
    if title:
        lines.append(f"**Title:** {title}")
    lines += ["", "## Abstract", "", "\n\n".join(parts), ""]
    return "\n".join(lines)


def fetch(pmids: list[str], cache: Path, batch: int, rate: float) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    missing = [p for p in pmids if not (cache / f"PMID_{p}.md").exists()
               and not (cache / f"PMID_{p}.noabstract").exists()]
    stats = Counter()
    for start in range(0, len(missing), batch):
        chunk = missing[start:start + batch]
        body = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(chunk),
                                       "retmode": "xml", "rettype": "abstract"}).encode()
        request = urllib.request.Request(EUTILS, data=body,
                                         headers={"User-Agent": "culturebotai-claw-evidence-survey/1"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = response.read()
                break
            except Exception as exc:  # noqa: BLE001
                stats["retry"] += 1
                time.sleep(2 ** attempt)
                if attempt == 3:
                    raise SystemExit(f"fetch failed for batch at {start}: {exc}") from exc
        returned = set()
        for article in ET.fromstring(payload).findall("PubmedArticle"):
            pmid = (article.findtext("MedlineCitation/PMID") or "").strip()
            if pmid not in chunk:
                stats["unexpected_pmid"] += 1
                continue
            returned.add(pmid)
            text = _render(pmid, article)
            target = cache / (f"PMID_{pmid}.md" if text else f"PMID_{pmid}.noabstract")
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache, delete=False) as stream:
                stream.write(text or "")
            os.replace(stream.name, target)
            stats["abstract" if text else "no_abstract"] += 1
        stats["not_returned"] += len(set(chunk) - returned)
        time.sleep(1.0 / rate)
    stats["requested"] = len(missing)
    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True,
                        help="scratch directory outside every Mech; caches go in references_cache/")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mech", action="append")
    parser.add_argument("--fetch", action="store_true", help="fetch missing PMID abstracts from NCBI")
    parser.add_argument("--fetch-limit", type=int, help="fetch at most this many PMIDs (canary)")
    parser.add_argument("--batch", type=int, default=200)
    parser.add_argument("--rate", type=float, default=2.0)
    parser.add_argument("--jobs", type=int, default=10)
    args = parser.parse_args()
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment(
        environ=merged_repository_environment(args.env), manifest=manifest)
    cache = args.cache_root / "references_cache"
    report = {}
    for key, mech in manifest.mechs.items():
        if args.mech and key not in args.mech:
            continue
        target = settings.get_target(key)
        target.open()
        if args.fetch:
            first = measure(target.path, mech.record_globs, CANDIDATES[key], args.cache_root, args.jobs)
            wanted = first["unique_pmids"][: args.fetch_limit] if args.fetch_limit else first["unique_pmids"]
            print(f"{key}: fetch {fetch(wanted, cache, args.batch, args.rate)}", flush=True)
        result = measure(target.path, mech.record_globs, CANDIDATES[key], args.cache_root, args.jobs)
        no_abstract = [p for p in result["unique_pmids"] if (cache / f"PMID_{p}.noabstract").exists()]
        result.update(no_abstract_pmids=no_abstract, candidate=CANDIDATES[key])
        report[key] = result
        print(f"{key}: files={result['files']} pmids={len(result['unique_pmids'])} "
              f"no_abstract={len(no_abstract)} verdicts={result['verdicts']}", flush=True)
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
