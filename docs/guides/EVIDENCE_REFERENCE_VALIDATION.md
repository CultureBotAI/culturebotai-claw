# Quote-against-source evidence validation

The `evidence_reference_validation` capability separates a populated evidence
field from a quotation matched against a retained source. Every Mech declares
an explicit status in `src/kg_microbe_fleet/fleet.yaml`; disabled and
not-applicable declarations require a reason. The initial scope is one
MediaIngredientMech (MIM) canary, with the other 13 Mechs disabled pending their
own reviewed adoption. No Mech is assumed inapplicable merely because most of
its records originated in a database.

## Contract and limits

An enabled profile must name a repository-relative `cache_dir`. Optional
`reference_fields`, `snippet_fields` and `evidence_fields` map native fields to
the shared validator. MIM uses `references_cache`, references
`[pmid, doi, reference]`, quotes `[snippet, excerpt, supporting_text]`, and
evidence containers `[evidence]`. Field mappings are explicit selectors, not
permission to reinterpret an explanation or database assertion as a quotation.

Optional `evidence_paths` limits the gate to specific evidence containers using
dotted fields and `[]` for list members. When omitted, all occurrences of the
declared evidence-field names are in scope; this broad mode requires a reviewed
native schema mapping. MIM deliberately preserves its existing gate's scope:

```yaml
evidence_paths:
  - ontology_mapping.evidence
  - role_assignments[].evidence
  - cellular_role_assignments[].evidence
```

These are the exact selectors used by the old gate at Claw revision
`a5d562962c75a2ad9efd8160b548df5944315422`. The two role names are legacy slots,
absent from MIM's current schema and committed records. They do not certify
the current role facets. On the inspected MIM main
`4625afd492b6cf43e3b499d1425d2453d490009d`, a complete archive scan found 2,953
records and 3,290 ontology-mapping evidence rows, of which 31 had a nonempty
quote-like field. This is a shape inventory, not a quote-validation result.

Broader native evidence remains explicitly unmeasured by this bounded gate:

| Native container | Immediate evidence entries in that snapshot | Reason for separate review |
|---|---:|---|
| `nutritional_roles[].evidence` | 752 | `RoleCitation` permits reference text/URLs and an excerpt or quote. |
| `physicochemical_roles[].evidence` | 272 | Same native `RoleCitation` distinction. |
| `cellular_metabolic_roles[].evidence` | 17 | Same native `RoleCitation` distinction. |
| `discussions[].evidence` | 32 | Discussion evidence and nested argument evidence need a reviewed source adapter. |
| `culturemech_reference.evidence` | 2 scalar values | The schema defines explanatory prose, not a quotation assertion. |

The inventory above counts immediate containers, not all nested evidence.
Reports identify other evidence-container locations and shapes as outside the
declared selectors; they do not assign quote verdicts to those native types.
Causal-edge evidence is also outside MIM's declared selectors, so graph
coverage must report it as unmeasured. Expanding any selector requires review
of its native semantics and source/cache support.

The first source adapter reads the cited PMID's retained markdown abstract.
It checks source identity and matches normalized quote text inside the abstract
body; title, authors and other metadata are not quote evidence. It performs no
fetch, provider call or corpus repair. Unsupported references, absent quotes,
and unavailable or invalid cached sources remain unverified; a populated
citation alone cannot become a successful quote validation.

A cached substring match does not prove that a source supports the scientific
claim, establish the source's redistribution rights, or replace human review.
Curators still assess entailment, context, source quality and rights. Graph
coverage therefore reports evidence-field presence separately from measured
quote validation; disabled capabilities do not silently become validated or
failures. This distinction implements the concern tracked in
[#687](https://github.com/CultureBotAI/culturebotai-claw/issues/687), with
[#333](https://github.com/CultureBotAI/culturebotai-claw/issues/333) and
[#352](https://github.com/CultureBotAI/culturebotai-claw/issues/352) as context.

## Canary choice and coordination

The 2026-10-31 committed-main audit selected MIM because its existing strict
`qc-evidence` gate already validates cached PMID snippets and
[passed on the inspected main](https://github.com/CultureBotAI/MediaIngredientMech/actions/runs/41250979368/job/124684245425).
The proposed runner, workflow, pin and test paths did not overlap the open
cycle work: [PR1002](https://github.com/CultureBotAI/MediaIngredientMech/pull/1002)
contained only workflow review artifacts, and
[PR1001](https://github.com/CultureBotAI/MediaIngredientMech/pull/1001) contained
reports and reviews. Recheck current paths before a downstream change.

The noncycle [PR914](https://github.com/CultureBotAI/MediaIngredientMech/pull/914)
does contain different workflow and canonical-pin bytes. Preserve that work;
its later integration must reconcile the current canonical workflow and pin.
This canary does not modify or close that PR. CommunityMech has committed
source caches, but its native instructions keep reference validation out of
the CI gate while evidence repairs remain open
([#417](https://github.com/CultureBotAI/CommunityMech/issues/417),
[#259](https://github.com/CultureBotAI/CommunityMech/issues/259),
[#347](https://github.com/CultureBotAI/CommunityMech/issues/347)). Adopting its
full-corpus gate would introduce a separate repair scope.

The runner and CI workflow are canonical vendored artifacts. The workflow
resolves the Claw revision from `scripts/.vendored_canon_ref`; it must not carry
an independent hard-coded Claw revision.

The bounded release contract is under implementation and review; it is not yet
deployed. It fixes the fleet baseline at
`a5d562962c75a2ad9efd8160b548df5944315422`. Only MIM may advance to the exact Claw
commit that introduces the immutable
`src/kg_microbe_governance/releases/evidence-reference-validation-mim-v1.json`
declaration; the other 13 Mechs retain the baseline pin. A separate release
audit verifies trusted history and permits exactly the two declared additions,
the evidence runner and workflow, with their recorded bytes and consumer scope.
The existing coordinated fleet-audit contract remains unchanged. Deployment
requires verified merges and CI; rollout to the remaining Mechs is separate.

## Later rollout

After the single canary passes on its merged change, later adoption should:

1. Reconcile each Mech's native evidence model, aliases and open work. Review
   adapters for local reference joins and for quote versus database assertion
   distinctions, especially PathwayMech, ProteinTraitsMech, CMMMech and AIMech.
2. Establish source identity, retained cache format and source rights. Inventory
   unsupported identifiers, missing sources and mismatches without silently
   skipping them or treating prose explanations as verbatim quotations.
3. Repair or explicitly resolve findings under native scientific review, run
   the gate offline, and independently review its results and integration.
4. With separate rollout authorization, open isolated per-Mech adoption PRs,
   verify required and merge-group checks, then update enabled declarations
   from verified adoption. No PRs for the remaining 13 Mechs are part of #687's
   initial canary scope.

The manifest records each deferred Mech's specific reason. CommunityMech is a
candidate for the next reviewed adapter after its repair backlog is assessed;
that ordering is a plan, not an enabled gate or authorization to begin.
