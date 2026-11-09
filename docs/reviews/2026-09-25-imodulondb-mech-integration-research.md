# iModulonDB integration fit across the Mech fleet

Research date: 2026-09-25

Question: which Mechs can be integrated with iModulonDB, and which would
actually benefit?

## Executive summary

The best fit is **not** the medium or ingredient side of the fleet. iModulonDB is
an organism/dataset/iModulon/gene resource for independently modulated
transcriptional components, so it is strongest where a record needs regulator,
gene, protein, pathway, or stress-response context.

Recommended priority:

| Priority | Mech | Fit | Why |
|---|---|---|---|
| 1 | ProteinTraitsMech | High | iModulon gene tables already carry locus tags, UniProt accessions, STRING IDs, COGs, regulators, and component weights. That maps directly to protein examples, causal nodes, and source-backed evidence for protein-function claims. |
| 2 | TraitMech | High | Named iModulons summarize stress responses, nutrient programs, metal homeostasis, motility, and other physiological traits; regulator-to-gene overlays can seed or support trait causal graphs. |
| 3 | PathwayMech | High but outside canonical fleet | PathwayMech is present locally but not in `src/kg_microbe_fleet/fleet.yaml`. It is an excellent target because iModulons cluster genes into pathway-like programs and expose upstream regulators for each module. |
| 4 | AntibioticMech | Medium-high | iModulons cover efflux, permeability, envelope stress, oxidative stress, and metal responses in several pathogens. They can support resistance-mechanism and molecular-target context, but not primary compound identity or MIC evidence. |
| 5 | NaturalProductMech | Medium | Secondary-metabolism and Streptomyces datasets can inform producer/BGC pathway context. iModulonDB does not identify product structures, so it should only provide regulon or expression context for an already grounded BGC or producer claim. |
| 6 | CellStructureMech | Medium | Cell-wall, LPS, envelope, flagellar, secretion, and membrane iModulons can support causal context for structure assembly/remodeling records. The database is not a structural source. |
| 7 | TaxonMech | Low-medium | Useful as a thin taxon-to-iModulonDB-dataset cross-reference layer for the covered organisms and strains; weak as evidence for nomenclature or taxonomy. |
| 8 | CommunityMech | Conditional | Useful only when a community record models a member organism whose monoculture transcriptional program or biosensor is relevant. iModulonDB is not a metatranscriptomics or community-interaction source. |
| 9 | CultureMech | Low | Growth-condition metadata can occasionally contextualize media perturbations, but iModulonDB does not curate exact medium recipes or ingredient concentrations. |
| 10 | HabitatMech | Low | Environmental-response iModulons can be background physiology, but they do not assert habitat occurrence or ENVO-style habitat definitions. |
| 11 | MediaIngredientMech | Very low | The database is gene/regulon centered and carries essentially no chemical-identity evidence for medium ingredients. |

The right first integration is a **shared iModulonDB source adapter in claw** that
indexes organism/dataset/iModulon/gene records and lets high-fit Mechs curate a
small number of source-backed links. Do not bulk-write all gene weights into
record YAML: keep bulk matrices and per-iModulon tables as generated source
artifacts, then lift only curated claims into Mech records.

## What iModulonDB exposes

The current iModulonDB app is a React app backed by a public API. Its live
`/api/datasets` endpoint returned 20 organisms and 28 datasets on 2026-09-25:

- Acinetobacter baumannii
- Bacillus subtilis
- Bradyrhizobium diazoefficiens
- Corynebacterium glutamicum
- Escherichia coli
- Lactiplantibacillus plantarum
- Lactobacillus reuteri
- Mycobacterium tuberculosis
- Pseudomonas aeruginosa
- Pseudomonas putida
- Pseudomonas syringae
- Salmonella enterica
- Staphylococcus aureus
- Streptococcus pneumoniae
- Streptococcus pyogenes
- Streptomyces albidoflavus
- Streptomyces coelicolor
- Sulfolobus acidocaldarius
- Synechococcus elongatus
- Vibrio natriegens

The useful public API shapes are:

- `/api/datasets` - organism IDs, organism names, and dataset folders.
- `/api/search?organism=e_coli&dataset=precise1k&query=fur` - gene and
  iModulon search over gene names, products, iModulon names, regulators,
  functions, and categories.
- `/api/genes/e_coli/precise1k/b4062` - gene metadata, including gene name,
  product, COG, genomic coordinates, UniProt, STRING, and whether the gene is a
  regulator.
- `/api/imodulons/e_coli/precise1k/22/genes` - a concrete iModulon gene table:
  component weights, `in_imodulon`, per-gene regulator strings, COG, gene
  product, UniProt annotation, STRING ID, and coordinates.
- `/api/publications/...` - DOI/PMID publication lookups.

The current app embeds the iModulonDB 2.0 paper as `DOI:10.1093/nar/gkae1009`.
The upstream `SBRG/pymodulon` package owns an `imodulondb_export` path that
emits the database build inputs:

