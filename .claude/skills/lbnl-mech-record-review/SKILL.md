---
name: lbnl-mech-record-review
description: "Content-triaged Mech record review using LBNL Library services, publisher TDM APIs, CAS Common Chemistry, ChEBI, SciFinder-n, Reaxys, CHEMnetBASE, WebCSD, ICSD, BioCyc, and CBORG MCP tools. Routes citations by journal/DOI prefix and chemical or biological claims by structure, stoichiometry, and domain to produce schema-valid structured record reviews."
category: review
requires_database: false
requires_internet: true
version: 1.0.0
tags:
  - fleet
  - review
  - literature
  - chemistry
  - lbnl
  - curation
---

# LBNL Content-Triaged Mech Record Review

Use this skill to perform a rigorous, read-only scientific and structural review of one record (or a bounded cohort) in any manifest-resolved Mech that enables `record_review`, using the full suite of LBNL Library literature channels, publisher Text and Data Mining (TDM) APIs, chemical/crystallographic databases, and CBORG MCP servers.

Rather than treating every citation or chemical identifier identically, this skill **triages each claim by its content**—routing citations by DOI prefix, journal family, and article section needed, and routing chemical, structural, and biological assertions to the authoritative LBNL service that can verify or refute them.

---

## 1. Resolve Target Mechs and Profiles from the Fleet Manifest

Never hardcode repository lists, paths, or fleet counts. Query `src/kg_microbe_fleet/fleet.yaml` to resolve which Mechs enable `record_review` and `evidence_reference_validation`, along with their checkout roots, schemas, and record globs:

```bash
uv run python -m kg_microbe_fleet list --capability record_review --format tsv
uv run python -m kg_microbe_fleet list --capability evidence_reference_validation --format tsv
uv run python -m kg_microbe_fleet targets --capability record_review
```

Before judging any record:
1. Resolve **exactly one target record** (or one explicitly bounded category/batch) inside the target Mech checkout (`$MECH_ROOT`). If a label, slug, or CURIE matches multiple records, stop and disambiguate.
2. Read the entire target YAML file, the Mech's `<mech>/docs/record-review-profile.md`, and the shared review contract in `src/kg_microbe_governance/artifacts/docs/record-reviews.md` (`<mech>/docs/record-reviews.md`).
3. Verify that `$MECH_ROOT/.temp/` is gitignored and use it for all staging files, review targets, and draft bundles. Never store session state in /tmp, /private/tmp or `$TMPDIR`.

---

## 2. Content-Driven Literature & Citation Triage

Inspect every citation in the record (`PMID:*`, `DOI:*`, journal title, publication year, and provenance flags such as `abstract only`, `author manuscript`, `supplement only`, or `inherited from parent`) plus the **kind of claim** attached to it (e.g., MIC table, medium recipe, NMR/crystal structure, enzyme kinetics, growth pH/temperature, or taxonomic description).

### A. Mine Unpromoted Local Provenance (`<mech>/data/raw/` & `<mech>/research/`) Before External Search

Many Mech records were seeded from curated upstream tables or deep-research harvests whose primary journal DOIs (including thousands of ACS *Biochemistry*, *JACS*, *J. Nat. Prod.*, *J. Med. Chem.*, *Inorg. Chem.*, and *Environ. Sci. Technol.* papers) sit in local repository provenance files without yet being promoted onto the YAML record:
- **`ProteinTraitsMech` (`<mech>/data/raw/mcsa-native-review/*.json`, `<mech>/data/raw/pmid2doi.json`):** Contains primary M-CSA catalytic-site and mechanism papers (*Biochemistry*, *JACS*) with catalytic-residue roles, mutagenesis fold-changes, and kinetic constants beyond what was copied into the initial YAML seed.
- **`NaturalProductMech` (`<mech>/data/raw/lotus_occurrences.tsv`, `<mech>/data/raw/chebi_origins.tsv`):** Contains primary isolation and structure-elucidation DOIs (*J. Nat. Prod.*, *Org. Lett.*, *JACS*) for `SEED` records; pair these DOIs with open ACS Figshare Supporting Information (`10.1021/<suffix>.s001`) to recover strain designations, fermentation media, NMR tables, and bioactivity assays.
- **`AntibioticMech` (`<mech>/data/raw/bindingdb_target_measurements.tsv`, `<mech>/research/*card*`, `<mech>/research/*resistance*`):** Contains quantitative BindingDB target affinities ($K_i$, $IC_{50}$, $K_d$ in *J. Med. Chem.* / *ACS Infect. Dis.*) and CARD citation concordance mappings ready to ground target and resistance claims.
- **`MediaIngredientMech` (`<mech>/research/ingredients/*-edison-literature*.json`), `CultureMech` (`<mech>/research/media/`), `PathwayMech` (`<mech>/research/pathway_additions/`), `CMMMech` (`<mech>/research/sources/`, `<mech>/research/ingests/`), `TraitMech` (`<mech>/research/traits/`), `HabitatMech` (`<mech>/research/habitats/`):** Contains pre-retrieved literature dossiers and candidate citations that can resolve missing role, stability, bioavailability, or pathway-step evidence without spending new provider credits.

