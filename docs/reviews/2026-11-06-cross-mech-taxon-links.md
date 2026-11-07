# Cross-Mech taxon links: what exists, what the records cite, and a plan

**Date:** 2026-11-06
**Question:** do we have a skill or infrastructure to review the TaxonMech links across the Mechs, as we do for adding UniProt protein examples? The starting point proposed was the taxon each protein example names.
**Method:** every claim below was measured this session against the Mech checkouts at the HEADs the appendix tables record; the fleet was pulled to `origin/main` that morning, three Mechs (CommunityMech, HabitatMech, CMMMech) advanced during the day, and every scan was re-run at the HEADs recorded, so the three summaries describe one fleet state. Four scripts under `scripts/adhoc/`:

- `measure_protein_example_taxa_in_taxonmech.py`: every protein example's organism taxon, against TaxonMech's seed scope;
- `measure_all_taxon_curies_in_taxonmech.py`: every `NCBITaxon` CURIE anywhere in a record, the upper bound of link targets;
- `classify_taxa_outside_taxonmech_scope.py`: each taxon outside the scope sorted by domain, kingdom, rank and nearest in-scope ancestor, using the NCBI taxdump snapshot TaxonMech pins.

The summaries they printed are in `2026-11-06-cross-mech-taxon-links/`, and `report_taxon_data_fixes_by_mech.py` turned the retired and deleted ids into the per-Mech tables the Phase 3 issues carry (`data_fixes_by_mech.md` there). Searches for "nothing exists" claims included ignored files; the published-site routes were checked with HTTP HEAD requests on 2026-11-06.

## 1. Short answer

No. There is no fleet-level mechanism for taxon links. What exists is:

- **HTML handoffs only, and every one of them is broken on the published site.** Six Mechs render a "TaxonMech" link on record pages. Four link a label search at `https://culturebotai.github.io/TaxonMech/browse.html?q=<label>` (AntibioticMech `record.html`, HabitatMech `habitat.html`, NaturalProductMech `record.html`, CMMMech `material.html`); CultureMech links `https://culturebotai.github.io/TaxonMech/#q=<label>`; CommunityMech links by id to `taxa/NCBITaxon_<id>.html`. Checked live on 2026-11-06: `/TaxonMech/browse.html` returns 404 and `/TaxonMech/taxa/NCBITaxon_562.html` returns 404, because the site publishes only `index.html` (a redirect to `pages/index.html`) and `pages/`; `/TaxonMech/pages/browse.html` and `/TaxonMech/pages/taxon.html?id=NCBITaxon:562` return 200. So the search route is `pages/browse.html?q=<label>`, the per-record route is `pages/taxon.html?id=NCBITaxon:<n>` (the browse index lists exactly that page for all 626,048 records), and the 63,699 slug pages under `pages/taxa/<domain>/` cover about a tenth of the corpus. CultureMech's link reaches the landing page through the redirect, and `pages/index.html` loads only `theme-toggle.js` and reads no fragment, so the `#q=` performs no search; CultureMech's browser page (`app/browser.html:771`) emits the dead `browse.html?q=` URL as well. claw#655 already lists `/TaxonMech/browse.html` among the handoffs that 404, and proposes routes in the manifest.
- **No slot, no check.** No Mech schema has a link slot whose target is TaxonMech. Four Mechs carry a `related_records` link class (AntibioticMech `CrossCorpusLink`, TraitMech `PathwayContextLink`, CellStructureMech `StructurePathwayLink`, NaturalProductMech `NaturalProductCrossCorpusLink`), and two of them pin the corpus to `^PathwayMech$`. MediaIngredientMech's schema says a protein example's taxon "resolves to a TaxonMech record", but no MIM code checks it. CommunityMech grounds taxa against OAK's NCBITaxon, not TaxonMech. Nothing in claw resolves a taxon to TaxonMech either.
- **TaxonMech has no inbound side.** `TaxonRecord` carries `xrefs`, `discussions`, `datasets` and strain-level `related_records` (`GenomeRelatedRecordLink`), nothing that records which sibling records cite the taxon.

The protein-example analogue the question refers to is also not fleet infrastructure; section 3 measures it.

## 2. What the records cite, and what TaxonMech holds

### 2.1 Protein examples

424,434 protein examples carry a UniProt key across six Mechs (ProteinTraitsMech 420,162; CellStructureMech 2,392; CMMMech 1,198; AntibioticMech 385; TraitMech 210; HabitatMech 87); 373,046 of them name a taxon. The other seven hold none on the shape measured, a mapping with a UniProt key and a taxon beside it; the protein-holding slots the walker skipped are listed in section 5, with which of them carry a taxon.

