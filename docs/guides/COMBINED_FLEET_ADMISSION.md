# Combined fleet admission candidate

This candidate composes the existing independent registration proposals; it
does not claim their deployment. The composition retains the historical DUF
cycle declaration, Edge admission, all three newcomer source manifests and
their immutable bootstrap pins. The source work is attributed to:

| Proposal | Reused head | Bootstrap source |
|---|---|---|
| [Cofactor #1056](https://github.com/CultureBotAI/culturebotai-claw/pull/1056) | `d1ac875d7037d059a7bc97429480ae01eea9f2f9` | `5790569efd881bd8bca82a04ea278cc462c0c2c8` |
| [Assay #1072](https://github.com/CultureBotAI/culturebotai-claw/pull/1072) | `3cb87b411bc4ebc6c91a45bc48848361e713ebe2` | `89bfcebaee8a0fcf99055b2acd1709abb64f8666` |
| [Scaleup #1074](https://github.com/CultureBotAI/culturebotai-claw/pull/1074) | `f006a24a4ff4164498db0a222ff81d9b875d1616` | `88e719d5480d0008d6ce082510dcd066775f232b` |

The combined candidate consolidates the registration changes in those drafts;
it is not an instruction to merge all four overlapping proposals. No existing
PR is closed or merged by preparing this candidate. Select and refresh the
final release sequence through separately reviewed PRs before any merge.

Live GitHub inspection on 2026-11-10 confirmed the exact identities and current
default-branch revisions below. Each commit points to Git's canonical empty
tree `4b825dc642cb6eb9a060e54bf8d69288fbee4904`.

| Repository | Inspected main | Planned package and record inventory |
|---|---|---|
| CultureBotAI/CofactorMech | `3cb9d7a6ce527c84277daf6ddfd5cd56decbb4d1` | `src/cofactormech`; `data/cofactors/*.yaml` |
| CultureBotAI/AssayMech | `a85aea616168160ec7e5dc08e71f15b361455924` | `src/assaymech`; `data/assays/*.yaml` |
| CultureBotAI/ScaleupMech | `38f8157fc960299f2458f4916dd581ce1b5d0262` | `src/scaleupmech`; `data/scale_transfers/*.yaml` |

These are planned paths, not installed packages. The candidate enables only the
mandatory vendored-governance obligation. Every implementation capability is
disabled or explicitly not applicable. Current `taxon_links` declarations are
disabled because empty main provides no taxon-bearing slots to measure. Shared
serialization remains unverified, and the exact missing-artifact ledger retains
all 22 native obligations per newcomer. The LinkML enum, root configuration,
merge policy, embedding disposition and internal inventory include each member.

The corresponding scaffold heads inspected were Cofactor
`67e9124ac6941c0e103fa7eeb23373b28e5addbf`, Assay
`c01d6162d473f9a85ee64a0094b29dbb944cccba`, and Scaleup
`febb97f00f69f70c0278dd58c9fd1eb4b1f18753`. Their prospective
`.github/workflows/validate-strict.yaml` job is `validate-strict`, with
unconditional PR and `merge_group` triggers. The queue mappings do not claim
those workflows exist on main or activate remote queue rules.

Configure the new root variables only against identity-verified usable
checkouts. Empty-main clones cannot satisfy the planned package-path check;
leaving these roots explicitly unconfigured is the truthful local state until
scaffold adoption. Do not point operational roots at unmerged scaffolds merely
to make required-root validation pass.

## Public membership

ScaleupMech carries `tags: [exclude-from-public]`. The shared public-membership
projection removes it before serialization and aggregation while ordinary
inventory, governance and internal commands retain it. This policy changes no
GitHub repository visibility. See [public outputs](PUBLIC_FLEET_OUTPUT.md).

The unpublished candidate entry hashes are resealed for the current catalogue
and Scaleup's tag. Frozen source manifests and historical declarations are not
rewritten. `scripts/adhoc/compose_pending_fleet_admissions.py` records the
composition and refresh procedure. Its input heads are immutable; rerunning the
initial composition requires a clean pre-integration checkout.

## Release holds

The active scoped cycle lane admits only its exact protected cohort. The new
declarations cannot activate themselves against an older protected base. The
combined branch is a reviewable candidate, not a green release shortcut.

Scaleup is private. The existing public governance job cannot anonymously clone
it; adding a private credential to candidate execution is not an acceptable
remedy. [Private prerequisite #1077](https://github.com/CultureBotAI/culturebotai-claw/pull/1077)
and [automatic audit #1082](https://github.com/CultureBotAI/culturebotai-claw/pull/1082)
remain separate reviewed dependencies. Their protected producer, App environment
configuration and live canaries are not installed or activated by this candidate.
The optional adapter retained from #1074 returns incomplete overall success
until trusted private verification finishes; it is not a gate waiver.

The previously proposed staged order was #1056, #1072, #1077, #1082, then #1074,
with exact-head refreshes between user-approved merges. Consolidating admissions
does not make that trust ordering disappear. A separately reviewed release
plan must reconcile these overlapping PRs and establish protected audit support
before admitting the private consumer. Do not merge this combined candidate
while private access or trusted activation remains unresolved.

After scaffold adoption, verify default-branch artifacts and remove only the
completed admission-ledger entries. Capability promotion, any coordinated
shared-pin release, remote merge-queue activation and site deployment remain
separate gates. No fleet-wide re-pin or repository merge is initiated here.
