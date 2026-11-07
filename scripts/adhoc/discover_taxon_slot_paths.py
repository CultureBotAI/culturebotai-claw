#!/usr/bin/env python3
"""Which record slots, per Mech, hold an NCBITaxon CURIE? The input to the taxon_links declarations.

Purpose: the taxon_links capability declares, per Mech, the dotted slot paths a
link check reads (the corpus_statistics.fields pattern). Those paths must come
from the records, not from guessing at schemas: a slot the schema allows but no
record uses is noise, and a path the schema does not name (a nested
sub-object) is the kind of thing a guess misses.
Method: walk every record under each Mech's manifest record_globs, parse the
YAML, and record the dotted path (keys joined by `.`, list items as `[]`) of
every string value that is exactly an NCBITaxon CURIE, with how many records
and distinct taxa use it. A CURIE inside a longer string (prose, a lineage
string) is counted separately as `embedded`, since a link check should not
read prose. Files whose text lacks `NCBITaxon:` are not parsed.
Inputs: claw's .env (set -a; . ./.env) for the Mech roots; --out DIR.
Outputs: DIR/taxon_slot_paths.tsv (mech, path, kind, records, occurrences,
distinct taxa) and DIR/taxon_slot_paths.md with the proposed `slots:` list per
Mech. Read-only; writes only under DIR.
Serves: the taxon_links capability, Phase 1 of the cross-Mech taxon-link
assessment in culturebotai-claw PR 881. Written 2026-11-06.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.repository_settings import RepositorySettings  # noqa: E402

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
EXACT = re.compile(r"^NCBITaxon:[0-9]+$")
EMBEDDED = re.compile(r"NCBITaxon:[0-9]+")
SKIP = {"taxonmech"}


def values(node, path: str = ""):
    if isinstance(node, dict):
        for key, child in node.items():
            yield from values(child, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for child in node:
            yield from values(child, f"{path}[]")
    elif isinstance(node, str):
        if EXACT.match(node):
            yield path, "exact", node
        else:
            for found in EMBEDDED.findall(node):
                yield path, "embedded", found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = load_fleet_manifest()
    settings = RepositorySettings.from_environment()
    records: dict[tuple, set] = defaultdict(set)
    occurrences: Counter = Counter()
    taxa: dict[tuple, set] = defaultdict(set)
    files: Counter = Counter()
    for key, mech in manifest.mechs.items():
        if key in SKIP:
            continue
        root = settings.paths.get(key)
        if root is None:
            continue
        for pattern in mech.record_globs:
            for path in sorted(root.glob(pattern)):
                if not path.is_file():
                    continue
                files[key] += 1
                raw = path.read_bytes()
                if b"NCBITaxon:" not in raw:
                    continue
                try:
                    document = yaml.load(raw, Loader=Loader)
                except yaml.YAMLError as exc:
                    print(f"{key}: {path.relative_to(root)}: {str(exc).splitlines()[0]}", file=sys.stderr)
                    continue
                for slot, kind, taxon in values(document):
                    cell = (key, slot, kind)
                    records[cell].add(str(path.relative_to(root)))
                    occurrences[cell] += 1
                    taxa[cell].add(taxon)
    rows = sorted(((k[0], k[1], k[2], len(records[k]), occurrences[k], len(taxa[k])) for k in occurrences),
                  key=lambda r: (r[0], r[2], -r[3], r[1]))
    with (args.out / "taxon_slot_paths.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["mech", "path", "kind", "records", "occurrences", "distinct_taxa"])
        writer.writerows(rows)
    lines = ["# Record slots holding an NCBITaxon CURIE, per Mech", ""]
    for key in manifest.mechs:
        if key in SKIP or key not in files:
            continue
        mine = [r for r in rows if r[0] == key]
        lines += [f"## {key} ({files[key]} record files)", ""]
        exact = [r for r in mine if r[2] == "exact"]
        if exact:
            lines += ["| path | records | occurrences | distinct taxa |", "|---|---:|---:|---:|"]
            lines += [f"| `{r[1]}` | {r[3]} | {r[4]} | {r[5]} |" for r in exact]
            lines += ["", "proposed `slots:`", "", "```yaml", "slots:"] + [f"  - {r[1]}" for r in exact] + ["```", ""]
        else:
            lines += ["no slot holds an NCBITaxon CURIE", ""]
        embedded = [r for r in mine if r[2] == "embedded"]
        if embedded:
            lines += ["CURIEs inside longer strings (not link slots):", ""]
            lines += [f"- `{r[1]}`: {r[3]} records, {r[5]} distinct taxa" for r in embedded] + [""]
    (args.out / "taxon_slot_paths.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
