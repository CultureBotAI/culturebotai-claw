# Complementary Mechs: TaxonMech, MobilomeMech, HostAssociationMech

**Status:** Draft — recommendation, not a commitment to build
**Audience:** culturebotai-claw maintainer; KG-Microbe maintainers
**Date:** 2026-09-04
**Method:** measured against the seven manifest Mechs, HabitatMech, and
kg-microbe's ingest surface at `master`. Every gap below was checked against
the corpora rather than inferred from repository names.

## What this is

Three candidate Mechs that the family does not have, chosen because each fills
a gap KG-Microbe already ingests data for and no Mech curates. Plus one
recommendation that is deliberately *not* a Mech.

The most useful part of this document may be the second section: three
plausible-sounding Mechs that should **not** be built, because checking showed
the ground is already occupied.

## Ruled out by measurement

**MetabolismMech — do not build.** ProteinTraitsMech already owns the reaction
layer: 18,558 records under `data/traits/function/enzymatic_activity/rhea`,
24,129 under `function/pathway/go`, 2,883 Reactome, 1,086 SEED. TraitMech owns
the organism-level phenotype: 143 records under `data/traits/metabolism`
(`acetogenesis`, `aerobic_respiration`, `anoxygenic_photosynthesis`, …). The
molecular and phenotypic ends are both covered by Mechs that already exist, and
a third would sit between two things that already meet.

**InteractionMech — do not build.** CommunityMech's schema declares
`EcologicalInteraction`. Pairwise interaction is already its concern.

**GrowthKineticsMech — do not build as a Mech.** `CultureBotHT` (growth-curve
data), `MicroGrowLink`, `MicroGrowLinkService` and `MicroMediaParam` already
occupy this. The question there is consolidation, not a new repository.

## 1. TaxonMech — organism identity and nomenclature

**The strongest of the three, because it is infrastructure for the family
rather than another domain.**

### The gap

Zero taxon-record files across all seven Mechs:

```
CultureMech 0 · MediaIngredientMech 0 · CommunityMech 0 · TraitMech 0
ProteinTraitsMech 0 · AntibioticMech 0 · CellStructureMech 0
```

Every Mech keys on a taxon. kg-microbe ingests **three** nomenclature sources
that disagree with each other — `gtdb`, `lpsn`, `lpsn_api` — alongside
NCBITaxon, and carries a `kgmicrobe.strain` prefix of its own.

### What already exists, and what it cannot do

kg-microbe's LPSN transform (`transform_utils/lpsn/lpsn.py`) already reconciles
names automatically: it emits `close_match` edges to `NCBITaxon:*` for every row
whose scientific name "resolves to exactly one NCBITaxon", pre-loading NCBITaxon
labels and exact synonyms by BFS from `NCBITaxon:2` and `NCBITaxon:2157`.

That qualifier is the whole point. A name resolving to zero or to several
produces **no edge at all**, and the residue is invisible — the same shape as
kg-microbe#373, where unmapped terms are silently dropped rather than emitted.
Four things a transform structurally cannot do:

- **Decide an ambiguous match.** That needs evidence and a curator.
- **Record reclassification history.** A `close_match` says nothing about
  basonyms, which name superseded which, or when — the information that makes a
  decade-old record readable. *Clostridium difficile* and *Clostridioides
  difficile* are one organism, and no fleet check can currently tell.
- **Assert equivalence across GTDB and LPSN**, the pair that disagrees most.
- **Carry evidence.** An edge from string matching is a computed assertion with
  no provenance a curator can inspect or dispute.

