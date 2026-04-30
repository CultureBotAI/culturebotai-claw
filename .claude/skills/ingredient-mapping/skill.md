---
name: ingredient-mapping
description: Import a new ingredient/compound source into MIM with a documented source→resolver→emit cascade — turns external rows (kg-microbe placeholders, CultureBotHT compounds + media, FEBA panels, MIM curation queue) into properly-typed MIM YAMLs with CHEBI/NCIT/cas:/UNMAPPED primaries, preserving provenance.
category: integration
requires_database: true
requires_internet: true
version: 1.0.0
tags: [ingredient, chebi, ncit, cas-rn, kgmicrobe.compound, oak, ols, pubchem, mim, import]
---

# Ingredient Mapping Skill

## Purpose

Standard pipeline for taking ingredient/compound rows from an
**external source** and turning them into MIM ingredient YAMLs with
the most authoritative ontology mapping the data supports.

This skill consolidates the previously-scattered scripts:

| Old script | Source | Now |
|---|---|---|
| `propose_chebi_for_unmapped.py` | MIM curation queue | superseded by `--source mim-queue` |
| `curate_unmapped_kgm_antibiotics.py` | kg-microbe `unmapped_compounds.tsv` | superseded by `--source kgm-unmapped` |
| `integrate_culturebotht_ingredients.py` | CultureBotHT compounds + media | superseded by `--source culturebotht` |
| `cas_chebi_lookup_pubchem.py` | OAK CAS-xref + PubChem fallback | now an internal resolver phase |
| `add_remaining_culturebotht.py` | Same as `culturebotht` | now `--include-fallback-tiers` flag |

The originals still work — they're kept for reproducibility — but new
imports should go through `scripts/import_ingredients.py`.

## When to use

- A new external dataset needs to land in MIM (e.g. another high-throughput
  growth assay panel, a curated metabolite list, a kg-microbe placeholder
  refresh).
- A previously-imported source has new rows (incremental refresh).
- Adding new source CSVs/JSON/TSV — extend `import_ingredients.py` with
  one new source loader and the resolver does the rest.

## Architecture

```
                  ┌── Source loaders (--source <X>) ──┐
                  │                                   │
   kg-microbe     ├── kgm-unmapped                ────┤
                  │     unmapped_compounds.tsv         │
                  │                                   │
   CultureBotHT   ├── culturebotht                ────┤── Stream of
                  │     compounds_to_cas.csv           │   Candidate(name, cas?,
                  │     consolidated_media.json         │      synonyms?, panels?,
                  │                                   │      media_uses?, source_id)
   MIM-internal   ├── mim-queue                    ────┤
                  │     mim_curation_queue.tsv         │
                  └── (extensible — drop a new        │
                      Source class in for new feeds)  │
                                  │
                                  ▼
                  Resolver cascade (priority order)
                  ┌──────────────────────────────────┐
                  │ 1. Already in MIM (label/CAS) │  → SKIP
                  │ 2. OLS exact label match      │  → CHEBI HIGH
                  │ 3. OLS exact synonym match    │  → CHEBI HIGH
                  │ 4. OAK CHEBI CAS-xref         │  → CHEBI HIGH (CAS-grounded)
                  │ 5. PubChem CID→synonyms       │  → CHEBI MEDIUM
                  │ 6. OLS exact match in NCIT    │  → NCIT HIGH
                  │ 7. Has CAS-RN, no CHEBI/NCIT  │  → cas: FALLBACK_REGISTRY
                  │ 8. (anything else)            │  → UNMAPPED_NNNN
                  └──────────────────────────────────┘
                                  │
                                  ▼
                  Emit MIM YAML
                  ┌──────────────────────────────────┐
                  │ MAPPED:                          │
                  │   data/ingredients/mapped/<Slug>.yaml │
                  │   identifier=<primary>           │
                  │   ontology_mapping with evidence │
                  │     ─ FEBA/Hans80 panel notes    │
                  │     ─ source CSV row reference    │
                  │     ─ media usage counts          │
                  │   chemical_properties.cas_rn      │
                  │                                  │
                  │ UNMAPPED:                        │
                  │   data/ingredients/unmapped/UNMAPPED_NNNN.yaml │
                  │   identifier=UNMAPPED_NNNN       │
                  │   notes=...                      │
                  └──────────────────────────────────┘
```