| Where the example's taxon falls | examples |
|---|---:|
| in TaxonMech's scope | 72,782 |
| no taxon on the example (ProteinTraitsMech `canonical_examples[]` without `taxon_id`) | 51,388 |
| outside the scope | 300,264 |

### 2.2 The 300,264 outside the scope are mostly not TaxonMech's to hold

The classifier sorts the 3,730 distinct taxa that any record cites outside the scope (1,947 of them on protein examples) into classes that are mutually exclusive, a retired id counting as retired whatever else is true of its merge target:

| class | distinct taxa | protein examples | records citing | what a link should do |
|---|---:|---:|---:|---|
| animals, plants, viruses and unclassified or metagenome sequences | 2,087 | 273,777 | 148,635 | resolve to NCBI Taxonomy or the UniProt organism, never TaxonMech |
| strain or isolate whose species is a TaxonMech record | 222 | 25,868 | 17,935 | resolve one rank up to the species record, labelled as such |
| rank above species (genus, family, phylum, domain) | 690 | 0 | 3,274 | never a record by TaxonMech's rule; link a lineage search, or nothing |
| fungal or protist species or strain that no TaxonMech source attests | 548 | 416 | 1,051 | the only true scope gap; TaxonMech holds 732 non-fungal eukaryote records, so a protist is its to hold |
| retired NCBI id (147 merged into a record, 34 into a taxon that is not one) | 181 | 182 | 345 | a data fix in the citing Mech, where the id sits in a slot rather than a note |
| id deleted from NCBI's taxonomy (in `delnodes.dmp`) | 2 | 21 | 22 | a data fix in the citing Mech |

Two facts shape the plan:

- **Bacteria and archaea are complete.** Not one bacterial or archaeal species or strain cited by any Mech is outside TaxonMech's scope, except retired ids and ranks above species. TaxonMech's inventory is kg-microbe's NCBITaxon extract (the Bacteria and Archaea subtrees, 640,815 taxa attested as `ncbitaxon`) plus taxa attested by GTDB, GOLD, Madin, LPSN, BacDive, MediaDive and BactoTraits. Eukaryotes enter only through those sources, which is why the 222 resolvable strains are almost all fungi, and the 548 unattested taxa are 459 fungi and 89 protists.
- **Protein examples name strains; TaxonMech records species.** `Saccharomyces cerevisiae S288C` (NCBITaxon:559292) alone is 23,459 protein examples and 15,684 records across eight Mechs; its species NCBITaxon:4932 is a record, and that record lists no strains. The same holds for *S. pombe* 972h-, *C. albicans* SC5314, *A. fumigatus* Af293, *A. nidulans* FGSC A4 and 217 more. A taxon link that insists on an exact record would miss all of them; one that resolves to the species, and says so, catches 25,868 examples.

### 2.3 Per Mech

Records citing a taxon, by where that taxon falls (from `summary_classified.md`):

| Mech | in scope | resolvable one rank up | retired id | above species | microbial, not attested | outside TaxonMech's domain | not in taxdump |
|---|---:|---:|---:|---:|---:|---:|---:|
| antibioticmech | 543 | 71 | 0 | 70 | 15 | 42 | 0 |
| cellstructuremech | 1028 | 296 | 0 | 418 | 41 | 110 | 0 |
| cmmmech | 466 | 8 | 0 | 13 | 16 | 2 | 0 |
| communitymech | 988 | 2 | 2 | 731 | 13 | 44 | 0 |
| culturemech | 55 | 2 | 1 | 0 | 0 | 3 | 0 |
| dufmech | 182 | 3 | 0 | 0 | 0 | 36 | 0 |
| habitatmech | 11640 | 19 | 87 | 976 | 104 | 415 | 1 |
| mediaingredientmech | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| naturalproductmech | 4692 | 219 | 76 | 1044 | 452 | 642 | 0 |
| pathwaymech | 351 | 86 | 0 | 9 | 0 | 0 | 0 |
| proteintraitsmech | 55606 | 17225 | 179 | 4 | 396 | 147335 | 21 |
| traitmech | 788 | 4 | 0 | 9 | 14 | 5 | 0 |

These counts come from a text scan that cannot tell a slot from a note. The slot-declared check that Phase 1 builds (`kg-microbe-links taxa`, PR 897) was run on the same checkouts to settle which retired ids are citations; the bullets say what it found.

Data findings this surfaces, each a candidate issue in the Mech named:

