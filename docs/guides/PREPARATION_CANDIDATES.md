# Preparing a new Mech before fleet admission

A repository can need reviewed native infrastructure before it is ready for
public fleet membership. `src/kg_microbe_governance/candidates.json` records
these **preparation identities** separately. It grants no deployed capability,
release status, public listing, runtime activation or merge permission.
`fleet.yaml` remains the only public/deployed fleet catalogue. Existing private
Scaleup policy remains separate; it cannot be copied to invent a new identity.

The registry is a closed, packaged declaration: exact key, GitHub identity and
repository ID, root environment variable, package/schema/record paths, inspected
initial main SHA, and a disabled or inapplicable decision for every current fleet
capability. Repository ID and initial SHA retain admission evidence; Git remote
validation still authenticates the owner/repository identity, not a live GitHub
ID lookup. Recheck live metadata before publication and before a later admission.
Paths describe the proposed native layout, while capability reasons describe
committed main. Implementations on a pending native PR are reported separately.
No candidate may overlap a fleet or separately governed private identity. The
control-plane key `claw` and canonical CLAW GitHub identity are reserved.

Use `RepositorySettings.get_candidate_target(key, root=exact_root)` for a
preparation checkout. Omitting `root` resolves only its declared environment
variable; missing, mismatched and nested worktrees fail closed. This classmethod
accepts a `Path` or string, and optional explicit `environ`. Normal `get_target`
and fleet commands do not discover preparation candidates. Do not add a candidate
to live controller configuration to make ordinary fleet commands find it.

## Canonical preparation and downstream canary

1. Inspect exact remote identity, repository ID, default head and native plan.
   Add a registry declaration and its tests. Record every capability decision;
   no capability can be enabled in this stage.
2. Commit canonical code/data and refresh the existing template baseline from
   that committed source. Publish both commits and verify the remote head before
   a downstream consumer pins them. The baseline covers candidate data and its
   packaged loader in addition to the governed standalone checker.
3. Resolve the isolated checkout through `get_candidate_target`, validate CLAW
   configuration, inspect Git state, and use the normal bounded repository lock.
   Dry-run governance synchronization first, review the planned targets, then
   apply the authorized candidate scope:

   ```bash
   uv run kg-microbe-governance sync --candidate --repository stressresponsemech \
     --target-root "$STRESSRESPONSEMECH_ROOT" --ref FULL_PUBLISHED_CLAW_SHA
   uv run kg-microbe-governance sync --candidate --repository stressresponsemech \
     --target-root "$STRESSRESPONSEMECH_ROOT" --ref FULL_PUBLISHED_CLAW_SHA --apply
   ```

   This uses the existing atomic, clean-worktree synchronizer. Candidate mode
   verifies the installed manifest and registry against the same immutable CLAW
   ref and composes only its universal governed artifacts. The candidate cannot
   choose artifact paths, checksums, source URLs or scoped artifacts. Ordinary
   sync remains fleet-only. Pin movement is separately reviewed, never inferred
   from template adoption.
4. Adopt the template using the registered identity and declared native paths.
   Do not provide `native_identity`; that is a distinct legacy private-policy
   extension. Review explicit component decisions and preserve native science.
5. In native CI use the standalone governed checker explicitly:

   ```bash
   python scripts/check_vendored_sync.py --candidate
   ```

   It obtains canonical manifest, registry and payloads from the exact pin,
   verifies actual Git origin, and rejects a supplied conflicting identity.
   Without the flag the candidate is unknown. Native/source/template checks and
   independent scientific and infrastructure review are additional obligations.
6. Retain evidence, issue/fix records, repeat-run no-op and canary preservation
   proof. Green candidate PRs are reviewable preparation, not deployment.

## Maintenance and later admission

`onboard-mech` owns this staged path. Existing `unify-skills`,
`evolve-mech-workflow` and template maintenance continue to own shared updates;
a candidate is not an alternative source of payloads. Re-pin through a reviewed
candidate PR when those authorities change. Changing the standalone checker
updates its ordinary governance digest but does not release it to existing
consumers or change their retained pins.

Later fleet admission is a separate decision. Recheck privacy/public availability,
committed native behavior, exact artifact completeness and capability settings.
Prepare the protected admission framework/declaration in dependency order, then
reconcile the fleet, governance consumer, merge policy, research enum, examples
and site only in the approved membership change. Remove the candidate declaration
in that same admission; duplicate identities fail. Update candidate-mode checks
to ordinary fleet mode and review the new pin. Candidate data is never loaded as
protected deployed-audit authority, and protected audit code is not bypassed.

StressResponseMech starts privately at README-only main
`d40c12971e9649a85c4989eb868b1d89828edffd`, repository ID `1458170146`.
The native proposal uses response systems in `data/response_systems/*.yaml` and
`src/stressresponsemech/schema/stressresponsemech.yaml`. The ammonia-producing
acidothermophile is an unverified research lead, not evidence for this admission.
