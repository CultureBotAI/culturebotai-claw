---
name: unmapped-inventory
description: Inventory every "unmapped / pending-curation" ingredient surface across the four repos (MIM, kg-microbe, CultureMech, CommunityMech) into a single report keyed by normalized name, with cross-source overlap analysis. Drives the "MIM as single source of truth" goal — surfaces what still needs to land in MIM, in priority order, and documents the lightweight upstream→MIM→downstream sync mechanisms.
category: cross-repo
requires_database: false
requires_internet: false
version: 1.0.0
tags: [mim, kg-microbe, culturemech, communitymech, unmapped, inventory, sync, single-source-of-truth]
---

# Unmapped Ingredient Inventory Skill

## Purpose

MIM is the **single source of truth** for ingredient → ontology mappings.
Every other repo (CultureMech, CommunityMech, kg-microbe) should consume
MIM's published SSSOM rather than curating independently. But each
downstream repo *also* maintains its own list of "still-unmapped"
ingredients — rows it found locally but couldn't resolve. Those lists
are MIM's curation backlog.

This skill walks all four repos, harvests every unmapped/pending
surface, and emits one unified inventory keyed by normalized name. It
tells you:

1. **How many unmapped items exist in total** across the system.
2. **Which names appear in multiple repos** (highest-priority MIM
   curation targets — fixing one row propagates to N consumers).
3. **What MIM still has to do** — both genuinely unmapped (`UNMAPPED_*`)
   and "half-mapped" (`kgmicrobe.compound:*` / `cas:*` placeholders).
4. **Where each row should be routed** for ingestion via the
   `ingredient-mapping` skill.

## Sources inventoried

| Source key | Path | Format | What it represents |
|---|---|---|---|
| `MIM:unmapped/` | `MediaIngredientMech/data/ingredients/unmapped/*.yaml` | per-ingredient YAML | Ingredients with no ontology hit; placeholder primary |
| `MIM:mapped/placeholder` | `MediaIngredientMech/data/ingredients/mapped/*.yaml` (filtered) | YAML where `identifier` starts `kgmicrobe.compound:` | Half-mapped — has placeholder, needs real CHEBI/NCIT |
| `MIM:mapped/cas_fallback` | `MediaIngredientMech/data/ingredients/mapped/*.yaml` (filtered) | YAML where `identifier` starts `cas:` | CAS-RN-only fallback (no CHEBI exists yet) |
| `kgm:metatraits/unmapped` | `kg-microbe/docs/metatraits/unmapped_compounds.tsv` | 4-col TSV | kg-microbe metatraits placeholders + edge counts |
| `kgm:mediadive/unmapped` | `kg-microbe/mappings/mediadive_unmapped_ingredients_to_curate.tsv` | TSV | mediadive-side unmapped |
| `culturemech:new-solution-ingredients` | `CultureMech/data/import_tracking/new_solution_ingredients_vs_mediaingredientmech.tsv` | TSV | Solution ingredients flagged as `NEW - Not in MediaIngredientMech` |
| `communitymech:ingredient_mapping` | `CommunityMech/CommunityMech/reports/ingredient_mapping.csv` (status=unmapped) | CSV | Per-community ingredients without a MIM mapping |

Adding a new source is a one-function addition to the script (see
`SOURCES` list near the bottom of `scripts/inventory_unmapped_ingredients.py`).

## Run it

```bash
just inventory-unmapped
# or:
python3 scripts/inventory_unmapped_ingredients.py
```

Outputs:

- `workspace/reports/unmapped_inventory.tsv` — every row, full detail
- `workspace/reports/unmapped_inventory.md` — bucketed summary +
  top cross-source overlaps + per-source breakdown + sync hints

## Reading the report

### Top of `unmapped_inventory.md`

```
Total rows:           1438
Distinct names:       1033
Cross-source names:    388  ← priority MIM curation targets
```

A row count > distinct count means duplication across sources, which
is what we want to know — those are the highest-leverage MIM fixes.

### "Top cross-source overlaps"

Each row in this table is a name observed in 2+ repos. Names appearing
in 3 sources (e.g. `atrop-abyssomicin C` in MIM:placeholder +
MIM:unmapped + kgm:metatraits) are the absolute top priority — one
MIM curation kills the placeholder *and* satisfies kg-microbe.

### "Per-source single-source rows"

Items that only one source flags. Lower priority, but still part of
MIM's mandate as the single source of truth — eventually MIM should
absorb every row here too.

## The sync plan

The skill enforces a **lightweight, file-based, manual-trigger** sync
model. There is no automation; every step is a deliberate human action,
because the failure mode of bad mappings is high (downstream consumers
get wrong CHEBI IDs).

