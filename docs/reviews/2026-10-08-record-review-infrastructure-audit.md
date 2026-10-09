# Record Review Infrastructure: Baseline And Adoption Contract

This is the pre-adoption inventory for the structured-review rollout. It is not
a claim that the rollout is complete or that any scientific record passes review.
The fleet scope is the 13 Mechs in CLAW main
`7e6c3eec34c203a74736c715e8eaebf7e60cd329`.

## Evidence Method

Repositories were resolved through `RepositorySettings`, their origin identities
validated, and main fetched under short per-repository metadata locks. Existing
working files were not switched, reset, stashed, or curated. Skills and tracked
paths were inspected at the exact revisions below, separately from local outputs.

Local file discovery included hidden and gitignored files with
`rg --files --hidden --no-ignore`; only Git internals, virtual environments,
Node dependencies, and Python bytecode directories were excluded. Report headings
were inventoried and representative output shapes retained for inspection. This
is a review-infrastructure inventory, not a scientific re-review of every report.
Local outputs can differ from main and can include in-progress work. Historical
reports are evidence of reporting conventions, not current issue disposition.

## Per-Mech Inventory

| Mech | Pinned main | Review surfaces and adoption considerations |
| --- | --- | --- |
| CultureMech | `0c789cd979bae23d0e7899bfffc65a46a3b98f5e` | Generic record/category skills, `review-recipes`, and `review-ingredient-concentrations`. Preserve P1-P4 rules, quantitative concentration claims, units and calculation basis, evidence access, per-claim statuses, and authoritative normalized inputs behind generated merges. Batch validators also emit JSON/HTML. |
| MediaIngredientMech | `a0d2c07811a4753230c03fe28982a622948cf7fc` | Generic record/category skills plus `review-ingredients` and semantic/mapping review workflows. Preserve local rules, ontology/label disagreements, exact chemical identity, purity distinctions, metrics, and cross-repository linkage limits. Existing Markdown includes both older and timestamped formats. |
| CommunityMech | `fa6783454fe1391dcae5195b002159a31b12cda8` | Generic skills plus `review-communities`; P1-P4 checks, citation/snippet support, organism scope, interaction edges, and media linkages. Validation success must not be conflated with scientific support. |
| TraitMech | `9c7ae6a992f89c25a194f5b61d7d85d0ce1f9f88` | Generic record/category skills with a local TraitRecord rubric: class versus instance, polarity, hierarchy, examples, and causal scope. A missing saved review is not a clean review. |
| ProteinTraitsMech | `9c563d320b0b39548daf119812a5e25298236b63` | Generic skills, `review-record-samples`, and `review-source-categories`. The sample skill permits session-only output. Preserve random seed, axis/category strata, population versus inspected counts, class/instance and family/parent distinctions, and seeder-level remediation ownership. |
| AntibioticMech | `0ce9bebaa01afd8df6fd34a1e682c1f56a3cc828` | Generic skills and structure/activity-specific sign-off. Preserve exact-structure identity, roles, mode of action, molecular-target evidence and review-queue limits. The queue is a checkpoint, not proof of scientific reading. |
| CellStructureMech | `49b8ed117bce10ce4b9768e7574901ea54612b6b` | Generic skills with component/composition, hierarchy/parthood, taxonomic distribution and figure/measurement checks. Saved reports vary substantially and sometimes mix scientific review with PR/curation progress. Preserve findings and corrections without confusing publication state with scientific validity. |
| HabitatMech | `893f468d11748cef519a6f1191f294af37559d04` | Generated habitats with decision-row, term-request, overlay, and source-inventory ownership. Preserve identity versus association, parent direction, source count units, MIxS context, and edge evidence. A generated record fix belongs to maintained inputs. |
| NaturalProductMech | `09f368bafc72088d713bc462f8832661eb60ddb6` | Generic skills and structure/producer/occurrence/BGC sign-off. No report under the generic per-record report directory was found at this pinned main or in the configured local root, including ignored files. This does not establish absence in old worktrees or external sessions. |
| TaxonMech | `a2f7afd3d2fe88b01962dd7531b1747e6f70d5d1` | Generic skills with nomenclature, lineage, strains, genomes and source attestations. Many local per-record Markdown reports are absent from the pinned Git tree. Preserve source-native counts and units; unlike counts must not be summed. New structured reports need explicit Git visibility. |
| PathwayMech | `2133fcb1b3d7e80d02f6ef646d814a8689f84eb2` | Native record/category skill wording includes graph/local references and edge evidence. Preserve taxon-local reactions, participants, direction, multi-record graph audits, and lump/split findings. Local reports and committed graph-review ledgers are distinct surfaces. |
| DUFMech | `3617561fac9e7bfff1f84f5be08543192ccda813` | Native `dufmech-review inspect/save/check`, YAML-frontmatter Markdown, `.claude` skills and `.agents` forwarding skills, frozen JSON-row targets, projections and overlays. Retain explicit scientific-review status and current-input digest binding. Its REVIEWED gate also requires a linked canonical history event; shared review saving must not bypass that gate. |
| CMMMech | `905388523b6e9184783989484896e4cc20297832` | Native `review-record`, per-record/per-round Markdown, reviewer independence, pre/post hashes, provenance-only limits, criticality authority/jurisdiction/edition, organism/substrate/condition scope, and distinctions among solubilization, removal and recovered product. Adapt the native skill instead of assuming generic curation-history adapters apply. |

