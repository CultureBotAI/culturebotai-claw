# Source-review helper provenance

This directory retains the helpers and public validation summaries for Claw PRs
1112, 1138, 1236 and 1243. Each numbered summary binds the exact reviewed head, current-main
comparison, test results, counterfactual results and original receipt hashes.
The original detailed evidence remains retained separately; no private workspace
paths, email addresses or session history are included here.

The PR 1112/1236 helper copies use an explicit `--review-tree` argument and require a detached
Git worktree at the original reviewed head. The original helpers used private
absolute-root guards. Each summary records the original and packaged SHA256 and
these packaging edits. The initial PR 1236 helper is retained deliberately: its
single alias fixture did not distinguish the mutation; the final helper used the
full existing test module, which did. The initial result is not counted as a
successful mutation check.

To reproduce a review, use an owned disposable detached worktree with the
repository's development environment. Pass that worktree to the relevant
`review_pr*.py` helper. The helper runs offline tests, temporarily changes only
that worktree and restores source in `finally`. It writes receipts beside the
worktree. The `package_review_pr*.py` helpers assemble the detailed review from
existing receipt files; their generated reports are working evidence and must be
inspected before any public publication.

`package_source_reviews.py --evidence-root "$OWNED_EVIDENCE_ROOT"` recreates these
public copies and summaries from the retained originals. It verifies original
helper hashes, parses the packaged Python and checks for private paths and email
addresses. Packaging does not rerun expensive validation or change an original
review receipt. The packaged helpers were syntax-checked and their `--help`
paths exercised after the edit.

These are code-only reviews. They grant no runtime installation, restart,
deployment, scientific publication or consumer-adoption authority.

The remote-verifier helpers copy the in-progress source packages and the test
file into a separate clean detached worktree, then run offline mutation controls.
They never edit the implementation worktree. `remote-verifier-summary.json`
records the tested source/test hashes, six killed mutations and the repaired
porcelain-completeness finding. Pass `--finding-issue-url` to the packager to bind
that finding's own-repository issue without rerunning the tests.

The PR 1138 rereview addresses issue 1252 without regenerating its archived
candidate. `1138/review_closeout.py` takes `--root`, `--python` and a new
`--output` directory; it compares the four original Git blobs, runs the offline
regressions, and invokes the committed GET-only release verifier. Existing local
canonical/main/historical Git objects are prerequisites. Its output preserves
initial fail-closed attempts separately from the final successful receipt.

The PR 1243 helpers take the same three arguments. `1243/review_source.py` runs
only synthetic tests and captures public GitHub metadata; `counterfactuals.py`
uses test-source overrides for count, duplicate-target and startup-retention
guards. They never inspect a live tmux endpoint or native session. Issues
1238–1242, 1244–1245 and 1249 define the reviewed source requirements.

`package_followup_reviews.py --reviews-root "$OWNED_REVIEWS_ROOT"` packages these
three helpers byte-for-byte and summarizes retained results. It records original
and copied hashes, checks public text for actual home paths and email addresses,
and does not rerun tests or live verification. The summaries distinguish source
acceptance from current CI/adoption readiness and classify the optional private
evidence skip. Original private evidence and earlier review worktrees remain
retained for evidence-preserving cleanup by their owner.
