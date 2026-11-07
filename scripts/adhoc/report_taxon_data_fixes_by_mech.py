#!/usr/bin/env python3
"""Per Mech, the taxon citations that need a data fix, with the records that carry them.

Purpose: the cross-Mech taxon-link assessment
(docs/reviews/2026-11-06-cross-mech-taxon-links.md) found records citing
retired NCBI ids (merged into a taxon that is a TaxonMech record), ids absent
from the pinned taxdump, and ProteinTraitsMech canonical examples with no
taxon. Each becomes an issue in its Mech; an issue needs the exact ids, the
merge targets, and record paths, which the assessment's summaries do not list.
Method: read the classifier's outside_scope_classified.tsv and the measurement
TSVs, then walk each Mech's manifest record_globs once, scanning file text for
the target ids, to collect up to three record paths per id.
Inputs: claw's .env (set -a; . ./.env) for the Mech roots; --classified PATH
(outside_scope_classified.tsv); --curies PATH (taxon_curies.tsv); --examples
PATH (protein_example_taxa.tsv from the tightened run); --out DIR.
Outputs: DIR/data_fixes_by_mech.md, printed too. Read-only; writes only under DIR.
Serves: the Phase 3 issues of the taxon-link plan. Written 2026-11-06.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.repository_settings import RepositorySettings  # noqa: E402

SAMPLES = 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classified", type=Path, required=True)
    parser.add_argument("--curies", type=Path, required=True)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment()

    fixes: dict[str, dict[str, dict]] = defaultdict(dict)  # mech -> taxon -> row
    with args.classified.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["class"] in ("in scope after merge", "not-in-taxdump"):
                for mech in row["mechs"].split(", "):
                    fixes[mech][row["taxon_id"]] = row
    citing: dict[str, dict[str, int]] = defaultdict(dict)
    with args.curies.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            citing[row["mech"]][row["taxon_id"]] = int(row["records_citing"])
    taxonless: list[tuple[str, str]] = []
    with args.examples.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["mech"] == "proteintraitsmech" and row["slot"] == "canonical_examples[]" and not row["taxon_id"]:
                taxonless.append((row["record_path"], row["uniprot"]))

    lines = ["# Taxon citations needing a data fix, per Mech", ""]
    for mech in sorted(fixes):
        root = settings.paths.get(mech)
        if root is None:
            lines += [f"## {mech}: not configured locally", ""]
            continue
        targets = {t: re.compile(re.escape(t).encode() + rb"(?![0-9])") for t in fixes[mech]}
        samples: dict[str, list[str]] = defaultdict(list)
        for pattern in manifest.mechs[mech].record_globs:
            for path in sorted(root.glob(pattern)):
                if not path.is_file():
                    continue
                raw = path.read_bytes()
                if b"NCBITaxon:" not in raw:
                    continue
                for taxon, regex in targets.items():
                    if len(samples[taxon]) < SAMPLES and regex.search(raw):
                        samples[taxon].append(str(path.relative_to(root)))
        lines += [f"## {manifest.mechs[mech].display_name} ({manifest.mechs[mech].github})", "",
                  "| cited id | name | status | records citing | sample records |", "|---|---|---|---:|---|"]
        for taxon, row in sorted(fixes[mech].items(), key=lambda kv: -citing[mech].get(kv[0], 0)):
            status = (f"merged into {row['merged_into']}" if row["merged_into"] else "absent from the taxdump")
            lines.append(f"| {taxon} | {row['name'] or '(no current name)'} | {status} | "
                         f"{citing[mech].get(taxon, 0)} | {', '.join(f'`{p}`' for p in samples[taxon])} |")
        lines.append("")
    lines += ["## ProteinTraitsMech canonical examples with no taxon_id", "",
              f"{len(taxonless)} `canonical_examples[]` entries carry a `protein_id` and no `taxon_id`. First {SAMPLES}:", ""]
    lines += [f"- `{path}`: `{uniprot}`" for path, uniprot in taxonless[:SAMPLES]]
    (args.out / "data_fixes_by_mech.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
