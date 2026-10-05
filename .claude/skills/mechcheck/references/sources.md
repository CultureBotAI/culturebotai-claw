# MechCheck Sources

These are discovery entry points, not a frozen feature inventory. Follow moved
sources and newly linked catalogues, recording redirects and version changes.

## DisMech

Repository: [monarch-initiative/dismech](https://github.com/monarch-initiative/dismech).
Resolve its current default branch and commit through the repository API; do
not assume a checkout or search-engine excerpt is current.

Start with its [README](https://github.com/monarch-initiative/dismech/blob/main/README.md),
[documentation index](https://github.com/monarch-initiative/dismech/blob/main/docs/index.md),
and [detailed feature guide](https://dismech.monarchinitiative.org/details/).
The guide's maintained source is
[details/index.html](https://github.com/monarch-initiative/dismech/blob/main/details/index.html).
It covers record sections, interface behavior, data products, tools, providers,
and automation; it is not just a list of schema fields.

Discover any explicit feature catalogue from the current root and documentation
trees. If there is no maintained exhaustive catalogue, derive the inventory
from those entry points and reconcile it against the repository's schema,
package CLI entry points, recipes, workflows, skills, tests, and published
products. Label this inventory derived; naming it a complete official feature
list would overstate the source. Record inspected surfaces and limitations.

Read [design decisions](https://github.com/monarch-initiative/dismech/blob/main/docs/explanation/design-decisions.md)
for applicability and contract semantics, not a historical freeze of current
implementation. Keep upstream experimental/planned items distinguishable from
shipped features. Do not count individual diseases, records, or ontology terms
as software features, or treat record coverage metrics as implementation proof.

## X-Mech Matrix

Published page: [CultureBotAI X-Mech Suite](https://culturebotai.github.io/mechs/).
Maintained site repository:
[CultureBotAI/culturebotai.github.io](https://github.com/CultureBotAI/culturebotai.github.io).

Useful source paths, resolved at the site's inspected commit:

- [Generated page](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/mechs.md)
  and [page template](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/_fleet/mechs_template.md).
- [Capability snapshot](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/_fleet/data/manifest.json):
  `capability_catalogue` supplies keys/definitions, `mechs` supplies identities
  and declarations, and `source` names the exact upstream CLAW revision/URL.
- [Page assembler](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/scripts/fleet/assemble_page.py):
  explains the current column labels, row set, and status encoding.
- [Site audit](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/_fleet/data/site_audit.json):
  supplies dated source evidence. It is not proof of what is currently deployed.

Read the capability matrix, not the separate vocabulary-occurrence heatmap.
In the current markup its table class is `fleet-caps`. Cells encode status in
`title` and `aria-label`; plain-text extraction can make all cells look empty.
Use the structured snapshot and an HTML parser or rendered-page inspection to
recover meanings and reasons. Do not interpret color, blank text, a missing
row, or an unfamiliar status as disabled. Preserve undecodable cells as unknown.

The page can include Mechs absent from its snapshot's manifest. Retain those
rows as undeclared, and distinguish them from disabled and not-applicable rows.
Enumerate columns dynamically; neither the feature count nor member count is
fixed. Extra features described elsewhere on the page may be reported as
supplemental findings, without quietly changing the matrix denominator.

Fetch the live page, not only its search-index rendering. Compare it with the
source snapshot and available Pages build/deployment metadata. If the live page
and site main differ, retain the published matrix baseline and label the newer
source separately. If their correspondence cannot be established, report that
uncertainty; do not describe site-main JSON as the verified deployed matrix.

Separately obtain the current published
[CLAW manifest](https://github.com/CultureBotAI/culturebotai-claw/blob/main/src/kg_microbe_fleet/fleet.yaml).
Show added/removed members, new/retired capability keys, changed definitions,
states, settings, and reasons. Preserve the page's original values. A renamed
key requires an explicit supported mapping; do not silently merge similar labels.
A retained key with a changed definition also needs two independent target
verdicts, one for each pinned contract. Never transfer a verdict by key alone.

## Acquisition Pattern

Use read-only, structured API responses. For a verified repository identity:

```bash
gh api "repos/$REPOSITORY" --jq '{full_name,default_branch}'
gh api "repos/$REPOSITORY/commits/$DEFAULT_BRANCH" --jq .sha
gh api "repos/$REPOSITORY/contents/$PATH_IN_REPO?ref=$SHA" \
  -H 'Accept: application/vnd.github.raw+json'
gh api "repos/$REPOSITORY/git/trees/$SHA?recursive=1"
```

Record the returned full SHA once; use it in all subsequent content reads and
source permalinks. Check `truncated` before trusting a recursive tree. Paginate
collection endpoints where applicable. Log missing permissions, unavailable
sources, and partial inventories. Prefer JSON/YAML/HTML parsers over scraping
table text with regular expressions. Never print credentials or invoke a
workflow, provider, upload, or repository mutation while acquiring evidence.
