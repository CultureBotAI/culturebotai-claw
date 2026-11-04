# Release occurrence accounting and bounded review decisions

`kg-microbe-curation` provides the first local infrastructure for
[release-wide curation](https://github.com/CultureBotAI/culturebotai-claw/issues/756).
It imports the manifest-verified occurrence export produced by
[KG-Microbe](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1717), creates
an external SQLite index, and retains exact source text and append-only decision
bundles. It makes no provider calls and does not approve scientific claims.

This is an initial local backend. Partitioned Parquet, an EdgeMech repository,
the public browser, domain adapters and autonomous research workers remain
separate implementation milestones. Keep the index and input shards outside Git.

## Commands

```bash
# Producer in the KG-Microbe checkout: verifies ALL input members, even for a subset.
poetry run python -m kg_microbe.edge_snapshot export \
  data/snapshot/manifest.json data/edge-exports/pilot --max-rows 1000

# Consumer in CLAW: only a new database path is accepted.
uv run kg-microbe-curation init \
  --export /absolute/path/to/edge-exports/pilot \
  --database workspace/curation/pilot.sqlite
uv run kg-microbe-curation status --database workspace/curation/pilot.sqlite
uv run kg-microbe-curation show --database workspace/curation/pilot.sqlite \
  --occurrence 'urn:kg-microbe:occurrence:v1:REPLACE_WITH_ACTUAL_DIGEST'
uv run kg-microbe-curation validate-bundle /absolute/path/to/decision.json
uv run kg-microbe-curation apply --database workspace/curation/pilot.sqlite \
  --bundle /absolute/path/to/decision.json --expected-revision CURRENT_STATUS_REVISION

# Deliberate whole-index check; ordinary status/apply do not scan the corpus.
uv run kg-microbe-curation audit --database workspace/curation/pilot.sqlite
```

`python -m kg_microbe_curation` exposes the same commands. JSON output is suitable
for receipts; errors produce a nonzero exit. `init` verifies exported shard hashes,
sizes, exact source-row hashes, occurrence IDs and contiguous selected ordinals.
For a complete edge export, it also reconstructs the original edge member digest.
It checks every source-manifest descriptor, while verification of auxiliary
source bytes and subset membership remains **producer-attested**. It does not
authenticate the remote release or independently rescan the original TSVs.

SQLite publication uses an exclusive hard link after the temporary file is
complete. A failure leaves an existing database untouched. Input files must be
regular files; symlinks and FIFOs are rejected. Export manifests and review
bundles are bounded at 16 MiB; JSONL occurrence lines are bounded at 32 MiB.
The producer's default shard size fits this consumer. Larger custom producer
limits may require a separately reviewed consumer change.

## Identity and review boundaries

The shared occurrence ID includes the exact input-manifest digest, member name
and digest, original data-row number, and exact row digest. Duplicate rows remain
distinct occurrences. Moving identical files does not change IDs. No prefix,
label, list or biological normalization occurs here.

Observation and claim fingerprints use versioned canonical JSON plus explicit
biological context and a required interpretation object. Interpretation names
the normalization contract and pins its digest, schema digest and prefix-map
digest; changing those pins changes identity and invalidates prior review.
These fingerprints do **not** replace KG-Microbe's native normalized
observation identity. A supplied native identity retains its algorithm,
normalizer-contract, schema and prefix-map digests. Domain adapters must supply
the correct interpretation; this package cannot verify biological semantics from
an identifier hash.

The packaged JSON Schema defines a bounded decision bundle with:

- Exact selected occurrence membership, with one current decision per member.
- Observations and scoped claims, preserving many claims per observation.
- Existing canonical `RecordReview` documents with input, target and semantic
  digests. Review documents are not a second source of scientific authority.
- Separate lifecycle, review state, conflict state and disposition. Initial
  decisions are active/unprocessed/not-assessed/withheld.

Each bundle is limited to 10,000 selected occurrences/decisions, 50,000 entries
per reference collection, and 16 MiB. Complete selected membership does not mean
complete release coverage. A review digest binds the exact proposed decision,
claim membership and native observation envelope; stale references are rejected.
Retain/amend dispositions require explicit completed scientific review covering
their scope. A passing schema, quote check or checksum never creates that
disposition. The validator checks review structure/binding, not reviewer
authenticity, evidence truth, or permission to publish.

`apply` compares the caller's expected revision inside an immediate transaction,
appends the bundle and changes only its selected current decisions. Stale
updates and replay of historical bundles are refused. The response describes
the revision committed by that operation. Status and lookup each use one
consistent read transaction.

Transactional counters make routine status independent of corpus size and
updates proportional to the selected packet. `audit` deliberately scans
membership, foreign-key references, history counts and per-dimension counts;
it does not reverify upstream evidence or redo scientific reviews. Release
revalidation of raw inputs and scientific evidence is a separate gate.

## Canary and current limits

`scripts/adhoc/run_edge_ledger_canary.py --help` runs the actual producer and
consumer commands, persists a bounded real snapshot export, defers one item,
checks exact lookup and refuses a stale revision. Use `--plan` first and a new
output directory. The receipt records source and executed-code hashes. It
proves offline accounting and persistence, not new literature acquisition,
large-run throughput or rate-limit behavior.

The separate [MIM reuse canary](MIM_REUSE_CANARY.md) verifies the already-adopted
historical MIM bundle and scope controls. It does not automatically convert its
native reviews into `RecordReview` or approve KG biological edges. Ingredient
identity supports the matching identity claim; it is insufficient to approve
growth or metabolism merely because the ingredient is an endpoint.

The ledger does not yet provide cross-release identity migration, domain routing,
claim matching, current-state export to a new KG, or a web server. Those require
explicit adapters and release contracts after this foundation is reviewed.
