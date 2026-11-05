# Offline MIM review-reuse canary

`scripts/adhoc/run_mim_reuse_canary.py` verifies one retained, KG-adopted MIM
export and imports three native decisions into a new JSON receipt. It performs
no provider calls, writes no Mech records, and grants no KG edge approvals.
This is an import/scope canary, not a full research or KG rebuild pipeline.

Use an explicit KG checkout containing `scripts/mim_reviewed_release.py`,
`scripts/refresh_reviewed_mim.py`, and its `mappings/mim_reviewed_release.json`.
Select a Python interpreter with that checkout's dependencies. The helper runs
the existing KG validators in that interpreter; it does not install packages
or execute code from the MIM archive. The canary is deliberately bound to MIM
commit `1848b0fe521bc2462f165912fcf92d09ad9a8cec`, not current MIM main.

The retained four-file release has manifest SHA-256
`9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af`.
The source archive SHA-256 is
`33ff549d7a2bf34e943156e800e00149736a30dfc0a974f3ca9a9884358bfef2`.
Always obtain expected hashes from the selected KG pin, not the input bundle.

First run the command with `--plan`; it writes nothing. Then repeat the same
command without `--plan`, using a fresh output filename:

```bash
python scripts/adhoc/run_mim_reuse_canary.py \
  --kg-root /path/to/kg-microbe-checkout \
  --kg-python /path/to/kg-python \
  --bundle /path/to/ci-sssom-1848b0fe \
  --archive /path/to/source-1848b0fe.tar.gz \
  --kg-manifest /path/to/kg-snapshot/manifest.json \
  --output /path/to/local-artifacts/mim-reuse-canary.json \
  --plan
```

The original KG checkout retains the bundle under
`data/mim-finalize-20260925.Wj4qvb/new-upstream/ci-sssom-1848b0fe/` and the
archive under `data/mim-followup-review-20260925.icmkIY/`. These are local
evidence paths, not portable defaults or automatic downloads.

The helper verifies the complete supported/withheld partition, all export
member hashes, archived source/review/workflow bindings, and every declared
native review input and owning-record hash. It checks the three selected
decisions against their original source rows, owning records, and evidence
entries. A mismatched hash or incomplete input closure aborts before output.

| Native position | Selected assertion | Expected outcome |
|---|---|---|
| 1 | Anisomycin exact identity to `CHEBI:338412` | Eligible inherited mapping review; explicitly not fresh literature review. |
| 21 | Imidazolium lysine broader mapping to `CHEBI:63895` | Withheld: relation and supplied-form scope remain unresolved. |
| 25 | Methyl alpha-galactopyranoside exact mapping to `CHEBI:55507` | Withheld: source does not establish the stereochemical restriction. |

Every case also exercises a changed payload, a changed evidence dependency,
and an explicitly synthetic organism-growth assertion sharing the ingredient
endpoint. All three controls refuse reuse. Ingredient identity can support
endpoint grounding; it cannot approve that biological proposition.

The KG manifest is fingerprinted as context only. The helper does not scan its
edge members, assert membership, or manufacture a positive KG claim match.
`actual_kg_edges_approved` remains zero. Exact original positions and complete
payloads are retained; a three-row excerpt is never presented as the original
2,999-row release. No native MIM decision is silently converted into CLAW's
separate `RecordReview` format.

Output publication is atomic and refuses existing files, including symlinks.
The CLI reads the saved bytes back and prints their SHA-256. Inspect the receipt's
`selected_claims`, assurance flags, source counts, input verification count,
validator hashes, and scope controls. Keep this full receipt and retained
inputs in local/versioned artifact storage rather than checking them into Git.
New receipts also record the selected child interpreter and actual imported
origins of all three KG validators. The launcher compares source hashes before
and after the child; the child checks origins and hashes before and after
validation. An unexpected origin or changed source prevents publication. The
child replaces ambient `PYTHONPATH` with the selected KG root and uses a fresh
bytecode-cache prefix with cache writes disabled, so stale bytecode cannot
substitute for the fingerprinted source. These checks bind the named validators
and launcher; they do not attest the interpreter's complete dependency closure.
The ordinary regression fixtures are synthetic and require no large archives:

```bash
uv run --extra dev pytest -q tests/test_mim_reuse_canary.py
```

## Recorded offline run, 2026-11-03

From the isolated CLAW implementation worktree, the following command was first
run with `--plan`, then exactly as shown. Paths describe this local run; they
are not installation defaults.

```bash
.venv/bin/python scripts/adhoc/run_mim_reuse_canary.py \
  --kg-root /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe-edge-curation-20261103 \
  --kg-python /Users/marcin/Library/Caches/pypoetry/virtualenvs/kg-microbe-pu1PEBVS-py3.10/bin/python \
  --bundle /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/data/mim-finalize-20260925.Wj4qvb/new-upstream/ci-sssom-1848b0fe \
  --archive /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/data/mim-followup-review-20260925.icmkIY/source-1848b0fe.tar.gz \
  --kg-manifest /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/data/merged/20260929/manifest.json \
  --output workspace/reports/edge-curation-20261103/mim-reuse-canary.json
```

The persisted receipt reports `PASS_OFFLINE_REVIEW_REUSE_CANARY` and has SHA-256
`20ae7030f6c3c27d5874fb1a9f96c0366d9a92570b00746f7790071f425d05e8`.
The complete export partition was verified as 2,999 = 1,747 supported + 1,252
withheld mappings, along with 2,694 archived native review input hashes. Position
1 retained inherited approval; positions 21 and 25 retained their holds. Every
changed-payload, changed-dependency, and endpoint-only biological control refused
reuse. No actual KG edge was approved, and no provider was called.

An earlier successful run used the planning worktree with the same pinned KG
validators; its receipt is preserved separately as
`mim-reuse-canary-planning-root.json`. It was not overwritten. The implementation
worktree receipt above is the final recorded run.

The receipts recorded above predate the runtime-origin guards added for #810.
They remain historical evidence and are not retroactively certified by those
guards; a new run must publish to a fresh output path.

## Runtime-bound rerun, 2026-11-04

After #810, the same pinned inputs were verified using the implementation KG
checkout and its Python interpreter at
`/Users/marcin/Library/Caches/pypoetry/virtualenvs/kg-microbe-aXSqUX8A-py3.10/bin/python`.
The command above was run with `--plan`, then without it, using the new output
`workspace/reports/edge-curation-20261103/mim-reuse-canary-review-810.json`.
The receipt has SHA-256
`81c1835ae7f82cf952db84f7d46c589cf827caf695f533b321ba43314fe49422`.
It records actual validator origins, the selected interpreter, and matching
source snapshots before and after execution. The partition remains 2,999 =
1,747 supported + 1,252 withheld, with 2,694 native review input hashes checked
and zero actual KG edges approved. Earlier receipts are preserved.
