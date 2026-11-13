# Diagnostic registry-retirement proposals

Claw #1189 adds an opt-in path for an obsolete canonical compatibility row that
prevents generating a candidate for independent publication review. Default
competing-namespace refusal is unchanged. No canonical table is edited, registry
handle minted, scientific hold cleared, or mapping approved by this command.

The stable CLI accepts both `--registry-retirement-proposal PATH` and
`--registry-retirement-proposal-sha256 SHA256`; legacy mode forbids them. The
proposal lives under the selected MIM root and uses this closed contract:

```json
{
  "schema_version": 1,
  "capability": "stable-registry-retirement-proposal-v1",
  "scope": "diagnostic_candidate_only",
  "author": "ACTUAL_AUTHOR",
  "scientific_approval": false,
  "canonical": {"path": "mappings/ingredient_mappings.sssom.tsv", "sha256": "ACTUAL_COMPLETE_TABLE_SHA256"},
  "evidence_inputs": {"relative/evidence.json": "ACTUAL_EVIDENCE_SHA256"},
  "entries": [{
    "row_position": 1,
    "row": {"EVERY_ORIGINAL_COLUMN": "EXACT_CELL"},
    "owner": {"path": "data/ingredients/mapped/ACTUAL_OWNER.yaml", "sha256": "ACTUAL_OWNER_SHA256", "mim_id": "ACTUAL_PERMANENT_ID"},
    "reason": "Actual author rationale; no scientific approval is inferred",
    "evidence": ["relative/evidence.json"]
  }]
}
```

Positions count data rows only. Every original cell, canonical header/comment
byte, evidence input and current owner is checksum-bound. Only an explicitly
selected exact registry row opposing its owner's current curated registry
primary can be omitted from the diagnostic compatibility view. Unknown and
ambiguous owner aliases, duplicate positions, changed cells/evidence, current
primary removal, numeric-handle invention and remaining conflicts are refused.
Same-namespace aliases, including mixed-case and escaped local slugs, remain.

Generation retains the full proposal and all source-input hashes, or explicit
null proposal metadata when no option is supplied. It captures/rechecks the
same input closure at the ordinary native transaction boundaries. MIM's guarded
publication generation/replay must consume the identical proposal and evidence;
its canonical installation still requires full `REMOVE_WITH_HISTORY` native
primary and separate skeptical review plus independent technical acceptance.
The proposal must not be represented as scientific approval or used to bypass
the separate supported/withheld external and source-identity contracts.
