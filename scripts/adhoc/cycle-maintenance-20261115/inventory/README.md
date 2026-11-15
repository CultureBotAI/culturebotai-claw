# Repository maintenance inventory helpers

Date: 2026-11-15. Related issue: [#1230](https://github.com/CultureBotAI/culturebotai-claw/issues/1230).

`capture_pr_audit.py --output-dir <new-private-durable-directory>` performs
read-only GitHub observations. Raw metadata may contain public author identities
and comments; inspect output before publication. Complete captures require
unique PR identity, head, base and draft agreement across paginated REST before
and after, check rows, and the independent GraphQL inventory. Acquisition drift
leaves an explicit incomplete receipt and a nonzero exit. The helper refuses
inventories over 100; it does not claim snapshot immutability.

`review_pr1197_mutations.py --worktree <exact-review-worktree> --output <directory>`
runs four paired baseline/mutation controls in fresh processes against the
reviewed issue-report implementation. Every baseline must pass; each mutation
must fail an intended selected test call with successful setup and teardown.
Missing anchors, imports, collection errors, skipped tests or unrelated failures
cannot count as killed mutants. It requires a new output directory. Source bytes
remain unchanged.

`package_inventory.py --audit-dir <retained-audit> --review-dir <retained-review>
--output-dir <new-directory>` packages only the exact recorded historical
inputs; it is not a generic review assessor. Every historical input hash is
verified before writing, including the original report supporting the archived
review claims. It also checks the historical inventories agree. Unknown inputs,
source/output aliases, symlink aliases and existing destinations are refused.
Generated packages retain the unchanged original summary separately from the
new repaired-helper metadata. Original evidence is never replaced.

The committed `inventory-and-review.json` remains the original historical
summary, SHA-256 `b6b63834eb203eef395ad73e7c6af376fe821a278c4cac21f2d2f449ecaaea83`.
Its original helper hashes describe those executed versions. The separate
`helper-repair-provenance.json` binds the repaired helpers, exact archived inputs,
35 initial regression tests and four successfully paired mutation cases. It
records the historical source unchanged; the complete historical 753-test review
was not rerun. After extending the no-write controls to the two retired review
packagers, the focused suite passed 41 tests; four-wrapper verification is
recorded separately in the archive. Existing receipts are retained
unchanged rather than relabelled as a later execution.

`verify_helper_repairs.py --audit-dir ... --review-dir ... --worktree ...
--evidence-dir <new-private-directory> --receipt <new-file-beside-helper>` repeats
the bounded offline verification and creates a fresh public-safe receipt. Keep
detailed logs and child bytecode caches in the private evidence directory.

Issues [1263](https://github.com/CultureBotAI/culturebotai-claw/issues/1263),
[1264](https://github.com/CultureBotAI/culturebotai-claw/issues/1264),
[1265](https://github.com/CultureBotAI/culturebotai-claw/issues/1265) and
[1266](https://github.com/CultureBotAI/culturebotai-claw/issues/1266) record these
confirmed repairs. The four historical review packagers are separately retired
as described in [archive/README.md](archive/README.md). These records grant no
runtime or merge authority. Recheck current heads, bases, checks and complete
queue before any authorized admission.
