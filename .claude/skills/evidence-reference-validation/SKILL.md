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
uv run python -m kg_microbe_fleet list --capability evidence_reference_validation --format tsv
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

Supported sources are PMID and DOI Markdown caches: `PMID_<n>.md` with a
matching `# PMID:<n>` header, or `DOI_<percent-encoded lowercase DOI>.md` with a
matching `# DOI:<doi>` header, each with exactly one nonempty `## Abstract`
section. DOIs are case-insensitive, and the `doi:`, bare and resolver-URL
(`doi.org`, `www.doi.org`, `dx.doi.org`) spellings of one DOI read one cache;
only a URL's path is the DOI (not its fragment or query), and only it is
percent-decoded. A citation that carries a PMID is checked against
the PMID alone; DOI values beside it are not read. A quote is compared only with that abstract
body, using NFKC normalization, collapsed whitespace and lowercase. Titles,
metadata and curator notes cannot establish a match. Manifest settings declare
cache location and evidence/reference/quote field aliases.

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
| `MISSING_CACHE` | Cited PMID or DOI cache is absent | Fail with `--strict` |
| `UNSUPPORTED_REFERENCE` | Citation is neither a PMID nor a DOI (a database record, URL or free text) | Fail with `--strict` |
| `INVALID_EVIDENCE` | Malformed or conflicting evidence fields, including a `pmid` slot that names no PMID | Fail |
| `INVALID_CACHE` | Cache identity/body is invalid or ambiguous | Fail |
| `SNIPPET_NOT_IN_SOURCE` | Quote is absent from the abstract body | Fail |

Malformed or unreadable records and an empty selected corpus also fail.
Exit status 2 means validation or input failure. Strict mode adds missing caches
and unsupported references to the blocking verdicts; it never treats unsupported
sources as validated. There is no auto-repair mode.

Reports are `evidence_reference_validation.json`,
`evidence_reference_validation.tsv` and `evidence_reference_validation.md`
under the selected checkout's `workspace/reports/` by default. They record
verdicts and quote/cache hashes without reproducing source quotations, and say
how many in-scope items carry a quote at all: a pass covers only those.
`kg-microbe-graph coverage` reports quote-validated edge evidence separately
from an evidence field merely being populated.

## Adding missing caches

The gate never fetches. `kg-microbe-evidence-fetch` is the separate command that
adds caches, and it is a dry run unless `--apply` is given:

```bash
uv run kg-microbe-evidence-fetch --mech <mech> --root <worktree>            # plan
uv run kg-microbe-evidence-fetch --mech <mech> --root <worktree> --limit 2 --apply   # canary
uv run kg-microbe-evidence-fetch --mech <mech> --root <worktree> --apply
```

It fetches exactly the sources the gate reports as `MISSING_CACHE` under the
declared selectors, from NCBI E-utilities, anonymously. A DOI's abstract is
accepted only from a single PubMed record that lists that DOI. It never rewrites
an existing cache and writes nothing for a record without an abstract, so those
stay `MISSING_CACHE`. When both PMIDs and DOIs are pending, `--limit` covers at
least one DOI, so the `--limit 2` canary exercises both lookup paths; check its
files before fanning out. Before any request, both modes check that the cache
directory is writable; every dry run also checks the repository-lock setup that
`--apply` takes (including the global lock), and `--apply` holds that lock. An
NCBI error reply stops the run; it is never reported as sources not found.
`--json` must be outside the checkout or under its `workspace/`. A cached abstract
does not clear its redistribution rights; follow the Mech's source policy before
committing caches.

## Known findings ledger

A Mech whose profile declares `known_findings` keeps a TSV
(`record`, `reference`, `verdict`, `quote_sha256`, `issue`) of existing findings
whose repair an issue owns; the rollout release declares the setting in the
manifest catalogue, and the manifest rejects it before that. A finding listed
there is reported, counted apart and never shown as validated, but does not
block. Each row excuses exactly one occurrence, so a copy of a recorded failing
quote blocks until it is recorded too. Any finding not listed still
blocks, and an entry whose finding no longer occurs is stale and blocks until it
is removed, so the ledger can only shrink by repair. Only quote or citation
findings can be recorded (`MISSING_REFERENCE`, `MISSING_CACHE`,
`UNSUPPORTED_REFERENCE`, `SNIPPET_NOT_IN_SOURCE`); broken input is fixed instead.
Editing a recorded quote changes its hash, so the new text is checked afresh.

```bash
uv run kg-microbe-evidence --mech <mech> --root <worktree> --record-known-findings --issue <issue-url>          # plan
uv run kg-microbe-evidence --mech <mech> --root <worktree> --record-known-findings --issue <issue-url> --apply  # write
```

The writer keeps entries that still occur with their existing owner, drops stale
ones, and assigns new findings to `--issue`. After repairing quotes, rerun it
without `--issue` to drop the repaired entries. A dry run that leaves a current
finding without an owner exits 1, and `--apply` then refuses (exit 2); the write
holds the Mech's repository lock.

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
