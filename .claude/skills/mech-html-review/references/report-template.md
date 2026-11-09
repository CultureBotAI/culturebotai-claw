# Mech HTML Review: <Mech>

- Started UTC / finished UTC:
- Repository, pinned default-branch SHA, and fleet membership:
- Live URL, successful deployment SHA or unknown, and observation time:
- Local/source/deployment differences:
- Requested scope and review completeness:
- Browser/tool, viewport sizes, and sampled routes/records:

## Summary

| Baseline | Inventoried | Present | Partial | Missing | Not applicable | Unknown |
| --- | --- | --- | --- | --- | --- | --- |
| DisMech UI | | | | | | |
| Published X-Mech Website features | | | | | | |

Counts sum to each baseline's own inventory. An unavailable inventory is
unavailable, not zero. Summarize strengths, highest-impact gaps, and limitations
without collapsing the two baselines into one score. Newer source-only matrix
criteria belong in a separately labeled reconciliation, not either row above.

## Sources And Freshness

| Source or surface | URL / SHA / content hash | Retrieval UTC / audit date | Coverage and limitations |
| --- | --- | --- | --- |

Include DisMech live UI and guide/source, published X-Mech table and snapshot,
target live/deployed/main surfaces, and fleet identity. State whether the
DisMech inventory is derived, its reader-task granularity, and whether source
snapshots match deployments. Reuse that inventory across targets in one review.

## Compared With DisMech UI

| Feature / route / baseline evidence | Target equivalent and applicability | Target verdict | Target evidence / reproduction / absence-search scope | Gap and acceptance check |
| --- | --- | --- | --- | --- |

Retain every inventoried UI feature, including those not applicable or unknown.
Identify documented/source-only upstream behavior rather than calling it live.

## Compared With X-Mech Website Features

| Key / label / published definition and criteria | Dated matrix rating and evidence | Fresh target verdict | Target evidence / reproduction / absence-search scope | Gap and acceptance check |
| --- | --- | --- | --- | --- |

Include every website-feature column, preserving historical status spelling and
explaining normalization. A target absent from the matrix is unlisted, not
missing every feature. Apply the published definition for these verdicts.

## Browser Evidence And Coverage

| Feature / surface / URL | Viewport and input | Steps and expected result | Observed result | Screenshot / trace / console evidence |
| --- | --- | --- | --- | --- |

Name tested records and templates, content-ready conditions, pagination/shard
coverage, isolated failure injection, and any skipped interactions. Separate
observed failures from checks not run. Give known denominators; do not claim
every record was tested from representative samples. Mark static-only checks;
markup observations do not count as present reader functionality without the
behavioral evidence required by the baseline.

## Source Drift And Additional Features

Show differences between the live matrix and source main, between deployed and
unpublished target behavior, and any source-only criteria with separate target
verdicts. Keep added/retired keys and changed definitions visible. Target-only
features and supplemental accessibility findings can be reported here without
altering the two baseline inventories.

## Prioritized Findings

| Priority | Reader impact / baseline feature | Evidence | Owning source | Acceptance check | Existing issue/PR, if checked |
| --- | --- | --- | --- | --- | --- |

Report actionable findings without filing or implementing them. An existing PR
does not resolve an observed deployed gap until that deployment is verified.

## Not Applicable And Unverified

Explain applicability, inaccessible sources/settings, unavailable tools, unrun
checks, and the smallest follow-up needed to resolve each unknown. Close with
the precise scope supported by the evidence, not a blanket fleet-wide pass.
