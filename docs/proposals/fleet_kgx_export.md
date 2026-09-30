# Fleet KGX export: one exporter from the declared graph shapes

**Status:** Draft
**Audience:** claw and Mech maintainers
**Date:** 2026-09-30
**Consolidates:** #276 (standardize the KGX transform), #275 (serialisation and
predicate modelling), #461 (versioned release assets), #358 (which Mechs feed
kg-microbe), #503 / #517 (every Mech's `kgx_export` declaration), and the
per-Mech adoption issues they cite.

## The problem, measured

`kgx_export` is enabled for one Mech of eleven, and no Mech's graph reaches
kg-microbe: its `download.yaml` and `merge.yaml` on `master` (1408e709) name no
Mech, and its only Mech input is MediaIngredientMech's legacy SSSOM lookup
inside `mim_ingredients` (#358). Three Mechs have written their own exporter --
CultureMech (1,148 lines), MediaIngredientMech (654) and CommunityMech (394) --
and none commits or releases a graph (#461: the releases API returns nothing
for any Mech).

#276 declined to generalise a transform from one implementation, correctly:
there was one exporter and no agreed target. Two things have changed since.

1. **The graphs are already read by shared code.** `kg-microbe-graph coverage`
   reads every Mech's causal graphs through a declared shape, and three shapes
   now cover the fleet: `graph_list` (TraitMech and the Mechs that copied it),
   `node_nested_edges` (CommunityMech) and `record_graph` (PathwayMech, #537).
   Measured on each Mech's `origin/main` today, that reader already extracts:

   | Mech | records with a graph | nodes | edges | evidenced edges | nodes grounded |
   |---|---:|---:|---:|---:|---:|
   | ProteinTraitsMech | 39,591 | 348,584 | 372,250 | 372,250 | 341,651 |
   | TraitMech | 626 | 5,434 | 4,684 | 4,684 | 2,133 |
   | PathwayMech | 148 | 3,190 | 4,632 | 4,632 | (ids are CURIEs) |
   | CellStructureMech | 710 | 3,754 | 3,085 | 3,085 | 2,077 |
   | CommunityMech | 371 | 1,495 | 949 | (not declared) | (not declared) |
   | NaturalProductMech | 112 | 599 | 467 | 467 | 429 |
   | HabitatMech | 32 | 407 | 427 | 427 | 33 |
   | AntibioticMech | 16 | 87 | 75 | 75 | 33 |
   | TaxonMech | 0 | 0 | 0 | 0 | 0 |

   About 385,000 nodes and 390,000 edges, nearly every edge carrying evidence.
   The part #276 feared -- one bespoke reader per Mech -- is done and tested.

2. **The target is the contract, not the merged file.** #276 could not target
   kg-microbe's merged graph because it is malformed (#273). It does not need
   to: `kg-microbe-kgx check` (#273) is a shared, tested definition of a
   well-formed graph -- `id` and `category` on nodes, `subject`, `predicate`
   and `object` on edges, Biolink categories and predicates unless a Mech
   declares extra prefixes, clean TSV serialisation. An exporter that passes it
   is correct independently of the merged file's state.

## What is actually hard

Serialising TSV is not. Three modelling gaps are, and the proposal is mostly
about them:

**Predicates are free text.** None of the top predicates in any `graph_list`
Mech is a CURIE. TraitMech has 630 distinct predicate strings, CellStructureMech
590, ProteinTraitsMech 406, HabitatMech 93 ("contributes to", "is part of",
"confers", "selects for"...). Only PathwayMech's six come from a closed enum.

**Node types are Mech-local enums with a shared core.** `BIOLOGICAL_PROCESS`,
`CHEMICAL`, `CELLULAR_LOCALIZATION`, `ENVIRONMENTAL_FACTOR` recur because the
`graph_list` Mechs copied TraitMech's schema, but no shared schema defines them
(`mech_shared.yaml` has no node-type enum).

**Many nodes are ungrounded.** A KGX node id must be a CURIE. HabitatMech
grounds 8% of its graph nodes, TraitMech 39%, CellStructureMech 55%; the rest
have only a record-local id such as `n3`.

## Design

### 1. One exporter in claw: `kg-microbe-kgx export --mech X`

It reads the corpus through the existing `causal_graph_coverage` declaration
(the same shape, globs and fields, so the graph that is measured is the graph
that is exported) and writes `nodes.tsv`, `edges.tsv` and a manifest:

- **Nodes.** A grounded node's id is its grounding. An ungrounded node gets a
  minted, stable CURIE in the Mech's own namespace,
  `<mech>:<record-id>/<node-id>`, and is marked as ungrounded in a column so
  consumers can filter it. Two graph nodes with the same grounding become one
  KGX node; `name` is the node's label, `provided_by` the Mech's `infores:`.
- **Edges.** Subject and object resolve through the same node-id map. `id` is
  a UUID5 of Mech, record and edge, so re-exports are stable. Evidence becomes
  `publications` (PMID/DOI) and `supporting_text` (the quote), as CommunityMech
  and dismech already do; `primary_knowledge_source` is the Mech's `infores:`
  and `knowledge_level` / `agent_type` follow the evidence type.
- **Categories and predicates** come from declared maps, below. Nothing is
  guessed: an unmapped value is exported as `biolink:NamedThing` /
  `biolink:related_to` with the original kept in an `original_category` /
  `original_predicate` column, and counted in the manifest.
- **Validation is the contract.** The exporter runs `kg-microbe-kgx check` on
  its own output and exits nonzero on any finding, so a written graph is a
  checked graph.

### 2. Declared maps, shared where the fleet already agrees

The `kgx_export` capability gains settings: `infores`, `category_map` and
`predicate_map`, and optionally a `node_id_namespace`.

- A **shared default category map** in claw covers the recurring node types
  (`CHEMICAL` → `biolink:ChemicalEntity`, `BIOLOGICAL_PROCESS` →
  `biolink:BiologicalProcess`, `CELLULAR_LOCALIZATION` →
  `biolink:CellularComponent`, `GENE_OR_PROTEIN` → `biolink:GeneOrGeneProduct`,
  ...). A Mech's `category_map` extends or overrides it.
- A **shared predicate normaliser** maps the recurring free-text phrasings
  ("is part of" / "part of" → `biolink:part_of`, "has input" →
  `biolink:has_input`, "inhibits" → `biolink:negatively_regulates`...). The
  long tail stays `biolink:related_to` with the original preserved, and the
  manifest reports what fraction of edges were normalised -- a number each
  Mech can raise by curating predicates, not a silent loss.
- METPO predicates (#275) are declared per Mech: kept with `extra_prefixes`, or
  mapped, rather than decided here.

### 3. Released as artifacts, checked as artifacts

The capability today can only judge a committed `nodes`/`edges` path, which is
why MediaIngredientMech (built in CI) and CommunityMech (release workflow)
cannot enable it with graphs that exist. Two changes:

- A claw **reusable release workflow**, like `label-correspondence-reusable`,
  that a Mech calls on a tag: install claw at the pin, export, check, and
  attach `nodes.tsv.gz`, `edges.tsv.gz` and the manifest (repository, tag,
  commit, claw pin, row counts, normalisation rates, SHA-256) to the GitHub
  release -- #461's acceptance criteria.
- The `kgx_export` contract accepts either a committed path or a **release
  asset**, and the fleet check reads the latest release's assets.

### 4. One kg-microbe transform for every Mech

kg-microbe gets a single `mech_kgx` transform that downloads each opted-in
Mech's release assets by versioned URL and passes them to the merge unchanged
-- the Mech has already produced checked KGX. Which Mechs are inputs is the
per-Mech decision #358 asks for, recorded in the manifest next to the
capability. This is kg-microbe work and lands there, not in claw.

## What this replaces

- The three hand-written exporters. CultureMech's and MediaIngredientMech's
  are not graph-shaped reads of a causal-graph slot -- they model media
  composition and ingredient identity -- so they stay as they are and are
  released through the same workflow, reported alongside. CommunityMech's is
  the parity canary: the shared exporter must reproduce its node and edge
  counts, category and predicate distributions, before it replaces it.
- Eleven per-Mech exporters that #503's adoption issues would otherwise each
  write.

## Order of work

1. **Declarations** -- merge #517 (every Mech's `kgx_export` says adoption is
   pending) and #537 (`record_graph`, so PathwayMech's graph is readable).
2. **Exporter core** with the category and predicate maps, tested offline
   against fixtures in each shape and the contract checker.
3. **Canary: PathwayMech.** Its predicates are a closed enum and its node ids
   are CURIEs, so its export tests the plumbing without the modelling gaps.
   Enable `kgx_export` there first.
4. **Parity: CommunityMech** against its own exporter.
5. **Normalisation for the `graph_list` Mechs**, reporting the normalised
   fraction per Mech; enable where the output passes the contract.
6. **Release workflow and artifact contract** (#461), canary on one Mech.
7. **kg-microbe transform** (#358), outside claw.

## Open questions

- Should ungrounded nodes be exported at all, or only edges between grounded
  nodes? Minting keeps the mechanism; filtering keeps the merged graph to
  shared identifiers. The column lets consumers choose; the default is export.
- Which Biolink version is pinned? #275 measured against 4.3.6.
- ProteinTraitsMech's graph is 97% of the fleet's edges; its redistribution
  boundary (#394, proteintraitsmech#517) must be resolved before its first
  release.
