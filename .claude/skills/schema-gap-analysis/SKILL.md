---
name: schema-gap-analysis
description: Cross-Mech reference + bootstrap template for the schema-gap-analysis methodology. The operational, copy-paste-runnable version lives in each Mech repo's own .claude/skills/schema-gap-analysis/ — use this version for the conceptual framework or to bootstrap a new Mech.
category: quality
requires_database: false
requires_internet: false
version: 2.1.0
---

# Schema gap analysis (cross-Mech reference)

> **Day-to-day use**: invoke this skill from inside the Mech repo you're auditing. Each Mech ships its own customized version with paths baked in (no substitution needed):
>
> | Mech | Operational skill |
> |---|---|
> | CultureMech | `.claude/skills/schema-gap-analysis/SKILL.md` (companion to the deeper `audit-schema-gaps`) |
> | MIM | `.claude/skills/schema-gap-analysis/SKILL.md` |
> | CommunityMech | `.claude/skills/schema-gap-analysis/SKILL.md` |
> | TraitMech | `.claude/skills/schema-gap-analysis/SKILL.md` |
>
> **This file** is the cross-Mech reference — where the methodology lives once (so framework changes can be propagated by re-syncing the per-Mech copies) and where to bootstrap a new Mech.

## When to use

Run the per-Mech operational version when:

- The schema and live data look drifted: tolerant project validators report clean while curation tooling is happily writing keys the schema doesn't declare.
- A new field is being added in code and you want to know whether the schema needs updating, the data needs migrating, or both.
- Onboarding: "is this YAML valid?" needs a more rigorous answer than "the project's custom validator says yes."

Each Mech ships its own custom validator (intentionally permissive to keep CI green during active curation). `linkml-validate` is the stricter ground truth this skill anchors on.

## Per-Mech configuration

Use the row that matches the repo you're analysing. Substitute the placeholders into the commands below.

| Mech | `SCHEMA` | Tree-root class (`-C`) | Canonical collection(s) | Per-record YAMLs | Custom validator (tolerant) | Curator/save module |
|---|---|---|---|---|---|---|
| **CultureMech** | `src/culturemech/schema/culturemech.yaml` | `MediaRecipe` | `data/merge_yaml/merged_2026/*.yaml` | `data/normalized_yaml/<cat>/*.yaml` | `src/culturemech/validation/validator.py` | `src/culturemech/render_media_pages.py` (read-only); curator edits are direct |
| **MIM** | `src/mediaingredientmech/schema/mediaingredientmech.yaml` | `IngredientCollection` (curated/) / `IngredientRecord` (per-file) | `data/curated/mapped_ingredients.yaml`, `data/curated/unmapped_ingredients.yaml` | `data/ingredients/mapped/*.yaml`, `data/ingredients/unmapped/*.yaml` | `src/mediaingredientmech/validation/schema_validator.py` | `src/mediaingredientmech/curation/ingredient_curator.py` |
| **CommunityMech** | `src/communitymech/schema/communitymech.yaml` | `MicrobialCommunity` | _(no top-level collection — per-record only)_ | `kb/communities/*.yaml`, `data/isolates/**/*.yaml` | _(check `src/communitymech/validation/`)_ | _(check `src/communitymech/curation/` or per-script writes)_ |
| **TraitMech** | `src/traitmech/schema/traitmech.yaml` | `TraitRecord` | _(no top-level collection — per-record only)_ | `data/traits/<cat>/*.yaml` | _(none — schema is the only validator)_ | `scripts/seed_from_metpo.py`, `scripts/trait_causal_graph.py` |

> **Note on tree-root vs collection class.** MIM has both — a `IngredientCollection` for the aggregate `mapped_ingredients.yaml` / `unmapped_ingredients.yaml` files **and** a per-record `IngredientRecord` for `data/ingredients/<status>/*.yaml`. Run validation against both shapes (see Procedure step 3). The other Mechs publish only the per-record shape.

## Setup

LinkML is normally installed in the Mech repo's `.venv/`, but two recurring bumps:

**1. `pip` is sometimes missing from the venv.** Bootstrap it if needed:

```bash
.venv/bin/python -m ensurepip
```

**2. Version mismatch between `linkml` and `linkml-runtime`.** As of mid-2026 the typical Mech venv ships `linkml 1.9.3` and `linkml-runtime 1.10.0`; runtime 1.10 dropped `Format.JSON` which 1.9.x imports at module load → `linkml-validate` aborts on import with `AttributeError: type object 'Format' has no attribute 'JSON'`. Pin the runtime back to 1.9.x:

```bash
.venv/bin/python -m pip install "linkml-runtime>=1.9,<1.10"
.venv/bin/linkml-validate --help  # smoke test
```

Upgrading `linkml` to a release that ships with 1.10-runtime is the permanent fix; pinning the runtime is the simplest interim path. Setup is one-time per venv.

## The three-axis perspective

