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
A record is a file git tracks (`git ls-files`) under a record glob: a
gitignored backup that matches the glob is not one (culturebotai-claw#1069).
A scoped id that TaxonMech's own merge table (data/raw/ncbi_merged_ids.tsv,
the taxdump's merged.dmp) retires is reported outside the scope, since a link
to it resolves to a retired id (culturebotai-claw#1067); the classifier then
reports it as retired. Sums over taxa are record citations, one per
record-taxon pair, and the summary says so beside the count of distinct
records that cite any outside taxon (culturebotai-claw#1068).
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
Written 2026-11-06; tracked files, retired scope ids and the citation
columns since 2026-11-09 (#1067, #1068, #1069).
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


def tracked_files(root: Path) -> set[str]:
    """Paths git tracks, relative to the root; existence is decided by git, not the filesystem."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
    return {part.decode("utf-8", "surrogateescape") for part in out.split(b"\0") if part}


def retired_scope_ids(taxonmech: Path, scope: set[str]) -> set[str]:
    """Scope ids that TaxonMech's merge table retires; a link to one resolves to a retired id."""
    with (taxonmech / "data/raw/ncbi_merged_ids.tsv").open(encoding="utf-8") as handle:
        return {row["old_taxon_id"] for row in csv.DictReader(handle, delimiter="\t")} & scope


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
    retired = retired_scope_ids(taxonmech, scope)
    scoped = scope - retired
    heads = {"taxonmech": head_of(taxonmech)}
    records_citing: dict[str, Counter] = defaultdict(Counter)
    records_outside: Counter = Counter()
    files: Counter = Counter()
    for key, mech in manifest.mechs.items():
        if key in SKIP:
            continue
        root = settings.paths.get(key)
        if root is None:
            continue
        heads[key] = head_of(root)
        tracked = tracked_files(root)
        for pattern in mech.record_globs:
            for path in sorted(root.glob(pattern)):
                if not path.is_file() or path.relative_to(root).as_posix() not in tracked:
                    continue
                files[key] += 1
                taxa = {f"NCBITaxon:{m.decode()}" for m in CURIE.findall(path.read_bytes())}
                for taxon in taxa:
                    records_citing[key][taxon] += 1
                if any(taxon not in scoped for taxon in taxa):
                    records_outside[key] += 1
    with (args.out / "taxon_curies.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["mech", "taxon_id", "records_citing", "in_taxonmech_scope"])
        for key in sorted(records_citing):
            # Deterministic: by records descending, then numeric id, so the file's digest reproduces.
            for taxon, count in sorted(records_citing[key].items(), key=lambda kv: (-kv[1], int(kv[0].split(":")[1]))):
                writer.writerow([key, taxon, count, taxon in scoped])
    lines = ["# Every NCBITaxon CURIE in Mech records, against TaxonMech's seed scope", "",
             f"TaxonMech scope: {len(scope)} taxa (curation/seed_scope.tsv at {heads['taxonmech']}), "
             f"{len(retired)} of them retired by data/raw/ncbi_merged_ids.tsv and counted outside it.", "",
             "A record file is one git tracks under a record glob. A record citation is one record citing one "
             "taxon, so a record citing three outside taxa is three citations and one record.", "",
             "| Mech | HEAD | record files | distinct taxa cited | in scope | outside scope | "
             "record citations of an outside taxon | records citing an outside taxon |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    fleet_outside: Counter = Counter()
    mechs_of: dict[str, set] = defaultdict(set)
    for key in manifest.mechs:
        if key in SKIP or key not in heads:
            continue
        cited = records_citing[key]
        inside = sum(1 for t in cited if t in scoped)
        outside = {t: c for t, c in cited.items() if t not in scoped}
        for t, c in outside.items():
            fleet_outside[t] += c
            mechs_of[t].add(key)
        lines.append(f"| {key} | {heads[key]} | {files[key]} | {len(cited)} | {inside} | {len(outside)} | "
                     f"{sum(outside.values())} | {records_outside[key]} |")
    lines += ["", f"## Taxa outside the scope: {len(fleet_outside)} distinct across the fleet", "",
              "| taxon | records citing it | Mechs |", "|---|---:|---|"]  # per taxon, a count of records
    top = sorted(fleet_outside.items(), key=lambda kv: (-kv[1], int(kv[0].split(":")[1])))[:40]  # ties by id
    lines += [f"| {t} | {c} | {', '.join(sorted(mechs_of[t]))} |" for t, c in top]
    (args.out / "summary_all_curies.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