- **ProteinTraitsMech:** 179 record citations use a retired NCBI id (98 distinct, e.g. NCBITaxon:2093792, now 3121606), and 21 cite NCBITaxon:3470597, deleted from NCBI's taxonomy; the slot check confirms them in `canonical_examples[].taxon_id` (203 occurrences in 199 records, 99 distinct ids). Separately, 51,388 `canonical_examples[]` entries have no `taxon_id` (for example `UniProtKB:P07327`, `ADH1A_HUMAN`, source `CURATOR`, "ExPASy ENZYME DR cross-reference"); the schema allows that, since `taxon_id` is optional on `CanonicalExample` alone among the fleet's typed examples, so this is a policy decision for ProteinTraitsMech rather than a defect.
- **HabitatMech:** 87 record citations of retired ids (49 distinct, e.g. NCBITaxon:57 *Polyangium sp.*, now 3409587), and one of NCBITaxon:2738467, deleted; the slot check confirms them in `characteristic_taxa[].taxon_id` (88 occurrences in 81 records, 50 distinct ids).
- **CommunityMech:** two by the text scan. One is a curation-history note describing its own replacement; the other, NCBITaxon:1434019, merged into NCBITaxon:74032, a genus, sits in five slots of `kb/communities/Coscinodiscus_Synthetic_Community.yaml`, which the slot check confirms.
- **NaturalProductMech and CultureMech:** 76 and 1 by the text scan, none in a slot. NaturalProductMech's are `notes:` lines its seeder writes to record the pre-merge id beside the current one, which it already cites; CultureMech's is curator prose explaining the synonymy. Neither is a defect.
- **Every Mech with a handoff:** the TaxonMech links in AntibioticMech, HabitatMech, NaturalProductMech, CMMMech and CommunityMech return 404 on the published site (section 1); CultureMech's reaches a landing page that reads no fragment, and its browser page emits the dead URL too.

TaxonMech already carries the merge table these need (`data/raw/ncbi_merged_ids.tsv`, 101,006 rows from the pinned taxdump). NaturalProductMech reads NCBI's `merged.dmp` in its own seeder; no other Mech, and nothing in claw, reads either.

## 3. The protein-example mechanism, reviewed

The question asked for the taxon work to mirror the protein-example work. Measured, that work is per-Mech, not fleet infrastructure:

- **Eight drifted copies of one skill.** `add-uniprot-protein-examples/SKILL.md` exists in MediaIngredientMech (92 lines), CommunityMech (74), AntibioticMech (156), TraitMech (84), HabitatMech (80), NaturalProductMech (169), TaxonMech (91) and PathwayMech (75); all eight digests differ. CultureMech has `curate-protein-examples` (120), DUFMech `dufmech-protein-examples` (80) and `ground-causal-graph-proteins` (129). claw's canonical skill templates (`src/kg_microbe_skills/canonical/`, 12 templates) include none of these, and claw's catalogue (43 skills) has no protein-example entry. `unify-skills` is the designated route for exactly this situation and has not been applied.
- **Two cross-Mech audits, each in one Mech, unaware of each other.** ProteinTraitsMech's `proteintraitsmech-cross-mech-proteins` skill and `scripts/cross_mech_proteins.py` (2,562 lines: scan, check and audit, reading sibling records from git objects at a pinned commit, with `data/cross_mech/manifest.json` pinning claw's `fleet.yaml` and all thirteen siblings' record globs; 16,082 mentions, 2,602 distinct proteins, in the roles EXAMPLE, TARGET, GRAPH_NODE, REFERENCE, CROSSWALK and SUBSTRATE) is the larger, and the closer base for a fleet check. PathwayMech's `cross-mech-protein-links` skill, `just cross-mech-proteins` and `conf/sibling_mechs.yaml` (dotted slot paths per sibling, read from each schema on 2026-10-05) is the other, PathwayMech-centric. DUFMech's `src/dufmech/cross_mech.py` (963 lines) is a DUF-centric finder. The two slot registries disagree with each other, and nothing in claw walks protein slots across the fleet.
- **The workflow stage is text, not a check.** Stage 3 `protein_examples` in claw's parent template (`src/kg_microbe_workflows/templates/mech-cycle.yaml`, byte-identical to the vendored copies) is one sentence. Thirteen Mech profiles override it with one identical sentence of their own; AIMech overrides it with an applicability audit, the one pattern that produced a measurable verdict (`research/validation/20261104T091000Z-protein-examples-applicability-audit.md`). No stage asks whether an example's taxon resolves anywhere.
- **Schemas disagree on the taxon.** The organism field is `taxon_id` in five Mechs, `organism_term.id` in CultureMech, `target_organism.id` in CMMMech, and absent on 51,388 ProteinTraitsMech examples. AntibioticMech's `ProteinExample` and ProteinTraitsMech's `CanonicalExample` have no `evidence` slot (the first keeps evidence on the parent target, the second a `reference` and a `source`); the other six typed examples carry one. `CanonicalExample` is also the only typed example whose `taxon_id` is optional, which is why 51,388 examples lack one and still conform. Only CultureMech's `src/culturemech/validation/protein_examples.py` checks an example's taxon against the record's own organism, and MediaIngredientMech states an `organism_scope` lineage rule its code does not enforce.

