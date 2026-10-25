# X-Mech Website Features: Fresh Review And Catalogue (2026-10-25)

This is a dated review of what readers can do on every manifest Mech's website,
measured against the published X-Mech Suite **Website features** catalogue, plus
the features it does not yet catalogue. It records observations, not fixes: the
unification PRs it led to are listed at the end with their state when written.

## Evidence Method

Each live site was exercised in an isolated headless Chrome 156 profile (no user
storage) at 390 and 1280 px: identifier and label search, filters and reset,
counts, sorting, cold reloads of filtered URLs, record pages, term, evidence and
source links, theme persistence across page types, page overflow, and aborted data
requests. Source was read at the pinned commits below through the GitHub API or
fresh scratch clones; no shared checkout was modified. Corpus-wide counts come
from static audits of the committed or deployed pages; interactive checks used
named samples. External resolvers that serve bot checks to headless browsers
(GO/AmiGO, PubMed, Rhea, several publishers) were not judged by their landing page.

The published table on `https://culturebotai.github.io/mechs/` was decoded and
matched its snapshot `_fleet/data/site_features.json` cell for cell (14 Mechs ×
24 keys) at site-repository main `70c3a4d98f1cd18074ad57f2cef6bacf54f20426`,
which was then the deployed revision; the file is byte-identical at
`6035dc2f64056a8cea5db01cd85c82e83b22928b`, merged later that day. Its ratings are dated 2026-10-10–2026-10-14.
Every Mech then merged a `feat/complete-website-features` PR on 2026-10-16, so the
published table no longer describes the sites. Its shared description claims a
404 recovery page and bulk TSV/JSON exports for every Mech; on 2026-10-25 eight
sites still served GitHub's generic 404 and ten offered no complete bulk export.

## Pinned Revisions

| Mech | Reviewed main | Deployed | Site HTML | Fresh P/p/m/na/u | Dated P/p/m/na/u |
| --- | --- | --- | --- | --- | --- |
| AntibioticMech | `d6910f68b7e1` | `d6910f68b7e1` | committed | 15/9/0/0/0 | 17/6/1/0/0 |
| CellStructureMech | `1497f644d596` | `1497f644d596` | committed | 20/4/0/0/0 | 18/3/3/0/0 |
| CommunityMech | `a57df1b23d29` | `0b66cfcb8dd7` | committed | 12/8/3/1/0 | 12/5/6/1/0 |
| CultureMech | `9ea7ff33d354` | `9ea7ff33d354` | mixed | 11/11/2/0/0 | 10/9/5/0/0 |
| DUFMech | `0b3ed0fb1dcb` | `0b3ed0fb1dcb` | ci_built | 22/2/0/0/0 | 24/0/0/0/0 |
| HabitatMech | `d4fc535d46ac` | `d4fc535d46ac` | committed | 12/12/0/0/0 | 12/7/5/0/0 |
| MediaIngredientMech | `cad7f78e5634` | `bd9e7304b960` | mixed | 18/6/0/0/0 | 18/4/2/0/0 |
| NaturalProductMech | `d14547bc76e0` | `d14547bc76e0` | committed | 16/7/1/0/0 | 14/7/3/0/0 |
| PathwayMech | `bbf40d20cb32` | `bbf40d20cb32` | committed | 14/7/2/1/0 | 13/4/6/1/0 |
| ProteinTraitsMech | `66e8f4797339` | `66e8f4797339` | mixed | 15/8/1/0/0 | 15/7/2/0/0 |
| TaxonMech | `e4d6906567eb` | `e4d6906567eb` | committed | 16/8/0/0/0 | 17/4/3/0/0 |
| TraitMech | `340c30479abf` | `340c30479abf` | committed | 19/5/0/0/0 | 18/4/2/0/0 |
| CMMMech | `2d8ce7a1fee9` | `2d8ce7a1fee9` | committed | 14/8/1/1/0 | 13/4/6/1/0 |
| AIMech | `621a86ea8e79` | `621a86ea8e79` | committed | 15/7/1/1/0 | 14/5/4/1/0 |

P/p/m/na/u = present / partial / missing / not applicable / unknown.

## Published Catalogue, Fresh Verdicts

● present · ◐ partial · ○ missing · – not applicable · ? unknown; ↑/↓ = changed from the dated rating.

