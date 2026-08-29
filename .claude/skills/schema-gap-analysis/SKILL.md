---
name: schema-gap-analysis
description: Canonical fleet schema-gap methodology. Resolve applicable repositories, schemas, and record globs from kg_microbe_fleet, then combine the shared procedure with each Mech's domain root classes and validators.
category: quality
requires_database: false
requires_internet: false
version: 2.1.0
tags: [schema, gap-analysis, cross-repo, fleet, audit]
reference-root: mech
---

# Schema gap analysis (cross-Mech reference)

This is the canonical general procedure. A Mech-local adapter may add scientific
root classes, validation extensions, or curation commands, but must not copy or
redefine the fleet membership or the general method.

This skill is diagnostic and analysis-only by default. It reads local schemas,
records, and source code; it does not install packages, rewrite records, modify a
schema, or invoke a network service. That is why `requires_internet: false` is
accurate. Turn an accepted remediation plan into a separately authorized change.

## When to use

Run the per-Mech operational version when:

- The schema and live data look drifted: tolerant project validators report clean while curation tooling is happily writing keys the schema doesn't declare.
- A new field is being added in code and you want to know whether the schema needs updating, the data needs migrating, or both.
- Onboarding: "is this YAML valid?" needs a more rigorous answer than "the project's custom validator says yes."

Each Mech may ship domain validation extensions. `linkml-validate` is the shared
structural ground truth this skill anchors on.

## Per-Mech configuration

Resolve the applicable repositories and verified schema/corpus locations from
the manifest rather than this skill:

```bash
uv run python -m kg_microbe_fleet list --capability schema_sync --format json
```

For the selected Mech, use its `schema_paths` and `record_globs`. Determine the
LinkML tree-root class from that schema and load any domain adapter declared by
the Mech. Repositories with multiple record shapes must validate every declared
glob against its corresponding root class; do not silently choose the first.

## Offline preflight

Use the validator already installed in the selected Mech's project environment.
Do not bootstrap `pip`, change dependency versions, or let an environment runner
resolve missing packages as part of an analysis. Those actions mutate the repo or
environment and may require network access.

```bash
test -x .venv/bin/linkml-validate || {
  echo "linkml-validate is not installed in this Mech environment" >&2
  exit 2
}
.venv/bin/linkml-validate --help >/dev/null
```

If this preflight fails, record the exact executable/import error as a blocker.
Use the Mech's documented, lockfile-backed environment setup only in a separate
authorized task; do not improvise a dependency pin during the gap analysis.

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

1. **Run the offline validator preflight** above. Stop and report if it fails.

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
   # Generic shape — use schema_paths and record_globs from the selected
   # manifest profile; derive RECORD_CLASS from the referenced schema.
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
   # that skip the curator. Adjust the bracketed filename to match the
   # canonical collection declared by the selected Mech's local adapter.
   grep -rnE 'open\([^)]*(mapped|unmapped)_ingredients\.yaml[^)]*["\047][wa][bt]?["\047]' \
     scripts/ src/ --include='*.py'
   ```

   Even with these calibrated greps, the first one (naive `datetime.now()`) can occasionally surface a filename/display call site that doesn't end up in validated YAML (e.g. report-generator scripts writing `"generated_at"` into a top-level JSON report). Read the line before classifying as a process-axis bug.

7. **Write a remediation plan; do not apply it in this analysis.** Group each
   proposed change by owner: schema, instance records, or generator/process.
   Include affected paths, counts, validation commands, migration/rollback needs,
   and any domain decision that requires review.

8. **Define acceptance checks for the later implementation.** A separately
   authorized fix should re-run `linkml-validate` over every declared corpus and
   reach exit code 0 with no errors, or explicitly document reviewed exceptions.

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
- **Don't propose fixing instance records with `sed`.** The remediation plan
  should name the Mech's curator/save module or local adapter so a later change
  preserves canonical YAML formatting and recomputes collection metadata such
  as `generation_date` and `total_count`.
- **Don't add overlapping fields without aliasing.** If a new field partially overlaps with an existing one across two classes (e.g. `cas_rn` on `ChemicalProperties` and `MappingEvidence` in MIM), make sure both classes declare it explicitly or factor a common slot.

## Cross-Mech invariants worth checking once per pass

- **Timezone-aware timestamps everywhere.** Every Mech writes `curation_history` / `mapping_date` / `last_modified` etc. The `datetime.now()` grep above catches naive uses across all Mechs uniformly.
- **CURIE pattern coverage.** Each Mech publishes its own prefix list (CHEBI / FOODON / METPO / NCBITaxon / kgmicrobe.* / cas: / mesh: / MICRO / BTO ...). When the schema's `^[A-Z]+:[0-9]+$` predates multi-prefix support, it'll reject `cas:50-99-7`, `mediadive.compound:foo`, `mesh:C012345`, etc. Broaden to `^[A-Za-z][A-Za-z0-9._-]*:[A-Za-z0-9._-]+$` (the pattern adopted by claw's SSSOM validator and TraitMech's seeder).
- **External CURIE prefix sets in `prefixes:`.** A pattern-valid CURIE that uses a prefix the schema's `prefixes:` block doesn't declare won't fail `linkml-validate` (LinkML doesn't enforce prefix membership), but it WILL fail downstream tools like `sssom validate`. Worth checking by hand.

## Pointers

- **Reference end-to-end pass**: MIM's `notes/schema_gap_analysis_2026-05-16.md` documents the six gap classes the skill turned up on its first run, plus the PR that closed each. Good template for a write-up after running the skill on another Mech.
- **Schema files and record corpora** — read `schema_paths` and `record_globs`
  from the selected manifest JSON object.
- **Custom validators** (intentionally tolerant) — discover the selected Mech's
  validator from its local adapter or repository code; do not infer its path
  from another Mech's layout.
- **Most common generator-drift sites**: any `scripts/aggregate_*`, `scripts/enrich_*`, `scripts/apply_*`, `scripts/auto_correct.py`, and any per-Mech curator module.