## Resolver tiers — confidence ladder

| Tier | What hits this tier | Primary | mapping_quality | Action |
|---|---|---|---|---|
| HIGH (CHEBI label-exact) | OLS returns a non-obsolete CHEBI whose `rdfs:label` equals the source name | `CHEBI:N` | `EXACT_MATCH` | auto-create MIM YAML |
| HIGH (CHEBI synonym-exact) | The source name is in OLS's `oio:hasExactSynonym` list for a non-obsolete CHEBI | `CHEBI:N` | `EXACT_MATCH` | auto-create |
| HIGH (CAS-xref) | OAK's local CHEBI sqlite has a `cas:NNN-NN-N` xref matching the source CAS-RN | `CHEBI:N` | `EXACT_MATCH` | auto-create |
| MEDIUM (PubChem) | PubChem CID→synonyms list contains a `CHEBI:N` synonym | `CHEBI:N` | `LEXICAL_MATCH` | auto-create with `--accept-medium` flag |
| HIGH (NCIT) | OLS returns a non-obsolete NCIT term with the matching label/synonym | `NCIT:N` | `EXACT_MATCH` | auto-create |
| FALLBACK_REGISTRY | Source has a valid CAS-RN, but no CHEBI/NCIT exists yet | `cas:NNN-NN-N` | `FALLBACK_REGISTRY` | auto-create (in mapped/, status=MAPPED) |
| UNMAPPED | No CAS-RN, no ontology hit | `UNMAPPED_NNNN` | (none) | auto-create in unmapped/, status=UNMAPPED |

The `cas:` and `UNMAPPED_NNNN` tiers ensure **every** source row lands
somewhere — the import is total. No row is dropped.

## Provenance conventions

Each emitted YAML's `ontology_mapping.evidence[].notes` and
`curation_history` capture:

- **Source repo + file**: `Imported from CultureBotHT compounds_to_cas.csv`
- **Source row identifier**: the original CURIE if there was one
  (`mediadive.ingredient:2436`, `kgmicrobe.compound:foo`)
- **Panel memberships** (CultureBotHT-only): `FEBA/Hans80 panels: FEBA_carbon, Hans80Anti`
- **Media usage** (CultureBotHT-only): `Used in N CultureBot media; samples: ...`
- **Resolver method**: `OAK CAS-xref` / `OLS label-exact` / `PubChem CID→synonyms` / `cas: fallback (no CHEBI exists)`
- **CAS-RN** (always when source has it): goes into `chemical_properties.cas_rn`

## Run it

```bash
# Standard import — auto-creates MAPPED + UNMAPPED records
just import-ingredients --source culturebotht

# Or directly
python scripts/import_ingredients.py --source kgm-unmapped --apply

# Dry-run a source first
python scripts/import_ingredients.py --source culturebotht
# (no --apply: prints plan, writes no YAMLs)

# Skip PubChem fallback for speed
python scripts/import_ingredients.py --source culturebotht --apply --no-pubchem

# Accept stem-overlap-verified MEDIUM hits too
python scripts/import_ingredients.py --source mim-queue --apply --accept-medium
```

After import, **always** rebuild + republish the SSSOM:

```bash
just build-sssom        # picks up new YAMLs
just review-sssom-team  # release-grade audit (or review-sssom for fast)
just publish-sssom      # promote to MIM/mappings/
```

Then trigger downstream sync:

```bash
cd ../kg-microbe && poetry run python scripts/consolidate_chemical_mappings.py
```

## Source-specific contracts

### `--source kgm-unmapped`

- **Reads**: `kg-microbe/docs/metatraits/unmapped_compounds.tsv`
- **Format**: 4 columns (`placeholder_id`, `label_token`, `edge_count`, `predicate`)
- **Provenance**: `source_id` = the `kgmicrobe.compound:*` placeholder
- **Special**: rows that fall to UNMAPPED tier go to `mapped/` with
  `kgmicrobe.compound:` primary (NOT to `unmapped/`) — kg-microbe's
  placeholder IS a usable identifier.

