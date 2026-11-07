---
name: cross-mech-taxon-links
description: "Judge every taxon a Mech's records cite against what TaxonMech holds: a retired NCBI id, a record, a strain resolved to its nearest ancestor that is a record, a rank above species, a taxon outside TaxonMech's domain, an unplaced metagenome or unclassified sequence, an unattested microbe, or an id absent from the pinned taxdump. Runs kg-microbe-links taxa over the slots each Mech declares in the fleet manifest's taxon_links capability. Read-only; reads TaxonMech's checkout and fetches nothing."
category: quality
requires_database: false
requires_internet: false
version: 1.0.0
tags: [taxon, taxonmech, links, cross-mech, quality, fleet, read-only, reporting]
---

# Cross-Mech taxon links

Use from the CLAW checkout. The question is whether the taxa a Mech's records
name resolve in TaxonMech, and what to do when they do not. The answer is
`kg-microbe-links taxa`, and this skill is how to run it, read it, and act on
it. It never edits a record: a finding becomes an issue in the Mech that owns
the record, under that Mech's rules.

## What is read, and from where

The Mechs to check and the slots to read come from the manifest. The
`taxon_links` capability in `src/kg_microbe_fleet/fleet.yaml` lists, per Mech,
the dotted slot paths in which its records name a taxon (`[]` visits each list
element, as in `causal_graphs[].nodes[].protein_examples[].taxon_id`). Those
paths were measured from the records, not guessed from the schema, so a path
the schema allows but no record uses is not listed; when a Mech adds one,
the declaration changes with it. A taxon in prose or in a citation is not a
link and is not read; a mixed identifier slot is declared where a taxon in it
is a link, and its other identifiers are counted, never judged.

```python
from kg_microbe_fleet import load_fleet_manifest

for key, mech in load_fleet_manifest().mechs.items():
    capability = mech.capabilities.get("taxon_links")
    if capability is not None and capability.is_enabled:
        print(key, capability.settings["slots"])
```

TaxonMech's side is read from its checkout, resolved like every other root
(`TAXONMECH_ROOT`, claw's `.env`, or `--taxonmech-root`): `TaxonMech/curation/seed_scope.tsv`
(the taxa that are records), `TaxonMech/data/raw/ncbi_merged_ids.tsv` (retired
ids and their targets), `TaxonMech/data/raw/ncbitaxon_taxa.tsv` (rank and parent
of every taxon a TaxonMech source attests) and, only for taxa outside that
inventory, the NCBI taxdump snapshot `TaxonMech/conf/ncbi_taxdump.yaml` pins. Nothing is fetched, so the
verdict is the same on a laptop and in CI. The taxdump's nodes and names are
each read at most once per process, and only when a cited taxon needs them;
each read costs tens of seconds.

## Run

```bash
uv run kg-microbe-links taxa --mech habitatmech              # one Mech, JSON on stdout
uv run kg-microbe-links taxa --mech habitatmech --strict     # exit 1 on retired, absent, malformed, or an unreadable record
uv run kg-microbe-links taxa --all                           # every Mech with an enabled declaration
uv run kg-microbe-links taxa --mech traitmech --root "$SNAP" # a `git archive origin/main` snapshot
```

ProteinTraitsMech holds about 430,000 records and takes a few minutes;
`--sample N` reads the first N in sorted order for a quick look, and the
report says it was sampled.

## Read the verdicts

| verdict | what it means | what to do |
|---|---|---|
| `record` | TaxonMech's scope holds the taxon | link the record page, `pages/taxon.html?id=NCBITaxon:<n>` |
| `species_of_strain` | below species; its nearest ancestor that is a record (usually its species) holds it | link that record, and say the cited taxon is a strain of it |
| `above_species` | genus or higher, never a record by TaxonMech's rule | a lineage search, or no link |
| `outside_domain` | animal, plant or virus | resolve to NCBI Taxonomy or UniProt, not TaxonMech |
| `unplaced` | an entry at species rank or below under no cellular domain and not a virus: a metagenome, an uncultured or unclassified sequence, a vector | resolve to NCBI Taxonomy; nothing in the fleet owns it |
| `unattested_microbial` | bacterium, archaeon, fungus or protist that no TaxonMech source attests | the only kind a TaxonMech scope change could admit; report to TaxonMech's owner |
| `retired` | NCBI merged the id into another; the current id and its own verdict are given (judged first: TaxonMech's own scope still lists fourteen retired ids) | fix the record to cite the current id |
| `absent` | the pinned taxdump has no such id | find the intended taxon from the record's source |
| `malformed` | the value is `NCBITaxon:`-prefixed but not a CURIE | fix the record |

A value in a declared slot that does not start with `NCBITaxon:` is another
identifier (a GTDB or CHEBI id in a mixed slot); it is counted under the slot
as `other_identifiers` and is never a finding.

## Act

- `findings` lists every retired, absent or malformed value with its record
  path and slot. File them in the Mech that owns the record, one issue per
  Mech, with the table; the issues the 2026-11-06 cross-Mech taxon-link
  assessment filed (claw PR 881) show the shape.
- `resolvable` lists the strains resolved to their nearest ancestor that is a record, most-cited
  first, with that ancestor. That is what a renderer needs to link one rank up.
- `unattested_microbial` is the list for TaxonMech's owner.
- The report is deterministic JSON. Keep one per Mech per run under
  `workspace/` when comparing releases; the artifact never belongs in a Mech.

## Boundaries

Read-only. No Mech checkout is modified, no branch switched, no network call
made. Changing a record, a renderer or TaxonMech's scope is downstream work
under the cross-repository checklist in `AGENTS.md`, as its own change.
