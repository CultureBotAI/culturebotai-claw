# Integrate infrastructure admission with current-main payload evolution

The final readiness audit found PR 953 no longer mergeable after protected main
advanced from `c7485ddbd86dba34a02f94bc24b72ff69a8ee4b6` to
`081e9c8f44c5ce28849e162b7fecac1b3ba17ad7` through PRs 978 and 956.
The reviewed PR head remains `85a69ee2164a3c9e70e0ffd8a9c33038ab84d716`
with its five successful historical checks. Those checks do not establish the
new combined tree's correctness or mergeability.

A read-only `git merge-tree --write-tree --name-only HEAD origin/main`
identifies conflicts in:

- `src/kg_microbe_governance/cycle_release_audit.py`
- `tests/test_governance_cycle_release_audit.py`

PR 956 permits valid future canonical payload/digest revisions while preserving
the active release's exact historical authority, applicability and target
bytes. It updates the current backlog prompt and record-review guide. PR 953's
infrastructure admission still equates the current manifest and payloads with
its exact declared source snapshot. Selecting either conflict side alone
would discard required behavior: future source publication, or the bounded
EdgeMech admission and its actual-source binding.

Integrate current main with a normal merge on the existing PR branch. Keep the
historical DUF declaration and all historical snapshots immutable, retain the
single admitted source pin and exact infrastructure identity/capability limits,
and distinguish the admitted immutable data snapshot from later current payload
revisions. Only the already-approved digest evolution may differ; authority,
artifact identity, paths, modes, consumers and scope must still fail closed.
Preserve both test families and add interaction regressions before a separate
adversarial review and fresh exact-head CI. Do not repin downstream repositories,
force-push, or merge the PR as part of this repair.

The clean feature worktree was inspected before any source fix. The historical
final receipts remain retained; any new validation evidence uses new paths.
