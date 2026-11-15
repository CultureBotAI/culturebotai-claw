# Independent production-module review

Reviewed exact core commit `1d0034ebe4fea0f4371e82e211db13d1b5ec2253`.
No verified blocking finding in `pr_maintenance_remote.py`.

Scope: read-only inspection of the full remote module and its caller boundary,
plus focused tests and independent counterfactual probes. I authored the initial
focused tests but did not author the production module. This is independent
production review, not an assertion that the existing tests have a new author.
The companion reviewer covers policy/schema, parent 2.1, supervisor integration,
closure and issues 1259/1260 in depth.

The remote observer preserves complete bounded pagination, exact repository/head
identity, all-check status classification and a second open-inventory readback.
Zero checks, skipped-only checks, unknown contexts, failures and pending checks
cannot be green. Retained PRs are checked against the final inventory and their
checks are read again; terminal PRs cannot reappear there as reopened drafts.
The exact-head proof map binds merged dispositions to the independently verified
PR number, head, merged status and merge SHA. A no-change proof cannot substitute.
Source fixes require actual same-declared-repository issues and merged PRs; the
pure validator additionally restricts source identities to the consumer/canonical
Claw. Semantic correspondence of a source fix and issue remains reviewed artifact
evidence, not something the API state check can prove by itself.

Approval, independent review provenance, required CI, exact branch/base identity,
merge ancestry, publication and local/remote branch absence remain the caller's
existing closure responsibility. I traced that caller before accepting this
module's trusted verified-proof argument. This module does not manufacture a
review or merge authorization. No-change closure retains the caller's stronger
no-open-PR check and cannot verify a merged maintenance disposition with its empty
proof. The caller's review evidence remains a trusted checksum-bound artifact;
this change adds no cryptographic reviewer-identity attestation.

Worktree cleanup validates full porcelain inventory, exact receipt identity,
retained audit/manifest bytes, ignored-inclusive preservation evidence and each
retained file digest. It refuses present/symlinked/registered paths and protected
root ancestors. This is post-action evidence validation, not deletion authority
or a pre-deletion filesystem audit.

Validation: 118 focused tests passed without skips. Three independent mutations
were killed in fresh interpreters without changing source files: restore the
invalid union-level id selection (#1257), omit the terminal-reopen check (#1258),
and accept a foreign/no-change closure proof status. The repaired real GraphQL
query succeeded against public PR1138 at observed head
`6aeeb55105659cb740a0e7410eeb03a67855569d`, returning six complete contexts with
pending state. This is a query-shape check, not readiness or merge permission for
that PR. Issues1257/1258 are fixed at this reviewed source; no duplicate issue
was needed. Issues1259/1260 were read to delimit the companion integration review.

Production source and tracked worktree remained unchanged. No GitHub writes,
branch changes, live process/session inspection, runtime action or adoption
occurred. The committed helper logic and private outputs are retained in this
review directory; the parent should package the safe helper/proof with the final
PR. The helper takes explicit root/Python/output arguments and contains no private
paths, emails or operation history.
