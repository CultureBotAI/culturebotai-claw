EdgeMech admission for #766/#767 previously failed the active DUF release gate
because that release freezes fourteen consumers and exact governance bytes.
This PR implements the separately authorized #960 transition as one additive,
versioned infrastructure admission. The original DUF declaration, payloads,
consumer rules and rollout permissions remain unchanged.

The declaration admits only `CultureBotAI/EdgeMech`, its exact fleet entry, its
reviewed governance data pin, and three explicit native-record test exclusions.
It distinguishes the exact empty bootstrap main tip (zero installed artifacts)
from complete installed-payload verification. Any bootstrap-tip change ends
the exception. Other membership, capability or payload changes fail closed.
Only vendored synchronization is enabled; native scientific, execution and
publication capabilities remain disabled or inapplicable.

Trusted audit code and the immutable declaration must come from protected main.
The separately declared data ref is read as data and verified against its actual
Git snapshot, supporting a squash merge without trusting candidate executable
code. Workflow preparation fetches only the one validated protected-declaration
ref. Candidate validation does not activate its own admission.

Shared artifact/native assertion contracts remain independently reviewable in
#962. Downstream implementations keep the unchanged immutable contract pin
`1b5391d083ba85ac94e5279c3cba25ac4fde243c`; occurrence identities and scientific
RecordReview authority are preserved. Companion site membership is
CultureBotAI/CultureBotAI.github.io#541. No fleet-wide repin, native curation,
embedding run, deployment or merge occurred.

Independent adversarial review filed and repaired #982, #984, #986 and #988.
Earlier #951/#952/#957/#959/#963/#964 dispositions remain recorded in the branch.
The policy/helper implementation was reviewed before its real canary. Dry-run
and no-op apply both verified 19 working and committed consumer artifacts plus
the pin, persisted independently rehashed receipts, made zero changes, and left
EdgeMech clean. The receipts explicitly report that trusted admission and
scientific capabilities are inactive.

Focused regressions, six mutation controls, Ruff and mypy passed. Full final-head
CI is pending the evidence push; no final full-suite pass is claimed yet.
[Validation and receipts](docs/reviews/edgemech-20261107/admission-validation.md)
and [policy design](docs/guides/INFRASTRUCTURE_ADMISSION.md) record scope and pins.
Storage, native exports and census evidence belong to CultureBotAI/EdgeMech#2.

Closes #960. Closes #982. Closes #984. Closes #986. Closes #988.

Keep this PR draft until its dependencies and final checks are reviewed.
Merging remains an explicit user decision.
