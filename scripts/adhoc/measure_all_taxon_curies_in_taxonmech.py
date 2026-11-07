#!/usr/bin/env python3
"""Every NCBITaxon CURIE in each Mech's records, against TaxonMech's seed scope.

Purpose: sizes the whole cross-Mech taxon-link problem, not only the
protein-example slice that measure_protein_example_taxa_in_taxonmech.py
covers. Any NCBITaxon CURIE written anywhere in a record (target organisms,
producer organisms, reported taxa, canonical examples, causal-graph scopes,
lineage copies) is a place a TaxonMech link could resolve. A CURIE outside
TaxonMech's scope is one that cannot.
Method: scan the text of every file under each Mech's manifest record_globs
for NCBITaxon:<digits>, without parsing YAML, so lineage entries and prose
count too; this is an upper bound on link targets, and the protein-example
script is the lower bound. TaxonMech itself is skipped.
Inputs: claw's .env (set -a; . ./.env) for the Mech roots; --out DIR.
Outputs: DIR/taxon_curies.tsv (mech, taxon id, records citing it, in scope)
and DIR/summary_all_curies.md (per-Mech distinct taxa, how many are in scope,
and the most-cited taxa outside it). Read-only; writes only under DIR.
A CURIE in a `notes:` line counts like one in a slot, so a Mech whose seeder
records a retired id beside the current one (NaturalProductMech) shows retired
ids here that no slot carries (culturebotai-claw#885); the slot-declared
`kg-microbe-links taxa` check is the one that tells them apart.
The rows are written in a deterministic order, so a re-run at the same HEADs
produces the same bytes.
Serves: the cross-Mech taxon-link assessment, culturebotai-claw PR 881.
Written 2026-11-06.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.repository_settings import RepositorySettings  # noqa: E402

CURIE = re.compile(rb"NCBITaxon:([1-9][0-9]*)")
SKIP = {"taxonmech"}


def head_of(root: Path) -> str:
    return subprocess.run(["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
                          text=True, capture_output=True, check=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment()
    taxonmech = settings.paths.get("taxonmech")
    if taxonmech is None:
        raise SystemExit(f"taxonmech: {settings.errors.get('taxonmech', 'not configured')}")
    with (taxonmech / "curation/seed_scope.tsv").open(encoding="utf-8") as handle:
        scope = {row["identifier"] for row in csv.DictReader(handle, delimiter="\t")}
    heads = {"taxonmech": head_of(taxonmech)}
    records_citing: dict[str, Counter] = defaultdict(Counter)
    files: Counter = Counter()
    for key, mech in manifest.mechs.items():
        if key in SKIP:
            continue
        root = settings.paths.get(key)
        if root is None:
            continue
        heads[key] = head_of(root)
        for pattern in mech.record_globs:
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                files[key] += 1
                for taxon in {f"NCBITaxon:{m.decode()}" for m in CURIE.findall(path.read_bytes())}:
                    records_citing[key][taxon] += 1
    with (args.out / "taxon_curies.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["mech", "taxon_id", "records_citing", "in_taxonmech_scope"])
        for key in sorted(records_citing):
            # Deterministic: by records descending, then numeric id, so the file's digest reproduces.
            for taxon, count in sorted(records_citing[key].items(), key=lambda kv: (-kv[1], int(kv[0].split(":")[1]))):
                writer.writerow([key, taxon, count, taxon in scope])
    lines = ["# Every NCBITaxon CURIE in Mech records, against TaxonMech's seed scope", "",
             f"TaxonMech scope: {len(scope)} taxa (curation/seed_scope.tsv at {heads['taxonmech']}).", "",
             "| Mech | HEAD | record files | distinct taxa cited | in scope | outside scope | records citing an outside taxon |",
             "|---|---|---:|---:|---:|---:|---:|"]
    fleet_outside: Counter = Counter()
    mechs_of: dict[str, set] = defaultdict(set)
    for key in manifest.mechs:
        if key in SKIP or key not in heads:
            continue
        cited = records_citing[key]
        inside = sum(1 for t in cited if t in scope)
        outside = {t: c for t, c in cited.items() if t not in scope}
        for t, c in outside.items():
            fleet_outside[t] += c
            mechs_of[t].add(key)
        lines.append(f"| {key} | {heads[key]} | {files[key]} | {len(cited)} | {inside} | {len(outside)} | "
                     f"{sum(outside.values())} |")
    lines += ["", f"## Taxa outside the scope: {len(fleet_outside)} distinct across the fleet", "",
              "| taxon | records citing it | Mechs |", "|---|---:|---|"]
    lines += [f"| {t} | {c} | {', '.join(sorted(mechs_of[t]))} |" for t, c in fleet_outside.most_common(40)]
    (args.out / "summary_all_curies.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