| Key | AntibioticMech | CellStructureMech | CommunityMech | CultureMech | DUFMech | HabitatMech | MediaIngredientMech | NaturalProductMech | PathwayMech | ProteinTraitsMech | TaxonMech | TraitMech | CMMMech | AIMech | Present |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `search` | ◐↓ | ● | ◐ | ● | ● | ◐ | ● | ● | ● | ● | ● | ● | ◐ | ● | 10/14 |
| `facets` | ◐ | ● | ● | ● | ● | ●↑ | ● | ●↑ | ●↑ | ● | ●↑ | ● | ● | ● | 13/14 |
| `result_counts` | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | 14/14 |
| `sorting` | ●↑ | ◐↑ | ●↑ | ○ | ● | ●↑ | ●↑ | ●↑ | ●↑ | ●↑ | ●↑ | ●↑ | ●↑ | ●↑ | 12/14 |
| `shareable_state` | ●↑ | ●↑ | ●↑ | ●↑ | ● | ●↑ | ◐ | ●↑ | ● | ● | ◐↑ | ● | ●↑ | ● | 12/14 |
| `full_catalogue` | ● | ● | ● | ◐ | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | 13/14 |
| `record_pages` | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | 14/14 |
| `term_links` | ◐ | ◐ | ● | ◐ | ◐↓ | ◐ | ● | ◐ | ◐ | ◐ | ● | ◐ | ◐↓ | ◐↓ | 3/14 |
| `evidence` | ◐↓ | ◐↓ | ◐↓ | ◐ | ◐↓ | ◐ | ◐↓ | ◐ | ◐↓ | ◐↓ | ● | ◐↓ | ◐↓ | ◐↓ | 1/14 |
| `review_status` | ● | ● | ○ | ○ | ● | ● | ● | ● | ○ | ● | ● | ● | ○ | ● | 10/14 |
| `curation_history` | ● | ● | ○ | ● | ● | ◐↓ | ● | ○ | ● | ● | ● | ● | ● | ◐ | 10/14 |
| `source_link` | ● | ● | ●↑ | ◐ | ● | ● | ◐ | ● | ● | ● | ● | ● | ● | ● | 12/14 |
| `domain_view` | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ◐↓ | ● | ◐↑ | ●↑ | 12/14 |
| `cross_mech_links` | ◐↓ | ● | ◐↓ | ◐↓ | ● | ◐↑ | ◐↓ | ◐↓ | ○ | ○ | ◐ | ● | ◐↑ | ○ | 3/14 |
| `corpus_stats` | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | 14/14 |
| `category_browse` | ● | ● | ◐ | ◐ | ● | ● | ●↑ | ● | ◐↑ | ◐ | ● | ● | ● | ● | 10/14 |
| `suite_nav` | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | 14/14 |
| `downloads` | ◐ | ●↑ | ◐ | ◐ | ● | ◐ | ◐ | ◐ | ● | ◐ | ◐ | ●↑ | ◐ | ◐ | 4/14 |
| `schema_docs` | ◐ | ◐ | ●↑ | ●↑ | ● | ◐↑ | ● | ◐↑ | ◐↑ | ● | ◐ | ◐ | ◐↑ | ◐↑ | 5/14 |
| `license` | ● | ● | ◐↑ | ◐↑ | ● | ◐ | ◐↑ | ● | ◐ | ◐ | ● | ◐↑ | ● | ◐ | 6/14 |
| `build_provenance` | ◐ | ●↑ | ○ | ◐↑ | ● | ◐ | ● | ◐ | ◐ | ◐ | ◐ | ● | ●↑ | ●↑ | 6/14 |
| `theme_toggle` | ● | ● | ◐↓ | ◐ | ● | ◐ | ● | ●↑ | ◐ | ◐ | ● | ● | ● | ● | 9/14 |
| `responsive` | ◐↓ | ● | ◐↓ | ◐ | ● | ◐↓ | ● | ◐↓ | ● | ◐ | ◐↓ | ◐ | ◐ | ◐ | 4/14 |
| `load_failure` | ● | ● | – | ● | ● | ◐↓ | ● | ● | – | ● | ◐↓ | ● | – | – | 8/10 |

A ↓ on `evidence` and `term_links` mostly reflects a stricter corpus-wide check
(every page, including notes and causal-graph sections added after the dated audit),
not a regression; each Mech's evidence file says which.

## What The Review Found

- **Linking is the universal gap.** Plain-text PMIDs, DOIs and URLs remained on
  record pages of every site but one, and unlinked CURIEs on all but three, most
  often in causal-graph sections, synonym sources and notes.
- **Shipped features that do not work.** The 2026-10-16 "Explore across X-Mech"
  rows link sibling paths that do not exist (`/TaxonMech/browse.html`,
  `/MediaIngredientMech/app.html`, `/CMMMech/pages/chemicals.html` and others) on
  record pages of most Mechs; several text maps never draw or open a 404 on every
  click; PathwayMech's theme toggle changes nothing; three AntibioticMech filter
  options always return zero.
