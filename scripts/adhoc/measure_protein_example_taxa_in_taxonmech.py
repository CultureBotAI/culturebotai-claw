#!/usr/bin/env python3
"""Which taxa do the fleet's protein examples name, and which of them does TaxonMech hold?

Purpose: the fleet's UniProt protein examples each name the organism in which
the protein's role was established. That taxon is the natural first cross-Mech
taxon link. This measures, per Mech, every protein example's taxon and whether
TaxonMech's seed scope (curation/seed_scope.tsv, the list of taxa that are
records) holds it. A taxon outside the scope is a candidate to add; a malformed
taxon is a data problem in the Mech.
Method: walk every record under each Mech's manifest record_globs, parse the
YAML, and treat a mapping as a protein example when it carries an explicit
UniProt key (uniprot_id, uniprot_term, uniprot_accession) or a generic one
(accession, protein_id) whose value is shaped like a UniProtKB accession; a
generic key holding a dataset DOI, a culture-collection number or a MIBiG id
is not a protein. Nothing nested inside a matched example is counted again
(ProteinTraitsMech's trait_occurrences carry the parent's protein id). The
taxon is the first of taxon_id, organism_term, target_organism or organism_id,
as a string or as a mapping with an id. Files whose text mentions none of the
keys are not parsed. TaxonMech itself is skipped: its records are the taxa.
Not covered: PathwayMech's pathway participants, which name proteins as
`identifier: UniProtKB:...` on a different shape.
Inputs: claw's .env (set -a; . ./.env) for the Mech roots; --out DIR.
Outputs: DIR/protein_example_taxa.tsv (one row per example: mech, record path,
record id, slot key, uniprot, taxon id, taxon label, in_taxonmech_scope),
DIR/summary.md (per-Mech counts, the Mech HEADs read, and the most-cited taxa
outside the scope). Read-only; it writes only under DIR.
Not covered either (culturebotai-claw#889): slots that hold a bare accession
string rather than a mapping, such as NaturalProductMech's
`molecular_targets[].protein_examples[]`, `biosynthetic_pathway[].enzyme_id`
and `bioactivities[].target_enzyme`, AntibioticMech's
`resistance_mechanisms[].protein_accession`, CellStructureMech's Complex
Portal participants, and CommunityMech's `kb/taxa/*.yaml`, which lies outside
its manifest record globs. None of those carries a per-example taxon.
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

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.repository_settings import RepositorySettings  # noqa: E402

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
EXPLICIT_KEYS = ("uniprot_id", "uniprot_term", "uniprot_accession")
GENERIC_KEYS = ("accession", "protein_id")
PROTEIN_KEYS = EXPLICIT_KEYS + GENERIC_KEYS
TAXON_KEYS = ("taxon_id", "organism_term", "target_organism", "organism_id")
LABEL_KEYS = ("taxon_label", "taxon_name", "organism_label")
PREFILTER = tuple(key.encode() for key in PROTEIN_KEYS)
NCBITAXON = re.compile(r"^NCBITaxon:[1-9][0-9]*$")
ACCESSION = re.compile(r"^(UniProtKB:)?([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})(-[0-9]+)?$")
SKIP = {"taxonmech"}


def taxon_of(mapping: dict) -> tuple[str, str]:
    for key in TAXON_KEYS:
        value = mapping.get(key)
        if isinstance(value, dict):
            return str(value.get("id") or ""), str(value.get("label") or "")
        if isinstance(value, str):
            label = next((str(mapping[k]) for k in LABEL_KEYS if mapping.get(k)), "")
            return value, label
    return "", ""


def uniprot_of(mapping: dict) -> tuple[str, str]:
    for key in PROTEIN_KEYS:
        value = mapping.get(key)
        if isinstance(value, dict) and value.get("id"):
            value = str(value["id"])
        if not isinstance(value, str) or not value:
            continue
        if key in EXPLICIT_KEYS or ACCESSION.match(value):
            return key, value
    return "", ""


def examples(node, path: str = ""):
    if isinstance(node, dict):
        key, uniprot = uniprot_of(node)
        if key:
            taxon, label = taxon_of(node)
            yield path, key, uniprot, taxon, label
            return
        for name, child in node.items():
            yield from examples(child, f"{path}.{name}" if path else str(name))
    elif isinstance(node, list):
        for child in node:
            yield from examples(child, f"{path}[]")


def record_id(document) -> str:
    if isinstance(document, dict):
        for key in ("identifier", "id", "record_id", "pathway_id", "trait_id"):
            if document.get(key):
                return str(document[key])
    return ""


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
    rows = []
    stats: dict[str, Counter] = defaultdict(Counter)
    for key, mech in manifest.mechs.items():
        if key in SKIP:
            continue
        root = settings.paths.get(key)
        if root is None:
            stats[key]["not_configured"] = 1
            continue
        heads[key] = head_of(root)
        for pattern in mech.record_globs:
            for path in sorted(root.glob(pattern)):
                if not path.is_file():
                    continue
                stats[key]["files"] += 1
                raw = path.read_bytes()
                if not any(marker in raw for marker in PREFILTER):
                    continue
                stats[key]["parsed"] += 1
                try:
                    document = yaml.load(raw, Loader=Loader)
                except yaml.YAMLError as exc:
                    stats[key]["unparseable"] += 1
                    print(f"{key}: {path.relative_to(root)}: {str(exc).splitlines()[0]}", file=sys.stderr)
                    continue
                rid = record_id(document)
                for slot, pkey, uniprot, taxon, label in examples(document):
                    in_scope = taxon in scope
                    rows.append((key, str(path.relative_to(root)), rid, slot, pkey, uniprot, taxon, label, in_scope))
                    stats[key]["examples"] += 1
                    if not taxon:
                        stats[key]["no_taxon"] += 1
                    elif not NCBITAXON.match(taxon):
                        stats[key]["malformed_taxon"] += 1
                    elif in_scope:
                        stats[key]["in_scope"] += 1
                    else:
                        stats[key]["outside_scope"] += 1
    with (args.out / "protein_example_taxa.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["mech", "record_path", "record_id", "slot", "protein_key", "uniprot", "taxon_id",
                         "taxon_label", "in_taxonmech_scope"])
        writer.writerows(rows)
    lines = ["# Protein-example taxa against TaxonMech's seed scope", "",
             f"TaxonMech scope: {len(scope)} taxa (curation/seed_scope.tsv at {heads['taxonmech']}).", "",
             "| Mech | HEAD | files | parsed | examples | distinct taxa | in scope | outside scope | malformed | no taxon |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key in manifest.mechs:
        if key in SKIP:
            continue
        s = stats[key]
        if s.get("not_configured"):
            lines.append(f"| {key} | — | not configured | | | | | | | |")
            continue
        distinct = {r[6] for r in rows if r[0] == key and r[6]}
        lines.append(f"| {key} | {heads[key]} | {s['files']} | {s['parsed']} | {s['examples']} | {len(distinct)} | "
                     f"{s['in_scope']} | {s['outside_scope']} | {s['malformed_taxon']} | {s['no_taxon']} |")
    outside = Counter(r[6] for r in rows if r[6] and NCBITAXON.match(r[6]) and not r[8])
    labels = {t: Counter(r[7] for r in rows if r[6] == t).most_common(1)[0][0] for t in outside}
    mechs_of = defaultdict(set)
    for r in rows:
        if r[6] and not r[8]:
            mechs_of[r[6]].add(r[0])
    lines += ["", f"## Taxa outside the scope: {len(outside)} distinct, {sum(outside.values())} examples", "",
              "| taxon | label | examples | Mechs |", "|---|---|---:|---|"]
    for taxon, count in outside.most_common(40):
        lines.append(f"| {taxon} | {labels[taxon]} | {count} | {', '.join(sorted(mechs_of[taxon]))} |")
    malformed = Counter((r[0], r[6]) for r in rows if r[6] and not NCBITAXON.match(r[6]))
    if malformed:
        lines += ["", "## Taxa that are not NCBITaxon CURIEs", "", "| Mech | value | examples |", "|---|---|---:|"]
        lines += [f"| {m} | `{v}` | {c} |" for (m, v), c in malformed.most_common(30)]
    (args.out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
