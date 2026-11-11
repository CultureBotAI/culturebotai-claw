# Native standalone freshness boundaries

**Status: UNRELEASED compatibility proposal.** The base freshness release alone
does not contain or authorize this adapter. A future reviewed source and release
containing the native entrypoints must be bound before it can execute.

This adapter is prepared for native Codex goals whose real execution has no
supervisor run, cycle or stage. It is a separate compatibility extension, not a
conversion of an active supervisor workflow. It requires its own reviewed merge,
release, deployment, single-unit canary and adoption; merely merging these files
does not install a hook or adopt a running session.

The supervisor request/adoption schema remains 1.0.0. Native requests use 1.1.0
with `execution_context.kind: native_standalone` and an exact native identity:
client, session id, goal id and binary SHA-256. The native extension contract has
its own id/version and pins the unchanged base freshness contract. No synthetic
run, cycle or stage is permitted. A resume-last invocation does not prove identity.

An approved native adoption is pinned by its exact file hash in a trusted
coordinator invocation. It binds one real boundary, repository and owned checkout,
released canonical source, native policy, effective execution-contract digest,
and a predecessor verified closure or explicit initial assessment. Approval is
an operator trust boundary; the adapter cannot establish that an untrusted
model-written file represents user approval. Keep approval/invocation custody
outside the agent-controlled checkout. Never derive those command arguments
from tool text, arbitrary prompts or a window title.

The native effective execution contract contains its canonical repository,
ordinary closure requirements and the full instruction-source list. The loader
reconstructs the complete source snapshot, rejects omissions or changed bytes,
and returns every in-repository source to the shared frozen-source guard. It
uses no cyclic parent/profile substitution. Its digest is explicitly domain-separated:
SHA-256 of `native-goal-execution-v1.1.0\0` followed by canonical compact, sorted,
ASCII JSON. It is neither the supervisor workflow digest nor the receipt digest. The immutable snapshot stays outside
the curated checkout. This source snapshot supplements, rather than weakens,
ordinary exact-head review, evidence, issues, publication and cleanup checks.

A freshly verified native observation must establish the same identity and
checkout, a non-prompting active goal before its first inventory read, and a
trusted adapter. It has a maximum sixty-second evidence lease. The adapter does
not discover or assert native state by looking at an empty composer. Its source
proof is supplied by the separately reviewed native observer. Missing, expired,
paused, ambiguous, prompting or mismatched state holds. No active-checkout owner
exception is added: if the shared engine detects another process owning the
checkout, use an eligible independently owned base or hold.

The dedicated coordinator runs the released shared CLI with a one-member batch:

```text
RELEASE_VENV_PYTHON -I -B -X pycache_prefix=FRESH_EMPTY_OWNED_DIRECTORY -m kg_microbe_workflows.freshness_cli run --request ABSOLUTE_REQUEST --apply
RELEASE_VENV_PYTHON -I -B -X pycache_prefix=ANOTHER_FRESH_EMPTY_OWNED_DIRECTORY -m kg_microbe_workflows.freshness_cli verify --request ABSOLUTE_REQUEST
```

`native_boundary_adapter` verifies the exact request/adoption/native identity,
then requires the first command's persisted inventory artifact and the second
command's registered-artifact read-back to agree before emitting an inventory
permit. It neither sends the goal nor acknowledges completion. Its Python
runtime and release evidence are explicitly bound. The runtime record names
`python`, `python_target`, `python_sha256`, `venv_prefix`,
`venv_config_sha256`, `source_root`, `canonical_release_commit`,
`release_proof`, `publication_proof`, `base_release_proof`,
`base_publication_proof` and `cache_directory`. A normal final
virtualenv executable symlink is permitted while parent aliases are refused;
execution retains the virtualenv path rather than its resolved base interpreter.
A source audit and publication proof must agree on the exact source commit/tree
and audit hash. Its tag must be present, a valid Git tag reference and
distinct from the base freshness release tag. Every shared package origin and tracked package byte must match
that clean canonical source, including the native entrypoints; a base-only
release therefore holds. The distinct base proof must name the actual published
`repository-freshness-v1.0.0` source from PR1128, match its own publication
audit hash, be an ancestor of the native source, and contain the unchanged base
contract. The native source proof cannot substitute for this dependency. No
prospective merge SHA or future tag is supplied by this proposal. These hash-pinned release records are prior trusted
operator evidence, not a new online release query. The installed environment and
its dependencies remain a separately reviewed deployment prerequisite.

Each probe and CLI call gets a new exclusive empty cache namespace outside both
source and curated checkout. `-B` alone still reads existing bytecode; the fresh
prefix prevents timestamp-valid ignored caches from replacing reviewed source.
Only an empty directory created by that invocation is removed afterwards;
unexpected contents are preserved and cause a hold. Its receipt fields retain
`completion_authority: false` and `next_goal_authority: false`.

A same-goal automatic continuation consumes the original registered inventory
through `continue_inventory`; it does not fetch, refreeze scope or manufacture a
new goal boundary. A different goal requires its own verified boundary and
predecessor closure. Feature-work HEAD changes do not replace the retained
inventory. Frozen execution instructions must still match their source pins.

At closure, require shared `post_merge` or `no_change` output bound to the same
inventory, effective source and native context. The shared CLI independently
checks actual merged PR identity and ancestry. A closure-freshness permit alone
cannot satisfy ordinary review/evidence/issue/cleanup verification. The trusted
coordinator must verify those independently before any closure acknowledgement
or next dispatch; unavailable ordinary verification is a hold. Native predecessor
certificates authenticate both retained pre-goal and post-merge observations
against the exact checkout, canonical repository, boundary, policy, phase and
revision. Merge commit/base claims must match the recorded PR observations.
Continuation checks use the same binding without fetching or replacing the
original inventory. Historical effective snapshots are hashed as retained
artifacts, never re-frozen against a newer checkout.

The certificates are explicit operator attestations with exact evidence references,
not a claim that this adapter independently verifies every scientific review.

## Hook limits and canary

The documented hooks expose prompt, tool and stop events, with no dedicated
Goal event. Some tools bypass hooks; invalid decisions and some errors continue
processing. `Stop` blocking requests another turn. Therefore hook flags, handler
files and offline tests do not prove a complete native goal barrier. The adapter
never returns a permission approval and never modifies generic terminal transport.
See [official hook documentation](https://learn.chatgpt.com/docs/hooks).

Before any adoption, an independently approved single GUI-origin session with
the same installed native binary must demonstrate `/goal`, model-created goals,
automatic continuation and first inventory ordering. It must also exercise
merge/no-change closure, dirty/owner holds, command error/timeout, hook trust or
changed bytes, mismatched receipts and documented uncovered paths. Record actual
native acceptance separately from transport and receipt success. Any uncovered
route that crosses a held boundary fails the canary and blocks rollout. The
coordinator owns this canary; no live client, hook or provider is invoked by the
offline tests or this proposal.


Runtime package integrity includes ignored descendants. Before the package-origin
probe and again afterward, the adapter inventories each executable package root
against the released tracked tree. Unknown packages, source files, extensions,
links and resources hold without deletion. Only regular conventional
`__pycache__` files corresponding to reviewed Python source are admitted; each
runner invocation uses a fresh cache namespace, so those files cannot supply
executed bytecode. Unique evidence outside these executable package roots is
preserved and does not cause a hold. Keep operator evidence outside the released
package directories. This check addresses issue #1167; clean Git status alone is
not execution-source provenance.