- **Licence statements.** CommunityMech labels its CC BY 4.0 data BSD-3-Clause on
  every page; CultureMech's footer names only the code licence; AIMech's footer
  implies a data licence for curated concepts that its repository does not grant.
- **Downloads, schema docs and build stamps** are partial on most sites: summary
  indexes rather than complete records, raw schema YAML rather than readable docs,
  and upstream dates rather than a dated version of the site's own records.

Each Mech's evidence file carries the owning source and an acceptance check for
every non-present key.

## Features Beyond The Catalogue

Reviewers listed 229 other reader-facing features. Most are domain displays
(structure viewers, lineage, preparation steps). Ten recur across Mechs, appear
in DisMech or in the design skill, and carry no domain content; they were
defined and rated live on every site:

| Candidate key | Label | Definition | AntibioticMech | CellStructureMech | CommunityMech | CultureMech | DUFMech | HabitatMech | MediaIngredientMech | NaturalProductMech | PathwayMech | ProteinTraitsMech | TaxonMech | TraitMech | CMMMech | AIMech |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `site_search` | Search from any page | The landing page and record pages carry a search box that opens the main listing with the query applied. | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| `breadcrumbs` | Breadcrumbs | Record and subset pages show a linked trail back to the listing and the record's category or parent. | ● | ● | ○ | ○ | ◐ | ● | ◐ | ● | ● | ◐ | ◐ | ● | ● | ● |
| `not_found_page` | Not-found page | A missing URL anywhere on the site returns HTTP 404 with the site's own page, offering navigation or search back into the site. | ● | ○ | ◐ | ◐ | ○ | ● | ◐ | ● | ○ | ○ | ○ | ○ | ○ | ○ |
| `skip_link` | Skip link | The first keyboard stop on each page is a link that skips to the main content. | ○ | ○ | ◐ | ◐ | ● | ● | ○ | ○ | ● | ○ | ○ | ○ | ○ | ○ |
| `visual_alternative` | Text alternative for visuals | Every map, diagram or graph has a table or list alternative a keyboard or screen-reader user can reach, listing what the visual shows with record links. | ○ | ○ | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | ○ | ○ | ● | ◐ | ◐ |
| `no_js_fallback` | Works without JavaScript | With JavaScript disabled, the listing still reaches every record and record pages still show their content, or the page says plainly that it needs JavaScript. | ◐ | ● | ● | ◐ | ● | ◐ | ◐ | ● | ● | ○ | ◐ | ● | ● | ● |
| `text_map` | Text embedding map | A map of the corpus projected from text embeddings (the fleet's shared embedding sets), with search and filters, where clicking a point opens its record. | ● | ● | ◐ | ◐ | ● | ● | ◐ | ◐ | ◐ | ● | ○ | ● | ◐ | ◐ |
| `discussions` | Open questions | Record pages show the record's open questions or knowledge gaps with their status, and an index links them across the corpus. | ◐ | ◐ | ◐ | – | ◐ | – | ◐ | ◐ | – | – | – | ● | – | – |
| `curation_notice` | Curation notice | The site says how its records were produced (for example AI-assisted curation or import) and what each curation status means, including that a workflow status is not a human review where that is the case. | ● | ○ | ○ | ◐ | ● | ● | ○ | ◐ | ○ | ◐ | ◐ | ◐ | ○ | ◐ |
| `feedback_route` | Report a problem | Each record page offers a route to report an error or suggest an edit, such as a prefilled GitHub issue or an edit link for the record's file. | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● | ○ | ○ |

Search from any page is already universal. A per-record route to report a
problem exists only on TraitMech; skip links, not-found pages and text
alternatives for maps are the next largest gaps.

## DisMech Comparison

DisMech (`monarch-initiative/dismech` main `e1ede1b1f4e0`) was inventoried at
reader-task level: 60 features, 10 of them disease-specific.
It has no counterpart for linkable search state, a theme toggle or cross-Mech
links, and shows record review status only in source. Of its features with no
X-Mech key, breadcrumbs, a report-a-problem route, AI-curation notices, keyboard
support and knowledge-gap pages informed the candidates above; the rest (search
match context, record dates, section summary bars, item deep links, inline source
records, hypothesis status, gene and model pages, reader and contributing guides)
remain uncatalogued observations.

## Limits

- Interactive checks sampled named records; corpus-wide claims rest on static
  audits of every page where stated, and on bounded samples for the two largest
  corpora (ProteinTraitsMech and TaxonMech).
- Keyboard checks covered Tab reachability; changing a select with arrow keys did
  not register in headless Chrome and is unverified. No screen-reader testing.
- Contrast was not measured beyond what the reviews state.
- Sites redeployed during the review; each evidence file names the revision its
  checks ran on.
