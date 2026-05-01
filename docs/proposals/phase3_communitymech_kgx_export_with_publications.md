# Phase 3: CommunityMech KGX export with publications (Koza blueprint)

**Status:** Draft
**Audience:** CommunityMech maintainers
**Date:** 2026-05-01
**Source pattern:** dismech `src/dismech/export/kgx_export.py` + `_format_evidence` (lines 45-88) + `.github/workflows/kgx-release.yaml`

## Goal

Make CommunityMech's ~35 microbial-community records emit a **valid
KGX TSV graph** on every release, with biolink-compliant edge
predicates and `publications`/`supporting_text` fields populated from
each evidence claim. Today CommunityMech has no graph export; downstream
kg-microbe consumes nothing from it.

CommunityMech is the right starting point (smallest record count, no
existing export to migrate, mature evidence infrastructure planned via
Phase 1) and produces a reusable blueprint that MIM and CultureMech
can adopt later.

## Scope

**In scope:**
- Koza-based KGX emitter (nodes.tsv + edges.tsv)
- Biolink Association class selection per edge type
- Evidence → `publications` and `supporting_text` propagation
- Deterministic UUID5 edge IDs
- `just kgx-export` recipe
- GitHub Actions release-attached artifact

**Out of scope:**
- MIM / CultureMech KGX export (later phases — this is the blueprint)
- Live SPARQL endpoint or dynamic API
- Graph database loading (downstream consumer's job)

## Critical files

| Path | Kind | Reason |
|---|---|---|
| `CommunityMech/CommunityMech/src/communitymech/export/kgx_export.py` | NEW | ~400 LoC; ports dismech's `kgx_export.py` |
| `CommunityMech/CommunityMech/src/communitymech/export/koza_transform.py` | NEW | Koza ingest config + transform fn |
| `CommunityMech/CommunityMech/conf/koza/communitymech.yaml` | NEW | Source config |
| `CommunityMech/CommunityMech/conf/koza/transform.yaml` | NEW | Transform config |
| `CommunityMech/CommunityMech/justfile` | EXTEND | `kgx-export` recipe |
| `CommunityMech/CommunityMech/.github/workflows/kgx-release.yaml` | NEW | Triggered on release; uploads artifact |
| `CommunityMech/CommunityMech/output/kgx/{nodes,edges}.tsv` | OUTPUT | Generated artifact |

## Edge schema design

CommunityMech needs domain-specific Association types. Map record
relationships to biolink:

| CommunityMech relation | Biolink Association | Predicate | Object range |
|---|---|---|---|
| Community ↔ member microbe | `OrganismToOrganismAssociation` | `biolink:has_part` | NCBITaxon |
| Community ↔ environment | `OrganismToEnvironmentAssociation` | `biolink:occurs_in` | ENVO |
| Community ↔ medium (links to CultureMech) | `OrganismToOrganismCohabitationAssociation` | `biolink:occurs_in` | CultureMech ID |
| Community ↔ phenotype/function | `OrganismToPhenotypicFeatureAssociation` | `biolink:has_phenotype` | (HP / GO) |
| Community ↔ literature | (carried as `publications` on every above edge) | n/a | PMID/DOI |

(Refine the table once each community YAML's actual slots are
inventoried — first execution step.)

## Execution order

1. **Inventory community YAML slots**: walk
   `CommunityMech/CommunityMech/data/` (or wherever community YAMLs live);
   produce `workspace/reports/communitymech_slot_inventory.md`. This
   pins down exact edge shapes before code is written.
2. **Decide Koza vs. custom**: dismech uses Koza (reuse). If
   CommunityMech's pyproject.toml doesn't pin Koza, add it. Confirm
   Koza version dismech uses; pin same.
3. **Port `kgx_export.py`**: copy dismech's file; replace
   disorder/phenotype association types with the table above; keep
   `_format_evidence()` verbatim — it already produces
   `publications` + `supporting_text` from EvidenceItem (Phase 1
   schema).
4. **Koza configs**: write `conf/koza/communitymech.yaml` (source
   declaration: format=yaml, files=`data/communities/*.yaml`) and
   `conf/koza/transform.yaml` (column mapping → KGX).
5. **Justfile recipe**: `kgx-export` runs `koza transform --source
   conf/koza/communitymech.yaml --output output/kgx/`.
6. **Test fixture**: pick 3 community YAMLs with the most evidence,
   run export, manually verify nodes.tsv and edges.tsv against
   biolink-validator.
7. **Release workflow**: `.github/workflows/kgx-release.yaml` triggers
   on release publish: runs `just kgx-export`, gzips outputs, attaches
   to release as artifacts. Mirrors dismech's exact workflow.
8. **Document downstream contract**: add a section to
   CommunityMech/README.md describing the artifact location, format,
   and biolink categories used so kg-microbe (and others) can ingest.

## Validation gates

Before merge of the export feature:

- KGX validator (`kgx validate output/kgx/nodes.tsv output/kgx/edges.tsv`)
  passes
- Every edge has `category` set to a biolink Association class
- Every edge with evidence has `publications` populated (zero if no
  evidence; never null)
- Edge IDs are stable across runs (UUID5; same input → same ID)
- Node IDs use canonical CURIE prefixes (NCBITaxon, ENVO, MIM, etc.)

## Verification

After step 7:
- Cut a test release tag; workflow runs; release page shows
  `community_kgx_nodes.tsv.gz` and `community_kgx_edges.tsv.gz`
  artifacts
- Download + inspect: edge counts ≥ slot inventory's expected count
- kg-microbe attempts ingestion (smoke test) without error

## Effort estimate

| Step | Hours |
|---|---:|
| Slot inventory | 4 |
| Koza setup + version pin | 2 |
| Port `kgx_export.py` + adapt to community schema | 16 |
| Koza configs | 4 |
| Justfile + tests | 4 |
| Release workflow | 4 |
| Documentation | 2 |
| **Total** | **~36** |

## Why CommunityMech first

- Smallest record count (35) — fast iteration
- No legacy export to migrate
- Phase 1 (evidence schema) is the only upstream dependency, and
  CommunityMech's CLAUDE.md already mentions planned KGX export
- Resulting `kgx_export.py` becomes a copy-paste blueprint for MIM
  (Phase 5) and CultureMech (deferred — 10,657 records will need
  performance tuning beyond simple port)

## What's deferred to later phases

- MIM KGX export (Phase 5; depends on Phase 1 evidence backfill being
  meaningful)
- CultureMech KGX export (post-Phase 5; performance work)
- Cross-repo unified KGX merge (kg-microbe consumer responsibility)