- `dataset_meta.csv`
- `gene_info.csv`
- `trn.csv`
- `gene_presence_matrix.csv`
- `gene_presence_list.csv`
- per-iModulon gene tables, histograms, scatter data, regulon Venn tables,
  regulon scatter tables, and raw gene weights
- per-gene iModulon membership and activity tables

So there are two levels of integration:

1. **API enrichment**: enough for search, dataset discovery, gene-to-iModulon
   links, UniProt grounding, and source-backed curation hints.
2. **Full import**: enough to mirror a release of the per-iModulon and per-gene
   source matrices into generated artifacts.

The first is enough for Mech curation. The second belongs in a versioned source
catalog only if a Mech needs reproducible matrix-level joins.

## Existing integration surface

An ignore-independent search for `iModulon`, `imodulon`, `modulon`, and
`i-modulon` found no iModulonDB adapter or source catalogue in
`culturebotai-claw`.

Across the local Mech tree, the only domain hit outside virtualenv/cache noise
was `CommunityMech/data/initial_research/README.md`, which lists an iModulon as
an engineered biosensor signal. That is a concept mention, not source ingestion.

The shared `Dataset` model already has the right shape for high-fit Mechs:

- `DatasetTypeEnum` has `TRANSCRIPTOMICS` for single-organism RNA-seq /
  expression.
- `DatasetRepositoryEnum` has GEO/SRA/ArrayExpress/BioProject and `OTHER`, but
  no first-class `IMODULONDB` value yet.

## Mech-by-Mech fit

### ProteinTraitsMech - high

Useful joins:

- `uniprot_id` -> `ProteinExample` / `ProteinReference`
- `gene_product`, `cog`, `all_regulators` -> functional context
- component weights and `in_imodulon` -> coexpression support for a protein's
  participation in a regulon or stress program
- iModulon function/category -> coarse biological-process context

Integration should be evidence-scoped:

- store iModulonDB as `Dataset(dataset_type=TRANSCRIPTOMICS)`;
- add source-specific `ProteinExample` evidence only after a locus maps to a
  reviewed UniProt accession;
- treat a component weight as computational context, not as direct proof that a
  protein has the trait.

Do not let the adapter infer homology outside the covered organism. E. coli
`soxS` or `fur` evidence is organism-specific.

### TraitMech - high

iModulons are almost trait records already: named stress responses, nutrient
programs, respiration shifts, metal-homeostasis programs, and other conditions
where an expression module stands for a regulatory state.

Good integration targets:

- `TraitRecord.causal_graphs`: regulator -> iModulon -> gene/protein edges.
- `CanonicalExample`: a representative organism/dataset/iModulon triplet.
- `EvidenceItem`: iModulonDB paper plus dataset-specific publication DOI/PMID.
- `CausalNode`: transcription factor, gene, GO biological process, pathway, or
  phenotype nodes.

The main guardrail is semantic: a named iModulon usually means "genes that move
together under this independent component", not "this trait was experimentally
measured for every gene in the module."

### PathwayMech - high, not canonical

PathwayMech is available in the local `Mechs/` directory but not declared in the
canonical claw fleet manifest. If it becomes a fleet member, iModulonDB is a
natural importer because PyModulon/iModulonDB exposes:

- module functions such as amino acid biosynthesis, cofactor metabolism, metal
  homeostasis, envelope biogenesis, and redox stress;
- per-iModulon gene membership lists;
- regulator overlap between the curated TRN and ICA components.

The strongest product would be regulatory overlays on existing KEGG, MetaCyc,
GO-CAM, ModelSEED, and Rhea pathway records. The source should add evidence for
"this pathway's genes co-vary in organism X under component K", not create new
canonical pathway identities.

### AntibioticMech - medium-high

iModulonDB covers several antibiotic-relevant pathogens and stresses:

- Acinetobacter baumannii
- Escherichia coli
- Mycobacterium tuberculosis
- Pseudomonas aeruginosa
- Salmonella enterica
- Staphylococcus aureus
- Streptococcus pneumoniae
- Streptococcus pyogenes

Concrete useful signals include TolC/Mdt efflux genes, Sox/Mar/Rob oxidative and
multi-drug responses, cell-envelope biogenesis, porins, and iron limitation.

Recommended use:

- support `ResistanceMechanism` records with regulator/gene context;
- back `MolecularTarget` protein examples with UniProt IDs where the target gene
  appears in a relevant iModulon;
- never use iModulon membership as an MIC, cidality, activity, or clinical
  susceptibility source.

### NaturalProductMech - medium

NaturalProductMech is not checked out locally under `Mechs/`, but its remote
schema has `ProducerOrganism`, `BiosyntheticGeneCluster`, `PathwayStep`, and
`biosynthetic_pathway` slots that could benefit from expression context.

iModulonDB helps when:

- the producer is one of the covered organisms;
- a BGC gene or pathway enzyme has a stable UniProt/locus mapping;
- a Streptomyces, Pseudomonas, Bacillus, or Staphylococcus iModulon implicates
  secondary metabolism, siderophores, metal homeostasis, or precursor supply.

