# HTML Review Sources

These are maintained discovery entry points, not a frozen feature list.
Resolve default branches and full SHAs through repository APIs, then read source
files at those SHAs. Fetch actual deployed HTML, not just search-index text.
Record redirects, retrieval UTC times, content hashes, and access failures.

## DisMech UI

- [Live DisMech](https://dismech.monarchinitiative.org/)
- [UI and record-page guide](https://dismech.monarchinitiative.org/details/)
- [Source repository](https://github.com/monarch-initiative/dismech)
- [Guide source](https://github.com/monarch-initiative/dismech/blob/main/details/index.html)

Follow current navigation to discover catalogue, detail, category, and
specialized views. Inspect real populated records rather than treating the
guide's synthetic example as proof of deployed record behavior. Trace controls
and page sections to their maintained templates/scripts when evidence is
ambiguous. Documentation helps discover features but does not establish that a
control works, a section is populated, or a feature is deployed.

Describe the resulting inventory as derived unless upstream supplies a
maintained exhaustive UI catalogue. Record which navigation routes, templates,
and record types were inspected. Keep domain-specific sections visible with an
applicability decision, and retain observed UI functions absent from the guide.
Research launchers may be inspected but must not be invoked during this audit.

## X-Mech Website Matrix

- [Published X-Mech Suite page](https://culturebotai.github.io/mechs/), specifically
  the **Website features** table and its criteria/evidence disclosure.
- [Structured website-feature snapshot](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/_fleet/data/site_features.json)
- [Generated page source](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/mechs.md)
- [Page template](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/_fleet/mechs_template.md)
- [Page assembler](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/scripts/fleet/assemble_page.py)

The snapshot currently uses:

| Field | Purpose |
| --- | --- |
| `catalogue` | Stable feature keys with labels, definitions, and any extra criteria. |
| `groups` | Display groupings and feature order. |
| `checked_on`, `scope` | Date and method of the recorded audit, not today's verification. |
| `mechs` | Repository/site identities and per-feature ratings, notes, and evidence URLs. |
| `deployed_revision` | Site-specific inspected deployment, when supplied within a Mech entry. |

Read the current structure rather than assuming the field list or feature count
is permanent. Preserve site-specific recheck dates/methods and other overrides
when present; the top-level date need not describe every row. Confirm that
grouped keys, catalogue keys, and table columns reconcile. Retain unmatched
keys/rows as drift or unknown instead of dropping them.

The web matrix differs from the general CLAW capability matrix, whose snapshot
is [manifest.json](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/_fleet/data/manifest.json).
The [site audit](https://github.com/CultureBotAI/culturebotai.github.io/blob/main/_fleet/data/site_audit.json)
is also not a substitute for the website-feature catalogue. General governance
flags and a healthy deployment do not demonstrate browser functionality.

Use an HTML parser or rendered DOM to identify the Website features table by
its heading and headers. Read cell status attributes, accessible text, legends,
and linked notes using the current assembler's encoding. Plain-text extraction
can leave status cells blank; blank or unfamiliar cells are unknown, not missing.

Relate the live matrix to its deployed site-source revision where possible.
If source main has newer ratings or definitions, retain the published baseline
and show source-only changes separately. Do not silently replace a dated matrix
rating with a fresh observation: the report needs both. If the same key has
changed criteria, assess each definition separately, not with a shared verdict.
Unproven source/deployment correspondence must be disclosed.

Enumerate all current website columns, including those with no present ratings;
do not hard-code a count or select only familiar controls. If reporting peer
adoption, use the matrix's own row set and date, distinguish unlisted cells from
missing features, and label it historical matrix evidence, not a fresh fleet
browser test.

## Target And Fleet Identity

Read the [current published CLAW manifest](https://github.com/CultureBotAI/culturebotai-claw/blob/main/src/kg_microbe_fleet/fleet.yaml)
for fleet membership and repository identity, not as the website-feature
baseline. Verify each target's Pages configuration/workflow, successful
deployment, live URL, current default-branch SHA, and relevant maintained UI
sources. A custom domain can be valid; a known repository URL is not sufficient
to guess the served path. Use read-only API calls and paginated collections.

Check recursive-tree truncation before asserting completeness; walk subtrees or
use an isolated complete scratch checkout when necessary. Do not modify or
fetch into an existing shared checkout. Preserve disagreements among live UI,
deployed source, source main, and local edits, rather than picking the most
favorable revision.
