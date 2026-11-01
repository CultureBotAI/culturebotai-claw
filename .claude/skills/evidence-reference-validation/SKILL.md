---
name: evidence-reference-validation
description: Offline quote-against-source validation for Mechs that enable the fleet evidence_reference_validation capability. Checks quotations against identified cached abstract bodies, separately from citation presence and scientific claim support.
category: curation
requires_database: false
requires_internet: false
version: 2.0.0
tags: [fleet, evidence, literature, pubmed, validation]
---

# Evidence reference validation

Use this skill before publishing curated quotations or when auditing whether
quoted edge evidence occurs in its cited cached source. Read the Mech's
`evidence_reference_validation` capability in `src/kg_microbe_fleet/fleet.yaml`;
disabled and not-applicable declarations include a reason. Only the MIM canary
is enabled in this release. Adoption in other Mechs is a separate rollout.

The validator is offline. It reads records and existing source caches, writes
reports within the active Mech checkout, and does not fetch sources, repair
quotes, change records or call a research provider. Missing sources require a
separate, authorized cache acquisition and review step.

## Run

Validate configuration first. Resolve the target through `RepositorySettings`
and verify its origin; do not use a guessed sibling checkout.

```bash
uv run openclaw-cli config validate
uv run kg-microbe-evidence --mech mediaingredientmech --strict
```

For an isolated worktree, supply its explicit absolute path with `--root`.
The CLI verifies that root's exact GitHub origin. Without `--root`, native
repository settings select the configured checkout. `--output-dir` may change
the report location only within that checkout.

The legacy command delegates to the same CLI and defaults to MIM:

```bash
uv run python scripts/validate_evidence_references.py --strict
```

Mech CI uses the canonical
`src/kg_microbe_governance/artifacts/scripts/run_shared_evidence_validator.py`
runner and `src/kg_microbe_governance/artifacts/workflows/qc-evidence.yaml`
workflow. The workflow checks out Claw at the full commit from the consumer's
`MediaIngredientMech/scripts/.vendored_canon_ref`; the runner requires `CLAW_ROOT` at that clean
pinned revision and binds validation to the Mech worktree containing it.

## What the result means

Supported sources are PMID Markdown caches with a matching `# PMID:...` header
and exactly one nonempty `## Abstract` section. A quote is compared only with
that abstract body, using NFKC normalization, collapsed whitespace and lowercase.
Titles, metadata and curator notes cannot establish a match. Manifest settings
declare cache location and evidence/reference/quote field aliases.

The optional `evidence_paths` selectors bound which evidence containers the
gate measures. The MIM canary selects only `ontology_mapping.evidence`,
`role_assignments[].evidence` and `cellular_role_assignments[].evidence`; the two
role names are legacy slots. Current role facets, discussion evidence and
causal-edge evidence remain explicitly unmeasured by this bounded MIM gate.
Evidence-field presence or an enabled capability alone does not certify them.

| Verdict | Meaning | Gate behavior |
|---|---|---|
| `OK` | Normalized quote occurs in the identified abstract | Pass |
| `NO_QUOTE` | No quote; a populated citation alone is not validation | Report separately |
| `MISSING_REFERENCE` | Quote has no citation | Fail |
| `MISSING_CACHE` | Cited PMID cache is absent | Fail with `--strict` |
| `UNSUPPORTED_REFERENCE` | Source format is not supported, including DOI-only citations | Fail with `--strict` |
| `INVALID_EVIDENCE` | Malformed or conflicting evidence fields | Fail |
| `INVALID_CACHE` | Cache identity/body is invalid or ambiguous | Fail |
| `SNIPPET_NOT_IN_SOURCE` | Quote is absent from the abstract body | Fail |

Malformed or unreadable records and an empty selected corpus also fail.
Exit status 2 means validation or input failure. Strict mode adds missing caches
and unsupported references to the blocking verdicts; it never treats unsupported
sources as validated. There is no auto-repair mode.

Reports are `evidence_reference_validation.json`,
`evidence_reference_validation.tsv` and `evidence_reference_validation.md`
under the selected checkout's `workspace/reports/` by default. They record
verdicts and quote/cache hashes without reproducing source quotations.
`kg-microbe-graph coverage` reports quote-validated edge evidence separately
from an evidence field merely being populated.

A match establishes quote occurrence only. It does not establish that the
paper supports the asserted relationship, causal direction, organism scope,
generality, or source-redistribution rights. Human scientific review and existing
curation-status gates remain necessary. Preserve an honest unverified result for
missing or unsupported sources; do not change a scientific claim just to satisfy
the gate.

The legacy `load_cache` and `normalize` imports remain available to
`scripts/apply_evidence_proposals.py`. The cache helper returns only the shared
validator's identified abstract body and resolves repository configuration
lazily; importing it does not require any locally configured Mech.

For the capability contract and rollout limits, see
`docs/guides/EVIDENCE_REFERENCE_VALIDATION.md`.