Always search `<mech>/data/raw/` and `<mech>/research/` for the record's identifier, label, CAS-RN, UniProt ID, or ChEBI CURIE (`rg --no-ignore --hidden` or `uv run kg-microbe-sources local-provenance --record <record.yaml> --root <mech>`) before declaring literature support absent.

### B. Triage Matrix by DOI Prefix, Publisher & Journal Family

| DOI Prefix / Publisher | Representative Journals in Mech Corpora | Primary LBNL / Full-Text Channel | Content-Specific Triage Rule |
| :--- | :--- | :--- | :--- |
| **Any (`PMID:*` / `DOI:*`)** | Every journal | Local `<mech>/references_cache/` & `$ZOTERO_DATA_DIR` (`zotero_local`) | Check cached abstracts (`<mech>/references_cache/PMID_*.md`, `<mech>/references_cache/DOI_*.md`) and local synced Zotero PDFs first before making network calls. |
| **Open Access / PMC / Preprints** (`10.1101/*`, `10.64898/*`) | PMC-indexed journals, *bioRxiv*, *medRxiv* | `europepmc_oa`, `openalex_oa`, `biorxiv`, `core` (`$CORE_API_KEY`) | Pull Europe PMC `fullTextXML` when `isOpenAccess == "Y"` to inspect Methods, strain tables, and media recipes. For preprints, run `valency-get_paper_versions` to check whether a peer-reviewed journal version superseded the preprint. |
| **DOE / National Lab Reports** (`10.2172/*` and DOE-funded DOIs) | LBNL, ORNL, PNNL, JGI, KBase, ENIGMA technical reports & accepted MSS | `osti_gov` (`https://www.osti.gov/api/v1/records`) | Preferred for subsurface/watershed field studies (`HabitatMech`, `CommunityMech`), lanthanide/actinide reports (`CMMMech`), and DOE-funded accepted manuscripts. |
| **Elsevier / ScienceDirect / Cell Press** (`10.1016/*`) | *J. Biol. Chem.* (*JBC*), *Bioorg. Med. Chem.*, *Phytochemistry*, *Tetrahedron*, *Tetrahedron Lett.*, *FEBS Lett.*, *BBA*, *Cell Chem. Biol.*, *Bioresource Technol.*, *Syst. Appl. Microbiol.* | `elsevier_tdm` (`$ELSEVIER_API_KEY`, optional `$ELSEVIER_INST_TOKEN`) | Retrieves full-text XML (`<body`, `<ce:sections>`, `<rawtext>`). Essential when claims depend on MIC/susceptibility tables (`AntibioticMech`), isolation yields and optical rotations (`NaturalProductMech`), or enzyme kinetics (`PathwayMech`, `ProteinTraitsMech`). |
| **Springer Nature** (`10.1007/*`, `10.1038/*`, `10.1186/*`) | *Nature*, *Nat. Chem. Biol.*, *Nat. Microbiol.*, *ISME J.*, *J. Antibiot.*, *Arch. Microbiol.*, *Appl. Microbiol. Biotechnol.*, *J. Ind. Microbiol. Biotechnol.*, *JBIC*, *Extremophiles*, *Antonie van Leeuwenhoek*, *BMC Microbiol.* | `springer_tdm` (`$SPRINGER_API_KEY` / `SPRINGER_OPENACCESS_API` / `SPRINGER_META_API`) | Retrieves JATS XML (`<body`) for open/hybrid articles and structured metadata for strain designations, fermentation media (`CultureMech`), and metal-binding stoichiometry (`CMMMech`). |
| **Wiley** (`10.1002/*`, `10.1111/*`) | *Angew. Chem. Int. Ed.*, *ChemBioChem*, *Chem. Eur. J.*, *FEBS J.* / *Eur. J. Biochem.*, *Mol. Microbiol.*, *Environ. Microbiol.*, *Microb. Biotechnol.*, *FEMS Microbiol.* | `wiley_tdm` (`$WILEY_TDM_TOKEN`) | Retrieves full-text PDF via `Wiley-TDM-Client-Token`. Critical for total-synthesis stereochemical revisions (`NaturalProductMech`), biosynthetic mechanism proofs, and physiological characterization (`TraitMech`). |
| **American Chemical Society — ACS** (`10.1021/*`) | *Biochemistry*, *JACS*, *J. Nat. Prod.*, *ACS Chem. Biol.*, *J. Med. Chem.*, *J. Org. Chem.*, *Org. Lett.*, *Environ. Sci. Technol.*, *Inorg. Chem.*, *ACS Catal.*, *ACS Synth. Biol.*, *ACS Infect. Dis.* | **1.** Open Figshare SI (`10.1021/<suffix>.s001`)<br>**2.** Local Zotero (`zotero_local`) / LBNL ACS TDM feed | **Special ACS Triage:**<br>• **Supporting Information first:** ACS deposits Supporting Information openly via Figshare (`https://doi.org/10.1021/<suffix>.s001`). When a record's structure, NMR ($^1\text{H}$/$^{13}\text{C}$), HR-MS, crystal data, MIC table, or assay protocol lives in the SI, fetch and inspect the open `.s001` artifact.<br>• **Main article body:** Paywalled ACS main text is not served by a self-service REST token; check `$ZOTERO_DATA_DIR` first, use `valency` / PubMed for abstract verification, and log unresolved paywalled body checks in `limitations` for the LBNL Library ACS TDM queue. |
| **Society & University Presses** (`10.1128/*` ASM, `10.1099/*` Microbiol. Soc., `10.1093/*` OUP, `10.1039/*` RSC) | *J. Bacteriol.*, *Appl. Environ. Microbiol.*, *Antimicrob. Agents Chemother.*, *IJSEM*, *Nucleic Acids Res.*, *Nat. Prod. Rep.*, *Chem. Commun.* | `europepmc_oa` -> `openalex_oa` -> CBORG `valency` / `tavily` | *IJSEM* (`10.1099/ijsem.*`) is the primary authority for prokaryotic nomenclature, type strains, and chemotaxonomic/media baselines (`TaxonMech`, `CultureMech`). Most ASM and OUP articles are in Europe PMC OA XML. |