### `--source culturebotht`

- **Reads**: `CultureBotHT/data/raw/google_sheets/compounds_to_cas.csv`
  + `CultureBotHT/data/consolidated/consolidated_media.json`
- **Format**: 1,392-row compound master + 691-medium ingredient lists
- **Provenance**: panel columns (`Hans80Anti`, `Hans80metals`,
  `FEBA_carbon`, `FEBA_nitrogen`, `FEBA_stress`, `All_star`) preserved
  in evidence notes.
- **Two-pass**: compound master first, then media-only fresh names.

### `--source mim-queue`

- **Reads**: `workspace/reports/mim_curation_queue.tsv` (produced by
  the audit pipeline as the union of mediadive-unmapped +
  kgmicrobe.compound:* not yet in MIM)
- **Provenance**: source_id from the queue's `source_id` column.
- **Skips**: rows already with `already_in_mim=yes`.

## Adding a new source

1. Subclass `Source` in `scripts/import_ingredients.py`:

   ```python
   class MyNewSource(Source):
       name = "mynew"
       def candidates(self) -> Iterable[Candidate]:
           # yield Candidate(name=..., cas=..., source_id=..., ...) per row
   ```

2. Register in `_SOURCES` dict at the bottom of the script.
3. Document the contract above.

That's it — the resolver and YAML emitter are source-agnostic.

## Outputs

| Path | Role |
|---|---|
| `data/ingredients/mapped/<Slug>.yaml` (in MIM) | New MAPPED records (CHEBI/NCIT/cas: primary) |
| `data/ingredients/unmapped/UNMAPPED_NNNN.yaml` (in MIM) | UNMAPPED placeholders |
| `workspace/reports/import_summary_<source>.md` | Per-import summary (counts, sample rows, resolver-method breakdown) |
| `workspace/reports/import_queue_<source>.tsv` | Rows that hit no resolver (always empty for `kgm-unmapped` and `culturebotht` since fallback tiers cover them; useful for `mim-queue`) |
| `workspace/cache/ols_cas_cache.json` | Shared OLS CAS-RN cache across runs |
| `workspace/cache/cas_to_chebi.json` | Pre-built OAK CHEBI CAS-xref index |
| `workspace/cache/pubchem_cas_chebi.json` | Pre-built PubChem CID→CHEBI cache |

## Dependencies

- Python 3.x + pyyaml
- OAK (`runoak` / oaklib) with local CHEBI sqlite
- Internet access (OLS4, PubChem REST, optional)

## Related skills

- `cas-rn-integration` — narrower; enriches existing MIM YAMLs with
  CAS-RN. This skill SUPERSEDES it for new-record creation but
  cas-rn-integration is still useful for back-filling CAS-RNs on
  records that lacked them at creation time.
- `feba-integration` — earlier specialized FEBA pipeline; this skill
  subsumes its CHEBI-mapping logic but `feba-integration` retains
  the CultureMech-specific applies.
- `cross-repo-sync` — the downstream propagation step; run after
  `just publish-sssom` so kg-microbe's consolidator picks up new
  rows.
- `publish-sssom` — the release lifecycle this feeds into.
- `synonym-review` / `team-review-sssom` — release gate for the
  republished SSSOM.

## Operational tips

- **Never run --apply on a stale local CHEBI**. If OAK's
  `~/.data/oaklib/chebi.db` is more than a release-cycle old, you'll
  miss real CHEBI hits and get more `cas:`/`UNMAPPED_NNNN` than
  necessary. Refresh with `rm ~/.data/oaklib/chebi.db && runoak -i sqlite:obo:chebi info CHEBI:15377` (the lookup re-downloads).
- **Slug collisions** are idempotent guards — the script skips them
  rather than overwrite. Look at `workspace/reports/import_summary_<source>.md`
  for the full skip list.
- **The PubChem fallback is slow** (1-2 sec per CAS due to NCBI rate
  limit). Use `--no-pubchem` if you need a fast sketch.