```
   ┌─────────────────────────────────────────────────────────────┐
   │  Phase 1 — UPSTREAM HARVEST (this skill)                    │
   │                                                              │
   │  Each downstream repo maintains its local unmapped list     │
   │  (kgm metatraits TSV, mediadive TSV, CultureMech tracking,  │
   │  CommunityMech reports). When a new ingredient is observed  │
   │  but can't be resolved locally, it goes into that list.     │
   │                                                              │
   │  This skill harvests them all into one inventory.           │
   └────────────────┬────────────────────────────────────────────┘
                    │ unmapped_inventory.{tsv,md}
                    ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Phase 2 — MIM INGESTION (`ingredient-mapping` skill)       │
   │                                                              │
   │  Use `import_ingredients.py --source <X>` to feed each      │
   │  source into MIM's curation pipeline:                       │
   │                                                              │
   │   - kgm:metatraits     → --source kgm-metatraits            │
   │   - kgm:mediadive      → --source mim-queue                 │
   │   - kgm:unmapped       → --source kgm-unmapped              │
   │   - culturebotht       → --source culturebotht              │
   │   - culturemech:pending→ --source culturemech-pending       │
   │   - communitymech:unm  → --source communitymech-unmapped    │
   │   - MIM:placeholder/cas→ rerun any source that produced it  │
   │                          after a CHEBI release; the         │
   │                          resolver upgrades placeholders     │
   │                          when CHEBI hits become available.  │
   │                                                              │
   │  Resolver writes new YAMLs under                            │
   │  MediaIngredientMech/data/ingredients/{mapped,unmapped}/.    │
   └────────────────┬────────────────────────────────────────────┘
                    │ new MIM YAMLs
                    ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Phase 3 — PUBLISH (`publish-sssom` skill)                  │
   │                                                              │
   │  `just build-sssom`     → workspace/reports/...sssom.tsv    │
   │  `just review-sssom`    → release-grade audit               │
   │  `just publish-sssom`   → MediaIngredientMech/mappings/     │
   │                           ingredient_mappings.sssom.tsv     │
   │                                                              │
   │  This is the ONE artifact every consumer reads.             │
   └────────────────┬────────────────────────────────────────────┘
                    │ MIM SSSOM (committed to MIM main)
                    ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Phase 4 — DOWNSTREAM PROPAGATION (`cross-repo-sync`)       │
   │                                                              │
   │  - kg-microbe consolidator: copies MIM SSSOM →              │
   │    kg-microbe/mappings/ingredient_mappings.sssom.tsv,       │
   │    rebuilds kgmicrobe_unified_entity_mappings.sssom.tsv.gz │
   │  - CultureMech: needs sync recipe (TODO)                    │
   │  - CommunityMech: needs sync recipe (TODO)                  │
   │                                                              │
   │  After propagation, downstream's unmapped lists shrink —    │
   │  next inventory run reflects the reduction.                 │
   └─────────────────────────────────────────────────────────────┘
```

### Cadence

| Trigger | Phases to run |
|---|---|
| New downstream-repo unmapped list landed | 1 (inventory) |
| Quarterly curation pass | 1 → 2 → 3 → 4 |
| CHEBI release dropped | 2 (rerun import_ingredients.py to upgrade placeholders) → 3 → 4 |
| MIM YAMLs hand-edited | 3 → 4 |
| Audit / health-check | 1 (just to see drift) |

### Single-source-of-truth invariants

After phase 4 of every cycle, these MUST hold:

1. **Every CHEBI/FOODON/NCIT/UBERON/ENVO ingredient mapping that any
   downstream repo claims must trace to MIM's published SSSOM.**
   No downstream repo independently asserts mappings.
2. **Downstream "unmapped" lists are append-only between cycles** —
   they accumulate locally, are harvested by this skill, ingested
   into MIM, then drained when the next SSSOM publish lands.
3. **`kgmicrobe.compound:*` and `cas:*` primaries in MIM are
   transient.** Each one represents a known ingredient that doesn't
   yet have a CHEBI hit. They should be re-evaluated on every CHEBI
   release.

## Adding a new source

Open `scripts/inventory_unmapped_ingredients.py` and:

1. Add a loader function (returns `Iterable[Row]`):

   ```python
   def load_my_new_source() -> Iterable[Row]:
       p = SOMEROOT / "path" / "to" / "file.tsv"
       if not p.is_file():
           return
       with open(p) as f:
           reader = csv.DictReader(f, delimiter="\t")
           for r in reader:
               yield Row(
                   source="mynew:tag",
                   name=r["name_column"],
                   norm=normalize(r["name_column"]),
                   status="UNMAPPED",
                   current_id=r.get("id_col", ""),
                   extra={...},
               )
   ```

2. Append to the `SOURCES` list at the bottom.
3. (Optional) extend `import_ingredients.py` with a matching
   `--source mynew` loader so the inventory output flows back into
   MIM via the `ingredient-mapping` skill.

The `Row` dataclass has six fields and a free-form `extra` dict — keep
the per-source semantics inside `extra`.

## Files

| Path | Role |
|---|---|
| `.claude/skills/unmapped-inventory/skill.md` | This file |
| `scripts/inventory_unmapped_ingredients.py` | The harvester |
| `workspace/reports/unmapped_inventory.tsv` | Per-row inventory |
| `workspace/reports/unmapped_inventory.md` | Bucketed summary |

## Dependencies

- Python 3 + `pyyaml` only
- No internet, no DB
- Read access to all four repo checkouts (env vars
  `MEDIAINGREDIENTMECH_ROOT`, `KGMICROBE_ROOT`, `CULTUREMECH_ROOT`,
  `COMMUNITYMECH_ROOT` if non-default)

## Related skills

- `ingredient-mapping` — the source→resolver→emit pipeline that
  ingests rows from this inventory into MIM
- `publish-sssom` — the release lifecycle that propagates MIM
  curation to consumers
- `cross-repo-sync` — the downstream-side sync (kg-microbe
  consolidator + planned CultureMech/CommunityMech recipes)
- `kg-microbe-review` — diff MIM SSSOM vs kg-microbe consolidator
  output to confirm phase 4 actually landed
- `mapping-taxonomy` — reference for every status/verdict/flag
  vocabulary used by the inventory