These are the same shape as the taxon gap: slots exist per Mech, claw does not know where they are, and no check reads across them. The taxon plan below therefore builds the shared piece first and lets protein examples reuse it.

## 4. Plan

Phase 0 is this PR. Each later phase is its own PR, under its own repository's rules, and nothing below edits a Mech.

**Phase 1, claw: declare taxon slots and check them (fleet-wide, read-only).**
Add a `taxon_links` capability to `src/kg_microbe_fleet/fleet.yaml` with per-Mech `settings.slots` (dotted record paths, the `corpus_statistics.fields` pattern), and a `kg-microbe-links taxa --mech X` command that walks `record_globs`, reads those slots, and reports each cited taxon as one of: record, species-of-strain (with the ancestor), above-species, out-of-domain, retired (with the merge target), unattested-microbial, or absent. It reads TaxonMech's `curation/seed_scope.tsv`, `data/raw/ncbi_merged_ids.tsv` and the pinned taxdump, so the verdict is the same on a laptop and in CI, and it never calls NCBI. The three adhoc scripts here are its prototype; the measurement in section 2 is its acceptance test (the numbers must reproduce). A `cross-mech-taxon-links` fleet skill wraps it.

**Phase 2, routes (claw#655).** Put each Mech's published routes in the manifest (`site_base`, record route with its query parameter, search route). TaxonMech's record route is `pages/taxon.html?id=NCBITaxon:<n>`; its search route is `pages/browse.html?q=<label>`. Then each Mech renderer links by id when the taxon is a record or resolves to one, and by lineage search when it is above species. The six dead handoffs go first, each as an issue in its Mech. A claw check that every emitted sibling URL uses a declared route closes the loop.

**Phase 3, data fixes in the Mechs.** The retired and deleted ids that sit in slots (section 2.3: HabitatMech, ProteinTraitsMech, CommunityMech) and ProteinTraitsMech's decision on its optional `taxon_id`. Each is one issue in its Mech; the Phase 1 report is the evidence and the re-check, and it, not the text scan, decides what is a citation.

**Phase 4, TaxonMech.** Two decisions for its owner. (a) Whether to show "cited by" on a taxon page, computed at a sibling pin the way NaturalProductMech computes `related_records`, rather than stored in records the seeder regenerates. (b) Whether a UniProt reference proteome counts as attestation, which would admit the 548 unattested fungal and protist taxa that sibling records cite (416 protein examples, 1,051 records) through the existing inventory route; the seeder refuses any scope row no inventory attests, so this cannot be a `seed_scope.tsv` edit alone.

**Phase 5, protein examples, on the same base.** Register protein-example slots beside the taxon slots in the manifest (ProteinTraitsMech's channel rules in `scripts/cross_mech_proteins.py` and PathwayMech's `conf/sibling_mechs.yaml` are the two drafts to reconcile), make one fleet skill of the two cross-Mech audits over that registry, and canonicalise `add-uniprot-protein-examples` through `unify-skills` so the eight copies become one template with per-Mech adapters. Resolving each example's taxon becomes part of the protein-example check, which is where the question started.

## 5. What was not measured

Protein-holding slots the walker skipped, because they hold a bare accession rather than a mapping with a taxon beside it: PathwayMech participants; NaturalProductMech `molecular_targets[].protein_examples[]` (84 of its 90 accessions sit under a target that carries `taxon_id`), `biosynthetic_pathway[].enzyme_id`, `bioactivities[].target_enzyme` and causal-graph node identifiers; CellStructureMech Complex Portal participants; causal-graph node `xrefs` everywhere; and CommunityMech's UniProt evidence in `kb/taxa/*.yaml`, outside its manifest record globs. The last two carry no taxon; the others take theirs from a parent mapping, and every such taxon is already in the all-CURIE scan, so the conclusions about TaxonMech do not move. AntibioticMech's `resistance_mechanisms[].protein_accession`, which does carry a taxon beside the accession, was first missed for its key name and is counted since. Also unmeasured: whether every retired id's merge target is the taxon the record meant, and the handoffs' behaviour in a browser beyond the HTTP status of each URL.