### C. Executing the Legal Full-Text Ladder

Load the LBNL TDM credentials (stored in `~/.config/lbnl-tdm.env`, never printed or echoed) and run `CommunityMech/scripts/fulltext_access.py`, staging any downloaded full text into `$MECH_ROOT/.temp/fulltext/` (never directly into `<mech>/references_cache/`):

```bash
uv run kg-microbe-sources local-provenance --record <record.yaml> --root "$MECH_ROOT"
uv run kg-microbe-sources acs-si --doi 10.1021/<suffix> --dest-dir "$MECH_ROOT/.temp/acs-si"
uv run python CommunityMech/scripts/fulltext_access.py --doi <doi> --fetch-to "$MECH_ROOT/.temp/fulltext/article.xml"
uv run python CommunityMech/scripts/fulltext_access.py --pmid <pmid> --fetch-to "$MECH_ROOT/.temp/fulltext/article.xml"
```

- **Copyright & Cache Rule:** Never commit `.pdf` files or copyright-asserted publisher XML/text (`All rights reserved`, `© YYYY Elsevier`, `© YYYY American Chemical Society`) into `<mech>/references_cache/` or git history. Use staged TDM full text to verify claims, record `snapshot_sha256` in the structured review's `evidence[]` list, and extract only short verbatim `quote` / `snippet` strings.

---

## 3. Content-Driven Chemical, Structural & Biological Triage

When a record asserts chemical identity, molecular structure, salt/hydrate stoichiometry, natural-product source, antibiotic activity, or metal-ligand coordination, triage by the **record's domain and chemical fields**:

### A. Chemical & Structural Triage Matrix

