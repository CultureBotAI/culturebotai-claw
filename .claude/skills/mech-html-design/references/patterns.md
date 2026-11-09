# Existing Mech HTML patterns

These source locations were inspected in the October 2026 fleet audit. Resolve
the current revision when using them. They describe reusable decisions, not a
claim that every page in an example repository implements every behavior.

| Reader task | Existing model and source | What to reuse | What stays local |
|---|---|---|---|
| Scan the project and choose a view | [TraitMech templates](https://github.com/CultureBotAI/TraitMech/tree/main/src/traitmech/templates), especially index and base | Hero, generated corpus counts, category cards, consistent navigation, local palette tokens | Corpus terminology, artwork, categories and metrics; counts must come from the same data surface they describe |
| Search a moderate catalogue | [AntibioticMech class template](https://github.com/CultureBotAI/AntibioticMech/blob/main/src/antibioticmech/templates/class.html) | Labelled full-class search, live count, visible load failure, semantic table headers, static pagination fallback | How data is indexed and which properties a class exposes |
| Browse a very large corpus | [ProteinTraitsMech browser](https://github.com/CultureBotAI/proteintraitsmech/tree/main/docs) and [TaxonMech browser source](https://github.com/CultureBotAI/TaxonMech/blob/main/src/taxonmech/templates/taxon-browser.js) | Sharded indexes, progressive data loads, filters, explicit failures, stable record routes and lazy details | Shard boundaries, axis/facet definitions, sequence and taxon fields; preserve corpus-wide search semantics |
| Explore faceted recipe or community data | [CultureMech browser](https://github.com/CultureBotAI/CultureMech/blob/main/app/browser.html) and [CommunityMech templates](https://github.com/CultureBotAI/CommunityMech/tree/main/src/communitymech/templates) | Search plus category facets, active-filter summary, clear-all and linked result cards | Recipe ingredients and units versus community members and interactions; test keyboard controls rather than copying onclick markup |
| Inspect evidence behind a record | [CellStructureMech structure template](https://github.com/CultureBotAI/CellStructureMech/blob/main/src/cellstructuremech/templates/structure.html), [TraitMech record template](https://github.com/CultureBotAI/TraitMech/blob/main/src/traitmech/templates/trait.html), [AntibioticMech record template](https://github.com/CultureBotAI/AntibioticMech/blob/main/src/antibioticmech/templates/record.html) | Label plus CURIE, definitions, evidence/provenance, source record link, graph/table alternatives | Which claim each citation supports, relationship direction, reviewed versus imported status |
| Compare tabular data on a small screen | [TaxonMech templates](https://github.com/CultureBotAI/TaxonMech/tree/main/src/taxonmech/templates) | Semantic table inside a named, keyboard-scrollable region, with wrapping of prose and long identifiers | Column priority and which values must remain aligned; preserve data rather than hiding columns to make the viewport fit |
| Move between projects | [Maintained Mech directory](https://culturebotai.github.io/mechs/) | A visible All Mech projects link from the project shell | Useful direct sibling links and the current repository's visual identity |
| Keep a selected theme | Existing local theme-toggle scripts and CSS in the repositories above | Reuse the same storage key, early theme initialization and semantic toggle across views | Brand colors; test the real page/card/button surfaces in every declared theme |

## Patterns that need domain evidence

Chemical maps need stable structure identifiers and a fallback list. Protein
views need source-aware coordinate and sequence semantics. Causal graphs need
explicit nodes, typed edges, direction and linked evidence. An embedding plot
shows similarity under its documented representation, not a measured biological
mechanism. Reuse interaction controls without flattening these meanings.

Do not turn absent scientific content into placeholder claims to complete a
layout. Display unknown or unavailable states honestly, and preserve distinctions
between reviewed records, imported records, candidates and seed worklists.

## A compact audit row

Record the repository and immutable SHA; public entry and detail URLs; the
template/builder/assets that own them; display, navigation and interaction
coverage; demonstrated gaps and applicability; existing issue/PR; acceptance
criteria; checks and rendered artifacts. Keep the matrix in the task report or
issue tracker rather than freezing changing counts into this skill.

For a missing search control, for example, the useful evidence is that a reader
cannot locate a known identifier across the advertised catalogue, followed by
a browser test that finds it after the change. A substring test for the word
search in a template does not establish that behavior.
