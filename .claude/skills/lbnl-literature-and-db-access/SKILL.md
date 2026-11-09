---
name: lbnl-literature-and-db-access
description: "Combine CBORG MCP servers (valency, tavily, context7), anonymous public APIs (Europe PMC, OpenAlex, bioRxiv, DOE OSTI.gov), local Zotero storage, and LBNL-licensed scientific databases and TDM APIs (BioCyc, Elsevier, Springer Nature, Wiley, ICSD, WebCSD, CHEMnetBASE) for evidence-backed Mech curation and research without disclosing personal email addresses or committing paywalled text."
category: research
requires_database: false
requires_internet: true
tags:
  - fleet
  - literature
  - databases
  - mcp
  - lbnl
---

# LBNL Literature, Database & CBORG MCP Access for Mech Curation

Use this skill when discovering papers, resolving DOIs/PMIDs, locating legal full text for Methods/supplementary data, or querying chemical, crystal-structure, pathway, and natural-product databases across manifest-resolved Mechs.

## 1. Resolve Applicable Mechs from the Fleet Manifest

Never hardcode repository lists or fleet counts. Resolve the Mechs that participate in evidence validation or curation from `src/kg_microbe_fleet/fleet.yaml`:

```bash
uv run python -m kg_microbe_fleet list --capability evidence_validation --format tsv
uv run python -m kg_microbe_fleet list --capability curation_history --format tsv
```

## 2. CBORG MCP Servers (`valency`, `tavily`, `context7`)

Three LBNL CBORG MCP servers (`https://api.cborg.lbl.gov/mcp/...`, authenticated via `CBORG_API_KEY`) are configured across Antigravity, Claude Code, and Codex:

### A. `valency` — Scientific Corpus & Citation Discovery
Use `valency` read-only tools before falling back to ad-hoc web searches:
- **Discovery & Semantic Search:** `valency-semantic_search_papers`, `valency-search_by_title`, `valency-search_by_abstract`, `valency-search_by_abstract_batch`, `valency-find_similar_papers`
- **Citation Graph & Provenance:** `valency-get_paper_by_id`, `valency-get_citing_papers`, `valency-get_paper_versions`, `valency-filter_papers_with_doi`, `valency-export_papers_bibtex`
- **Author & Domain Mapping:** `valency-search_by_author`, `valency-get_author_papers`, `valency-identify_research_domains`
- **Outbound Guardrail:** Never call `valency-submit_feedback` without explicit per-action human permission.

### B. `tavily` — Web Search & Structured Page Extraction
Use `tavily` when a target URL is a web page, strain catalog, publisher landing page, or documentation site:
- `tavily-tavily_extract`: Extract clean Markdown/text from specific URLs (such as DSMZ/ATCC media pages, BioCyc summaries, or OSTI landing pages).
- `tavily-tavily_search` / `tavily-tavily_research`: Locate strain-specific cultivation reports, reactor parameters, or database accession numbers when literature queries return sparse hits.

### C. `context7` — Live Library Documentation
Use `context7-resolve-library-id` followed by `context7-query-docs` when writing or debugging code against `linkml`, `linkml-runtime`, `oaklib`, `pydantic`, `duckdb`, or `pytest`.

## 3. Legal Full-Text Discovery Ladder

When abstract text is insufficient (for example, when curating `growth_media`, `cultivation_setup`, medium variants, or assay conditions), run `CommunityMech/scripts/fulltext_access.py`:

```bash
uv run python CommunityMech/scripts/fulltext_access.py --pmid <pmid>
uv run python CommunityMech/scripts/fulltext_access.py --doi <doi>
```