Relevant pinned source paths include each repository's review skill entrypoints,
their local `curate-yaml-record/references/review-checklist.md` where present,
DUFMech's `docs/reviews.md` and `src/dufmech/reviews.py`, and CMMMech's
`.claude/skills/review-record/SKILL.md`. The inventory also includes specialized
skills and report-producing scripts: adopting only the similarly named generic
skills would leave active output paths outside the shared contract.

## Common Contract

The new authority is the self-contained LinkML `RecordReview` schema at
`src/kg_microbe_governance/artifacts/schema/record_review.yaml`. It describes
observations, not an executable plan or permission to mutate scientific data.

- Exact repository, Git base, committed versus working state, source-file hashes,
  record identity/path, optional row selector and declared semantic digest.
- Actual reviewer identity/kind and independence basis; real UTC start/end;
  review kind, completion, verdict, scientific scope and limitations.
- Explicit selection, population size, inspected targets, exclusions, sampling
  method/seed, and category lump/split/retain/defer decisions.
- Validation commands/results, actual exit codes, unavailable/skipped checks,
  evidence provenance and source locators, bounded absence searches, and conflicts.
- Shared assessment areas with domain-specific topics, prose, metrics, units,
  denominators and scale definitions. Local rubric scores are not silently
  comparable or averaged across different Mechs.
- Individually identified findings with normalized severity, preserved native
  rule/severity and mapping rationale, certainty, status, affected claims,
  evidence and maintained owner paths.
- Proposed actions, acceptance checks, generator ownership, dependencies,
  blockers, and explicit links to earlier findings or external issue records.

Machine-readable YAML is authoritative. Markdown is a deterministic view of that
same validated record. Each immutable bundle lives under
`reviews/structured/<UTC-timestamp-prefixed-review-id>/` and contains
`review.yaml` plus `review.md`. The saver refuses ignored output paths and
changed reviewed inputs; the reader includes ignored files and checks paired
artifact consistency. A schema-valid review still does not prove its scientific
claims or reviewer independence.

## Triage Semantics

The aggregation layer must enumerate the manifest, not a remembered repository
list. Missing roots, missing reports, invalid records, uncommitted-only evidence,
and old source hashes remain visible. An unreviewed repository is not green.

Issue keys are repository-scoped and intentionally assigned to the same issue;
similar prose is not a deduplication rule. A later clean review does not silently
close findings from an earlier one. Resolution/rejection/accepted-risk records
must explicitly reference the prior occurrence and retain their evidence and
reason. Conflicting branches of disposition must be reported as conflicts, not
ordered into a fabricated consensus. Cross-Mech grouping is by shared category,
explicit tags, ownership and dependencies, with every original occurrence retained.

No migration of old ad hoc reports is required. Keep them intact as historical
documents; do not infer structured findings, timestamps, severity mappings,
closure, or evidence from their prose. Fresh schema-valid records start the
normalized triage history. Native DUFMech history and scientific status gates
remain additional checks, not consequences of fleet review-schema validation.

## Rollout Acceptance

1. Exercise the schema against all observed domain patterns, including partial
   checks, sampled cohorts, CMM provenance-only reviews and DUF snapshot rows.
2. Test strict schema/semantic validation, exact-byte persistence, append-only
   behavior, symlink/ignore boundaries, and YAML/Markdown consistency.
3. Provide a shared CLI and manifest-resolved fleet aggregation with JSON,
   Markdown and tabular triage views, preserving lineage and unresolved work.
4. Adopt every applicable record/cohort skill and active record-report producer,
   without stripping local scientific rubrics or weakening native gates.
5. Vendor the canonical schema/validator/contracts through CLAW governance,
   enforce them in each Mech's actual CI, and verify report retention paths.
6. Verify every Mech on its published main after authorized publication, with
   passing normal CI and the governed fleet audit. Keep the original dirty
   CLAW checkout and unrelated Mech work untouched.

This document records requirements and inspected baseline evidence. The presence
of this checklist or a new schema is not completion of fleet adoption.
