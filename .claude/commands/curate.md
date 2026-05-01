---
description: End-to-end curation pipeline orchestrator — inventory → import → publish → review → propose evidence
---

# /curate — full curation pipeline

You are running the standard MIM curation cycle. Walk the user through
these stages, executing each via the relevant skill or `just` recipe,
checking outputs before advancing, and stopping for confirmation
between stages that mutate MIM state.

## Stage 0 — Scope

Ask the user (one-line) which **source** they want to curate from. If
they pass it as `$ARGUMENTS` to `/curate`, use that. Valid values:

- `kgm-unmapped` — kg-microbe placeholders (`unmapped_compounds.tsv`)
- `kgm-metatraits` — kg-microbe metatraits (`special_chemical_mappings.tsv`)
- `mim-queue` — MIM curation queue (mediadive unmapped)
- `culturebotht` — CultureBotHT compound master + media
- `culturemech-pending` — CultureMech NEW-flagged solution ingredients
- `communitymech-unmapped` — CommunityMech unmapped rows

If unsure, run **Stage 1** first to see where the backlog is.

## Stage 1 — Inventory

```bash
just inventory-unmapped
```

Read `workspace/reports/unmapped_inventory.md`; surface the
cross-source-overlap names (highest leverage). State the per-source
counts back to the user. **Do not advance** without confirmation.

## Stage 2 — Dry-run import

```bash
python3 scripts/import_ingredients.py --source <chosen-source>
```

(no `--apply`). Report the resolver-tier breakdown (HIGH / MEDIUM /
FALLBACK_REGISTRY / UNMAPPED). Stop. Ask the user if the breakdown
looks right.

## Stage 3 — Apply import

```bash
python3 scripts/import_ingredients.py --source <chosen-source> --apply
```

Verify by counting new YAMLs in
`MediaIngredientMech/data/ingredients/{mapped,unmapped}/`. Echo the
count.

## Stage 4 — Propose evidence (optional)

For the new MAPPED records, propose PMID + snippet candidates:

```bash
python3 scripts/propose_evidence.py --top-occurrences 20
```

Direct the user to `workspace/reports/evidence_proposals/_summary.md`
for review. **Do not modify any MIM YAML on the user's behalf.** They
must paste-and-edit themselves.

## Stage 5 — Build + publish SSSOM

```bash
just build-sssom
/opt/homebrew/bin/python3.13 scripts/publish_sssom.py --apply
```

Show the row delta and validation outcome. Stop on any error.

## Stage 6 — Validate evidence (Phase 1 gate)

```bash
just validate-evidence
```

If `SNIPPET_NOT_IN_ABSTRACT > 0`: HALT. Surface the offending rows.
Curator must fix before publishing. Otherwise advance.

## Stage 7 — Sync kg-microbe

```bash
cd /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe
poetry run python scripts/consolidate_chemical_mappings.py
```

Then run the cross-repo review:

```bash
just kg-microbe-review
```

Report the diff classifications.

## Stage 8 — Commit

For each repo with changes (MIM, claw, kg-microbe), open a separate
commit. Use semantic commit messages referring to the source
(`Import N ingredients from <source>`). Push only on user confirmation.

## Failure handling

- Any non-zero exit code halts the pipeline; surface the error to the
  user and ask before retrying.
- Validate-evidence failure: do NOT auto-roll-back; let the curator
  see and fix.
- If the user interrupts mid-stage, leave artifacts in place — they
  can re-enter at any stage.

## Related skills

- `unmapped-inventory` (Stage 1)
- `ingredient-mapping` (Stages 2-3)
- `evidence-curation` (Stage 4)
- `publish-sssom` (Stage 5)
- `evidence-reference-validation` (Stage 6)
- `kg-microbe-review` (Stage 7)