The ladder checks legal sources in deterministic order:
1. **`zotero_local`** — Read-only SQLite query against `$ZOTERO_DATA_DIR/zotero.sqlite` resolving synced local PDFs in `$ZOTERO_DATA_DIR/storage/<KEY>/*.pdf` by DOI or PMID.
2. **`europepmc_oa`** — Free, anonymous JATS `fullTextXML` from Europe PMC when `isOpenAccess == "Y"`.
3. **`openalex_oa`** — Free, anonymous OpenAlex OA lookup (`best_oa_location` and all `locations`), filtering out bare `doi.org` redirects that bounce to publisher paywalls.
4. **`biorxiv`** — Direct bioRxiv and medRxiv preprint full-text PDF resolution for `10.1101/<suffix>` and `10.64898/<suffix>` DOIs.
5. **`osti_gov`** — Free, anonymous DOE OSTI.gov API (`https://www.osti.gov/api/v1/records`) for DOE and LBNL technical reports and accepted manuscripts.
6. **`elsevier_tdm`** — Elsevier Article Retrieval XML API (`https://api.elsevier.com/content/article/doi/{doi}?httpAccept=text/xml`) for `10.1016/<suffix>` DOIs when `$ELSEVIER_API_KEY` is set.
7. **`springer_tdm`** — Springer Nature JATS API (`https://api.springernature.com/openaccess/jats?q=doi:{doi}`) for `10.1007/<suffix>`, `10.1038/<suffix>`, and `10.1186/<suffix>` DOIs when `$SPRINGER_API_KEY` is set.
8. **`wiley_tdm`** — Wiley TDM API v1 (`https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}`) for `10.1002/<suffix>` and `10.1111/<suffix>` DOIs when `$WILEY_TDM_TOKEN` is set.
9. **`core`** — CORE v3 full-text search when `$CORE_API_KEY` is set.
10. **Author-request draft** — Generates a reviewable plain-text email draft for the curator when no legal full text is reachable.

## 4. LBNL-Licensed Scientific Databases by Domain

| Resource | Access / Endpoint | Target Domains | Primary Curation Use |
| :--- | :--- | :--- | :--- |
| **BioCyc PGDBs** | `https://biocyc.org/` (LBNL IP / VPN subscription) | Pathway, Enzyme, Trait, Culture | Curated pathways, enzyme-substrate-cofactor links, transporters, and defined growth media across 20,000+ sequenced microbes |
| **DOE OSTI.gov** | `https://www.osti.gov/api/v1/records` (anonymous JSON API) | Environment, Community, BioProcess | Full-text DOE/LBNL subsurface, watershed, synbio, and bioprocessing reports |
| **ICSD** | `https://icsd.products.fiz-karlsruhe.de/` (LBNL IP) | MediaIngredient, CMM | Exact hydrate stoichiometry, mineral phases, and inorganic salt crystal structures |
| **WebCSD (CCDC)** | `https://www.ccdc.cam.ac.uk/` (LBNL IP) | CMM, MediaIngredient | Metal-organic chelators, lanthanide/lanmodulin complexes, and siderophore coordination |
| **CHEMnetBASE** | Dictionary of Natural Products / Combined Chemical Dictionary | NaturalProduct, MediaIngredient | Natural product structures, biological sources, CAS numbers, and physicochemical properties |
| **UCB Library Search** | `https://search.library.berkeley.edu/discovery/search?vid=01UCS_BER:UCB` | Every Mech | Springer Protocols, Methods in Enzymology, and Bergey's Manual of Systematics of Archaea and Bacteria |

## 5. Mandatory Privacy, Copyright & Durable State Rules

1. **Zero Email Disclosure:** Never pass an email address (`mailto:` query parameter or `User-Agent` header) to CrossRef, OpenAlex, NCBI E-utilities, Europe PMC, Unpaywall, or OSTI. Always call external APIs anonymously.
2. **No Paywalled Full Text or PDFs in Git:**
   - Use LBNL TDM APIs (`elsevier_tdm`, `springer_tdm`, `wiley_tdm`) and local Zotero PDFs to verify claims and extract short verbatim evidence snippets (`snippet:` in YAML records).
   - Never commit `.pdf` files or copyright-asserted publisher full-text bodies (`All rights reserved`, `© YYYY Elsevier`, etc.) into `references_cache/` or tracked repository directories. Only genuinely open-access (`CC-BY` / `CC0` / Europe PMC OA) source text belongs in `references_cache/`.
3. **Durable Session State:** Never store session state in /tmp, /private/tmp or $TMPDIR. Keep staging bundles, extraction batches, and handoff artifacts in `<repo>/.temp/` or `~/agent-work/<repo>/`.