| Record Content / Issue Pattern | Target Mechs | Primary LBNL Service | Verification & Grounding Action |
| :--- | :--- | :--- | :--- |
| **`CAS-RN:*` present, or `MINTED` / `UNMAPPED` / `NEEDS_CREATION` / `INCHI_FALLBACK` chemical monomer** | `MediaIngredientMech`, `AntibioticMech`, `NaturalProductMech`, `CMMMech`, `PathwayMech`, `CultureMech` | **Tier 1:** CAS Common Chemistry API (`$CAS_COMMON_CHEMISTRY_API`) + 3-star ChEBI Crosswalk | Query `/api/detail?cas_rn=<rn>` (or `/api/search?q=<name>`), extract `inchi`, `inchiKey`, and `molecularFormula`, and cross-reference `inchiKey` against 3-star ChEBI (`chebi_structures.tsv` / OLS4). |
| **`REVIEW_NEEDED` protonation / tautomer / charge-state conflict** (`neutral` vs. `zwitterion` vs. `(n+)`/`(n-)` ion) | `NaturalProductMech`, `AntibioticMech`, `MediaIngredientMech`, `PathwayMech` | **Tier 1:** CAS Common Chemistry InChI (`InChI=1S/.../p.../q...` layers) + ChEBI OLS4 + `src/kg_microbe_governance/artifacts/scripts/chem_formula.py` | Compare the first 14 characters of `inchiKey` (connectivity block) against ChEBI candidates. Inspect formal charges (`+`/`-` in SMILES, `q-layer` and `p-layer` in InChI) so conjugate acids/bases (e.g., `streptothricin F(2+)` `CHEBI:60821` vs. neutral `streptothricin F` `CHEBI:26789`) are not conflated. |
| **Multi-component salts, hydrates, and buffers** (`.nH2O`, disodium/trisodium salts, trace-metal salts) | `MediaIngredientMech`, `CultureMech`, `CMMMech` | **Tier 1:** InChI formula layer + `src/kg_microbe_governance/artifacts/scripts/chem_formula.py`<br>**Tier 2:** ICSD (`https://icsd.products.fiz-karlsruhe.de/`) | **Stoichiometry Guard:** Reject CAS `canonicalSmile` when component multipliers $>1$ are deduplicated (see Mandatory Guards below). Verify exact hydrate water count and counterion ratio against the InChI formula layer and ICSD. |
| **Complex natural products, novel congeners, or Tier-1 CAS 404 misses** | `NaturalProductMech`, `AntibioticMech` | **Tier 2:** CAS SciFinder-n (`https://scifinder-n.cas.org`) & CHEMnetBASE (*Dictionary of Natural Products*) | Resolve CAS Registry Numbers outside the public ~500k Common Chemistry subset; verify producer organism vs. isolation matrix and congener stereochemistry. |
| **Bioactivity, MIC / $IC_{50}$ ranges, mode of action, and physicochemical properties** ($pK_a$, $\log P$, solubility, stability) | `AntibioticMech`, `NaturalProductMech`, `MediaIngredientMech` | **Tier 2:** Reaxys (`https://www.reaxys.com`) & CHEMnetBASE (*Dictionary of Drugs* / *Combined Chemical Dictionary*) | Cross-check target class, susceptible/resistant spectrum, and experimental physical properties when primary literature abstracts omit numerical values. |
| **3D crystal structures, absolute stereochemistry (`stereo:proposed_revision`), and lanthanide/metal coordination** | `CMMMech`, `NaturalProductMech`, `AntibioticMech`, `MediaIngredientMech` | **Tier 2:** WebCSD / CCDC (`https://www.ccdc.cam.ac.uk/`) & ICSD | Verify denticity, coordination number, metal-donor bond distances (e.g., lanmodulin/siderophore $\text{Ln}^{3+}$ complexes), and X-ray crystal stereochemical revisions. |
| **Metabolic pathways, enzyme-substrate-cofactor edges, transporters, and defined growth media** | `PathwayMech`, `TraitMech`, `ProteinTraitsMech`, `CultureMech` | **Tier 3:** BioCyc PGDBs (`https://biocyc.org/`) | Verify reaction stoichiometry, EC numbers, gene-protein-reaction (GPR) associations, and organism-specific auxotrophies. |
| **Bacterial gene, locus tag, regulator, or stress-response transcriptional module** | `TraitMech`, `ProteinTraitsMech`, `PathwayMech`, `AntibioticMech`, `CellStructureMech` | **Tier 3:** iModulonDB (`kg-microbe-sources imodulondb`) | Run `kg-microbe-sources imodulondb datasets`, `search`, and `summarize`. Treat iModulon membership as computational expression-module context, never as standalone proof of a phenotype, MIC, or biochemical mechanism. |

### B. Mandatory Chemical & License Guards