Every error `linkml-validate` reports fits one of these classes. Always ask "which axis owns the fix?" before patching.

### Axis 1 — schema

The schema (`$SCHEMA`) is wrong: a slot is missing, a pattern is too strict, or a name has drifted from what tooling has standardized on. Fix is to edit the schema; data and generators stay the same.

Signs:
- Hundreds-to-thousands of records fail the same way (data is consistent, schema is not).
- The field name in the error is one you can see in actual data files and recognize as canonical.
- The pattern in the error is older than recent design discussions (e.g. `^[A-Z]+:[0-9]+$` predating multi-prefix CURIE support — relevant especially in MIM and CultureMech).

### Axis 2 — instance records

The data is wrong: a typo, an unexpected key from a one-off script, a malformed value. Fix is to migrate the affected records.

Signs:
- A small number of records fail; most don't.
- The field name is suspicious (typo, abandoned experimental key).
- The value is malformed in a way that suggests human entry, not tooling (e.g. a single bad timestamp among thousands of well-formed ones).

### Axis 3 — process

The generator code is wrong: it emits structurally valid YAML that nonetheless violates the schema. Fix is to update the script(s); future runs are conformant, then optionally rewrite affected data.

Signs:
- Errors cluster by source tool (every record imported by `import_from_*.py`, every event written by an `accept_*` helper).
- A field that is otherwise correct is consistently in the wrong shape (naive vs. aware timestamps; lowercase vs. SCREAMING_SNAKE_CASE labels).
- `git blame` on the offending line in the generator points at a single commit that introduced the divergence.

## Procedure

1. **Make linkml-validate runnable** (see Setup).

2. **Validate canonical collection files**, if the Mech has any (MIM only, currently). For per-record-only Mechs, skip to step 3.

   ```bash
   # MIM only — adjust SCHEMA / -C / paths if you copied this to a Mech with a tree-root collection
   .venv/bin/linkml-validate \
     -s $SCHEMA \
     -C IngredientCollection \
     data/curated/mapped_ingredients.yaml \
     data/curated/unmapped_ingredients.yaml
   ```

3. **Validate per-record YAMLs**. Per-Mech smoke-test pattern:

   ```bash
   # Generic shape — substitute SCHEMA / RECORD_CLASS / RECORD_GLOB from the table above.
   SAMPLE=$(ls <RECORD_GLOB> | head -1)
   .venv/bin/linkml-validate -s $SCHEMA -C <RECORD_CLASS> "$SAMPLE"
   ```

   Example (TraitMech):
   ```bash
   SAMPLE=$(ls data/traits/environment/*.yaml | head -1)
   .venv/bin/linkml-validate -s src/traitmech/schema/traitmech.yaml -C TraitRecord "$SAMPLE"
   ```

   For corpus-wide validation:
   ```bash
   find <RECORD_DIR> -name "*.yaml" -print0 | xargs -0 \
     .venv/bin/linkml-validate -s $SCHEMA -C <RECORD_CLASS>
   ```

4. **Histogram the errors** so you see distinct issue classes, not thousands of per-record repetitions. Run against **every** collection/record source the Mech publishes — a gap that lives only in one collection is silently dropped if only the other is histogrammed.

   ```bash
   # Adjust the validation target to match what you ran in steps 2–3.
   LINKML_OUT=$(.venv/bin/linkml-validate -s $SCHEMA -C <CLASS> <TARGETS...> 2>&1)

   echo "$LINKML_OUT" | grep -oE "Additional properties are not allowed \('[^']+'" \
     | sort | uniq -c | sort -rn

   echo "$LINKML_OUT" | grep -oE "does not match '[^']+'" \
     | sort | uniq -c | sort -rn

   echo "$LINKML_OUT" | grep -oE "is not a '[^']+'" \
     | sort | uniq -c | sort -rn

   echo "$LINKML_OUT" | grep -c "is a required property"
   ```

5. **For each distinct class, decide the axis** using the heuristics above. Capture findings; don't change anything yet.

6. **Cross-check the process axis.** Generator drift is the biggest blind spot. These three targeted greps catch the most common patterns without producing noise. Run from the Mech repo root:

   ```bash
   # Naive datetimes (no timezone) — every datetime.now().isoformat call.
   # The `.isoformat\b` filter restricts to writes that produce ISO-8601
   # strings (the schema's `date-time` format).
   grep -rnE 'datetime\.now\(\)\.isoformat\b' \
     src/ scripts/ --include='*.py' \
     | grep -v "timezone"

   # Mech-specific: saves that drop collection metadata. Adjust the
   # bracketed collection-key (one of: ingredients|communities|media|traits).
   # Should be empty in current code.
   grep -rnE 'yaml\.dump\(\s*\{\s*["\047](ingredients|communities|media|traits)["\047]\s*:' \
     src/ scripts/ --include='*.py'

   # Mech-specific: direct WRITES to canonical curated collection file(s)
   # that skip the curator. Adjust the bracketed filename to match this
   # Mech's canonical collection(s) — see the per-Mech table.
   grep -rnE 'open\([^)]*(mapped|unmapped)_ingredients\.yaml[^)]*["\047][wa][bt]?["\047]' \
     scripts/ src/ --include='*.py'
   ```

   Even with these calibrated greps, the first one (naive `datetime.now()`) can occasionally surface a filename/display call site that doesn't end up in validated YAML (e.g. report-generator scripts writing `"generated_at"` into a top-level JSON report). Read the line before classifying as a process-axis bug.

