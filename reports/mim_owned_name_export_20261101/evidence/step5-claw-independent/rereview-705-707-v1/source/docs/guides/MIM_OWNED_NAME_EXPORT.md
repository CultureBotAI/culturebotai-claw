# MIM owned-name export

The MIM builder applies the export policy adopted in
[MIM #669](https://github.com/CultureBotAI/MediaIngredientMech/issues/669#issuecomment-6558035777):
a preferred name owned by a different record is suppressed from a subject's
published `other` tokens. This preserves the source YAML. It does not reject a
scientific synonym, approve a mapping, or merge two ingredient records.

The full mapped-directory snapshot defines ownership, including records that
emit no mapping row. Rejected records transfer their preferred names through
their explicit representative; only an absent representative permits the
legacy identifier fallback. A token stays when the current subject is among
its owners. Comparison uses trimmed, casefolded text, matching native Rule K.

The builder filters before alias capping and checks later CAS/registry token
paths too. It emits three diagnostic artifacts:

- The selected SSSOM working copy.
- `suppressed_aliases.tsv`, with one row per subject/token pair, credited owners
  and source/evidence references. Repeated encounters are aggregated.
- `<working-copy>.manifest.json`, binding the generation inputs, producer and
  both output hashes.

`--suppressed-aliases-output` and `--generation-manifest-output` select companion
paths. All three outputs must be distinct files in the same directory. The
path guard rejects parent traversal, symlinks and case/Unicode-equivalent
destination spellings before writing, including on filesystems that would
otherwise distinguish those spellings.
The sidecar is header-only when nothing was suppressed; old entries are replaced.
The manifest distinguishes external validation from an explicit
`--no-validate` diagnostic run. That flag never skips ownership filtering,
artifact consistency or source snapshot checks.

The builder compiles its declared local dependencies from captured source
bytes, avoiding cached modules and timestamp-valid bytecode. It checks those
bytes and the producer file set again before publication. This is a process
drift check, not cryptographic attestation: use the source CLI, or a trusted
harness that also compiles the captured entrypoint source.

Publication uses the native lock and validated write transaction. The snapshot
and output beforeimages are checked again before replacement, and the final
artifact bytes are verified. The previous working copy may be an explicitly
declared stamp input; other input/output aliases are refused. A successful
no-op requires all three artifacts to match. Partial writes fail and retain a
recovery journal in `.sssom-artifact-journals`; sequential replacements are not
a single filesystem-atomic operation.

The legacy `publish_sssom.py` copies only a TSV and therefore refuses these
policy-marked candidates, including its same-TSV-hash path. Deleting a manifest
does not bypass that refusal. Canonical promotion needs a reviewed MIM guarded
writer that preserves the sidecar and manifest and applies the authorized row
plan. A complete diagnostic candidate is not authorization to replace the
canonical file or retire deferred Rule K allowances.

Tests cover native ownership parity, preserved YAML, alias origins, stable
sidecars, output aliases, source/preimage changes, partial failures and
nonzero validator exits, cached producer code and rejected CAS eligibility.
The two new helpers are included in the maintained type-checking gate.
See Claw #701–#707. No provider calls or paid
research are part of this policy.
