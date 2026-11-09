# Minimal curation contract distribution

MediaIngredientMech's native mapping adapter needs CLAW's canonical identity,
artifact and assertion validators. Installing the complete orchestration package
also requires LinkML 1.10, which conflicts with MIM's current constraint below
1.10. This packaging path advances
[MIM #1144](https://github.com/CultureBotAI/MediaIngredientMech/issues/1144)
without changing MIM's runtime, data, or the canonical validator source.

The builder copies 17 exact Git blobs from a complete immutable CLAW commit into
an exclusively created build directory. The resulting provenance records the
source commit, every canonical file digest, builder and metadata digests. The
base distribution requires only `jsonschema`; its supported imports are identity,
artifact and native assertion validation. The optional `reviews` extra preserves
the canonical LinkML 1.10 requirements and enables bundle, review and ledger
operations, including `python -m kg_microbe_curation`. It does not make that extra
compatible with MIM's existing LinkML constraints.

The distribution shares module names with `kg-microbe-orchestration`. Do not
install both in one environment. The installation verifier rejects that overlap
and imported source-tree shadowing; the package manager cannot enforce it.
Included governance support is only the review import closure, not a supported
fleet or governance CLI. No package is published to an index by this workflow.

## Reproduce a local installation proof

Run from CLAW using a fresh output name for each attempt. Supply the reviewed
complete source commit; do not substitute a mutable branch or tag.

```bash
uv run --no-project python scripts/adhoc/stage_curation_distribution_20261107.py \
  --root . --source-commit 1b5391d083ba85ac94e5279c3cba25ac4fde243c \
  --output workspace/curation-package-example/source
uv build --project workspace/curation-package-example/source \
  --out-dir workspace/curation-package-example/dist
```

Retain the SHA-256 of `source/staging-manifest.json` independently of the installed
wheel, together with both archive digests. Create a clean environment, install
the wheel there, and use that environment's Python to run
`scripts/adhoc/verify_curation_distribution_20261107.py` with `--source-commit`,
`--provenance-sha256`, a new `--output` receipt path, and either `--native-only`
or `--reviews`. For a real adapter canary also supply `--native-export` and
`--native-manifest-sha256`; all persisted rows, source pins, bytes, review counters
and zero-approval counters are reconciled.

The CI workflow builds the wheel through the source archive, proves native-only
installation without LinkML, then uses a separate reviews environment. It runs
the canonical native, artifact, contract and ledger suites copied outside the
source checkout, after verifying all 13 installed Python module origins.

## Verified 2026-11-07 canary

The following proof uses source `1b5391d083ba85ac94e5279c3cba25ac4fde243c`,
the same immutable contract source used by the four native adapters. Outputs
remain in `workspace/curation-package-20261107/`; small installation receipts
are retained under `docs/reviews/edgemech-20261107/minimal-package/`.

| Artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| Provenance | `21102b3bade024a2fe3c18595ef34685c51397d20c549a9a369d20449ff7284f` | 2,646 |
| Wheel | `60c705eedb0c345889df225f5687a41a473e076d2d6a274652932a674faba7c3` | 58,745 |
| Source archive | `c91cd4dd76759977a2066bc6845462d59bd40615cb6299aa1613c7725ec5010f` | 52,054 |
| Native installation receipt | `3bb4df6914308124c1afbd603de17620d3f9e89041bdeb2cde9cb055972db0d5` | 894 |
| Review installation receipt | `c7146606f7d31602d11951a04f5183a3aa2ab2b3a703e5dfe0623cae371ae013` | 610 |

The base environment installed six packages and verified all 17 canonical files
and four supported import origins. A real three-row pinned MIM export retained
one supported and two withheld native assertions, with zero scientific approvals.
The separate reviews environment verified all 13 Python module origins; 148
canonical tests passed from installed files, including positive RecordReview
validation, bundle handling, SQLite ledger ingestion, decision updates and CLI
paths. The 11 packaging regression tests and Ruff passed.

Independent adversarial review found the missing optional-review proof, filed as
[CLAW #985](https://github.com/CultureBotAI/culturebotai-claw/issues/985).
The repair includes support-module shadowing regressions and the installed
positive suites above. The saved mutation helper reinstates native-only origin
selection in an isolated copy: both shadow tests pass on the repair and both
fail on that mutant. A second independent read-only review found no remaining
blocking defect in the repair.

This proves packaging and bounded consumer conformance. It does not install the
distribution into MIM, publish a package release, migrate its review runtime,
or grant scientific approval. MIM #1144 remains open for reviewed dependency
adoption and distribution policy.