7. **Decide and apply fixes.** Usually a mix: rename/alias the canonical slot on the schema, broaden patterns, add missing slots, fix the handful of malformed records, and patch the offending generators (timezone, action label, key name) so the next regeneration is clean.

8. **Re-run linkml-validate.** Exit code 0 with no errors is the target. Until then, document remaining divergences in a project memory file so they don't get rediscovered every session.

## Common gap classes seen across Mechs

| Error fragment | Likely class | Typical fix |
|---|---|---|
| `'X' is a required property` for thousands of records | Schema axis: slot is named wrong | Rename the slot in the schema to match what the data carries. **Note**: LinkML `aliases:` is descriptive metadata only — it does NOT make `linkml-validate` accept an alternate YAML key; rename is the actual fix. (MIM PR #19 — `ontology_id` → `identifier` — is the reference example.) |
| `Additional properties are not allowed ('X' was unexpected)` for thousands | Schema axis: slot missing from the schema entirely | Add the slot to the appropriate class |
| `Additional properties are not allowed ('X' was unexpected)` for a handful | Instance axis (typo) or process axis (one tool emits a wrong key) | Migrate records / fix generator |
| `does not match '<regex>'` | Schema axis if the regex hasn't caught up to legitimate values; instance axis if a single record is malformed | Broaden the schema pattern or correct the record |
| `is not a 'date-time'` | Process axis: generator emits naive datetimes | Replace `datetime.now()` with `datetime.now(timezone.utc)` |
| `Invalid value 'X' for enum Y` | Schema axis if Y is an organically growing vocabulary; process axis if a tool emits typos | Enumerate observed values OR convert the slot to `range: string` with a pattern, depending on whether the vocabulary is bounded |

## Anti-patterns

- **Don't patch the custom validator alone.** It's already permissive; the point of running `linkml-validate` is to find what the custom validator hides.
- **Don't silently rename a slot in the schema without also updating the consuming code.** `_check_required`, `_validate_*` helpers, dataclass generators, and tests still reference the old name. `git grep` the slot name before renaming.
- **Don't fix instance records with `sed`.** Round-trip through the Mech's curator/save module (see per-Mech table) so the canonical YAML formatting is preserved and collection-level metadata (`generation_date`, `total_count`, etc.) is correctly recomputed.
- **Don't add overlapping fields without aliasing.** If a new field partially overlaps with an existing one across two classes (e.g. `cas_rn` on `ChemicalProperties` and `MappingEvidence` in MIM), make sure both classes declare it explicitly or factor a common slot.

## Cross-Mech invariants worth checking once per pass

- **Timezone-aware timestamps everywhere.** Every Mech writes `curation_history` / `mapping_date` / `last_modified` etc. The `datetime.now()` grep above catches naive uses across all Mechs uniformly.
- **CURIE pattern coverage.** Each Mech publishes its own prefix list (CHEBI / FOODON / METPO / NCBITaxon / kgmicrobe.* / cas: / mesh: / MICRO / BTO ...). When the schema's `^[A-Z]+:[0-9]+$` predates multi-prefix support, it'll reject `cas:50-99-7`, `mediadive.compound:foo`, `mesh:C012345`, etc. Broaden to `^[A-Za-z][A-Za-z0-9._-]*:[A-Za-z0-9._-]+$` (the pattern adopted by claw's SSSOM validator and TraitMech's seeder).
- **External CURIE prefix sets in `prefixes:`.** A pattern-valid CURIE that uses a prefix the schema's `prefixes:` block doesn't declare won't fail `linkml-validate` (LinkML doesn't enforce prefix membership), but it WILL fail downstream tools like `sssom validate`. Worth checking by hand.

## Pointers

- **Reference end-to-end pass**: MIM's `notes/schema_gap_analysis_2026-05-16.md` documents the six gap classes the skill turned up on its first run, plus the PR that closed each. Good template for a write-up after running the skill on another Mech.
- **Schema files** (one per Mech) — see the per-Mech table.
- **Custom validators** (intentionally tolerant) — see the per-Mech table. The MIM one (`src/mediaingredientmech/validation/schema_validator.py`) is the most evolved example; refer to it when bootstrapping a Mech that doesn't have one yet.
- **Most common generator-drift sites**: any `scripts/aggregate_*`, `scripts/enrich_*`, `scripts/apply_*`, `scripts/auto_correct.py`, and any per-Mech curator module.
