# Reviewed invalid-CAS diagnostic dispositions (#1193)

The stable producer refuses invalid historical CAS identities by default. An
explicit `--cas-dispositions REQUEST.json --cas-dispositions-sha256 SHA256`
selection enables a separate diagnostic capability; it never validates an
invalid number or authorizes canonical retirement or release. Legacy mode and
partial options refuse this selection. Existing valid supplied-form CAS
preservation (#1192) is unchanged.

The closed request binds an authored claims document, two genuine current native
MIM scientific review bundles, their Markdown companions and complete source
input union. Both reviewers must independently assess every claim against the
same canonical table, current owner, evidence, native parser/schema and semantics.
The second reviewer must declare independent authorship and its basis. Native
parsing, required checks, exact target digests and explicit action/scope/hold
assessment dimensions are enforced. Extra source context may differ between
reviewers; all its exact bytes remain captured. A request digest or boolean is
not a review.

Each entry selects one complete historical row by one-based data position, the
current permanent owner/path/hash, and every invalid-check-digit CAS occurrence
in `object_id`, `other`, or `xref` as exact `{field, token}` objects. Malformed
syntax and valid CAS tokens are not eligible. The two actions are:

- `RETIRE_INVALID_CAS`: the object itself must be the invalid CAS. The corrected
  owner cannot retain it as primary, grounding, chemistry or resolving legacy
  identity. A pinned native source-correction endpoint is mandatory. The MIM
  consumer verifies that endpoint; this standalone diagnostic producer does not
  assert that it has verified the entire cross-root correction chain. Ordinary
  emission must not reintroduce the assertion.
- `RETAIN_INVALID_CAS_WITHHOLD`: retain the exact current owner and historical
  evidence under an explicit issue hold. An annotation-only row may have a valid
  CHEBI/NCIT object; the complete candidate row is withheld, never silently
  scrubbed or retired. Every selected invalid token must survive unchanged.

The ordinary generator determines current candidate labels and provenance; old
validation stamps remain in complete historical evidence and are not transferred
as new approval. After all ordinary and compatibility rows are emitted, the
selected capability rejects any additional invalid CAS identity or annotation
outside its exact held row set. This complete-candidate check is deliberately
limited to explicit disposition mode; default generation remains unchanged.

Candidate metadata carries `cas_disposition_capability` and the root-relative
`cas_disposition_request` path/hash. The generation manifest retains complete
claims/review provenance, exact historical rows, the full held candidate rows,
invalid tokens, mandatory `WITHHOLD`, and retired entry IDs. Immutable input
capture, all three output alias guards and terminal currentness apply to this
entire closure. MIM replay reproduces the same bytes and must enforce withheld
selection and genuine paired publication reviews before any canonical change.

The fixtures record seven actual historical rows and source-owner bytes with
hashes and original repository provenance. Native review reports and corrected
afterimages constructed by tests are explicitly synthetic contract evidence,
not scientific approval of the campaign.
