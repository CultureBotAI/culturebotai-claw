# Reproducible Mech text maps

Tracking: CultureBotAI/culturebotai-claw#426.

Each Mech retains its existing biological graph, signature, chemical or other
specialty view. A common semantic-text view uses BAAI/bge-large-en-v1.5 at
revision d4aa6901d3a41ba39fb536a557fa166f842b0e09, 1024 dimensions, normalized
vectors and a shared 512-token window with tail truncation. A Mech owns its selection of
biological text fields; curation history and publication metadata must not
accidentally become similarity features. Alternative model profiles must name
an immutable revision and remain clearly identified separate representations.

Adapters stream UTF-8 JSONL with these fields: identifier, label, category,
page, source_path, text, text_sha256, adapter_version. Identifiers are unique;
text is nonempty; the text digest covers the exact UTF-8 bytes sent to the
encoder. Page links are relative to the map's parent directory (the rendered
content root). For a map at `pages/text-map/`, `habitats/example.html` resolves
to `pages/habitats/example.html`; a deployment wrapper retaining `pages/` must
not cause that segment to be added twice. Full runs enumerate the
whole declared corpus; canaries identify their bounded selection explicitly.

The shared runtime is a governed standalone script, installed into each Mech
through the existing vendoring mechanism. It offers input inspection, local
embedding, PaCMAP projection, HTML export and offline validation. Heavy model
and projection dependencies are isolated from normal curation/CI environments.
All input records contribute to a length-framed SHA-256 digest; id ordering and
map display metadata have separate recorded hashes. A change in a middle
record cannot be hidden by a sampled fingerprint.

A per-record SQLite cache stores vectors under an immutable encoder-profile
identity, identifier and exact text digest. Transactions publish whole batches;
no record can acquire a new identity before its vector exists. Repeated runs
reuse verified unchanged records; old caches without immutable provenance are
not relabeled as newly verified. Model/library/window/dimension/normalization
changes select a different profile, as do inference-device and weight-precision
changes. Serialized vectors are finite, nonzero and
of the declared dimension. No pickle loading is allowed. A check with the local cache also verifies the recorded source-vector bytes; a public-artifact-only check cannot prove absent cache bytes.

A map generation publishes an immutable bundle: selected records,
coordinates and a manifest with checksums plus a receipt for the input vectors. The manifest records model identity,
adapter version, complete input identity, vector checksum, actual reducer and
parameters, seed, software versions and total/eligible/displayed counts.
Requested neighbors and effective neighbor/mid-near/further pair counts are
distinct, because PaCMAP adjusts the latter for small datasets. Vector caches
stay local; public map bundles do not duplicate large model vectors.
A small atomically replaced pointer selects a completed bundle. An interrupted
run preserves the previous active bundle. Check commands validate actual
artifact bytes and current adapter output; they do not perform model inference.
Site preflight requires the shared model, revision, dimension and token window.
Staging binds both the selected generation name and its manifest content to that
preflight decision, so a pointer replacement cannot publish a different profile
under the common-map label.

Large corpora must use streaming input/cache operations and bounded projection
selection. No all-pairs similarity matrix is permitted. The selection rule,
seed, omitted count and whether the view covers the entire corpus are explicit
in both manifest and map UI. A canary uses the same command path as a full run,
with a small declared input limit; its files are inspected before expensive
runs are expanded. Full migration is verified per Mech, not inferred from a
successful template or a single canary.

Each Mech fits its PaCMAP projection separately. Sharing the encoder does not
align coordinates between maps; a cross-Mech overlay requires a joint
projection of an explicitly declared combined corpus.

Old graph-map coordinates retain their historical uncertainty. Fresh graph
regeneration records the actual source file digest, vector mapping/proxy or
synthetic status, coverage and reducer. A title is not evidence of the method
used to generate old coordinates. Protein signature TF-IDF and Morgan chemical
fingerprints keep those names; neither is described as a neural sequence or
molecular language model.

New governed artifacts follow the existing consumer-completeness gate: first
land the reviewed consumer files while retaining the deployed canonical pin,
then register those artifacts in CLAW, then update the fleet pins. Verify the
candidate's governed payloads before the first phase. After the CLAW PR merges,
resolve its actual main-reachable commit and verify its manifest and payloads
against the reviewed candidate before using it as the shared release pin.
The merge queue uses squash merges, so the draft branch SHA must not be assumed
reachable from main. Coordinate the pin updates and finish with the fleet
convergence audit. See tracking issues #426 and #434.
