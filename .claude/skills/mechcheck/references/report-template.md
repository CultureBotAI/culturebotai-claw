# MechCheck: <Mech>

- Target repository and inspected default-branch SHA:
- Started UTC / finished UTC:
- Published fleet membership / page membership:
- Local checkout differences (if inspected):
- Comparison completeness: DisMech / published X-Mech matrix / current CLAW:

## Sources And Freshness

| Source | URL / pinned revision | Retrieved UTC / content hash | Complete? / limitations |
| --- | --- | --- | --- |

Name every inspected DisMech surface and whether its inventory is official or
derived. Distinguish live page, site-source snapshot, and current CLAW manifest.
State inaccessible sources, truncated inventories, and stale caches explicitly.

## Summary

| Baseline | Inventoried features | Present | Partial | Absent | Not applicable | Unknown |
| --- | --- | --- | --- | --- | --- | --- |
| DisMech inventory | | | | | | |
| Published X-Mech matrix | | | | | | |
| Current CLAW catalogue (reconciliation) | | | | | | |

Count each feature once per applicable baseline, not once per spelling or
evidence item. Never report zero inventoried features when a source failed.
State how many DisMech items are shipped, experimental, planned, or unknown;
missing an upstream proposal is not a shipped-parity failure.

## Compared With DisMech

| Feature / source key | DisMech state and evidence | Target equivalent / applicability | Target status | Target evidence or absence-search scope | Remaining gap / acceptance check |
| --- | --- | --- | --- | --- | --- |

Include every inventoried feature, including target strengths and unknowns.
Explain narrower/broader equivalents instead of calling them identical.

## Compared With X-Mech

| Capability key / source membership | Published definition / target declaration / reason | Current definition / target declaration / reason | Target status against published definition | Target status against current definition | Declared peer adoption | Evidence / absence scope / gap / acceptance check, by baseline |
| --- | --- | --- | --- | --- | --- | --- |

Use the union of page and current catalogue keys, labeling page-only,
current-only, or both. Cite both pinned definitions and relevant settings.
Assess each definition independently, even when the key is unchanged. Keep
evidence, gaps, and acceptance checks labeled by baseline; the summary uses
that baseline's verdict column. When a key is not listed by a baseline, put
"not listed" on that side and exclude it from that baseline's counts. This
is not a not-applicable verdict about the target. Give peer counts as
enabled / disabled / not-applicable / undeclared / unknown, with the
page's member denominator and snapshot revision. Do not assert peer runtime
verification unless it was actually performed. A current-only key has no
published peer tally, not a tally of zero adopters.

## Source Drift And Target-Only Features

List page/manifest/implementation disagreements, membership differences,
changed definitions, local-only changes, and supported features outside both
baselines. Keep unresolved mappings explicit and avoid treating them as absence.

## Prioritized Gaps

| Priority | Feature / baseline | Impact and evidence | Owning path | Acceptance check / dependency |
| --- | --- | --- | --- | --- |

## Not Applicable And Unverified

Give applicability reasons, missing evidence/permissions, unrun checks, and the
smallest read-only follow-up that would resolve each unknown. End with the
scope of the conclusion, not a blanket pass/fail for the Mech.