1. **CAS Common Chemistry License Gate (`CC BY-NC 4.0` -> `CURATE_ONLY`):**
   - CAS Common Chemistry is governed by **CC BY-NC 4.0** (`NON_COMMERCIAL`).
   - **Never** copy CAS Common Chemistry structures (`smile`, `canonicalSmile`, `inchi`), molecular properties, or synonyms directly into CC BY 4.0 (`AntibioticMech`, `NaturalProductMech`) or BSD-3-Clause (`MediaIngredientMech`) repository records.
   - Instead, use CAS Common Chemistry as a **read-only verification oracle and `Standard InChIKey` bridge** to identify the matching 3-star **ChEBI** term (CC BY 4.0), and recommend seeding the record from ChEBI in the review's `actions[]`.
   - Respect SHA-256-pinned source queues (such as `<mech>/curation/source_queue.tsv` in `AntibioticMech`, which is locked by historical audit plans): never mutate `<mech>/curation/source_queue.tsv` during a review.

2. **CAS Common Chemistry Polysalt & Polyhydrate SMILES Trap (`STRUCTURE_COMPOSITION_MISMATCH`):**
   - CAS Common Chemistry's `canonicalSmile` and `smile` fields **deduplicate repeated disconnected components**:
     - Disodium salts (e.g., $\text{C}_{10}\text{H}_{16}\text{N}_2\text{O}_8\cdot 2\text{H}_2\text{O}\cdot 2\text{Na}$) appear in CAS `canonicalSmile` with only one `[Na]` and one `.O`.
     - Polyhydrates (e.g., $\text{Cl}_3\text{La}\cdot 7\text{H}_2\text{O}$, $\text{Na}_2\text{S}\cdot 9\text{H}_2\text{O}$) appear with a single `.O`.
     - Hemi-salts / sesquihydrates (e.g., $2\text{C}_6\text{H}_{13}\text{NO}_4\text{S}\cdot\text{Na}$, $2\text{C}_7\text{H}_5\text{NO}_3\text{S}\cdot 3\text{H}_2\text{O}\cdot 2\text{Na}$) drop component multipliers across every dot-separated fragment.
   - **Rule:** Whenever a molecular formula or InChI contains dot-separated component multipliers (`2H2O`, `3Na`, `2C6H13...`) whose sum exceeds `len(smiles.split("."))`, flag `canonicalSmile` as stoichiometry-deduplicated (`STRUCTURE_COMPOSITION_MISMATCH`) and validate atom counts against the InChI formula layer (`InChI=1S/<formula>/...`) using `src/kg_microbe_governance/artifacts/scripts/chem_formula.py`.

---

## 4. End-to-End Review Workflow

### Step 1 — Inspect the Target Record and Capture Input Hashes
From the target Mech checkout (`$MECH_ROOT`), prepare `$MECH_ROOT/.temp/review-targets.yaml` and run the shared inspector before assessing:

```bash
uv run python "$MECH_ROOT/scripts/record_review.py" inspect --targets "$MECH_ROOT/.temp/review-targets.yaml"
```

Include `--input <path>` for the Mech's schema, overlays, or source tables that govern the record. For a generated record, identify the maintained input table, overlay, or seeder in `owner_paths`—never propose hand-editing a generated YAML output.

### Step 2 — Run Documented Native & Shared Validators
Run the narrowest documented validators from `$MECH_ROOT/justfile` and `$MECH_ROOT/docs/record-review-profile.md`:
- Schema, strict, term/ID-label correspondence (`<mech>/scripts/validate_id_label_correspondence.py`), and curation-history checks.
- If the Mech enables `evidence_reference_validation` in `src/kg_microbe_fleet/fleet.yaml`, run:
  ```bash
  uv run kg-microbe-evidence --mech <mech_key> --root "$MECH_ROOT" --strict
  ```
- Record every command run, its actual exit code, and its status (`passed`, `failed`, `skipped`, `unavailable`, `not_applicable`) in `checks[]`.

