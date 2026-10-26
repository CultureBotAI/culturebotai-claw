# X-Mech website features

Every Mech that publishes a website is judged against one feature catalogue:
the **Website features** table on the [X-Mech Suite page](https://culturebotai.github.io/mechs/),
generated from `_fleet/data/site_features.json` in
`CultureBotAI/CultureBotAI.github.io`. That file owns each feature's key,
label, definition and criteria, and the dated per-site ratings. This guide does
not redefine a key. It says which features every site is expected to provide,
what counts as done, and which existing implementation to copy.

Two skills do the work: [`mech-html-review`](../../.claude/skills/mech-html-review/SKILL.md)
audits a live site against the catalogue, and
[`mech-html-design`](../../.claude/skills/mech-html-design/SKILL.md) guides the
source-level fix. The dated fleet review that produced this guide is
[`docs/reviews/2026-10-25-xmech-website-feature-review.md`](../reviews/2026-10-25-xmech-website-feature-review.md).

## Applicability

A feature applies when its reader task exists on the site. Do not add
placeholder UI to fill a column, and do not mark a feature present from markup
alone: a verdict needs the reader action exercised in a browser.

The catalogue's domain features are decided per Mech: `facets`,
`category_browse`, `domain_view` and `cross_mech_links` depend on what the data
supports. A dark theme, a map or a graph is not a universal requirement merely
because a sibling has one. `review_status` and `curation_history` apply when the
records carry that data, which every Mech's vendored `history.yaml` makes
possible; a site whose records carry none is `not_applicable` with the reason.

## The unified set

These features have no domain content, so every publishing Mech is expected to
provide them. "Done" is the acceptance check, applied to the deployed site.
Some checks are stricter than the catalogue's criteria: the catalogue rates
`evidence` present when a record page links each reference it shows, while this
guide asks for every PMID, DOI and URL on the page to be a link. A site can
therefore be rated present and still have work to do here.

| Key | Done when | Reference implementation |
|---|---|---|
| `search` | The main listing finds a record by its own identifier and by its label, and by other identifiers shown on its card. | DUFMech `src/dufmech/dashboard.js` |
| `result_counts` | An `N of M` count updates with search and filters, distinct from the total. | DUFMech, TraitMech browse |
| `sorting` | A labelled sort control (or sortable headings with `aria-sort`) on the main listing changes the order, before paging, by keyboard, and is part of the URL state. | DUFMech `#family-sort`; TraitMech browse |
| `shareable_state` | Search, filters and sort are written to the URL and a cold load restores every control and the same results; reset clears them; unknown values fall back safely. | DUFMech `restore()`/`writeState()`; TraitMech browse |
| `full_catalogue` | Every record the site counts is reachable from it, including any second listing the landing page counts. | — |
| `record_pages` | Each record has a stable, linkable page. | — |
| `source_link` | Each record page links its own source YAML on GitHub. | TraitMech Source card |
| `evidence` | PMIDs, DOIs and URLs shown anywhere on a record page are links, including notes and synonym sources. One escaping-safe autolink filter, applied to already-escaped record text, does this; documentation prose with format examples stays plain. | TaxonMech record pages |
| `term_links` | Every displayed CURIE has a readable label when the record carries one and links to a resolver; a CURIE naming one of the Mech's own records links to that page. Unknown prefixes fall back to `https://bioregistry.io/<CURIE>`; nothing links to `#`. | MIM and TaxonMech record pages for labelled resolver links; the bioregistry fallback is new in the unmerged [TraitMech](https://github.com/CultureBotAI/TraitMech/pull/2021) and [DUFMech](https://github.com/CultureBotAI/DUFMech/pull/368) unification PRs |
| `corpus_stats` | The landing page shows counts generated from the same data the site lists. | — |
| `suite_nav` | A visible link to the X-Mech Suite directory. | — |
| `downloads` | A page in the main navigation links a bulk machine-readable export of every complete record, with its count and checksum. | TraitMech `pages/data/traits.json`; DUFMech Sources page; PathwayMech KGX exports |
| `schema_docs` | A visible link to readable schema documentation generated from, or verified current with, the LinkML schema. A raw YAML link alone stays partial. | MediaIngredientMech `schema/`; DUFMech `schema.html` |
| `license` | Every page type states the data and code licences exactly as the repository's licence files do, links them, and notes that third-party material keeps its own terms. | DUFMech and AntibioticMech footers |
| `build_provenance` | Aggregate pages state a dated version of the corpus, and record pages state their own record's last-update date, both derived deterministically so an unchanged re-render is byte-identical. A corpus-wide date or digest on every record page rewrites every page on each curation commit and makes concurrent record PRs conflict. | TraitMech ("Corpus as of" on aggregate pages, record dates on records) |
| `responsive` | No page reachable from the navigation, the listing or a record overflows at 390 px, and no sticky element covers the content while scrolling; wide tables scroll inside a named, focusable region; long identifiers and headings wrap. | CellStructureMech and MediaIngredientMech |

### Wherever the feature exists

These apply only where their reader task exists, so they are not required of a
site that lacks it. Where the site has the thing, it must work.

| Key | Applies when | Done when | Reference implementation |
|---|---|---|---|
| `theme_toggle` | The site styles a dark theme (every current site does) | A user-operated light/dark choice persists, under the `mech-theme` storage key, across every linked page type, including standalone maps and reports, and visibly changes the page in both themes. | TraitMech, AntibioticMech |
| `cross_mech_links` | A page links a sibling Mech | The link resolves and applies its query; an NCBITaxon identifier opens its TaxonMech record. New relations are a per-Mech decision. | The route table below |
| `load_failure` | A page fetches data | A failed request shows an error and a recovery route, never an empty result. | ProteinTraitsMech browse |

## Candidate features

The 2026-10-25 review found features the catalogue does not yet have. These ten
recur across Mechs, appear in DisMech or in the design skill, and carry no
domain content. They are rated for every Mech in the
[review record](../reviews/2026-10-25-xmech-website-feature-review.md#features-beyond-the-catalogue)
and are proposed for the published catalogue; until it adopts them, treat them as
expected wherever their reader task exists.

| Key | Label | Definition | Criteria |
|---|---|---|---|
| `site_search` | Search from any page | The landing page and record pages carry a search box that opens the main listing with the query applied. | Present: both the landing page and record pages hand off a query that the listing restores and applies. Partial: only one of them, or the query arrives but is not applied. Does not apply: the site has no listing search. |
| `breadcrumbs` | Breadcrumbs | Record and subset pages show a linked trail back to the listing and the record's category or parent. | Present: every record page has a trail whose links resolve. Partial: some page types only, or links that do not resolve. |
| `not_found_page` | Not-found page | A missing URL anywhere on the site returns HTTP 404 with the site's own page, offering navigation or search back into the site. | Present: missing URLs at the site root and under its page directories get the themed page with working recovery links. Partial: only some paths, or the page lacks the theme or recovery links. Missing: GitHub's generic 404. |
| `skip_link` | Skip link | The first keyboard stop on each page is a link that skips to the main content. | Present: landing, listing and record pages each start with a skip link whose target exists in main. Partial: some page types only. |
| `visual_alternative` | Text alternative for visuals | Every map, diagram or graph has a table or list alternative a keyboard or screen-reader user can reach, listing what the visual shows with record links. | Present: every visual on the site has one. Partial: some visuals only. A link to the general listing does not count: the alternative must list what that visual shows. Does not apply: the site has no maps, diagrams or graphs. |
| `no_js_fallback` | Works without JavaScript | With JavaScript disabled, the listing still reaches every record and record pages still show their content, or the page says plainly that it needs JavaScript. | Present: listing and record content render without JavaScript. Partial: record pages render but the listing is empty, or a page fails silently. Missing: blank pages with no message. |
| `text_map` | Text embedding map | A map of the corpus projected from text embeddings (the fleet's shared embedding sets), with search and filters, where clicking a point opens its record. | Present: the map renders, plots every record the site counts or states which are left out, and point clicks open the right record. Partial: renders but clicks fail, records are silently missing, or it does not render for some readers. Missing: a map is published but renders for no reader. Does not apply: no text map is published. |
| `discussions` | Open questions | Record pages show the record's open questions or knowledge gaps with their status, and an index links them across the corpus. | Present: records that carry discussions show them and a linked index lists them. Partial: shown on records but the index is unlinked or empty, or the index exists without record display. Does not apply: no record carries discussions. |
| `curation_notice` | Curation notice | The site says how its records were produced (for example AI-assisted curation or import) and what each curation status means, including that a workflow status is not a human review where that is the case. | Present: stated on the landing page or footer and explained beside the status on record pages. Partial: one of the two only. |
| `feedback_route` | Report a problem | Each record page offers a route to report an error or suggest an edit, such as a prefilled GitHub issue or an edit link for the record's file. | Present: every record page has a working route. Partial: a site-wide route only, or one that does not identify the record. |

A not-found page deserves one note: GitHub Pages serves the project's single
root `404.html` for a missing URL at any depth, so its links and assets must not
be relative. Use site-root-absolute paths (`/<Repo>/…`) or full
`https://culturebotai.github.io/<Repo>/…` URLs. Claw's site check cannot yet
resolve the `/<Repo>/` form (claw #667), so a Mech whose `404.html` is inside
the checked tree uses full URLs for now. The CommunityMech, CultureMech and
MediaIngredientMech 404 pages break below the root because their links are relative.

## Sibling routes

Record pages hand readers to sibling Mechs. Use these routes, each checked live
on 2026-10-25 to load and apply its query; a guessed path such as
`/TaxonMech/browse.html` returns GitHub's 404. Use the query string: the `#q=`
form is ignored by CultureMech, MediaIngredientMech and CommunityMech.

| Mech | Search (append the URL-encoded query) | A specific record |
|---|---|---|
| CultureMech | `CultureMech/app/browser.html?q=` | |
| MediaIngredientMech | `MediaIngredientMech/browser.html?q=` | |
| CommunityMech | `CommunityMech/browser.html?q=` | |
| TraitMech | `TraitMech/pages/browse.html?q=` | |
| ProteinTraitsMech | `proteintraitsmech/browse.html?q=` | |
| AntibioticMech | `AntibioticMech/pages/browse.html?q=` | |
| CellStructureMech | `CellStructureMech/pages/browse.html?q=` | |
| HabitatMech | `HabitatMech/pages/browse.html?q=` | |
| NaturalProductMech | `NaturalProductMech/pages/browse.html?q=` | |
| TaxonMech | `TaxonMech/pages/browse.html?q=` | `TaxonMech/pages/taxon.html?id=NCBITaxon:<n>` |
| PathwayMech | `PathwayMech/pages/browse.html?q=` | |
| DUFMech | `DUFMech/index.html?q=<query>#families` | |
| CMMMech | `CMMMech/pages/browse.html?q=` | |
| AIMech | `AIMech/pages/browse.html?q=` | |

All paths are under `https://culturebotai.github.io/`. A renderer that emits
sibling links should be tested against this list, since a test cannot reach
the network and a wrong path fails silently on every record page.

## Licences

Read the licence files rather than assuming the intended fleet policy, which is
unresolved (claw #394). Every Mech except AIMech carries `LICENSE` (scope),
`LICENSE-DATA` (CC BY 4.0) and `LICENSE-CODE` (BSD-3-Clause). The footers do not
all say so: on 2026-10-25 CommunityMech labelled its data BSD-3-Clause, CultureMech
named only the code licence, and the footers of HabitatMech, MediaIngredientMech,
PathwayMech, ProteinTraitsMech and TraitMech were incomplete on some page types.
AIMech is the exception: its `LICENSE` is the BSD-3-Clause code licence and its
`LICENSE-DATA` covers only AIO-derived records under `data/aio`, so its site
must not imply a data licence for its curated concepts.

## Implementing a change

- Change the owning renderer, template, stylesheet or script and regenerate
  tracked output with the repository's builder. Never hand-edit generated HTML.
- Keep each Mech's palette, landing structure and scientific displays. Use the
  existing tokens, and keep both dark-theme blocks in step: CSS never fails
  loudly, so an override that misses one block passes every gate.
- Escape at the rendering boundary. Query strings and record text are text.
- A site whose HTML is committed and checked for freshness must render
  deterministically: no wall-clock time in its output.
- A corpus-wide export file regenerated on every record change conflicts with
  every concurrent record PR. Where Pages is deployed by a workflow, generate the
  export in that workflow at deploy time, even when the pages themselves are
  committed, and run any site check after it. For a branch-deployed site or a
  corpus too large for Pages, the export route is a separate decision.
- Respect the Mech's declared page budget.
- Follow the [cross-repository checklist](../../CLAUDE.md) and
  [`cross-mech-sync`](../../.claude/skills/cross-mech-sync/SKILL.md): an
  isolated worktree off `origin/main`, one PR per repository.

## Recording the result

A merged PR is not a verified feature. After deployment, re-run
`mech-html-review` on the live site and refresh `site_features.json` through the
site repository's own change process, so the published table shows the dated,
browser-checked verdict rather than the intent.
