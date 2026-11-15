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
| Persistent agent sessions | tmux on an explicitly identified host and socket; XMechBay owns host launch/control, CLAW records and verifies observations; Terminal windows are views |
| Research, runtime and automation | Explicit deferred/adopted state; installing skills or a candidate profile does not start workers, loops, hooks or auto-merge |

The older [Mech standard](MECH_STANDARD.md) records historical measurements. Its
counts are not today's applicability evidence. Inventory the current published
consumer revision, installed native commands, checks and extensions first.
New repositories can use the [preparation registry](PREPARATION_CANDIDATES.md)
before fleet admission. Their native paths come from the sealed declaration;
`native_identity` is refused. Legacy private consumers use their separately declared identity/policy; their inclusion
in an adoption plan does not add them to the public fleet.

## Persistent agent sessions

Tmux is the default for new persistent Mech agent sessions. In-process subagents
retain their existing lifecycle. Use the
[XMechBay fleet control contract](https://github.com/CultureBotAI/XMechBay/blob/main/docs/fleet-control-contract.md)
and its host launcher for persistent sessions; use the
[boss skill](../../.claude/skills/boss/SKILL.md) for separately owned task workers.
Do not create a second launcher or embed machine-specific session names in the
consumer baseline.

A session binding records the host, explicit tmux socket, session, window and
pane ID, plus the native agent's thread ID, PID, tty and actual checkout cwd.
Keep these private. A Terminal window or attached client is a view of that
binding, not another agent or the durable identity. Verify the native process
and thread independently: a pane PID can be a launcher shell, and a managed
agent can own its thread in a background server. See
[tmux observation](MECH_TMUX_OBSERVATION.md) before admitting a migrated binding
to monitoring. Old Terminal-only entries remain stale until that check passes.

Launch only on the selected existing server. On macOS, a server that needs
GUI-login access must originate in that login session; a missing socket is a
setup problem, not permission to create a replacement over SSH. Specify both
the server socket and tmux executable in host configuration. The launcher must
perform an explicit `cd` inside the new pane before starting the agent, then
verify its actual cwd; the server's inherited environment is not proof of it.
XMechBay's `mac-term.sh` supports `--tmux-socket`, `--tmux-session` and
`--tmux-bin`, with `tmux-open DIRECTORY COMMAND` for an owned new session and
its attached Terminal view, and `tmux-screen`, `tmux-status` and `tmux-paste`
for the selected existing session. Use the reviewed installed version's help
and ownership guards before dispatch.

For an authorized migration, stop only a verified idle client and resume its
saved exact thread in tmux. Preserve account/home, model, effort, sandbox,
approval policy, worktree, drafts, goals and pending decisions. For a managed
Codex thread, reconnect through its existing daemon without arbitrary `-c`
overrides or `--no-daemon`; those options can select embedded execution and
compete for the same thread. Do not remove a lock, fork the thread or stop a
shared daemon to bypass a competing-writer screen. A transient unused thread
must be persisted and verified before closing its client; report any failure
before choosing a different thread. Migration is not a new goal or permission
to answer a prompt.

The host controller owns launcher updates and private binding changes; the
component maintainer owns this onboarding guidance. Validate launcher changes
with mock transports, then verify one authorized live canary's thread, cwd,
screen and unchanged checkout before a migration batch. Report code readiness,
installed runtime and verified monitoring separately. This session standard
does not add a template component or change a consumer's governed source pin.

## Refresh and adoption

From the isolated CLAW checkout, validate or refresh the canonical composition.
A fresh or squash-merged checkout may lack the recorded canonical input commit;
first run the explicit source-object preparation command. It verifies the exact
canonical origin, fetches only that immutable commit when absent, and changes no
branch, worktree file, or executable code. Keep published source commits available
through their retained PR history; a missing remote object is a release blocker.
The check and fleet maintenance remain offline.

```bash
uv run python scripts/ensure_mech_template_source.py --source-root .
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

When running an installed package outside CLAW, set
`OPENCLAW_ORCHESTRATION_ROOT` to the validated orchestration checkout (or
`OPENCLAW_WORKSPACE` to its existing absolute shared workspace) before applying.
The lock namespace must be the same one other coordinating processes use. Do
not create a second runtime or relocate an existing workspace to satisfy a check.

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