### Step 3 — Execute Content-Triaged Literature & Database Verification
1. **Classify each citation** using the Section 2 matrix and retrieve legal full text or open ACS Supporting Information (`.s001`) into `$MECH_ROOT/.temp/fulltext/` when abstract caches in `<mech>/references_cache/` are insufficient to verify the specific claim (e.g., MIC value, concentration, pH, stereochemistry, or causal edge predicate).
2. **Classify each chemical/biological entity** using the Section 3 matrix:
   - Run Tier-1 CAS Common Chemistry + 3-star ChEBI crosswalk checks for any `CAS-RN`, `MINTED`/`UNMAPPED` chemical, `INCHI_FALLBACK`, or `REVIEW_NEEDED` structure.
   - Classify the chemical triage outcome as one of:
     - `CHEBI_EXACT_MATCH` (full 27-char InChIKey match to 3-star ChEBI)
     - `CHEBI_3STAR_OUTSIDE_SLICE` (exact 3-star ChEBI match missed by a narrow branch filter)
     - `CHEBI_PROTONATION_OR_TAUTOMER_VARIANT` (14-char connectivity match differing only in `p-layer` or `q-layer` charge state)
     - `CHEBI_STEREO_OR_CONGENER_DIFFERENCE` (connectivity or formula difference; distinct stereoisomer/congener)
     - `CAS_RESOLVED_NO_CHEBI_3STAR` (verified in CAS Common Chemistry; absent from 3-star ChEBI; escalate to SciFinder-n / ChEBI submission)
     - `COMPLEX_OR_BIOLOGICAL_MIXTURE` (undefined extract, peptone, or mineral mixture; route to FOODON/ENVO rather than ChEBI/CAS monomer)
   - Run iModulonDB (`kg-microbe-sources imodulondb`) or CBORG `valency` / `tavily` lookups where applicable.
3. **Exhaustive Search Before Claiming Absence:** Before reporting any cache, overlay, decision row, or sibling record as missing, run a gitignore-independent search (`rg --no-ignore --hidden`, `rg -uu`, `grep -r`, or `find`) and record the exact search scope in `evidence[].search_scope`.

### Step 4 — Author and Save the Structured Review Bundle
Author `$MECH_ROOT/.temp/completed-review.yaml` conforming to `src/kg_microbe_governance/artifacts/schema/record_review.yaml` (`<mech>/schema/record_review.yaml`):
- Record content-triage coordinates in `assessments[].dimensions` using structured `ReviewDimension` entries:
  - `literature_channel`: e.g., `zotero_local`, `europepmc_oa`, `elsevier_tdm`, `springer_tdm`, `wiley_tdm`, `acs_figshare_si`, `osti_gov`, `abstract_only`
  - `chemical_triage_status`: e.g., `CHEBI_EXACT_MATCH`, `CHEBI_3STAR_OUTSIDE_SLICE`, `CHEBI_PROTONATION_OR_TAUTOMER_VARIANT`, `CAS_RESOLVED_NO_CHEBI_3STAR`, `STRUCTURE_COMPOSITION_MISMATCH`
  - `license_guard`: e.g., `CC_BY_4_0_CHEBI_SAFE`, `CURATE_ONLY_CAS_NC_BRIDGED`
- Classify each defect in `findings[]` by severity (`blocker`, `major`, `minor`, `informational`) and pair it with concrete `actions[]` naming the maintained `owner_paths` and `acceptance_checks`.
- Validate, save, and verify the immutable bundle (`reviews/structured/<YYYYMMDDTHHMMSSZ>-<slug>/review.yaml` and `review.md`):

```bash
uv run python "$MECH_ROOT/scripts/record_review.py" validate "$MECH_ROOT/.temp/completed-review.yaml"
uv run python "$MECH_ROOT/scripts/record_review.py" save --content "$MECH_ROOT/.temp/completed-review.yaml"
uv run python "$MECH_ROOT/scripts/record_review.py" check
```

---

## 5. Boundaries

- **Read-only scientific review:** This skill writes only the new structured review bundle under `<mech>/reviews/structured/` and temporary staging files under `$MECH_ROOT/.temp/`. It never edits corpus records, mutates `<mech>/curation/source_queue.tsv`, appends curation-history events, or promotes scientific status.
- **No outbound communication or paid provider calls:** Never send emails (author-request templates are local text drafts only), create/comment on GitHub issues or PRs, or invoke paid deep-research providers without separate, explicit per-action human permission.
- **Zero personal email disclosure:** All public API calls (Europe PMC, OpenAlex, CrossRef, NCBI, OSTI) must remain strictly anonymous.

## Related Skills

- `/lbnl-literature-and-db-access` — CBORG MCP servers (`valency`, `tavily`, `context7`), `CommunityMech/scripts/fulltext_access.py`, and LBNL database endpoints
- `/evidence-reference-validation` — Offline quote-against-cached-abstract verification across manifest-enabled Mechs
- `/cas-rn-integration` — MIM CAS Registry Number enrichment pipeline