It does not help identify chemical structures, analogs, or bioactivity classes.
At most it can say "this gene cluster or pathway is co-regulated under component
K"; it cannot prove which compound a cluster produces.

### CellStructureMech - medium

iModulonDB iModulons can supply transcriptomic context for structures whose
biogenesis genes are co-regulated: cell wall, outer membrane, LPS, secretion,
flagella, stress envelopes, or ribosome-associated structures.

Use it for:

- adding dataset evidence to `StructureFunction` or `TraitLink`;
- connecting structural components with genes/proteins that appear in an
  envelope or motility iModulon;
- prioritizing E. coli and Pseudomonas structure records that already have
  UniProt-backed `ProteinExample` entries.

It is not a source for electron microscopy, stoichiometry, or subcellular
localization by itself.

### TaxonMech - low-medium

TaxonMech can absorb the iModulonDB organism index as a tiny cross-reference:

- iModulonDB organism ID
- covered dataset folders
- organism label and best NCBITaxon match

That would help source discovery for the rest of the fleet, especially if a
future adapter needs to know whether a taxon has expression-module coverage.
It should not be used as nomenclatural evidence.

### CommunityMech - conditional

CommunityMech could use iModulonDB only in isolate-backed contexts:

- engineered co-cultures with a member that has an iModulonDB dataset;
- iModulon-driven biosensors;
- member metabolic roles supported by single-organism expression modules.

The evidence has to be framed as monoculture context for a member, not as
community-level metatranscriptomics. iModulonDB's curated public organism list
does not represent mixed communities.

### CultureMech - low

iModulonDB contains sample metadata and growth-condition perturbations, but it
does not curate medium recipes. The plausible uses are narrow:

- link a media perturbation paper as transcriptomic context for a known medium;
- explain why adding or removing iron, glucose, oxygen, or another condition
  activates a known regulatory module;
- associate a medium variant with a source dataset when the publication already
  supplies the exact recipe.

The database should not be used to infer ingredient concentrations.

### HabitatMech - low

The expression modules sometimes represent environmental stresses, but iModulonDB
does not assert habitat occurrence. It can support a causal graph for why a
species tolerates low iron, oxidative stress, heat, or other conditions, not the
definition of an ENVO habitat.

### MediaIngredientMech - very low

MediaIngredientMech curates chemical ingredient identities and roles. iModulonDB
returns genes, proteins, COGs, regulators, and module weights. A gene module may
mention iron, sulfate, or glucose utilization, but that is too indirect for
grounding a CHEBI mapping or resolving an ambiguous ingredient string.

If anything, MediaIngredientMech should only inherit curated downstream facts
from CultureMech once a medium perturbation has been linked elsewhere.

## Adapter design

A shared claw adapter should normalize iModulonDB around these source-native
keys:

| Entity | Stable key shape |
|---|---|
| Organism | `organism_id`, e.g. `e_coli` |
| Dataset | `organism_id` + `dataset`, e.g. `e_coli/precise1k` |
| iModulon | `organism_id` + `dataset` + integer `k` |
| Gene | `organism_id` + `dataset` + source locus, e.g. `e_coli/precise1k/b4062` |

Keep these generated tables outside curated YAML:

- organism/dataset index from `/api/datasets`;
- gene search/detail cache;
- iModulon-to-gene membership with weights and threshold;
- iModulon search cache;
- publication metadata by DOI/PMID.

Then expose three `kg-microbe-sources imodulondb` curation helpers:

1. `datasets`, listing covered `organism/dataset` keys.
2. `search --organism --dataset --query`, finding matching source genes and
   iModulons inside one dataset.
3. `summarize --organism --dataset --k`, producing a source-backed
   Markdown report with genes, regulators, category, function, and mapped
   UniProt accessions.

The shared `DatasetRepositoryEnum` should grow `IMODULONDB`, with repository
records still storing source GEO/SRA/BioProject accessions when present.

## Guardrails

- A module membership is **computational evidence**, not a direct biochemical or
  phenotypic assertion.
- iModulon integer IDs are dataset-local; never store bare `22`.
- Locus tags are organism/strain-specific; map through UniProt or NCBIGene
  before linking into protein or target fields.
- Regulator names can be Boolean strings or complexes in PyModulon exports; keep
  the raw string and curated parsed members separately.
- The covered organism set is small and model-organism-biased. Absence from
  iModulonDB is not negative evidence.
- Bulk weights belong in generated source tables, not hand-curated record YAML.

## Bottom line

Build this once in claw as a source adapter and first wire it to
ProteinTraitsMech and TraitMech. Add PathwayMech as soon as it joins the
canonical fleet. Let AntibioticMech, NaturalProductMech, CellStructureMech, and
TaxonMech consume the same normalized cache when they need it. Leave
MediaIngredientMech, HabitatMech, CultureMech, and CommunityMech out of the
first pass unless a concrete record mentions a covered organism/dataset.
