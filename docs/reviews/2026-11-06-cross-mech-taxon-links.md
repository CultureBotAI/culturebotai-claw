# Cross-Mech taxon links: what exists, what the records cite, and a plan

**Date:** 2026-11-06
**Question:** do we have a skill or infrastructure to review the TaxonMech links across the Mechs, as we do for adding UniProt protein examples? The starting point proposed was the taxon each protein example names.
**Method:** every claim below was measured this session against the Mech checkouts at the HEADs in the appendix tables (all equal to `origin/main` after a fleet pull the same day), with three scripts under `scripts/adhoc/`:

- `measure_protein_example_taxa_in_taxonmech.py`: every protein example's organism taxon, against TaxonMech's seed scope;
- `measure_all_taxon_curies_in_taxonmech.py`: every `NCBITaxon` CURIE anywhere in a record, the upper bound of link targets;
- `classify_taxa_outside_taxonmech_scope.py`: each taxon outside the scope sorted by domain, kingdom, rank and nearest in-scope ancestor, using the NCBI taxdump snapshot TaxonMech pins.

The summaries they printed are in `2026-11-06-cross-mech-taxon-links/`. Searches for "nothing exists" claims included ignored files.

## 1. Short answer

No. There is no fleet-level mechanism for taxon links. What exists is:

- **HTML handoffs only.** Six Mechs render a "TaxonMech" link on record pages. Five link by a label search (`browse.html?q=<label>`: AntibioticMech, HabitatMech, NaturalProductMech, CMMMech, and CultureMech with `#q=`). That route works, but it is a search, not a record. CommunityMech links by id to `taxa/NCBITaxon_<id>.html`, which does not exist: TaxonMech's per-record route is `pages/taxon.html?id=NCBITaxon:<n>`, and its browse index lists exactly that page for all 626,048 records. The 63,699 slug pages under `pages/taxa/<domain>/` cover about a tenth of the corpus. claw#655 already describes this (sibling routes have no single source and no link check) and proposes routes in the manifest.
- **No slot, no check.** No Mech schema has a link slot whose target is TaxonMech. Four Mechs carry a `related_records` link class (AntibioticMech `CrossCorpusLink`, TraitMech `PathwayContextLink`, CellStructureMech `StructurePathwayLink`, NaturalProductMech `NaturalProductCrossCorpusLink`), and two of them pin the corpus to `^PathwayMech$`. MediaIngredientMech's schema says a protein example's taxon "resolves to a TaxonMech record", but no MIM code checks it. CommunityMech grounds taxa against OAK's NCBITaxon, not TaxonMech. Nothing in claw resolves a taxon to TaxonMech either.
- **TaxonMech has no inbound side.** `TaxonRecord` carries `xrefs`, `discussions`, `datasets` and strain-level `related_records` (`GenomeRelatedRecordLink`), nothing that records which sibling records cite the taxon.

The protein-example analogue the question refers to is also not fleet infrastructure; section 3 measures it.

## 2. What the records cite, and what TaxonMech holds

### 2.1 Protein examples

424,380 protein examples carry a UniProt key across six Mechs (ProteinTraitsMech 420,162; CellStructureMech 2,392; CMMMech 1,198; AntibioticMech 352; TraitMech 210; HabitatMech 66). CultureMech, MediaIngredientMech, CommunityMech, NaturalProductMech, PathwayMech and DUFMech hold none on the protein-example shapes; PathwayMech's proteins are pathway participants, a different shape this measurement does not cover.

| Where the example's taxon falls | examples |
|---|---:|
| in TaxonMech's scope | 72,730 |
| no taxon on the example (ProteinTraitsMech `canonical_examples[]` without `taxon_id`) | 51,388 |
| outside the scope | 300,262 |

### 2.2 The 300,262 outside the scope are mostly not TaxonMech's to hold

The classifier sorts the 3,730 distinct taxa that any record cites outside the scope (1,947 of them on protein examples):

| class | distinct taxa | protein examples | records citing | what a link should do |
|---|---:|---:|---:|---|
| animals, plants, viruses, other non-fungal eukaryotes | 2,192 | 273,918 | 148,849 | resolve to NCBI Taxonomy or the UniProt organism, never TaxonMech |
| strain or isolate whose species is a TaxonMech record | 234 | 25,878 | 17,954 | resolve one rank up to the species record, labelled as such |
| rank above species (genus, family, phylum, domain) | 695 | 0 | 3,886 | never a record by TaxonMech's rule; link a lineage search, or nothing |
| fungal species or strain that no TaxonMech source attests | 468 | 289 | 875 | the only true scope gap |
| retired NCBI id, merged into a taxon that is a record | 147 | 166 | 279 | a data fix in the citing Mech |
| id absent from the taxdump | 2 | 21 | 22 | a data fix in the citing Mech |

