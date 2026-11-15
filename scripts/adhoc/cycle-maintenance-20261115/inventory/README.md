# Repository maintenance inventory helpers

Date: 2026-11-15. Related issue: [#1230](https://github.com/CultureBotAI/culturebotai-claw/issues/1230).

`capture_pr_audit.py --output-dir <private-durable-directory>` performs read-only
GitHub observations. Its raw metadata may contain public author identities and
comments; inspect output before publication. It checks pagination completeness
and records before/after PR sets without claiming snapshot immutability.

`review_pr1197_mutations.py --worktree <exact-review-worktree> --output <directory>`
runs four fresh-process mutations in memory against the reviewed issue-report
implementation. The source bytes remain unchanged.

`package_inventory.py --audit-dir <retained-audit> --review-dir <retained-review>
--output-dir <directory>` creates the public-only summary and helper copies.
`inventory-and-review.json` binds original and packaged helper hashes, describes
packaging edits, and retains the initial15-PR inventory and review result.
Original evidence is preserved separately; these records grant no runtime or
merge authority. Recheck current heads, bases, checks and complete queue before
any authorized admission.
