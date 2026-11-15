# PR1211 pending-dependency integration preparation

Date: 2026-11-15. Related issues: #1255 (retain the complete fixture union) and
#1277 (preserve the reviewed bounded CI timeout repair in the dependency).

The dated `metadata_prepare.executed.py.txt` archive preserves the exact helper
used for an ordinary no-commit integration of reviewed but **pending** PR1138
head `40788fd77a428d4226c2047c1a1d18661bdfef71` into owned PR1211 source
`553a6103c2275ce7f020f6c6519465323240aaa8`. Its dependency tree is
`51a37b10664f1e842f4866c7af10516890132066`; observed actual main was
`9a4b0b22ce6e9bed878d512be4597502e03ed98a`. This does not claim that PR1138 was
merged, released or deployed. Publication/admission requires independent review
and subsequent dependency/main/queue checks.

Helper inputs were explicit owned-root/lock-directory paths, expected HEAD and
the prepare action. Its emitted `merge-prepared.json` records that HEAD remained
unchanged, the only conflict was the generated baseline, and no commit, push or
hook override occurred. The helper uses the shared claw metadata lease only
for preparation or explicit staging; commits are performed separately with
normal hooks after that lease is released. The archive is retained evidence,
not a new operational command or source of authorization.

The baseline conflict retained version1.1.0 and candidate authorities. Its old
source_ref is provisional until the maintained generator authenticates the
subsequent actual combined-source commit; the resulting baseline is committed
separately. Both session-infrastructure and preparation documentation additions
were retained. The existing provenance-union helper verified all13 records
against immutable inputs, producing the unchanged fixture SHA256
`e25d489133fc0ce6b2a53c5ce8f00f0f07d3fab3528a314f28d962a56c9952d8`.
The incoming skills catalogue SHA256 remains
`05669853d850c1ddd134411ff5b26c8c083257fb5e22e2baf346336e28f3d6b1`.

The initial invocation in the pre-existing target environment stopped during
import because GitPython was missing, before lock acquisition or Git mutation.
The unchanged source then ran in an existing complete development environment;
no environment was synchronized or replaced. Private original source, failed
attempt observation, successful receipt and later validation evidence remain
in the durable owning work area. No inventory or expensive generation was
repeated merely to create this archive. No downstream/runtime action occurred.