So the scope is not "build reconciliation" — it is **own what automated matching
leaves unresolved, plus the history automation cannot infer**. The transform
produces the easy edges and the residue; the Mech curates the residue. (#336)

The family already feels the identity gap as a shape without an owner:
`manage-identifiers` and `id-label-correspondence` are carried by three and
four Mechs respectively, each with its own copy.

For KG-Microbe this is the **join key for the whole graph**, and it bears
directly on Knowledge-Graph-Hub/kg-microbe#373 — open since 2025-09-24 — which
asks for ingest terms that do not map to METPO or `custom_curies.yaml` to be
emitted rather than silently dropped.

### What a record is

Not new taxonomy. A **reconciled identity**: one record per organism concept,
carrying its GTDB, LPSN, NCBITaxon and SILVA identifiers, its basonym and
current name, the reclassification that connects them, and evidence for each
equivalence. That is the ordinary Mech shape — ontology-grounded,
evidence-backed, one record per entity — applied to identity.

### Capability declarations

| Capability | Status | Note |
|---|---|---|
| `id_label_validation` | enabled | its whole subject |
| `sssom_export` | enabled | the equivalences *are* mappings; `mapping_globs` required |
| `kgx_export` | enabled | `nodes_path`, `edges_path` required |
| `strict_validation`, `curation_history`, `testing`, `documentation` | enabled | fleet baseline |
| `site_contract` | enabled | `site_path` required |
| `corpus_statistics` | enabled | `fields` required — declare the identifier slots |
| `source_catalogue` | enabled | GTDB, LPSN and NCBITaxon are versioned releases; a `download.yaml` is the point |
| `source_queue` | enabled | `queue_path` required; licences differ per source |
| `unmapped_inventory_input` | enabled | this is what makes kgm#373 actionable |
| `vendored_sync` | enabled | on admission |
| `deep_research` | **disabled** | reconciliation is decided by source records, not literature search |
| `environment_coverage` | not_applicable | no environmental axis |
| `page_budgets`, `knowledge_gap_scan`, `writer_audit`, … | defer | declare on admission with measured settings |

## 2. MobilomeMech — plasmids, prophages, BGCs, genomic islands

### The gap

ProteinTraitsMech has 2,124 files matching mobile-element terms, and every one
is **protein-level**:

```
data/traits/function/molecular_function/go/prophage-integrase-activity-go0008979.yaml
data/traits/function/ortholog_group/cog/dna-primase-phage-or-plasmid-associated-cog3378.yaml
```

Proteins that *participate in* mobile elements. Nothing anywhere has a record
whose subject is the element itself — a plasmid, a biosynthetic gene cluster,
a genomic island — with host range, cargo, and transfer mechanism.

### Why it is complementary rather than additive

It is the **mechanism layer under two existing Mechs**. AntibioticMech records
that an organism resists a compound; MobilomeMech would record whether that
resistance is intrinsic or arrived on a plasmid. TraitMech records a
capability; this records whether the capability is encoded in a cluster that
moves. AntibioticMech already carries `data/raw/mibig_producers.tsv`, so the
BGC adjacency is live rather than hypothetical.

kg-microbe ingests `bakta`. `GenomeExplainer` explores Bakta annotations across
57 genomes but is an exploration repository, not a curated corpus.

### Capability declarations

| Capability | Status | Note |
|---|---|---|
| `strict_validation`, `curation_history`, `id_label_validation`, `testing`, `documentation` | enabled | fleet baseline |
| `sssom_export` | enabled | MIBiG/ICEberg/PLSDB cross-references |
| `kgx_export` | enabled | edges to taxa and to AntibioticMech compounds |
| `source_catalogue` + `source_queue` | enabled | MIBiG, PLSDB and ICEberg are versioned and licence-varied |
| `corpus_statistics` | enabled | `fields`: element class, host range, cargo |
| `site_contract`, `page_budgets` | enabled | on admission, with measured baselines |
| `deep_research` | enabled | element boundaries and host range are literature claims |
| `environment_coverage` | not_applicable | |

## 3. HostAssociationMech — the microbe side of host and disease

### The gap and the boundary

kg-microbe ingests `disbiome` and `ctd`; nothing curates either.
ProteinTraitsMech's 590 host/disease matches are GO *pathogenesis* terms —
protein function again, not association.

The boundary matters more than the gap. `monarch-initiative/dismech` is a
Disease Mechanisms KB and is already cited from this org (claw#7,
TraitMech#448, and five `docs/proposals/` phase documents take patterns from
it). This Mech should own **the microbe side** — which taxa associate with
which host, body site and disease state, with evidence and directionality —
and leave disease mechanism to DisMech. Scoped that way the two have an
interface rather than an overlap.

### Capability declarations

| Capability | Status | Note |
|---|---|---|
| `strict_validation`, `curation_history`, `id_label_validation`, `testing`, `documentation` | enabled | fleet baseline |
| `deep_research` | enabled | association strength and directionality are literature claims |
| `sssom_export` | enabled | UBERON body sites, MONDO disease terms, NCBITaxon hosts |
| `kgx_export` | enabled | the edges are the product |
| `source_catalogue` + `source_queue` | enabled | Disbiome and CTD carry real licence constraints; CTD's terms need reading before adoption |
| `environment_coverage` | **open decision** | not asserted here (#337). The capability's pipeline is ENVO term validation over an isolate/media corpus; this Mech grounds in UBERON body site, NCBITaxon host and MONDO disease. ENVO does model host association (`ENVO:01001002`), so it *may* carry that axis — but "may, if it chooses" is a different declaration from `enabled` |
| `corpus_statistics` | enabled | `fields`: host taxon, body site, association direction |
| `site_contract` | enabled | on admission |

## Not a Mech: the shared evidence layer

Before any new Mech, fix the layer every Mech already improvises (#333).

CommunityMech has independently built **748 tracked `references_cache/` files**
plus `evidence_snippet_audit.py`, mirroring DisMech's `reference_snippet_audit.py`.
AntibioticMech built 763 lines of *discovery* (`publications/`: PubMed,
Semantic Scholar, Google Scholar) with no verification at all. CellStructureMech
has a `literature-evidence` skill and no scripts. Five Mechs have literature
scripts, no two alike.

No capability declares "cites literature as evidence", so
`kg-microbe-skills catalogue` and the vendored-artifact registry are both blind
to the whole area — the same gap #316 records for source fetching.

Each new Mech will reinvent the same half of this. Declaring the capability and
canonicalising the verification rules costs less now than three times later.

## Ordering, and what admission costs

**If one: TaxonMech.** Everything else keys on it.

#279 measured what admission actually costs: a three-step, eight-repository
handshake — claw declares the consumer (advancing the canonical ref) → the
newcomer vendors its artifacts and pins that ref → every existing consumer
re-pins. `main` is red throughout, and the re-pin count grows with the fleet.
AntibioticMech's admission needed six re-pins; the next needs seven.

Two costs are known in advance rather than discoverable:

- `site_contract` newly parametrises over the newcomer and needs a measured
  baseline recorded, or the test dies on a `KeyError` (#318).
- `kg-microbe-skills inventory` will report a Mech with one or two skills
  against a fleet median of thirteen, which is accurate and worth seeing.

## Open questions

1. Is TaxonMech a Mech or a claw package? It is reference reconciliation rather
   than domain curation, and claw already owns identity tooling. Against that:
   it has a corpus, and corpora live in Mechs.
2. Does the residue justify a repository? kg-microbe's LPSN transform already
   emits the unambiguous edges, so TaxonMech's corpus is whatever that leaves
   over — and nobody has measured how large it is, because the transform does
   not emit its own misses (kg-microbe#373). **Measuring that residue is the
   cheapest next step, and it decides this recommendation.**
3. Does MobilomeMech absorb AntibioticMech's MIBiG data, or read it?
4. Does HostAssociationMech's boundary with DisMech hold in practice, or does
   one of them end up curating the other's records?
