# Reusable Mech baseline

The reusable baseline composes the existing skill catalogue, workflow contract
and vendored governance sources. It does not replace any of those authorities.
The [onboard-mech skill](../../.claude/skills/onboard-mech/SKILL.md) is the
entry point for inventory, canonical refresh, adoption and later updates.

## What is shared and what stays local

The baseline locks the complete canonical source inventory and its SHA-256
hashes. Adding, deleting or changing a canonical component makes its consistency
check fail until a reviewed refresh records that change. It is a versioned
composition, not a second directory of copied templates.

Every consumer explicitly decides whether to adopt, defer, or declare a component
inapplicable, with an evidence-based reason. A disabled fleet capability is not
permission to omit a component silently. Admission policy can seal a consumer's
capability declarations even after its native implementation advances; a template
candidate records this difference without changing that admission authority.

| Surface | Authority and adoption rule |
|---|---|
| Instructions and discovery | Real `AGENTS.md`, relative `CLAUDE.md -> AGENTS.md`, real `.claude/skills/`, relative `.agents/skills -> ../.claude/skills`; preserve native instructions |
| Shared skills | Render existing canonical templates; update only marked managed regions; retain native skills and local prose |
| Workflow and evidence schema | Existing packaged parent and schema, with explicit decision; a repository profile retains its own native bindings and applicability |
| Scientific schemas and records | Consumer-owned; never generated or rewritten by baseline adoption |
| History, provenance and record review | Existing governed artifacts plus native validation/writer/review commands; retained source pins govern copies |
| Native checks and CI | Consumer-owned commands and unconditional PR checks; add offline template drift validation using a published implementation revision |
| Governed infrastructure | Existing governance synchronization and release/admission APIs; baseline adoption cannot authorize a re-pin |
| Research, runtime and automation | Explicit deferred/adopted state; installing skills or a candidate profile does not start workers, loops, hooks or auto-merge |

The older [Mech standard](MECH_STANDARD.md) records historical measurements. Its
counts are not today's applicability evidence. Inventory the current published
consumer revision, installed native commands, checks and extensions first.
Private consumers use their separately declared identity/policy; their inclusion
in an adoption plan does not add them to the public fleet.

## Refresh and adoption

From the isolated CLAW checkout, validate or refresh the canonical composition:

```bash
uv run python -m kg_microbe_skills.template_cli check-baseline --source-root .
uv run python -m kg_microbe_skills.template_cli refresh --source-root . --apply
```

Refresh after committing reviewed canonical source changes. Inspect the resulting
source inventory and hash changes, version/migration implications, and consumer
impact in the same PR. Do not attribute uncommitted source bytes to a published
revision. Publish the implementation branch before consumers reference its full
commit. A published candidate is reviewable; it is not an approved release.

Create workflow/mech-template.json with this shape. `components` must contain
one decision for every name returned by the current baseline; omission is an
error. This example illustrates the fields rather than a complete decision set:

```json
{
  "schema_version": 1,
  "repository": "assaymech",
  "source_ref": "FULL_PUBLISHED_IMPLEMENTATION_COMMIT",
  "components": {
    "skill:review-open-issues": {
      "action": "adopt",
      "reason": "Native repository issue review uses this shared process.",
      "evidence": ["AGENTS.md", "justfile"]
    },
    "workflow:parent": {
      "action": "defer",
      "reason": "Native bindings and boundary activation require separate review.",
      "evidence": ["AGENTS.md"]
    }
  },
  "native_checks": [["just", "check"]],
  "extensions": ["AGENTS.md"]
}
```

The three actions are `adopt`, `defer`, and `not_applicable`; every decision
requires a nonempty reason and evidence list. An adopted skill may specify a
`target` under the real `.claude/skills/` tree. Native checks are argv arrays
recorded as evidence; the tool never executes them. Extensions name existing
consumer-owned paths to preserve. Run the repository's real commands separately.
For a separately governed private consumer, supply the tool's required measured
`native_identity` schema paths and record globs; the private policy still supplies
its fixed GitHub and package identity. Do not fabricate public membership.
The source ref is the full immutable implementation commit, independently of the
baseline's canonical-source revision and the consumer's governed payload pin.

To list the complete decision keys from a verified source checkout:

```bash
uv run python - <<'PYCODE'
from pathlib import Path
from kg_microbe_skills.template import check_baseline, component_names
print("\n".join(component_names(check_baseline(Path.cwd()))))
PYCODE
```

The consumer-owned workflow/mech-template.json selects components and records
native evidence. Its generated workflow/mech-template-lock.json binds the
configuration, source revision, composition and managed outputs. Preview first:

```bash
uv run python -m kg_microbe_skills.template_cli plan \
  --source-root . --target-root "$MECH_WORKTREE" \
  --config workflow/mech-template.json
uv run python -m kg_microbe_skills.template_cli apply --apply \
  --source-root . --target-root "$MECH_WORKTREE" \
  --config workflow/mech-template.json
uv run python -m kg_microbe_skills.template_cli check \
  --source-root . --target-root "$MECH_WORKTREE" \
  --config workflow/mech-template.json
```

Run these only after resolving the exact consumer identity and inspecting its
staged, unstaged and untracked changes. Use an owned isolated worktree. The tool
must refuse unmanaged conflicts and unexpected managed edits. First adoption of
an existing skill needs an explicit review of where canonical regions belong;
never delete native text to make the renderer pass. Dry runs and checks do not
write consumer files. Application stages and validates the full managed set.

Run native checks, compare scientific/source/site paths against the base, and
repeat the same plan to prove no-op behavior. For multiplied adoption, complete
one consumer canary, including hosted checks, before applying the remainder.
Keep receipts of exact source and consumer heads, plans, checks, preservation,
review findings and deferred obligations. Candidate PRs describe their dependency
order and retain existing governed pins until a separate release decision.

## Maintained update process

The canonical component maintainer owns its source change and the corresponding
baseline refresh. The adopter owns native applicability decisions and local
extensions. Changes to the catalogue, templates, workflow contract, schema,
vendored manifest or payloads trigger baseline consistency validation in ordinary
PR and merge-group CI. The existing fleet maintenance cycle runs the same check
and reports consumer adoption/drift where roots are configured.

A maintenance finding becomes a scoped update PR through
[cross-mech-sync](../../.claude/skills/cross-mech-sync/SKILL.md). A missing local
checkout is unknown coverage; a missing adoption config is unadopted; deferred
components remain visible. Neither is a successful deployment. Review changed
managed regions and native checks, re-canary changes that multiply behavior,
and publish exact dependency heads. Do not install a cron job or autonomous
loop to maintain this baseline.

For a source release or governed re-pin, use
[VENDORED_GOVERNANCE.md](VENDORED_GOVERNANCE.md) and the applicable admission lane.
Workflow profile changes additionally use
[evolve-mech-workflow](../../.claude/skills/evolve-mech-workflow/SKILL.md).
Running cycles retain their effective contract until a separately approved
boundary activation. This baseline grants no merge/release authority.

## Migration and rollback

Keep the prior config, adoption receipt and consumer commit. A changed region
set or new required component needs a reviewed migration; do not force a splice.
Preserve unmanaged prose, native skills, identifiers, schemas, records, sites and
source evidence. Roll back a candidate by reverting its exact scoped adoption
commit and validating with the prior published implementation/config. Do not
reset active checkouts. Governed pin rollback and runtime rollback remain their
own audited operations; a template revert does not perform either.
