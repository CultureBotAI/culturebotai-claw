# Packager portability repair #710

V3 fails the actual reviewed squash tree because portable verification requires the historical implementation commit as an ancestor and reads its objects. V4 keeps those strict historical checks for author freeze/publication only. Portable verification instead requires every selected maintained SHA-256 and size, exact working bytes, and the current `HEAD` Git blob. The historical implementation and generation revisions remain unchanged provenance.

`control-results.json` records separate fresh processes: two v3 failures (real single-parent squash and depth-one clone), six passing v4 scenarios, and five detected mutations. The six scenarios exercise an identical-tree squash, a shallow clone with the feature object proven absent, refusal of changed working bytes, refusal of a mismatched current Git blob hidden by restored working bytes, refusal of a changed selected hash, and strict author historical checks. Each scenario also runs the retained 21 packaging controls; these repeated controls are not presented as distinct tests.

`probe_removed_ancestry_only.py` and its receipt/log separately show that dropping only the old ancestry check still fails the shallow consumer at `git show` of the absent historical object. All fixtures are disposable real Git repositories; no maintained repository, active evidence package, or GitHub state was modified by this author work.

`evidence-index.json` selects scripts, exact original/repaired source snapshots, patch, receipts, result JSON and logs. Copied mutant source files are reconstructable from the scripts and exact replacements. Bytecode caches and disposable Git repositories are excluded. Independent repair review and final package/head/queue review remain separate.
