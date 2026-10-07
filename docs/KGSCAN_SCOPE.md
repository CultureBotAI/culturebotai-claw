# Knowledge-gap scan scope

The scheduled Europe PMC knowledge-gap scan covers CultureMech, TraitMech,
MediaIngredientMech, and CommunityMech. Each has a `Discussion` slot and a
bounded corpus where rotating windows converge.

Capability availability is separate from eligibility for this live schedule.
An offline adapter that requires an explicitly retained abstract cache declares
`knowledge_gap_scan.settings.scheduled: false`. It remains visible in ordinary
capability queries and matrices but is excluded by the nightly workflow's
`matrix --capability knowledge_gap_scan --setting window --scheduled-only`.
Omitting `scheduled` preserves legacy eligibility; explicit `true` also opts in.
The setting must be a real boolean. A filtered matrix with no eligible Mechs
fails closed instead of emitting an unusable job matrix.

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
