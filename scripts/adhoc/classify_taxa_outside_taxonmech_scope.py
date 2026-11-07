#!/usr/bin/env python3
"""Classify the taxa that Mech records cite but TaxonMech does not hold.

Purpose: a taxon outside TaxonMech's seed scope is not one kind of thing. It
may be a strain whose species is a record (a link can resolve one rank up),
a genus or higher rank (never a record by TaxonMech's rule), an animal, plant
or virus outside the microbial sources TaxonMech attests from, a fungus or
protist that those sources simply never attested, or an identifier NCBI has
merged or deleted. The plan for cross-Mech taxon links differs for each, so
this sorts them.
Method: read the taxa the two measurement scripts found outside the scope,
and look each up in the NCBI taxdump snapshot TaxonMech pins
(conf/ncbi_taxdump.yaml, data/source_snapshots/...tar.gz): nodes.dmp for rank
and parent, names.dmp for the scientific name, merged.dmp for retired ids.
TaxonMech's own attested inventory cannot do this, because it holds only the
scope and its lineage. Walk parents to find the domain, the kingdom for
eukaryotes, the nearest ancestor in the scope, and the class: species,
below-species, higher, or not in the taxdump. A retired id is always reported
as retired, whatever its merge target is; an id absent from nodes.dmp is looked
up in delnodes.dmp so a deleted id is told from one newer than the snapshot.
Microbial means bacterial, archaeal, or a eukaryote outside Metazoa and
Viridiplantae, because TaxonMech holds protists as well as fungi.
Inputs: claw's .env (set -a; . ./.env) for TAXONMECH_ROOT; --measure DIR
holding protein_example_taxa.tsv and taxon_curies.tsv; --out DIR.
Outputs: DIR/outside_scope_classified.tsv (taxon, name, merged_into, domain,
kingdom, rank, class, nearest in-scope ancestor and its name, protein
examples, records citing it, Mechs) and DIR/summary_classified.md, which names
the digests of the two input TSVs (culturebotai-claw#916); rows are written in
a deterministic order so the TSV's own digest reproduces.
Read-only; writes only under DIR. The tarball is read twice (nodes, then the
names of the ids that turned out to be needed).
Serves: the cross-Mech taxon-link assessment, culturebotai-claw PR 881 (and
#655 for routes). Written 2026-11-06; retired ids whose target is not a record,
protists, deleted ids and the mutually exclusive outcome table added for
#884-#887 the same day.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plugins.repository_settings import RepositorySettings  # noqa: E402

DOMAINS = {2: "Bacteria", 2157: "Archaea", 2759: "Eukaryota", 10239: "Viruses"}
KINGDOMS = {4751: "Fungi", 33090: "Viridiplantae", 33208: "Metazoa"}


def dmp_rows(tar_path: Path, member: str):
    with tarfile.open(tar_path, "r:gz") as tar:
        handle = tar.extractfile(member)
        assert handle is not None, member
        for raw in handle:
            yield raw.decode("utf-8", "replace").rstrip("\t|\n").split("\t|\t")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    settings = RepositorySettings.from_environment()
    taxonmech = settings.paths.get("taxonmech")
    if taxonmech is None:
        raise SystemExit(f"taxonmech: {settings.errors.get('taxonmech', 'not configured')}")
    snapshot = yaml.safe_load((taxonmech / "conf/ncbi_taxdump.yaml").read_text(encoding="utf-8"))
    tar_path = taxonmech / snapshot["path"]
    with (taxonmech / "curation/seed_scope.tsv").open(encoding="utf-8") as handle:
        scope = {int(row["identifier"].split(":")[1]) for row in csv.DictReader(handle, delimiter="\t")}

    examples: Counter = Counter()
    records: Counter = Counter()
    mechs: dict[int, set] = defaultdict(set)
    with (args.measure / "protein_example_taxa.tsv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["taxon_id"].startswith("NCBITaxon:") and row["in_taxonmech_scope"] == "False":
                taxon = int(row["taxon_id"].split(":")[1])
                examples[taxon] += 1
                mechs[taxon].add(row["mech"])
    with (args.measure / "taxon_curies.tsv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["in_taxonmech_scope"] == "False":
                taxon = int(row["taxon_id"].split(":")[1])
                records[taxon] += int(row["records_citing"])
                mechs[taxon].add(row["mech"])
    cited = set(examples) | set(records)

    merged = {int(old): int(new) for old, new in dmp_rows(tar_path, "merged.dmp")}
    deleted = {int(fields[0]) for fields in dmp_rows(tar_path, "delnodes.dmp")}
    nodes: dict[int, tuple[int, str]] = {}
    for fields in dmp_rows(tar_path, "nodes.dmp"):
        nodes[int(fields[0])] = (int(fields[1]), fields[2])

    def chain(taxon: int) -> list[int]:
        out, seen = [], set()
        while taxon in nodes and taxon not in seen and taxon != 1:
            seen.add(taxon)
            out.append(taxon)
            taxon = nodes[taxon][0]
        return out

    resolved = {t: merged.get(t, t) for t in cited}
    chains = {t: chain(resolved[t]) for t in cited}
    needed = set(resolved.values()) | {a for c in chains.values() for a in c}
    names = {}
    for fields in dmp_rows(tar_path, "names.dmp"):
        if fields[3] == "scientific name" and int(fields[0]) in needed:
            names[int(fields[0])] = fields[1]

    rows = []
    for taxon in sorted(cited, key=lambda t: (-(examples[t] + records[t]), t)):  # deterministic; ties by id
        current, lineage = resolved[taxon], chains[taxon]
        merged_into = f"NCBITaxon:{current}" if current != taxon else ""
        if current not in nodes:
            klass = "deleted" if current in deleted else "not-in-taxdump"
            rows.append((f"NCBITaxon:{taxon}", "", merged_into, "not in taxdump", "", "", klass, "", "",
                         examples[taxon], records[taxon], ", ".join(sorted(mechs[taxon]))))
            continue
        rank = nodes[current][1]
        domain = next((DOMAINS[a] for a in lineage if a in DOMAINS), "other")
        kingdom = next((KINGDOMS[a] for a in lineage if a in KINGDOMS), "")
        ancestor = next((a for a in lineage[1:] if a in scope), 0)
        if current in scope:
            klass = "in scope after merge"
        elif merged_into:
            klass = "retired, target not a record"
        elif rank == "species":
            klass = "species"
        elif any(nodes[a][1] == "species" for a in lineage[1:]):
            klass = "below-species"
        else:
            klass = "higher"
        rows.append((f"NCBITaxon:{taxon}", names.get(current, ""), merged_into, domain, kingdom, rank, klass,
                     f"NCBITaxon:{ancestor}" if ancestor else "", names.get(ancestor, "") if ancestor else "",
                     examples[taxon], records[taxon], ", ".join(sorted(mechs[taxon]))))
    header = ["taxon_id", "name", "merged_into", "domain", "kingdom", "rank", "class", "nearest_in_scope_ancestor",
              "ancestor_name", "protein_examples", "records_citing", "mechs"]
    with (args.out / "outside_scope_classified.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)

    cells: dict[tuple, list] = defaultdict(list)
    for r in rows:
        cells[(r[3], r[4] or "-", r[6])].append(r)
    digests = {name: hashlib.sha256((args.measure / name).read_bytes()).hexdigest()[:16]
               for name in ("protein_example_taxa.tsv", "taxon_curies.tsv")}
    lines = ["# Taxa outside TaxonMech's scope, by domain, kingdom and rank class", "",
             f"{len(rows)} distinct taxa cited outside the scope; scope {len(scope)}; taxdump {snapshot['snapshot']} "
             f"({len(nodes)} nodes).", "",
             "Inputs (SHA-256, first 16 hex): " + ", ".join(f"`{n}` {d}" for n, d in digests.items())
             + "; the Mech HEADs are those the two scan summaries record.", "",
             "| domain | kingdom | class | distinct taxa | with an in-scope ancestor | protein examples | records citing |",
             "|---|---|---|---:|---:|---:|---:|"]
    for key, cell in sorted(cells.items(), key=lambda kv: -sum(r[9] + r[10] for r in kv[1])):
        lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {len(cell)} | {sum(1 for r in cell if r[7])} | "
                     f"{sum(r[9] for r in cell)} | {sum(r[10] for r in cell)} |")
    resolvable = [r for r in rows if r[7] and not r[2]]  # a retired id is counted as retired, not here
    lines += ["", f"## Resolvable one rank up: {len(resolvable)} taxa whose nearest in-scope ancestor is a record "
                  f"({sum(r[9] for r in resolvable)} protein examples, {sum(r[10] for r in resolvable)} records)", "",
              "| taxon | name | rank | ancestor | ancestor name | protein examples | records | Mechs |",
              "|---|---|---|---|---|---:|---:|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[5]} | {r[7]} | {r[8]} | {r[9]} | {r[10]} | {r[11]} |" for r in resolvable[:30]]
    candidates = [r for r in rows if r[6] in ("species", "below-species") and not r[7]
                  and (r[3] in ("Bacteria", "Archaea") or (r[3] == "Eukaryota" and r[4] not in ("Metazoa", "Viridiplantae")))]
    lines += ["", f"## Microbial species or strains with no in-scope ancestor (scope candidates): {len(candidates)} "
                  f"({sum(r[9] for r in candidates)} protein examples, {sum(r[10] for r in candidates)} records)", "",
              "| taxon | name | domain | rank | protein examples | records | Mechs |", "|---|---|---|---|---:|---:|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[3]}{'/' + r[4] if r[4] else ''} | {r[5]} | {r[9]} | {r[10]} | {r[11]} |"
              for r in candidates[:40]]
    # One outcome per taxon, mutually exclusive, in this order; the tables below are built from it.
    outcome = {}
    for r in rows:
        if r[6] in ("in scope after merge", "retired, target not a record"):
            outcome[r[0]] = "retired id"
        elif r[6] in ("deleted", "not-in-taxdump"):
            outcome[r[0]] = "not in taxdump"
        elif r[7]:
            outcome[r[0]] = "resolvable one rank up"
        elif r[6] == "higher":
            outcome[r[0]] = "above species"
        elif r[3] in ("Bacteria", "Archaea") or (r[3] == "Eukaryota" and r[4] not in ("Metazoa", "Viridiplantae")):
            outcome[r[0]] = "microbial, not attested"
        else:
            outcome[r[0]] = "outside TaxonMech's domain"
    columns = ["in scope", "resolvable one rank up", "retired id", "above species", "microbial, not attested",
               "outside TaxonMech's domain", "not in taxdump"]
    totals: dict[str, list[int]] = {c: [0, 0, 0] for c in columns[1:]}
    for r in rows:
        cell = totals[outcome[r[0]]]
        cell[0] += 1
        cell[1] += r[9]
        cell[2] += r[10]
    lines += ["", "## Outcomes, one per taxon", "", "| outcome | distinct taxa | protein examples | records citing |",
              "|---|---:|---:|---:|"]
    lines += [f"| {c} | {totals[c][0]} | {totals[c][1]} | {totals[c][2]} |" for c in columns[1:]]
    lines.append(f"| total | {sum(v[0] for v in totals.values())} | {sum(v[1] for v in totals.values())} | "
                 f"{sum(v[2] for v in totals.values())} |")
    per_mech: dict[str, Counter] = defaultdict(Counter)
    with (args.measure / "taxon_curies.tsv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            key = "in scope" if row["in_taxonmech_scope"] == "True" else outcome.get(row["taxon_id"], "not in taxdump")
            per_mech[row["mech"]][key] += int(row["records_citing"])
    lines += ["", "## Per Mech: record citations of a taxon, by where that taxon falls", "",
              "| Mech | " + " | ".join(columns) + " |", "|---|" + "---:|" * len(columns)]
    for mech in sorted(per_mech):
        lines.append(f"| {mech} | " + " | ".join(str(per_mech[mech][c]) for c in columns) + " |")
    (args.out / "summary_classified.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
