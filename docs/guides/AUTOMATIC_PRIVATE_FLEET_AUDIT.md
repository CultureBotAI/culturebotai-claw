# Automatic private governance audit

This extension keeps ScaleupMech private while allowing the existing required
`fleet-audit` check to cover its governance obligations. It is preparation for a
protected rollout. Committing this code does not configure an App, environment,
secret, or branch protection, and a local test is not a live private audit.

The parent workflow has two components and one required aggregate. Candidate
contract tests run without private access. Protected code audits public mains
and candidate completeness, uploading a closed public report. The report says
explicitly when private verification is still required. It cannot supply a
successful full-fleet verdict by omitting a root or inventing a local private
checkout. Historical canary and infrastructure states retain their existing
rules; an exact empty bootstrap records zero installed artifacts.

A separate default-branch `workflow_run: in_progress` producer waits for both
public components to succeed and for verifier setup to finish. It authenticates
the current parent event, source repository, run and attempt, protected main,
and tested checkout. For a PR, the source head and synthetic merge SHA are
separate fields; the merge must have exactly the current base and source head
as parents. Empty fork association metadata is resolved through authenticated
commit associations, with unique source-repository identity required. Stale PR
bases, changed heads, canceled runs, unknown events, truncated listings, and
attempt replay are refused. Merge groups require the exact live queue ref;
push, schedule, and manual runs must use current main.

Only the producer job enters the `scaleup-private-audit` environment. The
environment must permit the exact `main` branch only. It mints a short-lived
App token for `CultureBotAI/ScaleupMech`, with contents read only, after public
preflight. It executes protected code, reads the fixed governance policy, and
never executes candidate code, restores a shared cache, downloads candidate
artifacts, or publishes private record content. The output is the closed public
receipt already defined by the prerequisite, wrapped with parent/run bindings.

The aggregate authenticates the public component artifact through GitHub's
Actions API and digest, validates its closed schema and exact public/private
consumer union, then authenticates the producer run and artifact. The private
main observation timestamp is captured immediately after the last private ref
read. Acceptance is limited to 120 seconds after that observation and is checked
again after the last public metadata request. The receipt is an observation as
of that instant; it cannot prevent a later private push. Polling and API pages
are bounded, and only the newest matching producer attempt can supply evidence.

## Deployment order and configuration

The user decides every merge. Refresh branches and re-run exact-head checks as
protected main changes. The measured dependency order is:

1. [Cofactor onboarding/common admission framework PR1056](https://github.com/CultureBotAI/culturebotai-claw/pull/1056).
2. [Assay onboarding PR1072](https://github.com/CultureBotAI/culturebotai-claw/pull/1072), including its reviewed admission specification.
3. [Private manual prerequisite PR1077](https://github.com/CultureBotAI/culturebotai-claw/pull/1077).
4. [Automatic infrastructure PR1082](https://github.com/CultureBotAI/culturebotai-claw/pull/1082), with no Scaleup registration of its own.
5. [Scaleup onboarding PR1074](https://github.com/CultureBotAI/culturebotai-claw/pull/1074) with the explicit optional audit adapter.

Each Mech has separate scaffold and seed proposals. After the user merges a
scaffold, refresh and retarget its seed proposal to the actual protected main
and re-run its checks before a separate seed merge decision.

Before protected automatic code exists, the workflow retains the original
protected public-only audit. A candidate or protected manifest containing
Scaleup refuses this fallback. Public-only runs do not require App variables.
Installed public additions remain supported. Proposed empty public bootstraps
require specifications present in the installed protected admission framework:
`consumer_admission.compose` reads candidate Git blobs as data, without importing
candidate code. Such a completeness result does not activate an admission in
the deployed fleet. An unsupported prospective specification fails explicitly.

A maintainer must configure all of the following after reviewing the code:

- Environment `scaleup-private-audit`, with exactly one branch deployment policy,
  `main` of type `branch`; no tag policy or wildcard.
- Environment variable `SCALEUP_AUDIT_APP_ID` and environment secret
  `SCALEUP_AUDIT_APP_PRIVATE_KEY` for an App with contents read whose installation
  includes ScaleupMech. The workflow narrows the issued token to ScaleupMech and
  contents read; the installation may retain its other selected repositories.
- Public repository variable `SCALEUP_AUDIT_EXPECTED_APP_ID`. Its numeric value
  must equal the environment App ID. This separate nonsecret value is available
  to PR verification without exposing the protected environment.

Missing or mismatched configuration fails whenever private coverage is owed.
No App ID is hardcoded. Do not broaden an OAuth session to configure this path.
The private source policy is deliberately fixed to its reviewed immutable
source pin and exact artifact set; a future policy/pin change needs review.
The required queue context remains `fleet-audit` on ordinary PR and merge-group
runs. The producer's workflow-run check is not a replacement required context.

## Trust and validation limits

The required aggregate runs with `always()` but its first step requires both
component results to be `success`. The merge-queue validator accepts only that
exact bounded aggregate shape; arbitrary conditional required jobs remain
invalid. The verifier checks out the event revision for the queue's subject
contract but executes only the separate protected checkout. It has no private
credential.

Public component job results retain the existing workflow/branch-review trust
boundary. Job names alone do not prove commands if a candidate changes its
workflow. Artifact digests bind bytes and run provenance; they do not turn
candidate-controlled workflow configuration into cryptographic code authority.
Private isolation holds independently because the credentialed producer only
executes protected default-branch code and consumes candidate manifests as data.

Live activation still requires successful canary runs on the protected workflow,
including a fork PR and rerun, a merge-group event, private-tip change/refusal,
and missing configuration. Observe the exact empty-bootstrap result while the
private main still contains its initial empty commit. After the approved
scaffold merge, verify the installed-artifact state. Use planned, approved
merges for live head-change observations and retain offline corruption controls;
no record or governance corruption is required for a canary. No live activation
or private-token access is implied by the offline suite.

Primary GitHub references: [workflow-run semantics and security warning](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run),
[untrusted checkout boundary](https://docs.github.com/en/actions/reference/security/secure-use#mitigating-the-risks-of-untrusted-code-checkout),
[Actions artifact metadata](https://docs.github.com/en/rest/actions/artifacts),
and [environment branch deployment policies](https://docs.github.com/en/rest/deployments/branch-policies).
