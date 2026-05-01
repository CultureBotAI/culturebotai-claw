# Phase 5: mkdocs Material + browser parity across MIM/CommunityMech

**Status:** Draft
**Audience:** MIM and CommunityMech maintainers
**Date:** 2026-05-01
**Source pattern:** dismech `mkdocs.yml` + Material theme + mermaid2 plugin + `app/` faceted browser + `BrowserExporter` (`src/dismech/export/browser_export.py`)

## Goal

Bring MIM and CommunityMech up to **parity with dismech's docs site
and faceted browser**:

- Material-themed mkdocs replacing MIM's legacy Jekyll minimal
- mermaid2 plugin enabling inline relationship diagrams
- A shared `kg_microbe.export.browser_exporter` module so all repos use
  the same null-handling, facet-naming, pagination conventions
- Per-ingredient detail pages in MIM (mirroring Phase 2's CultureMech
  per-media pages)

This phase is **the polish layer** — by the time it lands, every mech
repo has consistent UI/UX, a shared component library for browser
exports, and Mermaid diagrams illustrating ingredient ↔ medium ↔
community relationships across the three repos.

## Scope

**In scope:**
- mkdocs Material site for MIM (replaces Jekyll)
- mkdocs Material site for CommunityMech (greenfield)
- mermaid2 plugin enabled in CultureMech, MIM, CommunityMech
- Shared `kg_microbe.export.browser_exporter` package in claw
- MIM per-ingredient HTML detail pages (`pages/ingredient/<slug>.html`)
- CommunityMech per-community detail pages
- Shared mermaid graph builder (`kg_microbe.graph` module)

**Out of scope:**
- CultureMech Jekyll → Material migration (CultureMech doesn't have
  Jekyll today; it has the empty `dashboard/` and `app/`)