Two facts shape the plan:

- **Bacteria and archaea are complete.** Not one bacterial or archaeal species or strain cited by any Mech is outside TaxonMech's scope, except the 120 retired ids and ranks above species. TaxonMech's inventory is kg-microbe's NCBITaxon extract (the Bacteria and Archaea subtrees, 640,815 taxa attested as `ncbitaxon`) plus taxa attested by GTDB, GOLD, Madin, LPSN, BacDive, MediaDive and BactoTraits. Eukaryotes enter only through those sources, which is why the 234 resolvable strains and the 468 unattested taxa are almost all fungi.
- **Protein examples name strains; TaxonMech records species.** `Saccharomyces cerevisiae S288C` (NCBITaxon:559292) alone is 23,459 protein examples and 15,684 records across eight Mechs; its species NCBITaxon:4932 is a record, and that record lists no strains. The same holds for *S. pombe* 972h-, *C. albicans* SC5314, *A. fumigatus* Af293, *A. nidulans* FGSC A4 and 229 more. A taxon link that insists on an exact record would miss all of them; one that resolves to the species, and says so, catches 25,878 examples.

### 2.3 Per Mech

Records citing a taxon, by where that taxon falls (from `summary_classified.md`):

| Mech | in scope | resolvable one rank up | retired id | above species | microbial, not attested | outside TaxonMech's domain | not in taxdump |
|---|---:|---:|---:|---:|---:|---:|---:|
| antibioticmech | 543 | 71 | 0 | 70 | 14 | 43 | 0 |
| cellstructuremech | 1028 | 296 | 0 | 418 | 8 | 143 | 0 |
| cmmmech | 466 | 8 | 0 | 13 | 15 | 3 | 0 |
| communitymech | 977 | 2 | 1 | 729 | 8 | 49 | 0 |
| culturemech | 55 | 2 | 1 | 0 | 0 | 3 | 0 |
| dufmech | 182 | 3 | 0 | 0 | 0 | 36 | 0 |
| habitatmech | 11627 | 19 | 71 | 984 | 100 | 427 | 1 |
| mediaingredientmech | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| naturalproductmech | 4692 | 219 | 40 | 1063 | 445 | 666 | 0 |
| pathwaymech | 351 | 86 | 0 | 9 | 0 | 0 | 0 |
| proteintraitsmech | 55606 | 17225 | 166 | 4 | 277 | 147467 | 21 |
| traitmech | 788 | 4 | 0 | 9 | 8 | 11 | 0 |

Data findings this surfaces, each a candidate issue in the Mech named:

- **ProteinTraitsMech:** 51,388 `canonical_examples[]` entries have no `taxon_id` (for example `UniProtKB:P07327`, `ADH1A_HUMAN`, source `CURATOR`, "ExPASy ENZYME DR cross-reference"); 166 record citations use a retired NCBI id (90 distinct, e.g. NCBITaxon:2093792, now 3121606); 21 cite NCBITaxon:3470597, which the 2026-09-13 taxdump does not contain.
- **HabitatMech:** 71 citations of retired ids (42 distinct, e.g. NCBITaxon:57 *Polyangium sp.*, now 3409587); one citation of NCBITaxon:2738467, absent from the taxdump.
- **NaturalProductMech:** 40 citations of retired ids (20 distinct, e.g. NCBITaxon:65497 *Actinoalloteichus caeruleus*, now 2893586).
- **CultureMech and CommunityMech:** one retired id each.
- **CommunityMech:** the `taxa/NCBITaxon_<id>.html` route in `community.html` resolves to nothing.

TaxonMech already carries the merge table these need (`data/raw/ncbi_merged_ids.tsv`, 101,006 rows from the pinned taxdump); no Mech reads it.

## 3. The protein-example mechanism, reviewed

The question asked for the taxon work to mirror the protein-example work. Measured, that work is per-Mech, not fleet infrastructure:

