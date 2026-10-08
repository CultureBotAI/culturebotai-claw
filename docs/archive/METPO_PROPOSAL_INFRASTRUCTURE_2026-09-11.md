# METPO infrastructure survey — 2026-09-11

> Historical snapshot from 2026-09-11, archived on 2026-10-08 UTC. Fleet counts,
> repository states, and local evidence paths below describe the original survey.
> The aggregation/parser work later merged in [PR #548](https://github.com/CultureBotAI/culturebotai-claw/pull/548).
> Follow-up scope is tracked in [#385](https://github.com/CultureBotAI/culturebotai-claw/issues/385)
> and [#386](https://github.com/CultureBotAI/culturebotai-claw/issues/386).
> Use the maintained [METPO aggregation skill](../../.claude/skills/metpo-aggregate/SKILL.md)
> for current commands. The ignored workspace evidence named below is local provenance,
> not a required file in a fresh checkout.

Survey covers all nine repositories in `src/kg_microbe_fleet/fleet.yaml`, plus kg-microbe as the upstream integration reference. All local filename inventory searches used `rg --files --no-ignore --hidden`; focused infrastructure-reference searches also included ignored/hidden files. No downstream files were changed. Current GitHub default-branch trees were fetched read-only and compared to local file blob hashes. All discovered METPO proposal/skill/command artifacts match current remote defaults; differences in commit heads below concern other changes. kg-microbe uses `master`, all nine Mechs use `main`.

## Inventory

Counts exclude ROBOT directive rows and SSSOM headers. Cohorts are additive topics, not a latest-version-only sequence.

| Repository | Manifest proposal status | Cohorts | Classes | Properties | Mapping rows | Local HEAD | Remote default HEAD |
|---|---|---:|---:|---:|---:|---|---|
| culturemech | disabled | 0 | 0 | 0 | 0 | `75bc4b4df5e3` | `75bc4b4df5e3` |
| mediaingredientmech | not_applicable | 0 | 0 | 0 | 0 | `7c99dffa48cc` | `f1c2af1949e1` |
| communitymech | enabled | 3 | 130 | 22 | 0 | `6484dc26e981` | `92723c26f57d` |
| traitmech | enabled | 17 | 165 | 31 | 23 | `8017c3417e8b` | `50556be5167a` |
| proteintraitsmech | disabled | 0 | 0 | 0 | 0 | `f756db1b800b` | `18f9462b0d9d` |
| antibioticmech | disabled | 0 | 0 | 0 | 0 | `3830f412dffc` | `ce48c5003f6e` |
| cellstructuremech | disabled | 0 | 0 | 0 | 0 | `c9cc80786924` | `d3896f3abcea` |
| habitatmech | disabled | 0 | 0 | 0 | 0 | `2eccdcfbdeb5` | `b059e2984fa4` |
| naturalproductmech | disabled | 0 | 0 | 0 | 0 | `6aa2f69c9806` | `041282e4a8ea` |
| kg-microbe | outside fleet | 1 | 49 | 9 | 0 | `e74652bbbb47` | `e74652bbbb47` |

The fleet supplies **20 cohorts, 295 classes, 53 properties and 23 mapping rows**. CommunityMech has 15 unrelated working-tree changes; kg-microbe has 2. Proposal artifacts in both still match upstream default-branch blobs. The other surveyed working trees are clean.

## Existing skills and validators

- **TraitMech**: `.claude/skills/metpo-proposal/SKILL.md` (v1.1.0), four reference pages, `.claude/commands/ground-or-propose-metpo.md`; `scripts/verify_metpo_proposal.py`, `scripts/robot_validate_proposal.py`, `tests/test_verify_metpo_proposal.py`, and `just verify-proposal`, `robot-validate-proposal`, `audit-proposal-coverage`. Supports 11/12-column classes and 12-column properties, including optional related synonyms; five mapping sidecars contain 23 rows. Scope-A coverage is correctly cross-cohort. Its syntactic parent check accepts any recognized CURIE prefix, rather than resolving against a pinned release; it does not validate SSSOM semantics or cross-Mech allocation.
- **CommunityMech**: `.claude/skills/metpo-proposal/SKILL.md` (v1.0.0) and `.claude/commands/ground-or-propose-metpo.md`. Skill has hand-run width/coverage/parent and optional ROBOT checks. `tests/test_proposal_ids_are_unique.py` checks uniqueness across local cohorts and nonempty parents; `tests/test_cultivation_vocab_sync.py` checks cultivation vocabulary coverage. No dedicated proposal-validator script was found in the ignored-inclusive infrastructure inventory. The skill still describes one active cohort and older counts/ranges, despite three additive cohorts and newer allocation blocks.
- **CultureMech**: `.claude/commands/ground-or-propose-metpo.md` explicitly delegates proposal format to CommunityMech; no own proposal skill or cohort was found in the ignored-inclusive inventory. Existing grounding capability is therefore distinct from currently enabled proposal production.
- **MediaIngredientMech**: ingredient grounding command mentions METPO as a scope boundary; proposal capability is correctly not applicable to ingredient vocabulary.
- **ProteinTraitsMech, AntibioticMech, CellStructureMech, HabitatMech, NaturalProductMech**: no METPO proposal cohorts, dedicated skills, or proposal references were found in the ignored-inclusive local infrastructure searches; remote trees agree on dedicated artifacts. Disabled proposal states match the surveyed evidence.
- **kg-microbe**: `.claude/skills/metpo-proposal/SKILL.md`, generated curation/ROBOT templates under `mappings/`, source generator `scripts/extract_metpo_proposals.py`, `scripts/diff_metpo_proposals.py`, regeneration tests, and `tests/test_metpo_proposal_release_sync.py`. This is a separate proposer outside the nine-Mech fleet; integrate only through an explicit reconciliation step.

## Release reconciliation is a real outstanding gate

GitHub `berkeleybop/metpo/releases/latest` reported tag **2026-06-12**, published `2026-06-12T20:37:15Z`. Both TraitMech and kg-microbe local `data/raw/metpo.owl` declare that release. The OWL uses canonical IRIs **`https://w3id.org/metpo/NNNNNNN`**. Old kg-microbe skill ROBOT examples instead set `http://purl.obolibrary.org/obo/METPO_`; copying those commands creates a separate namespace and makes release checking misleading. Use `--prefix "METPO: https://w3id.org/metpo/"` for this release.

No TraitMech or CommunityMech proposed ID occurs verbatim in the release. This does **not** establish semantic novelty:

- TraitMech `scripts/finalize_metpo_2026_06_12_review.py:DUPLICATE_OF` explicitly identifies **17 upstream additions** overlapping existing reviewed local traits. All 17 local traits still appear in cohort v5 under proposed IDs. The release-review disposition is `DUPLICATE_NO_NEW_PRIMARY`: it prevents duplicate corpus records, but does not withdraw, accept, or rewrite proposal rows. Examples: proposed `METPO:1007655` flagellar arrangement versus released `METPO:1007005`; proposed `METPO:1007702` nitrogen fixation versus released `METPO:1005039`; proposed `METPO:1007703` denitrification versus released `METPO:1005038`. Other candidates cover flagellation, piezophily/tolerance, radiotolerance, metal tolerance, capsule, biofilm formation, enzyme activities and xerophily. These require a curator decision and an explicit proposal reconciliation ledger, not automatic deletion or re-ID.
- TraitMech v9 has **11 exact label overlaps** with released predicates. Its mapping sidecar deliberately declares `skos:closeMatch` because the proposed predicates allow causal-node domains instead of microbial organism domains. Equal labels cannot justify merging them; preserve domain/range, mapping strength, and comments.
- kg-microbe `docs/metpo/metpo_proposal_release_diff.md` records **31 classes and 4 properties already landed**, leaving **18 classes and 5 properties** pending. Blindly importing its entire ledger resubmits accepted content.
- kg-microbe and CommunityMech assign different meanings to overlapping proposed IDs, including `METPO:1007100` (biofilm-associated microorganism versus microbial community). A combined kg-microbe+Mech submission needs explicit coordinated allocation, not silent deduplication.

Detailed evidence is retained under `workspace/metpo/` in `survey_release_matches.json` and `survey_release_duplicate_candidates.json`. These are candidate-review records, not claims that all lexical/semantic matches are equivalent.

## Implemented upgrade in CLAW

The existing `/metpo-aggregate` skill is the common fleet entry point. Its
shared implementation remains `scripts/fleet_metpo_aggregate.py`; domain-specific
authoring skills stay with their repositories. The manifest's proposer membership
already matches observed artifacts, so it does not need changing.

The baseline merger returned exit 1 and **zero classes**: the 14 class files
split evenly between legacy and extended synonym schemas. The upgrade normalizes
`synonyms` to `exact_synonyms` only when the OWL directive agrees, and retains the
optional related-synonym column. It now gathers all 295 class and 53 property rows.

It also replaces first-row-wins deduplication with complete-row deduplication,
retains differing assertions for review, detects class/property reuse of an ID,
rejects malformed identity/header data and excess columns, reports enabled
proposers with no templates, and requires a strict majority for incompatible
shapes. Failures remain nonzero and diagnostics retain their incomplete status.

Every output run writes a provenance TSV, a JSON report with source fingerprints
and every manifest declaration, and a review `proposal.md`. Old generated templates
are removed when absent from a new run; old verdicts are invalidated before
replacing templates so a failed write cannot leave an old clean report certifying
new output. `--check` remains read-only. Outputs are not a transactional bundle;
an I/O failure exits 2 and requires rerunning into a usable output directory.

The updated skill removes historical counts/collision claims, explains the
supported schema extension and domain-specific mappings, and requires current
release reconciliation and canonical METPO prefixes before submission. The
review bundle is **mechanically clean**, with submission readiness **not assessed**.
No downstream curation files or skills were overwritten, IDs were not reassigned,
and nothing was published.

Run:

```bash
uv run python scripts/fleet_metpo_aggregate.py --check
uv run python scripts/fleet_metpo_aggregate.py --out workspace/metpo/review
```

The generated review is `workspace/metpo/review/proposal.md`. Mapping sidecars
and original cohort narratives remain at their source paths; they are not merged
into ontology assertions or silently discarded from the original repositories.

## Curation follow-up before a submission

1. Maintain one fleet aggregation skill/command and manifest-driven assembler in culturebotai-claw, while preserving repository-specific curation skills. Do not copy TraitMech-specific enum or citation rules across all Mechs.
2. Preserve all ROBOT columns and directives, all optional related synonyms, all SSSOM sidecars with metadata/provenance, all additive cohorts, source hashes, repository heads, and disabled-repository inventory. Fail closed on source errors and incompatible duplicate IDs.
3. State clearly that a mechanical aggregate is a review bundle. Submission requires release reconciliation, intentional duplicate-label review, resolved parent/domain/range references and ROBOT+ELK with canonical prefixes.
4. Track accepted, replaced, retired and pending proposal dispositions in a machine-readable ledger before filtering rows. Include the 17 known TraitMech candidates in the first review queue. Keep kg-microbe separate until its accepted rows and cross-source ID collisions are resolved.

Raw provenance under `workspace/metpo/`: `survey_details.json` (local inventories/counts/dirty paths), `survey_remote.json` (remote heads, discovered files and blob comparisons), and `survey_reference_files.json` (ignored-inclusive content-reference inventory).
