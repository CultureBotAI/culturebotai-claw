# Knowledge-gap scan scope

The scheduled Europe PMC knowledge-gap scan covers CultureMech, TraitMech,
MediaIngredientMech, and CommunityMech. Each has a `Discussion` slot and a
bounded corpus where rotating windows converge.

ProteinTraitsMech is intentionally excluded. Its 424,000-plus records are
ontology-derived trait classes, not individually curated biological entities;
they have no `discussions` field in the schema. At the current 300-record window,
one pass would require more than 1,400 runs. Adding a dry-run-only matrix leg
would imply coverage it cannot deliver, while enabling `--apply` would write a
field the schema rejects.

ProteinTraitsMech instead scopes research by source, category, trait axis, and
selected records through its deep-research skills. Revisit scheduled kgscan only
if it gains a Discussion-bearing curated subset with a bounded, measurable work
queue. This is an explicit non-applicability decision, not an omitted fifth leg.
