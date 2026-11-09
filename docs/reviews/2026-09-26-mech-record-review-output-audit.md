# Mech Record Review Output Audit

- Date: 2026-09-26
- Scope: the 10 canonical Mechs in `src/kg_microbe_fleet/fleet.yaml`
- Checkouts: local Mech worktrees plus refreshed `origin/main` refs
- Absence searches: included ignored and hidden files via `rg --no-ignore --hidden --files` and direct `find` checks on each report directory

## Summary

Every canonical Mech now has both tracked Claude review skills on
`origin/main`:

- `.claude/skills/review-yaml-record/SKILL.md`
- `.claude/skills/review-yaml-category/SKILL.md`

Every `review-yaml-record` skill instructs the reviewer to write exactly one
UTC-timestamped Markdown artifact before the final response:

`reports/yaml_record_review/<YYYYMMDDTHHMMSSZ>-<record-stem>.md`

Every `review-yaml-category` skill likewise writes a UTC-timestamped cohort
artifact:

`reports/yaml_category_review/<YYYYMMDDTHHMMSSZ>-<category-slug>.md`

The record reports use this shared top-level structure:

```markdown
# YAML Record Review: <record label>

- Repository:
- Record:
- Started UTC:
- Finished UTC:
- Verdict:

## Target
## Validation
## Identity and Grounding
## Evidence
## Completeness
## Findings
## Recommended Edits
## Follow-up Checks
## Additional Notes
```

The category reports use this shared top-level structure:

```markdown
# YAML Category Review: <category label>

- Repository:
- Category:
- Selection Rule:
- Started UTC:
- Finished UTC:
- Verdict:

## Target Category
## Selection and Membership
## Validation
## Lump and Split Review
## Identity and Grounding
## Evidence Patterns
## Completeness Patterns
## Findings
## Recommended Edits
## Follow-up Checks
## Additional Notes
```

## Per-Mech Findings

| Mech | `origin/main` skills | Tracked record reports on `origin/main` | Local record reports | Timestamped locally | Report git state |
| --- | --- | ---: | ---: | ---: | --- |
| CultureMech | record + category | 3,429 | 3,429 | 3,429 | tracked |
| MediaIngredientMech | record + category | 2,680 | 2,679 `.md` + `manifest.tsv` | 0 | tracked, legacy non-timestamped filenames |
| CommunityMech | record + category | 33 | 33 | 33 | tracked |
| TraitMech | record + category | 0 | 0 | 0 | none generated |
| proteintraitsmech | record + category | 0 | 0 | 0 | none generated |
| AntibioticMech | record + category | 191 | 191 | 191 | tracked |
| CellStructureMech | record + category | 0 | 0 | 0 | none generated |
| HabitatMech | record + category | 366 | 366 | 366 | tracked |
| NaturalProductMech | record + category | 0 | 142 | 142 | ignored by `reports/` |
| TaxonMech | record + category | 0 | 10,858 | 10,858 | ignored by `reports/` |

No canonical Mech has committed category-review artifacts under
`reports/yaml_category_review/` yet. The skill support exists; the fleet just
has not retained any category review output there.

## CultureMech

The stale premise that CultureMech `main` does not have per-record review output
is resolved. After fetching, `origin/main` points at `2c881635f7`:

`Add YAML record review reports (#488)`

The local `main` worktree is clean and contains 3,429 tracked,
timestamp-conforming Markdown files under `reports/yaml_record_review/`.

## Persistence Gaps

Two Mechs create valid timestamped local outputs that git still ignores:

- TaxonMech has 10,858 local timestamped reports, all ignored by the
  repository-level `reports/` rule in `.gitignore`.
- NaturalProductMech has 142 local timestamped reports, all ignored by the
  repository-level `reports/` rule in `.gitignore`.

If those artifacts are meant to persist through PRs, these two repositories
need either a `.gitignore` exception for review reports or a report location
outside `reports/`.

MediaIngredientMech has the opposite problem: its report directory is tracked,
but the 2,679 Markdown files use the original record-stem filenames such as
`Glutaric_Acid.md`, not the new
`<YYYYMMDDTHHMMSSZ>-<record-stem>.md` convention. New reviews will be
timestamped because the skill is updated; only the existing artifacts are
legacy-named.

## Other Local State

The audit did not mutate any Mech worktrees. Three local Mechs currently have
uncommitted branch work:

- CommunityMech: untracked `references_cache/` files on
  `codex/yeast-adhesion-resveratrol-coculture`
- TraitMech: untracked Rst proposal/history/script files on
  `codex/add-rst-helicaseduf2290-system`
- CellStructureMech: modified generated pages plus untracked Rpd3L files on
  `add-rpd3l-complex`

PathwayMech is outside the canonical fleet manifest but also has the same
record/category review skills and 17 local record review reports.