- Custom theme branding (use Material defaults)
- Custom search engine (Material's built-in search is sufficient)
- Cross-repo merged search (separate effort; would need a unified
  index)

## Critical files

| Path | Kind | Reason |
|---|---|---|
| `MediaIngredientMech/mkdocs.yml` | NEW | Replaces `_config.yml` |
| `MediaIngredientMech/docs/index.md` | NEW | Material homepage |
| `MediaIngredientMech/docs/{schema,about,curation}.md` | NEW | Nav pages |
| `MediaIngredientMech/src/mim/render.py` | NEW | Per-ingredient page render driver |
| `MediaIngredientMech/src/mim/templates/ingredient.html.j2` | NEW | Page template |
| `MediaIngredientMech/.github/workflows/deploy-docs.yaml` | NEW | mkdocs build → gh-pages |
| `CommunityMech/CommunityMech/mkdocs.yml` | NEW | Same |
| `CommunityMech/CommunityMech/docs/{index,schema,community}.md` | NEW | Same |
| `CommunityMech/CommunityMech/src/communitymech/render.py` | NEW | Per-community page renderer |
| `culturebotai-claw/src/kg_microbe_browser/browser_exporter.py` | NEW PKG | Shared browser exporter |
| `culturebotai-claw/src/kg_microbe_browser/graph.py` | NEW | Mermaid graph builder |
| `MediaIngredientMech/_config.yml` | DELETE | After migration |

## Site structure (consistent across all 3 repos)

Each mech repo's mkdocs site uses the same nav skeleton:

```
- Home (index.md)
- Schema / Ontology
- Browser (links to app/index.html)
- Curation Guide
- API / Downloads (KGX, SSSOM)
- About
```

Material theme features turned on:

- search (full-text, instant)
- navigation.instant (SPA-like)
- content.code.copy
- toc.integrate
- mermaid2 plugin (v11+)

## Shared `kg_microbe_browser` package design

Refactors dismech's `BrowserExporter` into a generalizable base class:

```python
class BrowserExporter:
    def __init__(self, schema_path, yaml_dir, output_path):
        ...
    def extract_facets(self, record) -> dict:
        """Override per-repo to define facets."""
        raise NotImplementedError
    def extract_searchable_text(self, record) -> str:
        """Override per-repo."""
        raise NotImplementedError
    def export(self):
        """Walks YAMLs, applies extract_*, writes data.js."""
        ...
```

Per-repo subclasses:

| Repo | Subclass | Facets |
|---|---|---|
| MIM | `MIMIngredientBrowser` | ontology source, mapping_quality, evidence_type, occurrence count buckets |
| CultureMech | `CultureMechMediaBrowser` | source DB, medium type, organism count, sterilization |
| CommunityMech | `CommunityBrowser` | environment, ecosystem, member microbe count, pH range |

Each subclass is ~30-50 LoC. Null-handling + pagination + debounce live
in the base class.

## Mermaid graph builder

`kg_microbe_browser.graph` produces Mermaid syntax embeddable in
mkdocs pages and per-record HTML pages:

```python
def build_ingredient_composition_graph(medium_yaml) -> str:
    """Returns Mermaid flowchart: medium → ingredients → CHEBI."""

def build_community_membership_graph(community_yaml) -> str:
    """Returns Mermaid flowchart: community → microbes (+strains)."""

def build_cross_repo_link_graph(mim_id) -> str:
    """Returns Mermaid: an ingredient's appearances in CultureMech
       media + CommunityMech communities."""
```

## Execution order

1. **Shared package**: extract dismech's `BrowserExporter` to
   `culturebotai-claw/src/kg_microbe_browser/`. Add the base class
   above; convert dismech's logic into the default extract_facets/
   extract_searchable_text pair (so a `DismechBrowser` subclass also
   works — but we don't actually port dismech back).
2. **MIM Material migration**: write `mkdocs.yml`, port content from
   Jekyll site. Verify GitHub Pages deploy works on a feature branch
   first. Delete `_config.yml` only after the new site is live.
3. **MIM per-ingredient pages**: port template + render.py from
   Phase 2's CultureMech work. Same Jinja2 structure, ingredient
   slots instead of media slots. Deploy under `pages/ingredient/`.
4. **MIM browser**: subclass `BrowserExporter` as
   `MIMIngredientBrowser`; emit `app/data.js`; copy faceted-browser
   HTML/JS from dismech.
5. **CommunityMech mkdocs**: greenfield setup; same structure as MIM.
6. **CommunityMech per-community pages**: same pattern as MIM
   ingredients. Embed Mermaid composition graphs.
7. **CommunityMech browser**: subclass `BrowserExporter` as
   `CommunityBrowser`; emit `app/data.js` + faceted browser.
8. **CultureMech browser refactor**: port CultureMech's existing 15 MB
   `app/data.js` to use the shared `BrowserExporter`. Maintains
   feature parity but eliminates duplicated null-handling logic.
9. **mermaid2 in CultureMech mkdocs**: enable plugin (CultureMech
   has `docs/` already; assume mkdocs is or will be configured per
   Phase 2). Embed `build_ingredient_composition_graph` outputs.
10. **deploy-docs.yaml** in each repo: standard mkdocs build →
    gh-pages workflow. Triggered on push to main when docs/ or
    mkdocs.yml change.

## Verification

After step 4:
- MIM site live at `https://<org>.github.io/MediaIngredientMech`
- 1,730 per-ingredient pages exist; spot-check 5 (links to CHEBI
  resolve, CAS-RN displayed, evidence section populated when Phase 1
  has provided data)
- `app/index.html` faceted browser: search "glucose" returns the right
  records; facets work; "show 8+" toggle works

After step 7:
- CommunityMech site live; 35 per-community pages; Mermaid graphs
  render

After step 10:
- Pushing a docs/ edit triggers redeploy within 5 min on each repo

## Effort estimate

| Step | Hours |
|---|---:|
| Extract shared `kg_microbe_browser` | 16 |
| MIM mkdocs migration | 12 |
| MIM per-ingredient pages | 16 |
| MIM browser subclass | 8 |
| CommunityMech mkdocs setup | 8 |
| CommunityMech per-community pages | 12 |
| CommunityMech browser subclass | 8 |
| CultureMech browser refactor | 12 |
| Mermaid graph builder + integration | 16 |
| deploy-docs workflows × 3 | 6 |
| **Total** | **~114** |

## Why this is Phase 5 (last)

- Dependencies on Phase 1 (evidence section in pages is empty without
  it) and Phase 2 (CultureMech HTML pattern serves as the template
  baseline)
- Lowest blast radius if it slips — the data and exports work fine
  without polished docs sites
- Maximum cross-repo consistency comes once everything else is in
  place; doing it earlier would mean re-doing it as schemas evolve

## What's deferred beyond Phase 5

- Cross-repo unified search (one index, three repos)
- Custom theme / branding aligned with kg-microbe ecosystem
- Versioned docs (mkdocs-material insiders feature) — only if needed
- Live SPARQL/GraphQL endpoint over the merged KGX
