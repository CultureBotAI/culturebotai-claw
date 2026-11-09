# Private Scaleup governance receipt prerequisite

This is dormant plumbing for one private repository, `CultureBotAI/ScaleupMech`.
It does not replace the public fleet audit, register Scaleup, enable its merge
queue, or make its onboarding merge-ready. The existing public audit is unchanged.
That audit cannot anonymously clone Scaleup; adding a private token there would
put private Git objects in the same workspace as candidate code. Missing private
access remains an unsatisfied full-fleet gate, never a successful skip.

## Protected setup and activation decisions

The user decides whether to merge this prerequisite. Before the first manual
run, an administrator must configure all of the following; this PR creates none
of them and does not request broader local OAuth permissions:

1. A GitHub App installation authorized to read repository contents in
   `CultureBotAI/ScaleupMech`. Supply its real numeric App ID; availability of a
   suitable installation has not been verified. Metadata access is implicit.
   The workflow requests an installation token restricted to Scaleup and
   `contents: read`; it verifies the returned installation can see exactly the
   allowlisted repository ID. No write permission is requested.
2. The claw environment `scaleup-private-audit`, with **custom deployment branch
   rules**, exactly one rule of type `branch` named `main`, and no tag or wildcard
   rules. Configure this before adding any secret. The producer checks the
   environment metadata through the GitHub API before minting a token. Require
   trusted maintainers to approve deployment if desired; the exact branch rule
   remains mandatory even with reviewers.
3. Store `SCALEUP_AUDIT_APP_PRIVATE_KEY` only as a secret of that protected
   environment, and `SCALEUP_AUDIT_APP_ID` as an environment variable there.
   Do not put the key in repository-wide secrets, files, command arguments or
   URLs. Use the App key, not a personal access token. The pinned official token
   action revokes its short-lived token at job completion.
4. After the workflow and code are user-merged to protected `main`, manually
   dispatch `private-scaleup-audit.yaml` **on main**, supplying the exact public
   claw candidate commit as `subject_head`. The subject is validated and recorded
   but is never checked out or executed. Runs from other refs are denied by the
   protected environment and producer preflight.
5. Verify the actual uploaded receipt using the protected verifier described
   below. A successful manual run proves this bounded inspection only. A later,
   separately reviewed change must integrate isolated production and verification
   into the automatic full-fleet required check, define its trusted event/candidate
   binding and freshness, and make a deliberate protected cutover. That integration
   is **not implemented here**. Scaleup's onboarding remains held until it exists
   and all fleet-release requirements pass. Never configure this manual workflow
   as a substitute successful required check.

GitHub documents [installation token narrowing](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
and [environment protection rules](https://docs.github.com/en/actions/reference/deployments-and-environments).
The design avoids the [privileged workflow-run execution hazard](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
by implementing no candidate-triggered privileged continuation in this prerequisite.

## Bounded producer

The workflow is manual-only and uses an isolated runner with the protected
producer checkout, pinned actions, disabled checkout credentials and no shared
cache. It never checks out the private repository or candidate commit. It first
authenticates the public canonical manifest and payloads at immutable source
`88e719d5480d0008d6ce082510dcd066775f232b` against the closed packaged policy.
Then fixed GET-only GitHub API requests inspect the private main commit, the
known public governance targets and pin, using nonrecursive tree traversal.
Private tree objects, blobs and pin values stay in memory. It never reads
scientific records or executes downstream code. Main is read again after
inspection; a change invalidates the result.

The only uploaded artifact is `receipt.json`. Its closed schema permits the
allowlisted repository identity/ID, exact private main SHA, public subject SHA,
producer run/attempt/main SHA/App ID, public source ref, timestamps, known public
artifact IDs and expected hashes, and match booleans. It contains no private
paths, object lists, commit messages, file bytes, actual pin value or server error
body. All CLI errors are fixed codes, including malformed private input. No
private response is written to a checkout, log, cache or artifact.

`pending_bootstrap` is only the exact empty main
`38f8157fc960299f2458f4916dd581ce1b5d0262`, with every governed target and pin
absent. It records unfinished installation, not release completion. `installed`
requires all 22 applicable artifacts, executable modes and the exact source pin.
Any other state fails. A candidate cannot change the producer policy or select
another private repository, source pin or output field.

## Protected verification and limits

Run verification only from an isolated trusted checkout of current protected
claw main, with the matching installed package, not from candidate code or a
candidate-populated environment. A checkout check cannot make a previously
executed Python interpreter trustworthy. Supply a read-only public Actions token
through `GH_PUBLIC_READ_TOKEN` and the configured real App ID through
`SCALEUP_AUDIT_APP_ID`; no private token is needed by the verifier.

```bash
uv run --no-sync python -m kg_microbe_governance.private_scaleup_audit verify \
  --trusted-root "$TRUSTED_CLAW_ROOT" --subject-head "$PUBLIC_CANDIDATE_SHA" \
  --run-id "$PRODUCER_RUN_ID" --attempt "$PRODUCER_ATTEMPT"
```

The verifier obtains current main from the authoritative GitHub API and requires
that exact SHA in both the clean canonical local checkout and the producing run.
It does not trust a local `origin/main` alone or infer executable equivalence from
a subset of files. **Any main advance invalidates earlier receipts.** It downloads
the artifact from the actual completed successful main-only workflow attempt,
checks GitHub's artifact digest, exact artifact name and single-file ZIP shape,
run/attempt/subject/producer identity, and timestamps. Receipts expire after at
most 15 minutes, cannot be future-dated, and cannot be passed as arbitrary local
JSON. Artifact redirects strip authorization and are restricted to known HTTPS
GitHub artifact storage hosts.

The module's injected test transports and supplied protected-SHA set are explicit
trusted-caller interfaces, not arbitrary external authority. Production CLI paths
obtain both from fixed endpoints. The future automatic verifier must preserve
that boundary, keep candidate code away from the producer runner, and recheck
current private main/freshness as required by the final gate contract. Manual
receipts here are not proof that private main remained unchanged after production.

Offline corruption tests and mutation controls exercise these boundaries. No live
App minting or end-to-end private producer run has been performed without the
external configuration above. Public prerequisite CI can validate the code; it
cannot establish live access, deploy this workflow, or satisfy the private fleet
release gate.