- **Eight drifted copies of one skill.** `add-uniprot-protein-examples/SKILL.md` exists in MediaIngredientMech (92 lines), CommunityMech (74), AntibioticMech (156), TraitMech (84), HabitatMech (80), NaturalProductMech (169), TaxonMech (91) and PathwayMech (75); all eight digests differ. CultureMech has `curate-protein-examples` (120), DUFMech `dufmech-protein-examples` (80) and `ground-causal-graph-proteins` (129). claw's canonical skill templates (`src/kg_microbe_skills/canonical/`, 12 templates) include none of these, and claw's catalogue (43 skills) has no protein-example entry. `unify-skills` is the designated route for exactly this situation and has not been applied.
- **One cross-Mech audit, in one Mech.** PathwayMech's `cross-mech-protein-links` skill, `just cross-mech-proteins` and `conf/sibling_mechs.yaml` (dotted slot paths per sibling, read from each schema on 2026-10-05) are the only cross-Mech protein link check. The registry lives in PathwayMech and is PathwayMech-centric. DUFMech's `src/dufmech/cross_mech.py` (963 lines) is a second, DUF-centric finder. Nothing in claw walks protein slots across the fleet.
- **The workflow stage is text, not a check.** Stage 3 `protein_examples` in claw's parent template (`src/kg_microbe_workflows/templates/mech-cycle.yaml`, byte-identical to the vendored copies) is one sentence. Twelve Mech profiles override it with one identical sentence of their own; AIMech overrides it with an applicability audit, the one pattern that produced a measurable verdict (`research/validation/20261104T091000Z-protein-examples-applicability-audit.md`). No stage asks whether an example's taxon resolves anywhere.
- **Schemas disagree on the taxon.** The organism field is `taxon_id` in five Mechs, `organism_term.id` in CultureMech, `target_organism.id` in CMMMech, and absent on 51,388 ProteinTraitsMech examples. AntibioticMech's `ProteinExample` has no `evidence` slot (evidence sits on the parent target); the other five typed examples carry one. Only CultureMech's `validation/protein_examples.py` checks an example's taxon against the record's own organism, and MediaIngredientMech states an `organism_scope` lineage rule its code does not enforce.

These are the same shape as the taxon gap: slots exist per Mech, claw does not know where they are, and no check reads across them. The taxon plan below therefore builds the shared piece first and lets protein examples reuse it.

## 4. Plan

Phase 0 is this PR. Each later phase is its own PR, under its own repository's rules, and nothing below edits a Mech.

**Phase 1, claw: declare taxon slots and check them (fleet-wide, read-only).**
Add a `taxon_links` capability to `src/kg_microbe_fleet/fleet.yaml` with per-Mech `settings.slots` (dotted record paths, the `corpus_statistics.fields` pattern), and a `kg-microbe-links taxa --mech X` command that walks `record_globs`, reads those slots, and reports each cited taxon as one of: record, species-of-strain (with the ancestor), above-species, out-of-domain, retired (with the merge target), unattested-microbial, or absent. It reads TaxonMech's `curation/seed_scope.tsv`, `data/raw/ncbi_merged_ids.tsv` and the pinned taxdump, so the verdict is the same on a laptop and in CI, and it never calls NCBI. The three adhoc scripts here are its prototype; the measurement in section 2 is its acceptance test (the numbers must reproduce). A `cross-mech-taxon-links` fleet skill wraps it.

**Phase 2, routes (claw#655).** Put each Mech's published routes in the manifest (`site_base`, record route with its query parameter, search route). TaxonMech's record route is `pages/taxon.html?id=NCBITaxon:<n>`; its search route is `pages/browse.html?q=<label>`. Then each Mech renderer links by id when the taxon is a record or resolves to one, and by lineage search when it is above species; CommunityMech's dead route goes first. A claw check that every emitted sibling URL uses a declared route closes the loop.

**Phase 3, data fixes in the Mechs.** The retired and absent ids (section 2.3) and ProteinTraitsMech's missing `taxon_id`s. Each is one issue in its Mech; the Phase 1 report is the evidence and the re-check.

**Phase 4, TaxonMech.** Two decisions for its owner. (a) Whether to show "cited by" on a taxon page, computed at a sibling pin the way NaturalProductMech computes `related_records`, rather than stored in records the seeder regenerates. (b) Whether a UniProt reference proteome counts as attestation, which would admit the 468 unattested fungal taxa that sibling records cite (289 protein examples, 875 records) through the existing inventory route; the seeder refuses any scope row no inventory attests, so this cannot be a `seed_scope.tsv` edit alone.

**Phase 5, protein examples, on the same base.** Register protein-example slots beside the taxon slots in the manifest (PathwayMech's `conf/sibling_mechs.yaml` is the draft), move `cross-mech-protein-links` from a PathwayMech skill to a fleet skill over that registry, and canonicalise `add-uniprot-protein-examples` through `unify-skills` so the eight copies become one template with per-Mech adapters. Resolving each example's taxon becomes part of the protein-example check, which is where the question started.

## 5. What was not measured

PathwayMech participants and causal-graph node `xrefs` that name proteins (a different shape); the HTML handoffs' live behaviour on GitHub Pages (local `pages/` only); whether every retired id's merge target is the taxon the record meant.
