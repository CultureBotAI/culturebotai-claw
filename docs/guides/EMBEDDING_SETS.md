# PaCMAP and independent embedding sets across the Mech fleet

Every Mech in the canonical fleet must have a PaCMAP adoption disposition and
support multiple, separately identified embedding sets. The machine-checked
[rollout](../../src/kg_microbe_embeddings/rollout.yaml) covers all thirteen
members at the recorded October 9, 2026 source revisions. A new fleet member
without a rollout entry fails the contract tests.

PaCMAP projects existing vectors into a map. Text encoders, protein language
models, graph embeddings and chemical features produce different vectors and
retain their own identities. The reference is
[ProteinTraitsMech's four-view selector](https://github.com/CultureBotAI/proteintraitsmech/blob/9c563d320b0b39548daf119812a5e25298236b63/docs/map.html):
full-record text, definition-only text, protein trait profiles, and ESM-2
sequence embeddings. Protein points and record points have different identities
and denominators, even when they appear in the same application.

## Current implementation and rollout

The shared `kg-microbe-embeddings` package can validate multiple vector sets and
build independent PaCMAP assets with a small catalogue. It does not run an
encoder, download weights, modify a downstream repository or publish a site.
Installation of this package is not evidence that a Mech has adopted its
registry or that a deployed map uses it. Registry adoption remains **planned**
for the fleet; native source evidence and required next steps are recorded
separately for each repository.

| Mech | Native source at audit | Required next step |
| --- | --- | --- |
| CultureMech | PaCMAP for KG vectors | Register media and ingredients separately; add text |
| MediaIngredientMech | PaCMAP for KG vectors | Record lookup provenance and coverage; add text |
| CommunityMech | PaCMAP for aggregated KG vectors | Separate community graph and text sets |
| TraitMech | PaCMAP for KG vectors | Bind actual vector source and matched IDs; add text |
| ProteinTraitsMech | PaCMAP, four distinct views | Register existing sets and preserve their selector |
| AntibioticMech | PaCMAP text; UMAP chemical view | Separate text and chemical spaces with true method labels |
| CellStructureMech | MiniLM text with PCA | Complete PaCMAP migration in issue 910 |
| HabitatMech | Provenance-bound BGE/PaCMAP | Adapt the existing verified bundle into the catalogue |
| NaturalProductMech | PaCMAP text; UMAP chemical view | Separate text and chemical spaces with true method labels |
| TaxonMech | No pipeline found in audited source | Complete bounded-memory text/PaCMAP work in issue 58 |
| PathwayMech | No pipeline found in audited source | Add pathway text adapter, vectors, projection and viewer |
| DUFMech | No pipeline found in audited source | Separate family text from any verified sequence cohort |
| CMMMech | No pipeline found in audited source; three records | Add text adapter; retain a blocked map for the small cohort |

The audit used fresh sparse checkouts of each main revision, full tracked file
name inventories, and ignored-inclusive searches of checked-out source,
scripts, workflows, configuration and documentation. Source evidence paths are
retained in the rollout. These are repository findings, not a new live-site
audit or a claim about uncommitted caches in another working copy.

The existing [text rollout issue #426](https://github.com/CultureBotAI/culturebotai-claw/issues/426)
and [governed runtime draft #432](https://github.com/CultureBotAI/culturebotai-claw/pull/432)
remain the integration path for the common BGE text encoder. Extend their
original scope to PathwayMech, DUFMech and CMMMech. Preserve the governed
runtime's full encoder profile, incremental cache, immutable bundles and
publication checks. This vector-set package complements that work with a
modality-independent registry and projector; it does not replace or register
those pending governed artifacts. Existing text bundles can remain active
while their adapters gain the registry and additional spaces.

## Commands

Use the repository's locked Python 3.13 environment:

```bash
uv run kg-microbe-embeddings rollout
uv run kg-microbe-embeddings check /absolute/path/embedding-sets.json
uv run kg-microbe-embeddings check /absolute/path/embedding-sets.json --artifacts
uv run --extra embeddings kg-microbe-embeddings build \
  /absolute/path/embedding-sets.json --output /absolute/path/new-map-release
```

`check` validates metadata without importing PaCMAP. `--artifacts` also verifies
file hashes, ordered IDs, dimensions, numeric types and finite nonzero vectors.
`build` runs real PaCMAP over every ready set. It stages all outputs, rechecks
inputs, then moves the completed directory into place. An error in any set
leaves no new release; existing releases are never overwritten. Select a new
output directory for each build. These commands only create local artifacts;
downstream adoption and publication follow their existing review workflow.

## Registry contract

The JSON registry has exactly `format_version: 1`, the canonical `repository`
GitHub identity, `default_set`, and a nonempty `sets` list. Set IDs are unique
lowercase names, such as `record-text-bge`, `definition-text-bge`,
`protein-sequence-esm2` or `kg-microbe-graph`. Multiple models within one
modality use different set IDs and independent vector files.

Each set declares `id`, `label`, `modality`, `entity_type` and `status`.
Supported modalities are `text`, `protein_language_model`, `graph`, `chemical`
and `trait_profile`. `ready` means the registered vectors exist; it does not
mean the map has been built or deployed. `planned` and `blocked` entries carry
a nonempty `reason` and no artifact claims. They remain visible in the output
catalogue. If any set is ready, the default must name a ready set.

A minimal plan, valid before there are any vectors, is:

```json
{
  "format_version": 1,
  "repository": "CultureBotAI/CMMMech",
  "default_set": "record-text",
  "sets": [
    {
      "id": "record-text", "label": "Record text", "modality": "text",
      "entity_type": "record", "status": "planned",
      "reason": "Text adapter and encoder output are pending."
    },
    {
      "id": "protein-sequence", "label": "Protein sequence",
      "modality": "protein_language_model", "entity_type": "protein",
      "status": "blocked",
      "reason": "No verified sequence cohort is registered."
    }
  ]
}
```

To make a set ready, replace `reason` with all of these fields:

| Field | Required contents |
| --- | --- |
| `encoder` | `name`, immutable `revision`, integer `dimension`, versioned `input_recipe`, nonempty `parameters` and `library_versions` objects |
| `source` | 40-hex corpus `revision` and 64-hex `input_sha256` for the complete ordered semantic/sequence inputs used by the encoder |
| `ids` | `path` to a JSON string list in exact vector-row order, and its `sha256` |
| `vectors` | `path` to a numeric N×D `.npy` file, and its `sha256` |
| `coverage` | `total` and `eligible` counts for this entity population; embedded and shown counts are measured during the build |
| `projection` | The explicit settings below |

Artifact paths are relative to the registry directory. Absolute paths, parent
traversal and escaping symlinks are rejected. Identical entity IDs may occur in
different sets. Duplicate IDs within one set, reused vector-file paths,
duplicate JSON keys, unknown fields and changing input bytes are rejected.
The adapter supplies the model/semantic provenance; hashing cannot prove that
an upstream encoder used the claimed model or that its biological inputs are
appropriate. Review that adapter and retain its own generation receipt.

`encoder.parameters` preserves the encoder's actual pooling, normalization,
token/window limits, overlap handling, compute precision, and feature or graph
aggregation settings as applicable. Retain actual encoder software versions.
PaCMAP's software versions are recorded separately by the projector. A source,
model, pooling or input-recipe change requires a new encoder output and matching
hashes; it cannot be handled by relabelling an old artifact.

Example text projection settings, modelled on ProteinTraitsMech:

```json
{
  "method": "pacmap", "neighbors": 15,
  "MN_ratio": 0.5, "FP_ratio": 2.0, "seed": 42,
  "init": "pca", "apply_pca": true,
  "preprocessing": "l2", "max_points": 0
}
```

For the ProteinTraitsMech ESM-2 reference space, use `center_l2`,
`apply_pca: false` and `neighbors: 10`; its preprocessing subtracts the selected
cohort's mean before row normalization. A different protein model can have
different validated preprocessing. Model settings and dimensions are per set.
`max_points: 0` projects all embedded entities. A positive limit uses a seeded
uniform sample and records both embedded and shown counts. Sampling never
changes the eligible/total denominators or implies complete displayed coverage.

The fleet builder requires at least ten selected entities; this is a
conservative fleet policy, not a claimed mathematical minimum for PaCMAP.
Too-small, zero or degenerate cohorts fail explicitly. Requested neighbours
are bounded to leave further-pair candidates; requested and effective pair
counts are both retained. Missing PaCMAP fails the build without a PCA/UMAP
fallback. The locked reducer uses Euclidean distance, FAISS neighbours, PCA
initialization and a fixed seed. See the [PaCMAP API](https://github.com/YingfanWang/PaCMAP/blob/master/README.md).
Seeds aid reproducibility under the recorded runtime; coordinates are not
guaranteed identical across platforms or stable across corpus/model changes.

This projector accepts dense feature vectors, not precomputed chemical
distance matrices. Preserving Tanimoto or another chemistry-specific geometry
requires a separately validated feature/pair adapter before a chemical view
migrates. Existing chemical UMAP and graph-layout comparisons retain accurate
labels during that work.

## Consumer and adoption gates

The output `index.json` lists all sets, their status and the default, with a
relative `path` and SHA-256 for each ready map. Each `sets/<id>.json` contains
`[entity_id, x, y]` points, the set ID, entity type, encoder/source metadata,
input hashes, measured coverage and actual reducer settings/software versions.
A site must verify the asset hash against the index and lazy-load the selected
set. Key browser caches and neighbour indexes by set identity and source/model
fingerprint, not just by entity ID. Preserve set selection in navigation and
use the selected entity type's record/protein links.

Text vectors and protein-language-model vectors are independent spaces. Do
not concatenate them, average them, compare coordinates across maps, or reuse
neighbours from a different space. Compute semantic neighbours in the selected
original vector space. Cross-space protein-to-record associations require
explicit provenance-backed bindings; they are not coordinate equivalences.

Every Mech must be able to describe additional sets, including conditional
protein sets. That does not require manufacturing protein embeddings for a
corpus without grounded sequences. Such a set remains blocked with its reason.
For real sequences, preserve ProteinTraitsMech's pinned model revision,
sequence checksums, residue-mean pooling and overlap-corrected long-sequence
windows, or document and validate a different model's recipe.

Complete each repository's rollout actions and shared acceptance gates before
claiming adoption. Run a two-set offline test, a bounded real PaCMAP canary,
the native repository checks, current-input artifact verification, and live
desktop/mobile/keyboard checks for selection, coverage and links. Keep ordinary
CI free of model inference. Update repository and X-Mech web support only after
the corresponding implementation and deployment have been verified.
